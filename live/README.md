# New 3DS 双屏直播实验分支

目标：New 3DS 上屏 400×240、下屏 320×240 优先稳定双屏 30 FPS，无法稳定达到时采用固定 24 FPS；画面清晰、延迟尽量低，合计 IPv4 流量不超过 1,000,000 B/s，通过 PC 接入 OBS。R6 已构建并完成本地协议测试，**真机帧率、游戏兼容性和端到端延迟尚待验收**。只传视频，不传声音，不支持 800 像素宽屏模式。

上游基线：`BolgarMaxym97/3ds-recorder@2952a1df332a5c9c34938f5ba788b30cd57a2168`。开发分支：`feature/dual-screen-live`。保留原录制功能；只有 SD 上的 `live.ini` 有效且 `enabled=on` 时，开始录制操作才转为直播。

## 实现

```mermaid
flowchart LR
  A[双屏 framebuffer DMA] --> B[RGB565 与旋转转换]
  B --> C[双屏共享预算 / DCT 缓存 / JPEG 4:2:0]
  C --> E[双屏交错 UDP 与 XOR 冗余]
  E --> F[PC 成对解码与原子显示]
  F --> J[直显窗口 / OBS 窗口采集]
  F --> G[FFmpeg H.264]
  G --> H[本机 MediaMTX RTSP]
  H --> I[OBS 媒体源]
```

R6 使用固定总字节预算，不再根据拥塞反馈降低总预算。两屏共享额度、使用相同量化参数；变化的 16×16 MCU 才重新转换和计算 DCT，未变化块复用精确系数。超预算时最多再做两次量化/熵编码，不重复颜色转换和 DCT。最后仍放不下则整对丢弃，并记录统计，不允许某一屏无限落后。每个 JPEG 都独立解码，缓存不产生网络帧间依赖。

`live-quality.ini.example` 是另一测试配置：24 FPS、800,000 B/s、JPEG。相比 30 FPS/700,000 B/s，每帧编码预算增加约 43%，仍需验证所在网络能否承受该速率。

两个编码线程分别尝试核心 2、3，失败回退核心 1。采样时等待两屏最新请求的 DMA 完成，再提交同一对画面；保留原采集器的安全抓取判断，游戏本身不同步换屏或静止时可能复用某屏的最后一次采集，`source_reused` 单独计数。统一帧号确保接收端不会组合不同发送对；这不意味着游戏内部两屏在同一时刻渲染。

发送时交错上下屏分片，每屏附加两个条带 XOR 冗余包。每条带缺一个数据包且相应冗余包收到时可恢复；同条带丢多个包仍不能恢复。冗余、应用头、IPv4/UDP 和状态包全部计入预算，另留调度余量。接收端最多保留两对未完成画面，80 ms 超时；仅完整解码两屏后一起显示，不重传、不累计旧帧。默认测试包使用 `fixed30`（30 FPS / 1 MB/s），也提供 `fixed24`；原 800,000 B/s 配置仍可用。R5 自适应退步的证据见 RESEARCH.md；R6 忽略旧 `adaptive` 和 `codec` 选项，始终固定预算 JPEG。

这里的“固定码率”指固定预算与逐包限速，不发送填充包强行用满带宽。静态/简单画面的实际速率可以更低。

带宽限制计入自定义头、IPv4 和 UDP 头；不包括 Wi-Fi MAC 开销、路由器缓冲和无线重传。RTSP 在 PC 本机产生，不占 3DS→PC 的这份预算。

## 可选：单独测真机编码耗时

可以直接按下面的“PC 与 OBS”和“安装实验系统模块并试游戏”做推流测试；独立编码基准不是前置条件，适合在帧率不足时定位编码开销。

在本机已构建的项目中，运行 `python live/package.py` 会生成 `live/dist/new3ds-live-test.zip`。解压后将 `sd-benchmark` 内的内容合并到 SD 根目录，在 Homebrew Launcher 启动 `live-bench.3dsx`。它不安装系统模块、不修改 Luma 配置，会写 SD 根目录 `/live-bench.csv`。样本文件存在时使用真实游戏视频的抽样画面，否则使用合成图案；控制台和包清单会注明。

复制 CSV 回 PC 后：

```powershell
Set-Location D:\Games\Old_Times\3ds\live_stream\3ds-recorder
python .\live\analyze_bench.py .\live-bench.csv
```

