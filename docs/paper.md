# 端侧 ASR 运行时的可分发空集
### ——4 格式 × 3 平台的一份可用性测绘（工作稿）

**英文题**：The Distributable Empty Set: A Usability Survey of 4 On-Device ASR Runtimes × 3 Platforms

| | |
|---|---|
| 状态 | **工作稿 / working paper**，未投稿，随仓库演进 |
| 版本 | v2 · 2026-11-12（对应仓库 commit 见 `git log -- docs/paper.md`） |
| 作者 | Offlisten 项目（单人 + 助手协作） |
| 数据 | 本仓库 `docs/bench/`、`docs/adr-001-runtime.md`、`docs/negative-results.md` |
| 性质 | **不是 SOTA 研究**。不训练模型、不刷榜，只测绘"已有开源模型 × 已有运行时"哪些组合实际可分发 |

> **状态声明（前置，不放在最后）**
> 本稿目前是**文档依据为主、实测为辅**：12 个格子里 5 格有官方依据、1 格有本机运行时实测、1 格只做了模型侧取证、5 格为推断。
> **在补上"同模型跨格式 RTF/CER"之前，本稿不能被称为 benchmark。** 数据来源与逐格依据见 `docs/bench/README.md`。

---

## 摘要

端侧语音识别（ASR）的选型长期依赖零散经验：每个项目各自试十几种"格式 × 平台"组合，各自得出"某某不能用"的私人结论，且几乎不公开失败原因。结果是**失败信息完全不流通**，同类坑被反复踩。

本文把该问题形式化为一个可判定的问题：在"向未知用户的 Windows 桌面机分发"这一约束下，4 种运行时（ONNX Runtime / ncnn / GGUF / TensorRT）× 3 种平台（x86-64 CPU / x86-64 + NVIDIA GPU / Windows arm64）的 12 个组合中，有多少同时满足 ①CPU 可运行 ②可流式 ③可分发给未知用户？

答案：**2 / 12**，其中只有 1 格有本机运行时实测。三个"空集"格可仅凭厂商文档判定不存在，无需实验。

本文的主要贡献不是"哪个最快"，而是**把失败写成了可复核的一等结果**：每个空格都指向一条官方依据，每个降级都指向一个外部事实而非主观体验。

**Abstract.** On-device ASR runtime selection is folk knowledge: each project re-tries the same dozen combinations and keeps its failures private. We formalise the question — under the constraint "ship to an unknown user's Windows desktop", how many of 12 (4 runtimes × 3 platforms) combinations are CPU-capable, streaming, and distributable? Answer: 2 of 12, only one of which we have measured locally. Three cells are provably non-existent from vendor documentation alone. The contribution is not speed; it is making failure a first-class, checkable result.

---

## 1 问题

### 1.1 现象

端侧 ASR 社区的公开材料高度同质：模型卡给 CER/WER，运行时仓库给"支持平台"勾选表，博客给"我换了 XX，快了 N 倍"。
三者都缺同一件事：**约束**。

- 模型卡不知道你要把它发给谁；
- 支持矩阵的 ✅ 不区分"能编译"和"有预编译轮子"；
- "快了 N 倍"通常换了模型（于是测的是模型差异，不是运行时差异）。

于是最常见的失败不是"选了个慢的"，而是"选了个**原理上装不到用户机器上**的组合"——比如在纯 CPU 笔记本上选 TensorRT，或给 Windows on ARM 选一个只有 `win_amd64` 轮子的库。

### 1.2 形式化

设运行时集合 $R$、平台集合 $P$，约束集 $C$：

| 约束 | 判定问题 | 为什么必须单列 |
|---|---|---|
| $c_1$ CPU 可运行 | 无 GPU 时能否推理 | 目标用户是普通笔记本 |
| $c_2$ 流式 | 能否增量出字（会议实时字幕） | 决定产品形态，不能事后补 |
| $c_3$ 可分发 | 是否有该平台**预编译**产物 | "能编译"≠"能发给用户" |

求 $|\{(r,p) \in R \times P : c_1 \wedge c_2 \wedge c_3\}|$。

**注意 $c_3$ 的措辞**：不是"支持该平台"，是"有预编译产物"。这一条把大量"理论上支持"的格子变成空集，也正是本测绘最有价值的部分。

---

## 2 相关工作与差异

