# 安装与使用教程

[返回直播首页](README.md) · [开发总结](DEVELOPMENT.md)

## 1. 组件与安装包

| 组件 | 用途 |
| --- | --- |
| 3DS Live R7 `.3dsx` | 安装配套系统模块；游戏后台采集、压缩和 UDP 发送 |
| SD `/3ds/recorder/live.ini` | 指定 PC 地址和每次启动的默认设置 |
| PC `live/preview.pyw` | 双击启动 Direct Preview，实时设置设备参数 |
| PC `live/run.py` / `play.py` | 可选的本机 RTSP 桥接 / 低缓存 VLC 播放 |

本轮本地包为 `live/dist/new3ds-live-r7.zip`，不是已安装状态。解压后有 `sd-stream`、`live`、许可证和 `manifest.json`。包内包含 Windows x64 编解码 DLL，不包含 Python、Pillow、FFmpeg、MediaMTX 或 VLC；仅运行直显不需要编译器。Git 源码用户需先按[开发文档](DEVELOPMENT.md)构建 DLL 和应用。

所有命令在仓库根目录或解压目录执行。示例 `192.168.0.105` 是 **3DS 地址**；请替换为自己的实际地址。

## 2. 安装或升级 3DS 模块

1. 先按 R + SELECT 停止推流，确认通知灯熄灭。
2. 备份 SD `/luma/sysmodules/0004013000F1D302.cxi`、原控制应用及 `/3ds/recorder/live.ini`。应用与系统模块必须配套；R7 与原 Recorder 共用模块标题标识，目录名称不同不代表独立安装槽位。
3. 将包内 **`sd-stream` 里的内容**合并到 SD 根目录。检查 `/3ds/recorder/live.ini` 的 `host` 为 **PC 的局域网 IPv4**。打包时指定的地址可能因 DHCP 变化，需核对；不要填 3DS 地址。
4. 按上游安装要求在 Luma 启用 **Enable loading external FIRMs and modules**。从 Homebrew Launcher 启动 `/3ds/3ds-live-r7/3ds-live-r7.3dsx`，确认版本带 `live-r7`，让应用更新模块，并按提示重启。
5. 启动 PC 接收窗口，进入 HOME 或游戏，关闭 3D，按 **R + SELECT** 开始。再次按下即停止；自定义过热键时使用自己的组合。

有效且启用的直播配置会让热键进入直播，不同时写入普通录像。缺失或无效配置可能回退普通录制，所以通知灯闪动本身不能证明 PC 正在收到直播。原有录制文件无需迁移。

## 3. PC 直显

使用带 Tkinter 的 Python 3（本机验证版本为 3.14），安装依赖：

```powershell
python -m pip install -r .\live\requirements.txt
```

双击 `live/preview.pyw`，或执行 `python .\live\preview.pyw`，输入 3DS IP。先关闭旧接收窗口，避免占用同一 UDP 8001 端口。也可直接指定地址：

```powershell
python .\live\receiver.py --sender 192.168.0.105 --preview --no-output --stats .\live\build\received.csv
```

| 操作 | 效果 |
| --- | --- |
| 选择帧率、带宽，点“应用” | 请求设备在画面对之间切换；“设置已生效”表示收到设备实际值确认 |
| H / 双击画面 / 右键菜单 | 隐藏或恢复整个设置栏 |
| Esc | 隐藏设置栏 |
| `--hide-controls` | 命令行启动时直接隐藏设置栏 |
| 状态“设备 …” / “实收 … FPS” | 分别表示设备配置和最近约 1 秒收到的完整画面对率 |

纯黑画面背景与原来的 400×480 合成布局保持一致。隐藏时整个底部面板退出布局，不留空白；显示状态保存在本机 `live/build/viewer-ui.json`。隐藏后仍可用 H、双击或右键恢复。只在有新画面时刷新图像。

窗口隐藏状态会记住，设备帧率和带宽**不会写回 SD**。下一次推流仍读取 `live.ini`。等待信号或请求超时，请检查地址、端口和设备状态；下拉框中选中的值与状态行回报的实际值要区分。

