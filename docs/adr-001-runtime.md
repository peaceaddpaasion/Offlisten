# ADR-001 推理运行时：ncnn 与 ONNX 曾并存，主线定为 ONNX

- 状态：**已采纳**（2026-11-12 复核确认）
- 影响范围：`pc_transcriber.py`、`pc_models/`、安装包体积、Windows on ARM 覆盖
- **修订 2026-11-12**：下方「理由 1（质量天花板）」**已作废**——sherpa-ncnn 官方 release tag `asr-models`（2025-09-13）已发布 SenseVoice 的 ncnn 模型包（int8 / float32，两版日期）。"ncnn 没有更强的模型可换"不成立。决议本身不变，剩余三条理由仍成立。运行时的取舍与重新评估条件见 `docs/negative-results.md` N-08。

## 为什么需要这条记录

因为本项目**确实有过两条运行时线**，而切换没有被记录，导致口头结论与实际代码不一致：

| 时间 | 状态 | 证据 |
|---|---|---|
| 2026-10-24 | 分析对象（厂商 APK）走的是 **sherpa-ncnn**（模型 `xb-zh-en-v3`，ncnn + Vulkan/GPU，仅 arm64-v8a） | `ASR升级评估报告.md` §一、`.workbuddy/memory/2026-10-24.md` |
| 2026-10-25 | **ncnn 在 Android 真机上跑过**：改造 APK（换 `zipformer-libri-giga-70M`）重签后装机成功 | `.workbuddy/memory/2026-10-25.md`；`apk_out_*`、`official_model/`、`apk_models/` 仍在盘上 |
| 2026-11-06 | 做过一个 **ncnn-only 迁移包**，把 `pc_models/` 里的 onnx 模型剔除（SenseVoice / silero_vad / zipformer-en-onnx） | `.workbuddy/memory/2026-11-06.md` |
| 现在 | **主线是 ONNX** | `engine/pc_transcriber.py:37` `import sherpa_onnx`；venv 实测 `sherpa_onnx 2.0.0` + `onnxruntime 1.31.0` |

ncnn 资产仍然在盘上：`official_model/` 135 MB、`apk_models/` 135 MB。所以"有没有 ncnn"这个问题的答案是：
**资产有、Android 上跑过、PC 主线不用。**

**注意区分**：2026-10-24 那条是**分析对象的架构**，不是我们的 PC 实现；我们的 PC 端从未装过 `sherpa_ncnn`
（`.venv` 无此包、全仓 `.py` 无 `import sherpa_ncnn`）。把这两件事混起来，就会得出"我们在 PC 上跑过 ncnn"的假结论。

## 决策

主线固定为 **sherpa-onnx + ONNX Runtime**。ncnn 降级为**可选实验**，不进发布主线。

## 理由（按权重排序）

1. ~~**质量天花板**：SenseVoice（onnx）自带标点、覆盖 zh/en/ja/ko/yue。而 ncnn 侧最强的中英双语模型已被实证是官方 `bilingual-2023-02-13` 的换皮——`param/tokens` 的 **md5 完全一致**，纯改名未微调。也就是说 **ncnn 侧没有更强的双语模型可换**，换过去等于降级。~~
   **→ 2026-11-12 作废**：sherpa-ncnn 官方已发布 SenseVoice 的 ncnn 模型包（tag `asr-models`，2025-09-13），模型不再是差距。这条从"理由"降级为"历史事实"：当时盘上的 ncnn 模型确实只有换皮的双语模型。**不能因为一条理由作废就否定决议，但要标明它作废了**——否则下次有人拿新证据打穿这条，会误以为整个决定也塌了。
2. **平台覆盖**：PyPI 实测 `sherpa-ncnn 2.1.15` 只有 cp313 **win32 / win_amd64**，**没有 win_arm64**；`sherpa-onnx 2.0.1` 有 **win_arm64**。选 ncnn 等于放弃 Surface / Snapdragon X。
3. **收益边界被高估**：ncnn 的真实收益只有两项——甩掉 ONNX Runtime（约 45 MB）、模型压缩包更小（zh-14M：22.2 MB vs 70.6 MB）。
   但它**不是"能不能做到 96 MB"的前提**：Lite 档 96 MB 用 onnx 已经可以达成（英文流式 70 + 中文 14M 25 + VAD 1，只发 int8）。
   所以 ncnn 省的是**安装包里的 45 MB**，不是能力。
4. **迁移成本不低**：需要重新导出、重新验证 RTF 与 WER，且 SenseVoice→ncnn 的质量差**至今没有实测数据**。

## 后果

- **接受**：安装包会多背约 45 MB 的 ONNX Runtime。
- **触发重新评估的条件**（两条同时满足才做）：
  1. P1 用 PyInstaller 打出来的 onedir 总体积 **> 200 MB**；
  2. 确认**不需要** Windows on ARM 覆盖。
- 届时步骤：`pip install sherpa-ncnn` → 在同一条 30 帧音频上比 RTF/WER/内存 → 只有显著不劣化才动。

## 简历上应该怎么写（重要）

不要写"用了 ncnn 这种冷门技术"——那是**工具炫耀**，而且与代码不符，面试一查就露。
写**取舍**：

> 端侧 ASR 运行时选型：对比 sherpa-ncnn 与 sherpa-onnx，因 ncnn 无 Windows arm64 轮子
> （`sherpa-ncnn 2.1.15` 仅 win32/win_amd64），且 96 MB 档在 onnx 上已能达成、ncnn 的收益
> 仅是安装包里的 45 MB 运行时，放弃该收益，选 onnx 换取 5 语言 + 标点 + arm64 覆盖。

（原版这句话里还写了「其双语模型被实证为官方模型换皮」——**这句 2026-11-12 已作废**：
ncnn 侧现在有官方 SenseVoice 模型包。简历上不要再写它，否则面试官一查 release 页就能反驳。）

同一件事，后一种写法证明的是**判断力**，前一种只能证明**听说过**。

## 未验证

- `sherpa-ncnn` 在本机 Python 3.13 x64 上实际能否跑通（只核了 wheel 存在）。
- SenseVoice 导出到 ncnn 后的 RTF / WER / 内存峰值差。
- `official_model/` 与 `apk_models/` 是否仍被任何脚本引用（当前只确认 `pc_transcriber.py` 用的是 onnx）。
