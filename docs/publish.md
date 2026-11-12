# 发布占位清单（个人项目 · 不求赚钱 · 只要留痕）

## 0. 现在做到哪了

| 项 | 状态 |
|---|---|
| 本地 git 仓库 | ✅ `main`，提交历史完整（`git log --oneline`），工作树干净 |
| 可对外读的 README | ✅ 已重写（不再出现 `whisper-ext` 旧名） |
| LICENSE | ✅ MIT |
| 版本 tag | ✅ `v0.2.1` |
| **远端仓库（公开占位）** | ❌ **没做**：本机 `gh` 未安装，仓库无 remote，无凭据 |

公开占位是唯一还缺的一步，而且**必须你本人操作**（涉及你的 GitHub 账号）。

## 1. 公开占位的两条路

### 路线 A：gh CLI（一条命令，推荐）

```powershell
winget install --id GitHub.cli -e
gh auth login                       # 选 GitHub.com → HTTPS → 浏览器授权
cd D:\projects\whisper-ext
gh repo create offlisten --public --source=. --remote=origin --push `
  --description "100% offline meeting transcription. No account, no cloud. 12.5 KB MV3 extension + local ASR engine."
```

### 路线 B：网页建仓再推（不想装 gh）

1. 打开 `github.com/new`，仓库名 `offlisten`，Public，**不要**勾选 README/.gitignore/License（本地已有）。
2. 进到仓库根目录，再执行：

```bash
git remote add origin https://github.com/<你的用户名>/offlisten.git
git push -u origin main --tags
```

进仓库根目录的三种写法（`cd /d/projects/...` 只在 Git Bash 里成立，cmd 里 `/d` 是切盘符的开关，会直接报「系统找不到指定的路径」）：

| Shell | 命令 |
|---|---|
| cmd | `pushd D:\projects\whisper-ext` |
| PowerShell | `Set-Location D:\projects\whisper-ext` |
| Git Bash | `cd /d/projects/whisper-ext` |

## 2. 建完立刻做的四件事（占位的实际价值在这里）

1. **About 栏**填这句（网页建仓时已写过，别在覆盖时丢掉）：

   > 本地离线会议转写（MV3 扩展 + sherpa-onnx/SenseVoice 引擎）录匣，性能和功能的精确权衡，部署灵活度和性能的博弈。

   Topics 建议：
   `offline` `speech-to-text` `asr` `sherpa-onnx` `sensevoice` `privacy` `mv3` `chrome-extension` `chinese`
   —— 这几个词是**别人能找到你**的入口，比名字重要。
2. **Pin 到个人主页**。简历上的链接比任何 SEO 都快。
3. **发第一个 Release**，附上 `dist/whisper-ext-0.2.1.zip`。Release 页是"能下载"的证据。
   > `dist/` 和 `*.zip` 已在 `.gitignore` 里，**不要提交进仓库**——二进制走 Release 附件，再单独 `git commit` 会让仓库历史变脏。
4. **README 首屏保持三行以内**：一句承诺 + 四个数字。技术面试官只看前 15 秒。

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

## 7. 未验证

- `gh repo create` 的参数在本机 gh 版本上的具体行为（**gh 尚未安装**，未实测）。
- GitHub 上 `offlisten` 这个仓库名/用户名是否已被占用（RDAP 只查域名，不查 GitHub）。
- 商店审核对 `clipboardWrite` + `storage` 的具体要求。
