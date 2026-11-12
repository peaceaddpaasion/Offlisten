# whisper-ext

Whisper 本地转写的浏览器扩展。**只做两件事：读本机转写、遥控本机引擎。**

它不是一个能独立工作的产品：ASR、会议存档、SSE、导出全部在本地 Python 后端（另一个仓库 `whisper`）里。
本仓库只包含 MV3 扩展代码、API 契约和自检脚本。

## 为什么单独一个仓库

- 扩展的发布节奏与后端不同：扩展要过浏览器商店审核、要固定 ID、要单独发版。
- 扩展的运行环境被限制住：只有 JS，不能 spawn 进程、不能读文件系统、不能打包原生引擎。
- 主项目 `whisper` 目前不是 git 仓库，扩展留在里面无法独立版本化。
- 因此：**两处代码，单向同步**。本仓库是扩展的事实源；`whisper/extension/` 只是内测加载副本，由
  `scripts/sync-to-main.ps1` 从本仓库覆盖过去，禁止反向手改。

## 安装（当前阶段：unpacked）

1. 启动本地后端（在主项目里）：
   ```
   run_transcriber.bat live --web-live --headless
   ```
   控制台会打印一行带 token 的完整地址。
2. 打开 `chrome://extensions` 或 `edge://extensions`，开启「开发者模式」。
3. 「加载已解压的扩展程序」→ 选本仓库根目录（含 `manifest.json` 的那一层）。
4. 点扩展图标，把那行完整地址粘进输入框 → 「保存并连接」。

## 现在能做什么

| 能力 | 说明 |
| --- | --- |
| 连接状态 | `/health`，显示端口与段数 |
| 最近 3 段 | `/transcript.json`，译文行带「译 」前缀 |
| 复制全文 | 写入剪贴板，带事实源表头（标明译文非原文） |
| 打开 live 页 | 新标签打开同一 token 的 live 页，交给第三方 AI 插件读 DOM |
| 控制面板 | 开始/停止、引擎、音源、译文开关（`/api/control/*`） |
| 只读降级 | 后端没挂运行核心时明确显示只读，不造假按钮 |

## 现在不能做什么（如实）

- **不能自动发现后端**。扩展读不到 `web_live.json`，token 只能手粘；后端重启 token 变了要重粘。
- **不能独立运行**。没起 Python 后端时它只是一个连不上的弹窗。
- **不能跑引擎**。MV3 service worker 不是常驻进程，没有 `child_process`。
- **没走 Native Messaging**。`nativeMessaging` 权限未申请，`connectNative` 未使用（见 docs/contract.md 末尾）。
- **扩展 ID 随加载路径变化**。实测同一份代码：从 `whisper/extension` 加载得到 `ajgmcdhh…`，
  从本仓库加载得到 `hbfbckcfmnnakaekleoadicgnghofcij`。unpacked 的 ID 由路径派生，
  只有商店安装或 manifest 加 `key` 才固定。**Native Messaging 的 `allowed_origins` 必须写死 ID，
  所以要做 NM，得先定 ID 策略。**

## 脚本

```
node scripts/contract_check.js          # 对正在运行的本机后端验一遍 API 契约
powershell -File scripts/pack.ps1       # 产出 dist/whisper-ext-<version>.zip（只含 4 个运行文件）
powershell -File scripts/sync-to-main.ps1   # 单向同步到 ..\whisper\extension\
```

`contract_check.js` 默认从 `..\whisper\web_live.json` 取地址，也可：

```
node scripts/contract_check.js --url "http://127.0.0.1:47813/?token=..."
node scripts/contract_check.js --discovery D:\projects\whisper\web_live.json
```

## 版本

`manifest.json` 的 `version` 是本仓库唯一版本号。改动扩展行为必须同时更新它，
否则商店审核与「已加载版本」无法区分。契约变更见 `docs/contract.md` 的变更记录。
