"""Verify a stream bundle's hashes, documentation and isolated PC startup."""
import argparse
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('bundle',type=Path,nargs='?',default=ROOT/'live/dist/new3ds-live-r7.zip')
    a=p.parse_args();build=(ROOT/'live/build').resolve()
    with zipfile.ZipFile(a.bundle) as z:
        names=z.namelist();assert len(names)==len(set(names)),'Duplicate archive entry'
        manifest=json.loads(z.read('manifest.json'))
        assert set(manifest['sha256'])==set(names)-{'manifest.json'},'Incomplete hash manifest'
        for name,digest in manifest['sha256'].items():
            assert hashlib.sha256(z.read(name)).hexdigest()==digest,name
        assert 'sd-stream/3ds/3ds-live-r7/3ds-live-r7.3dsx' in names
        assert manifest['maximum_ipv4_bytes_per_second']==2000000
        config=z.read('sd-stream/3ds/recorder/live.ini').decode('ascii')
        assert 'enabled=on' in config and 'host=' in config
        with tempfile.TemporaryDirectory(prefix='bundle-qa-',dir=build) as folder:
            folder=Path(folder).resolve();assert folder.is_relative_to(build)
            for name in names:
                assert not PurePosixPath(name).is_absolute()
                assert (folder/name).resolve().is_relative_to(folder),name
            z.extractall(folder)
            links=0
            for doc in folder.rglob('*.md'):
                for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',doc.read_text(encoding='utf-8')):
                    if re.match(r'[a-zA-Z][\w+.-]*:',target) or target.startswith('#'):continue
                    path=target.split('#',1)[0].split(' "',1)[0].strip('<>')
                    assert (doc.parent/path).exists(),f'{doc.name}: {path}'
                    links+=1
            env=os.environ.copy();env.pop('LIVE_CODEC_LIBRARY',None)
            for script in ('receiver.py','run.py','play.py'):
                subprocess.run([sys.executable,str(folder/'live'/script),'--help'],cwd=folder,env=env,
                               check=True,stdout=subprocess.DEVNULL,timeout=10)
            code="""import sys
sys.path.insert(0,'live')
from codec import Codec
from preview_ui import Preview
from PIL import Image
c=Codec()
assert c.jpeg(Image.new('RGB',(400,240),'red'),128000)
p=Preview(preferences_path=None,controls_visible=False)
p.root.withdraw();p.root.update_idletasks()
assert p.root.winfo_reqwidth()==400 and p.root.winfo_reqheight()==480
assert p.root.cget('background')=='black' and p.video.cget('background')=='black'
p.close()
"""
            subprocess.run([sys.executable,'-c',code],cwd=folder,env=env,check=True,timeout=15)
    print(f'Bundle QA: {len(names)} entries, all SHA-256 hashes, {links} local doc links, standalone DLL/UI/CLI OK')
    print(f'Source commit: {manifest["commit"]}; dirty: {manifest["working_tree_dirty"]}')

if __name__=='__main__':main()