旧独立基准测量 LTC1 和基础 JPEG，不覆盖 R6 的并行缓存流水线；R6 应以实时状态和停止后的 `live-stats.txt` 验收。每个并行工作线程及整体流水线都需要满足 33.33 ms（30 FPS）或 41.67 ms（24 FPS）的截止时间。独立 homebrew 的耗时不能替代游戏后台测量。

## PC 与 OBS

已有依赖的这台 PC 可双击 `live/preview.pyw`，输入 3DS 的 IP 后打开直显窗口；连接地址只保存在忽略版本管理的本机 build 目录。请先关闭旧接收窗口，避免占用同一个 UDP 8001 端口。

已有构建的这台 PC：

```powershell
Set-Location D:\Games\Old_Times\3ds\live_stream\3ds-recorder
python .\live\run.py --sender 192.168.0.105 --fps 30 --stats .\live\build\received.csv
```

保持窗口运行。OBS 添加“媒体源”，取消“本地文件”，输入 `rtsp://127.0.0.1:8554/3ds`，输入格式可留空。若本机 OBS 的媒体源无法打开该地址，可用 VLC 视频源添加相同网络地址。上下屏合成 400×480，下屏水平居中，OBS 可裁剪成两个来源。降低网络缓存后检查稳定性。本轮已用 FFprobe 验证 RTSP，尚未在 OBS UI 中验收。

独立 VLC 测试时，关闭之前的流窗口，在另一个终端执行 `python live/play.py`，以 50 ms 网络缓存打开新实例；不要用默认约 1000 ms 的缓存评估操作延迟。若出现抖动可用 `--cache-ms 100`。这仅减少播放端缓存，不代表总延迟已经降到 50 ms。PC H.264 桥接使用 CRF 10、无 B 帧和立即刷新，避免再编码明显加重模糊。

用户在同源画面对照中确认直显窗口比低缓存 VLC 更跟手。优先评估低延迟时，可加 `--preview` 同时打开直显；或使用下面的命令只直显，省去 H.264/RTSP 播放链路。OBS 可先用“窗口采集”选择 `3DS Live - Direct Preview`（尚未在 OBS UI 验收）；原生 OBS 源插件仍未实现。

```powershell
python .\live\receiver.py --sender 192.168.0.105 --fps 30 --preview --no-output --stats .\live\build\received.csv
```

R6 直显窗口底部可以选择 **24/30 FPS** 和 **700000/800000/900000/1000000 B/s**，点击“Apply / 应用”发送给设备；状态行显示设备回报的实际设置及接收帧率。切换在发送对之间生效，旧配置的待发对会丢弃，不用停止推流或打开 ftpd。设置只在本次推流有效，下次仍从 SD 的 `live.ini` 读取。命令行也可加 `--set-fps 24 --set-rate 1000000`。接收器的 `--fps` 是 PC 输出时钟；`--set-fps` 才会改变设备采集目标。RTSP 输出时钟在启动时固定，切到 24 FPS 后可能重复画面补齐输出时钟。

OBS 使用直显窗口采集时，可裁掉底部设置栏，保留 400×480 画面。窗口帧率是成功收到的画面对数；静止游戏内容或采集复用不能算成新的游戏渲染帧。

CSV 还记录缺失分片、未完成帧、乱序/迟到包和解码耗时。`arrival_lag_ms` 是相对本次会话最小到达延迟的增长量，不是端到端绝对延迟；绝对延迟仍需用真机和电脑同框视频测量。

R5 的 `sender_*` CSV 列来自实时 UDP 统计，包含设备运行时间、编码/发送计数、当前预算和反馈接收次数；可在推流过程中检查反馈是否生效。设备与 PC 的实际 FPS 应按各自计数差/时间差计算，不使用输出时钟替代。

Python 入站 UDP 8001 需要在 Windows 的当前局域网防火墙规则中允许；RTSP 8554 仅监听回环地址。`--sender` 填 3DS IP，SD 配置的 `host` 填 **PC IP**，不要写反。日志每 5 秒报告每屏实际收帧率、IPv4 B/s 和解码错误；输出时钟丢帧时会重复上帧，因此 OBS 显示 30 FPS 不代表真机有 30 个新画面。

不启动 RTSP、单独接收测量：

```powershell
python .\live\receiver.py --sender 192.168.0.105 --no-output --seconds 120 --stats .\live\build\received.csv
```

