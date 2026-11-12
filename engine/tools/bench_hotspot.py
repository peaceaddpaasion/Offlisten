# -*- coding: utf-8 -*-
"""8565U 热点分析：VAD / SenseVoice 解码 / 伪流式部分解码 / 翻译 / 空闲采集 开销实测"""
import time, os, sys
import numpy as np
import soundfile as sf

os.chdir(os.path.dirname(os.path.abspath(__file__)))
import pc_transcriber as pt
import sherpa_onnx

x, sr = sf.read(r'pc_models\sherpa-onnx-streaming-zipformer-en-2023-06-26\test_wavs\0.wav', dtype='float32')
dur = len(x) / sr
print(f"== 测试音频 {dur:.1f}s，机器 4C8T (i7-8565U) ==\n")

# ---- 1. VAD 开销 ----
seg = pt.VadSegmenter()
t0 = time.perf_counter()
out = seg.feed(x, 0.0)
vad_t = time.perf_counter() - t0
print(f"1) VAD 分段: {vad_t*1000:.1f} ms / {dur:.1f}s 音频 -> 占音频时长 {vad_t/dur*100:.2f}% (段数 {len(out)})")

# ---- 2. SenseVoice 冷/热解码 RTF ----
recog = pt.build_offline_sv()
def decode(samples):
    st = recog.create_stream()
    st.accept_waveform(16000, samples)
    recog.decode_stream(st)
    return st.result.text.strip()

t0 = time.perf_counter(); decode(x); cold = time.perf_counter() - t0
ts = []
for _ in range(3):
    t0 = time.perf_counter(); txt = decode(x); ts.append(time.perf_counter() - t0)
warm = min(ts)
print(f"2) SenseVoice 整段解码: 冷 {cold*1000:.0f} ms, 热 {warm*1000:.0f} ms -> RTF {warm/dur:.3f} (热)")
print(f"   文本: {txt[:50]}...")

# ---- 3. 伪流式部分解码开销（1.2s/3s/6s 段长）----
for sec in (1.2, 3.0, 6.0):
    n = int(sec * 16000)
    t0 = time.perf_counter(); decode(x[:n]); t = time.perf_counter() - t0
    print(f"3) 部分解码 {sec:.1f}s 音频: {t*1000:.0f} ms (RTF {t/sec:.2f})")

# ---- 4. 翻译延迟（冷/热）----
t0 = time.perf_counter(); pt.translate_text("The meeting starts at nine and ends at five."); tr_cold = time.perf_counter() - t0
t0 = time.perf_counter(); r = pt.translate_text("This course covers machine learning basics."); tr_warm = time.perf_counter() - t0
print(f"4) Argos 翻译: 冷 {tr_cold*1000:.0f} ms, 热 {tr_warm*1000:.0f} ms -> {r[:30]}")

# ---- 5. 采集线程空闲 CPU（纯录音重采样）----
import psutil, threading, queue as q
p = psutil.Process()
stop = threading.Event(); lv = {}
qu = q.Queue(maxsize=400)
th = threading.Thread(target=pt.open_input, args=("loopback", qu, stop, None, lv), daemon=True)
th.start()
time.sleep(2)
c0 = p.cpu_times()
time.sleep(8)
c1 = p.cpu_times()
stop.set()
cpu = ((c1.user - c0.user) + (c1.system - c0.system)) / 8.0 / psutil.cpu_count() * 100
print(f"5) 采集线程(仅环回+重采样)进程 CPU: {cpu:.1f}% (8s 采样, 全机 {psutil.cpu_count()} 逻辑核)")
print(f"   机器基准: {psutil.cpu_freq().current:.0f} MHz 当前频率")
