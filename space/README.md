---
title: Offlisten
emoji: 🎙️
colorFrom: gray
colorTo: yellow
sdk: static
pinned: false
license: mit
short_description: 100% offline ASR for meetings, local, no upload
---

# 录匣 Offlisten

100% 离线的会议 / 课堂转写。没有账号，没有云端，拔掉网线它还在写。

这个 Space 是静态证据页：五个语种的实测输出、两段演示视频，以及一张端侧 ASR 运行时选型矩阵。

不放可交互 demo，原因是免费档跑不了 Gradio 容器：`cpu-basic` 返回配额错误，`zero-a10g` 返回 402，
官方文档写明 Gradio / Docker Space 需要付费计划。转写本来也要在本地跑 229 MiB 的模型。

## 目录里有什么

| 文件 | 用途 |
|---|---|
| `index.html` | 实际展示的页面 |
| `demo.mp4` | 42 秒演示：五段音频真跑，听完才落字；`tools/record-demo.py` 生成 |
| `demo.mp4.json` | 那次录制的实测记录：每段文本、耗时、音频 sha256 |
| `use-with-browser-ai.mp4` | 46 秒，无音轨：本地文本页 + Page Assist + Ollama 的闭环实录 |
| `matrix-zh.png` / `matrix-en.png` | 选型矩阵，1000×780；源文件 `docs/bench/*.svg`，改文案后重出 PNG/PDF |
| `README.md` | 本文件，Space 卡片元数据 |
| `app.py`、`requirements.txt` | Gradio 版，本地跑通过；当前 `sdk: static` 不执行它 |

## 演示是怎么录的

不是手工录屏。`tools/record-demo.py` 做三件事，所以视频和页面上那张表不可能对不上：

1. 用同一份权重、同样 2 线程，真跑五段 `test_wavs`，拿到文本与耗时
2. 起本地 `web_live` 服务与无头 Edge，按真实时钟把每段结果推给页面，逐帧截图
3. 按同一时钟把五段音频混成音轨，ffmpeg 合成 H.264 + AAC

所以字幕出现的时刻，就是产品里一段话说完的时刻，音画不会漂。

## 接本地的 AI

`use-with-browser-ai.mp4` 记录的是另一条链路，46 秒，无音轨：

    本机 SenseVoice → 127.0.0.1 上的文本页 → 浏览器扩展 Page Assist 读当前页 → Ollama 上的 qwen2.5:0.5b 作答

三个部件都在同一台机器上，链路里没有一处需要出网。本地文本页上那行提示就是为这条路留的：
「要交给 AI 处理，就复制全文，或让你浏览器里已有的 AI 插件读取本页。」

源素材 14.8 MB，裁掉录屏工具条、去掉音轨后是 1.2 MB，1440×746。

## 选型矩阵

4 个运行时 × 3 个平台，12 格里只有 2 格同时满足「CPU 能跑 · 流式 · 能装进别人的机器」。
逐格依据分级：5 格来自官方文档或包矩阵，1 格本机实测，1 格只验过模型，5 格是推断。

页面上的链接都可以当场点开核：

- [FunAudioLLM 论文（arXiv:2407.04051）](https://arxiv.org/abs/2407.04051)
- [sherpa-onnx 文档](https://k2-fsa.github.io/sherpa/onnx/)
- [sherpa-ncnn 的 SenseVoice 章](https://k2-fsa.github.io/sherpa/ncnn/sense-voice/)
- [Triton 后端支持矩阵](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/backend/docs/backend_platform_support_matrix.html)
- [PyPI 上 sherpa-ncnn 的 wheel 列表](https://pypi.org/project/sherpa-ncnn/#files)

## 模型与音频

权重在 [ToothpasteLake/offlisten-models](https://huggingface.co/ToothpasteLake/offlisten-models)，
6 个文件 229.07 MiB，逐文件 sha256 对应发行清单。
表里那五段音频在同一个仓库的 `test_wavs/` 下，点语种名可以直接听，也可以下载后自己复跑。

## 更新这个 Space

页面改动后跑一次，脚本会跳过 `_` 开头的本地临时文件，并在 `--verify` 下逐个核对线上字节数：

```bash
python tools/push-space.py --dry-run    # 只看会传什么
python tools/push-space.py --verify     # 传 + 核对
```
