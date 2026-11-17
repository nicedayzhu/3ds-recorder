"""R6 paired UDP/FEC or legacy R3LP -> direct preview / local RTSP.
Reports received complete screen pairs separately from the output clock.
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
from pair_protocol import PairAssembler,config_packet

HEADER=struct.Struct('<4s7I')
CHUNK=1168
STATUS=struct.Struct('<4s16I')
FEEDBACK=struct.Struct('<4s6I')
STATUS_FIELDS=('sender_session','sender_elapsed_ms','sender_cap','sender_budget','sender_fps',
    'sender_encoded_top','sender_encoded_bottom','sender_sent_top','sender_sent_bottom','sender_errors',
    'sender_expired','sender_feedback','encoder_core_top','encoder_core_bottom','encoder_last_us_top','encoder_last_us_bottom')

def parse_status(packet):
    if len(packet)!=STATUS.size:return None
    values=STATUS.unpack(packet)
    if values[0]!=b'R3ST':return None
    result=dict(zip(STATUS_FIELDS,values[1:]))
    if (result['sender_fps'] not in (24,30) or not 400000<=result['sender_budget']<=result['sender_cap']<=1000000
        or result['encoder_core_top']>3 or result['encoder_core_bottom']>3):return None
    return result

def compose(top,bottom):
    canvas=bytearray(top+bytes(400*240*3))
    for y in range(240):canvas[((y+240)*400+40)*3:((y+240)*400+360)*3]=bottom[y*960:(y+1)*960]
    return canvas

class Preview:
    """Optional direct view of the same decoded frames, without a player queue."""
    def __init__(self,configure=None):
        import tkinter as tk
        from tkinter import ttk
        from PIL import ImageTk
        self.photo_class=ImageTk.PhotoImage
        self.root=tk.Tk();self.root.title('3DS Live - Direct Preview')
        self.root.resizable(False,False)
        self.label=tk.Label(self.root,borderwidth=0);self.label.pack()
        controls=ttk.Frame(self.root);controls.pack(fill='x')
        self.fps=tk.StringVar(value='30');self.rate=tk.StringVar(value='800000')
        ttk.Label(controls,text='FPS').pack(side='left')
        ttk.Combobox(controls,textvariable=self.fps,values=('30','24'),width=4,state='readonly').pack(side='left')
        ttk.Label(controls,text='B/s').pack(side='left')
        ttk.Combobox(controls,textvariable=self.rate,values=('700000','800000','900000','1000000'),width=9,state='readonly').pack(side='left')
        def apply():
            message=configure(int(self.fps.get()),int(self.rate.get())) if configure else 'No sender connected'
            self.status.set(message)
        ttk.Button(controls,text='Apply / 应用',command=apply).pack(side='left')
        self.status=tk.StringVar(value='Waiting for R6 sender / 等待设备')
        self.config_initialized=False
        status_box=ttk.Frame(self.root,width=400,height=44);status_box.pack(fill='x');status_box.pack_propagate(False)
        ttk.Label(status_box,textvariable=self.status,wraplength=400,justify='left').pack(fill='x')
        self.root.protocol('WM_DELETE_WINDOW',self.close)
    def show(self,canvas):
        if self.root is None:return
        self.photo=self.photo_class(Image.frombytes('RGB',(400,480),bytes(canvas)))
        self.label.configure(image=self.photo);self.root.update()
    def close(self):
        if self.root is not None:self.root.destroy();self.root=None
    def poll(self):
        if self.root is not None:self.root.update()
    def set_status(self,text,settings=None):
        if self.root is not None:
            self.status.set(text)
            if settings and settings[0] and not self.config_initialized:
                self.fps.set(str(settings[0]));self.rate.set(str(settings[1]));self.config_initialized=True

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
    p.add_argument('--set-fps',type=int,choices=(24,30),help='Request R6 capture FPS once connected')
    p.add_argument('--set-rate',type=int,choices=(700000,800000,900000,1000000),help='Request R6 fixed IPv4 B/s')
    a=p.parse_args(); decoder=Codec(); ass=Assembler();paired=PairAssembler(); lock=threading.Lock();stop=threading.Event()
    screens=[bytes(400*240*3),bytes(320*240*3)];counts=[0,0];errors=[0];received=[0];jpeg_counts=[0,0];ltc_counts=[0,0]
    decode_max_us=[0]
    delay=RelativeDelay();lag_ms=[0.0];lag_max_ms=[0.0]
    remote=dict.fromkeys(STATUS_FIELDS,0);feedback_at=[0.0]
    peer=[None];protocol=[None];request=[None];request_sent=[0.0];request_seq=[int(time.monotonic()*1000)&0xffffffff or 1]
    initial_request=[a.set_fps is not None or a.set_rate is not None]
    def configure(hz,bps):
        if protocol[0]!='paired' or not peer[0] or not remote['sender_session']:return 'Waiting for R6 sender / 等待 R6'
        with lock:
            request_seq[0]=(request_seq[0]+1)&0xffffffff or 1
            request[0]=(remote['sender_session'],request_seq[0],hz,bps,time.monotonic())
        return f'Requested {hz} FPS / {bps} B/s; waiting for device'
    def decode_frame(sc,frame):
        width=400 if sc==0 else 320
        if frame.startswith(b'\xff\xd8'):
            with Image.open(io.BytesIO(frame)) as im:
                if im.size!=(width,240):raise ValueError('Wrong screen size')
                return im.convert('RGB').tobytes()
        if len(frame)<8 or struct.unpack_from('<HH',frame,4)!=(width,240):raise ValueError('Wrong screen size')
        return decoder.decode(frame)
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,1024*1024);sock.bind((a.bind,a.port));sock.settimeout(.2)
    def receive():
        while not stop.is_set():
            try:packet,addr=sock.recvfrom(1500)
            except socket.timeout:paired.expire(time.monotonic());continue
            except OSError:break
            if addr[0]!=a.sender:continue
            received[0]+=len(packet)+28
            now=time.monotonic()
            pair_result=None
            if packet.startswith(b'R3ST'):
                status=parse_status(packet)
                active=paired if protocol[0]=='paired' else ass
                if status and status['sender_session'] not in active.retired and (active.session is None or status['sender_session']==active.session):
                    remote.update(status)
                    with lock:
                        if request[0] and (status['sender_fps'],status['sender_cap'])==request[0][2:4]:request[0]=None
                result=None
            elif packet.startswith((b'R3P2',b'R3F2')):
                pair_result=paired.feed(packet,now);protocol[0]='paired';peer[0]=addr;result=None
            else:result=ass.feed(packet,now);protocol[0]='legacy'
            active=paired if protocol[0]=='paired' else ass
            if initial_request[0] and protocol[0]=='paired' and remote['sender_session']:
                configure(a.set_fps or remote['sender_fps'],a.set_rate or remote['sender_cap']);initial_request[0]=False
            with lock:pending_request=request[0]
            if pending_request and peer[0] and now-request_sent[0]>=.5:
                if now-pending_request[4]<5:
                    try:sock.sendto(config_packet(*pending_request[:4]),peer[0])
                    except OSError:pass
                    request_sent[0]=now
                else:
                    with lock:request[0]=None
            if remote['sender_fps'] and (active.session is None or remote['sender_session']==active.session) and now-feedback_at[0]>=1:
                feedback_at[0]=now
                feedback=FEEDBACK.pack(b'R3FB',remote['sender_session'],int(now*1000)&0xffffffff,
                    active.metrics['udp_packets']&0xffffffff,sum(counts)&0xffffffff,
                    active.metrics['incomplete_frames']&0xffffffff,min(10000,int(lag_ms[0])))
                try:sock.sendto(feedback,addr)
                except OSError:pass
            if pair_result:
                payloads,session,seq,pts,hz=pair_result
                lag_ms[0]=delay.sample(session,pts,now);lag_max_ms[0]=max(lag_max_ms[0],lag_ms[0])
                decode_start=time.perf_counter_ns()
                try:
                    images=[decode_frame(sc,frame) for sc,frame in enumerate(payloads)]
                    with lock:
                        screens[:]=images
                        for sc in range(2):counts[sc]+=1;jpeg_counts[sc]+=1
                except (ValueError,OSError):errors[0]+=1
                finally:decode_max_us[0]=max(decode_max_us[0],(time.perf_counter_ns()-decode_start)//1000)
            if result:
                sc,frame=result
                header=HEADER.unpack_from(packet)
                lag_ms[0]=delay.sample(header[1],header[3],time.monotonic())
                lag_max_ms[0]=max(lag_max_ms[0],lag_ms[0])
                decode_start=time.perf_counter_ns()
                try:
                    rgb=decode_frame(sc,frame)
                    with lock:
                        screens[sc]=rgb;counts[sc]+=1
                        (jpeg_counts if frame.startswith(b'\xff\xd8') else ltc_counts)[sc]+=1
                except (ValueError,OSError):errors[0]+=1
                finally:decode_max_us[0]=max(decode_max_us[0],(time.perf_counter_ns()-decode_start)//1000)
    thread=threading.Thread(target=receive,daemon=True);thread.start()
    ff=None;stats=None;preview=None;write_max_us=0
    try:
        if a.preview:preview=Preview(configure)
        if a.stats:
            stats=open(a.stats,'w',encoding='utf-8',newline='')
            stats.write('elapsed_s,top_fps,bottom_fps,ip_bytes_per_second,decode_errors,jpeg_top,jpeg_bottom,ltc1_top,ltc1_bottom,'+
                        ','.join(ass.metrics)+',decode_max_us,arrival_lag_ms,arrival_lag_max_ms,write_max_us,'+
                        ','.join(STATUS_FIELDS)+',complete_pairs,incomplete_pairs,fec_recovered\n')
        if not a.no_output:
            ff=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','warning','-f','rawvideo',
                '-pixel_format','rgb24','-video_size','400x480','-framerate',str(a.fps),'-i','pipe:0',
                '-an','-c:v','libx264','-preset','ultrafast','-tune','zerolatency','-crf','10','-pix_fmt','yuv420p',
                '-g',str(a.fps),'-bf','0','-flush_packets','1','-muxdelay','0','-f','rtsp','-rtsp_transport','tcp',a.rtsp],stdin=subprocess.PIPE,bufsize=0)
        destination=a.rtsp if ff else 'direct preview' if preview else 'decode only'
        print(f'Listening UDP {a.bind}:{a.port}, sender {a.sender}; output {destination}',flush=True)
        start=report=time.monotonic();due=start;previous=[0,0];last_bytes=0;shown=[-1,-1]
        while not a.seconds or time.monotonic()-start<a.seconds:
            now=time.monotonic()
            if now<due:time.sleep(due-now)
            due=max(due+1/(120 if preview and not ff else a.fps),time.monotonic())
            if ff or preview:
                with lock:top,bottom=screens;current=counts.copy()
                if ff or current!=shown:
                    canvas=compose(top,bottom)
                    if preview:preview.show(canvas)
                    shown=current
                elif preview:preview.poll()
                if preview and preview.root is None and a.no_output:break
            if ff:
                write_start=time.perf_counter_ns()
                write_frame(ff.stdin,canvas)
                write_max_us=max(write_max_us,(time.perf_counter_ns()-write_start)//1000)
            now=time.monotonic()
            if now-report>=5:
                dt=now-report
                metrics=(paired if protocol[0]=='paired' else ass).metrics
                top_fps=(counts[0]-previous[0])/dt;bottom_fps=(counts[1]-previous[1])/dt
                if preview:preview.set_status(f'Device {remote["sender_fps"]} FPS / {remote["sender_cap"]} B/s | received {top_fps:.1f}/{bottom_fps:.1f} | FEC {metrics.get("fec_recovered",0)}',
                    (remote['sender_fps'],remote['sender_cap']))
                print(f'actual FPS top={(counts[0]-previous[0])/dt:.2f} bottom={(counts[1]-previous[1])/dt:.2f}; '
                      f'IP bytes/s={(received[0]-last_bytes)/dt:.0f}; decode errors={errors[0]}; '
                      f'JPEG={jpeg_counts} LTC1={ltc_counts}; incomplete={metrics["incomplete_frames"]} '
                      f'missing packets={metrics["missing_fragments"]} late={metrics["late_packets"]}; '
                      f'budget={remote["sender_budget"]} feedback={remote["sender_feedback"]}',flush=True)
                if stats:
                    stats.write(f'{now-start:.3f},{(counts[0]-previous[0])/dt:.3f},'
                                f'{(counts[1]-previous[1])/dt:.3f},{(received[0]-last_bytes)/dt:.0f},{errors[0]},'
                                f'{jpeg_counts[0]},{jpeg_counts[1]},{ltc_counts[0]},{ltc_counts[1]},'+
                                ','.join(str(metrics[k]) for k in ass.metrics)+
                                f',{decode_max_us[0]},{lag_ms[0]:.3f},{lag_max_ms[0]:.3f},{write_max_us},'+
                                ','.join(str(remote[k]) for k in STATUS_FIELDS)+
                                ','+','.join(str(metrics.get(k,0)) for k in ('complete_pairs','incomplete_pairs','fec_recovered'))+'\n')
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
