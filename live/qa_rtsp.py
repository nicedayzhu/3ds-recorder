"""Runs an isolated localhost transport/RTSP smoke test; stops only its children."""
import csv
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
def main():
    build=ROOT/'live/build'; logs=[]; processes=[]
    def launch(args,name):
        log=(build/(name+'.log')).open('w');logs.append(log)
        process=subprocess.Popen(list(map(str,args)),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        processes.append(process);return process
    try:
        server=launch([build/'tools/mediamtx/mediamtx.exe',ROOT/'live/mediamtx.yml'],'qa-mediamtx')
        ready=False
        for _ in range(40):
            if server.poll() is not None:raise RuntimeError('MediaMTX exited; see qa-mediamtx.log')
            try:
                with socket.create_connection(('127.0.0.1',8554),timeout=.1):ready=True;break
            except OSError:time.sleep(.1)
        if not ready:raise RuntimeError('MediaMTX did not listen')
        receiver=launch([sys.executable,'-u','live/receiver.py','--bind','127.0.0.1','--sender','127.0.0.1','--seconds','22',
                         '--stats',build/'qa-receiver.csv'],'qa-receiver')
        time.sleep(1)
        sender=launch([sys.executable,'-u','live/demo_sender.py','--seconds','18'],'qa-sender')
        time.sleep(3)
        probe=subprocess.run(['ffprobe','-v','error','-rtsp_transport','tcp','-read_intervals','%+3',
             '-count_frames','-select_streams','v:0','-show_entries','stream=codec_name,width,height,r_frame_rate,nb_read_frames',
             '-of','json','rtsp://127.0.0.1:8554/3ds'],capture_output=True,text=True,timeout=12)
        if probe.returncode:raise RuntimeError(probe.stderr)
        result=json.loads(probe.stdout);stream=result['streams'][0]
        assert stream['width']==400 and stream['height']==480 and int(stream['nb_read_frames'])>=60,result
        sender.wait(timeout=25);receiver.wait(timeout=10)
        assert sender.returncode==0 and receiver.returncode==0
        with (build/'qa-receiver.csv').open(newline='') as f:measurements=list(csv.DictReader(f))
        steady=[r for r in measurements if 9<float(r['elapsed_s'])<17]
        assert len(steady)>=2,measurements
        assert all(float(r['top_fps'])>=24 and float(r['bottom_fps'])>=24 for r in steady),steady
        assert all(int(r['decode_errors'])==0 and float(r['ip_bytes_per_second'])<=701200 for r in measurements),measurements
        result['steady_intervals']=steady
        (build/'qa-rtsp.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2))
    finally:
        for p in reversed(processes):
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=3)
                except subprocess.TimeoutExpired:p.kill();p.wait()
        for log in logs:log.close()
if __name__=='__main__':main()
