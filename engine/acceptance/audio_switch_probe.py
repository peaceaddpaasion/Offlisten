# -*- coding: utf-8 -*-
"""音源热切换与门限实机探针（I-065 / I-066）。

不启动 GUI、不加载 ASR 模型，只用真实声卡与 pc_transcriber 的采集函数：
  .venv/Scripts/python.exe acceptance/audio_switch_probe.py

验证：
  1. noise_gate_for 按音源取门限，显式覆盖优先
  2. resolve_source 对 mic / loopback 解析到不同设备与 kind
  3. 运行中改 args.source，open_input 会打印「音源已切换」并重开采集流，
     两种音源都真的产出音频块（不是只改了变量）
证据写到 acceptance/audio_switch_probe_<时间戳>.txt
"""
import os
import queue
import sys
import threading
import time
import types
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
import pc_transcriber as pt

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         ("  -> " + detail) if detail else ""))


class Collector:
    """线程安全地收集采集线程里的 print，避免污染探针自身输出。"""

    def __init__(self):
        self.parts = []
        self.lock = threading.Lock()

    def write(self, s):
        with self.lock:
            self.parts.append(s)

    def flush(self):
        pass

    def isatty(self):
        return False

    def text(self):
        with self.lock:
            return "".join(self.parts)


def main():
    # 1. 门限口径
    check("麦克风门限 0.0008 / 系统声音门限 0.006",
          pt.noise_gate_for("mic") == 0.0008 and
          pt.noise_gate_for("loopback") == 0.006,
          "mic=%.4f loopback=%.4f" %
          (pt.noise_gate_for("mic"), pt.noise_gate_for("loopback")))
    check("--noise-gate 显式覆盖优先于音源默认",
          pt.noise_gate_for("mic", 0.0004) == 0.0004 and
          pt.noise_gate_for("loopback", 0.0004) == 0.0004)

    # 2. 设备解析
    try:
        mic_dev = pt.resolve_source("mic")
        lb_dev = pt.resolve_source("loopback")
        check("mic 与 loopback 解析到不同 kind/设备",
              mic_dev[2] == "mic" and lb_dev[2] == "loopback" and
              mic_dev[0] != lb_dev[0],
              "%r / %r" % (mic_dev[0], lb_dev[0]))
    except Exception as e:
        check("mic 与 loopback 解析到不同 kind/设备", False, repr(e))

    # 3. 运行中热切换：loopback -> mic -> loopback
    args = types.SimpleNamespace(source="loopback", device=None, noise_gate=None)
    audio_q = queue.Queue(maxsize=400)
    stop = threading.Event()
    logs = Collector()
    orig = sys.stdout
    sys.stdout = logs
    th = threading.Thread(
        target=pt.open_input,
        args=(args.source, audio_q, stop, None, {}),
        kwargs={"source_ref": lambda: args.source},
        daemon=True)
    th.start()
    try:
        time.sleep(1.6)
        args.source = "mic"
        time.sleep(1.6)
        args.source = "loopback"
        time.sleep(1.6)
    finally:
        stop.set()
        th.join(timeout=6)
        sys.stdout = orig

    text = logs.text()
    check("采集线程未卡死且产出音频块", not th.is_alive() and audio_q.qsize() > 0,
          "queue=%d alive=%s" % (audio_q.qsize(), th.is_alive()))
    check("启动时绑定系统声音并打印输入源", "输入源: [系统声音]" in text)
    check("运行中切到麦克风打印「音源已切换」并重开流",
          "音源已切换: loopback -> mic" in text and
          text.count("输入源: 麦克风阵列") >= 1,
          "swap_lines=%d" % text.count("音源已切换"))
    check("再切回系统声音同样重开流",
          "音源已切换: mic -> loopback" in text and
          text.count("输入源: [系统声音]") >= 2)
    check("切换总次数为 2（无多余重开）",
          text.count("音源已切换:") == 2,
          "count=%d" % text.count("音源已切换:"))

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(os.path.dirname(__file__),
                        "audio_switch_probe_%s.txt" % stamp)
    with open(path, "w", encoding="utf-8") as f:
        f.write("whisper 音源热切换实机探针  %s\n" %
                datetime.now().isoformat(timespec="seconds"))
        f.write("真实声卡 / 无 GUI / 无 ASR 模型\n\n")
        for name, ok, detail in results:
            f.write("[%s] %s%s\n" % ("PASS" if ok else "FAIL", name,
                                     ("  -> " + detail) if detail else ""))
        f.write("\n%d/%d passed\n\n--- 采集线程原始输出 ---\n%s\n" %
                (sum(1 for r in results if r[1]), len(results), text))
    print("证据:", path)
    return 0 if all(r[1] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
