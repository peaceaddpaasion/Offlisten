# -*- coding: utf-8 -*-
"""
PC 全局转写 + 实时字幕 + 离线翻译（sherpa-onnx + Argos Translate，纯本地，无 LLM）
================================================================================
用法（推荐 run_transcriber.bat）：
  run_transcriber.bat live                          # 双语字幕浮窗（默认 sensevoice + 翻译）
  run_transcriber.bat live --source mic             # 麦克风（自动用低噪声门限）
  run_transcriber.bat live --source mic --noise-gate 0.0004   # 麦克风电平过低时手动放低门限
  run_transcriber.bat live --engine zipformer       # 英文低延迟流式档
  run_transcriber.bat live --list-devices           # 列输出设备
  run_transcriber.bat live --device 耳机            # 指定采集哪个输出设备
  run_transcriber.bat srt meeting.wav -o out.srt --translate   # 文件转双语 SRT
  run_transcriber.bat live --web-live                  # 同时开启本地 web live 页面（旁路，默认关；自动打开浏览器）
  run_transcriber.bat live --headless                  # 无桌面窗：扩展 / live 页控制为主，自带 tkinter 前端不加载
  run_transcriber.bat live --headless --overlay       # 无桌面窗，但额外开一个轻量悬浮字幕（可选）
停止：点 ✕ 或 Ctrl+C
"""
import argparse
import os
import queue
import re
import sys
import threading
import time

# pythonw（无控制台）下 stdout/stderr 为 None，print 会崩 —— 重定向到日志文件
if sys.stdout is None or sys.stderr is None:
    _log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_run.log"),
                "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log
    import faulthandler
    faulthandler.enable(_log)

import numpy as np
import soundcard as sc
import sherpa_onnx

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "pc_models/sherpa-onnx-streaming-zipformer-en-2023-06-26")
SV_DIR = os.path.join(BASE_DIR, "pc_models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17")
VAD_MODEL = os.path.join(BASE_DIR, "pc_models/silero_vad.onnx")
VAD_THRESHOLD = 0.4
NOISE_GATE = float(os.environ.get("WHISPER_NOISE_GATE", "0.006"))  # O-034: 相对门限挂账，先暴露绝对门限
# I-065: 0.006 是按 loopback（直接取播放流）增益调的。麦克风收扬声器外放经空气传播，
# 实机对照 loopback 峰值 0.282 / mic 峰值 0.0016（差 180 倍），沿用同一门限会把 mic 语音整块吞掉。
MIC_NOISE_GATE = float(os.environ.get("WHISPER_MIC_NOISE_GATE", "0.0008"))
TARGET_SR = 16000
CHUNK_MS = 100
CONFIG_PATH = os.path.join(BASE_DIR, "pc_ui_config.json")

# 增量继承自原 APK 悬浮字幕栏的可调项
FONT_COLORS = [("白", "white"), ("黄", "#ffd54a"), ("天蓝", "#4fc3f7"),
               ("橙", "#ffb74d"), ("浅灰", "#cfd8dc"), ("深灰", "#90a4ae")]
BACKGROUNDS = [("黑色", "#101418"), ("深蓝", "#0d1b2a"), ("深蓝灰", "#263238"),
               ("灰色", "#37474f"), ("半透明", None), ("浮层", "OVERLAY")]
               # OVERLAY=色键+抖动黑板：背景半透明(视觉)、文字全实——APK 形态的 tkinter 等价物
FONT_SIZES = [14, 16, 18, 20, 24, 28]


# ---------------------------------------------------------------- 引擎 ----
def build_recognizer(model_dir: str = MODEL_DIR) -> sherpa_onnx.OnlineRecognizer:
    import os
    files = os.listdir(model_dir)
    def pick(prefix):
        cands = sorted(f for f in files if f.startswith(prefix) and f.endswith("int8.onnx"))
        if cands:
            return os.path.join(model_dir, cands[0])
        cands = sorted(f for f in files if f.startswith(prefix) and f.endswith(".onnx"))
        return os.path.join(model_dir, cands[0])
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=os.path.join(model_dir, "tokens.txt"),
        encoder=pick("encoder"), decoder=pick("decoder"), joiner=pick("joiner"),
        num_threads=4, sample_rate=TARGET_SR, feature_dim=80,
        decoding_method="greedy_search",
        rule1_min_trailing_silence=2.0, rule2_min_trailing_silence=0.8,
        rule3_min_utterance_length=20.0,
    )


def build_offline_sv(model_dir: str = SV_DIR) -> sherpa_onnx.OfflineRecognizer:
    import os
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=os.path.join(model_dir, "model.int8.onnx"),
        tokens=os.path.join(model_dir, "tokens.txt"),
        num_threads=4, language="", use_itn=True,
    )


# ---------------------------------------------------------- 音频采集 ----
def resolve_source(source: str, device: str = None):
    """按音源解析设备，返回 (设备名, 采样率, kind, 显示名)。"""
    if source == "mic":
        spk = sc.default_microphone()
        return spk.name, 48000, "mic", spk.name
    if device:
        cands = [sp for sp in sc.all_speakers() if device.lower() in sp.name.lower()]
        if not cands:
            print(f"找不到输出设备含 '{device}'，回退默认。可用: "
                  + " | ".join(sp.name for sp in sc.all_speakers()))
            spk = sc.default_speaker()
        else:
            spk = cands[0]
    else:
        spk = sc.default_speaker()
    if "hands-free" in spk.name.lower():
        print("⚠ 蓝牙耳机当前是 Hands-Free(通话档)端点，Windows 环回采集不到它的声音！"
              "请在 系统声音设置 把输出切到 'Stereo' 档或扬声器。本工具检测到后会自动跟随切换。")
    return spk.name, 48000, "loopback", f"[系统声音] {spk.name}"


def noise_gate_for(source, override=None):
    """按音源取 RMS 噪声门限；显式覆盖优先（--noise-gate / 环境变量）。"""
    if override is not None:
        return float(override)
    return MIC_NOISE_GATE if source == "mic" else NOISE_GATE


