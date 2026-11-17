"""Create a local test bundle; does not copy to a console or install a module."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
from build import ROOT,BUILD

def main():
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
    for screen in ('top','bottom'):
        sample=BUILD/f'live-bench-{screen}.rgb565'
        if sample.exists():files[f'sd-benchmark/{sample.name}']=sample
    missing=[str(p) for p in files.values() if not p.is_file()]
    if missing:raise SystemExit('Build first; missing: '+', '.join(missing))
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    manifest={'commit':commit,'working_tree_dirty':dirty,'hardware_validated':False,
              'samples':'Local samples from upstream demo; see RESEARCH.md. Not raw framebuffer captures.',
              'sha256':{name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in files.items()}}
    out=ROOT/'live/dist';out.mkdir(exist_ok=True)
    target=out/'new3ds-live-test.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for name,path in files.items():z.write(path,name)
        z.writestr('manifest.json',json.dumps(manifest,indent=2))
    print(target)
if __name__=='__main__':main()
