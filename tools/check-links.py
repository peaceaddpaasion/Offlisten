#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查文档里引用的仓库文件是否真实存在。

为什么需要它：GitHub 上，一个指向已删除文件的引用就是一个 404，而本地看不出来。
仓库里真实发生过的两次：矩阵图拆成 matrix-zh / matrix-en 之后，五处文档还在指 matrix.svg；
scripts/ 改名 tools/ 之后，README 的示例命令还是旧路径。两次都是人肉发现的。

检查两类引用：
  1. Markdown 链接  `[x](docs/paper.md)`
  2. 反引号路径    `` `docs/paper.md` `` —— 本仓库文档主要用这种写法，
     所以只查 1 会几乎什么都查不到。

刻意不查的东西（查了只会制造假失败）：
  - **锚点** `doc.md#section`：GitHub 的锚点生成规则不稳定。
  - **模型与数据文件** `model.int8.onnx`、`pc_models/`：按设计不入库。
  - **不带顶层目录的裸文件名** `manifest.json`：在散文里指的是 `extension/manifest.json`，
    在代码块里指的是子目录里的同名文件，无法从字面判断，宁可不查。
  - **外部链接** http(s)、mailto。

大小写是重点：Windows 文件系统不区分大小写，`Matrix-ZH.png` 在本地能打开、在 GitHub 上 404。
所以逐级比对 os.listdir 的字面名字，而不是用 os.path.exists。

用法：
    python tools/check-links.py            # 仓库根执行，失败退出码 1
    python tools/check-links.py --quiet    # 只打印失败
"""
import os
import re
import sys
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "dist", "node_modules", "__pycache__", ".venv", "pc_models"}

LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)>\s]+)>?\s*\)")
FENCE = re.compile(r"^```.*?^```", re.S | re.M)
CODE = re.compile(r"`([^`\n]{2,120})`")
# 只认顶层四个目录开头的路径；行号后缀（:40-42）先剥掉
LINEREF = re.compile(r":\d+(?:-\d+)?$")
PATHLIKE = re.compile(r"^(?:\.\./)*(?:docs|engine|extension|tools)/[\w./\-]+$")

# 按设计不入库的路径（被 .gitignore 覆盖），检查它们的存不存在没有意义
ALLOW_MISSING = {
    "engine/pc_models",  # 模型 229 MiB，不入库；获取方式见 CONTRIBUTING.md
}


def allowed_missing(token):
    return any(token == a or token.startswith(a + "/") for a in ALLOW_MISSING)


def md_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.lower().endswith(".md"):
                yield os.path.join(dirpath, fn)


def exists_exact(base, rel):
    """逐级按字面名字比对，等价于大小写敏感的存在性检查。"""
    cur = base
    for part in rel.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            cur = os.path.dirname(cur)
            continue
        try:
            entries = os.listdir(cur)
        except OSError:
            return False
        if part not in entries:
            return False
        cur = os.path.join(cur, part)
    return True


def is_external(target):
    return target.lower().startswith(
        ("http://", "https://", "mailto:", "ftp:", "//")
    ) or target.startswith("#") or target == ""


def main(argv):
    quiet = "--quiet" in argv
    failures = []
    checked = 0
    for path in md_files():
        raw = open(path, encoding="utf-8", errors="replace").read()
        text = FENCE.sub("", raw)  # 代码块里的示例不是引用
        rel_file = os.path.relpath(path, ROOT).replace("\\", "/")

        for lineno, line in enumerate(text.splitlines(), 1):
            # 1) markdown 链接
            for m in LINK.finditer(line):
                target = m.group(1).strip()
                if is_external(target):
                    continue
                target = unquote(target.split("#", 1)[0].split("?", 1)[0])
                if not target:
                    continue
                base = ROOT if target.startswith("/") else os.path.dirname(path)
                checked += 1
                if not exists_exact(base, target.lstrip("/").replace("\\", "/")):
                    failures.append((rel_file, lineno, target))

            # 2) 反引号里形如顶层路径的片段
            for m in CODE.finditer(line):
                token = LINEREF.sub("", m.group(1).strip()).rstrip("/")
                if not PATHLIKE.match(token) or allowed_missing(token):
                    continue
                base = os.path.dirname(path) if token.startswith("../") else ROOT
                checked += 1
                if not exists_exact(base, token):
                    failures.append((rel_file, lineno, token))

    if failures:
        for f, ln, t in failures:
            print("MISSING  %s:%d  ->  %s" % (f, ln, t))
        print("\n%d broken of %d references" % (len(failures), checked))
        return 1
    if not quiet:
        print("OK  %d references, all resolve" % checked)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
