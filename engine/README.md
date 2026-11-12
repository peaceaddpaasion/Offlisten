# 引擎

产品的重量都在这里。`extension/` 那 8 个文件只是遥控器——拔掉扩展，引擎照常工作，它自己会起一个 live 页面。

## 为什么是 Python

- `sherpa-onnx` 有官方 `cp313` `win_amd64` 轮子（PyPI 实测 75 个发布文件），换语言就得自己绑 ONNX Runtime；
- 推理只占运行时间的一小部分，瓶颈在音频采集与 VAD，不在语言本身；
- 不做原生重写的完整理由与**重新评估触发条件**见 [`../docs/adr-001-runtime.md`](../docs/adr-001-runtime.md)。

## 两条管线，不是一个模型的两种配置

`--engine` 二选一，默认 `sensevoice`。这个区别常被误解，写清楚：

| | `sensevoice`（默认） | `zipformer` |
|---|---|---|
| 模型 | `model.int8.onnx` 228.2 MiB | encoder/decoder/joiner int8 共 67.9 MiB |
| 流式 | 否（整段） | 是 |
| 语言 | zh / en / ja / ko / yue | 英文 |
| 标点 | 自带 | 无 |
| 延迟 | 高于流式 | 低 |

实现在 `pc_transcriber.py` 的 `build_offline_sv()` 与 `build_recognizer()`，两条完全独立的管线。

## 模块

| 文件 | 职责 |
|---|---|
| `pc_transcriber.py` | 音频采集、VAD、识别、存档 |
| `live_core.py` | 会话状态机：开始 / 停止 / 切换音源 / 多会话 |
| `web_live.py` | 本机 HTTP + SSE、token 鉴权；页面在 `web_live/` |
| `win32_overlay.py` / `overlay.py` | 悬浮字幕（分层窗口 + 点击穿透） |

## 一条值得看的细节：VAD 门限不是常数

按音源类型给不同门限：**mic `0.0008` / loopback `0.006`**。

依据是实测的峰值分布：mic 峰值 `0.0016`（0/30 帧过旧门限），loopback 峰值 `0.275`（24/30 帧过）。
所以不是「调到一个经验值」，而是两类音源的动态范围本来就差两个数量级。

同时如实记录：门限扫描证明两类音源之间**不存在分离点**，mic 录外放时 SNR≈1。
这是物理限制，不是待修 bug——写进文档比假装解决了更可信。

## 跑起来

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
run_transcriber.bat --engine sensevoice
```

模型不入库，放 `engine/pc_models/`，目录名与代码里的硬编码必须一致（`pc_transcriber.py:40-42`）：

```
pc_models/
  sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/
    model.int8.onnx        # 228.2 MiB，只读这一个；同目录的 model.onnx 937 MB 代码从不打开
    tokens.txt
  silero_vad.onnx          # 0.6 MiB
  sherpa-onnx-streaming-zipformer-en-2023-06-26/   # 可选，英文流式
```

体积账、三档取舍与为什么只分发 int8：见 [`../docs/distribution.md`](../docs/distribution.md)。
三个文件的下载地址、归档体积与字节校验值：见 [`../CONTRIBUTING.md`](../CONTRIBUTING.md)（模型不入库，仓库里没有）。

## 目录

- `tools/` — 测量与诊断：`bench_hotspot`（热点）、`cycle_stress`（循环压力）、`ulw_*`（悬浮窗变体）、`probe_*`（设备与路由探测）。
- `acceptance/` — 证据脚本：音频源与音源切换探测。上面那些门限数字就是它们跑出来的，不是估的。
- **未收录**：一次性的截图与交互脚本（`a*_shot.py`、`*_smoke.py` 之类）。它们只验证当时的界面长什么样，没有长期价值。

## 与开发工作区的关系

开发在 `D:\projects\whisper` 里进行，仓库里的 `engine/` 是**发布快照**。两边会漂移，用漂移检查器比对：

```bash
cd engine
python ../tools/engine-drift.py          # 只看差异
python ../tools/engine-drift.py --copy   # 以仓库为准覆盖工作区
```
