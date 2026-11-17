"""Build the host codec, tests and standalone ARM11 codec benchmark."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'live/build'
def run(args):
    print(' '.join(map(str,args)),flush=True)
    subprocess.run(list(map(str,args)),check=True,cwd=ROOT)
def main():
    p=argparse.ArgumentParser();p.add_argument('--arm',action='store_true');p.add_argument('--sdk',type=Path,
        default=ROOT.parents[1]/'toolchain/sdk/opt/devkitpro')
    p.add_argument('--output-dir',type=Path,default=BUILD,help='Separate candidate output while the viewer holds its DLL open')
    a=p.parse_args();output=a.output_dir.resolve();output.mkdir(parents=True,exist_ok=True)
    src=ROOT/'codec/source/live_codec.c';inc=ROOT/'codec/include'
    gcc=shutil.which('gcc');suffix='dll' if sys.platform=='win32' else 'so'
    if not gcc:raise SystemExit('gcc not found: add MinGW-w64 bin to PATH')
    if not (ROOT/'third_party/JPEGENC/src/JPEGENC.h').exists():
        raise SystemExit('Run: git submodule update --init --recursive')
    jpeg=ROOT/'codec/source/live_jpeg.c'
    run([gcc,'-O3','-fno-strict-aliasing','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC','-I',inc,src,jpeg,'-o',output/('livecodec.dll' if suffix=='dll' else 'liblivecodec.so')])
    test=output/('test_live.exe' if sys.platform=='win32' else 'test_live')
    run([gcc,'-O2','-std=c11','-Wall','-Wextra','-Werror','-I',inc,src,ROOT/'live/test_live.c','-o',test]);run([test])
    pacing=output/('test_pacing.exe' if sys.platform=='win32' else 'test_pacing')
    run([gcc,'-O2','-std=c11','-Wall','-Wextra','-Werror','-I',inc,ROOT/'live/test_pacing.c','-o',pacing]);run([pacing])
    rate_test=output/('test_rate.exe' if sys.platform=='win32' else 'test_rate')
    run([gcc,'-O2','-std=c11','-Wall','-Wextra','-Werror','-I',inc,ROOT/'live/test_rate.c','-o',rate_test]);run([rate_test])
    pair_test=output/('test_pair.exe' if sys.platform=='win32' else 'test_pair')
    run([gcc,'-O2','-std=c11','-Wall','-Wextra','-Werror','-I',inc,ROOT/'live/test_pair.c','-o',pair_test]);run([pair_test])
    if a.arm:
        sdk=a.sdk.resolve();cc=sdk/'devkitARM/bin/arm-none-eabi-gcc';ctru=sdk/'libctru'
        run([cc,'-O3','-fno-strict-aliasing','-std=gnu11','-Wall','-Wextra','-Werror','-march=armv6k','-mtune=mpcore','-mfloat-abi=hard','-mtp=soft',
             '-D__3DS__','-I',ctru/'include','-I',inc,'-specs=3dsx.specs','-L',ctru/'lib',
             src,jpeg,ROOT/'live/arm_bench.c','-lctru','-lm','-o',output/'live-bench.elf'])
        run([sdk/'tools/bin/3dsxtool',output/'live-bench.elf',output/'live-bench.3dsx'])
if __name__=='__main__':main()
