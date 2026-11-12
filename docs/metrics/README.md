# 数据账本

平台给你「当前值」，不给「历史」。这本账就是历史：每天抄一次，抄进仓库，变成可以被 diff 的字节。

一本没人看的账没有意义，所以先说清楚它为什么必须存在——三条都是实测出来的，不是猜的。

## 平台留不住什么

| 事实 | 实测 |
|---|---|
| 仓库浏览量只保留 **14 天** | 2026-11-13 查询 `/traffic/views?per=day`，最早一天是 2026-10-30。第 15 天平台删除，删掉就再也拿不回来 |
| 发行资产的下载数是**累计值**，没有按天序列 | `/releases` 只给 `download_count` 一个数字。想知道「昨天涨了多少」，只能自己有昨天的数 |
| static Space **没有浏览量** | `/api/spaces/<id>/analytics` 返回 404；Space 对象里只有 `likes` |

第一条最要命：它不是「数据不好看」，是**数据会消失**。今天不抄，明天那 14 天里就少一天，永久少一天。

## 记什么

| 来源 | 指标 | 口径 | 需要什么 |
|---|---|---|---|
| `github` | `stars` `forks` `watchers` `open_issues` | 当前值 | 私有仓需 token |
| `github_release` | `downloads_total`、`asset.<文件名>` | **累计**，只算 Release 资产，不含 `git clone` | 同上 |
| `github_traffic` | `views` `views_uniques` `clones` `clones_uniques` | **日增量**，平台按 UTC 日切，导入时换算成 +8 日期 | push 权限 |
| `github_popular` | `referrer.<来源>`、`path.<路径>` | 14 天窗口内的**排名**，不是日增量 | push 权限 |
| `hf_model` | `downloads_30d` `downloads_all_time` `likes` | `downloads_30d` 是**滚动 30 天**，会掉 | 公开接口，无需 token |
| `hf_space` | `likes`；`views` 恒为空 | 平台没有浏览量接口 | 无需 token |

## 三种值必须分开

这是整本账的纪律，也是它能不能被信的前提：

| 写法 | 含义 |
|---|---|
| `12` | 接口明确返回 12 |
| `0` | 接口明确返回 0——今天确实没人看 |
| 空 | **取不到**：没有权限、没有这个接口、请求失败。原因写在 `note` 列 |

把「取不到」写成 `0` 会让曲线凭空多出一段平地，读者无法区分「没人来」和「没测到」。宁可断一截。

整源失败时只写一行 `_unavailable`，不为每个指标各写一条空值——同一句话刷十遍，表就没法看了。

标记和真数据会打架：同一个源一天里可能一次成功、一次失败（本机有 PAT，CI 只有内置 token）。
两条规则消解它：**有数据就不留标记**（取到了比"当时没取到"更接近事实）；
**本次运行该源成功就删掉今天的旧标记**（否则本机补跑成功后，表里还挂着 CI 那次的 403，读者会以为现在也取不到）。

## 怎么读

- `downloads_total`、`downloads_all_time`、`stars` 是**累计值**：求相邻两天之差才是增量。
- `views`、`clones` 是**日增量**：直接就是当天的数，不要再去求差。
- `*_uniques` **不可跨天相加**：同一个人连着来三天，会被记成三个 uniques。周、月独立访客平台不提供，别自己加出来。
- `referrer.*` / `path.*` 是窗口内排名：只反映「最近 14 天谁排前面」，不能当趋势。

## 跑法

```bash
python tools/metrics.py                 # 只看，不落盘
python tools/metrics.py --write         # 写 docs/metrics/history.csv 与徽章
python tools/metrics.py --report        # 把已记下的历史打成 Markdown 表
```

GitHub 凭证依次取 `--github-token` → `$GH_TOKEN` / `$GITHUB_TOKEN` → `git credential fill`（本机凭证管理器）。

### 流量数据要单独配一个令牌