## 4. FPS 与带宽档位

R7 的上下屏始终使用相同目标帧率；没有“上屏 30、下屏 15”的暗中降帧。

- FPS：**15、20、24、30**。
- 带宽：**0.40、0.50、0.60、0.70、0.80、0.90、1.00、1.20、1.40、1.60、1.80、2.00 MB/s**。
- 1 MB/s = 1,000,000 B/s = 8 Mbit/s；2 MB/s = 16 Mbit/s。
- 这是两屏合计的 IPv4 字节上限，包含应用头、UDP/IP、FEC 和状态包；不包括 Wi-Fi MAC、无线重传。简单画面实际流量可以更低。

以下是起始配置建议，不是自动切换规则或所有游戏的性能保证：

| 场景 | FPS | MB/s | 使用方法 |
| --- | ---: | ---: | --- |
| 已有可用基线 | 30 | 1.00 | 默认，先复现当前效果 |
| 靠近路由器，增加清晰度 | 30 | 1.20 → 2.00 | 每次增加一档，观察实收帧率、画质及卡顿 |
| 希望增加每对画面的预算 | 24 | 0.80–1.20 | 和 30 FPS 在同一位置、同一场景对比 |
| 链路较弱或内容变化较少 | 20 | 0.60–0.80 | 降低目标帧率，保留更多单帧字节 |
| 较低带宽测试 | 15 | 0.40–0.60 | 画质和流畅度都有取舍；复杂画面仍可能超预算 |

新 PC 工具连接 R6 时只显示其支持的 24/30 FPS、0.70–1.00 MB/s 档位。要使用 15/20 FPS 或超过 1 MB/s，需先安装 R7；旧 PC 接收器也应配套升级，因为 R7 单屏 JPEG 可能超过旧版 40 KB 上限。

**不提供 60 FPS 档位。**30 FPS / 2 MB/s 的毛预算约 66,667 B/对，60 FPS / 1 MB/s 只有 16,667 B/对，同时采集、编码截止时间从 33.3 ms 缩至 16.7 ms。网络能跑满 2 MB/s 不能证明 CPU 能完成双倍编码次数。还需考虑游戏自身渲染帧率。

命令行动态设置示例（R7，设备已连接后生效）：

```powershell
python .\live\receiver.py --sender 192.168.0.105 --preview --no-output --set-fps 24 --set-rate 1400000
```

`--fps` 控制 PC 输出时钟，`--set-fps` 才请求修改真机目标帧率。不要把播放器显示的 30 FPS 当成真机收到 30 个新画面的证据。

## 5. 保存默认配置

停止推流后编辑 SD `/3ds/recorder/live.ini`。包内 `fixed30` 默认内容如下，`host` 必须替换：

```ini
enabled=on
host=192.168.0.10
port=8001
fps=30
bytes_per_second=1000000
codec=jpeg
adaptive=off
```

R7 接受 FPS 15/20/24/30、`bytes_per_second` 400000–2000000 的整数范围，GUI 提供常用离散档位。R6 仅接受 24/30 和 620000–1000000。R6/R7 始终采用固定预算 JPEG；保留 `codec`、`adaptive` 两项是为识别旧配置，不能据此开启 R5 的拥塞算法。打包的 `fixed24` 是 24 FPS / 1 MB/s。

## 6. OBS 与 RTSP

### 优先：窗口采集

在 Direct Preview 按 H 隐藏设置栏，OBS 添加“窗口采集”，选择 **3DS Live - Direct Preview**，按需要排除标题栏/窗口边框。内容区域为 400×480：上屏 `(0,0,400,240)`；下屏 `(40,240,320,240)`。可将同一来源复制、裁剪成两个来源，分别排版。保持窗口运行。

用户同源对照确认直显比低缓存 VLC 更跟手；OBS 窗口采集步骤尚未完成本项目的 OBS UI 验收，具体捕获方式需按本机 OBS/显卡环境确认。当前没有原生 OBS 源插件。

### 可选：RTSP 媒体源

