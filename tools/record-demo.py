"""录一段真实的产品演示：真引擎转写 → 真实页面逐段出字 → 合成为带音轨的 mp4。

之所以要脚本而不是手工录屏：index.html 上那张表必须能被复跑。这个脚本用同一份
权重、同一套参数（2 线程、use_itn）跑官方 test_wavs 五段，把输出同时用于
① 视频字幕 ② sidecar 里的 RTF 记录，两者不可能对不上。

用法（在装有 sherpa_onnx 的环境里）：
    python tools/record-demo.py --out space/demo.mp4

产物：
    space/demo.mp4          视频（H.264 + AAC，1840x1520）
    <out>.json              这次录制的实测记录：每段文本、耗时、RTF、音频 sha256

帧时间戳来自真实墙钟，音轨按同一时钟放置，所以音画不会漂。
"""

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
DEFAULT_MODEL_DIR = r"D:\projects\whisper\pc_models\sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"

# 顺序与 index.html 的表一致
ITEMS = [
    ("zh", "zh.wav", "中", "5.6 s"),
    ("en", "en.wav", "英", "7.2 s"),
    ("ja", "ja.wav", "日", "7.2 s"),
    ("ko", "ko.wav", "韩", "4.6 s"),
    ("yue", "yue.wav", "粤", "5.1 s"),
]

SR = 16000
LEAD = 0.8        # 开头留白：让人先看到空白的「等待第一段转写」
GAP = 0.5         # 段间留白
TAIL = 2.2        # 末段之后定格
CARD = 3.6        # 片尾卡停留


# ---------------------------------------------------------------- 引擎

def load_audio(path):
    import numpy as np
    import soundfile as sf

    x, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = x.mean(axis=1)
    if sr != SR:
        n = int(round(len(mono) * SR / float(sr)))
        mono = np.interp(np.linspace(0, len(mono) - 1, n), np.arange(len(mono)), mono)
    return np.ascontiguousarray(mono, dtype="float32")


def run_engine(model_dir, threads, rounds=1):
    """逐段真跑。rounds>1 时取耗时中位数——单次计时受机器负载影响，三位小数没意义。"""
    import statistics

    import sherpa_onnx

    rows = []
    rec = None
    cur = None
    for lang, wav_name, label, _ in ITEMS:
        path = os.path.join(model_dir, "test_wavs", wav_name)
        audio = load_audio(path)
        if rec is None or cur != lang:
            rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=os.path.join(model_dir, "model.int8.onnx"),
                tokens=os.path.join(model_dir, "tokens.txt"),
                language=lang,
                use_itn=True,
                num_threads=threads,
            )
            cur = lang
        dur = len(audio) / float(SR)
        times, texts = [], []
        for _ in range(rounds):
            st = rec.create_stream()
            st.accept_waveform(SR, audio)
            t = time.perf_counter()
            rec.decode_stream(st)
            times.append(time.perf_counter() - t)
            texts.append((st.result.text or "").strip())
        if len(set(texts)) > 1:
            print("  ! %s 多轮输出不一致：%s" % (label, texts))
        med = statistics.median(times)
        rows.append({
            "lang": lang, "label": label, "wav": wav_name,
            "duration": round(dur, 2), "elapsed": round(med, 3),
            "rtf": round(med / dur, 3),
            "rtf_min": round(min(times) / dur, 3),
            "rtf_max": round(max(times) / dur, 3),
            "rounds": rounds,
            "text": texts[0],
            "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(),
            "audio": audio,
        })
        print("  %-4s %5.2fs -> %5.3fs  RTF %.3f (%.3f–%.3f, %d 轮)  %s"
              % (label, dur, med, med / dur, min(times) / dur,
                 max(times) / dur, rounds, texts[0]))
    return rows


# ---------------------------------------------------------------- CDP