def open_input(source: str, q: queue.Queue, stop: threading.Event,
               device: str = None, level_holder: dict = None,
               source_ref=None):
    """采集循环。source_ref 为可选 callable：运行中改音源会立即重开采集流（I-066）。"""
    def current():
        try:
            return source_ref() if source_ref else source
        except Exception:
            return source

    active = current()
    target, sr, kind, name = resolve_source(active, device)
    ratio = sr // TARGET_SR

    def announce():
        auto = (not device) or (kind == "mic")
        print(f"输入源: {name} @{sr}Hz -> 重采样 {TARGET_SR}Hz"
              + ("（自动跟随设备切换）" if auto else ""))

    announce()
    while not stop.is_set():
        wanted = current()
        if wanted != active:
            print(f"音源已切换: {active} -> {wanted}，重开采集流")
            active = wanted
            try:
                target, sr, kind, name = resolve_source(active, device)
                ratio = sr // TARGET_SR
                announce()
            except Exception as e:
                print(f"切换音源失败({e})，保持原音源")
                continue
        follow_default = (not device) or (kind == "mic")
        try:
            mic = sc.get_microphone(target, include_loopback=(kind == "loopback"))
        except Exception as e:
            print(f"设备 '{target}' 暂不可用({e})，2s 后重试")
            if stop.wait(2.0):
                return
            continue
        try:
            rec = mic.recorder(samplerate=sr, channels=1, blocksize=sr * CHUNK_MS // 1000)
            rec.__enter__()
        except Exception as e:   # O-033: get_microphone 成功后设备仍可能消失，不再杀线程
            print(f"采集流创建失败({e})，2s 后重试")
            if stop.wait(2.0):
                return
            continue
        try:
            while not stop.is_set():
                if current() != active:
                    break  # 音源变了，交给外层重开
                if follow_default:  # 检测默认设备切换，自动换绑
                    try:
                        cur = sc.default_microphone().name if kind == "mic" \
                            else sc.default_speaker().name
                    except Exception:
                        cur = target
                    if cur != target:
                        print(f"默认设备已切换: {target} -> {cur}，自动跟随")
                        target = cur
                        break
                try:
                    data = rec.record(numframes=sr * CHUNK_MS // 1000)
                except Exception as e:   # 单块采集失败：跳过，连续失败则重开
                    print(f"采集块异常({e})，重开采集流")
                    break
                x = data[:, 0]
                if ratio > 1:
                    x = x[: len(x) // ratio * ratio].reshape(-1, ratio).mean(axis=1)
                x = x.astype(np.float32)
                if level_holder is not None:
                    level_holder["rms"] = float(np.sqrt(np.mean(x * x))) if len(x) else 0.0
                    level_holder["t"] = time.time()
                try:
                    q.put(x, timeout=0.5)
                except queue.Full:
                    pass  # 丢块优于卡死
        finally:
            try:                 # I-032: 切换时旧流关闭抛错不再杀线程
                rec.__exit__(None, None, None)
            except Exception as e:
                print(f"旧采集流关闭异常(已忽略): {e}")
        if not stop.is_set():
            time.sleep(0.2)  # 重开缓冲


# ------------------------------------------------------------ VAD ----
class VadSegmenter:
    """silero 逐窗分段：预卷积防吞字 + 段首裁剪防幻听 + 跨批余数衔接。"""
    WIN = 512
    CLOSE_SIL = int(0.6 * TARGET_SR / WIN)
    MAX_LEN = 8 * TARGET_SR
    PRE_ROLL = 8

    def __init__(self):
        cfg = sherpa_onnx.VadModelConfig(
            silero_vad=sherpa_onnx.SileroVadModelConfig(model=VAD_MODEL, threshold=VAD_THRESHOLD),
            sample_rate=TARGET_SR,
        )
        self.vad = sherpa_onnx.VadModel.create(cfg)
        self.buf, self.start, self.sil, self.open = [], 0.0, 0, False
        self.hist = []
        self.carry = np.zeros(0, dtype=np.float32)
        self.carry_t0 = 0.0

    def feed(self, samples, t0):
        x = np.concatenate([self.carry, samples]) if len(self.carry) else samples
        base_t = self.carry_t0 if len(self.carry) else t0
        nwin = len(x) // self.WIN
        out = []
        for i in range(nwin):
            win = x[i * self.WIN:(i + 1) * self.WIN]
            t_end = base_t + (i + 1) * self.WIN / TARGET_SR
            self.hist.append((False, win))
            if len(self.hist) > self.PRE_ROLL:
                self.hist.pop(0)
            if self.vad.is_speech(win):
                if not self.open:
                    self.open = True
                    self.start = max(0.0, t_end - len(self.hist) * self.WIN / TARGET_SR)
                    self.buf = list(self.hist)
                    self.sil = 0
                else:
                    self.buf.append((True, win))
            elif self.open:
                self.buf.append((False, win))
                self.sil += 1
                if self.sil >= self.CLOSE_SIL or len(self.buf) * self.WIN >= self.MAX_LEN:
                    out.append(self._close())
        self.carry = x[nwin * self.WIN:]
        self.carry_t0 = base_t + nwin * self.WIN / TARGET_SR
        return out

    def _close(self):
        first_speech = next((i for i, (sp, _) in enumerate(self.buf) if sp), 0)
        trim = max(0, first_speech - 6)  # ~0.2s 词头保护
        self.start += trim * self.WIN / TARGET_SR
        samples = np.concatenate([w for _, w in self.buf[trim:]])
        seg = (self.start, samples)
        self.open, self.buf, self.hist = False, [], []
        return seg

    def open_partial(self):
        """当前打开段的实时快照（不动内部状态），供伪流式部分结果用。"""
        if not self.open or len(self.buf) * self.WIN < int(1.0 * TARGET_SR):
            return None
        first_speech = next((i for i, (sp, _) in enumerate(self.buf) if sp), 0)
        trim = max(0, first_speech - 6)
        samples = np.concatenate([w for _, w in self.buf[trim:]])
        return (self.start + trim * self.WIN / TARGET_SR, samples)

    def flush_tail(self):
        if self.open and self.buf:
            return [self._close()]
        return []


# ------------------------------------------------- 翻译（Argos 离线 MT）----
_stanza_patched = False

def _patch_stanza_offline():
    """argos 的分句器(stanza)默认联网拉模型；改为只用已布置的本地包内模型。"""
    global _stanza_patched
    if _stanza_patched:
        return
    try:
        import stanza
        orig = stanza.Pipeline
        stanza.Pipeline = lambda *a, **k: orig(*a, **{**k, "download_method": None})
        _stanza_patched = True
    except Exception:
        pass


def detect_lang(text: str) -> str:
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return "zh" if cjk >= max(2, len(text) * 0.2) else "en"


def translate_text(text: str) -> str:
    """zh<->en 离线神经翻译（Argos/OpenNMT，非 LLM）。失败降级返回空。"""
    if not text.strip():
        return ""
    src = detect_lang(text)
    tgt = "en" if src == "zh" else "zh"
    try:
        _patch_stanza_offline()
        import argostranslate.translate as at
        return at.translate(text, src, tgt)
    except Exception as e:
        print(f"[翻译失败: {e}]")
        return ""


# ------------------------------------------------- 数学口播模式 ----
def _math_frac(m):
    sign = {"负": "-", "正": "", "-": "-", "−": "-", None: ""}[m.group(2)]
    return f"{m.group(1)}^({sign}{m.group(3)}/{m.group(4)})"

MATH_RULES = [
    (r"([A-Za-z])的(负|正|-|−)?(\d+)分之([A-Za-z0-9]+)次方", _math_frac),
    (r"([A-Za-z0-9])的(\d+)次方", r"\1^\2"),
    (r"平方", "²"), (r"立方", "³"), (r"四次方", "⁴"),
    (r"的(²|³|⁴)", r"\1"),
    (r"e的([\-0-9A-Za-z/^()]+)次方", r"e^(\1)"),
]

def apply_math(text: str) -> str:
    for pat, rep in MATH_RULES:
        text = re.sub(pat, rep, text)
    return text

# ------------------------------------------------------- 引擎管线 ----
def sv_pipeline(args, stop, res_q, level_holder):
    """SenseVoice：VAD 分段 + 离线双语识别（自动语种 + ITN + 标点风格）。"""
    recog = build_offline_sv()
    audio_q = queue.Queue(maxsize=400)
    threading.Thread(target=open_input,
                     args=(args.source, audio_q, stop, args.device, level_holder),
                     kwargs={"source_ref": lambda: args.source},
                     daemon=True).start()
    seg = VadSegmenter()
    played = 0.0

    def decode(x):
        stream = recog.create_stream()
        stream.accept_waveform(TARGET_SR, x)
        recog.decode_stream(stream)
        return stream.result.text.strip()

    last_part_t = 0.0
    quiet = 0.0
    quiet_total = 0.0
    quiet_reported = 0.0
    gate_override = getattr(args, "noise_gate", None)
    gate = noise_gate_for(args.source, gate_override)
    print(f"[噪声门限] 音源 {args.source} -> {gate}（低于此值的块不喂 VAD；--noise-gate 可覆盖）")
    while not stop.is_set():
        gate = noise_gate_for(getattr(args, "source", "loopback"), gate_override)  # I-066 热切换同步
        try:
            samples = audio_q.get(timeout=0.5)
        except queue.Empty:
            continue
        dur = len(samples) / TARGET_SR
        rms = float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0
        if rms < gate:   # 静默块：不喂 VAD；当前段超 0.6s 静默则强闭
            quiet += dur
            quiet_total += dur
            if quiet_total - quiet_reported >= 60:   # O-035: 排障观测——区分"没人说话"和"被门限吞了"
                quiet_reported = quiet_total
                print(f"[噪声门限] 累计吞掉静默 {quiet_total:.0f}s（阈值 {gate}）")
            if seg.open and quiet >= 0.6:
                for s2, x2 in seg.flush_tail():
                    text = decode(x2)
                    if text:
                        res_q.put(("final", text))
                last_part_t = time.time()
            played += dur
            continue
        quiet = 0.0
        for s, x in seg.feed(samples, played):
            text = decode(x)
            if text:
                res_q.put(("final", text))
            last_part_t = time.time()
        played += len(samples) / TARGET_SR
        # 伪流式：语音段打开期间每 1.2s 刷一次部分结果，段闭出终稿
        if seg.open and time.time() - last_part_t >= 1.2:
            pv = seg.open_partial()
            if pv:
                text = decode(pv[1])
                if text:
                    res_q.put(("part", text))
                last_part_t = time.time()
    for s, x in seg.flush_tail():
        text = decode(x)
        if text:
            res_q.put(("final", text))


def zf_pipeline(args, stop, res_q, level_holder):
    """Zipformer：英文流式识别，100ms 粒度低延迟。"""
    recog = build_recognizer(args.model_dir)
    stream = recog.create_stream()
    audio_q = queue.Queue(maxsize=400)
    threading.Thread(target=open_input,
                     args=(args.source, audio_q, stop, args.device, level_holder),
                     kwargs={"source_ref": lambda: args.source},
                     daemon=True).start()
    last_partial = ""
    while not stop.is_set():
        try:
            samples = audio_q.get(timeout=0.5)
        except queue.Empty:
            continue
        stream.accept_waveform(TARGET_SR, samples)
        while recog.is_ready(stream):
            recog.decode_stream(stream)
        cur = recog.get_result(stream)
        if cur and cur != last_partial:
            last_partial = cur
            res_q.put(("part", cur))
        if recog.is_endpoint(stream):
            text = cur.strip()
            if text:
                res_q.put(("final", text))
            last_partial = ""
            recog.reset(stream)
    stream.accept_waveform(TARGET_SR, np.zeros(int(TARGET_SR * 0.6), dtype=np.float32))
    stream.input_finished()
    while recog.is_ready(stream):
        recog.decode_stream(stream)
    tail = recog.get_result(stream).strip()
    if tail:
        res_q.put(("final", tail))


# ------------------------------------------------------------- UI ----
class SubtitleApp:
    """置顶字幕 + 控制窗。窗口随内容自适应收缩，底边锚定，可拖动，可最小化成悬浮球。"""

    def __init__(self, args, web_live=None):
        import tkinter as tk
        import json, os
        self.tk = tk
        self.args = args
        self.web = web_live  # 旁路信息源层；None=未开启，任何异常都不得影响字幕主线
        self.stop = threading.Event()
        self.ui_q = queue.Queue()
        self.level = {}
        self.running = False
        self.minimized = False
        _save = args.save
        if _save and not os.path.isabs(_save):
            _save = os.path.join(BASE_DIR, _save)
        self.save_f = open(_save, "w", encoding="utf-8") if _save else None
        self.cfg = {"font_size": 16, "font_color": "white", "bg": "#101418",
                    "alpha": 0.92, "x": 0, "bottom": None, "toolbar_hidden": False}
        if os.path.exists(CONFIG_PATH):
            try:
                self.cfg.update(json.load(open(CONFIG_PATH, encoding="utf-8")))
            except Exception:
                pass

        self.history = []  # [(HH:MM:SS, kind, text, rel_sec)] 供历史区与导出
        self.t_start = time.time()
        self.hist_txt = None

        import tkinter.messagebox
        tk.messagebox = tkinter.messagebox

        w = tk.Tk()
        self.root = w
        w.title("Whisper 全局转写")
        w.attributes("-topmost", True)
        w.overrideredirect(True)
        self.sw = w.winfo_screenwidth()
        self.sh = w.winfo_screenheight()
        if not self.cfg.get("bottom"):
            self.cfg["bottom"] = self.sh
        if self.cfg.get("bg") == "CLEAR":   # 色键退役，旧配置回退
            self.cfg["bg"] = "#101418"
        # 位置自愈：换显示器/断开外接屏后旧坐标可能开出屏幕外，钳回当前屏
        if not (0 <= self.cfg.get("x", 0) < self.sw - 200):
            self.cfg["x"] = 0
        if not (200 < self.cfg.get("bottom", self.sh) <= self.sh + 60):
            self.cfg["bottom"] = self.sh
        _m = self.cfg["bg"]
        bg = "#010203" if _m == "OVERLAY" else ("#eef0f2" if _m == "SLIM_LIGHT" else (_m or "#101418"))
        w.configure(bg=bg)

        bar = tk.Frame(w, bg=bg)
        self.bar = bar
        bar.pack(fill="x", padx=8, pady=(4, 0))
        # 单一状态按钮：运行中=红色停止，空闲=绿色开始（状态机不裸奔）
        self.btn_run = tk.Button(bar, text="▶ 开始", command=self.on_run_toggle,
                                 bg="#43a047", fg="white", relief="flat", width=8,
                                 disabledforeground="#a5e8b0")
        self.btn_run.pack(side="left")
        tk.Button(bar, text="最小化", command=self.minimize, bg=bg,
                  fg="#cfd8dc", relief="flat").pack(side="right")
        tk.Button(bar, text="退出", command=self.quit_all, bg=bg,
                  fg="#9aa0a6", relief="flat").pack(side="right")
        tk.Button(bar, text="导出", command=self.export_txt, bg=bg,
                  fg="#4fc3f7", relief="flat").pack(side="right", padx=(0, 6))
        tk.Button(bar, text="历史", command=self.toggle_history, bg=bg,
                  fg="#4fc3f7", relief="flat").pack(side="right")
        # 声音来源/引擎收进设置行：主界面只留状态与四个动词（苹果式"宁可不给我"）
        self.src_map = {"系统声音": "loopback", "麦克风": "mic"}
        self.src_var = tk.StringVar(value=args.source)
        rev_src = {v: k for k, v in self.src_map.items()}
        self.eng_map = {"双语高精度": "sensevoice", "英文低延迟": "zipformer"}
        self.eng_var = tk.StringVar(value=args.engine)
        rev_eng = {v: k for k, v in self.eng_map.items()}
        self.tr_var = tk.BooleanVar(value=not getattr(args, "no_translate", False))


        self.final_lb = tk.Label(w, text="", font=("Microsoft YaHei", self.cfg["font_size"]),
                                 fg=self.cfg["font_color"], bg=bg, wraplength=self.sw - 30, justify="left")
        self.final_lb.pack(fill="x", padx=15)
        self.trans_lb = tk.Label(w, text="", font=("Microsoft YaHei", max(12, self.cfg["font_size"] - 2)),
                                 fg="#ffd54a", bg=bg, wraplength=self.sw - 30, justify="left")
        self.trans_lb.pack(fill="x", padx=15)
        self.status = tk.Label(w, text="未运行 — 点 ▶ 开始", font=("Microsoft YaHei", 11),
                               fg="#9aa0a6", bg=bg, anchor="w")
        self.status.pack(fill="x", padx=10, pady=(0, 4))

        sb = tk.Frame(w, bg=bg)
        self.sb = sb
        self._sb_labels = []
        self.sb.pack(fill="x", padx=8, pady=(0, 4), before=self.status)
        self.fi = FONT_SIZES.index(self.cfg["font_size"]) if self.cfg["font_size"] in FONT_SIZES else 1
        self.ci = next((i for i, (_, c) in enumerate(FONT_COLORS) if c == self.cfg["font_color"]), 0)
        self.bi = next((i for i, (_, b) in enumerate(BACKGROUNDS) if b == self.cfg["bg"]), 0)
        _l = tk.Label(sb, text="声音:", fg="#9aa0a6", bg=bg,
                 font=("Microsoft YaHei", 9)); _l.pack(side="left"); self._sb_labels.append(_l)
        self.src_disp = tk.StringVar(value=rev_src.get(args.source, "系统声音"))
        def on_src_change(label):
            self.src_var.set(self.src_map[label])
            self.args.source = self.src_map[label]   # I-066: 运行中立即被采集线程看见
            if self.running:
                self.status.config(text=f"音源已切到「{label}」— 采集流正在重开")
        tk.OptionMenu(sb, self.src_disp, *self.src_map.keys(),
                      command=on_src_change).pack(side="left")
        _l = tk.Label(sb, text="引擎:", fg="#9aa0a6", bg=bg,
                 font=("Microsoft YaHei", 9)); _l.pack(side="left", padx=(6, 0)); self._sb_labels.append(_l)
        self.eng_disp = tk.StringVar(value=rev_eng.get(args.engine, "双语高精度"))
        tk.OptionMenu(sb, self.eng_disp, *self.eng_map.keys(),
                      command=lambda l: self.eng_var.set(self.eng_map[l])).pack(side="left")
        tk.Checkbutton(sb, text="翻译", variable=self.tr_var, fg="#cfd8dc",
                       bg=bg, selectcolor=bg, activebackground=bg,
                       font=("Microsoft YaHei", 9)).pack(side="left", padx=4)
        self._sbd_buttons = []
        for txt, cmd in [("A-", lambda: self.cycle_font(-1)), ("A+", lambda: self.cycle_font(1)),
                         ("字色:" + FONT_COLORS[self.ci][0], self.cycle_color),
                         ("背景:" + BACKGROUNDS[self.bi][0], self.cycle_bg)]:
            b = tk.Button(sb, text=txt, command=cmd, bg="#1b2129", fg="#cfd8dc",
                          relief="flat", font=("Microsoft YaHei", 9))
            b.pack(side="left", padx=2)
            self._sbd_buttons.append(b)
        _l = tk.Label(sb, text="宽度", fg="#9aa0a6", bg=bg,
                 font=("Microsoft YaHei", 9)); _l.pack(side="left", padx=(8, 0)); self._sb_labels.append(_l)
        sc_w = tk.Scale(sb, from_=40, to=100, orient="horizontal", showvalue=0, length=80,
                        command=self.set_width)
        sc_w.set(self.cfg.get("width_pct", 100))
        sc_w.pack(side="left")
        tk.Button(sb, text="半宽居中", command=self.preset_half, bg="#1b2129", fg="#cfd8dc",
                  relief="flat", font=("Microsoft YaHei", 9)).pack(side="left", padx=2)
        _l = tk.Label(sb, text="透明", fg="#9aa0a6", bg=bg,
                 font=("Microsoft YaHei", 9)); _l.pack(side="left", padx=(8, 0)); self._sb_labels.append(_l)
        sc_a = tk.Scale(sb, from_=40, to=100, orient="horizontal", showvalue=0, length=80,
                        command=self.set_alpha)
        sc_a.set(int(self.cfg.get("alpha", 0.92) * 100))
        sc_a.pack(side="left")
        self._btn_slim = tk.Button(sb, text="极简:开" if self.cfg.get("auto_slim", True) else "极简:关",
                                   command=self.toggle_slim, bg="#1b2129",
                                   fg="#4fc3f7" if self.cfg.get("auto_slim", True) else "#cfd8dc",
                                   relief="flat", font=("Microsoft YaHei", 9))
        self._btn_slim.pack(side="left", padx=2)
        self._slim = False
        self.breath = self.tk.Frame(self.root, height=2, bg="#4fc3f7")
        self.breath.bind("<Button-1>",
                         lambda e: self.cfg.get("toolbar_hidden") and self.toggle_toolbar())
        self._btn_math = tk.Button(sb, text="数:关", command=self.toggle_math, bg="#1b2129",
                                   fg="#cfd8dc", relief="flat", font=("Microsoft YaHei", 9))
        self._btn_math.pack(side="left", padx=2)
        self._btn_collapse = tk.Button(sb, text="收起工具栏", command=self.toggle_toolbar,
                                       bg="#1b2129", fg="#cfd8dc",
                                       relief="flat", font=("Microsoft YaHei", 9))
        self._btn_collapse.pack(side="left", padx=2)

        bar.bind("<Button-1>", self._drag_start)
        bar.bind("<B1-Motion>", self._drag_move)
        self.status.bind("<Button-1>", self._drag_start)    # 状态行是拖动把手
        self.status.bind("<B1-Motion>", self._drag_move)
        for _w in (self.final_lb, self.trans_lb, self.breath):   # 字幕/译文/呼吸条均可拖
            _w.bind("<Button-1>", self._drag_start)
            _w.bind("<B1-Motion>", self._drag_move)
        w.bind("<Button-3>", lambda e: self.cfg.get("toolbar_hidden") and self.toggle_toolbar())
        self._dx = self._dy = 0

        self.apply_look()
        self.reflow()
        w.bind("<Configure>", self._sync_plate, add="+")
        w.after(100, self.poll)
        w.after(1200, self._poll_slim)
        self.on_start()
        self._make_tray()

    # ---- 布局：内容自适应 + 底边锚定 ----
    def reflow(self, width=None):
        self.root.update_idletasks()
        w = width or int(self.sw * self.cfg.get("width_pct", 100) / 100)
        h = self.root.winfo_reqheight()
        x = self.cfg.get("x", 0)
        y = self.cfg.get("bottom", self.sh) - h
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        wrap = max(200, w - 30)  # 文字换行宽度跟随窗口，半宽也不截断
        self.final_lb.config(wraplength=wrap)
        self.trans_lb.config(wraplength=wrap)

    def _pointer_in_root(self, e):
        """指针在窗口坐标系中的位置（与绑定在哪个控件上无关）。"""
        return (e.widget.winfo_rootx() - self.root.winfo_rootx() + e.x,
                e.widget.winfo_rooty() - self.root.winfo_rooty() + e.y)

    def _drag_start(self, e):
        self._dx, self._dy = self._pointer_in_root(e)

    def _drag_move(self, e):
        px, py = self._pointer_in_root(e)
        x = self.root.winfo_x() + px - self._dx
        y = self.root.winfo_y() + py - self._dy
        self.root.geometry(f"+{x}+{y}")
        self.cfg["x"] = x
        self.cfg["bottom"] = y + self.root.winfo_height()
        self.save_cfg()

    # ---- 字幕外观 ----
    def save_cfg(self):
        import json
        try:
            json.dump(self.cfg, open(CONFIG_PATH, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass

    def apply_look(self):
        """背景四态：普通色 / 半透明(整窗 alpha) / SLIM_LIGHT(浅底板) / OVERLAY(色键+抖动黑板)。"""
        overlay = self.cfg["bg"] == "OVERLAY"
        slim_light = self.cfg["bg"] == "SLIM_LIGHT"
        bg = "#010203" if overlay else ("#eef0f2" if slim_light else (self.cfg["bg"] or "#101418"))
        # 浮层模式：只有字幕区抠透明(可穿透)，控制区必须不透明——否则整窗点击穿透无法交互
        chrome_bg = "#101418" if overlay else bg
        for wdg in (self.final_lb, self.trans_lb):
            wdg.config(bg=bg)
        for wdg in (self.status, self.sb, self.bar):
            wdg.config(bg=chrome_bg)
        self.root.configure(bg=bg)
        text_fg = "#1a1a1a" if slim_light else self.cfg["font_color"]
        trans_fg = "#5a3d00" if slim_light else "#ffd54a"
        self.final_lb.config(font=("Microsoft YaHei", self.cfg["font_size"]),
                             fg=text_fg)
        self.trans_lb.config(font=("Microsoft YaHei", max(12, self.cfg["font_size"] - 2)),
                             fg=trans_fg)
        self.status.config(fg="#1a1a1a" if slim_light else "#9aa0a6")
        if hasattr(self, "hist_txt") and self.hist_txt is not None:
            self.hist_txt.config(bg=bg)
        if hasattr(self, "_sb_labels"):
            for _l in self._sb_labels:
                _l.config(fg="#1a1a1a" if slim_light else "#9aa0a6")
        if overlay:
            self._ensure_canvas()
            self._ensure_plate()
            for wdg in (self.final_lb, self.trans_lb, self.status):
                if wdg.winfo_manager():
                    wdg.pack_forget()
            self.canvas.pack(fill="both", expand=True)
        elif getattr(self, "canvas", None) is not None and self.canvas.winfo_manager():
            self.canvas.pack_forget()   # 退回标签模式：画布文字同步回标签
            self.final_lb.config(text=self.canvas.itemcget(self.c_final, "text"))
            self.trans_lb.config(text=self.canvas.itemcget(self.c_trans, "text"))
            self._destroy_plate()
            self._pack_display()
        try:
            self.root.attributes("-alpha", 1.0 if (overlay or slim_light)
                                 else (0.55 if self.cfg["bg"] is None else self.cfg["alpha"]))
            self.root.attributes("-transparentcolor",
                                 "#010203" if overlay else "#000001")
        except Exception:
            pass
        self.reflow()
        self.save_cfg()

    def _pack_display(self):
        """规范打包顺序（bar/字幕/译文/设置/状态）——所有模式切换的唯一出口。"""
        self.bar.pack(fill="x", padx=8, pady=(4, 0))
        self.final_lb.pack(fill="x", padx=15)
        self.trans_lb.pack(fill="x", padx=15)
        if not self.cfg.get("toolbar_hidden"):
            self.sb.pack(fill="x", padx=8, pady=(0, 4))
        self.status.pack(fill="x", padx=10, pady=(0, 4))

    def _ensure_plate(self):
        """双窗底板：独立窗整窗 alpha（真半透明）+ 点击穿透，文字窗全实叠于其上。"""
        if getattr(self, "plate_win", None) is not None:
            return
        self.plate_win = self.tk.Toplevel(self.root)
        self.plate_win.overrideredirect(True)
        self.plate_win.configure(bg="#101418")
        self.plate_win.attributes("-topmost", True)
        self.plate_win.attributes("-alpha",
                                  min(0.7, max(0.15, self.cfg.get("alpha", 0.92) * 0.6)))
        try:
            import ctypes
            hwnd = self.plate_win.winfo_id()
            hwnd = ctypes.windll.user32.GetAncestor(hwnd, 2)  # GA_ROOT
            GWL_EXSTYLE = -20
            ex = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex | 0x20 | 0x80000)
        except Exception:
            pass
        self.plate_win.lower(self.root)

    def _sync_plate(self, event=None):
        if self.cfg["bg"] != "OVERLAY" or getattr(self, "plate_win", None) is None:
            return
        try:
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            w, h = self.root.winfo_width(), self.root.winfo_height()
            self.plate_win.geometry(f"{w}x{h}+{x}+{y}")
            self.root.lift()
            self.plate_win.lower(self.root)
        except Exception:
            pass

    def _destroy_plate(self):
        pw = getattr(self, "plate_win", None)
        if pw is not None:
            try:
                pw.destroy()
            except Exception:
                pass
            self.plate_win = None

    def _ensure_canvas(self):
        """OVERLAY 显示层：色键全透明背景 + 描边文字（8 方向黑影垫底，任意背景可读）。"""
        if getattr(self, "canvas", None) is not None:
            return
        self.canvas = self.tk.Canvas(self.root, bg="#010203", highlightthickness=0)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<Button-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        f1 = ("Microsoft YaHei", self.cfg["font_size"])
        f2 = ("Microsoft YaHei", max(12, self.cfg["font_size"] - 2))
        self.c_final = self.canvas.create_text(12, 8, anchor="nw",
                                               fill=self.cfg["font_color"], font=f1,
                                               width=self.sw - 24, text="")
        self.c_trans = self.canvas.create_text(12, 40, anchor="nw", fill="#ffd54a", font=f2,
                                               width=self.sw - 24, text="", state="hidden")

    def _on_canvas_resize(self, e):
        self.canvas.itemconfig(self.c_final, width=e.width - 24)
        self.canvas.itemconfig(self.c_trans, width=e.width - 24)
        self._stack_overlay_text()

    def _stack_overlay_text(self):
        """译文紧贴原文下方；描边影子跟随各自主字。"""
        try:
            b = self.canvas.bbox(self.c_final)
            if b:
                self.canvas.coords(self.c_trans, 12, b[3] + 4)
        except Exception:
            pass

    def cycle_font(self, d):
        self.fi = (self.fi + d) % len(FONT_SIZES)
        self.cfg["font_size"] = FONT_SIZES[self.fi]
        self.apply_look()

    def cycle_color(self):
        self.ci = (self.ci + 1) % len(FONT_COLORS)
        name, color = FONT_COLORS[self.ci]
        self.cfg["font_color"] = color
        self._sbd_buttons[2].config(text="字色:" + name)
        self.apply_look()

    def cycle_bg(self):
        self.bi = (self.bi + 1) % len(BACKGROUNDS)
        name, bg = BACKGROUNDS[self.bi]
        self.cfg["bg"] = bg
        self._sbd_buttons[3].config(text="背景:" + name)
        self.apply_look()

    def toggle_toolbar(self):
        hidden = not self.cfg.get("toolbar_hidden", False)
        self.cfg["toolbar_hidden"] = hidden
        if hidden:
            self.sb.pack_forget()
            self._btn_collapse.config(text="展开工具栏")
        else:
            if self.status.winfo_manager():
                self.sb.pack(fill="x", padx=8, pady=(0, 4), before=self.status)
            else:
                self.sb.pack(fill="x", padx=8, pady=(0, 4))
            self._btn_collapse.config(text="收起工具栏")
        self.reflow()
        self.save_cfg()

    def toggle_slim(self):
        on = not self.cfg.get("auto_slim", True)
        self.cfg["auto_slim"] = on
        self._btn_slim.config(text="极简:开" if on else "极简:关",
                              fg="#4fc3f7" if on else "#cfd8dc")
        if on:   # 极简 = 浅色底板(浅到几乎看不见) + 深色字 + 隐去 chrome
            self._prev_bg = self.cfg["bg"]
            self.cfg["bg"] = "SLIM_LIGHT"
        else:
            if self.cfg["bg"] == "SLIM_LIGHT":
                self.cfg["bg"] = getattr(self, "_prev_bg", None) or "#101418"
        if not on and self._slim:
            self._set_slim(False)
        self.apply_look()
        self.save_cfg()

    def _set_slim(self, slim):
        """瘦身：鼠标不在窗上时只留字幕行，悬停恢复控制条。"""
        if slim == self._slim:
            return
        self._slim = slim
        if slim:  # 只藏控制条与设置行，保留状态行；顶部留 2px 呼吸条招手
            for wdg in (self.bar, self.sb):
                if wdg.winfo_manager():
                    wdg.pack_forget()
            if self.final_lb.winfo_manager():   # 标签模式：插到字幕上方
                self.breath.pack(fill="x", before=self.final_lb)
            else:                                # 浮层模式：画布在，呼吸条排最前
                self.breath.pack(fill="x")
        else:
            self.breath.pack_forget()
            self._pack_display()
        self.reflow()

    def _mirror_overlay(self):
        """OVERLAY 模式：标签文字镜像到画布（保持标签为唯一事实源）。"""
        if self.cfg["bg"] != "OVERLAY" or getattr(self, "canvas", None) is None:
            return
        self.canvas.itemconfig(self.c_final, text=self.final_lb.cget("text"),
                               fill=self.cfg["font_color"])
        t = self.trans_lb.cget("text")
        self.canvas.itemconfig(self.c_trans, text=t, state="normal" if t else "hidden")
        self._stack_overlay_text()

    def _poll_slim(self):
        try:
            if self.cfg.get("auto_slim", True) and self.running and not self.minimized:
                x, y = self.root.winfo_pointerx(), self.root.winfo_pointery()
                wx, wy = self.root.winfo_rootx(), self.root.winfo_rooty()
                ww, wh = self.root.winfo_width(), self.root.winfo_height()
                inside = wx <= x < wx + ww and wy <= y < wy + wh
                self._set_slim(not inside)
        except Exception as e:
            print(f"[slim] {e}")   # 任何异常不断轮询链
        self.root.after(600, self._poll_slim)

    def toggle_math(self):
        on = not self.cfg.get("math", False)
        self.cfg["math"] = on
        self._btn_math.config(text="数:开" if on else "数:关",
                              fg="#4fc3f7" if on else "#cfd8dc")
        self.save_cfg()

    def set_width(self, v):
        self.cfg["width_pct"] = int(v)
        self.reflow()
        self.save_cfg()

    def set_alpha(self, v):
        self.cfg["alpha"] = int(v) / 100
        if self.cfg["bg"] == "OVERLAY" and getattr(self, "plate_win", None) is not None:
            self.plate_win.attributes("-alpha",
                                      min(0.7, max(0.15, self.cfg["alpha"] * 0.6)))
        elif self.cfg["bg"] is None:
            self.root.attributes("-alpha", max(0.15, self.cfg["alpha"] - 0.35))
        self.save_cfg()

    def preset_half(self):
        self.cfg["width_pct"] = 50
        self.reflow()
        w = self.root.winfo_width()
        self.root.geometry(f"+{(self.sw - w) // 2}+{self.root.winfo_y()}")
        self.cfg["x"] = (self.sw - w) // 2
        self.save_cfg()

    # ---- 最小化为悬浮球（不退出、转写继续）----
    def minimize(self):
        self.minimized = True
        for wdg in (self.bar, self.final_lb, self.trans_lb, self.status, self.sb):
            wdg.pack_forget()
        self.pill = self.tk.Label(self.root,
                                  text="● 转写中 — 点击恢复" if self.running else "◉ 待机 — 点击恢复",
                                  font=("Microsoft YaHei", 11), fg="white", bg="#1b2129",
                                  padx=16, pady=8)
        self.pill.pack()
        self.pill.bind("<Button-1>", lambda e: self.restore())
        self.reflow(width=260)

    def restore(self):
        self.minimized = False
        self.pill.destroy()
        self.bar.pack(fill="x", padx=8, pady=(4, 0))
        self.final_lb.pack(fill="x", padx=15)
        self.trans_lb.pack(fill="x", padx=15)
        if not self.cfg.get("toolbar_hidden"):
            self.sb.pack(fill="x", padx=8, pady=(0, 4))
        self.status.pack(fill="x", padx=10, pady=(0, 4))
        self.reflow()

    # ---- 运行控制 ----
    # ---- 历史区 / 导出 ----
    def toggle_history(self):
        if self.hist_txt is not None and self.hist_txt.winfo_manager():
            self.hist_frame.pack_forget()
            self.reflow()
            return
        bgc = self.cfg["bg"] or "#101418"
        frame = self.tk.Frame(self.root, bg=bgc)
        self.hist_frame = frame
        self.hist_txt = self.tk.Text(frame, height=7, wrap="word",
                                     font=("Microsoft YaHei", 11),
                                     fg="#cfd8dc", bg=bgc, relief="flat",
                                     state="disabled", padx=8, pady=4)
        sb = self.tk.Scrollbar(frame, command=self.hist_txt.yview)
        self.hist_txt.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.hist_txt.pack(fill="both", expand=True)
        self.hist_txt.tag_config("ts", foreground="#7f8c8d")
        self.hist_txt.tag_config("tr", foreground="#ffd54a")
        frame.pack(fill="both", padx=8, pady=(2, 0), before=self.final_lb)
        if not self.history:
            t.config(state="normal")
            t.insert("end", "（暂无记录——有人说话后，这里会出现带时间戳的字幕和译文）", "ts")
            t.config(state="disabled")
        for ts, kind, text in self.history:  # 回填
            self._hist_append(ts, kind, text)
        self.reflow()

    def _hist_append(self, ts, kind, text):
        if self.hist_txt is None:
            return
        t = self.hist_txt
        t.config(state="normal")
        t.insert("end", f"[{ts}] ", "ts")
        if kind == "trans":
            t.insert("end", "译 " + text + "\n", "tr")
        else:
            t.insert("end", text + "\n")
        t.config(state="disabled")
        t.see("end")

    def _publish(self, kind, text, ts=None, rel=None):
        """旁路 fan-out：吞掉一切异常，web live 永不影响字幕主线（MVP 冻结基线）。"""
        if not self.web:
            return
        try:
            self.web.publish(kind, text, ts=ts, rel=rel)
        except Exception as e:
            print("[web live] 旁路推送失败，已忽略:", e)

    def export_txt(self):
        import datetime
        if not self.history:
            self.status.config(text="没有可导出的内容")
            return
        name = datetime.datetime.now().strftime("transcript_%Y%m%d_%H%M%S.txt")
        path = os.path.join(BASE_DIR, name)
        with open(path, "w", encoding="utf-8") as f:
            for item in self.history:
                ts, kind, text = item[0], item[1], item[2]
                rel = f"+{item[3]}s" if len(item) > 3 else ""
                f.write(f"[{ts} {rel}] {text}\n" if kind == "final" else f"[{ts} {rel}] 译 {text}\n")
        self.status.config(text="已导出 -> " + name)
        print("已导出:", path)
        try:  # 资源管理器定位到文件
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        except Exception:
            pass
        self.tk.messagebox.showinfo("导出成功",
            f"已保存到：\n{path}\n\n（含时间戳与译文，可直接拖进播放器对照）")

    def on_start(self):
        if self.running:
            return
        self.stop.clear()
        self.args.source = self.src_var.get()
        self.args.engine = self.eng_var.get()
        engine_q = queue.Queue()
        self.ui_q = queue.Queue()
        self.level = {}
        target = sv_pipeline if self.args.engine == "sensevoice" else zf_pipeline
        threading.Thread(target=target,
                         args=(self.args, self.stop, engine_q, self.level),
                         daemon=True).start()
        consumer = self.trans_worker if self.tr_var.get() else self.passthrough_worker
        threading.Thread(target=consumer, args=(engine_q,), daemon=True).start()
        self.running = True
        self.btn_run.config(text="■ 停止", bg="#e53935", state="normal")
        if not getattr(self, "_tr_warmed", False):  # 翻译冷启动 15s，开跑即后台预热
            self._tr_warmed = True
            threading.Thread(target=translate_text, args=("预热。",), daemon=True).start()
            threading.Thread(target=translate_text, args=("warm up.",), daemon=True).start()
        if self.minimized:
            self.pill.config(text="● 转写中 — 点击恢复")

    def on_run_toggle(self):
        if self.running:
            self.on_stop()
        else:
            self.on_start()

    def on_stop(self):
        self.stop.set()
        self.running = False
        self.btn_run.config(state="disabled", text="■ 停止中…", bg="#43a047")
        self.status.config(text="已停止 — 点 ▶ 开始")  # 状态行与按钮必须同账
        if self.minimized:
            self.pill.config(text="◉ 待机 — 点击恢复")
        self.root.after(1500, lambda: self.btn_run.config(
            state="normal", text="▶ 开始"))

    def passthrough_worker(self, in_q):
        while not (self.stop.is_set() and in_q.empty()):
            try:
                self.ui_q.put(in_q.get(timeout=0.5))
            except queue.Empty:
                continue

    def trans_worker(self, in_q):
        while not (self.stop.is_set() and in_q.empty()):
            try:
                kind, text = in_q.get(timeout=0.5)
            except queue.Empty:
                continue
            self.ui_q.put((kind, text))
            if kind == "final":
                self.ui_q.put(("trans", translate_text(text)))

    def poll(self):
        try:
            while True:
                kind, text = self.ui_q.get_nowait()
                if kind in ("final", "part", "trans"):
                    pass  # 先占位，下面统一处理
                if kind == "final":
                    ts = time.strftime("%H:%M:%S")
                    if self.cfg.get("math"):
                        text = apply_math(text)
                    rel = int(time.time() - self.t_start)
                    self.history.append((ts, "final", text, rel))
                    self._hist_append(ts, "final", text)
                    self._publish("final", text, ts=ts, rel=rel)
                    self.final_lb.config(text=text, fg=self.cfg["font_color"])
                    print("[段] " + text)
                    if self.save_f:
                        self.save_f.write(text + "\n")
                        self.save_f.flush()
                elif kind == "part":
                    self._publish("part", text)
                    self.final_lb.config(text=text, fg="#9aa0a6")
                    if self.trans_lb.cget("text"):  # 新段开始，上一段的译文撤下
                        self.trans_lb.config(text="")
                elif kind == "trans":
                    ts = time.strftime("%H:%M:%S")
                    if self.cfg.get("math"):
                        text = apply_math(text)
                    rel = int(time.time() - self.t_start)
                    self.history.append((ts, "trans", text, rel))
                    self._hist_append(ts, "trans", text)
                    self._publish("trans", text, ts=ts, rel=rel)
                    self.trans_lb.config(text=text)
                # 文字行数变化 → 窗口高度必须跟随，否则溢出/叠压
                if kind in ("final", "part", "trans") and not self.minimized:
                    self.reflow()
                    self._mirror_overlay()
        except queue.Empty:
            pass
        if self.running:
            rms = self.level.get("rms", 0.0)
            bars = min(20, int(rms * 400))
            hint = "  ｜ 设置已收起：右键展开" if self.cfg.get("toolbar_hidden") else ""
            bars = min(10, bars)
            src = getattr(self.args, "source", "loopback")
            src_tag = "｜麦克风" if src == "mic" else "｜系统声音"
            if bars > 0:
                self.status.config(text="● 聆听中  " + "▰" * bars + "▱" * (10 - bars)
                                   + src_tag + hint)
            else:
                idle = time.time() - self.level.get("t", time.time())
                if idle > 15:
                    tip = ("⚠ 15s 无声音：麦克风电平低，可用 --noise-gate 调低门限"
                           if src == "mic" else
                           "⚠ 15s 无声音：检查播放设备是否为默认输出，或用 --device 指定")
                    self.status.config(text=tip + src_tag + hint)
        self.root.after(100, self.poll)

    # ---- 托盘：桌面级自由开关 UI ----
    def _make_tray(self):
        try:
            import pystray
            from PIL import Image, ImageDraw
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle((4, 4, 60, 60), radius=14, fill=(16, 20, 24, 255))
            d.ellipse((20, 20, 44, 44), fill=(255, 213, 74, 255))
            self.tray = pystray.Icon(
                "transcriber", img, "双语转写字幕",
                menu=pystray.Menu(
                    pystray.MenuItem("显示 / 隐藏字幕窗", self._tray_toggle, default=True),
                    pystray.MenuItem("退出", self._tray_quit),
                ))
            self.tray.default_action = self._tray_toggle  # 单击图标 = 开关
            threading.Thread(target=self.tray.run, daemon=True).start()
        except Exception as e:
            print("托盘不可用(可忽略):", e)
            self.tray = None

    def _tray_toggle(self, icon=None, item=None):
        self.root.after(0, self._toggle_visible)

    def _tray_quit(self, icon=None, item=None):
        self.root.after(0, self.quit_all)

    def _toggle_visible(self):
        if self.root.winfo_viewable():
            self.root.withdraw()   # 隐藏窗体，转写继续
        else:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self.root.lift()

    def quit_all(self):
        self.stop.set()
        if self.web:
            try:
                self.web.stop()
            except Exception:
                pass
        if self.save_f:
            self.save_f.close()
        if getattr(self, "tray", None):
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()


# ------------------------------------------------------------- srt ----
def fmt_ts(sec: float) -> str:
    ms = int(sec * 1000)
    return f"{ms//3600000:02d}:{ms%3600000//60000:02d}:{ms%60000//1000:02d},{ms%1000:03d}"


def load_audio_16k(path):
    import soundfile as sf
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    x = data[:, 0]
    if sr != TARGET_SR:
        ratio = round(sr / TARGET_SR)
        x = x[: len(x) // ratio * ratio].reshape(-1, ratio).mean(axis=1)
        sr = TARGET_SR
    return x, sr


def cmd_srt(args):
    x, sr = load_audio_16k(args.input)
    print(f"处理 {args.input}: {len(x)/sr:.1f}s")
    items = []
    if args.engine == "sensevoice":
        recog = build_offline_sv()
        seg = VadSegmenter()
        segs = []
        for i in range(0, len(x), TARGET_SR):
            segs += seg.feed(x[i:i + TARGET_SR], i / sr)
        segs += seg.flush_tail()
        if not segs:
            print("未检测到语音")
            return
        streams = [recog.create_stream() for _ in segs]
        for st, (_, samples) in zip(streams, segs):
            st.accept_waveform(TARGET_SR, samples)
        recog.decode_streams(streams)
        items = [(a, len(samp) / TARGET_SR, st.result.text.strip())
                 for (a, samp), st in zip(segs, streams)]
    else:
        recog = build_recognizer(args.model_dir)
        stream = recog.create_stream()
        last_end = 0.0
        step = TARGET_SR // 2
        for i in range(0, len(x), step):
            t0 = i / sr
            stream.accept_waveform(sr, x[i:i + step])
            while recog.is_ready(stream):
                recog.decode_stream(stream)
            if recog.is_endpoint(stream):
                text = recog.get_result(stream).strip()
                if text:
                    items.append((last_end, t0, text))
                    last_end = t0
                recog.reset(stream)
        stream.accept_waveform(sr, np.zeros(int(sr * 0.6), dtype=np.float32))
        stream.input_finished()
        while recog.is_ready(stream):
            recog.decode_stream(stream)
        tail = recog.get_result(stream).strip()
        if tail:
            items.append((last_end, len(x) / sr, tail))
    n = 0
    with open(args.output, "w", encoding="utf-8") as f:
        for a, dur, text in items:
            if not text:
                continue
            n += 1
            if args.translate:
                tr = translate_text(text)
                text = text + ("\n" + tr if tr else "")
            f.write(f"{n}\n{fmt_ts(a)} --> {fmt_ts(a + dur)}\n{text}\n\n")
    print(f"写出 {n} 条字幕 -> {args.output}")


# ------------------------------------------------------------- main ----
_guard_mutex = None

def acquire_single_instance() -> bool:
    """命名互斥量单实例锁：进程死亡 OS 自动释放，永不残留（端口锁会被临时连接抢占，已退役）。"""
    global _guard_mutex
    try:
        import ctypes
        ctypes.windll.kernel32.CreateMutexW(None, False, "WhisperTranscriber_SingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
            return False
        _guard_mutex = int(ctypes.windll.kernel32.CreateMutexW(None, False,
                          "WhisperTranscriber_SingleInstance"))  # 持句柄防 GC
        return True
    except Exception as e:
        print(f"单实例守卫不可用({e})，跳过检查")
        return True

def cmd_live(args):
    headless = getattr(args, "headless", False)
    if not acquire_single_instance():
        print("已有实例在运行，退出。")
        if headless:   # 无桌面窗模式不弹 tkinter 对话框
            return
        try:
            import tkinter as tk2
            from tkinter import messagebox
            r = tk2.Tk(); r.withdraw()
            messagebox.showwarning("双语字幕", "已经在运行了\n（屏幕底部字幕条 / 托盘黄点图标）\n如需重启请先从托盘右键退出。")
            r.destroy()
        except Exception:
            pass
        return
    if headless:
        import live_core
        live_core.run_headless(args)
        return
    srv = None
    if getattr(args, "web_live", False):
        try:
            import web_live
            srv = web_live.start(open_browser=not getattr(args, "web_live_no_open", False))
            print("web live 已开启（旁路）:", srv.url)
            print(srv.summary())
            print(srv.meeting_line())
            print("历史会议: http://127.0.0.1:%d/history?token=%s" % (srv.port, srv.token))
            if getattr(args, "web_live_no_open", False):
                print("请完整复制上面的 URL 到浏览器，不要照着屏幕手敲 token。")
            else:
                print("已在默认浏览器打开；若没弹出，双击 %s" % web_live.SHORTCUT_PATH)
            print("扩展也用上面这条 URL 配置。")
        except Exception as e:
            print("web live 启动失败，字幕照常运行:", e)
            srv = None
    app = SubtitleApp(args, web_live=srv)
    try:
        app.root.mainloop()
    finally:
        if srv:
            try:
                srv.stop()
            except Exception:
                pass


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="PC 全局转写 + 实时字幕 + 离线翻译（纯本地）")
    p.add_argument("--model-dir", default=MODEL_DIR)
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("live", help="实时转写+字幕+翻译")
    pl.add_argument("--source", choices=["mic", "loopback"], default="loopback")
    pl.add_argument("--noise-gate", type=float, default=None,
                    help="覆盖 RMS 噪声门限（麦克风默认 0.0008；系统声音默认 0.006）")
    pl.add_argument("--engine", choices=["sensevoice", "zipformer"], default="sensevoice",
                    help="sensevoice=中英双语+标点(推荐); zipformer=英文低延迟流式")
    pl.add_argument("--device", default=None, help="loopback 指定输出设备名子串")
    pl.add_argument("--save", default=None, help="文字稿保存路径")
    pl.add_argument("--no-translate", action="store_true", help="关闭翻译（UI 里也可切）")
    pl.add_argument("--web-live", action="store_true",
                    help="开启本地 web live 页面（旁路，默认关；只绑 127.0.0.1）")
    pl.add_argument("--web-live-no-open", action="store_true",
                    help="开启 web live 但不自动打开浏览器（URL 需自行复制）")
    pl.add_argument("--headless", action="store_true",
                    help="无桌面窗：扩展 / live 页控制为主，强制开启 web live 与控制 API，tkinter 前端不加载")
    pl.add_argument("--overlay", action="store_true",
                    help="仅 --headless 生效：额外开一个轻量悬浮字幕浮层（默认不开任何桌面窗）")
    pl.add_argument("--no-archive", action="store_true",
                    help="仅 --headless 生效：不写 meetings/ 会议存档")
    pl.add_argument("--list-devices", action="store_true", help="列出输出设备后退出")
    ps = sub.add_parser("srt", help="音频文件 -> SRT 字幕")
    ps.add_argument("input")
    ps.add_argument("-o", "--output", default=None)
    ps.add_argument("--engine", choices=["sensevoice", "zipformer"], default="sensevoice")
    ps.add_argument("--translate", action="store_true", help="双语字幕（Argos 本地翻译）")
    args = p.parse_args()
    if getattr(args, "list_devices", False):
        print("默认输出:", sc.default_speaker().name)
        for i, sp in enumerate(sc.all_speakers()):
            print(f"  [{i}] {sp.name}")
        sys.exit(0)
    if args.cmd == "srt" and not args.output:
        args.output = args.input.rsplit(".", 1)[0] + ".srt"
    {"live": cmd_live, "srt": cmd_srt}[args.cmd](args)
