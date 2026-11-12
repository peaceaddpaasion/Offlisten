# -*- coding: utf-8 -*-
"""环回路由矩阵探针：对每个输出端点测 (a)播放到该端点能否被自身环回采到"""
import soundcard as sc, soundfile as sf, numpy as np, time

x, sr = sf.read(r'pc_models\sherpa-onnx-streaming-zipformer-en-2023-06-26\test_wavs\0.wav', dtype='float32')
if x.ndim > 1:
    x = x[:, 0]
seg = x[: sr * 3]  # 3秒

sps = sc.all_speakers()
default = sc.default_speaker()
print('当前默认输出:', default.name)
print('端点列表:', [s.name for s in sps])

def rms_of(endpoint_name, play_to):
    """loopback 采集 endpoint_name 的同时，把音频播放到 play_to"""
    mic = sc.get_microphone(endpoint_name, include_loopback=True)
    player = sc.get_speaker(play_to) if play_to else sc.default_player()
    with mic.recorder(samplerate=48000, channels=2) as rec:
        time.sleep(0.3)
        with player.player(samplerate=48000, channels=2) as p:
            p.play(np.stack([seg, seg], axis=1))
            data = rec.record(numframes=48000 * 4)
        tail = rec.record(numframes=48000 * 1)
    blob = np.concatenate([data, tail])
    rms = float(np.sqrt(np.mean(blob ** 2)))
    return rms

for sp in sps:
    try:
        r_self = rms_of(sp.name, sp.name)     # 播到该端点+采该端点
        print(f"[{sp.name}] 自环 RMS = {r_self:.5f}", "✅可采" if r_self > 1e-4 else "❌静音")
    except Exception as e:
        print(f"[{sp.name}] 探测失败: {e}")
    time.sleep(1.0)  # 蓝牙 profile 切换缓冲
