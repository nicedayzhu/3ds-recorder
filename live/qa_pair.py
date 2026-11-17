"""Real UDP receiver + R6/R7 config acknowledgement + injected burst-loss QA."""
import argparse
import csv
import io
from pathlib import Path
import socket
import subprocess
import sys
import time
from PIL import Image
from pair_protocol import packetize,CONFIG,FPS_OPTIONS,RATE_OPTIONS,FPS_MASK
from receiver import STATUS,STATUS7
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fps',type=int,choices=FPS_OPTIONS,default=30)
    parser.add_argument('--rate',type=int,choices=RATE_OPTIONS,default=2000000)
    parser.add_argument('--legacy-status',action='store_true',help='Exercise the existing R6 status format')
    a=parser.parse_args()
    if a.legacy_status and (a.fps not in (24,30) or not 620000<=a.rate<=1000000):
        parser.error('R6 requires 24/30 FPS and 620000..1000000 B/s')
    tag=f'{"r6" if a.legacy_status else "r7"}-{a.fps}-{a.rate}'
    stats=ROOT/f'live/build/qa-pair-{tag}.csv'
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as reserve:
        reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    log=(ROOT/f'live/build/qa-pair-{tag}.log').open('w')
    p=subprocess.Popen([sys.executable,'-u','live/receiver.py','--sender','127.0.0.1','--bind','127.0.0.1',
        '--port',str(port),'--no-output','--seconds','12','--set-fps',str(a.fps),'--set-rate',str(a.rate),
        '--stats',str(stats)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind(('127.0.0.1',0));sock.setblocking(False)
    images=[Image.effect_noise((w,240),15 if a.rate<=600000 else 60).convert('RGB') for w in (400,320)]
    def encode(hz,rate):
        for q in range(95,0,-1):
            frames=[]
            for im in images:
                buf=io.BytesIO();im.save(buf,format='JPEG',quality=q);frames.append(buf.getvalue())
            wire=sum(len(p)+28 for p in packetize(*frames,1,1,0,hz))
            if wire*hz<=rate*.95:return frames
        raise AssertionError('Synthetic input cannot fit test budget')
    frames=encode(30,800000)
    session=7654321;hz=30;rate=800000;seq=0;requests=0
    try:
        time.sleep(.4);start=time.monotonic();status_at=0;due=start
        while time.monotonic()-start<11:
            now=time.monotonic();seq+=1
            if now-status_at>=.5:
                fields=(session,int((now-start)*1000),rate,rate,hz,seq,seq,seq,seq,0,0,0,2,3,10000,10000)
                status=(STATUS.pack(b'R3ST',*fields) if a.legacy_status else STATUS7.pack(b'R7ST',*fields,2000000,FPS_MASK))
                sock.sendto(status,('127.0.0.1',port));status_at=now
            packets=list(packetize(*frames,session,seq,int((now-start)*1e6),hz))
            if seq%7==0:packets=packets[:4]+packets[8:]
            for packet in packets:sock.sendto(packet,('127.0.0.1',port))
            while True:
                try:data,peer=sock.recvfrom(256)
                except BlockingIOError:break
                if data.startswith(b'R6CF'):
                    _,sid,request,new_hz,new_rate=CONFIG.unpack(data);assert sid==session;requests+=1
                    if (hz,rate)!=(new_hz,new_rate):
                        hz,rate=new_hz,new_rate;frames=encode(hz,rate);due=time.monotonic()
            due+=1/hz;time.sleep(max(0,due-time.monotonic()))
        p.wait(timeout=4);assert p.returncode==0
        with stats.open(newline='') as f:rows=list(csv.DictReader(f))
        assert requests>=1 and len(rows)>=2,rows
        steady=rows[-1]
        assert steady['sender_fps']==str(a.fps) and steady['sender_cap']==str(a.rate),steady
        assert float(steady['top_fps'])>=a.fps-.5 and steady['top_fps']==steady['bottom_fps'],steady
        assert int(steady['decode_errors'])==0 and int(steady['fec_recovered'])>=4,steady
        assert float(steady['ip_bytes_per_second'])<=a.rate,steady
        if not a.legacy_status:assert steady['sender_max_rate']=='2000000',steady
        if (a.fps,a.rate)==(15,2000000):assert max(map(len,frames))>40000
        print(f'{tag} UDP: config applied; {steady["top_fps"]} paired FPS; {steady["fec_recovered"]} fragments recovered; decode errors 0; JPEG sizes {list(map(len,frames))}')
    finally:
        sock.close()
        if p.poll() is None:p.terminate();p.wait(timeout=3)
        log.close()
if __name__=='__main__':main()
