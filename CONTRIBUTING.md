# 参与贡献

这个项目只有一个作者在维护，所以规则写得比一般项目更直白：**什么会被接受、什么不会、以及怎么在本地把它跑起来**。

## 你能改什么

| 方向 | 门槛 | 说明 |
|---|---|---|
| 文档纠错、链接失效、数字与代码对不上 | 最低 | 最需要的一类。本仓库的价值一半在文档，文档错了比代码错了更难发现 |
| `extension/` | 低 | 8 个文件、无构建步骤、无 npm 依赖，改完在浏览器里点一下就能验 |
| `engine/` | 高 | 强依赖 Windows（WASAPI loopback + win32 分层窗口）。非 Windows 环境只能做静态修改，无法验证 |
| `docs/bench/` 加一格数据 | 中 | 见 `docs/bench/README.md` 的 PR 模板；**只允许"该格不存在"的格子省数据，且必须引官方原文** |

## 环境

- **Windows 10/11**（引擎）
- Python 3.13（仓库按 `cp313` 轮子验证）
- Node 22 —— 只用于 `tools/contract_check.js`，扩展本身不需要 Node
- 扩展**没有构建步骤**：`extension/` 下 8 个文件就是全部产物

## 跑起来（引擎）

```bat
python -m venv .venv
.venv\Scripts\pip install -r engine\requirements.txt
```

模型不入库（229 MiB，且 GitHub 单文件限 100 MB）。三个文件，来源与体积如下——**下载后请核对字节数**，对不上说明链接指到了别的版本：

| 放到 | 来源 | 归档体积 | 校验 |
|---|---|---|---|
| `engine/pc_models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/` | [sherpa-onnx asr-models](https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2) | 1,047,870,769 B | 解压后只用 `model.int8.onnx`（228.2 MiB）与 `tokens.txt`；同目录 `model.onnx` 937 MB 代码从不打开 |
| `engine/pc_models/sherpa-onnx-streaming-zipformer-en-2023-06-26/` | [同上](https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-en-2023-06-26.tar.bz2) | 310,414,022 B | 可选，只给 `--engine zipformer` 用 |
| `engine/pc_models/silero_vad.onnx` | [silero_vad.onnx](https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx) | — | **643,854 B**，单文件直接落盘，不改名 |

目录名必须一字不差：`engine/pc_transcriber.py` 里是硬编码的（`MODEL_DIR` / `SV_DIR` / `VAD_MODEL`）。

```bat
engine\run_transcriber.bat live
```

## 跑起来（扩展）

`chrome://extensions` 或 `edge://extensions` → 开发者模式 → 加载已解压的扩展程序 → 选 **`extension/`**（含 `manifest.json` 那一层，不是仓库根）。

## 两条硬规矩

**1. 契约优先。** 端点、字段名、错误码、鉴权方式只要有变动，**先改 `docs/contract.md`，再改两侧实现**。契约是从真实响应里抄出来的，不是设计稿；凭记忆改会把两侧一起改错。

**2. 一个提交只动一个目录族。** `engine/` / `extension/` / `tools/` / `docs/` 分开提。混在一起会让 GitHub 首页每个目录都显示同一句提交信息，读起来像复读。

提交信息只写「改了什么 + 为什么」。不要写思考过程、不要写"我一开始以为…后来发现…"——那是 issue 和 PR 描述的地方。

## 提交前跑这几个

```bash
python tools/check-links.py                  # 文档里所有路径引用是否真实存在（区分大小写）
python -m compileall -q engine               # 语法
node --check extension/popup.js && node --check extension/service_worker.js
pwsh tools/pack.ps1                          # 打包并校验 manifest 引用的文件
node tools/contract_check.js --url "http://127.0.0.1:<port>/?token=<token>"   # 后端在跑时
```

CI 会跑前四项，跑不了的第五项需要真实后端与模型。

CI **不做**的事，别指望它：引擎跑不起来。GitHub runner 上既没有 229 MiB 模型，也没有 WASAPI 与 Windows 会话——引擎的行为只能在本机验。所以引擎改动请在 PR 里贴实测输出，而不是"CI 绿了"。

## 不会接受的改动

- **任何云端兜底**：上传音频、调用在线 ASR、加遥测。这与"拔掉网线它还在写"直接冲突，不是权衡问题。
- **把模型或二进制塞进仓库**：模型走 Release 附件与安装器，仓库只放代码与清单。
- **给扩展引入构建链**：`extension/` 保持 8 个文件、零依赖、可直接 load unpacked。加 webpack 就等于要求贡献者装 Node 才能改一个按钮。
- **AGPL 代码**：本项目是 MIT，引入 AGPL 会传染整个仓库。
- **改扩展行为却不 bump `extension/manifest.json` 的 `version`**：商店审核与"已加载版本"会分不清。

## 许可证

MIT。提交即视为同意以 MIT 分发。