**Actions 内置的 `GITHUB_TOKEN` 打不了 `/traffic/*`。** 这不是权限没开够，而是权限模型：
这几个端点要求 fine-grained token 的 **Administration (read)**，而 `permissions:` 里根本没有
`administration` 这一项可以授予。实测结果是 `403 Resource not accessible by integration`。

配法（一次性）：

1. GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token
2. Repository access 选 **Only select repositories** → `Offlisten`
3. Permissions → Repository permissions → **Administration: Read-only**（这是流量接口要的那一项）
4. 复制出来，仓库 → Settings → Secrets and variables → Actions → New secret，名字 `METRICS_TOKEN`

工作流里是 `secrets.METRICS_TOKEN || secrets.GITHUB_TOKEN`，没配也能跑：仓库计数、Release 下载数、
HF 数字照常；流量那一段不落盘、不写 0，只在运行日志里发四条 `warning`（views / clones / referrers / paths），
job 仍然是绿的。

> 缺凭证刻意不写进 `history.csv`：那是配置状态，不是数据事件。写进去会变成「每天一行 403」，
> 把真正取到的数淹掉；而数据缺口本身已经表现为那段没有行。

> 用 classic PAT 的话给 `repo` scope 也行（公开仓 `public_repo`）。
> 本机不需要这个 secret：`git credential fill` 拿到的就是你自己账号的令牌，够用。


`metrics.yml` 每天 **03:17 UTC（11:17 UTC+8）** 跑一次。选非整点是因为 GitHub 的定时任务在整点前后排队会漂。默认分支的定时任务才会触发，所以这本账只在 `main` 上累积。

漏跑不致命：流量部分每轮都把整个 14 天窗口全量回填，一次运行就能补齐窗口内的空白。真正补不回来的是窗口之外的日子。

## 这份经验能不能迁移

能，而且它跟本仓库另外两处是同一招，不是新发明：

| 已有的 | 换成这里的说法 |
|---|---|
| `dist-manifest.json` 给每个文件记 sha256 | 把「上游随时会变的文件」钉成可复核的字节 |
| 负结果册记下「试过并放弃的路」 | 把「别人会重复踩的坑」钉成可读的记录 |
| `history.csv` 记下平台的计数 | 把「平台只留 14 天的数」钉成可 diff 的序列 |

共同点只有一句：**外部状态会变、会过期、会消失，所以落到自己仓库里。**

具体可复用的是四条，与指标本身无关：

1. **空不是零。** 任何「拿不到」都要有独立的表示，否则下游所有聚合都在撒谎。
2. **窗口回填，而不是只记今天。** 平台给的是滑动窗口，就每轮把窗口整体抄一遍，让漏跑自愈。
3. **同键覆盖，不重开一行。** 一天跑两次不该出现两行；但也不能删历史——只覆盖同一天同一个指标。
4. **先提交，再报警。** 数据先落盘，再去判断今天有没有源挂了。顺序反过来，一次网络抖动会让当天其余指标一起丢。

第 4 条在 `metrics.yml` 里是分开的两个 step，就是为此。

## 边界

- 仓库私有期间这本账全是 0——不是没人看，是**没人能看**。转公开后曲线会从某一天开始抬头，那天是个有用的日子。
- HF `downloads_30d` 是滚动窗口，模型没人下的时候它会掉回 0，别误读成「数据被清零」。
- 这本账不统计 Space 页面的浏览量，因为平台不提供；也不打算挂第三方统计脚本——那与「不埋点」的产品承诺冲突。

## 文件

| 文件 | 用途 |
|---|---|
| `history.csv` | 唯一事实源。列：`date,source,metric,value,note` |
| `badge-release-downloads.json` | shields.io endpoint 徽章，给 README 用 |
| `badge-hf-downloads.json` | 同上，HF 侧 |
| `badge-stars.json` | 同上，star 数 |

徽章格式是 shields 的 `endpoint` schema，仓库转公开后可这样引：

```markdown
![release downloads](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/peaceaddpaasion/Offlisten/main/docs/metrics/badge-release-downloads.json)
```

取不到值时徽章显示 `—` 而不是 `0`，与表里一致。