| 工作 | 提供了什么 | 缺什么 |
|---|---|---|
| sherpa-onnx / sherpa-ncnn 文档 | 各运行时的平台勾选表、模型下载、单点速度 | 不跨运行时比较；✅ 不区分预编译与可编译 |
| whisper.cpp / llama.cpp | 单文件二进制、量化矩阵、CPU 性能表 | 只覆盖自家格式 |
| FunASR / SenseVoice 模型卡 | 同数据集 CER、量化档体积 | 不与其它运行时对位 |
| 各类"端侧 ASR 横评"博客 | 观感、速度对比 | 常混模型差异；极少记录失败原因 |

**差异**：本文不产生新模型、不产生新运行时，只把"约束 × 组合"的**可判定性**补齐，并强制失败可引用。
换句话说：别人给答案，本文给**问题的定义域**。

---

## 3 方法

### 3.1 锚点模型：控制变量

若拿 ONNX 上的 SenseVoice 去比 ncnn 上的 zipformer，比出来的是**模型差异**。这类对比在社区里到处都是，结论无效。

因此整张表挂在**能跨格式的锚点模型**上。已确认该锚点存在：

| 格式 | SenseVoice 实现 | 证据 |
|---|---|---|
| ONNX | ✅ 本项目主用 | `sherpa_onnx 2.0.0` + `onnxruntime 1.31.0` |
| ncnn | ✅ 2025-09 起 | `sherpa-ncnn` release tag `asr-models`（2025-09-13）发布 6 个 SenseVoice ncnn 模型包（int8 / float32 / 默认 × 两版日期） |
| GGUF | ✅ 官方发布 | `FunAudioLLM/SenseVoiceSmall-GGUF`：q8 ≈ 235 MB，8 线程 8.01% CER（184 条普通话） |
| TensorRT | ⚠️ 需自行 ONNX→engine | 且必须 NVIDIA GPU |

一个模型、四种运行时、同一段音频 → 控制变量才成立。

### 3.2 证据分级（本稿的自我约束）

每个格子必须标一级，**级别决定它能被怎样引用**：

| 级别 | 含义 | 可被引用为 | 格数 |
|---|---|---|---|
| L1 | 官方文档 / 包矩阵 | 结论 | 5 |
| L2 | 本机运行时实测 | 结论（限本机配置） | 1 |
| L2′ | 只做了模型侧取证（存在性 / 结构 / md5），运行时未跑 | **仅"模型在"，不是"能跑"** | 1 |
| L3 | 推断或未验证 | **仅"值得试"** | 5 |

把 L2′ 单独拆出来是必要的：口语里"测过"会把**模型取证**与**运行时实测**粘在一起，而这两件事回答的是不同问题。

### 3.3 不测清单（并说明为什么不测）

诚实标注"不测"比编一个估算值有价值：

- **功耗**：Windows 读不到 RAPL，物理功耗需外接功率计；代理指标跨机型不可比。**放进去会让人误以为测过**，故整维砍掉。
- **CPU 型号横评**：换机器结论就变，那是硬件评测，不是运行时选型。
- **跨数据集 CER 横比**：各模型测试集不同，横向比是伪对比。只报同数据集自测值并注明来源。
- **全部 192 格**（4 运行时 × 4 线程 × 3 平台 × 4 模型）：个人做不完，且大部分格子不改变结论。只填能改变结论的。

---

## 4 结果

主图见 `docs/bench/matrix-zh.svg`（中文）与 `matrix-en.svg`（English）；`matrix-{zh,en}.png/.pdf` 为导出版。

### 4.1 核心计数

$$|\{(r,p): c_1 \wedge c_2 \wedge c_3\}| = 2$$

- `sherpa-onnx × x86-64 CPU` —— 通过，且**有本机实测**（L2）
- `sherpa-ncnn × x86-64 CPU` —— 通过，但**运行时未实测**（L2′）

### 4.2 两类空集，性质不同

**A. 原理性空集（引文档即可判定，无需实验）**

| 格 | 判定依据 |
|---|---|
| TensorRT × x86-64 CPU | NVIDIA 官方 FAQ：*"Does TensorRT run on a CPU? No."*；Triton 支持矩阵同为 `GPU ✅ / CPU ❌` |
| TensorRT × Windows arm64 | 无 Windows arm64 target；Jetson 走 Linux / JetPack |
| sherpa-ncnn × Windows arm64 | `sherpa-ncnn 2.1.15` 只有 cp313 `win32` / `win_amd64`（PyPI 实测），无 `win_arm64` |
| GGUF × 流式 | 现有 GGUF ASR 基本为整段输入（SAN-M encoder + CTC），不适合实时字幕 |

**B. 条件性不适用（能用，但代价改变产品形态）**