新 PC 需 Python、GCC/MinGW-w64、FFmpeg（含 libx264）和 [MediaMTX](https://github.com/bluenviron/mediamtx/releases)。本轮使用 MediaMTX v1.21.4；将其 Windows 可执行文件放到 `live/build/tools/mediamtx/mediamtx.exe`，或给 `run.py` 传 `--mediamtx`。然后：

```powershell
git submodule update --init --recursive
python -m pip install -r .\live\requirements.txt
python .\live\build.py
```

## 安装实验系统模块并试游戏

可直接进行此步。包的 `experimental-app/3ds-recorder.3dsx` 是包含本次系统模块的完整控制应用。也可执行 `python live/package.py --stream-only --host PC的IPv4地址`，得到 `live/dist/new3ds-stream-test.zip`，将其中 `sd-stream` 内的内容合并到 SD 根目录，应用和 `live.ini` 即已就位。先备份 SD 的 `/luma/sysmodules/0004013000F1D302.cxi` 和原应用；实验版沿用上游标题标识，不是独立安装槽位。原录制文件不需要迁移。

1. 将实验应用放在 SD `/3ds/`；将 `live-fixed30.ini.example` 复制成 `/3ds/recorder/live.ini`，把 `host` 改成 PC 的局域网 IPv4 地址。该配置为 30 FPS / 1 MB/s。缺少有效配置时热键会进入原本的 SD 录制模式。
2. 按上游安装方式，Luma 开启 **Enable loading external FIRMs and modules**；启动实验应用，让它安装更新系统模块，并按应用提示重启。该安装会替换原系统模块。
3. 启动 PC 接收器。进入游戏，按原热键 **R + SELECT** 开始/停止直播；热键若在原配置中改过则用改后的热键。关闭 3D，先测常规 400×240 上屏游戏。
4. 连续测 120 秒，两屏都需要有运动；停止后收集 PC `received.csv`、SD `/3ds/recorder/live-stats.txt` 和 Recorder 日志。固定画面本来不会每秒产生 30 个新画面；上游对静止 VRAM 只偶尔重抓，对静止 FCRAM 保留上一帧。
5. 同一场景通过直显窗口分别测 30 FPS、24 FPS，并确认设备回报值改变。若需永久修改默认值，在停止推流后编辑 SD 配置。建议近路由器、双屏都有变化的游戏场景，先各持续 60–120 秒。

建议先用 700,000 B/s：此前 FTP 前台吞吐均值仅约 875,000 B/s，最低一轮约 763,000 B/s，且游戏后台网络可能更慢。`bytes_per_second` 接受 620,000–1,000,000。这里的 1 MB/s 是十进制 8 Mbit/s。

如果启动失败或卡住，恢复备份模块并重启；不需要改动游戏。恢复普通录制时删除 `live.ini` 或设置 `enabled=off`；恢复原版模块后也恢复原版控制应用，两者共享地址必须配套。此前版本已验证基本采集和联网；R6 新流水线及联网游戏兼容性仍需真机测试。

## 开发与复现

```powershell
python .\live\build.py --arm --sdk D:\Games\Old_Times\3ds\toolchain\sdk\opt\devkitpro
python -m unittest discover -s live -p 'test_*.py'
python .\live\qa_rtsp.py
python .\live\qa_pair.py
python .\live\evaluate.py --images .\live\build\samples\frames
```

`build.py --arm` 生成 `live/build/live-bench.3dsx`；主机 C 测试覆盖字节预算、截断和畸形输入；Python 测试覆盖 JPEG 内存边界、颜色/方向、UDP 乱序/丢包/重启/序号回绕。`qa_rtsp.py` 使用预编码的合成双屏帧，输出实测 CSV 和 FFprobe JSON；这不是 ARM 编码性能测试。`evaluate.py` 不带 `--images` 时使用合成图案并覆盖当前 `quality.csv`。

完整应用在已有 devkitPro 环境构建：按顺序 `make -C sysmod`、`make -C plugin`、`make -C app`。需要 libctru、citro2d/3d、makerom、3gxtool；上游 `tools/Dockerfile` 固定了 3gxtool 源码版本。务必先构建 sysmod，以更新 app 的共享地址头文件。Windows 本机构建用法见 `build_app.py`。

设计依据、质量数据和验收门槛见 [RESEARCH.md](RESEARCH.md)；协议见 [PROTOCOL.md](PROTOCOL.md)。
