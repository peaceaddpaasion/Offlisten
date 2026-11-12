#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把散落在平台侧、且会过期或没有时间序列的公开计数，抄成仓库内的一本账。

为什么需要它：
  - GitHub release 资产有 `download_count`，但那是**累计值**，平台不存按天的历史，
    想画一条曲线只能自己每天抄一次。
  - 仓库流量接口 `traffic/views`、`traffic/clones` 只保留 **14 天**（实测今天能取到的
    最早一天是 2026-10-30），第 15 天被平台删掉，删掉就再也拿不回来。
  - Hugging Face 的 model 只给近 30 天 `downloads` 与 `downloadsAllTime`；
    static Space 只有 `likes`，`/api/spaces/<id>/analytics` 返回 404——**没有浏览量**。
  平台不替我们留痕，所以自己抄。抄下来的每一行都能被 diff、被 review、被 grep，
  也正好是「证据驱动」这套做法在数据侧的复用：不引用平台的当前值，引用我们自己记下的序列。

三种值必须分开（这是整份脚本的纪律）：
    数字   接口给了，就是它
    0      接口明确返回 0（今天确实没人看）
    空     取不到（没有权限、没有这个接口、请求失败），原因写在 note 列
  把「取不到」写成 0 是伪造。宁可留空，宁可让曲线断一截。

用法：
    python tools/metrics.py                     # 只看，不落盘
    python tools/metrics.py --write             # 写 docs/metrics/history.csv 与徽章 json
    python tools/metrics.py --write --date 2026-11-13
    python tools/metrics.py --write --strict    # 任一数据源失败即退出 1（CI 用这个）

凭证：
    GitHub  依次取 --github-token → $GH_TOKEN/$GITHUB_TOKEN → `git credential fill`（仅本机可用）。
            仓库是私有的，流量接口还额外要求 push 权限，匿名一律 404。
    Hugging Face  公开接口不需要 token；$HF_TOKEN 只用来抬高限流阈值。

口径说明：
    快照日期按 **UTC+8** 取，和人的日历一致。
    流量接口按 UTC 日切，脚本把每天的 00:00Z 换算成 +8 日期再入库，
    所以日界和平台差 8 小时——写在这里，不留给读者猜。
"""
import argparse
import csv
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO_ROOT, "docs", "metrics")
HISTORY = os.path.join(OUT_DIR, "history.csv")

GH_REPO = "peaceaddpaasion/Offlisten"
HF_MODEL = "ToothpasteLake/offlisten-models"
HF_SPACE = "ToothpasteLake/offlisten"

TZ = dt.timezone(dt.timedelta(hours=8))
TIMEOUT = 25
UA = "offlisten-metrics/1 (+https://github.com/%s)" % GH_REPO

FIELDS = ["date", "source", "metric", "value", "note"]


# ---------------------------------------------------------------- http

def fetch(url, token=None):
    """返回 (ok, data, err)。err 是一句人能读的话，直接进 note 列。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return True, json.loads(r.read().decode("utf-8")), ""
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            body = json.loads(e.read().decode("utf-8"))
            detail = body.get("message", "")
        except Exception:
            pass
        hint = ""
        if e.code == 404 and "github" in url:
            hint = "（私有仓库对匿名请求一律 404）"
        elif e.code == 403 and "traffic" in url:
            if "Resource not accessible by integration" in detail:
                # Actions 内置 token 无法授予 Administration 权限，这是权限模型，不是配置漏填
                hint = "（内置 token 无 Administration 权限；需配 METRICS_TOKEN 个人令牌）"
                return False, None, "缺凭证: " + detail + hint
            hint = "（流量接口需要 push 权限）"
        return False, None, "HTTP %d%s%s" % (e.code, (": " + detail) if detail else "", hint)
    except urllib.error.URLError as e:
        return False, None, "网络不可达: %s" % e.reason
    except Exception as e:  # noqa: BLE001 - 任何解析错误都不该让整轮快照崩掉
        return False, None, "%s: %s" % (type(e).__name__, e)


def git_credential_token():
    """从本机凭证管理器取 GitHub token。CI 里没有 GCM，会直接失败返回空。"""
    try:
        p = subprocess.run(
            ["git", "credential", "fill"],
            input=b"protocol=https\nhost=github.com\n\n",
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=20,
            env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never"),
        )
        for line in p.stdout.decode("utf-8", "replace").splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------- rows

def row(date, source, metric, value, note=""):
    return {"date": date, "source": source, "metric": metric,
            "value": "" if value is None else str(value), "note": note}


def unavailable(date, source, err):
    """整源失败时只写一行，不为每个指标各写一条空值——否则历史表会被同一句话刷满。"""
    return [row(date, source, "_unavailable", None, err)]


# ---------------------------------------------------------------- sources

