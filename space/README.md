---
title: Offlisten
emoji: 🎙️
colorFrom: gray
colorTo: yellow
sdk: static
pinned: false
license: mit
short_description: 100% offline ASR for meetings — local, no upload
---

# 录匣 Offlisten

100% 离线的会议 / 课堂转写。没有账号，没有云端，拔掉网线它还在写。

这个 Space 是**静态证据页**：五个语种的实测输出、RTF 分布、演示视频。
不放可交互 demo 的原因很实际——转写要在服务端跑 229 MiB 的模型，
而 Hugging Face 免费账号不能运行 CPU 上的 Gradio 容器（`cpu-basic` 返回配额错误，
`zero-a10g` 返回 402，官方文档写明 Gradio/Docker Space 需要付费计划）。

## 目录里有什么

| 文件 | 用途 |
|---|---|
| `index.html` | 实际展示的页面 |
| `demo.mp4` | 42 秒演示：五段音频真跑，听完才落字；`tools/record-demo.py` 生成 |
| `demo.mp4.json` | 那次录制的实测记录：每段文本、耗时、音频 sha256 |
| `use-with-browser-ai.mp4` | 46 秒，无音轨：本地文本页 + Page Assist + Ollama 的闭环实录 |
| `README.md` | 本文件，Space 卡片元数据 |
| `app.py`、`requirements.txt` | **Gradio 版**，本地已跑通；当前 `sdk: static` 不执行它。升级 PRO 后把 frontmatter 改回 `sdk: gradio` 即可切换 |

## 演示是怎么录的

不是手工录屏。`tools/record-demo.py` 做三件事，所以视频和上表不可能对不上：

1. 用同一份权重、同样 2 线程，真跑五段 `test_wavs`，拿到文本与耗时
2. 起本地 `web_live` 服务与无头 Edge，把每段结果按真实时钟推给页面，逐帧截图
3. 按同一时钟把五段音频混成音轨，ffmpeg 合成 H.264 + AAC

因此视频里“字幕出现的时刻”就是产品里“一段话说完的时刻”，音画不会漂。

## 接本地的 AI

`use-with-browser-ai.mp4` 记录的是另一条链路，46 秒，无音轨：

    本机 SenseVoice → 127.0.0.1 上的文本页 → 浏览器扩展 Page Assist 读当前页 → Ollama 上的 qwen2.5:0.5b 作答

三个部件都在同一台机器上，链路里没有一处需要出网。这不是外挂，是产品页里写好的出口——
本地文本页有一行提示：「要交给 AI 处理，就复制全文，或让你浏览器里已有的 AI 插件读取本页。」

视频去掉音轨、裁掉录屏工具条后转码：源素材 14.8 MB → 1.2 MB，1440×746。
去掉声音是因为它要证明的是数据不出本机，不是听感。


## 模型与音频

权重在 [ToothpasteLake/offlisten-models](https://huggingface.co/ToothpasteLake/offlisten-models)，
6 个文件 229.07 MiB，逐文件 sha256 对应发行清单。
表里那五段音频在同一个仓库的 `test_wavs/` 下，点语种名可以直接听，也可以下载后自己复跑。

