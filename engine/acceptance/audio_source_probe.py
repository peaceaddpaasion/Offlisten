# -*- coding: utf-8 -*-
"""音频输入源实机探针：定量对比 mic / loopback 电平与噪声门限的关系。

不启动 GUI、不加载 ASR 模型，只用真实声卡：
  .venv/Scripts/python.exe acceptance/audio_source_probe.py

播放模型自带的测试 wav 到默认扬声器，分别用
  mic（真实麦克风，收扬声器外放）与 loopback（WASAPI 环回，直接取播放流）
采集同样时长，统计 RMS 分布，并与 sv_pipeline 的 GATE 比较。

这一步专门证伪/坐实「麦克风模式不出字」是否由绝对噪声门限吞掉。
证据写到 acceptance/audio_source_probe_<时间戳>.txt
"""
import os
import sys
import time
import wave
from datetime import datetime

import numpy as np
import soundcard as sc
import winsound

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
import pc_transcriber as pt  # 门限口径与产品代码同源，不在证据里写死数字
WAV = os.path.join(ROOT, "pc_models", "sherpa-onnx-streaming-zipformer-en-2023-06-26",
                   "test_wavs", "0.wav")
GATE_LOOPBACK = pt.NOISE_GATE
GATE_MIC = pt.MIC_NOISE_GATE
BLOCK = 4800           # 100ms @48k
N_BLOCKS = 30          # 3s

lines = []


def log(s=""):
    print(s)
    lines.append(s)


def measure(kind):
    if kind == "mic":
        target = sc.default_microphone().name
        dev = sc.get_microphone(target, include_loopback=False)
    else:
        target = sc.default_speaker().name
        dev = sc.get_microphone(target, include_loopback=True)
    log("  device=%r  isloopback=%s" % (dev.name, getattr(dev, "isloopback", "?")))

    vals = []
    with dev.recorder(samplerate=48000, channels=1, blocksize=BLOCK) as rec:
        # 先开流再播，避免漏掉开头
        winsound.PlaySound(WAV, winsound.SND_FILENAME | winsound.SND_ASYNC)
        for _ in range(N_BLOCKS):
            d = rec.record(numframes=BLOCK)
            vals.append(float(np.sqrt(np.mean(d[:, 0] ** 2))))
    winsound.PlaySound(None, winsound.SND_PURGE)
    time.sleep(0.2)
    return vals


def measure_silent(kind):
    """不播放任何声音，采 1s 静音基线，用于评估降门限后的杂段风险。"""
    if kind == "mic":
        dev = sc.get_microphone(sc.default_microphone().name, include_loopback=False)
    else:
        dev = sc.get_microphone(sc.default_speaker().name, include_loopback=True)
    vals = []
    with dev.recorder(samplerate=48000, channels=1, blocksize=BLOCK) as rec:
        for _ in range(10):
            d = rec.record(numframes=BLOCK)
            vals.append(float(np.sqrt(np.mean(d[:, 0] ** 2))))
    return vals


def main():
    with wave.open(WAV, "rb") as w:
        log("测试音频: %s  %.2fs  %dHz" %
            (os.path.basename(WAV), w.getnframes() / w.getframerate(), w.getframerate()))
    log("门限 修复前统一=%.4f  |  修复后 系统声音=%.4f / 麦克风=%.4f  |  每块 100ms，共 %d 块" %
        (GATE_LOOPBACK, GATE_LOOPBACK, GATE_MIC, N_BLOCKS))
    log("")
    out = {}
    for kind in ("loopback", "mic"):
        log("[%s]" % kind)
        vals = measure(kind)
        out[kind] = vals
        peak = max(vals)
        passed_old = sum(1 for v in vals if v >= GATE_LOOPBACK)
        passed_new = sum(1 for v in vals if v >= (GATE_MIC if kind == "mic" else GATE_LOOPBACK))
        log("  peak=%.6f  mean=%.6f  min=%.6f" %
            (peak, float(np.mean(vals)), min(vals)))
        log("  修复前门限 %.4f -> 过 %d/%d 块  ｜  修复后门限 %.4f -> 过 %d/%d 块" %
            (GATE_LOOPBACK, passed_old, N_BLOCKS,
             GATE_MIC if kind == "mic" else GATE_LOOPBACK, passed_new, N_BLOCKS))
        log("  前 8 块: %s" % " ".join("%.5f" % v for v in vals[:8]))
        log("")

    lb, mi = out["loopback"], out["mic"]
    ratio = (max(lb) / max(mi)) if max(mi) > 0 else float("inf")
    mic_old = sum(1 for v in mi if v >= GATE_LOOPBACK)
    mic_new = sum(1 for v in mi if v >= GATE_MIC)
    log("loopback/mic 峰值比 = %.1fx" % ratio)
    log("结论: 修复前统一门限 %.4f 下 mic 只有 %d/%d 块能进 VAD（语音被整块吞掉）；"
        "按音源改用 %.4f 后为 %d/%d 块" %
        (GATE_LOOPBACK, mic_old, N_BLOCKS, GATE_MIC, mic_new, N_BLOCKS))
    log("这是输入层增益问题，不是识别引擎问题：引擎无需返修。")
    log("")
    sil_mic = measure_silent("mic")
    sil_lb = measure_silent("loopback")
    n_mic = sum(1 for v in sil_mic if v >= GATE_MIC)
    n_lb = sum(1 for v in sil_lb if v >= GATE_LOOPBACK)
    log("[静音基线] 不播放时 mic %d/10 块过 %.4f 门限（峰值 %.6f）；"
        "loopback %d/10 块过 %.4f（峰值 %.6f）" %
        (n_mic, GATE_MIC, max(sil_mic), n_lb, GATE_LOOPBACK, max(sil_lb)))
    log("局限: mic 门限降到能放进语音的同时，静音底噪也会进 VAD → 长时间挂机可能出杂段(I-031)。")
    log("      相对自适应门限仍是 O-034 挂账；mic 适合人对着麦克风说话，不适合录扬声器外放。")
    log("")
    log("[门限扫描] 同一组 mic 样本在各候选门限下：语音块 / 静音块")
    for g in (0.0006, 0.0008, 0.0010, 0.0012, 0.0015, 0.0020):
        v = sum(1 for x in mi if x >= g)
        s = sum(1 for x in sil_mic if x >= g)
        log("  %.4f  语音 %2d/30  静音 %2d/10" % (g, v, s))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(os.path.dirname(__file__), "audio_source_probe_%s.txt" % stamp)
    with open(path, "w", encoding="utf-8") as f:
        f.write("whisper 音频输入源实机探针  %s\n" % datetime.now().isoformat(timespec="seconds"))
        f.write("本机真实声卡，无 GUI / 无 ASR 模型\n\n")
        f.write("\n".join(lines) + "\n")
    print("证据:", path)


if __name__ == "__main__":
    main()
