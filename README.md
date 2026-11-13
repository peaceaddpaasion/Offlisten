# 录匣 Offlisten

<sub>[English](README.en.md) · 中文</sub>

**100% 离线的会议 / 课堂转写。没有账号，没有云端，拔掉网线它还在写。**

> Offlisten — 100% offline speech-to-text for meetings and lectures.
> No account, no cloud, no telemetry. A 12.5 KB browser extension plus a local ASR engine.

当前状态：**本地可用**。引擎 `4,160` 行 Python（`engine/`），扩展 `v0.2.1`（`extension/`，12.5 KB）。两者同仓库，靠契约解耦。

---

## 造轮子之前，先看这张图

端侧 ASR 不缺轮子，缺的是有人把试过的路记下来。

4 个运行时 × 3 个平台一共 12 格，只有 2 格同时满足「CPU 能跑 · 流式 · 能装进别人的机器」。
其余 10 格逐格写了为什么不行，能引官方文档的不靠猜。

这 2 格里我们只拿 1 格做产品，另 1 格也照原样写进文档。

![端侧 ASR 运行时可用性矩阵：4 个后端 × 3 个平台，12 格里只有 2 格通过](docs/bench/matrix-zh.png)

<sub>English version: [`docs/bench/matrix-en.png`](docs/bench/matrix-en.png) · 逐格原因与证据分级见 [`docs/bench/README.md`](docs/bench/README.md)</sub>