另需 FFmpeg（包含 libx264，在 PATH 中）和 [MediaMTX](https://github.com/bluenviron/mediamtx/releases)。本地验证使用 MediaMTX 1.21.4，并非对最新版的要求；将其可执行文件放到 `live/build/tools/mediamtx/mediamtx.exe`，或给 `run.py` 传 `--mediamtx` 路径。

```powershell
python .\live\run.py --sender 192.168.0.105 --fps 30 --stats .\live\build\received.csv
```

OBS 添加“媒体源”，取消“本地文件”，地址填 `rtsp://127.0.0.1:8554/3ds`。本机桥接已通过 FFprobe 验证 H.264、400×480、30 FPS。RTSP 服务仅监听回环地址，这不是跨互联网发布地址。

可给 `run.py` 加 `--preview`，同时打开直显用于对照。VLC 测试先关旧播放窗口，再执行：

```powershell
python .\live\play.py
```

默认网络缓存 50 ms；抖动时可试 `--cache-ms 100`，路径未找到时用 `--vlc`。这只是播放器缓存，不是总端到端延迟。RTSP 输出帧率在启动时固定；真机切换到 24 FPS 后，PC 可能重复画面补齐 30 FPS 时钟。如需改变 RTSP 时钟，重新以相应 `--fps` 启动。

## 7. 测试、日志与排查

把机器放到直播时的位置，同一场景每档持续 60–120 秒并连续操作。先测默认 30 / 1.00，再逐档增加带宽；若实际 FPS 或体感变差，回到前一档，或比较固定 24 FPS。较近位置的前台 FTP 2 MB/s 是参考，不能替代游戏后台 UDP 实测。

只接收并记录 120 秒，不打开预览或 RTSP：

```powershell
python .\live\receiver.py --sender 192.168.0.105 --no-output --seconds 120 --stats .\live\build\received.csv
```

| 现象 | 检查 |
| --- | --- |
| 黑屏、实际 FPS 与 IP 字节均为 0 | 真机是否开始推流；SD `host` 是 PC 地址，`--sender` 是 3DS 地址；Python UDP 8001 的当前局域网防火墙规则是否允许 |
| 红灯闪动但 PC 无数据 | 配置无效可能进入普通录制；核对 `live.ini`、安装模块和应用版本 |
| 端口占用错误 | 关闭旧接收器，避免 `preview.pyw`、`receiver.py`、`run.py` 同时抢 UDP 8001 |
| 不显示高档位 | 状态来自 R6；完成 R7 模块更新后才会开放 |
| 点应用没有生效 | 看设备实际值与超时提示；检查双向 UDP 和 SD host/port，重新连接后再试 |
| 实收 FPS 下降但解码错误为 0 | 查看未完成画面对、缺片、FEC 和发送超时；0 解码错误不代表无丢包 |
| VLC 明显慢于直显 | 用 `play.py` 低缓存实例，或改用 OBS 窗口采集 |
| FTP 连不上 | 先停止直播并在真机打开 ftpd；本工具的直播端口是 UDP 8001，FTP 是独立的 TCP 5000 |

双击启动器的日志在 `live/build/preview.log`，统计在 `live/build/received.csv`；每次启动会覆盖这两个文件，重要测试先另存。连接地址保存在 `preview-settings.json`。SD `/3ds/recorder/live-stats.txt` 在停止推流后写入。日志、IP 和配置保留本机，分享前自行检查。

CSV 的实际接收 FPS 按完整画面对计算。`arrival_lag_ms` 是相对本会话最低到达延迟的增长，不能当作绝对延迟；游戏静止或采集复用也不能算作新的游戏渲染帧。绝对操作延迟需拍摄真机和 PC 同框对照。

## 8. 回退与普通录制

恢复普通录制：停止推流，将 `enabled=off` 或移走 `live.ini`，再开始录制。回退模块：恢复自己备份的模块、配套控制应用和配置，并按安装要求重启。R6 回退时配置必须回到 24/30 FPS 且不超过 1 MB/s，不能留下 R7 专用档位。
