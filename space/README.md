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

这个 Space 是**静态证据页**：五个语种的实测输出、RTF 数字、演示视频位。
不放可交互 demo 的原因很实际——转写要在服务端跑 229 MiB 的模型，
而 Hugging Face 免费账号不能运行 CPU 上的 Gradio 容器（`cpu-basic` 返回配额错误，
`zero-a10g` 返回 402，官方文档写明 Gradio/Docker Space 需要付费计划）。

## 目录里有什么

| 文件 | 用途 |
|---|---|
| `index.html` | 实际展示的页面 |
| `README.md` | 本文件，Space 卡片元数据 |
| `app.py`、`requirements.txt` | **Gradio 版**，本地已跑通；当前 `sdk: static` 不执行它。升级 PRO 后把 frontmatter 改回 `sdk: gradio` 即可切换 |

## 模型

权重在 [ToothpasteLake/offlisten-models](https://huggingface.co/ToothpasteLake/offlisten-models)，
6 个文件 229.07 MiB，逐文件 sha256 对应发行清单。
