"""Windows/MSYS2 build of the full app; uses existing tools, installs nothing globally."""
import argparse
import os
from pathlib import Path
import subprocess
from build import ROOT

def msys(path):
    s=Path(path).resolve().as_posix()
    return '/'+s[0].lower()+s[2:] if len(s)>1 and s[1]==':' else s

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sdk',type=Path,default=ROOT.parents[1]/'toolchain/sdk/opt/devkitpro')
    p.add_argument('--bash',type=Path,default=Path('F:/Tools/msys64/usr/bin/bash.exe'))
    p.add_argument('--tool-bin',type=Path,default=ROOT/'live/build/tools')
    a=p.parse_args()
    env=os.environ.copy()
    env['LIVE_SDK']=msys(a.sdk);env['LIVE_REPO']=msys(ROOT);env['LIVE_TOOLS']=msys(a.tool_bin)
    # Fixed shell program; paths are passed as environment values, not shell code.
    script='''export DEVKITPRO="$LIVE_SDK"
export DEVKITARM="$DEVKITPRO/devkitARM"
export PATH="$LIVE_TOOLS:$DEVKITARM/bin:$DEVKITPRO/tools/bin:/mingw64/bin:/usr/bin:$PATH"
cd "$LIVE_REPO" || exit 1
make -B -C sysmod -j2 && make -C plugin -j2 && make -B -C app -j2 APP_CHANNEL=live-r6
'''
    subprocess.run([str(a.bash),'-lc',script],env=env,check=True)
if __name__=='__main__':main()
