# 扩展 ↔ 本机后端 API 契约

本文件是扩展仓库与后端仓库之间**唯一的接口约定**。后端改这些端点时必须同步改这里，
并在下方变更记录里写一行；扩展只依赖这里列出的字段，多余字段一律忽略。

## 传输与鉴权

- 只允许 `http://127.0.0.1:<port>` 与 `http://localhost:<port>`，`manifest.json` 的
  `host_permissions` 也只声明这两个 host。
- 所有请求由 **service worker**（扩展自身 origin）发出，不使用 content script：
  页面上下文发起的本机请求会撞 CORS、混合内容和 Local Network Access 限制。
- token 从用户粘贴的完整 URL 的 `?token=` 取，同时用两种方式带：
  - query：`?token=<token>`
  - header：`X-Whisper-Token: <token>`
- 后端做 Host 白名单校验（防 DNS rebinding），非 127.0.0.1/localhost 的 Host 一律 403。
- 缺 token 访问受保护端点返回 **403**；token 只存在于内存和 `chrome.storage.local`，不写日志。

## GET /health

**不需要 token**（仅 Host 校验），用于连接探测。

```json
{
  "ok": true,
  "service": "whisper-web-live",
  "version": "…",
  "port": 47813,
  "instance": "dba088c5",
  "meeting": { "id": "20261112_153733", "title": "", "star": false },
  "segments": 12,
  "control": true
}
```

扩展只用：`ok`、`port`、`segments`、`control`。
`instance` 用于区分「同一端口换了进程」，扩展当前只展示不消费。

## GET /transcript.json

**需要 token**。这是扩展的唯一文本来源。

```json
{
  "meeting_id": "20261112_153733",
  "started_at": "2026-11-12T15:37:33",
  "meeting": { "id": "…", "date": "2026-11-12", "seq": 2, "title": "…", "star": false },
  "segments": [
    { "id": 1, "ts": "14:43:24", "rel": 20, "kind": "final", "source": "replay", "text": "原文" },
    { "id": 2, "ts": "14:43:29", "rel": 25, "kind": "trans", "source": "argos", "text": "译文" }
  ],
  "text": "拼接后的纯文本，一行一段",
  "note": "译文由 Argos 离线机器翻译生成，非原文；未定稿片段不在此处。"
}
```

扩展只用：`segments[].ts / rel / kind / text`、`text`、`note`。
`kind` 只会有 `final`（原文定稿）与 `trans`（译文）两种；后端内部的 `part`（未定稿）不会出现在此端点。
`kind === "trans"` 时 UI 必须加「译 」前缀，**不得把译文当原文展示或复制**。
`segments` 为空是合法状态（服务起来了但还没说话），不是错误。

## GET /api/control/state

**需要 token**。返回两种形状之一。

无运行核心（传统桌面窗模式、纯回放服务）：

```json
{ "available": false, "readonly": true, "reason": "本实例未挂运行核心：…" }
```

有运行核心：

```json
{
  "available": true,
  "state": {
    "available": true,
    "mode": "headless",
    "running": false,
    "engine": "sensevoice",
    "source": "loopback",
    "translate": false,
    "overlay": false,
    "overlay_changeable": false,
    "overlay_hint": "悬浮字幕是启动选项（--overlay），运行时不可切换",
    "device": null
  }
}
```

扩展在 `available !== true` 时必须隐藏控制按钮并显示 `reason`，**不允许渲染点了没反应的按钮**。

## POST /api/control/action

**需要 token**，`Content-Type: application/json`。

```json
{ "action": "start" | "stop" | "configure" | "state",
  "patch": { "engine": "sensevoice", "source": "mic", "translate": true } }
```

- `patch` 只在 `configure` 时使用；允许键：`engine`（`sensevoice`/`zipformer`）、`source`
  （`loopback`/`mic`）、`translate`（布尔）、`noise_gate`（(0,1) 数字）、`device`/`save`（字符串或 null）。
- 成功：`200` + `{ "ok": true, "message": "…", "state": {…} }`
- 参数非法：`400` + `{ "ok": false, "error": "…" }`
- 无运行核心：`409` + `{ "ok": false, "available": false, "error": "…" }`
- 内部异常：`500` + `{ "ok": false, "error": "…" }`

**扩展必须读 body 而不是只看 HTTP 状态**：400/409 也带可展示的 `error`。
运行中切引擎由后端按 `stop → configure → start` 原子处理，扩展不做本地状态猜测，
每次操作后重新拉 `/api/control/state` 以服务端为准。

## 不做的事（边界）

- **不注入 content script**：live 页必须保持普通 `http://127.0.0.1` 页面，
  第三方 AI 插件才能读 DOM。若搬进 `chrome-extension://` 页面，这条路直接断掉。
- **不用 Native Messaging**（当前版本）：虽然能让扩展一键拉起 Python 进程，但
  `allowed_origins` 要绑定固定扩展 ID、需要独立 installer 写注册表、商店禁止包内捆绑原生可执行文件，
  且 Chrome 在 port 断开时会杀掉 host 进程。结论是双通道并存而非替换，详见主项目 issues.csv 的 I-070。
- **不绑定扩展 ID**：后端 CORS 对任意 `chrome-extension://` / `moz-extension://` origin 回显，
  不维护白名单，所以扩展换路径、换 ID 都不会断。代价是任意扩展都能发请求，靠 token 兜底。
  一旦引入 Native Messaging，这条就不成立了（`allowed_origins` 必须写死 ID），
  实测 unpacked 的 ID 随路径变化：`whisper/extension` → `ajgmcdhh…`，`whisper-ext` → `hbfbckcfmnnakaekleoadicgnghofcij`。

## 变更记录

| 日期 | 变更 | 兼容性 |
| --- | --- | --- |
| 2026-11-12 | 从主项目 `whisper/extension/` 拆出，固化 `/health`、`/transcript.json`、`/api/control/*` 契约 | 与后端 v0.1 对齐 |
