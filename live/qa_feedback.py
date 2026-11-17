"""Local UDP duplex test for R5 status/feedback; no console or RTSP required."""
import csv
import io
import socket
import subprocess
import sys
import time
from pathlib import Path
from PIL import Image
from receiver import HEADER,CHUNK,STATUS,FEEDBACK

ROOT=Path(__file__).resolve().parents[1]

def main():
    build=ROOT/'live/build'
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as reserve:
        reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    log=(build/'qa-feedback.log').open('w')
    process=subprocess.Popen([sys.executable,'-u',str(ROOT/'live/receiver.py'),'--bind','127.0.0.1',
        '--port',str(port),'--sender','127.0.0.1','--no-output','--seconds','6',
        '--stats',str(build/'qa-feedback.csv')],stdout=log,stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind(('127.0.0.1',0));sock.setblocking(False)
    frames=[];acks=[];session=0x12345678;seq=0
    for width in (400,320):
        data=io.BytesIO();Image.new('RGB',(width,240),'green').save(data,format='JPEG');frames.append(data.getvalue())
    try:
        time.sleep(.4)
        start=last_status=time.monotonic();last_status-=1
        while time.monotonic()-start<5:
            now=time.monotonic();stamp=int((now-start)*1e6)
            if now-last_status>=.5:
                sock.sendto(STATUS.pack(b'R3ST',session,int((now-start)*1000),1000000,800000,30,
                    seq//2,seq//2,seq//2,seq//2,0,0,len(acks),2,3,22000,18000),('127.0.0.1',port))
                last_status=now
            for sc,frame in enumerate(frames):
                seq+=1
                for off in range(0,len(frame),CHUNK):
                    if seq==3 and off==CHUNK:continue  # exercise missing-fragment feedback
                    sock.sendto(HEADER.pack(b'R3LP',session,seq,stamp,sc,len(frame),off,30)+frame[off:off+CHUNK],('127.0.0.1',port))
            while True:
                try:packet,peer=sock.recvfrom(256)
                except BlockingIOError:break
                assert peer==('127.0.0.1',port)
                values=FEEDBACK.unpack(packet);assert values[0]==b'R3FB' and values[1]==session
                acks.append(values)
            time.sleep(max(0,now+1/30-time.monotonic()))
        process.wait(timeout=4);assert process.returncode==0
        assert len(acks)>=3 and acks[-1][3]>0 and acks[-1][4]>0 and acks[-1][5]>0,acks
        with (build/'qa-feedback.csv').open(newline='') as f:rows=list(csv.DictReader(f))
        assert rows and int(rows[-1]['decode_errors'])==0,rows
        assert int(rows[-1]['sender_cap'])==1000000 and int(rows[-1]['sender_feedback'])>0,rows
        print(f'UDP status/feedback OK: {len(acks)} feedback messages; loss reported; frames decoded')
    finally:
        sock.close()
        if process.poll() is None:process.terminate();process.wait(timeout=3)
        log.close()

if __name__=='__main__':main()
