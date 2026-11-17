"""Synthetic PC sender for transport/OBS verification, not a 3DS performance result."""
import argparse
import socket
import time
from codec import Codec
from evaluate import fixture
from receiver import HEADER,CHUNK

def main():
    p=argparse.ArgumentParser();p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8001)
    p.add_argument('--seconds',type=float,default=15);p.add_argument('--fps',type=int,choices=(24,30),default=30)
    p.add_argument('--rate',type=int,default=700000);a=p.parse_args();c=Codec()
    # Pre-encode; Python image conversion must not affect the transport test.
    bank=[]
    for w in (400,320):
        frames=[]
        for k in (0,1):
            im=fixture(w,k);budget=a.rate*93//100//a.fps*w//720
            frames.append((c.jpeg(im,budget,60,scaled=True) if k==0 else b'') or c.encode(im,budget))
        bank.append(frames)
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);session=time.time_ns()&0xffffffff
    start=due=time.perf_counter();seq=0;sent=0
    while time.perf_counter()-start<a.seconds:
        pair_start=time.perf_counter()
        for sc in (0,1):
            seq+=1;frame=bank[sc][int((pair_start-start)//2)%2]
            for off in range(0,len(frame),CHUNK):
                packet=HEADER.pack(b'R3LP',session,seq,int((pair_start-start)*1e6)&0xffffffff,sc,len(frame),off,a.fps)+frame[off:off+CHUNK]
                delay=due-time.perf_counter()
                if delay>0:time.sleep(delay)
                sock.sendto(packet,(a.host,a.port));sent+=len(packet)+28
                due=max(due,time.perf_counter())+(len(packet)+28)/a.rate
        delay=pair_start+1/a.fps-time.perf_counter()
        if delay>0:time.sleep(delay)
    elapsed=time.perf_counter()-start
    print(f'synthetic: {seq/2/elapsed:.2f} pairs/s, {sent/elapsed:.0f} IP bytes/s')
    sock.close()
if __name__=='__main__':main()
