#!/usr/bin/env python3
"""把 dist-manifest.json 登记的发行文件推到 Hugging Face。

两种目标，用途不同，别混：
  --type model   Model repo。有 git 历史，每次上传是一个 commit，可以 pin revision，
                 适合放**权重**——dist-manifest.json 里的 sha256 才有长期意义。
  --type bucket  Storage bucket。S3 式可变存储，**没有版本控制**，同名覆盖即丢失旧版，
                 适合放**安装包**（文件名自带版本号即可规避），不适合放权重。

用法：
  # 先看会传什么，不联网
  python tools/push-hf.py --repo ToothpasteLake/offlisten --dry-run

  # 真的推（需要 HF_TOKEN，写权限）
  set HF_TOKEN=hf_xxx
  python tools/push-hf.py --repo ToothpasteLake/offlisten --type model \
      --source D:/projects/whisper

退出码：0 全部就绪；1 有文件缺失或哈希不符；2 环境/参数问题。
"""

import argparse
import hashlib
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(REPO_ROOT, "dist-manifest.json")
# 开发时 whisper-ext 与 whisper 工作区同级；fork 到别处时用 --source 覆盖。
DEFAULT_SOURCE = os.path.normpath(os.path.join(REPO_ROOT, "..", "whisper"))


def human(n):
    if n >= 1024 * 1024:
        return "%.2f MiB" % (n / 1024.0 / 1024.0)
    if n >= 1024:
        return "%.1f KiB" % (n / 1024.0)
    return "%d B" % n


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="Push release files listed in dist-manifest.json to the Hugging Face Hub.")
    ap.add_argument("--repo", required=True, help="<owner>/<name>，例如 ToothpasteLake/offlisten")
    ap.add_argument("--type", choices=["model", "bucket"], default="model")
    ap.add_argument("--tier", default="standard", help="dist-manifest.json 里的 tier 名，默认 standard")
    ap.add_argument("--source", default=DEFAULT_SOURCE, help="pc_models/ 所在的本地根目录，默认与原仓库同级的 whisper/")
    ap.add_argument("--dry-run", action="store_true", help="只校验并打印计划，不联网")
    ap.add_argument("--skip-hash", action="store_true", help="跳过 sha256 复核（大文件可省几秒，不推荐）")
    args = ap.parse_args()

    if not os.path.isfile(MANIFEST):
        print("找不到 %s" % MANIFEST, file=sys.stderr)
        return 2
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)

    tiers = manifest.get("tiers", {})
    if args.tier not in tiers:
        print("tier %r 不存在，可选：%s" % (args.tier, ", ".join(tiers)), file=sys.stderr)
        return 2
    tier = tiers[args.tier]
    if not tier.get("available", False):
        print("tier %r 标记为不可用，缺失：\n  %s" % (args.tier, "\n  ".join(tier.get("missing", []))), file=sys.stderr)
        return 2

    print("tier=%s  repo=%s  type=%s  source=%s" % (args.tier, args.repo, args.type, args.source))
    print("%d files, %s" % (tier["file_count"], human(tier["bytes"])))
    print()

    plan = []
    problems = []
    for item in tier["files"]:
        rel = item["path"]
        local = os.path.join(args.source, *rel.split("/"))
        if not os.path.isfile(local):
            problems.append("缺失 %s" % local)
            print("  MISS  %-78s %s" % (rel, human(item["bytes"])))
            continue
        size = os.path.getsize(local)
        digest = item["sha256"]
        if size != item["bytes"]:
            problems.append("大小不符 %s：%d != %d" % (rel, size, item["bytes"]))
            print("  SIZE  %-78s %s (期望 %s)" % (rel, human(size), human(item["bytes"])))
            continue
        if not args.skip_hash:
            actual = sha256_of(local)
            if actual != digest:
                problems.append("sha256 不符 %s：%s != %s" % (rel, actual[:12], digest[:12]))
                print("  HASH  %-78s %s" % (rel, human(size)))
                continue
        print("  ok    %-78s %10s  %s…" % (rel, human(size), digest[:12]))
        plan.append((local, rel))

    print()
    if problems:
        print("有 %d 个问题，未上传：" % len(problems), file=sys.stderr)
        for p in problems:
            print("  - %s" % p, file=sys.stderr)
        return 1

    if args.dry_run:
        print("dry-run：%d 个文件就绪，未联网。" % len(plan))
        if args.type == "bucket":
            print("提醒：bucket 无版本控制，同名覆盖会丢旧版。放安装包请让文件名带版本号。")
        return 0

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        print("需要 HF_TOKEN（写权限）。dry-run 不需要。", file=sys.stderr)
        return 2

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("缺依赖：pip install huggingface_hub", file=sys.stderr)
        return 2

    api = HfApi(token=token)
    try:
        who = api.whoami()
        print("已认证：%s" % who.get("name", "?"))
    except Exception as e:
        print("认证失败：%s" % e, file=sys.stderr)
        return 2

    if args.type == "bucket":
        try:
            from huggingface_hub import batch_bucket_files
        except ImportError:
            print("当前 huggingface_hub 版本不支持 buckets，请升级：pip install -U huggingface_hub", file=sys.stderr)
            return 2
        batch_bucket_files(args.repo, add=plan)
        base = "https://huggingface.co/buckets/%s/resolve" % args.repo
    else:
        api.create_repo(repo_id=args.repo, repo_type="model", exist_ok=True)
        for local, rel in plan:
            print("上传 %s" % rel)
            api.upload_file(
                path_or_fileobj=local,
                path_in_repo=rel,
                repo_id=args.repo,
                repo_type="model",
                commit_message="add %s from Offlisten dist-manifest" % os.path.basename(rel),
            )
        info = api.repo_info(repo_id=args.repo, repo_type="model")
        base = "https://huggingface.co/%s/resolve/%s" % (args.repo, info.sha)

    print()
    print("完成。直链前缀：")
    print("  " + base)
    print("把 sha256 写进发布说明，别人就能核对下载到的字节与 dist-manifest.json 一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
