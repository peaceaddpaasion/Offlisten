# 端侧 ASR 运行时可用性地图（长期展望，I-081）

> 一句话：**把「格式 × 资源约束 × 模型」画成一张带空集的图，用实测标注哪些格子能跑、为什么大部分不能，
> 让后来的人不必再重复造轮子。**
> 这不是 SOTA 研究，是**可用性测绘**——价值在"空集也有据"，不在数字更高。

## 1. 为什么这件事有意义（而不是自嗨）

端侧 ASR 的现状是：每个项目都在自己试一遍同样十几种组合，然后各自得出"XX 不能用"的私人结论，且不公开失败原因。
结果是**失败信息完全不流通**，所有人重复踩同一批坑。

测绘的价值在于：**失败也得写下来，并且要能引用官方依据。** 这张图里最贵的部分不是"哪个最快"，
是"这一整列根本没有实现"，以及"它为什么没有"。

## 2. 三个维度的定义

| 维度 | 取值 | 备注 |
|---|---|---|
| **格式 / 运行时** | ONNX (sherpa-onnx) · ncnn (sherpa-ncnn) · GGUF (llama.cpp / FunASR-llamacpp) · TensorRT | 四者不是同层：前三是"能装能跑"，TRT 是"要编译成 engine" |
| **资源约束** | 线程数 {1,2,4,8} × 平台 {x86-CPU, x86-GPU, arm64} × 功耗代理 | 功耗见 §6 |
| **模型** | SenseVoice · zipformer(zh-14M / en-70M) · Whisper(tiny~small) · Parakeet | 只有锚点模型能贯穿多格式 |

## 3. 关键方法问题：必须用「同模型」做锚点

如果拿 ONNX 上的 SenseVoice 去比 ncnn 上的 zipformer，比出来的是**模型差异**，不是运行时差异——这类对比在社区里到处都是，结论无效。

**所以整张表必须挂在一个能跨格式的锚点模型上。** 实测已确认这个锚点存在：

| 格式 | SenseVoice 是否有实现 | 证据 |
|---|---|---|
| ONNX | ✅ **本项目正在用** | `sherpa_onnx 2.0.0` + `onnxruntime 1.31.0` |
| ncnn | ✅ 2025-09 加入 | sherpa-ncnn #416「Export sense voice to sherpa-ncnn」/ #418「C++ runtime for sense-voice」 |
| GGUF | ✅ **官方已发布** | `FunAudioLLM/SenseVoiceSmall-GGUF`：q8 ≈235 MB、f16 470 MB，**CPU 8 线程 8.01% CER**（184 条普通话），同基准下 whisper.cpp 为 22–31% |
| TensorRT | ⚠️ 需 ONNX→engine，须 NVIDIA GPU | 见 §4 |

**这是整件事成立的前提**：一个模型、四种运行时、同一段音频——控制变量才成立。

## 4. 预判：哪些格子注定是空的（一半可以引官方文档，不必跑实验）

这一节是"半个研究"里**成本最低、可信度最高**的部分。

### 4.1 TensorRT 的 CPU 列——整列为空

NVIDIA 官方 FAQ 原文：**"Does TensorRT run on a CPU? No. TensorRT needs an NVIDIA GPU or Jetson module."**
Triton 的 Backend-Platform Support Matrix 也一致：TensorRT 在 x86 与 ARM-SBSA 上均为 `GPU ✅ / CPU ❌`。

→ 结论：**"端侧 CPU 笔记本 + TensorRT"这个格子不是慢，是不存在。** 无需实验，引文档即可。

### 4.2 TensorRT 的跨设备列——基本为空

官方：TensorRT engine **默认只与构建它的设备类型兼容**；hardware compatibility 仅支持 Ampere 及以后，
且 **JetPack / Jetson 不支持**。另外 TensorRT 11.3 **不支持 JetPack**（Jetson 必须留在 10.x），DLA 在 11.3 已移除。

→ 结论：TRT 是"**一机一引擎**"，在分发场景（给未知用户的安装包）里几乎不可用。这条比性能数据更重要。

### 4.3 GGUF 的流式列——大量为空

现有 GGUF ASR 多为**非流式**（SenseVoiceSmall-GGUF 是 SAN-M encoder + CTC，整段输入；Fun-ASR-Nano 是 encoder+Qwen3-0.6B）。
→ 结论：GGUF 在"低延迟流式"这一列基本空着，它的强项是**离线批量 + 单文件零依赖**。别拿它做实时字幕。

### 4.4 ncnn 的平台列——arm64 为空（Windows）

实测 PyPI：`sherpa-ncnn 2.1.15` 只有 cp313 **win32 / win_amd64**，**无 win_arm64**；`sherpa-onnx 2.0.1` 有。
→ 结论：Windows on ARM（Surface / Snapdragon X）这一格，ncnn 为空。

