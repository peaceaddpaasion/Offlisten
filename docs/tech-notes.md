# 技术素材与交付路径（2026-11-12）

> 用途：把「技术产品简历」这件事落成**可验证的句子**，而不是形容词。
> 每条都标了状态：`实测` = 本机跑出来的数；`待测` = 还没跑，不许写进对外材料。

## 1. 四条可以写的技术点（附准确写法）

### 1.1 模型体积与性能适配 —— `实测`

不要写「模型很小」，写清**取舍的边界**：

| 档 | 组成 | 体积 | 代价 |
|---|---|---|---|
| Lite | zipformer-en int8 70 + zh-14M int8 25 + VAD 1 | **96 MB** | 14M 中文对术语/口音/远场掉字，不出标点 |
| Standard | SenseVoice int8 | **229 MB** | 非流式，延迟高于 zipformer |

而且 `sensevoice` 与 `zipformer` 是**两条独立管线**（`--engine` 二选一，默认前者），不是一个模型的两种配置。
这句话能证明你真的读过自己的代码。

### 1.2 特化场景 —— `实测`

噪声门限不是拍一个常数，是**按音源类型自适应**：mic `0.0008` / loopback `0.006`。
依据是实测两类音源的峰值分布：mic 峰值 `0.0016`（0/30 帧过旧门限），loopback `0.275`（24/30 帧过）。
同时如实记录：**门限扫描证明不存在分离点**，mic 录外放时 SNR≈1 —— 这不是缺陷，是物理限制。

> 简历里写「做了门限扫描并承认无解」，比写「优化了降噪」可信十倍。

### 1.3 部署解耦度 —— `实测`

| 层 | 体积 | 依赖 |
|---|---|---|
| MV3 扩展 | **12.5 KB / 8 文件** | 零构建、零 npm 依赖 |
| 本地引擎 | 96 MB 起 | Python + sherpa 运行时 |

解耦靠的是**契约而非代码共享**：`docs/contract.md` 钉死 4 个端点的字段与错误码，扩展不知道后端是 Python 还是别的。
另一侧证据：`host_permissions` 只声明 `127.0.0.1` / `localhost`，**在设计上就没有上传路径**。

### 1.4 ncnn：核对过，最终没用 —— `已决策`

> **先说结论：当前主线是 ONNX（venv 实测 `sherpa_onnx 2.0.0` + `onnxruntime 1.31.0`），不是 ncnn。**
> ncnn 是 2026-10 的旧线，模型资产仍占 135 MB × 2（`official_model/`、`apk_models/`）。
> 完整决策记录见 `docs/adr-001-runtime.md`。
>
> **一句话说清 ncnn 到底跑没跑**：在 **Android 真机上跑过**（2026-10-25 改造 APK 换模型后装机成功，arm64 + Vulkan）；
> 在 **Windows x86-64 上从未跑过**（`.venv` 无 `sherpa_ncnn`，全仓 `.py` 无 `import sherpa_ncnn`）。
> 另外 `ASR升级评估报告.md` 里的 `RTF 0.3~0.6` 是该报告自标的**估算值**，不是实测，别引用成数据。

事实核查（PyPI JSON API 实拉，不是记忆）：

| 项 | sherpa-ncnn 2.1.15 | sherpa-onnx 2.0.1 |
|---|---|---|
| win32 wheel | ✅ cp313 | ✅ cp313 |
| win_amd64 wheel | ✅ cp313 | ✅ cp313 |
| **win_arm64 wheel** | ❌ **没有** | ✅ cp313 |
| 发布文件总数 | 40 | 75 |
| 第三方推理依赖 | **无**（ncnn 静态编译，只依赖系统库） | ONNX Runtime（约 45 MB） |
| SenseVoice 支持 | ✅ 2025-09 加入（#416 导出 / #418 运行时） | ✅ 原生 |

**这里有一个真实的权衡，正好是「性能权衡体现技术定位」的例子：**

- 选 **ncnn** → 甩掉 ONNX Runtime 依赖、模型包更小（zh-14M：ncnn 22.2 MB vs onnx 70.6 MB 压缩包），但**放弃 Windows on ARM**（Surface / Snapdragon X 装不上 wheel）。
- 选 **onnx** → 保留 arm64 覆盖，但多背 45 MB 运行时。

**待测（不许先写进简历）**：在本机 Windows x64 上 `pip install sherpa-ncnn` 能否跑通、SenseVoice 转 ncnn 后的 RTF 与 WER 差多少、内存峰值对比。

## 2. 上微软商店：政策与硬约束