def collect_github(token, date):
    base = "https://api.github.com/repos/" + GH_REPO
    rows = []
    ok = {}

    good, d, err = fetch(base, token)
    ok["github"] = good
    if not good:
        return unavailable(date, "github", err), ok
    for key, metric in (("stargazers_count", "stars"), ("forks_count", "forks"),
                        ("subscribers_count", "watchers"), ("open_issues_count", "open_issues")):
        rows.append(row(date, "github", metric, d.get(key)))

    good, rel, err = fetch(base + "/releases?per_page=100", token)
    ok["github_release"] = good
    if not good:
        rows += unavailable(date, "github_release", err)
    else:
        total = 0
        for r in rel:
            for a in r.get("assets", []):
                n = a.get("download_count", 0)
                total += n
                rows.append(row(date, "github_release", "asset." + a["name"], n,
                                "tag " + r["tag_name"]))
        rows.append(row(date, "github_release", "downloads_total", total,
                        "%d 个 release" % len(rel)))

    # 流量：每轮把整个 14 天窗口回填一遍，漏跑的日期能补上，不依赖「今天必须跑过」
    for kind, key, tag in (("views", "views", "views"), ("clones", "clones", "clones")):
        good, t, err = fetch("%s/traffic/%s?per=day" % (base, kind), token)
        ok["github_traffic"] = good
        if not good:
            rows += unavailable(date, "github_traffic", err)
            continue
        days = t.get(kind, [])
        for item in days:
            ts = dt.datetime.strptime(item["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
            d8 = ts.astimezone(TZ).date().isoformat()
            rows.append(row(d8, "github_traffic", tag, item["count"],
                            "回填自 14 天窗口；平台按 UTC 日切"))
            rows.append(row(d8, "github_traffic", tag + "_uniques", item["uniques"],
                            "回填自 14 天窗口；平台按 UTC 日切"))
        if not days:
            ok["github_traffic"] = False
            rows += unavailable(date, "github_traffic", "接口返回空窗口")

    # 来源与热门路径：同样只有 14 天，且是「这段窗口内的排名」，不是按天增量。
    # 因此只记当天这一行，不做回填——把它当累计值会读错。
    for kind, prefix in (("referrers", "referrer."), ("paths", "path.")):
        good, t, err = fetch("%s/traffic/popular/%s" % (base, kind), token)
        ok["github_popular"] = ok.get("github_popular", True) and good
        if not good:
            rows += unavailable(date, "github_popular", err)
            continue
        for item in t:
            name = item.get("referrer") or item.get("path") or "?"
            rows.append(row(date, "github_popular", prefix + name, item.get("count"),
                            "14 天窗口内排名，非日增量"))
    return rows, ok


def collect_hf(date):
    rows = []
    ok = {}
    good, d, err = fetch("https://huggingface.co/api/models/%s?expand%%5B%%5D=downloads&expand%%5B%%5D=downloadsAllTime&expand%%5B%%5D=likes" % HF_MODEL)
    ok["hf_model"] = good
    if not good:
        rows += unavailable(date, "hf_model", err)
    else:
        rows.append(row(date, "hf_model", "downloads_30d", d.get("downloads"), "平台口径：近 30 天"))
        rows.append(row(date, "hf_model", "downloads_all_time", d.get("downloadsAllTime")))
        rows.append(row(date, "hf_model", "likes", d.get("likes")))

    good, s, err = fetch("https://huggingface.co/api/spaces/" + HF_SPACE)
    ok["hf_space"] = good
    if not good:
        rows += unavailable(date, "hf_space", err)
    else:
        rows.append(row(date, "hf_space", "likes", s.get("likes")))
        # 浏览量：平台没有这个接口，不是我们没写上
        rows.append(row(date, "hf_space", "views", None,
                        "static Space 不提供浏览量；/api/spaces/<id>/analytics 返回 404"))
    return rows, ok


# ---------------------------------------------------------------- store

def read_history(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def merge(old, new, ok_sources=None, date=None):
    """同 (date, source, metric) 覆盖，其余保留。表只增不减，断更的日期不会被抹掉。

    难处理的是「标记」和「数据」打架。同一个源一天里可能一次成功一次失败
    （本机有 PAT、CI 只有内置 token），两次结果会落在同一个 (date, source) 下。
    规则两条：
      1. 有数据就不留标记——取到了总比「当时没取到」更接近事实。
      2. 本次运行该源成功，就删掉今天留下的旧标记——否则本机补跑成功了，
         表里还挂着上一次 CI 的 403，读者会以为现在也取不到。
    """
    key = lambda r: (r["date"], r["source"], r["metric"])  # noqa: E731
    merged = {key(r): r for r in old}
    changed = 0
    for r in new:
        k = key(r)
        if merged.get(k) != r:
            changed += 1
        merged[k] = r

    ok_sources = ok_sources or {}
    have = {}
    for d, s, m in merged:
        if m != "_unavailable":
            have.setdefault((d, s), True)
    for k in [k for k in list(merged) if k[2] == "_unavailable"]:
        d, s, _ = k
        if (d, s) in have or (ok_sources.get(s) and d == date):
            del merged[k]

    return [merged[k] for k in sorted(merged)], changed


def write_history(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def badge(label, value):
    """shields.io endpoint 徽章格式。取不到写 —，不写 0。"""
    return {
        "schemaVersion": 1,
        "label": label,
        "message": "—" if value is None or value == "" else str(value),
        "color": "lightgrey" if value is None or value == "" else "blue",
    }


def write_badges(dirpath, rows, date):
    def pick(source, metric):
        for r in rows:
            if r["source"] == source and r["metric"] == metric and r["date"] == date:
                return r["value"]
        return None

    pairs = {
        "badge-release-downloads.json": ("release downloads", pick("github_release", "downloads_total")),
        "badge-hf-downloads.json": ("HF downloads", pick("hf_model", "downloads_all_time")),
        "badge-stars.json": ("stars", pick("github", "stars")),
    }
    for name, (label, value) in pairs.items():
        with open(os.path.join(dirpath, name), "w", encoding="utf-8", newline="") as f:
            json.dump(badge(label, value), f, ensure_ascii=False, indent=2)
            f.write("\n")


# ---------------------------------------------------------------- main

def report(path):
    """把历史表压成一张 Markdown 表：最新值 + 7 天变化。给人看的，不是给机器。"""
    rows = read_history(path)
    if not rows:
        print("还没有历史。先跑 `python tools/metrics.py --write`。")
        return 0

    series = {}
    for r in rows:
        series.setdefault((r["source"], r["metric"]), {})[r["date"]] = r["value"]

    def shift(d, days):
        return (dt.date.fromisoformat(d) - dt.timedelta(days=days)).isoformat()

    print("| 指标 | 最新 | 7 天前 | 变化 |")
    print("|---|---|---|---|")
    for (source, metric), days in sorted(series.items()):
        if metric == "_unavailable":
            continue
        dated = sorted(k for k, v in days.items() if v != "")
        if not dated:
            continue
        last = dated[-1]
        base_candidates = [k for k in dated if k <= shift(last, 7)]
        base = base_candidates[-1] if base_candidates else None
        cur, old = days[last], days[base] if base else None
        try:
            delta = int(cur) - int(old) if old is not None else None
        except ValueError:
            delta = None
        print("| `%s.%s` | %s | %s | %s |" % (
            source, metric, cur,
            old if old is not None else "—",
            ("+%d" % delta) if (delta or 0) > 0 else (str(delta) if delta is not None else "—")))
    print("\n<sub>数据日期截至 %s。累计值求差得增量；`views`/`clones` 本身就是日增量；"
          "`uniques` 不可跨天相加。</sub>" % max(r["date"] for r in rows))
    return 0


def main():
    ap = argparse.ArgumentParser(description="把平台侧计数抄成仓库内的历史表")
    ap.add_argument("--write", action="store_true", help="写入 docs/metrics/（默认只看）")
    ap.add_argument("--report", action="store_true", help="把已记下的历史打成 Markdown 表")
    ap.add_argument("--date", default=dt.datetime.now(TZ).date().isoformat(),
                    help="快照日期，默认今天（UTC+8）")
    ap.add_argument("--github-token", default="")
    ap.add_argument("--strict", action="store_true", help="任一源不可用即退出 1")
    args = ap.parse_args()

    if args.report:
        return report(HISTORY)

    token = args.github_token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or git_credential_token()

    rows, ok = collect_github(token, args.date)
    hf_rows, hf_ok = collect_hf(args.date)
    rows += hf_rows
    ok.update(hf_ok)

    bad = [r for r in rows if r["metric"] == "_unavailable"]
    if args.github_token:
        src = "--github-token"
    elif os.environ.get("GH_TOKEN"):
        src = "$GH_TOKEN"
    elif os.environ.get("GITHUB_TOKEN"):
        src = "$GITHUB_TOKEN"
    elif token:
        src = "git credential fill（本机凭证管理器）"
    else:
        src = "无"
    print("GitHub 凭证：%s｜快照日期 %s（UTC+8）\n" % (src, args.date))

    width = max(len(r["metric"]) for r in rows)
    for r in rows:
        if r["date"] != args.date:
            continue  # 回填行在下面汇总打印
        print("  %-14s %-*s %s%s" % (r["source"], width, r["metric"],
                                     r["value"] if r["value"] != "" else "（空）",
                                     ("  ← " + r["note"]) if r["note"] else ""))

    backfill = [r for r in rows if r["date"] != args.date and r["metric"].endswith(("views", "views_uniques", "clones", "clones_uniques"))]
    if backfill:
        dates = sorted({r["date"] for r in backfill})
        print("\n流量窗口回填：%d 行，覆盖 %s … %s" % (len(backfill), dates[0], dates[-1]))

    if bad:
        print("\n不可用：")
        for r in bad:
            print("  %s — %s" % (r["source"], r["note"]))

    if not args.write:
        print("\n（只看模式，未落盘；加 --write 写入 docs/metrics/）")
        return 1 if (args.strict and bad) else 0

    old = read_history(HISTORY)
    merged, changed = merge(old, rows, ok, args.date)
    write_history(HISTORY, merged)
    write_badges(OUT_DIR, merged, args.date)
    print("\n已写入 docs/metrics/history.csv：共 %d 行，本次新增/更新 %d 行" % (len(merged), changed))
    return 1 if (args.strict and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