class Chromium:
    def __init__(self, port, width, height, dpr, profile):
        self.port = port
        self.width, self.height, self.dpr = width, height, dpr
        self.profile = profile
        self.proc = None
        self.ws = None
        self.n = 0
        self.session = None

    def __enter__(self):
        self.proc = subprocess.Popen(
            [EDGE, "--headless=new", "--disable-gpu",
             "--remote-debugging-port=%d" % self.port,
             "--user-data-dir=" + self.profile,
             "--window-size=%d,%d" % (self.width, self.height),
             "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
             "--disable-extensions", "--mute-audio", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        import websocket
        url = None
        for _ in range(60):
            try:
                d = json.load(urllib.request.urlopen(
                    "http://127.0.0.1:%d/json/version" % self.port, timeout=1))
                url = d["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.25)
        if not url:
            raise RuntimeError("Edge 的 CDP 端点没起来")
        self.ws = websocket.create_connection(url, timeout=30)
        tid = self.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.session = self.send("Target.attachToTarget",
                                 {"targetId": tid, "flatten": True})["sessionId"]
        self.send("Page.enable")
        self.send("Emulation.setDeviceMetricsOverride",
                  {"width": self.width, "height": self.height,
                   "deviceScaleFactor": self.dpr, "mobile": False})
        return self

    def send(self, method, params=None):
        self.n += 1
        msg = {"id": self.n, "method": method, "params": params or {}}
        if self.session:
            msg["sessionId"] = self.session
        self.ws.send(json.dumps(msg))
        while True:
            r = json.loads(self.ws.recv())
            if r.get("id") == self.n:
                if "error" in r:
                    raise RuntimeError("%s -> %s" % (method, r["error"]))
                return r.get("result", {})

    def goto(self, url, settle=1.6):
        self.send("Page.navigate", {"url": url})
        time.sleep(settle)

    def shoot(self, path):
        r = self.send("Page.captureScreenshot",
                      {"format": "jpeg", "quality": 90, "optimizeForSpeed": True})
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))

    def scroll_to_bottom(self):
        self.send("Runtime.evaluate", {
            "expression": "window.scrollTo(0, document.body.scrollHeight)",
            "returnByValue": True})

    def paint_background(self):
        """产品页只给 body 设了底色，超过内容高度的部分会露出 html 的白。
        这里只补 html 底色，不改任何内容与布局。"""
        self.send("Runtime.evaluate", {
            "expression": "document.documentElement.style.background='#f5f6f7';",
            "returnByValue": True})

    def __exit__(self, *exc):
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()


# ---------------------------------------------------------------- 片尾卡

CARD_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
 body{margin:0;background:#23272c;color:#e8eaed;
   font:15px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
   display:flex;min-height:100vh;align-items:center;justify-content:center}
 .box{width:760px;padding:0 24px}
 h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
 .sub{color:#9aa4ae;font-size:14px;margin:0 0 26px}
 table{border-collapse:collapse;width:100%;font-size:14px}
 th,td{text-align:left;padding:9px 12px;border-bottom:1px solid #343a41}
 th{color:#9aa4ae;font-weight:600;font-size:13px}
 td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
 .hi{color:#f5c542}
 .out{font-size:13px;color:#d4d9de}
 .foot{margin-top:24px;color:#9aa4ae;font-size:13px;border-top:1px solid #343a41;padding-top:16px}
 .brand{margin:18px 0 0;color:#f5c542;font-size:14px;letter-spacing:.12em}
</style></head><body><div class="box">
<h1>同一份模型，五个语种</h1>
<p class="sub">刚才那五行字幕不是写好的台词，是这段视频里真跑出来的结果。</p>
<table><thead><tr><th>音频</th><th>时长</th><th>输出</th></tr></thead>
<tbody>__ROWS__</tbody></table>
<p class="foot">处理速度约为实时的十倍（RTF 0.08–0.10，2 个 CPU 线程）；测法与波动范围在页面上。<br>
权重与这五段音频都在 `ToothpasteLake/offlisten-models`，可逐条复跑。<br>
这段视频里的字只经过了 127.0.0.1，没有出过这台机器。</p>
<p class="brand">录匣 Offlisten</p>
</div></body></html>"""


def card_html(rows):
    cells = []
    for r in rows:
        cells.append(
            '<tr><td>%s</td><td class="num">%.1f s</td><td class="out">%s</td></tr>'
            % (r["label"], r["duration"], r["text"]))
    # CARD_HTML 里含 CSS 的 %，不能用 % 格式化，只做一次替换
    return CARD_HTML.replace("__ROWS__", "".join(cells))


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join("space", "demo.mp4"))
    ap.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--width", type=int, default=920)
    ap.add_argument("--height", type=int, default=700)
    ap.add_argument("--dpr", type=float, default=2.0)
    ap.add_argument("--port", type=int, default=8793)
    ap.add_argument("--debug-port", type=int, default=9334)
    ap.add_argument("--keep", action="store_true", help="保留帧与中间文件")
    ap.add_argument("--rounds", type=int, default=1, help="每段测量轮数，>1 取中位数")
    ap.add_argument("--bench", action="store_true", help="只测量不录制，输出 JSON")
    args = ap.parse_args()

    import numpy as np
    import imageio_ffmpeg

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "engine"))
    import web_live as W

    work = tempfile.mkdtemp(prefix="offlisten-demo-")
    frames_dir = os.path.join(work, "frames")
    os.makedirs(frames_dir)
    profile = os.path.join(work, "profile")
    print("工作目录:", work)

    print("\n[1/5] 真跑五段音频")
    rows = run_engine(args.model_dir, args.threads, args.rounds)

    if args.bench:
        out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "model": "SenseVoice int8, use_itn=True, threads=%d" % args.threads,
               "rounds": args.rounds,
               "rows": [{k: v for k, v in r.items() if k != "audio"} for r in rows]}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print("\n[2/5] 起本地服务与无头浏览器")
    srv = W.start(port=args.port, write_discovery=False, open_browser=False, archive=True)
    print("  页面:", srv.url)

    frames = []      # (t_rel, path)
    audio_plan = []  # (t_rel, np.array)
    t0 = None

    def tick(browser, deadline):
        """在 deadline 之前不停截帧，返回实际停下的时刻。"""
        while True:
            now = time.monotonic()
            if now >= deadline:
                return now
            p = os.path.join(frames_dir, "f%05d.jpg" % len(frames))
            browser.shoot(p)
            frames.append((time.monotonic() - t0, p))

    try:
        with Chromium(args.debug_port, args.width, args.height, args.dpr, profile) as br:
            print("\n[3/5] 打开页面")
            br.goto(srv.url, settle=2.6)
            br.paint_background()
            br.scroll_to_bottom()

            t0 = time.monotonic()
            tick(br, t0 + LEAD)

            for k, r in enumerate(rows):
                # 先让这段音频在录制时钟上开始，说完再落字——产品里就是 VAD 段结束才出稿
                start = time.monotonic() - t0
                audio_plan.append((start, r["audio"]))
                print("  %-2s 音频 t=%.1fs 起（%.1fs）" % (r["label"], start, r["duration"]))
                tick(br, t0 + start + r["duration"])

                srv.publish("final", r["text"],
                            ts=time.strftime("%H:%M:%S"),
                            rel=int(round(start + r["duration"])),
                            source="asr")
                br.scroll_to_bottom()
                tick(br, time.monotonic() + GAP)

                # 段末立刻截一帧，保证字幕出现的瞬间一定被拍到
                p = os.path.join(frames_dir, "f%05d.jpg" % len(frames))
                br.shoot(p)
                frames.append((time.monotonic() - t0, p))

            tick(br, time.monotonic() + TAIL)

            end_t = time.monotonic() - t0

            print("\n[4/5] 片尾卡")
            card = os.path.join(work, "card.html")
            with open(card, "w", encoding="utf-8") as f:
                f.write(card_html(rows))
            br.goto("file:///" + card.replace("\\", "/"), settle=1.4)
            br.paint_background()
            for _ in range(3):
                p = os.path.join(frames_dir, "f%05d.jpg" % len(frames))
                br.shoot(p)
                frames.append((end_t + (time.monotonic() - t0 - end_t), p))
                time.sleep(0.9)
    finally:
        srv.stop()

    total = time.monotonic() - t0
    print("  录制总时长 %.1fs，%d 帧，平均 %.1f fps"
          % (total, len(frames), len(frames) / max(total, 0.1)))

    print("\n[5/5] 合成")
    # 音轨：按录制时钟放置，空白处自然静音
    n_total = int(round((total + 0.5) * SR))
    mix = np.zeros(n_total, dtype=np.float32)
    for start, a in audio_plan:
        i = int(round(start * SR))
        j = min(i + len(a), n_total)
        if i < n_total:
            mix[i:j] += a[: j - i]
    peak = float(np.max(np.abs(mix))) or 1.0
    if peak > 0.98:
        mix *= 0.98 / peak
    wav = os.path.join(work, "audio.wav")
    import soundfile as sf
    sf.write(wav, mix, SR)

    # 帧时间表：每帧持续到下一帧，最后一帧补到音轨结尾
    listf = os.path.join(work, "frames.txt")
    with open(listf, "w", encoding="utf-8", newline="\n") as f:
        for idx, (t, p) in enumerate(frames):
            nxt = frames[idx + 1][0] if idx + 1 < len(frames) else max(total, t + 0.1)
            dur = max(nxt - t, 0.02)
            f.write("file '%s'\nduration %.3f\n" % (p.replace("\\", "/"), dur))
        f.write("file '%s'\n" % frames[-1][1].replace("\\", "/"))

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", listf, "-i", wav,
           "-vf", "scale=in_range=full:out_range=tv",
           "-c:v", "libx264", "-preset", "medium", "-crf", "21",
           "-pix_fmt", "yuv420p", "-color_range", "tv", "-fps_mode", "vfr",
           "-c:a", "aac", "-b:a", "112k", "-shortest",
           "-movflags", "+faststart", out]
    print("  ffmpeg …")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    side = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": "SenseVoice int8, use_itn=True, threads=%d" % args.threads,
        "video": os.path.basename(out),
        "video_bytes": os.path.getsize(out),
        "video_seconds": round(total, 2),
        "frames": len(frames),
        "rows": [{k: v for k, v in r.items() if k != "audio"} for r in rows],
    }
    with open(out + ".json", "w", encoding="utf-8") as f:
        json.dump(side, f, ensure_ascii=False, indent=2)

    print("\n产物: %s (%.2f MB, %.1fs)" % (out, os.path.getsize(out) / 1048576.0, total))
    print("记录: %s.json" % out)
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print("中间文件保留在:", work)


if __name__ == "__main__":
    main()
