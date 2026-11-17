"""Bounded UDP reassembly -> native C decoder -> FFmpeg -> local RTSP.
The two screen frames are independent. Reports actual received FPS separately
from the constant output clock (which repeats the last frame on loss).
"""
import argparse
from collections import deque
import io
import socket
import struct
import subprocess
import threading
import time
from PIL import Image
from codec import Codec

HEADER=struct.Struct('<4s7I')
CHUNK=1168

class Assembler:
    def __init__(self):
        self.session=None; self.frames={};self.last={};self.completed=set();self.retired=deque(maxlen=16)
    def feed(self, packet, now):
        if len(packet)<HEADER.size: return None
        magic,session,seq,pts,screen,total,offset,fps=HEADER.unpack_from(packet)
        data=packet[HEADER.size:]
        if (magic!=b'R3LP' or screen>1 or fps not in (24,30) or total<12 or total>40000
            or offset>=total or offset%CHUNK or len(data)!=min(CHUNK,total-offset)):
            return None
        if session!=self.session:
            # A session change is accepted only at fragment zero.
            if offset or session in self.retired: return None
            if self.session is not None:self.retired.append(self.session)
            self.session=session;self.frames.clear();self.last.clear();self.completed.clear()
        last=self.last.get(screen)
        if last is not None and seq!=last and ((seq-last)&0xffffffff)>=0x80000000: return None
        if last!=seq:
            self.frames.pop(screen,None);self.last[screen]=seq;self.completed.discard(screen)
        if screen in self.completed:return None
        frame=self.frames.get(screen)
        if frame is None:
            frame=(now,total,pts,bytearray(total),set());self.frames[screen]=frame
        start,length,stamp,buf,seen=frame
        if now-start>0.15 or length!=total or stamp!=pts:return None
        if offset in seen:return None
        buf[offset:offset+len(data)]=data;seen.add(offset)
        if len(seen)==(total+CHUNK-1)//CHUNK:
            self.completed.add(screen);self.frames.pop(screen,None)
            return screen,bytes(buf)
        return None

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bind',default='0.0.0.0');p.add_argument('--port',type=int,default=8001)
    p.add_argument('--sender',required=True,help='3DS IPv4 address; accepts only this sender')
    p.add_argument('--fps',type=int,choices=(24,30),default=30)
    p.add_argument('--rtsp',default='rtsp://127.0.0.1:8554/3ds')
    p.add_argument('--seconds',type=float,default=0)
    p.add_argument('--no-output',action='store_true',help='Receive and decode only')
    p.add_argument('--stats',help='Write per-interval CSV with actual received FPS and IP byte rate')
    a=p.parse_args(); decoder=Codec(); ass=Assembler(); lock=threading.Lock();stop=threading.Event()
    screens=[bytes(400*240*3),bytes(320*240*3)];counts=[0,0];errors=[0];received=[0]
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,1024*1024);sock.bind((a.bind,a.port));sock.settimeout(.2)
    def receive():
        while not stop.is_set():
            try:packet,addr=sock.recvfrom(1500)
            except socket.timeout:continue
            except OSError:break
            if addr[0]!=a.sender:continue
            received[0]+=len(packet)+28
            result=ass.feed(packet,time.monotonic())
            if result:
                sc,frame=result
                try:
                    width=400 if sc==0 else 320
                    if frame.startswith(b'\xff\xd8'):
                        with Image.open(io.BytesIO(frame)) as im:
                            if im.size!=(width,240):raise ValueError('Wrong screen size')
                            rgb=im.convert('RGB').tobytes()
                    else:
                        if struct.unpack_from('<HH',frame,4)!=(width,240):raise ValueError('Wrong screen size')
                        rgb=decoder.decode(frame)
                    with lock:screens[sc]=rgb;counts[sc]+=1
                except (ValueError,OSError):errors[0]+=1
    thread=threading.Thread(target=receive,daemon=True);thread.start()
    ff=None;stats=None
    try:
        if a.stats:
            stats=open(a.stats,'w',encoding='utf-8',newline='')
            stats.write('elapsed_s,top_fps,bottom_fps,ip_bytes_per_second,decode_errors\n')
        if not a.no_output:
            ff=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','warning','-f','rawvideo',
                '-pixel_format','rgb24','-video_size','400x480','-framerate',str(a.fps),'-i','pipe:0',
                '-an','-c:v','libx264','-preset','ultrafast','-tune','zerolatency','-pix_fmt','yuv420p',
                '-g',str(a.fps),'-bf','0','-f','rtsp','-rtsp_transport','tcp',a.rtsp],stdin=subprocess.PIPE)
        print(f'Listening UDP {a.bind}:{a.port}, sender {a.sender}; output {a.rtsp}',flush=True)
        start=report=time.monotonic();due=start;previous=[0,0];last_bytes=0
        while not a.seconds or time.monotonic()-start<a.seconds:
            now=time.monotonic()
            if now<due:time.sleep(due-now)
            due=max(due+1/a.fps,time.monotonic())
            if ff:
                with lock:top,bottom=screens
                canvas=bytearray(top+bytes(400*240*3))
                for y in range(240):canvas[((y+240)*400+40)*3:((y+240)*400+360)*3]=bottom[y*960:(y+1)*960]
                ff.stdin.write(canvas)
            now=time.monotonic()
            if now-report>=5:
                dt=now-report
                print(f'actual FPS top={(counts[0]-previous[0])/dt:.2f} bottom={(counts[1]-previous[1])/dt:.2f}; '
                      f'IP bytes/s={(received[0]-last_bytes)/dt:.0f}; decode errors={errors[0]}',flush=True)
                if stats:
                    stats.write(f'{now-start:.3f},{(counts[0]-previous[0])/dt:.3f},'
                                f'{(counts[1]-previous[1])/dt:.3f},{(received[0]-last_bytes)/dt:.0f},{errors[0]}\n')
                    stats.flush()
                previous=counts.copy();last_bytes=received[0];report=now
    except KeyboardInterrupt:pass
    finally:
        stop.set();sock.close();thread.join(1)
        if stats:stats.close()
        if ff:
            try:ff.stdin.close();ff.wait(timeout=3)
            except (OSError,subprocess.TimeoutExpired):ff.kill();ff.wait()

if __name__=='__main__':main()
