"""Real UDP receiver + R6 config acknowledgement + injected burst-loss QA."""
import csv
import io
from pathlib import Path
import socket
import subprocess
import sys
import time
from PIL import Image
from pair_protocol import packetize,CONFIG
from receiver import STATUS
ROOT=Path(__file__).resolve().parents[1]

def main():
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as reserve:
        reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    log=(ROOT/'live/build/qa-pair.log').open('w')
    p=subprocess.Popen([sys.executable,'-u','live/receiver.py','--sender','127.0.0.1','--bind','127.0.0.1',
        '--port',str(port),'--no-output','--seconds','12','--set-fps','24','--set-rate','1000000',
        '--stats','live/build/qa-pair.csv'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind(('127.0.0.1',0));sock.setblocking(False)
    images=[Image.effect_noise((w,240),60).convert('RGB') for w in (400,320)]
    for q in range(45,0,-1):
        frames=[]
        for im in images:
            buf=io.BytesIO();im.save(buf,format='JPEG',quality=q);frames.append(buf.getvalue())
        wire=sum(len(p)+28 for p in packetize(*frames,1,1,0,30))
        if wire*30<=800000*.95:break
    assert wire*30<=800000*.95
    session=7654321;hz=30;rate=800000;seq=0;requests=0
    try:
        time.sleep(.4);start=time.monotonic();status_at=0;due=start
        while time.monotonic()-start<11:
            now=time.monotonic();seq+=1
            if now-status_at>=.5:
                sock.sendto(STATUS.pack(b'R3ST',session,int((now-start)*1000),rate,rate,hz,
                    seq,seq,seq,seq,0,0,0,2,3,10000,10000),('127.0.0.1',port));status_at=now
            packets=list(packetize(*frames,session,seq,int((now-start)*1e6),hz))
            if seq%7==0:packets=packets[:4]+packets[8:]
            for packet in packets:sock.sendto(packet,('127.0.0.1',port))
            while True:
                try:data,peer=sock.recvfrom(256)
                except BlockingIOError:break
                if data.startswith(b'R6CF'):
                    _,sid,request,hz,rate=CONFIG.unpack(data);assert sid==session;requests+=1
            due+=1/hz;time.sleep(max(0,due-time.monotonic()))
        p.wait(timeout=4);assert p.returncode==0
        with (ROOT/'live/build/qa-pair.csv').open(newline='') as f:rows=list(csv.DictReader(f))
        assert requests>=1 and len(rows)>=2,rows
        steady=rows[-1]
        assert steady['sender_fps']=='24' and steady['sender_cap']=='1000000',steady
        assert float(steady['top_fps'])>=23.5 and steady['top_fps']==steady['bottom_fps'],steady
        assert int(steady['decode_errors'])==0 and int(steady['fec_recovered'])>=4,steady
        assert all(float(row['ip_bytes_per_second'])<=1000000 for row in rows),rows
        print(f'R6 UDP: config applied; {steady["top_fps"]} paired FPS; {steady["fec_recovered"]} fragments recovered; decode errors 0')
    finally:
        sock.close()
        if p.poll() is None:p.terminate();p.wait(timeout=3)
        log.close()
if __name__=='__main__':main()
