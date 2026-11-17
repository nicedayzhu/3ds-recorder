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

def compose(top,bottom):
    canvas=bytearray(top+bytes(400*240*3))
    for y in range(240):canvas[((y+240)*400+40)*3:((y+240)*400+360)*3]=bottom[y*960:(y+1)*960]
    return canvas

class Preview:
    """Optional direct view of the same decoded frames, without a player queue."""
    def __init__(self):
        import tkinter as tk
        from PIL import ImageTk
        self.photo_class=ImageTk.PhotoImage
        self.root=tk.Tk();self.root.title('3DS Live - Direct Preview')
        self.root.resizable(False,False)
        self.label=tk.Label(self.root,borderwidth=0);self.label.pack()
        self.root.protocol('WM_DELETE_WINDOW',self.close)
    def show(self,canvas):
        if self.root is None:return
        self.photo=self.photo_class(Image.frombytes('RGB',(400,480),bytes(canvas)))
        self.label.configure(image=self.photo);self.root.update()
    def close(self):
        if self.root is not None:self.root.destroy();self.root=None

class RelativeDelay:
    """Arrival-delay growth above the session minimum; not absolute device latency."""
    def __init__(self):self.session=None;self.pts=0;self.extended=0;self.minimum=None
    def sample(self,session,pts,now):
        if session!=self.session:
            self.session=session;self.pts=pts;self.extended=pts;self.minimum=None
        else:
            self.extended+=((pts-self.pts+0x80000000)&0xffffffff)-0x80000000;self.pts=pts
        offset=now-self.extended/1e6
        self.minimum=offset if self.minimum is None else min(self.minimum,offset)
        return max(0,(offset-self.minimum)*1000)

def write_frame(pipe,data):
    """Unbuffered pipes may perform a short write; never split the rawvideo clock."""
    remaining=memoryview(data)
    while remaining:
        count=pipe.write(remaining)
        if not count:raise BrokenPipeError('FFmpeg input closed')
        remaining=remaining[count:]

