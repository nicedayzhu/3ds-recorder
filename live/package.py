"""Create a local test bundle; does not copy to a console or install a module."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import platform
import subprocess
import sys
import zipfile
from build import ROOT,BUILD

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stream-only',action='store_true',help='Package the R7 app, PC viewer and SD-ready live.ini without the old benchmark')
    parser.add_argument('--host',type=ipaddress.IPv4Address,help='PC IPv4 address for the SD configuration')
    parser.add_argument('--profile',choices=('default','quality','live30','fixed30','fixed24'),default='fixed30',help='fixed30/fixed24 = fixed 1 MB/s cap; quality/live30 = 800000 B/s')
    library_name='livecodec.dll' if sys.platform=='win32' else 'liblivecodec.so'
    parser.add_argument('--codec-library',type=Path,default=BUILD/library_name,help='Use a separately built candidate library')
    args=parser.parse_args()
    if args.stream_only and not args.host:parser.error('--stream-only requires --host PC_IP')
    files={
        'sd-benchmark/3ds/live-bench/live-bench.3dsx':BUILD/'live-bench.3dsx',
        'experimental-app/3ds-recorder.3dsx':ROOT/'app/3ds-recorder.3dsx',
        'experimental-app/rec3ds.cxi':ROOT/'sysmod/rec3ds.cxi',
        'experimental-app/live.ini.example':ROOT/'live/live.ini.example',
        'LICENSE':ROOT/'LICENSE',
        'third_party/JPEGENC/LICENSE':ROOT/'third_party/JPEGENC/LICENSE',
    }
    generated={}
    if args.stream_only:
        files={name:path for name,path in files.items() if name=='LICENSE' or name.startswith('third_party/')}
        files['sd-stream/3ds/3ds-live-r7/3ds-live-r7.3dsx']=ROOT/'app/3ds-recorder.3dsx'
        template={'default':'live.ini.example','quality':'live-quality.ini.example','live30':'live-30.ini.example',
                  'fixed30':'live-fixed30.ini.example','fixed24':'live-fixed24.ini.example'}[args.profile]
        config=(ROOT/'live'/template).read_text().replace('host=192.168.0.10',f'host={args.host}')
        generated['sd-stream/3ds/recorder/live.ini']=config.encode('ascii')
    else:
        for screen in ('top','bottom'):
            sample=BUILD/f'live-bench-{screen}.rgb565'
            if sample.exists():files[f'sd-benchmark/{sample.name}']=sample
    # Preserve the live/ layout: imports, DLL paths and Markdown links also work
    # when this bundle is extracted independently of a Git checkout.
    for name in ('README.md','USAGE.md','DEVELOPMENT.md','RESEARCH.md','PROTOCOL.md',
                 'preview.pyw','preview_ui.py','receiver.py','pair_protocol.py','codec.py',
                 'run.py','play.py','requirements.txt','mediamtx.yml',
                 'live-fixed30.ini.example','live-fixed24.ini.example'):
        files[f'live/{name}']=ROOT/'live'/name
    files['live/results/quality.csv']=ROOT/'live/results/quality.csv'
    files[f'live/build/{library_name}']=args.codec_library
    generated['README.md']=('''# 3DS Live R7 测试安装包

先阅读 [安装与使用教程](live/USAGE.md)，开发结论见 [开发总结](live/DEVELOPMENT.md)。

- `sd-stream`（直播包）：将其内容合并到 SD 根目录，随后在 Homebrew Launcher 启动 **3DS Live R7** 更新模块。
- `live`：PC 工具和文档。安装 Python/Pillow 后双击 `live/preview.pyw`。不要把此目录复制进 SD。
- 打包不会安装或上传到 3DS。R7 新增档位尚未经过真机验证，默认仍为 30 FPS / 1 MB/s。
- 新 PC 只用直显无需 GCC、FFmpeg 或 MediaMTX；RTSP 需要另装后两者。
- 主程序许可证见 [LICENSE](LICENSE)，嵌入的 JPEGENC 见 [Apache-2.0 许可证](third_party/JPEGENC/LICENSE)。

`manifest.json` 记录源代码提交、构建平台和各文件 SHA-256。源码及完整开发工具在
[项目分支](https://github.com/nicedayzhu/3ds-recorder/tree/feature/dual-screen-live)。
''').encode('utf-8')
    missing=[str(p) for p in files.values() if not p.is_file()]
    if missing:raise SystemExit('Build first; missing: '+', '.join(missing))
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    manifest={'version':'live-r7','commit':commit,'working_tree_dirty':dirty,'hardware_validated':False,
              'host_platform':sys.platform,'host_machine':platform.machine(),
              'fps_options':[15,20,24,30],'maximum_ipv4_bytes_per_second':2000000,
              'samples':'None' if args.stream_only else 'Local samples from upstream demo; see live/RESEARCH.md. Not raw framebuffer captures.',
              'sha256':{name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in files.items()}}
    out=ROOT/'live/dist';out.mkdir(exist_ok=True)
    manifest['sha256'].update({name:hashlib.sha256(data).hexdigest() for name,data in generated.items()})
    target=out/('new3ds-live-r7.zip' if args.stream_only else 'new3ds-live-test.zip')
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for name,path in files.items():z.write(path,name)
        for name,data in generated.items():z.writestr(name,data)
        z.writestr('manifest.json',json.dumps(manifest,indent=2))
    print(target)
if __name__=='__main__':main()
