"""Create a local test bundle; does not copy to a console or install a module."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import subprocess
import zipfile
from build import ROOT,BUILD

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stream-only',action='store_true',help='Package the app and an SD-ready live.ini')
    parser.add_argument('--host',type=ipaddress.IPv4Address,help='PC IPv4 address for the SD configuration')
    parser.add_argument('--profile',choices=('default','quality','live30','fixed30','fixed24'),default='fixed30',help='fixed30/fixed24 = fixed 1 MB/s cap; quality/live30 = 800000 B/s')
    args=parser.parse_args()
    if args.stream_only and not args.host:parser.error('--stream-only requires --host PC_IP')
    files={
        'sd-benchmark/3ds/live-bench/live-bench.3dsx':BUILD/'live-bench.3dsx',
        'experimental-app/3ds-recorder.3dsx':ROOT/'app/3ds-recorder.3dsx',
        'experimental-app/rec3ds.cxi':ROOT/'sysmod/rec3ds.cxi',
        'experimental-app/live.ini.example':ROOT/'live/live.ini.example',
        'README.md':ROOT/'live/README.md',
        'RESEARCH.md':ROOT/'live/RESEARCH.md',
        'PROTOCOL.md':ROOT/'live/PROTOCOL.md',
        'LICENSE':ROOT/'LICENSE',
        'JPEGENC-LICENSE':ROOT/'third_party/JPEGENC/LICENSE',
    }
    generated={}
    if args.stream_only:
        files={name:path for name,path in files.items() if '/' not in name}
        files['sd-stream/3ds/3ds-recorder/3ds-recorder.3dsx']=ROOT/'app/3ds-recorder.3dsx'
        template={'default':'live.ini.example','quality':'live-quality.ini.example','live30':'live-30.ini.example',
                  'fixed30':'live-fixed30.ini.example','fixed24':'live-fixed24.ini.example'}[args.profile]
        config=(ROOT/'live'/template).read_text().replace('host=192.168.0.10',f'host={args.host}')
        generated['sd-stream/3ds/recorder/live.ini']=config.encode('ascii')
    else:
        for screen in ('top','bottom'):
            sample=BUILD/f'live-bench-{screen}.rgb565'
            if sample.exists():files[f'sd-benchmark/{sample.name}']=sample
    missing=[str(p) for p in files.values() if not p.is_file()]
    if missing:raise SystemExit('Build first; missing: '+', '.join(missing))
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    manifest={'commit':commit,'working_tree_dirty':dirty,'hardware_validated':False,
              'samples':'None' if args.stream_only else 'Local samples from upstream demo; see RESEARCH.md. Not raw framebuffer captures.',
              'sha256':{name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in files.items()}}
    out=ROOT/'live/dist';out.mkdir(exist_ok=True)
    manifest['sha256'].update({name:hashlib.sha256(data).hexdigest() for name,data in generated.items()})
    target=out/('new3ds-stream-test.zip' if args.stream_only else 'new3ds-live-test.zip')
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for name,path in files.items():z.write(path,name)
        for name,data in generated.items():z.writestr(name,data)
        z.writestr('manifest.json',json.dumps(manifest,indent=2))
    print(target)
if __name__=='__main__':main()