### 4.5 汇总：一张"空集图"就已经是贡献

把上面四条画成矩阵，会发现**四格式 × 三平台 = 12 格里，真正"能跑且适合分发"的只有 3–4 格**。
这个结论不需要训练任何模型，只需要读文档 + 两次 PyPI 查询。

## 5. 最小实验集：12–16 格，不是全跑

全跑 4 格式 × 4 线程 × 3 平台 × 4 模型 = 192 格，个人做不完也没意义。**只跑能改变结论的格子**：

| # | 模型 | 格式 | 平台 | 线程 | 为什么必须跑 |
|---|---|---|---|---|---|
| 1 | SenseVoice | onnx | x86-CPU | 1/4/8 | 基线（当前产品） |
| 2 | SenseVoice | gguf | x86-CPU | 1/4/8 | **同模型跨格式**，本图核心对照 |
| 3 | SenseVoice | ncnn | x86-CPU | 1/4/8 | 同模型第三方运行时 |
| 4 | SenseVoice | tensorrt | x86-GPU | - | GPU 列唯一有效点（需 4060 现成） |
| 5 | zipformer-en | onnx | x86-CPU | 4 | 流式 vs 非流式的延迟差 |
| 6 | zipformer-zh14M | ncnn | x86-CPU | 4 | ncnn 侧中文最小模型 |
| 7 | Whisper-small | gguf(whisper.cpp) | x86-CPU | 4 | GGUF 线上最成熟的对照 |
| 8 | Parakeet-110m | gguf | x86-CPU | 4 | GGUF 另一条独立实现（parakeet.cpp） |
| 9 | SenseVoice | onnx | arm64 | - | 有硬件才做；否则标 `未测` |
| 10 | SenseVoice | ncnn | arm64 | - | 同上（Windows arm64 为空，可作反例） |

**其余格子明确写"不测及原因"**——不测也要进表，这正是"失败信息流通"的意义。

## 6. 功耗：只能给代理指标，必须写明

Windows 上读不到 RAPL，物理功耗需要外接功率计。可行的三种代理，按可信度排序：

1. **HWiNFO / LibreHardwareMonitor 的 CPU Package Power**（需管理员权限，传感器支持因主板而异）；
2. **笔记本电池放电速率**（`powercfg /batteryreport`，只对整机有效，噪声大）；
3. **CPU 时间 × 占用**（最弱，但一定能拿到）。

**论文/报告里必须写清"功耗为代理指标，非功率计实测"**，否则就是overclaim——这个领域最常见的造假点。

## 7. 产出形态

1. **主图**：三维矩阵热图，横轴平台×线程，纵轴格式，格内为 RTF；**空格用斜纹表示"不可行"并附编号注脚**（注脚指向 §4 的官方依据）。
2. **副图**：同模型（SenseVoice）三格式的 RTF-线程曲线 —— 证明"线程不是越多越好"（14M 模型在 N100 上多线程是负优化的已有实证）。
3. **数据表 + 复现脚本**：每条数据附音频片段 hash、模型文件 hash、命令行。
4. **一页 README**：结论先行，给"我要做 X 场景，该选哪个格式"的决策树。

## 8. 边界（避免变成空头研究）

- **不训练模型、不做 SOTA**。只测"已有开源模型 + 已有运行时"的组合。
- **不追全覆盖**。宁可 10 格有数据 + 30 格有依据的"不可行"，也不做 192 格全是估算。
- **不发表也行**。先作为仓库里的 `docs/bench/` 长期维护；有数据后自然会有人引用——这比投稿更快成为"开源人"。
- 与现有产品的边界：本项目的 Lite/Standard 两档只取其中 2 格，其余是**公共品**。

## 9. 已核实 / 未核实

**已核实**：TensorRT 不支持 CPU（NVIDIA FAQ + Triton 矩阵）；TRT engine 设备绑定、JetPack 不支持 11.3、DLA 在 11.3 移除；sherpa-ncnn 无 win_arm64 wheel；SenseVoice 有官方 GGUF（q8 235MB，8 线程 8.01% CER）；sherpa-ncnn 2025-09 支持 SenseVoice 导出。

**未核实**：SenseVoice 导出 ncnn 后的实际 RTF/CER；`sherpa-ncnn` 在本机 Python 3.13 能否装跑；TRT 转 SenseVoice 的算子支持度；arm64 硬件是否可得；SenseVoice GGUF 的实时流式能力（目前看是非流式）。

## 10. 若真要启动，第一步是什么

**不是买显卡，是把 SenseVoice 在 gguf 上跑通并与现有 onnx 基线对齐同一段音频。**
两条数据（RTF、CER）出来，这张表就已经有了骨架——其余全是往里填。
