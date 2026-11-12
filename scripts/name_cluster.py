#!/usr/bin/env python3
"""名字候选聚类与近似冲突检测（纯标准库，离线可跑）。

用途：把一批中英文候选名分成「形态簇」和「语义簇」，并标出**同一形态簇内
编辑距离过近**的对——那正是"用户少打两个字就跑到别人站"的位置。

为什么不用 embedding：
- DeepSeek 没有 /embeddings 端点（官方文档只列 chat/Responses/FIM/models/balance/files/Search）。
- 深言（DeepLang）没有公开的通用生成/向量 API，语鲸开放 API 是「账号/搜索订阅/拉文章」三类内容接口。
- 名字是短字符串，字形/音形特征比稠密向量更能反映"打错就串"的风险。
- 离线可复现，不需要 key，也不会因模型版本变化而结论漂移。

用法：
  python scripts/name_cluster.py
  python scripts/name_cluster.py --json candidates.json
"""
from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations

# ---------------------------------------------------------------- 基础距离

def lev(a: str, b: str) -> int:
    """Levenshtein 编辑距离。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def bigrams(s: str) -> set[str]:
    s = s.lower()
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def form_sim(a: str, b: str) -> float:
    """同语言内的形态相似度 0..1（编辑距离 + 二元组）。"""
    a, b = a.lower(), b.lower()
    if not a or not b:
        return 0.0
    d = lev(a, b)
    mx = max(len(a), len(b))
    dist_sim = 1.0 - d / mx
    return 0.6 * dist_sim + 0.4 * jaccard(bigrams(a), bigrams(b))


def tag_sim(a: list[str], b: list[str]) -> float:
    return jaccard(set(a), set(b))


# ---------------------------------------------------------------- 层次聚类

def average_link(items, sim_fn, threshold):
    """平均链接凝聚聚类，返回簇列表（每项是下标列表）。"""
    clusters = [[i] for i in range(len(items))]
    while True:
        best, best_sim = None, -1.0
        for x, y in combinations(range(len(clusters)), 2):
            pairs = [(i, j) for i in clusters[x] for j in clusters[y]]
            s = sum(sim_fn(items[i], items[j]) for i, j in pairs) / len(pairs)
            if s > best_sim:
                best, best_sim = (x, y), s
        if best is None or best_sim < threshold:
            break
        x, y = best
        clusters[x] = clusters[x] + clusters[y]
        clusters.pop(y)
    return clusters


# ---------------------------------------------------------------- 报告

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="候选文件，留空用内置真实候选集")
    ap.add_argument("--form-threshold", type=float, default=0.55)
    ap.add_argument("--tag-threshold", type=float, default=0.5)
    ap.add_argument("--risk-distance", type=int, default=2, help="编辑距离<=该值视为打错即串")
    args = ap.parse_args()

    if args.json:
        with open(args.json, encoding="utf-8") as f:
            cands = json.load(f)
    else:
        cands = BUILTIN

    en = [c for c in cands if c.get("en")]
    cn = [c for c in cands if c.get("cn")]

    print("=" * 74)
    print("A. 英文形态簇（谁和谁长得像）")
    print("=" * 74)
    _report_form(en, "en", args)

    print()
    print("=" * 74)
    print("B. 中文形态簇")
    print("=" * 74)
    _report_form(cn, "cn", args)

    print()
    print("=" * 74)
    print("C. 语义簇（跨语言：同一语义场被几个名字挤）")
    print("=" * 74)
    _report_tags(cands, args)

    print()
    print("=" * 74)
    print("D. 高风险近似对")
    print("=" * 74)
    print("  判据：英文用编辑距离（长词<=%d / 短词<=1）；中文用**共享字符**——" % args.risk_distance)
    print("  两字词之间编辑距离恒等于 2，用它判断中文只会得到一堆废话。")
    risky = 0
    for a, b in combinations(en, 2):
        x, y = a["en"].lower(), b["en"].lower()
        d = lev(x, y)
        limit = args.risk_distance if max(len(x), len(y)) >= 5 else 1
        if d <= limit:
            risky += 1
            print("  [en] %-12s vs %-12s  编辑距离=%d   ← 少打/多打 %d 个字母就会串" % (x, y, d, d))
    for a, b in combinations(cn, 2):
        x, y = a["cn"], b["cn"]
        shared = set(x) & set(y)
        if shared:
            risky += 1
            print("  [cn] %-12s vs %-12s  共享字=%s   ← 同一字族，搜索与口传会互相干扰"
                  % (x, y, "".join(sorted(shared))))
    if risky == 0:
        print("  （无）")
    return 0


def _report_form(pool, key, args):
    if len(pool) < 2:
        print("  样本不足")
        return
    clusters = average_link(pool, lambda a, b: form_sim(a[key], b[key]), args.form_threshold)
    for idx, cl in enumerate(sorted(clusters, key=len, reverse=True), 1):
        names = " / ".join(pool[i][key] for i in cl)
        note = ""
        if len(cl) > 1:
            inner = min(
                lev(pool[i][key].lower(), pool[j][key].lower())
                for i, j in combinations(cl, 2)
            )
            note = "  紧密度=最小编辑距离 %d" % inner
        print("  簇%d (%d): %s%s" % (idx, len(cl), names, note))


def _report_tags(cands, args):
    clusters = average_link(cands, lambda a, b: tag_sim(a.get("tags", []), b.get("tags", [])), args.tag_threshold)
    for idx, cl in enumerate(sorted(clusters, key=len, reverse=True), 1):
        names = " / ".join((cands[i].get("cn") or cands[i].get("en")) for i in cl)
        shared = set(cands[cl[0]].get("tags", []))
        for i in cl[1:]:
            shared &= set(cands[i].get("tags", []))
        print("  簇%d (%d): %s" % (idx, len(cl), names))
        if shared:
            print("          共同语义: %s" % " , ".join(sorted(shared)))


BUILTIN = [
    # 已排除 / 已判死
    {"cn": "声盒", "en": "soundbox", "tags": ["器物", "声音", "盒子"]},
    {"cn": "录本", "en": "", "tags": ["器物", "记录", "本子"]},
    {"cn": "留声", "en": "", "tags": ["记录", "声音", "怀旧"]},
    {"cn": "拾音", "en": "pickup", "tags": ["记录", "声音"]},
    {"cn": "", "en": "pitalk", "tags": ["离线", "对话", "树莓派"]},
    {"cn": "", "en": "offtalk", "tags": ["离线", "对话"]},
    {"cn": "", "en": "offlist", "tags": ["离线", "隐私", "清单"]},
    {"cn": "", "en": "earshot", "tags": ["听觉", "范围"]},
    {"cn": "", "en": "all ears", "tags": ["听觉", "专注"]},
    {"cn": "", "en": "verba", "tags": ["语言", "记录"]},
    {"cn": "", "en": "sift", "tags": ["筛选", "提纯"]},
    {"cn": "", "en": "hark", "tags": ["听觉", "倾听"]},
    # 现用
    {"cn": "录匣", "en": "offlisten", "tags": ["器物", "离线", "记录", "盒子"]},
    # 待评
    {"cn": "有底", "en": "", "tags": ["把握", "凭据"]},
    {"cn": "底稿", "en": "", "tags": ["记录", "原件"]},
]


if __name__ == "__main__":
    sys.exit(main())
