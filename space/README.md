---
title: Offlisten ASR
emoji: 🎙️
colorFrom: indigo
colorTo: gray
sdk: gradio
app_file: app.py
pinned: false
license: mit
short_description: Offline ASR demo for zh/en/ja/ko/yue, reports RTF
---

# Offlisten ASR — 在线演示

把一段音频转成带标点的文字，并报出在 2 vCPU 上的 RTF。

**这不是产品。** 产品 Offlisten 是本地桌面端：WASAPI 抓系统声音、转写结果写本地文件、全程不联网。
这个 Space 跑的是同一个 SenseVoice int8 模型，放在 Linux CPU 上，只用来让人先听到效果。

## 会看到什么

| 项 | 值 |
|---|---|
| 模型 | SenseVoice int8，229 MiB，中 / 英 / 日 / 韩 / 粤 |
| 标点 | 模型自带，不需要单独标点模型 |
| 硬件 | 免费 CPU Basic，2 vCPU / 16 GB |
| 输出 | 转写文本 + 音频时长 + 耗时 + RTF |

## 实测（本机 Windows，2 线程，不是 Space 硬件）

用 `test_wavs/` 里五个语种各一条，走的就是本 Space 的 `transcribe()`：

| 音频 | 时长 | 耗时 | RTF | 输出 |
|---|---|---|---|---|
| zh.wav | 5.6 s | 0.45 s | 0.080 | 开饭时间早上9点至下午5点。 |
| en.wav | 7.2 s | 0.81 s | 0.114 | The tribal chieftain called for the boy and presented him with 50 pieces of code. |
| ja.wav | 7.2 s | 0.61 s | 0.085 | うちの中学は弁当制で持っていきない場合は50円の学校販売のパンを買う。 |
| ko.wav | 4.6 s | 0.39 s | 0.084 | 조금만 생각을 하면서 살면 훨씬 편할 거야. |
| yue.wav | 5.1 s | 0.45 s | 0.088 | 呢几个字都表达唔到我想讲嘅意思。 |

两个如实标注：

- 官方示例对 `zh.wav` 输出「**开放**时间」，int8 量化 + 2 线程下这里是「**开饭**时间」。
  重采样到 44.1 kHz 再喂回去，结果相同——说明不是重采样管线的问题，是模型在这段短音频上的真实取舍。
- 上表是本机 CPU 的成绩；Space 的免费档是共享 2 vCPU，实测 RTF 可能更高，以页面里显示的数字为准。

## 它不是产品的原因

- 这里**必须上传音频**，产品是**不上传**的；
- 这里只能处理整段文件，产品是实时抓取、边开边写；
- 免费档闲置会休眠，第一名访客要等容器唤醒并加载 229 MiB 模型。

## 模型从哪来

默认从 `OFFLISTEN_MODEL_REPO`（默认 `ToothpasteLake/offlisten-models`）用 `hf_hub_download` 拉取，
只取 `model.int8.onnx` 与 `tokens.txt`。要换成本地目录，设 `OFFLISTEN_MODEL_DIR` 指向含这两个文件的目录。

许可证与来源见主仓库 `docs/distribution.md`；模型的原始许可见 SenseVoice 上游（Apache-2.0）。

## 主仓库

<https://github.com/peaceaddpaasion/Offlisten>
