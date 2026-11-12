# -*- coding: utf-8 -*-
"""
无桌面 UI 的转写运行核心（前端反转 / I-068）。

边界：本模块不 import tkinter，也不在模块顶层 import pc_transcriber（后者会
拉起 numpy / soundcard / sherpa-onnx 等重依赖）。真实 pipeline 在 start() 里
延迟导入；验收可注入 pipeline_factory 与 translator，全程不碰音频设备。

控制面唯一入口是 handle(action, patch)，由 web_live 的 /api/control/* 转发。
这样 web_live 保持零重依赖，也不需要知道 LiveCore 的任何细节。
"""
import os
import queue
import threading
import time
from datetime import datetime
from types import SimpleNamespace

ENGINES = ("sensevoice", "zipformer")
SOURCES = ("loopback", "mic")
CONFIG_KEYS = ("engine", "source", "translate", "device", "noise_gate", "save")

DEFAULTS = {
    "engine": "sensevoice",
    "source": "loopback",
    "translate": True,
    "overlay": False,
    "device": None,
    "noise_gate": None,
    "save": None,
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class LiveCore:
    """运行核心：采集/识别线程 + 消费循环 + 旁路发布，全部后台线程。"""

    def __init__(self, web=None, config=None, pipeline_factory=None,
                 translator=None, on_event=None, model_dir=None):
        self.web = web
        self.cfg = dict(DEFAULTS)
        self.cfg.update({k: v for k, v in (config or {}).items() if k in CONFIG_KEYS})
        self.cfg["overlay"] = bool((config or {}).get("overlay", False))
        self.model_dir = model_dir
        self.pipeline_factory = pipeline_factory
        self.translator = translator
        self.on_event = on_event
        self.lock = threading.RLock()
        self.running = False
        self._closed = False
        self._session = 0
        self._stop = threading.Event()
        self._threads = []
        self.ui_q = queue.Queue()
        self.level = {}
        self.t_start = time.time()
        self.started_at = None
        self.segments = 0
        self.save_f = None
        self._consume_thread = threading.Thread(target=self._consume_loop,
                                                daemon=True, name="live-core-consume")
        self._consume_thread.start()

    # ------------------------------------------------------------ 状态 ----
    def status(self):
        with self.lock:
            meeting = None
            if self.web is not None:
                try:
                    meeting = self.web.meta
                except Exception:
                    meeting = None
            return {
                "available": True,
                "mode": "headless",
                "running": self.running,
                "engine": self.cfg["engine"],
                "source": self.cfg["source"],
                "translate": bool(self.cfg["translate"]),
                "overlay": bool(self.cfg["overlay"]),
                "overlay_changeable": False,
                "overlay_hint": "悬浮字幕是启动选项（--overlay），运行时不可切换",
                "device": self.cfg["device"],
                "noise_gate": self.cfg["noise_gate"],
                "engines": list(ENGINES),
                "sources": list(SOURCES),
                "segments": self.segments,
                "started_at": self.started_at,
                "level": round(float(self.level.get("rms", 0.0)), 6),
                "meeting": meeting,
            }

    def handle(self, action, patch=None):
        """web_live 控制端点的唯一入口。返回可直接 JSON 序列化的 dict。"""
        if action == "state":
            return {"ok": True, "state": self.status()}
        if action == "start":
            ok, msg = self.start()
            return {"ok": ok, "message": msg, "state": self.status()}
        if action == "stop":
            ok, msg = self.stop()
            return {"ok": ok, "message": msg, "state": self.status()}
        if action == "configure":
            ok, msg = self.configure(patch or {})
            return {"ok": ok, "message": msg, "state": self.status()}
        return {"ok": False, "error": "未知动作: %s" % action, "state": self.status()}

    # ---------------------------------------------------------- 配置 ----
    def configure(self, patch):
        if not isinstance(patch, dict):
            return False, "配置必须是 JSON 对象"
        unknown = [k for k in patch if k not in CONFIG_KEYS]
        if unknown:
            return False, "不支持的配置项: %s" % ", ".join(unknown)
        engine = patch.get("engine", self.cfg["engine"])
        source = patch.get("source", self.cfg["source"])
        if engine not in ENGINES:
            return False, "engine 只能是 %s" % " / ".join(ENGINES)
        if source not in SOURCES:
            return False, "source 只能是 %s" % " / ".join(SOURCES)
        if "translate" in patch and not isinstance(patch["translate"], bool):
            return False, "translate 必须是布尔值"
        if "noise_gate" in patch and patch["noise_gate"] is not None:
            try:
                patch = dict(patch, noise_gate=float(patch["noise_gate"]))
            except (TypeError, ValueError):
                return False, "noise_gate 必须是数字"
            if not 0 < patch["noise_gate"] < 1:
                return False, "noise_gate 必须落在 (0, 1)"
        for key in ("device", "save"):
            if key in patch and patch[key] is not None and not isinstance(patch[key], str):
                return False, "%s 必须是字符串或 null" % key

        with self.lock:
            was_running = self.running
            need_restart = ("engine" in patch and patch["engine"] != self.cfg["engine"])
            self.cfg.update({k: v for k, v in patch.items() if k in CONFIG_KEYS})
            if need_restart and was_running:
                # 换引擎 = 换模型，必须整条 pipeline 重启，不能只改字符串
                self.stop()
                self.start()
                return True, "引擎已切换为 %s，采集与识别链路已重启" % self.cfg["engine"]
        if "source" in patch:
            # open_input 的 source_ref 会检测 args.source 变化并重开采集流（I-066）
            return True, "音源已设为 %s，采集流会自动重开" % self.cfg["source"]
        return True, "配置已更新"

    # ------------------------------------------------------ 生命周期 ----
    def _runner(self, engine):
        if self.pipeline_factory is not None:
            return self.pipeline_factory(engine)
        import pc_transcriber as pc  # 延迟：避免模块顶层拉起音频/模型依赖
        return pc.sv_pipeline if engine == "sensevoice" else pc.zf_pipeline

    def _translate(self, text):
        if self.translator is not None:
            return self.translator(text)
        import pc_transcriber as pc
        return pc.translate_text(text)

    def _args(self):
        md = self.model_dir
        if md is None and self.pipeline_factory is None:
            import pc_transcriber as pc
            md = pc.MODEL_DIR
        return SimpleNamespace(
            source=self.cfg["source"],
            device=self.cfg["device"],
            noise_gate=self.cfg["noise_gate"],
            model_dir=md or "",
            engine=self.cfg["engine"],
        )

    def start(self):
        with self.lock:
            if self._closed:
                return False, "运行核心已关闭"
            if self.running:
                return True, "已在运行"
            self._stop = threading.Event()
            self._session += 1
            sid = self._session
            stop = self._stop
            self.level = {}
            self.t_start = time.time()
            self.started_at = datetime.now().isoformat(timespec="seconds")
            if self.save_f is None and self.cfg["save"]:
                path = self.cfg["save"]
                if not os.path.isabs(path):
                    path = os.path.join(BASE_DIR, path)
                try:
                    self.save_f = open(path, "a", encoding="utf-8")
                except OSError as e:
                    return False, "文字稿无法写入: %s" % e
            try:
                args = self._args()
                runner = self._runner(self.cfg["engine"])
            except Exception as e:
                return False, "引擎加载失败: %s" % e
            res_q = queue.Queue()
            t_pipeline = threading.Thread(
                target=self._safe_run,
                args=(runner, args, stop, res_q, self.level),
                daemon=True, name="live-core-pipeline-%d" % sid)
            t_consume = threading.Thread(
                target=self._res_consumer, args=(sid, res_q, stop),
                daemon=True, name="live-core-trans-%d" % sid)
            self._threads = [t_pipeline, t_consume]
            t_pipeline.start()
            t_consume.start()
            self.running = True
            print("[运行核心] 已启动 engine=%s source=%s translate=%s"
                  % (self.cfg["engine"], self.cfg["source"], self.cfg["translate"]))
            return True, "已启动"

    @staticmethod
    def _safe_run(runner, args, stop, res_q, level):
        try:
            runner(args, stop, res_q, level)
        except Exception as e:
            print("[运行核心] pipeline 异常退出: %s: %s" % (type(e).__name__, e))

    def _res_consumer(self, sid, res_q, stop):
        while not (stop.is_set() and res_q.empty()):
            try:
                kind, text = res_q.get(timeout=0.5)
            except queue.Empty:
                continue
            self.ui_q.put((sid, kind, text))
            if kind == "final" and self.cfg["translate"]:
                try:
                    tr = self._translate(text)
                except Exception as e:
                    print("[运行核心] 翻译失败，已跳过: %s" % e)
                    continue
                if tr:
                    self.ui_q.put((sid, "trans", tr))

    def stop(self):
        with self.lock:
            if not self.running:
                return True, "已是待机"
            self._stop.set()
            self.running = False
        # 让旧会话的采集流先退出，再允许下一次 start 开新流
        deadline = time.time() + 2.0
        for t in list(self._threads):
            try:
                t.join(timeout=max(0.0, deadline - time.time()))
            except RuntimeError:
                pass
        self._threads = []
        print("[运行核心] 已停止")
        return True, "已停止"

    def publish(self, kind, text):
        """注入一段事件（验收 / 回放用），走与真实链路相同的消费循环。"""
        self.ui_q.put((self._session, kind, text))

    def _consume_loop(self):
        while not self._closed:
            try:
                sid, kind, text = self.ui_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if sid != self._session:
                continue  # 丢弃上一会话的残留段
            self._emit(kind, text)

    def _emit(self, kind, text):
        if kind not in ("final", "part", "trans"):
            return
        ts = time.strftime("%H:%M:%S")
        rel = int(time.time() - self.t_start)
        if self.web is not None:
            try:
                self.web.publish(kind, text, ts=ts, rel=rel)
            except Exception as e:
                print("[运行核心] 旁路推送失败，已忽略: %s" % e)
        if self.on_event is not None:
            try:
                self.on_event(kind, text)
            except Exception:
                pass
        if kind == "final":
            self.segments += 1
            print("[段] " + text)
            if self.save_f:
                try:
                    self.save_f.write(text + "\n")
                    self.save_f.flush()
                except OSError:
                    pass

    def close(self):
        self.stop()
        self._closed = True
        if self.save_f:
            try:
                self.save_f.close()
            except OSError:
                pass
            self.save_f = None


def run_headless(args):
    """`live --headless` 入口。主线程给 overlay 或 Ctrl+C，其余全在后台线程。"""
    import web_live

    cfg = {
        "engine": getattr(args, "engine", "sensevoice"),
        "source": getattr(args, "source", "loopback"),
        "translate": not getattr(args, "no_translate", False),
        "overlay": bool(getattr(args, "overlay", False)),
        "device": getattr(args, "device", None),
        "noise_gate": getattr(args, "noise_gate", None),
        "save": getattr(args, "save", None),
    }
    core = LiveCore(config=cfg, model_dir=getattr(args, "model_dir", None))
    web = web_live.start(control=core, open_browser=False,
                         archive=not getattr(args, "no_archive", False))
    core.web = web
    print("无桌面窗模式：扩展 / live 页是控制与阅读前端，tkinter 前端未加载")
    print("本机服务: %s" % web.url)
    print(web.summary())
    print(web.meeting_line())
    print("历史会议: http://127.0.0.1:%d/history?token=%s" % (web.port, web.token))
    print("控制端点: /api/control/state (GET) 与 /api/control/action (POST)")
    print("把上面完整 URL 粘进扩展；Ctrl+C 结束。")

    overlay = None
    if cfg["overlay"]:
        try:
            from overlay import Overlay
            overlay = Overlay()
            core.on_event = overlay.push
            print("悬浮字幕已开启（Esc 或右键关闭浮层也会结束本进程）")
        except Exception as e:
            print("悬浮字幕启动失败，无窗模式照常运行: %s" % e)
            overlay = None

    try:
        if overlay is not None:
            overlay.run()          # tkinter 必须主线程
        else:
            while True:
                time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，正在结束…")
    finally:
        core.close()
        web.stop()
