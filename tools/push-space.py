#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 space/ 目录推到 Hugging Face Space，再逐个核对线上文件与本地是否同字节。

为什么单独一个脚本、不复用 push-hf.py：
  push-hf.py 是**清单驱动**的——它只信任 dist-manifest.json 里登记的权重，逐个核 sha256，
  理由是权重一旦传错，下游所有复跑都跟着错。
  Space 是**页面驱动**的：改一行文案就该重新上线，没有清单可核。
  两者的校验方式不同（前者核哈希，后者核"线上的字节数等于本地"），混在一个入口里会让
  两边都变得不可信，所以拆开。

用法：
    python tools/push-space.py --dry-run          # 只列出会传什么
    python tools/push-space.py                    # 真的传
    python tools/push-space.py --verify           # 传完再 HEAD 一遍线上文件

凭证：--token → $HF_TOKEN → 默认凭证文件（whisper/key.env，一行 hf_ 开头的 token）。
"""
import argparse
import os
import sys
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPACE_DIR = os.path.join(REPO_ROOT, "space")
DEFAULT_REPO = "ToothpasteLake/offlisten"
DEFAULT_TOKEN_FILE = os.path.normpath(os.path.join(REPO_ROOT, "..", "whisper", "key.env"))

# 下划线开头的是本地临时产物（截图、渲染中间文件），不进 Space；
# __pycache__ 是跑 Gradio 版时留下的，同理。
SKIP_PREFIX = ("_", ".")
SKIP_NAMES = {"__pycache__", ".gitattributes"}
SKIP_SUFFIX = (".pyc",)


def human(n):
    if n >= 1024 * 1024:
        return "%.2f MiB" % (n / 1024.0 / 1024.0)
    if n >= 1024:
        return "%.1f KiB" % (n / 1024.0)
    return "%d B" % n


def token_from_file(path):
    """凭证文件允许两种写法：`HF_TOKEN=hf_xxx` 或直接一行 hf_xxx（本项目是后者）。"""
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("hf_"):
                return line
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip().upper() in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
                    return v.strip().strip('"')
    return ""


def collect(root):
    plan = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_NAMES and not d.startswith(SKIP_PREFIX)]
        for name in sorted(filenames):
            if name in SKIP_NAMES or name.startswith(SKIP_PREFIX) or name.endswith(SKIP_SUFFIX):
                continue
            local = os.path.join(dirpath, name)
            rel = os.path.relpath(local, root).replace(os.sep, "/")
            plan.append((local, rel, os.path.getsize(local)))
    return sorted(plan, key=lambda x: x[1])


def verify(repo, plan):
    """线上字节数等于本地字节数，才算这次上传生效了。

    只比大小不比内容：Space 的 /resolve/ 会做 CDN 缓存，HEAD 拿不到稳定 etag；
    而"大小一致 + 上传调用返回了 commit"已经能排除绝大多数失败（半截文件、传错目录）。
    """
    base = "https://huggingface.co/spaces/%s/resolve/main/" % repo
    bad = 0
    for _local, rel, size in plan:
        url = base + rel
        req = urllib.request.Request(url, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                remote = int(r.headers.get("Content-Length", "-1"))
                ok = remote == size
                print("  %s  %-26s 本地 %8s 线上 %8s" % ("ok  " if ok else "DIFF", rel, human(size), human(remote)))
                if not ok:
                    bad += 1
        except Exception as e:  # noqa: BLE001 - 校验失败要如实报出来，不能吞
            print("  FAIL  %-26s %s" % (rel, e))
            bad += 1
    return bad


def main():
    ap = argparse.ArgumentParser(description="Push the space/ directory to a Hugging Face Space.")
    ap.add_argument("--repo", default=DEFAULT_REPO, help="<owner>/<name>，默认 %s" % DEFAULT_REPO)
    ap.add_argument("--dir", default=SPACE_DIR, help="要上传的目录，默认仓库里的 space/")
    ap.add_argument("--token", default="")
    ap.add_argument("--token-file", default=DEFAULT_TOKEN_FILE)
    ap.add_argument("--dry-run", action="store_true", help="只列文件，不联网")
    ap.add_argument("--verify", action="store_true", help="上传后逐个核对线上文件大小")
    args = ap.parse_args()

    if not os.path.isdir(args.dir):
        print("找不到目录 %s" % args.dir, file=sys.stderr)
        return 2

    plan = collect(args.dir)
    if not plan:
        print("%s 里没有可上传的文件" % args.dir, file=sys.stderr)
        return 2

    total = sum(s for _, _, s in plan)
    print("目标 Space：%s｜%d 个文件，%s\n" % (args.repo, len(plan), human(total)))
    for _local, rel, size in plan:
        print("  %-30s %10s" % (rel, human(size)))
    print()

    if args.dry_run:
        print("dry-run：未联网。")
        return 0

    token = args.token or os.environ.get("HF_TOKEN") or token_from_file(args.token_file)
    if not token:
        print("需要 token：--token、$HF_TOKEN 或 %s" % args.token_file, file=sys.stderr)
        return 2

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("缺依赖：pip install huggingface_hub", file=sys.stderr)
        return 2

    api = HfApi(token=token)
    try:
        who = api.whoami()
    except Exception as e:  # noqa: BLE001
        print("认证失败：%s" % e, file=sys.stderr)
        return 2
    print("已认证：%s" % who.get("name", "?"))

    for local, rel, _size in plan:
        print("上传 %s" % rel)
        api.upload_file(
            path_or_fileobj=local,
            path_in_repo=rel,
            repo_id=args.repo,
            repo_type="space",
            commit_message="update %s" % rel,
        )

    print("\n完成：https://huggingface.co/spaces/%s" % args.repo)
    if args.verify:
        print("\n核对线上文件：")
        bad = verify(args.repo, plan)
        if bad:
            print("\n有 %d 个文件与本地不一致。" % bad, file=sys.stderr)
            return 1
        print("\n全部一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
