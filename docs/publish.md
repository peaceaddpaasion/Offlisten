# 发布占位清单（个人项目 · 不求赚钱 · 只要留痕）

## 0. 现在做到哪了

| 项 | 状态 |
|---|---|
| 本地 git 仓库 | ✅ `main`，提交历史完整（`git log --oneline`），工作树干净 |
| 可对外读的 README | ✅ 中文 + 英文两份，互相有语言切换 |
| LICENSE | ✅ MIT，持有人写实名 |
| 版本 tag | ✅ `v0.2.1` |
| 远端仓库 | ✅ **已公开**（2026-11-13），`api.github.com/repos/peaceaddpaasion/Offlisten` 匿名 200 |
| Release | ✅ `v0.2.1`，附件 `whisper-ext-0.2.1.zip`（12,787 B） |
| 数据账本 | ✅ `METRICS_TOKEN` 已配（fine-grained，Administration + Secrets 读写），流量段每天入库 |
| CI | ✅ `.github/workflows/ci.yml` + `metrics.yml` |
| 贡献入口 | ✅ `CONTRIBUTING.md` + issue 表单 + PR 模板 |

## 1. 切公开这一步（已完成）

2026-11-13 用 fine-grained PAT 调 `PATCH /repos/:owner/:repo {"private": false}` 完成，同时设了 homepage 指向 HF Space。

同一件事也可以用网页做：Settings → General → 拉到最底 **Danger Zone** → Change visibility → Public。
公开后会被搜索引擎与镜像站抓取，撤回删不干净。

两个副作用值得记下来：

- **README 里的相对路径图片，私有期一律是破图**。GitHub 渲染时把图交给 camo 匿名抓取，私有仓对匿名请求返回 404，页面显示「图片来源无效」。这跟 markdown 语法无关，公开后自动恢复。
- **`/traffic/*` 与 `Secrets` 两个接口要的权限档位不同**。`Administration` 光有 `Read` 能读流量但改不了可见性，`Secrets` 默认不给。要三个都给：`Administration: Read and write`、`Secrets: Read and write`、`Contents: Read and write`。

## 2. 公开时该做的五件事

1. **About 栏**填这句：

   > 本地离线会议转写（MV3 扩展 + sherpa-onnx/SenseVoice 引擎）录匣，性能和功能的精确权衡，部署灵活度和性能的博弈。

   Topics 建议：
   `offline` `speech-to-text` `asr` `sherpa-onnx` `sensevoice` `privacy` `mv3` `chrome-extension` `chinese`
   这几个词是**别人能找到你**的入口，比名字重要。
2. **Pin 到个人主页**。简历上的链接比任何 SEO 都快。
3. **发第一个 Release**，附上 `dist/whisper-ext-0.2.1.zip`。Release 页是"能下载"的证据。
   > `dist/` 和 `*.zip` 已在 `.gitignore` 里，**不要提交进仓库**。二进制走 Release 附件。
4. **README 首屏保持三行以内**：一句承诺 + 四个数字。
5. **确认数据账本开始记数**。`Metrics` 工作流每天 03:17 UTC 快照一次。转公开后第一周去看
   `docs/metrics/history.csv` 是否出现非零段，那是「真的有人来了」的第一个客观证据。
   流量接口只认 fine-grained token 的 Administration 权限，内置 `GITHUB_TOKEN` 打它 403，
   所以 secret `METRICS_TOKEN` 不能省。徽章是自渲染的，不必依赖 shields。

## 3. 为什么用 MIT 而不是 AGPL

- 你的目标是**留痕 + 造福**，不是防止别人商用。AGPL 会挡掉一部分"想拿去用"的人，正好和传播相反。
- MIT 下被 star、被 fork、被引用，才会变成简历上的可信信号。
- 真担心被白嫖商业化，正确做法不是换协议，是**你先把 Lite 档做出来**——96 MB 能跑，别人抄一个壳没有意义。

## 4. 命名：为什么不叫「离线留学宝」

三条都已实测/可验证：

1. **`录影` 是事实错误**。本产品只处理音频（`soundcard` / WASAPI loopback 抓的是音频流），不含任何视频编码。叫"录影机"会让人以为能录屏。
2. **"留学宝"把通用能力锁死在一个场景**。引擎本身是通用的（会议、访谈、课堂、播客都能用），名字写死"留学"，以后扩场景就要改名，而改名会动到存档路径。
3. **"宝"是消费品后缀，在简历上是负分**。招聘方想看的是流式音频、模型量化、进程间通信、MV3 权限模型这些硬东西；"离线留学宝"读起来像校园创业比赛的项目名，恰恰把这些盖住了。

**"可靠 + 离线"不该进名字，该进第一句话**：
- 名字负责**被认出来**（短、独特、可搜）
- 句子负责**给承诺**（可验证）
- `Offlisten` 已经承担了 `off`（离线）；再加"离线"是重复。"可靠"是形容词，任何产品都能自称——**可验证的只有"拔掉网线它还在写"**。

## 5. 如果确实想要一个"商务向"的中文别名

可以，但用**副标题/分类词**的位置，不要替换品牌：

| 用法 | 写法 |
|---|---|
| GitHub About | `录匣 Offlisten — 离线会议转写` |
| 商店分类 | `商务办公` |
| B 站/小红书标题 | `录匣｜离线会议记录，拔掉网线也能用` |
| 简历一行 | `Offlisten 录匣 — 本地离线会议转写（MV3 扩展 + sherpa-onnx/SenseVoice 引擎）` |

