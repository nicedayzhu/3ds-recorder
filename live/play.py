"""Open this RTSP stream in a separate VLC instance with a small local-network cache."""
import argparse
from pathlib import Path
import shutil
import subprocess

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--vlc',type=Path)
    p.add_argument('--cache-ms',type=int,default=50)
    p.add_argument('--url',default='rtsp://127.0.0.1:8554/3ds')
    a=p.parse_args()
    candidates=[a.vlc,shutil.which('vlc'),Path('F:/Program Files/VideoLAN/VLC/vlc.exe'),
                Path('C:/Program Files/VideoLAN/VLC/vlc.exe')]
    vlc=next((str(v) for v in candidates if v and Path(v).is_file()),None)
    if not vlc:p.error('VLC missing; specify --vlc PATH')
    if a.cache_ms<0 or a.cache_ms>2000:p.error('--cache-ms must be 0..2000')
    subprocess.Popen([vlc,'--no-one-instance','--rtsp-tcp',f'--network-caching={a.cache_ms}',
                      '--clock-jitter=0','--clock-synchro=0','--no-video-title-show',a.url])
    print(f'Opened VLC with {a.cache_ms} ms network cache; close the previous VLC stream window.')
if __name__=='__main__':main()
