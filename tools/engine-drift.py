#!/usr/bin/env python3
"""Check (and optionally fix) drift between engine/ in this repo and the dev workspace.

engine/ is a published snapshot. Development happens in the workspace, so the two
drift silently unless something compares them. This does exactly that, nothing else.

    python tools/engine-drift.py                 # report only
    python tools/engine-drift.py --copy          # repo -> workspace (repo wins)

Exit code: 0 if identical, 1 if differences found (even in report-only mode),
so it can be wired into a pre-push step later.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(REPO, "engine")


def rel_map() -> list[tuple[str, str]]:
    """(repo-relative path, workspace-relative path)."""
    out: list[tuple[str, str]] = []
    for name in sorted(os.listdir(ENGINE)):
        full = os.path.join(ENGINE, name)
        if os.path.isfile(full) and name.endswith(".py"):
            out.append((f"engine/{name}", name))
    for sub, target in (("web_live", "web_live"), ("acceptance", "acceptance")):
        d = os.path.join(ENGINE, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if os.path.isfile(os.path.join(d, name)):
                out.append((f"engine/{sub}/{name}", f"{target}/{name}"))
    tools = os.path.join(ENGINE, "tools")
    if os.path.isdir(tools):
        for name in sorted(os.listdir(tools)):
            if name.endswith(".py"):
                out.append((f"engine/tools/{name}", name))
    return out


def sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default=os.path.join(os.path.dirname(REPO), "whisper"),
                    help="development workspace (default: sibling directory named whisper)")
    ap.add_argument("--copy", action="store_true", help="overwrite workspace files with the repo version")
    args = ap.parse_args()

    work = os.path.abspath(args.workdir)
    if not os.path.isdir(work):
        print(f"workspace not found: {work}", file=sys.stderr)
        return 2

    same, differ, only_repo, only_work = [], [], [], []
    for repo_rel, work_rel in rel_map():
        a = os.path.join(REPO, repo_rel.replace("/", os.sep))
        b = os.path.join(work, work_rel.replace("/", os.sep))
        if not os.path.exists(b):
            only_repo.append(work_rel)
            continue
        if sha(a) == sha(b):
            same.append(work_rel)
        else:
            differ.append(work_rel)

    print(f"repo      {REPO}")
    print(f"workspace {work}")
    print(f"identical {len(same)}   differ {len(differ)}   missing-in-workspace {len(only_repo)}")
    for name in differ:
        print(f"  differ   {name}")
    for name in only_repo:
        print(f"  missing  {name}")

    if args.copy and (differ or only_repo):
        for name in differ + only_repo:
            src = next(os.path.join(REPO, r.replace("/", os.sep))
                       for r, w in rel_map() if w == name)
            dst = os.path.join(work, name.replace("/", os.sep))
            os.makedirs(os.path.dirname(dst) or work, exist_ok=True)
            shutil.copy2(src, dst)
        print(f"copied {len(differ) + len(only_repo)} file(s) repo -> workspace")

    return 0 if not (differ or only_repo) else 1


if __name__ == "__main__":
    raise SystemExit(main())