| 项 | 事实 | 来源 |
|---|---|---|
| 注册费 | **当前免**（个人 2025 底起免，企业 2026-05 起免）；历史 $19 一次性 | 多方一致，提交前以 Partner Center 实价为准 |
| 签名 | **微软免费签 MSIX**，不需要自购代码签名证书 | 同上 |
| 托管 / 更新 | 二进制由微软 CDN 托管，更新自动下发 | 同上 |
| 可提交类型 | Win32（含 WPF/WinForms/Electron）、UWP、PWA、.NET MAUI，**无需重写** | 同上 |
| 流程 | Partner Center → 保留应用名（全局唯一）→ IARC 年龄分级 → 截图 → 隐私政策 URL → 认证 | 同上 |

结论：**这条路的成本是零，不是"要不要花钱"的问题。**

## 3. 但 MSIX 有一个必须先改的坑 —— `代码里已确认`

```python
BASE_DIR = os.path.dirname(os.path.abspath(__file__))   # web_live.py:71
ARCHIVE_DIR = os.path.join(BASE_DIR, "meetings")        # web_live.py:78
```

存档目录挂在**程序目录**下。打成 MSIX 后：

1. 安装目录一般**只读**；
2. 即便能写，MSIX 的 VFS 会把它**重定向**到 `%LOCALAPPDATA%\Packages\<包名>\LocalCache\...`。

后果有两个，都很糟：

- 用户在「文档」里找不到自己的会议存档；
- 卸载/重装时存档的归属变得不可控。

**结论：P1 之前必须把 `ARCHIVE_DIR`（以及 `DISCOVERY_PATH`）挪到 `%LOCALAPPDATA%\Offlisten\` 这类稳定路径，并且保留一次性迁移。**
这也正好是「部署解耦」的实证：**程序目录不该是数据目录**。

> 注：VFS 重定向与只读行为需在真 MSIX 包上复验一次，本文按 MSIX 已知机制推断，未实测。

## 4. 交付路径：现在卡在哪

```
P0 模型瘦身（只挑 int8 / 定 Lite 档）      ← 未做
P1 PyInstaller onedir（量真实体积+启动耗时） ← 未做，且没有任何 .spec / build / dist
P2 挪数据目录 + 打 MSIX                     ← 未做
P3 Partner Center 提交（保留名 / IARC / 截图 / 隐私政策）
P4 商店认证
```

**当前卡点是 P1 之前**：主项目里 `find` 不到任何 `*.spec`、`build/`、`dist/`、`AppxManifest.xml`。
也就是说**还没有一个能双击运行的产物**，商店无从谈起。

## 5. GitHub 状态（已推送）

2026-11-12 17:48 完成首次推送。远端原先只有一个网页初始化提交 `83bb199`（`Initial commit`：`LICENSE` 21 行 + `README.md` 2 行），
与本地历史没有共同祖先，因此用 `--force-with-lease` 覆盖：

```
 + 83bb199...cc22616 main -> main (forced update)
 * [new tag]         v0.2.1 -> v0.2.1
```

覆盖前先把那两个文件里的信息留了下来，否则会静默丢失：

- `LICENSE` 的版权持有人是真实署名 `LI BINGZHEN`，本地原先写的是 `Offlisten contributors`——已改回；
- `README.md` 那两句描述存进了 `docs/publish.md`，作为仓库 About 栏文案。

当前远端：`main = cc22616`，44 个文件，`git diff origin/main main` 为空。

**遗留：仓库是私有的。** 未登录访问 `api.github.com/repos/peaceaddpaasion/Offlisten` 返回 404。
要对外传播必须先改可见性：仓库页 → Settings → General → 最下方 Danger Zone → Change visibility → Public。
公开后会被搜索引擎与镜像站抓取，撤回也删不干净，改之前想清楚。

工具侧的事实：沙箱内 git 一律走 `127.0.0.1` 代理，访问 `github.com` 报 `CONNECT tunnel failed, response 502`，
清空 `HTTP_PROXY`/`HTTPS_PROXY` 无效；非沙箱执行才通。这不是凭据问题——凭据助手是 `manager`，登录态一直有效。

进仓库根目录的写法随 shell 变，别混用：

| Shell | 命令 |
|---|---|
| cmd | `pushd D:\projects\whisper-ext` |
| PowerShell | `Set-Location D:\projects\whisper-ext` |
| Git Bash | `cd /d/projects/whisper-ext` |

## 6. 未验证清单

- 仓库可见性仍是私有（需在网页改），改了之后搜索引擎和镜像站的抓取无法撤回。
- MSIX 的 VFS 重定向与只读行为（按机制推断，未打包实测）。
- `sherpa-ncnn` 在本机 Python 3.13 x64 上实际可跑、以及 SenseVoice→ncnn 的质量差。
- Microsoft Store 当前对个人开发者的具体条款（政策变动频繁，提交前需看 Partner Center）。
