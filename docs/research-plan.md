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
| **平台** | x86-64 CPU · x86 + NVIDIA GPU · Windows arm64 | **二维：格式 × 平台**。线程数作为格内数据，不单独成轴 |
| **模型** | SenseVoice · zipformer(zh-14M / en-70M) · Whisper(tiny~small) · Parakeet | 只有锚点模型能贯穿多格式 |

## 3. 关键方法问题：必须用「同模型」做锚点

如果拿 ONNX 上的 SenseVoice 去比 ncnn 上的 zipformer，比出来的是**模型差异**，不是运行时差异——这类对比在社区里到处都是，结论无效。

**所以整张表必须挂在一个能跨格式的锚点模型上。** 实测已确认这个锚点存在：

| 格式 | SenseVoice 是否有实现 | 证据 |
|---|---|---|
| ONNX | ✅ **本项目正在用** | `sherpa_onnx 2.0.0` + `onnxruntime 1.31.0` |
| ncnn | ✅ 2025-09 加入，**已发预编译模型包** | sherpa-ncnn #416「Export sense voice to sherpa-ncnn」/ #418「C++ runtime for sense-voice」；release tag `asr-models`（2025-09-13）6 个 asset = `sherpa-ncnn-sense-voice-zh-en-ja-ko-yue-{2024-07-17,2025-09-09}` × {默认, int8, float32} |
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

若再叠上「必须流式」（会议实时字幕的硬需求），只剩 **2 格**——`sherpa-onnx` 与 `sherpa-ncnn` 的 x86-64 CPU。
精确计数与逐格证据等级见 `docs/bench/README.md`；形式化表述见 `docs/paper.md`。

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

## 6. 功耗：**砍掉**（并说明为什么砍）

原计划把功耗作第三维，实测条件不允许，已从图中移除：

- Windows 读不到 RAPL，物理功耗需要**外接功率计**；
- 代理指标（HWiNFO package power / `powercfg` 电池放电 / CPU 时间×占用）**跨机型不可比**，噪声大到无法支撑一张图；
- 更关键的是：**放进去会让人以为我们测过**。这比缺一维更糟。

→ 决议：**二维（格式 × 平台），颜色深浅表示可用度**。功耗若要补，等有功率计再单独做一页，并注明测量条件。
**不写"功耗更低"这种没有测量支撑的结论。**

## 7. 产出形态

1. **主图**：**二维矩阵**（格式 × 平台），格内写结论词，**颜色深浅 = 可用度**，不存在的格子用斜纹 + 编号注脚指向官方依据。已产出中英各一套：`docs/bench/matrix-{zh,en}.svg` / `.png` / `.pdf`。
2. **副图**：同模型（SenseVoice）三格式的 RTF-线程曲线 —— 证明"线程不是越多越好"（14M 模型在 N100 上多线程是负优化的已有实证）。
3. **数据表 + 复现脚本**：每条数据附音频片段 hash、模型文件 hash、命令行。
4. **一页 README**：结论先行，给"我要做 X 场景，该选哪个格式"的决策树。

## 8. 边界（避免变成空头研究）

- **不训练模型、不做 SOTA**。只测"已有开源模型 + 已有运行时"的组合。
- **不追全覆盖**。宁可 10 格有数据 + 30 格有依据的"不可行"，也不做 192 格全是估算。
- **不发表也行**。先作为仓库里的 `docs/bench/` 长期维护；有数据后自然会有人引用——这比投稿更快成为"开源人"。
- 与现有产品的边界：本项目的 Lite/Standard 两档只取其中 2 格，其余是**公共品**。

## 9. 已核实 / 未核实

**已核实**：TensorRT 不支持 CPU（NVIDIA FAQ + Triton 矩阵）；TRT engine 设备绑定、JetPack 不支持 11.3、DLA 在 11.3 移除；sherpa-ncnn 无 win_arm64 wheel；SenseVoice 有官方 GGUF（q8 235MB，8 线程 8.01% CER）；sherpa-ncnn 2025-09 支持 SenseVoice 导出**且已发预编译模型包**（tag `asr-models`，2026-11-12 复核）；本机 Windows x86-64 **从未安装运行** `sherpa_ncnn`；ncnn 在 **Android 真机**跑过（2026-10-25 改造 APK 装机）。

**未核实**：SenseVoice 导出 ncnn 后的实际 RTF/CER；`sherpa-ncnn` 在本机 Python 3.13 能否装跑；TRT 转 SenseVoice 的算子支持度；arm64 硬件是否可得；SenseVoice GGUF 的实时流式能力（目前看是非流式）。

## 10. 若真要启动，第一步是什么

**不是买显卡，是把 SenseVoice 在 gguf 上跑通并与现有 onnx 基线对齐同一段音频。**
两条数据（RTF、CER）出来，这张表就已经有了骨架——其余全是往里填。

## 11. 社区形态：为什么适合 X + Hugging Face

这两个平台要的东西不一样，图要用两次，但文案不能一样。

**X（传播，靠一张图）**
- 发 `docs/bench/matrix-en.png`，配 **2 句**结论，不放长文。
- 英文帖模板（X 是国际场）：
  > 4 runtimes × 3 platforms = 12 combos. Only **one** can ship to an unknown Windows machine.
  > TensorRT doesn't run on CPU (NVIDIA's own FAQ). sherpa-ncnn has no win_arm64 wheel.
  > GGUF ASR is non-streaming. Full matrix + sources 👇
- 图里已有编号注脚，正文只挂链接，不在帖里堆依据——**图和论证分离**是 X 的正确用法。

**Hugging Face（被引用，靠可检索的文档）**
- HF 的用户是"正在找模型/找方案的人"，入口应该是问题，不是产品：
  **"我要选一个能装到用户机器上的运行时"** → 这张图。
- 建议**单独建一个 Space / repo**（例如 `edge-asr-matrix`），只放这张图 + 决策树 + 数据表，
  **不要塞进产品仓库的 docs 里**。理由很实际：引用者不想为了看一张表去 star 一个产品仓库。
- 数据能逐格提交 PR 之后，它才会真的活着——单方面维护的表，半年就过期。

**一句话原则**：图是公共品，产品是自己的。把图放在能被独立引用的地方。

## 12. 已产出

| 文件 | 用途 |
|---|---|
| `docs/paper.md` | 工作稿：形式化问题、证据分级、效度威胁、可证伪条件 |
| `docs/negative-results.md` | 负结果册：11 条没成的事 + 判定 + 证据路径 |
| `docs/bench/matrix-zh.svg` / `matrix-en.svg` | 图源，可编辑（改一格不用重画） |
| `docs/bench/matrix-zh.png` / `matrix-en.png` | 中文平台 / X 与 HF 发布用（1000×780） |
| `docs/bench/matrix-zh.pdf` / `matrix-en.pdf` | 打印 / 引用 |
| `docs/bench/README.md` | 逐格原因、证据分级、不测清单、贡献模板、决策树 |
