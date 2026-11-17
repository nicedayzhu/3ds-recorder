"""Start the local RTSP bridge and stop only child processes created by this command."""
import argparse
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from pair_protocol import FPS_OPTIONS

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sender',required=True,help='3DS IPv4 address')
    p.add_argument('--fps',type=int,choices=FPS_OPTIONS,default=30)
    p.add_argument('--seconds',type=float,default=0)
    p.add_argument('--preview',action='store_true',help='Open a direct preview alongside RTSP output')
    p.add_argument('--hide-controls',action='store_true',help='Hide preview settings; H restores them')
    p.add_argument('--stats',default=str(ROOT/'live/build/received.csv'))
    p.add_argument('--mediamtx',type=Path,default=ROOT/'live/build/tools/mediamtx/mediamtx.exe')
    a=p.parse_args()
    if not a.mediamtx.is_file():p.error('MediaMTX missing; install it as described in live/USAGE.md or use --mediamtx')
    if not shutil.which('ffmpeg'):p.error('ffmpeg not in PATH')
    try:
        with socket.create_connection(('127.0.0.1',8554),timeout=.2):
            p.error('Port 8554 is already occupied. Use receiver.py with your existing RTSP server.')
    except OSError:pass
    server=None;receiver=None
    try:
        server=subprocess.Popen([str(a.mediamtx),str(ROOT/'live/mediamtx.yml')],cwd=ROOT/'live/build',
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(50):
            if server.poll() is not None:raise RuntimeError('MediaMTX exited')
            try:
                with socket.create_connection(('127.0.0.1',8554),timeout=.1):break
            except OSError:time.sleep(.1)
        else:raise RuntimeError('MediaMTX did not listen within 5 seconds')
        args=[sys.executable,'-u',str(ROOT/'live/receiver.py'),'--sender',a.sender,'--fps',str(a.fps),
              '--seconds',str(a.seconds),'--stats',a.stats]
        if a.preview:args.append('--preview')
        if a.hide_controls:args.append('--hide-controls')
        receiver=subprocess.Popen(args,cwd=ROOT)
        print('OBS Media Source: rtsp://127.0.0.1:8554/3ds',flush=True)
        result=receiver.wait()
        if result:raise SystemExit(result)
    except KeyboardInterrupt:pass
    finally:
        for child in (receiver,server):
            if child and child.poll() is None:
                child.terminate()
                try:child.wait(timeout=3)
                except subprocess.TimeoutExpired:child.kill();child.wait()

if __name__=='__main__':main()