- TensorRT × x86+GPU：engine 默认只与构建它的设备兼容，hardware compatibility 仅 Ampere 及以后，11.3 起不再支持 JetPack → **一机一引擎**，在"给未知用户发安装包"的场景里几乎不可用。
- GGUF × x86+GPU：单文件、零依赖，是分发体验最好的一档，但它换的是"离线批量"而非"实时字幕"。

### 4.3 这张图目前缺的一列

我们唯一亲手跑过 ncnn 的平台是 **Android arm64 + Vulkan**（改造 APK，2026-10-25 装机成功），而图的平台列里没有它。
这暴露了测绘范围与自身证据不匹配：**图的列选的是"用户装到哪"，我们跑过的是"手上有什么设备"**。
在补列之前，Android 的体验不得当作图上的数据引用。

---

## 5 阴性结果

完整记账见 `docs/negative-results.md`。其中两条直接决定了本文的方法：

- **功耗维度被整维砍掉**（N-01）。原因不是不重要，是**测不了且不可比**——放进去等于假装测过。于是本文只留二维。
- **"模型取证 ≠ 运行时实测"**（见 §3.2 的 L2′）。模型文件存在、结构对得上、md5 一致，只说明"这个模型是它宣称的那个"；
  说明不了"它在这台机器上多快"。本文把这两件事分成两级，就是为了不让前者偷偷顶替后者。

这两条的共同点：**它们的价值在于标出了一个我们本来会含糊过去的地方。**

---

## 6 效度威胁（Threats to validity）

**构念效度**：$c_3$ 用"有无预编译产物"代理"能否分发"。这对 pip/npm 生态合适，对"我们自己的安装包"偏严——我们本可以自己编 arm64 再打包。
→ 该代理会**低估** ncnn 与 GGUF 的 arm64 可用性。本文接受这一低估，理由是：自编译意味着每次升级都要重走一遍工具链，这不是选型优势。

**内部效度**：锚点模型控制了模型差异，但**没有控制量化档**（int8 vs fp32）与线程数。当前 L2 实测只覆盖 int8 / 默认线程。

**外部效度**：L2 实测只有一台机器（Windows x86-64）。RTF 不可外推到别的 CPU，本文也不做这种外推。

**结论效度**：结论是**计数**，不是排序。"2 格通过"不蕴含"这两格够快"。速度结论必须等 §7 的数据。

---

## 7 可复现性与下一步

**复现**：`docs/bench/README.md` §重新生成 给出图的再生成命令；数据来源逐条列在 §数据来源。

**第一优先实验**（决定本稿能否升级为 benchmark）：
把 SenseVoice 在 **GGUF** 上跑通，与现有 **ONNX** 基线对齐**同一段音频**，产出两个数：RTF、CER。
理由：这是唯一能同时验证"同模型跨格式"与"流式/非流式代价"的一格；两条数据出来，整张表就有了骨架。

**第二优先**：`sherpa-ncnn` 在本机装上并跑 SenseVoice（把 L2′ 升为 L2），顺带回答 §6 构念效度里的低估问题。

**第三优先**：加 `Android arm64` 列，把已有真机数据纳入。

---

## 8 可证伪条件

本稿结论应被推翻，当且仅当出现以下任一情况：

1. 找到某个 $(r,p)$ 满足 $c_1 \wedge c_2 \wedge c_3$ 但本文判为不通过（**漏判**）；
2. 本文判为通过的格子，在未知用户的 Windows 机器上无法流式运行（**误判**）；
3. $c_3$ 的代理被证伪：自编译 + 打包在工程上被证明成本可忽略（**构念失效**）。

条件 1 的具体触发点已知：`sherpa-ncnn` 若发布 `win_arm64` 轮子，`sherpa-ncnn × Windows arm64` 立即从空集转为候选。**这类"监视某个 release 就能更新结论"的格子，正是这张表值得长期维护的原因。**

---

## 9 如何引用

本稿没有 DOI，引用请给**版本 + commit**（仓库演进中，结论会变）：

```
Offlisten project. "The Distributable Empty Set: A Usability Survey of
4 On-Device ASR Runtimes × 3 Platforms." Working paper, v2, 2026-11-12.
https://github.com/peaceaddpaasion/Offlisten  (commit <sha>)
```

若只需要那张图，引用 `docs/bench/matrix-en.pdf` 并注明版本日；**不要拿它当性能 benchmark**——它是选型图，不是测速表。

---

*本文的立场：端侧这件事上，轮子不是不够圆，是没有人画过一张标着"此路不通"的地图。*