class Assembler:
    def __init__(self):
        self.session=None; self.frames={};self.last={};self.completed=set();self.retired=deque(maxlen=16)
        self.metrics=dict.fromkeys(('udp_packets','invalid_packets','late_packets','duplicate_packets',
            'reordered_packets','incomplete_frames','missing_fragments','expired_frames',
            'missing_one','missing_two','missing_many'),0)
    def discard(self,screen,expired=False):
        frame=self.frames.pop(screen,None)
        if frame is None:return
        missing=(frame[1]+CHUNK-1)//CHUNK-len(frame[4])
        self.metrics['incomplete_frames']+=1
        self.metrics['missing_fragments']+=missing
        self.metrics['expired_frames']+=int(expired)
        self.metrics['missing_one' if missing==1 else 'missing_two' if missing==2 else 'missing_many']+=1
    def feed(self, packet, now):
        self.metrics['udp_packets']+=1
        if len(packet)<HEADER.size:
            self.metrics['invalid_packets']+=1;return None
        magic,session,seq,pts,screen,total,offset,fps=HEADER.unpack_from(packet)
        data=packet[HEADER.size:]
        if (magic!=b'R3LP' or screen>1 or fps not in (24,30) or total<12 or total>40000
            or offset>=total or offset%CHUNK or len(data)!=min(CHUNK,total-offset)):
            self.metrics['invalid_packets']+=1;return None
        if session!=self.session:
            # A session change is accepted only at fragment zero.
            if offset or session in self.retired: return None
            if self.session is not None:self.retired.append(self.session)
            self.session=session;self.frames.clear();self.last.clear();self.completed.clear()
        last=self.last.get(screen)
        if last is not None and seq!=last and ((seq-last)&0xffffffff)>=0x80000000:
            self.metrics['late_packets']+=1;return None
        if last!=seq:
            self.discard(screen);self.last[screen]=seq;self.completed.discard(screen)
        if screen in self.completed:
            self.metrics['duplicate_packets']+=1;return None
        frame=self.frames.get(screen)
        if frame is None:
            frame=(now,total,pts,bytearray(total),set());self.frames[screen]=frame
        start,length,stamp,buf,seen=frame
        if now-start>0.15:
            self.discard(screen,expired=True);self.completed.add(screen);return None
        if length!=total or stamp!=pts:
            self.metrics['invalid_packets']+=1;return None
        if offset in seen:
            self.metrics['duplicate_packets']+=1;return None
        if seen and offset<max(seen):self.metrics['reordered_packets']+=1
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
    p.add_argument('--preview',action='store_true',help='Show decoded screens directly for player-delay comparison')
    p.add_argument('--stats',help='Write per-interval CSV with actual received FPS and IP byte rate')
    a=p.parse_args(); decoder=Codec(); ass=Assembler(); lock=threading.Lock();stop=threading.Event()
    screens=[bytes(400*240*3),bytes(320*240*3)];counts=[0,0];errors=[0];received=[0];jpeg_counts=[0,0];ltc_counts=[0,0]
    decode_max_us=[0]
    delay=RelativeDelay();lag_ms=[0.0];lag_max_ms=[0.0]
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
                header=HEADER.unpack_from(packet)
                lag_ms[0]=delay.sample(header[1],header[3],time.monotonic())
                lag_max_ms[0]=max(lag_max_ms[0],lag_ms[0])
                decode_start=time.perf_counter_ns()
                try:
                    width=400 if sc==0 else 320
                    if frame.startswith(b'\xff\xd8'):
                        with Image.open(io.BytesIO(frame)) as im:
                            if im.size!=(width,240):raise ValueError('Wrong screen size')
                            rgb=im.convert('RGB').tobytes()
                    else:
                        if struct.unpack_from('<HH',frame,4)!=(width,240):raise ValueError('Wrong screen size')
                        rgb=decoder.decode(frame)
                    with lock:
                        screens[sc]=rgb;counts[sc]+=1
                        (jpeg_counts if frame.startswith(b'\xff\xd8') else ltc_counts)[sc]+=1
                except (ValueError,OSError):errors[0]+=1
                finally:decode_max_us[0]=max(decode_max_us[0],(time.perf_counter_ns()-decode_start)//1000)
    thread=threading.Thread(target=receive,daemon=True);thread.start()
    ff=None;stats=None;preview=None;write_max_us=0
    try:
        if a.preview:preview=Preview()
        if a.stats:
            stats=open(a.stats,'w',encoding='utf-8',newline='')
            stats.write('elapsed_s,top_fps,bottom_fps,ip_bytes_per_second,decode_errors,jpeg_top,jpeg_bottom,ltc1_top,ltc1_bottom,'+
                        ','.join(ass.metrics)+',decode_max_us,arrival_lag_ms,arrival_lag_max_ms,write_max_us\n')
        if not a.no_output:
            ff=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','warning','-f','rawvideo',
                '-pixel_format','rgb24','-video_size','400x480','-framerate',str(a.fps),'-i','pipe:0',
                '-an','-c:v','libx264','-preset','ultrafast','-tune','zerolatency','-crf','10','-pix_fmt','yuv420p',
                '-g',str(a.fps),'-bf','0','-flush_packets','1','-muxdelay','0','-f','rtsp','-rtsp_transport','tcp',a.rtsp],stdin=subprocess.PIPE,bufsize=0)
        print(f'Listening UDP {a.bind}:{a.port}, sender {a.sender}; output {a.rtsp}',flush=True)
        start=report=time.monotonic();due=start;previous=[0,0];last_bytes=0
        while not a.seconds or time.monotonic()-start<a.seconds:
            now=time.monotonic()
            if now<due:time.sleep(due-now)
            due=max(due+1/a.fps,time.monotonic())
            if ff or preview:
                with lock:top,bottom=screens
                canvas=compose(top,bottom)
                if preview:preview.show(canvas)
            if ff:
                write_start=time.perf_counter_ns()
                write_frame(ff.stdin,canvas)
                write_max_us=max(write_max_us,(time.perf_counter_ns()-write_start)//1000)
            now=time.monotonic()
            if now-report>=5:
                dt=now-report
                print(f'actual FPS top={(counts[0]-previous[0])/dt:.2f} bottom={(counts[1]-previous[1])/dt:.2f}; '
                      f'IP bytes/s={(received[0]-last_bytes)/dt:.0f}; decode errors={errors[0]}; '
                      f'JPEG={jpeg_counts} LTC1={ltc_counts}; incomplete={ass.metrics["incomplete_frames"]} '
                      f'missing packets={ass.metrics["missing_fragments"]} late={ass.metrics["late_packets"]}',flush=True)
                if stats:
                    stats.write(f'{now-start:.3f},{(counts[0]-previous[0])/dt:.3f},'
                                f'{(counts[1]-previous[1])/dt:.3f},{(received[0]-last_bytes)/dt:.0f},{errors[0]},'
                                f'{jpeg_counts[0]},{jpeg_counts[1]},{ltc_counts[0]},{ltc_counts[1]},'+
                                ','.join(str(v) for v in ass.metrics.values())+
                                f',{decode_max_us[0]},{lag_ms[0]:.3f},{lag_max_ms[0]:.3f},{write_max_us}\n')
                    stats.flush()
                previous=counts.copy();last_bytes=received[0];report=now
    except KeyboardInterrupt:pass
    finally:
        stop.set();sock.close();thread.join(1)
        if preview:preview.close()
        if stats:stats.close()
        if ff:
            try:ff.stdin.close();ff.wait(timeout=3)
            except (OSError,subprocess.TimeoutExpired):ff.kill();ff.wait()

if __name__=='__main__':main()