候选（**都会与「录匣」共享"匣"字，属于家族命名，双刃**）：`纪要匣`、`留档`。
如果用它们，说明这是子产品线（面向商务会议），不是替代主名。

## 6. 红海 + 个人项目的判据（和商业项目不同）

| 商业项目要做 | 你不需要做 |
|---|---|
| 商标检索（CNIPA 9/42 类） | ✅ 不做也行，个人非商用风险低 |
| `.com` 十年版权防御 | ✅ 不必，先占 handle 就够 |
| 官网 / SEO / 备案 | ✅ 全跳过，GitHub Pages 都不要也可以 |
| 商店审核（截图/隐私声明/单一用途） | ✅ 等真要发商店再说 |

**必须做的只有三件**：公开仓库、可下载 Release、README 首屏能读懂。
因为你的产出物不是产品，是**"这个人能独立把离线 ASR 全链路做出来"的证据**。

## 7. 作为扩散项目的基础

想让别人能拿去改，光有代码不够——得让"改"这件事的启动成本足够低。已经就位的四件：

| 件 | 位置 | 作用 |
|---|---|---|
| 模型获取方式 | `CONTRIBUTING.md` | 三个文件的下载地址 + 归档字节数。**这是最大的门槛**：229 MiB 模型不在库里，没有这一节，别人 clone 下来跑不起来 |
| 契约 | `docs/contract.md` | 换实现不用读代码，只读四个端点 |
| 零构建扩展 | `extension/` | 8 个文件，load unpacked 即可；没有 npm install，改一个按钮不用装 Node |
| CI | `.github/workflows/ci.yml` | 文档引用、语法、打包三项，fork 后开箱能跑 |

### 要不要设成模板仓库

Settings → Template repository 勾上，别人能「Use this template」，得到一份**干净历史**的副本（不是 fork 关系，不带你的提交记录）。

判断：**现在不收**。模板适合「拿来起新项目」，而这个仓库的框架（契约 + 论文式测绘 + 负结果册）是为这个特定产品长出来的，别人拿去做别的产品，先得删一半。等真有人问"能不能拿来当底子"再开，比现在开了没人用更实在。

### CI 的成本口径（影响要不要公开）

| 仓库可见性 | Actions 额度 |
|---|---|
| 公开 | 标准 runner **免费且不限量** |
| 私有 | 2,000 分钟/月（Free 计划），之后按分钟计费 |

Windows runner 按 **2 倍** 计费（$0.010/min，Linux 是 $0.006）。所以打包 job 固定在 `windows-latest` 只跑一次，不铺 matrix——不是为了省这几分钟，是为了不让后面的人一句"改个 matrix 试试"把额度吃光。

CI 的诚实边界写在 `CONTRIBUTING.md` 里：**引擎跑不起来**。runner 上没有 229 MiB 模型，也没有 WASAPI 与交互式 Windows 会话。所以引擎改动的证据只能是本机输出，PR 模板里专门留了一栏"实测记录"。

### 构建放本机、CI 只做检查——这条分工的理由

| | 本机 | CI |
|---|---|---|
| 现在做 | PyInstaller onedir + Inno Setup 出 exe | 文档引用、语法、扩展打包 |
| 能否验证 exe | 能：真实声卡、WASAPI loopback、可交互桌面 | **不能**：无音频设备、无交互会话、无模型 |
| 反馈速度 | 分钟级 | 排队 + 装依赖 + 打包，一轮十分钟起 |
| 可追溯性 | 弱（"我机器上打的"） | 强（tag → commit → 二进制） |

结论分三段，不要合并：

1. **P1/P2 阶段在本机构建。** PyInstaller 的 hidden-import 与 DLL 收集要反复试，CI 十分钟的反馈循环没法用；
   更要紧的是 CI 产出的 exe 只能证明"能启动"，证明不了"能转写"——绿了不等于可用。
2. **稳定之后把构建搬进 CI，目的不是验证而是可追溯。** 加 `actions/attest-build-provenance`，
   把 exe 的 sha256 写进 release notes，别人才能核对「这个 tag 的源码 + 这份权重 = 这个二进制」。
   这才是"别人能修改、能复现"的实质，而不是口号。
3. **验证永远在本机。** 这一条已写进 `CONTRIBUTING.md` 与 PR 模板的"实测记录"栏，不会因为 CI 变绿而放松。

CI 真要在构建里拿权重时，来源按可靠性排：

| 来源 | 能否 pin 版本 | 备注 |
|---|---|---|
| 自己的 HF **model repo** | ✅ revision/commit | `hf_hub_download` 带缓存与断点续传，**首选** |
| 自己 Release 的公开直链 | ⚠️ tag 固定即固定 | 无需 token，但无分片续传 |
| 上游 `FunAudioLLM/SenseVoiceSmall` | ❌ | 上游可能换文件，构建不可复现 |
| HF **bucket** | ❌ 无版本 | 同名覆盖即丢旧版，CI 两次拉到的字节可能不同，**不要用** |

## 8. 未验证

- 仓库切成 Public 之后的实际索引速度与搜索可见性。
- 商店审核对 `clipboardWrite` + `storage` 的具体要求。
- CI 在真实 runner 上的首次运行（工作流已通过 YAML 与本地等价命令校验，但没有在 GitHub 上跑过）。