- 图是怎么推出来的、凭什么能被证伪 → [`docs/paper.md`](docs/paper.md)（工作稿）
- 试过并放弃的路 → [`docs/negative-results.md`](docs/negative-results.md)（9 条，附判定与证据路径）
- 它被打开、被下载了多少次 → 下面的[下载与浏览](#下载与浏览)一节

---

## 它做什么

- 把**系统声音**或**麦克风**实时转成文字（中文 / 英文 / 日文 / 韩文 / 粤语）
- 每场会议自动成档：按日期分组，可改标题、标星、导出
- 过程不联网：不上传、不登录、不埋点

## 四个可验证的数字

| 项 | 实测值 | 怎么来的 |
|---|---|---|
| 扩展包体积 | **12.5 KB** | 8 个文件，**无构建、无 npm 依赖**，`pack.ps1` 产出 |
| Lite 模型档 | **96 MB** | 英文流式 70 + 中文 14M 25 + VAD 1（只发 int8） |
| 标准模型档 | **229 MB** | SenseVoice int8，5 语言，带标点 |
| 真机自检 | **10 / 10** | headless Edge 真实加载扩展并点到页面里 |

> 不发 fp32：`model.onnx` 895 MB 与几个 `.tar.bz2` 共约 2.2 GB，都是开发期产物。

## 为什么说"离线"而不是"本地优先"

"本地优先"是**策略**，可以随时改成上传；"离线"是**可验证的承诺**：断网演示十秒就能证伪。
所以对外只说后者，代码里也只做后者：没有上传路径，`host_permissions` 只声明 `127.0.0.1` / `localhost`。

## 架构：两个可独立运行的半边，一条契约

```
录匣 Offlisten
├─ engine/       Python 引擎（4,160 行）ASR / 采集 / 存档 / SSE / 导出 / 悬浮字幕
│                pc_transcriber.py  web_live.py  live_core.py  win32_overlay.py  overlay.py
│                web_live/（live·history·meeting 页面）  tools/  acceptance/
├─ extension/    MV3 扩展（8 文件 / 12.5 KB）只做两件事：读本机转写、遥控引擎
│                manifest.json  popup.html  popup.js  service_worker.js  icons/
├─ docs/         契约、分发、ADR、工作稿、负结果册、可用性矩阵、数据账本
├─ tools/        打包、契约自检、发行清单、漂移检查、HF 推送、计数快照
└─ space/        Hugging Face Space 在线演示（上传音频 → 转写 + RTF），不依赖 WASAPI
```

**引擎不依赖扩展**：拔掉扩展它照常工作，自己会起一个 `127.0.0.1` 的 live 页面。
**扩展也不依赖引擎的代码**：只依赖 `docs/contract.md` 里钉死的 4 个端点。

所以这两半可以分别发版、分别卸载、分别替换。引擎现在跑在 Python + sherpa-onnx 上，换成别的语言也行：
只要契约不变，扩展一行都不用改。

## 安装（当前阶段：unpacked）

1. 启动本地后端，控制台会打印一行带 token 的完整地址。
2. 打开 `chrome://extensions` 或 `edge://extensions`，开启「开发者模式」。
3. 「加载已解压的扩展程序」→ 选本仓库的 **`extension/`** 目录（含 `manifest.json` 那一层，不是仓库根目录）。
4. 点扩展图标，把那行完整地址粘进输入框 → 「保存并连接」。

> 从仓库根目录加载会失败：根目录没有 `manifest.json`。这是把扩展收进子目录的代价，也是它该在的位置。

## 自检

```bash
node tools/contract_check.js          # 对运行中的后端验 19 项契约
python tools/check-links.py           # 所有 .md 里的相对链接是否真实存在（区分大小写）
python tools/name_cluster.py          # 候选名聚类与"打错就串"检测（纯标准库、离线）
pwsh tools/pack.ps1                   # 打包扩展，并校验 manifest 引用的文件真实存在
python tools/engine-drift.py          # engine/ 与开发工作区是否漂移（退出码 1 = 有差异）
python tools/build-dist.py --source <后端> --compress   # 发行体积实测
python tools/metrics.py --report      # 把记下的下载/浏览历史打成一张表（数据见 docs/metrics/）
python tools/metrics.py --write-readme   # 用那份历史重写本文件里的计数表
```

`contract_check.js` 默认从 `..\whisper\web_live.json` 取地址，也可显式指定：

```bash
node tools/contract_check.js --url "http://127.0.0.1:47813/?token=..."
node tools/contract_check.js --discovery D:\projects\whisper\web_live.json
```

## 不做什么

- **扩展不能独立工作**，也不能跑模型：MV3 service worker 不是常驻进程，没有 `child_process`，商店也禁止包内捆绑原生可执行文件。
- **扩展抓不到 Zoom / 腾讯会议的桌面客户端**：`tabCapture` 只能抓标签页。抓全系统声音靠后端走 WASAPI loopback。
- **没走 Native Messaging**：`nativeMessaging` 权限未申请，`connectNative` 未使用（见 `docs/contract.md` 末尾）。
- **不做云端兜底**：识别质量不够时，选择是换更大的本地模型，而不是上传。
- **不做界面 i18n**：当前全中文；抽 i18n 会打断真机验收里的中文断言，收益为零。

## 已知限制

- 扩展读不到后端的发现文件，**token 只能手粘**；后端重启换 token 要重配。
- **扩展 ID 随加载路径变化**。实测同一份代码：从主项目 `extension/` 加载得到 `ajgmcdhh…`，
  从本仓库加载得到 `hbfbckcfmnnakaekleoadicgnghofcij`。unpacked 的 ID 由路径派生，
  只有商店安装或 manifest 加 `key` 才固定。Native Messaging 的 `allowed_origins` 必须写死 ID，
  所以要做 NM，得先定 ID 策略。
- 中文名 `录匣` 是造词，零搜索量（这是代价，不是红利）。
- Lite 档的 14M 中文模型对术语、口音、远场会掉字，且不出标点。

## 两处代码与工作区的关系

开发在 `D:\projects\whisper` 里跑，仓库里的是**发布快照**。两边会漂移，所以两边各有一道闸：

| 方向 | 机制 |
|---|---|
| `extension/` → `whisper\extension` | `tools/sync-to-main.ps1` 按 SHA256 单向覆盖，**禁止反向手改** |
| `engine/` ← 工作区 | `tools/engine-drift.py` 只比对不自动改；`--copy` 才以仓库为准覆盖回去 |

扩展是「仓库为准」，引擎是「工作区为准」。因为引擎在那里跑着、带日志和临时改动，
反过来以工作区覆盖仓库会把没验证的改动直接发出去。两边都不做双向自动合并。

## 版本

`extension/manifest.json` 的 `version` 是本仓库唯一版本号。改动扩展行为必须同时更新它，
否则商店审核与「已加载版本」无法区分。契约变更见 `docs/contract.md` 的变更记录。

## 下载与浏览

<!-- metrics:begin -->
![downloads](docs/metrics/badge-downloads.svg) ![hf](docs/metrics/badge-hf.svg) ![views](docs/metrics/badge-views.svg) ![stars](docs/metrics/badge-stars.svg)

![下载量与仓库浏览的逐日曲线](docs/metrics/stats.svg)

<sub>数据截至 2026-11-13。缺数据的日子断线，不补 0；口径见 [`docs/metrics/README.md`](docs/metrics/README.md)。</sub>
<!-- metrics:end -->

## 文档

| 文件 | 内容 |
|---|---|
| `engine/README.md` | **引擎**：两条管线的区别、模块职责、VAD 门限为什么不是常数、怎么跑起来 |
| `extension/` | MV3 扩展本体（8 文件 / 12.5 KB）；加载时选这个目录 |
| `docs/paper.md` | **工作稿**：可分发空集测绘，含证据分级、效度威胁、可证伪条件 |
| `docs/negative-results.md` | **负结果册**：9 条放弃/改法的路，每条附判定与证据路径 |
| `docs/bench/README.md` | 可用性矩阵成品：12 格逐格原因、证据分级、决策树、PR 模板（图见 `matrix-zh` / `matrix-en` 两套） |
| `docs/research-plan.md` | 长期展望：端侧 ASR 运行时可用性地图（维度定义、最小实验集、社区形态） |
| `docs/adr-001-runtime.md` | ADR：ncnn 与 ONNX 曾并存，主线定为 ONNX（含取舍依据，部分理由已作废并标注） |
| `docs/contract.md` | 扩展与后端之间的 API 契约（唯一接口约定） |
| `docs/distribution.md` | 后端分发：**实测体积账**、三条路线、P0→P5、main/Release/HF 三条通道的硬上限 |
| `dist-manifest.json` | 发行清单：逐文件 `sha256` + 体积 + 被故意排除的文件及原因 |
| `tools/build-dist.py` | 生成上表的脚本，`--compress` 可实测安装包下载体积 |
| `docs/metrics/README.md` | **数据账本**：平台各自留不住什么、三种值状态（数字 / 0 / 空）、每日快照怎么跑 |
| `docs/tech-notes.md` | 技术素材与交付路径：体积档、ncnn 权衡、MSIX 约束 |
| `docs/naming.md` | 命名与定位：候选判定、域名实测、双语口径 |
| `docs/naming-tooling.md` | 命名工具链：能力核查、分工边界、聚类实测 |
| `docs/publish.md` | 发布占位清单（GitHub + Release + 命名判定） |
| `extension/icons/README.md` | 图标源文件、配色，与逐尺寸光栅化的再生方法 |
| `CONTRIBUTING.md` | 怎么改：模型下载地址、契约纪律、提交规范、CI 会检查什么 |
| `CITATION.cff` | 引用信息（GitHub 侧栏会显示「Cite this repository」） |

## License

MIT。随便用、随便改、随便商用，不要求署名（署名更好）。
