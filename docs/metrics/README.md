# 数据账本

`history.csv` 是本仓库的计数序列，`.github/workflows/metrics.yml` 每天 03:17 UTC 采集一次并提交。
README 顶部的徽章与曲线由 `tools/metrics.py` 从这份 CSV 渲染成 SVG，同一次 CI 里完成，不需要人碰。

## 平台留不住什么

| 事实 | 实测 |
|---|---|
| 仓库浏览量只保留 **14 天** | 2026-11-13 查询 `/traffic/views?per=day`，最早一天是 2026-10-30 |
| 发行资产的下载数是**累计值**，没有按天序列 | `/releases` 只给 `download_count` 一个数字 |
| static Space **没有浏览量** | `/api/spaces/<id>/analytics` 返回 404；Space 对象里只有 `likes` |

第一行决定这份 CSV 的存在：窗口之外的日子平台不再提供，也不补发。

## 记什么

| 来源 | 指标 | 口径 | 需要什么 |
|---|---|---|---|
| `github` | `stars` `forks` `watchers` `open_issues` | 当前值 | 私有仓需 token |
| `github_release` | `downloads_total`、`asset.<文件名>` | **累计**，只算 Release 资产，不含 `git clone` | 同上 |
| `github_traffic` | `views` `views_uniques` `clones` `clones_uniques` | **日增量**，对应 Insights → Traffic；平台按 UTC 日切，入库时换算成 +8 日期 | push 权限 |
| `github_popular` | `referrer.<来源>`、`path.<路径>` | 14 天窗口内的**排名**，不是日增量 | push 权限 |
| `hf_model` | `downloads_30d` `downloads_all_time` `likes` | `downloads_30d` 是**滚动 30 天**，会掉 | 公开接口，无需 token |
| `hf_space` | `likes`；`views` 恒为空 | 平台没有浏览量接口 | 无需 token |

## 三种值必须分开

| 写法 | 含义 |
|---|---|
| `12` | 接口明确返回 12 |
| `0` | 接口明确返回 0——今天确实没人看 |
| 空 | **取不到**：没有权限、没有这个接口、请求失败。原因写在 `note` 列 |

把「取不到」写成 `0` 会让曲线多出一段不存在的平地，读者无法区分「没人来」和「没测到」。

整源失败时只写一行 `_unavailable`，不为每个指标各写一条空值。

同一个源一天里可能一次成功、一次失败（本机有 PAT，CI 只有内置 token），两条规则消解：
**有数据就不留标记**；**本次运行该源成功就删掉今天的旧标记**。

## 怎么读

- `downloads_total`、`downloads_all_time`、`stars` 是**累计值**：求相邻两天之差才是增量。
- `views`、`clones` 是**日增量**：直接就是当天的数，不要再去求差。
- `*_uniques` **不可跨天相加**：同一个人连着来三天会记成三个 uniques。周、月独立访客平台不提供。
- `referrer.*` / `path.*` 是窗口内排名：只反映「最近 14 天谁排前面」，不能当趋势。

## 跑法

```bash
python tools/metrics.py                 # 只看，不落盘
python tools/metrics.py --write         # 采集并写 history.csv、徽章与 SVG
python tools/metrics.py --write-readme  # 只从 CSV 重画图并重写 README 那一段，不联网
python tools/metrics.py --report        # 把全部指标打成 Markdown 表
```

`--write` 与 `--write-readme` 都是纯标准库，不需要装依赖。CI 的顺序是采集 → 重画 → 一次提交，
所以同一次提交里的数字和图必然同源。

GitHub 凭证依次取 `--github-token` → `$GH_TOKEN` / `$GITHUB_TOKEN` → `git credential fill`（本机凭证管理器）。

### 流量数据要单独配一个令牌

**Actions 内置的 `GITHUB_TOKEN` 打不了 `/traffic/*`。** 这是权限模型：这几个端点要求 fine-grained token 的
**Administration (read)**，而 `permissions:` 里没有 `administration` 这一项可以授予。实测返回
`403 Resource not accessible by integration`。

配法（一次性）：

1. GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token
2. Repository access 选 **Only select repositories** → `Offlisten`
3. Permissions → Repository permissions → **Administration: Read-only**
4. 复制出来，仓库 → Settings → Secrets and variables → Actions → New secret，名字 `METRICS_TOKEN`

工作流里是 `secrets.METRICS_TOKEN || secrets.GITHUB_TOKEN`，没配也能跑：仓库计数、Release 下载数、
HF 数字照常，流量那一段不落盘、不写 0，只在运行日志里发四条 `warning`，job 仍然是绿的。

> 缺凭证不写进 `history.csv`：那是配置状态，不是数据事件。写进去会变成每天一行 403，
> 把真正取到的数淹掉；而数据缺口本身已经表现为那段没有行。

> classic PAT 给 `repo` scope 也行（公开仓 `public_repo`）。本机不需要这个 secret。

`metrics.yml` 每天 **03:17 UTC（11:17 UTC+8）** 跑。选非整点是因为 GitHub 的定时任务在整点前后排队会漂。
定时任务只在默认分支触发，所以这份序列只在 `main` 上累积。

漏跑不致命：流量每轮都把整个 14 天窗口全量回填，一次运行就能补齐窗口内的空白。补不回来的是窗口之外的日子。

## 四条纪律

与指标本身无关，换一份数据也成立：

1. **空不是零。** 任何「拿不到」都要有独立表示，否则下游所有聚合都在撒谎。
2. **窗口回填，而不是只记今天。** 平台给滑动窗口，就每轮把窗口整体抄一遍，让漏跑自愈。
3. **同键覆盖，不重开一行。** 一天跑两次不该出现两行；但也不删历史。
4. **先提交，再报警。** 数据先落盘，再判断今天有没有源挂了；顺序反过来，一次网络抖动会让当天其余指标一起丢。

## 文件

| 文件 | 用途 |
|---|---|
| `history.csv` | 唯一事实源。列：`date,source,metric,value,note` |
| `stats.svg` | README 那张三面板曲线，由 CSV 渲染 |
| `badge-downloads.svg` `badge-hf.svg` `badge-views.svg` `badge-stars.svg` | 徽章，自渲染 |
| `badge-*.json` | shields.io `endpoint` 格式，给想引第三方徽章的地方 |

徽章自己画，但不妨碍别人引 shields.io：`badge-*.json` 是 shields 的 `endpoint` 格式，指过去就能用。
自渲染的理由是私有期第三方取不到数，且 `—` 不会被第三方服务改写成 `0`。

## 边界

- 2026-11-13 之前仓库是私有的，那段时间的浏览与克隆在平台上没有留下数据，回填只能回填出 0。这一段的 0 是「没人能访问」，不是「没人想看」，图上看不出来。
- HF `downloads_30d` 是滚动窗口，模型没人下的时候会掉回 0，不是数据被清零。
- 不统计 Space 页面的浏览量，因为平台不提供；也不挂第三方统计脚本，与「不埋点」的产品承诺冲突。
