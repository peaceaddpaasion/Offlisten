#!/usr/bin/env python3
"""Generate dist-manifest.json: what actually ships, how big, and its sha256.

Only the files the runtime opens are listed. Everything else in pc_models
(fp32 weights, .tar.bz2 archives, test_wavs) is development material and is
deliberately excluded -- see docs/distribution.md.

Usage:
    python scripts/build-dist.py --source D:/projects/whisper
    python scripts/build-dist.py --source D:/projects/whisper --stage dist/stage
    python scripts/build-dist.py --source D:/projects/whisper --compress

--stage copies the selected files into a flat-ish tree and reports the real
on-disk size. --compress additionally packs that tree with deflate and reports
the payload size a user would actually download.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import zipfile

SV_DIR = "pc_models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
EN_DIR = "pc_models/sherpa-onnx-streaming-zipformer-en-2023-06-26"
ZH_DIR = "pc_models/sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23"
VAD = "pc_models/silero_vad.onnx"


# name -> (relative paths, note). "required" means the engine opens it at startup.
TIERS: dict[str, dict] = {
    "standard": {
        "label": "Standard (SenseVoice int8) - zh/en/ja/ko/yue, non-streaming, punctuation",
        "required": [
            f"{SV_DIR}/model.int8.onnx",
            f"{SV_DIR}/tokens.txt",
            VAD,
        ],
        "optional": [
            f"{SV_DIR}/LICENSE",
            f"{SV_DIR}/README.md",
            f"{SV_DIR}/export-onnx.py",
        ],
    },
    "english": {
        "label": "English add-on (streaming zipformer int8)",
        "required": [
            f"{EN_DIR}/encoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
            f"{EN_DIR}/decoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
            f"{EN_DIR}/joiner-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
            f"{EN_DIR}/tokens.txt",
        ],
        "optional": [
            f"{EN_DIR}/bpe.model",
            f"{EN_DIR}/README.md",
        ],
    },
    "lite": {
        "label": "Lite (streaming zipformer int8, zh-14M + en)",
        "required": [
            f"{ZH_DIR}/encoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
            f"{ZH_DIR}/decoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
            f"{ZH_DIR}/joiner-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
            f"{ZH_DIR}/tokens.txt",
            f"{EN_DIR}/encoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
            f"{EN_DIR}/decoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
            f"{EN_DIR}/joiner-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
            f"{EN_DIR}/tokens.txt",
            VAD,
        ],
        "optional": [],
    },
}

# Dev-only material that must never reach a release. Listed so the manifest can
# state what was skipped and why, instead of leaving it implicit.
EXCLUDED = {
    f"{SV_DIR}/model.onnx": "fp32 weights, 937 MB, runtime never opens it",
    f"{EN_DIR}/encoder-epoch-99-avg-1-chunk-16-left-128.onnx": "fp32 encoder",
    f"{EN_DIR}/decoder-epoch-99-avg-1-chunk-16-left-128.onnx": "fp32 decoder",
    f"{EN_DIR}/joiner-epoch-99-avg-1-chunk-16-left-128.onnx": "fp32 joiner",
    "pc_models/sensevoice.tar.bz2": "source archive",
    "pc_models/en-streaming.tar.bz2": "source archive",
    f"{SV_DIR}/test_wavs": "sample audio",
    f"{EN_DIR}/test_wavs": "sample audio",
}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def describe(root: str, rel: str, required: bool) -> dict | None:
    full = os.path.join(root, rel)
    if not os.path.isfile(full):
        return None
    return {
        "path": rel,
        "bytes": os.path.getsize(full),
        "sha256": sha256(full),
        "required": required,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="path to the backend project (contains pc_models/)")
    ap.add_argument("--out", default="dist-manifest.json")
    ap.add_argument("--stage", help="copy the standard tier into this directory")
    ap.add_argument("--compress", action="store_true", help="also deflate the staged tree and report payload size")
    args = ap.parse_args()

    root = os.path.abspath(args.source)
    manifest: dict = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source_root": ".",
        "note": "Only files the runtime opens are listed. fp32 weights and .tar.bz2 archives are excluded by design.",
        "tiers": {},
        "excluded": [{"path": p, "reason": r, "present": os.path.exists(os.path.join(root, p))}
                     for p, r in EXCLUDED.items()],
    }

    errors: list[str] = []
    for name, spec in TIERS.items():
        files, missing = [], []
        for rel in spec["required"]:
            item = describe(root, rel, True)
            (files if item else missing).append(item or rel)
        for rel in spec["optional"]:
            item = describe(root, rel, False)
            if item:
                files.append(item)
        total = sum(f["bytes"] for f in files)
        usable = not missing
        if not usable:
            errors.append(name)
        manifest["tiers"][name] = {
            "label": spec["label"],
            "available": usable,
            "missing": missing,
            "file_count": len(files),
            "bytes": total,
            "mib": round(total / 1048576, 1),
            "files": files,
        }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"{'tier':10} {'files':>5} {'MiB':>8}  status")
    for name, t in manifest["tiers"].items():
        status = "ok" if t["available"] else f"incomplete, missing {len(t['missing'])}"
        print(f"{name:10} {t['file_count']:>5} {t['mib']:>8.1f}  {status}")

    if args.stage:
        stage = os.path.abspath(args.stage)
        if os.path.isdir(stage):
            shutil.rmtree(stage)
        payload = manifest["tiers"]["standard"]["files"]
        for f in payload:
            dst = os.path.join(stage, f["path"])
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(root, f["path"]), dst)
        staged = sum(os.path.getsize(os.path.join(dp, fn))
                     for dp, _, fns in os.walk(stage) for fn in fns)
        print(f"\nstaged  {len(payload)} files, {staged / 1048576:.1f} MiB -> {stage}")

        if args.compress:
            archive = stage.rstrip("\\/") + ".zip"
            t0 = time.time()
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                for dp, _, fns in os.walk(stage):
                    for fn in fns:
                        full = os.path.join(dp, fn)
                        z.write(full, os.path.relpath(full, stage))
            print(f"packed  {os.path.getsize(archive) / 1048576:.1f} MiB "
                  f"({os.path.getsize(archive) / staged * 100:.0f}% of staged, {time.time() - t0:.0f}s)")
            print(f"        {archive}")

    if errors:
        print(f"\nincomplete tiers (files absent from pc_models/): {', '.join(errors)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
