# -*- coding: utf-8 -*-
"""
web_live.py - 本地信息源旁路层（纯标准库；零 LLM、零 apikey）

把转写段变成浏览器可立即消费的文本流：
  GET  /                     live 页面（需 token）
  GET  /events               SSE 增量事件（需 token）
  GET  /transcript.json      事实源快照：仅 final + 译文（需 token）
  GET  /transcript.md        Markdown 导出（需 token）
  GET  /health               状态探针（免 token，不含文本、不含 token）
  GET  /history              历史会议页：按日期分组，题目/star 管理（需 token）
  GET  /m/<id>               单场会议页：首屏注入全文，供复现与 AI 插件读取（需 token）
  GET  /meetings.json        历史会议分组数据（需 token）
  GET  /api/meeting/<id>     单场结构化数据（需 token）
  POST /api/meeting/<id>     更新题目与星标（需 token + application/json）
  GET  /api/control/state    运行核心状态（需 token；未挂核心时返回只读说明）
  POST /api/control/action   start / stop / configure / state（需 token + JSON）

控制面通过 `start(control=...)` 注入；HTTP 层只转发 action，不 import 任何引擎依赖，
因此 Native Messaging（I-070）等其它传输通道可以复用同一控制面。

安全边界：只绑 127.0.0.1；Host 白名单防 DNS rebinding；内容端点 token 鉴权；
          CORS 仅对扩展 origin 回显；发现文件 web_live.json 只写端口/token 供本机工具读取。
          part（未定稿流式片段）只走 SSE 灰字显示，不进入事实源与导出。
          Windows 端口用 SO_EXCLUSIVEADDRUSE 独占、占用即递增；不要改回 SO_REUSEADDR，
          否则两个实例会同绑一个端口，浏览器连到旧实例并报 403。

会议对象（I-062 口径，用户 2026-11-12 拍板）：
  一级 = 按日期归组 meetings/YYYY-MM-DD/，列表显示 `2026-11-12 #2`（组内序号）
  二级 = YYYYMMDD_HHMMSS（日期+时间）作唯一标识，所有链接与 API 都用它
  `<id>.md` 是事实源，只 append 不回写；`<id>.meta.json` 存题目/star/ended_at/段数。
  `#n` 按当天 ID 排序动态计算、不落盘，页面 / health / 历史列表同源，避免数字矛盾。
  旧扁平 `meetings/<no>_<id>.md` 自动识别为 legacy，用 --migrate-archives 显式迁移。
  段级深链接与问询 AI 侧栏绑定属 I-060，尚未实现。

命令行：
  python web_live.py --self-test
  python web_live.py --replay transcript_20261027_145556.txt --speed 20
  python web_live.py --port 47813                # 自动打开浏览器
  python web_live.py --port 47813 --no-open      # 只打印 URL
  python web_live.py --port 47813 --no-archive   # 不写会议存档
  python web_live.py --migrate-archives [--dry-run]

被主程序调用：
  import web_live
  srv = web_live.start(port=47813)
  srv.publish("final", text, ts="14:43:24", rel=20)
  srv.stop()
"""
import argparse
import atexit
import hashlib
import hmac
import json
import os
import queue
import re
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PAGE_PATH = os.path.join(BASE_DIR, "web_live", "index.html")
HISTORY_PAGE_PATH = os.path.join(BASE_DIR, "web_live", "history.html")
MEETING_PAGE_PATH = os.path.join(BASE_DIR, "web_live", "meeting.html")
ERROR_PAGE_PATH = os.path.join(BASE_DIR, "web_live", "token_error.html")
DISCOVERY_PATH = os.path.join(BASE_DIR, "web_live.json")
SHORTCUT_PATH = os.path.join(BASE_DIR, "open_live.url")  # 英文名：中文名 .url 在部分 Windows 环境删除/识别会失败
ARCHIVE_DIR = os.path.join(BASE_DIR, "meetings")
EVIDENCE_DIR = os.path.join(BASE_DIR, "acceptance", "web_live")
DEFAULT_PORT = 47813
VERSION = 2

ID_RE = re.compile(r"^\d{8}_\d{6}$")
LEGACY_RE = re.compile(r"^(\d{4})_(\d{8}_\d{6})$")
DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FINAL_LINE_RE = re.compile(r"^\*\*\[(\d{2}:\d{2}:\d{2})(?:\s+\+(\d+)s)?\]\*\*\s*(.*)$")
TRANS_LINE_RE = re.compile(r"^>\s*\[(\d{2}:\d{2}:\d{2})(?:\s+\+(\d+)s)?\]\s*译\s*(.*)$")
ENDED_RE = re.compile(r"<!--\s*ended_at:\s*([^;]+?)\s*;\s*facts:\s*(\d+)\s*-->")
MAX_PATCH_BYTES = 4096
MAX_TITLE_LEN = 120


class EventBus:
    """单一事实源：facts 只含 final + trans；part 只广播给页面，不落事实源。"""

    def __init__(self, meeting_id=None):
        self.lock = threading.Lock()
        self.subscribers = []
        self.facts = []
        self.seq = 0
        self.meeting_id = meeting_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.started_at = datetime.now().isoformat(timespec="seconds")

    def publish(self, kind, text, ts=None, rel=None, source="asr"):
        if kind not in ("final", "part", "trans"):
            raise ValueError("kind must be final/part/trans, got %r" % kind)
        if kind == "trans":
            source = "argos"  # 译文来自 Argos 离线机器翻译，不是模型生成
        ev = {
            "id": 0,
            "kind": kind,
            "text": text,
            "ts": ts or time.strftime("%H:%M:%S"),
            "rel": rel,
            "source": source,
        }
        with self.lock:
            self.seq += 1
            ev["id"] = self.seq
            if kind != "part":
                self.facts.append(ev)
            subs = list(self.subscribers)
        for q in subs:
            try:
                q.put_nowait(ev)
            except queue.Full:
                pass
        return ev

    def subscribe(self):
        q = queue.Queue(maxsize=256)
        with self.lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def snapshot(self):
        with self.lock:
            return list(self.facts)


def facts_lines(facts):
    out = []
    for e in facts:
        rel = " +%ss" % e["rel"] if e["rel"] is not None else ""
        tag = "译 " if e["kind"] == "trans" else ""
        out.append("[%s%s] %s%s" % (e["ts"], rel, tag, e["text"]))
    return "\n".join(out)


def facts_markdown(bus, meta=None):
    """实时导出：title / label 都来自当前 meta，落盘存档不写这些易变字段。"""
    facts = bus.snapshot()
    meta = meta or {}
    out = ["---", "meeting_id: %s" % bus.meeting_id]
    if meta.get("date"):
        out.append("date: %s" % meta["date"])
    if meta.get("label"):
        out.append("meeting_label: %s" % meta["label"])
    if meta.get("started_at"):
        out.append("started_at: %s" % meta["started_at"])
    if meta.get("title"):
        out.append('title: "%s"' % str(meta["title"]).replace('"', "'").replace("\r", " ").replace("\n", " "))
    if meta.get("archive"):
        out.append("archive: %s" % meta["archive"])
    out += [
        "source: local ASR (offline, sherpa-onnx)",
        "translation: Argos offline machine translation (not an LLM)",
        "segments: %d" % len(facts),
        "---",
        "",
        "# 本地转写 · 会议记录",
        "",
        "译文行以 > 开头，由 Argos 离线机器翻译生成，不是原文，仅供参考。",
        "",
    ]
    for e in facts:
        rel = " +%ss" % e["rel"] if e["rel"] is not None else ""
        if e["kind"] == "trans":
            out.append("> [%s%s] 译 %s" % (e["ts"], rel, e["text"]))
            out.append("")
        else:
            out.append("**[%s%s]** %s" % (e["ts"], rel, e["text"]))
            out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- 会议仓储
# 只读事实源 md + 可写 meta.json。所有编号在扫描时按 (date, id) 排序动态生成，
# 不存进文件，避免「页面写 #2、列表写 #3」这类数字矛盾。

def id_date(mid):
    try:
        return datetime.strptime(mid[:8], "%Y%m%d").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def id_clock(mid):
    return "%s:%s:%s" % (mid[9:11], mid[11:13], mid[13:15])


def _rel(path):
    try:
        return os.path.relpath(path, BASE_DIR).replace("\\", "/")
    except ValueError:  # 自检把存档放到系统临时目录时可能跨盘符
        return path.replace("\\", "/")


def meta_path_for(archive_path):
    return os.path.join(os.path.dirname(archive_path),
                        os.path.basename(archive_path)[:-3] + ".meta.json")


def _read_meta(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_meta(path, data):
    """原子写：先写 .tmp 再 replace，避免半截 JSON。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def parse_segments(md):
    segs = []
    for raw in md.splitlines():
        line = raw.rstrip()
        m = FINAL_LINE_RE.match(line)
        if m:
            segs.append({"ts": m.group(1), "rel": int(m.group(2)) if m.group(2) else None,
                         "kind": "final", "text": m.group(3)})
            continue
        m = TRANS_LINE_RE.match(line)
        if m:
            segs.append({"ts": m.group(1), "rel": int(m.group(2)) if m.group(2) else None,
                         "kind": "trans", "text": m.group(3)})
    return segs


def _scan_archives():
    """扫描 meetings/ 下新格式与 legacy 格式，按 (date, id) 排序并生成组内序号。"""
    out = []
    if not os.path.isdir(ARCHIVE_DIR):
        return out
    for root, _dirs, files in os.walk(ARCHIVE_DIR):
        for name in files:
            if not name.endswith(".md"):
                continue
            stem = name[:-3]
            m = LEGACY_RE.match(stem)
            if m:
                mid, legacy = m.group(2), True
            elif ID_RE.match(stem):
                mid, legacy = stem, False
            else:
                continue
            parent = os.path.basename(root)
            date = parent if DATE_DIR_RE.match(parent) else id_date(mid)
            if not date:
                continue
            out.append({"id": mid, "date": date, "path": os.path.join(root, name),
                        "legacy": legacy})
    out.sort(key=lambda e: (e["date"], e["id"], e["path"]))
    seen = {}
    for e in out:
        seen[e["date"]] = seen.get(e["date"], 0) + 1
        e["no"] = seen[e["date"]]
    return out


def no_for_id(mid):
    for e in _scan_archives():
        if e["id"] == mid:
            return e["no"]
    return None


def meeting_info(entry):
    md_text = ""
    try:
        with open(entry["path"], "r", encoding="utf-8") as f:
            md_text = f.read()
    except OSError:
        pass
    meta = _read_meta(meta_path_for(entry["path"]))
    ended = ENDED_RE.search(md_text)
    segs = parse_segments(md_text)
    label = "%s #%d" % (entry["date"], entry["no"])
    return {
        "id": entry["id"],
        "date": entry["date"],
        "no": entry["no"],
        "label": label,
        "display": "%s %s" % (entry["date"], id_clock(entry["id"])),
        "title": meta.get("title", ""),
        "star": bool(meta.get("star", False)),
        "started_at": meta.get("started_at") or (entry["date"] + "T" + id_clock(entry["id"])),
        "ended_at": meta.get("ended_at") or (ended.group(1).strip() if ended else None),
        "segments": len(segs),
        "archive": _rel(entry["path"]),
        "legacy": entry["legacy"],
        "url": "/m/%s" % entry["id"],
    }


def list_meetings():
    entries = _scan_archives()
    groups = {}
    for e in entries:
        groups.setdefault(e["date"], []).append(meeting_info(e))
    return {
        "groups": [{"date": d, "label": d, "count": len(items), "meetings": items}
                   for d, items in sorted(groups.items(), reverse=True)],
        "total": len(entries),
        "legacy": sum(1 for e in entries if e["legacy"]),
        "archive_dir": _rel(ARCHIVE_DIR),
    }


def find_meeting(mid):
    if not ID_RE.match(mid or ""):
        return None
    for e in _scan_archives():
        if e["id"] == mid:
            return e
    return None


def get_meeting(mid):
    entry = find_meeting(mid)
    if not entry:
        return None
    try:
        with open(entry["path"], "r", encoding="utf-8") as f:
            md = f.read()
    except OSError:
        md = ""
    segs = parse_segments(md)
    return {
        "meeting": meeting_info(entry),
        "segments": segs,
        "markdown": md,
        "text": facts_lines(segs),
        "note": "译文由 Argos 离线机器翻译生成，非原文；未定稿片段不在此处。",
    }


def update_meeting(mid, patch):
    """题目增删改查 + star。只允许这两个字段；清空题目 = title: ""。"""
    entry = find_meeting(mid)
    if not entry:
        return None
    if not isinstance(patch, dict):
        raise ValueError("body 必须是 JSON 对象")
    extra = set(patch) - {"title", "star"}
    if extra:
        raise ValueError("不支持的字段: %s" % ", ".join(sorted(extra)))
    meta = _read_meta(meta_path_for(entry["path"]))
    if "title" in patch:
        title = patch["title"]
        if not isinstance(title, str):
            raise ValueError("title 必须是字符串")
        title = re.sub(r"\s+", " ", title).strip()
        if len(title) > MAX_TITLE_LEN:
            raise ValueError("title 最长 %d 字" % MAX_TITLE_LEN)
        meta["title"] = title
    if "star" in patch:
        if not isinstance(patch["star"], bool):
            raise ValueError("star 必须是布尔值")
        meta["star"] = patch["star"]
    meta.setdefault("id", mid)
    meta.setdefault("started_at", entry["date"] + "T" + id_clock(mid))
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_meta(meta_path_for(entry["path"]), meta)
    return meeting_info(entry)


def migrate_archives(dry_run=False):
    """把旧扁平 <no>_<id>.md 搬进 <date>/<id>.md；冲突不动原文件，绝不静默覆盖。"""
    result = {"moved": [], "conflicts": [], "planned": []}
    for e in _scan_archives():
        if not e["legacy"]:
            continue
        dst_dir = os.path.join(ARCHIVE_DIR, e["date"])
        dst = os.path.join(dst_dir, e["id"] + ".md")
        if os.path.exists(dst):
            result["conflicts"].append(e["id"])
            continue
        if dry_run:
            result["planned"].append(e["id"])
            continue
        os.makedirs(dst_dir, exist_ok=True)
        os.replace(e["path"], dst)
        src_meta = meta_path_for(e["path"])
        if os.path.exists(src_meta):
            os.replace(src_meta, meta_path_for(dst))
        result["moved"].append(e["id"])
    return result


def live_meta(ctx):
    """当前会议的 meta：每次现算 no / title / star，与历史列表同源。"""
    bus = ctx["bus"]
    base = dict(ctx.get("meta_base") or {})
    if not ctx.get("archive_path") or not base:
        return {"id": bus.meeting_id, "date": id_date(bus.meeting_id),
                "display": bus.started_at.replace("T", " "),
                "started_at": bus.started_at, "no": None, "label": None,
                "archive": None, "title": "", "star": False}
    no = no_for_id(bus.meeting_id)
    base["no"] = no
    base["label"] = "%s #%s" % (base["date"], no if no is not None else "?")
    meta = _read_meta(meta_path_for(ctx["archive_path"]))
    base["title"] = meta.get("title", "")
    base["star"] = bool(meta.get("star", False))
    return base


# ---------------------------------------------------------------- HTTP 层

class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, ctx, request, client_address, server):
        self.ctx = ctx
        super().__init__(request, client_address, server)

    def log_message(self, fmt, *args):
        pass

    def _host_ok(self):
        host = self.headers.get("Host", "")
        port = self.ctx["port"]
        return host in ("127.0.0.1:%d" % port, "localhost:%d" % port)

    def _token_state(self):
        supplied = self.headers.get("X-Whisper-Token", "")
        if not supplied:
            supplied = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        if not supplied:
            return "missing"
        try:
            ok = hmac.compare_digest(supplied.encode("utf-8"),
                                     self.ctx["token"].encode("utf-8"))
        except (AttributeError, UnicodeError):
            ok = False
        return "ok" if ok else "invalid"

    def _deny(self, state):
        """403 返回可读引导页：不泄露任何转写文本，也不泄露 token 本身。"""
        try:
            with open(ERROR_PAGE_PATH, "r", encoding="utf-8") as f:
                html = f.read()
            meta = json.dumps({"state": state,
                               "instance": self.ctx["instance"],
                               "port": self.ctx["port"]}, ensure_ascii=False)
            html = html.replace("window.__DENY__ = {};",
                                "window.__DENY__ = %s;" % meta)
            self._send(403, html, "text/html; charset=utf-8")
        except OSError:
            self._send(403, {"error": "token " + state})

    def _cors(self):
        origin = self.headers.get("Origin", "")
        if origin.startswith("chrome-extension://") or origin.startswith("moz-extension://"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Whisper-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _page(self, path, replacements):
        try:
            with open(path, "r", encoding="utf-8") as f:
                html = f.read()
        except OSError as e:
            self._send(500, {"error": "page missing: %s" % e})
            return
        for old, new in replacements:
            html = html.replace(old, new)
        self._send(200, html, "text/html; charset=utf-8")

    @staticmethod
    def _boot(value):
        return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")

    def do_OPTIONS(self):
        if not self._host_ok():
            self._send(403, {"error": "host not allowed"})
            return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    def do_GET(self):
        if not self._host_ok():
            self._send(403, {"error": "host not allowed"})
            return
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, {
                "ok": True,
                "service": "whisper-web-live",
                "version": VERSION,
                "port": self.ctx["port"],
                "instance": self.ctx["instance"],
                "meeting": live_meta(self.ctx),
                "segments": len(self.ctx["bus"].snapshot()),
                "control": self.ctx.get("control") is not None,
            })
            return
        state = self._token_state()
        if state != "ok":
            self._deny(state)
            return
        if path == "/":
            boot = self._boot(self.ctx["bus"].snapshot())
            meta = self._boot(live_meta(self.ctx))
            self._page(PAGE_PATH, [
                ("window.__WHISPER_BOOTSTRAP__ = [];",
                 "window.__WHISPER_BOOTSTRAP__ = %s;" % boot),
                ("window.__WHISPER_MEETING__ = {};",
                 "window.__WHISPER_MEETING__ = %s;" % meta),
            ])
            return
        if path == "/events":
            self._sse()
            return
        if path == "/transcript.json":
            facts = self.ctx["bus"].snapshot()
            self._send(200, {
                "meeting_id": self.ctx["bus"].meeting_id,
                "started_at": self.ctx["bus"].started_at,
                "meeting": live_meta(self.ctx),
                "segments": facts,
                "text": facts_lines(facts),
                "note": "译文由 Argos 离线机器翻译生成，非原文；未定稿片段不在此处。",
            })
            return
        if path == "/transcript.md":
            self._send(200, facts_markdown(self.ctx["bus"], live_meta(self.ctx)),
                       "text/markdown; charset=utf-8")
            return
        if path == "/history":
            self._page(HISTORY_PAGE_PATH, [
                ("window.__HISTORY_BOOT__ = null;",
                 "window.__HISTORY_BOOT__ = %s;" % self._boot(list_meetings())),
            ])
            return
        if path == "/meetings.json":
            self._send(200, list_meetings())
            return
        if path.startswith("/m/") and path.endswith(".md"):
            data = get_meeting(path[3:-3])
            if data is None:
                self._send(404, {"error": "meeting not found"})
            else:
                self._send(200, data["markdown"], "text/markdown; charset=utf-8")
            return
        if path.startswith("/m/"):
            data = get_meeting(path[3:])
            if data is None:
                self._send(404, {"error": "meeting not found"})
            else:
                self._page(MEETING_PAGE_PATH, [
                    ("window.__MEETING_BOOT__ = null;",
                     "window.__MEETING_BOOT__ = %s;" % self._boot(data)),
                ])
            return
        if path == "/api/control/state":
            ctrl = self.ctx.get("control")
            if ctrl is None:
                self._send(200, {
                    "available": False,
                    "readonly": True,
                    "reason": "本实例未挂运行核心：传统桌面窗模式或纯回放服务，只能读取文本",
                })
            else:
                try:
                    self._send(200, {"available": True,
                                     "state": ctrl.handle("state").get("state", {})})
                except Exception as e:
                    self._send(500, {"available": True,
                                     "error": "control state failed: %s" % e})
            return
        if path.startswith("/api/meeting/"):
            data = get_meeting(path[len("/api/meeting/"):])
            if data is None:
                self._send(404, {"error": "meeting not found"})
            else:
                self._send(200, data)
            return
        self._send(404, {"error": "not found"})

    def _read_json_body(self):
        """返回 (body, None) 或 (None, (状态码, 消息))。"""
        if "application/json" not in self.headers.get("Content-Type", ""):
            return None, (415, "Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_PATCH_BYTES:
            return None, (413, "body must be 1..%d bytes" % MAX_PATCH_BYTES)
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")), None
        except (UnicodeDecodeError, ValueError):
            return None, (400, "invalid JSON")

    def _control_action(self):
        """控制面：动作转交给注入的 LiveCore，HTTP 层不认识任何引擎细节。"""
        ctrl = self.ctx.get("control")
        if ctrl is None:
            self._send(409, {
                "ok": False,
                "available": False,
                "error": "本实例没有运行核心（传统桌面窗模式或纯回放服务），控制按钮不可用",
            })
            return
        body, err = self._read_json_body()
        if err:
            self._send(err[0], {"ok": False, "error": err[1]})
            return
        if not isinstance(body, dict):
            self._send(400, {"ok": False, "error": "body must be a JSON object"})
            return
        action = body.get("action")
        if action not in ("state", "start", "stop", "configure"):
            self._send(400, {"ok": False,
                             "error": "action 只能是 state / start / stop / configure"})
            return
        try:
            reply = ctrl.handle(action, body.get("patch"))
        except Exception as e:
            self._send(500, {"ok": False,
                             "error": "control failed: %s: %s" % (type(e).__name__, e)})
            return
        self._send(200 if reply.get("ok") else 400, reply)

    def do_POST(self):
        if not self._host_ok():
            self._send(403, {"error": "host not allowed"})
            return
        if self._token_state() != "ok":
            self._send(403, {"error": "token required"})
            return
        path = urlparse(self.path).path
        if path == "/api/control/action":
            self._control_action()
            return
        if not path.startswith("/api/meeting/"):
            self._send(404, {"error": "not found"})
            return
        patch, err = self._read_json_body()
        if err:
            self._send(err[0], {"error": err[1]})
            return
        try:
            info = update_meeting(path[len("/api/meeting/"):], patch)
        except ValueError as e:
            self._send(400, {"error": str(e)})
            return
        except OSError as e:
            self._send(500, {"error": "meta write failed: %s" % e})
            return
        if info is None:
            self._send(404, {"error": "meeting not found"})
            return
        self._send(200, {"ok": True, "meeting": info})

    def _sse(self):
        bus = self.ctx["bus"]
        q = bus.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()
        try:
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.write(b"event: ready\ndata: {\"ok\":true}\n\n")
            for ev in bus.snapshot():
                self.wfile.write(("event: backfill\ndata: %s\n\n" %
                                  json.dumps(ev, ensure_ascii=False)).encode("utf-8"))
            self.wfile.flush()
            while not self.ctx["stop"].is_set():
                try:
                    ev = q.get(timeout=1.0)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                self.wfile.write(("event: segment\ndata: %s\n\n" %
                                  json.dumps(ev, ensure_ascii=False)).encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            bus.unsubscribe(q)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # Windows 的 SO_REUSEADDR 允许多个进程绑同一个 127.0.0.1:port，
    # 会让「占用则递增」探测永远不触发，浏览器随机连到旧实例。
    allow_reuse_address = False

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET,
                                       socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        super().server_bind()

    def handle_error(self, request, client_address):
        # SSE 客户端刷新/关闭标签页是正常断连，不要往控制台打 traceback
        if isinstance(sys.exc_info()[1], (ConnectionAbortedError,
                                          ConnectionResetError,
                                          BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class WebLiveServer:
    """旁路服务。端口独占绑定，占用则递增；端口只用于服务，不做单实例锁。"""

    def __init__(self, port=DEFAULT_PORT, host="127.0.0.1", write_discovery=True,
                 open_browser=False, archive=True, control=None):
        self.bus = EventBus()
        self.token = secrets.token_urlsafe(18)
        self.instance = hashlib.sha256(self.token.encode("utf-8")).hexdigest()[:8]
        self.stop_event = threading.Event()
        self.write_discovery = write_discovery
        self.httpd = None
        self.thread = None
        self._stopped = False
        self.archive_path = None
        self._archive_lock = threading.Lock()
        self._archive_closed = False
        if archive:
            try:
                self._init_archive()
            except OSError:
                self.archive_path = None  # 存档失败不影响字幕与页面
        self.meta_base = self._meeting_base()
        self._ctx = {"bus": self.bus, "token": self.token, "port": 0,
                     "stop": self.stop_event, "instance": self.instance,
                     "meta_base": self.meta_base, "archive_path": self.archive_path,
                     "control": control}
        self.control = control
        candidates = list(range(port, port + 8)) + [0] if port else [0]
        last_err = None
        for p in candidates:
            try:
                self.httpd = _Server((host, p), partial(_Handler, self._ctx))
                break
            except OSError as e:
                last_err = e
        if self.httpd is None:
            raise RuntimeError("无法绑定本地端口: %s" % last_err)
        self.port = self.httpd.server_address[1]
        self._ctx["port"] = self.port
        self.url = "http://127.0.0.1:%d/?token=%s" % (self.port, self.token)
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       kwargs={"poll_interval": 0.2}, daemon=True)
        self.thread.start()
        if write_discovery:
            self._write_discovery()
        atexit.register(self.stop)
        if open_browser:
            threading.Thread(target=self._open_browser, args=(self.url,),
                             daemon=True).start()

    @property
    def meta(self):
        return live_meta(self._ctx)

    @property
    def meeting_no(self):
        return self.meta.get("no")

    @staticmethod
    def _open_browser(url):
        time.sleep(0.4)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def _init_archive(self):
        """按日期建一级目录，ID（日期+时间）为唯一文件名；同秒多实例则顺延秒数。"""
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        mid = self.bus.meeting_id
        date = id_date(mid)
        day_dir = os.path.join(ARCHIVE_DIR, date)
        os.makedirs(day_dir, exist_ok=True)
        path = os.path.join(day_dir, mid + ".md")
        for _ in range(60):
            if not os.path.exists(path):
                break
            mid = (datetime.strptime(mid, "%Y%m%d_%H%M%S") +
                   timedelta(seconds=1)).strftime("%Y%m%d_%H%M%S")
            date = id_date(mid)
            day_dir = os.path.join(ARCHIVE_DIR, date)
            os.makedirs(day_dir, exist_ok=True)
            path = os.path.join(day_dir, mid + ".md")
        else:
            raise OSError("同一秒内会议过多，无法分配唯一 ID")
        self.bus.meeting_id = mid
        self.archive_path = path
        head = [
            "---",
            "meeting_id: %s" % mid,
            "date: %s" % date,
            "started_at: %s" % self.bus.started_at,
            "source: local ASR (offline, sherpa-onnx)",
            "translation: Argos offline machine translation (not an LLM)",
            "# 题目与星标见同目录 %s.meta.json；本文件只追加事实源，不回写" % mid,
            "---",
            "",
            "# %s" % mid,
            "",
            "逐段追加，随转写实时更新；可用 Typora / Obsidian / VSCode 打开，也可整份丢给 AI 客户端分析。",
            "译文行以 > 开头，不是原文，仅供参考。未定稿片段不写入。",
            "",
        ]
        with open(self.archive_path, "w", encoding="utf-8") as f:
            f.write("\n".join(head) + "\n")  # 多留一个空行，说明段与第一段不粘在一起
        _write_meta(meta_path_for(self.archive_path), {
            "id": mid,
            "date": date,
            "started_at": self.bus.started_at,
            "title": "",
            "star": False,
        })

    def _meeting_base(self):
        if not self.archive_path:
            return {}
        return {
            "id": self.bus.meeting_id,
            "date": id_date(self.bus.meeting_id),
            "display": self.bus.started_at.replace("T", " "),
            "started_at": self.bus.started_at,
            "archive": _rel(self.archive_path),
            "url": "/m/%s" % self.bus.meeting_id,
        }

    def meeting_line(self):
        m = self.meta
        if not m.get("archive"):
            return "本次未开启会议存档（--no-archive）"
        return "会议 %s ｜ ID %s ｜ 开始 %s ｜ 存档 %s" % (
            m["label"], m["id"], m["display"], m["archive"])

    def _archive_append(self, ev):
        if not self.archive_path or ev["kind"] == "part":
            return
        rel = " +%ss" % ev["rel"] if ev["rel"] is not None else ""
        if ev["kind"] == "trans":
            line = "> [%s%s] 译 %s\n\n" % (ev["ts"], rel, ev["text"])
        else:
            line = "**[%s%s]** %s\n\n" % (ev["ts"], rel, ev["text"])
        with self._archive_lock:
            try:
                with open(self.archive_path, "a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
            except OSError:
                pass

    def _archive_close(self):
        if not self.archive_path or self._archive_closed:
            return
        self._archive_closed = True
        ended = datetime.now().isoformat(timespec="seconds")
        n = len(self.bus.snapshot())
        with self._archive_lock:
            try:
                with open(self.archive_path, "a", encoding="utf-8") as f:
                    f.write("<!-- ended_at: %s ; facts: %d -->\n" % (ended, n))
                path = meta_path_for(self.archive_path)
                meta = _read_meta(path)
                meta["ended_at"] = ended
                meta["segments"] = n
                _write_meta(path, meta)
            except OSError:
                pass

    def _write_discovery(self):
        data = {
            "url": self.url,
            "port": self.port,
            "token": self.token,
            "instance": self.instance,
            "pid": os.getpid(),
            "started_at": self.bus.started_at,
            "version": VERSION,
        }
        try:
            with open(DISCOVERY_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Windows 双击即开，避免从控制台手抄 token（1/l/I 与 _/-/. 极易看错）
            with open(SHORTCUT_PATH, "w", encoding="utf-8") as f:
                f.write("[InternetShortcut]\nURL=%s\n" % self.url)
        except OSError:
            pass

    def publish(self, kind, text, ts=None, rel=None, source="asr"):
        ev = self.bus.publish(kind, text, ts=ts, rel=rel, source=source)
        self._archive_append(ev)
        return ev

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self._archive_close()
        self.stop_event.set()
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.write_discovery and os.path.exists(DISCOVERY_PATH):
            try:
                with open(DISCOVERY_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("token") == self.token:
                    os.remove(DISCOVERY_PATH)
            except (OSError, ValueError):
                pass
        if self.write_discovery and os.path.exists(SHORTCUT_PATH):
            try:
                with open(SHORTCUT_PATH, "r", encoding="utf-8") as f:
                    owns = self.token in f.read()
                if owns:
                    # 不删文件：.url 在部分 Windows 环境无法移入回收站。
                    # 覆写成不含 token 的失效标记，下次启动会覆盖成新地址。
                    with open(SHORTCUT_PATH, "w", encoding="utf-8") as f:
                        f.write("; 实例已结束，token 已失效；重新启动会写入新地址。\n"
                                "[InternetShortcut]\n"
                                "URL=http://127.0.0.1:%d/health\n" % self.port)
            except OSError:
                pass

    def summary(self):
        return "端口 %d ｜ 实例指纹 %s ｜ 只绑 127.0.0.1 ｜ 文本不出本机 ｜ 未接任何模型" % (
            self.port, self.instance)


def start(port=DEFAULT_PORT, write_discovery=True, open_browser=False,
          archive=True, control=None):
    return WebLiveServer(port=port, write_discovery=write_discovery,
                         open_browser=open_browser, archive=archive,
                         control=control)


LINE_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})(?:\s+\+(\d+)s)?\]\s*(.*)$")


def replay_file(srv, path, speed=20.0, min_gap=0.05):
    """把既有 transcript 按 +Ns 相对秒压缩回放；用于无音频跑通与回归。"""
    count = 0
    last_rel = None
    with open(path, "r", encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            m = LINE_RE.match(line)
            if not m:
                continue
            ts, rel_s, text = m.group(1), m.group(2), m.group(3)
            rel = int(rel_s) if rel_s is not None else None
            is_trans = text.startswith("译")
            if is_trans:
                text = re.sub(r"^译\s*", "", text)
            kind = "trans" if is_trans else "final"
            if last_rel is not None and rel is not None and speed > 0:
                time.sleep(min(max(0, rel - last_rel) / speed, 2.0))
            else:
                time.sleep(min_gap)
            srv.publish(kind, text, ts=ts, rel=rel,
                        source="argos" if is_trans else "replay")
            if rel is not None:
                last_rel = rel
            count += 1
    return count


def _get(url, headers=None, timeout=4):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _post(url, data, headers=None, timeout=4):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def run_self_test():
    """端到端自检：防线、会议对象、按日期归组、题目 CRUD、star、历史页、迁移、SSE、导出、清理。"""
    import tempfile
    global ARCHIVE_DIR, DISCOVERY_PATH, SHORTCUT_PATH
    # 三个落盘位置全部隔离到临时目录：自检默认 write_discovery=True，
    # 若指向项目根，会覆盖并在停止时删掉正在运行的服务的 web_live.json（I-064）。
    saved = (ARCHIVE_DIR, DISCOVERY_PATH, SHORTCUT_PATH)
    tmp_root = tempfile.mkdtemp(prefix="whisper_web_live_")
    ARCHIVE_DIR = os.path.join(tmp_root, "meetings")
    DISCOVERY_PATH = os.path.join(tmp_root, "web_live.json")
    SHORTCUT_PATH = os.path.join(tmp_root, "open_live.url")
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                             ("  -> " + detail) if detail else ""))

    srv = WebLiveServer(port=0)
    base = "http://127.0.0.1:%d" % srv.port
    try:
        code, body = _get(base + "/health")
        check("health 200 且 ok=true", code == 200 and '"ok": true' in body, body.strip()[:120])
        check("health 带实例指纹且不泄露 token",
              json.loads(body).get("instance") == srv.instance and srv.token not in body,
              "instance=%s" % srv.instance)

        code, body = _get(base + "/health", headers={"Host": "evil.example.com"})
        check("伪造 Host 被拒 (DNS rebinding 防线)", code == 403, "status=%d" % code)

        code, body = _get(base + "/transcript.json?token=wrong")
        check("错误 token 被拒", code == 403, "status=%d" % code)

        code, body = _get(base + "/transcript.json")
        check("无 token 被拒", code == 403, "status=%d" % code)

        srv.publish("final", "不该出现在错误页的原文", ts="14:43:20", rel=15)
        code, body = _get(base + "/?token=wrong")
        check("token 不匹配返回可读引导页且不泄露事实源",
              code == 403 and "连到了另一个实例" in body and "不该出现在错误页的原文" not in body
              and srv.token not in body, "status=%d" % code)
        code, body = _get(base + "/")
        check("无 token 同样返回引导页且标注 missing",
              code == 403 and '"state": "missing"' in body, "status=%d" % code)

        srv2 = WebLiveServer(port=srv.port, write_discovery=False, archive=False)
        try:
            check("同端口第二次启动不共用端口（Windows SO_REUSEADDR 劫持防线）",
                  srv2.port != srv.port, "port1=%d port2=%d" % (srv.port, srv2.port))
        finally:
            srv2.stop()

        srv.publish("final", "第一句原文", ts="14:43:24", rel=20)
        srv.publish("part", "这句还没定稿", ts="14:43:25")
        srv.publish("trans", "First sentence", ts="14:43:29", rel=25)
        code, body = _get(base + "/transcript.json?token=" + srv.token)
        data = json.loads(body)
        kinds = [e["kind"] for e in data["segments"]]
        check("事实源只含 final+trans，part 不进入",
              code == 200 and kinds == ["final", "final", "trans"], "kinds=%s" % kinds)
        check("译文标注 Argos 来源",
              any(e.get("source") == "argos" for e in data["segments"]), "")
        check("快照文本不含未定稿片段",
              "还没定稿" not in data["text"], "")

        code, body = _get(base + "/?token=" + srv.token)
        check("live 页面 200 且首屏注入事实源",
              code == 200 and 'id="segments"' in body and "第一句原文" in body,
              "status=%d" % code)

        code, body = _get(base + "/transcript.md?token=" + srv.token)
        check("Markdown 导出含原文与译文来源声明",
              code == 200 and "第一句原文" in body and "Argos" in body, "status=%d" % code)

        sse_result = queue.Queue()

        def reader():
            try:
                req = urllib.request.Request(base + "/events?token=" + srv.token,
                                             headers={"Accept": "text/event-stream"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    lines = []
                    deadline = time.time() + 4
                    while time.time() < deadline:
                        line = r.readline().decode("utf-8", "replace").strip()
                        if line:
                            lines.append(line)
                            if "SSE 自检段落" in line:
                                break
                    sse_result.put("\n".join(lines))
            except Exception as e:
                sse_result.put("ERROR: %s" % e)

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        time.sleep(0.3)
        srv.publish("final", "SSE 自检段落", ts="14:44:00", rel=56)
        try:
            sse_text = sse_result.get(timeout=6)
        except queue.Empty:
            sse_text = "ERROR: timeout"
        check("SSE 推送增量段与历史补发",
              "SSE 自检段落" in sse_text and "backfill" in sse_text,
              sse_text.replace("\n", " | ")[:160])

        meta = srv.meta
        mid = meta["id"]
        date = meta["date"]
        check("会议有稳定 ID（日期+时间）与日期分组",
              bool(ID_RE.match(mid)) and bool(DATE_DIR_RE.match(date)),
              "id=%s date=%s" % (mid, date))
        check("按日期归组的一级目录与二级文件名",
              os.path.basename(os.path.dirname(srv.archive_path)) == date and
              os.path.basename(srv.archive_path) == mid + ".md",
              os.path.basename(srv.archive_path))
        check("组内展示序号 label = 日期 #n",
              meta["label"] == "%s #1" % date and meta["no"] == 1,
              "label=%s" % meta["label"])
        check("同目录 .meta.json 存在且带空题目/未标星",
              os.path.exists(meta_path_for(srv.archive_path)) and
              meta["title"] == "" and meta["star"] is False, "")
        check("health 与 transcript.json 带同一会议 meta",
              json.loads(_get(base + "/health")[1])["meeting"]["id"] == mid and
              json.loads(_get(base + "/transcript.json?token=" + srv.token)[1])["meeting"]["no"] == 1,
              "")
        code, body = _get(base + "/?token=" + srv.token)
        check("页面首屏注入会议标识（含日期 #n）",
              code == 200 and "window.__WHISPER_MEETING__" in body
              and '"id": "%s"' % mid in body and '"label": "%s #1"' % date in body,
              "status=%d" % code)
        code, body = _get(base + "/transcript.md?token=" + srv.token)
        check("Markdown 导出带 meeting_id 与日期标签",
              code == 200 and "meeting_id: %s" % mid in body
              and "meeting_label: %s #1" % date in body, "status=%d" % code)
        with open(srv.archive_path, encoding="utf-8") as f:
            arc = f.read()
        check("事实源 md 逐段 append、part 不进入、注明 meta 位置",
              "meeting_id: %s" % mid in arc and "第一句原文" in arc
              and "First sentence" in arc and "还没定稿" not in arc
              and ".meta.json" in arc, os.path.basename(srv.archive_path))

        # 同一天第二场：编号 #2 且 ID 不冲突
        srv_2nd = WebLiveServer(port=0, write_discovery=False)
        try:
            check("同日第二场自动得 #2 且唯一 ID 不同",
                  srv_2nd.meta["no"] == 2 and srv_2nd.meta["id"] != mid,
                  "label=%s id=%s" % (srv_2nd.meta["label"], srv_2nd.meta["id"]))
        finally:
            srv_2nd.stop()

        # 历史列表：按日期分组、同源编号
        code, body = _get(base + "/meetings.json?token=" + srv.token)
        listing = json.loads(body)
        check("历史列表按日期分组且编号与页面同源",
              code == 200 and listing["total"] == 2
              and listing["groups"][0]["date"] == date
              and listing["groups"][0]["meetings"][0]["label"] == "%s #1" % date,
              "total=%d" % listing["total"])
        code, body = _get(base + "/history?token=" + srv.token)
        check("历史页 200 且首屏注入分组数据",
              code == 200 and "window.__HISTORY_BOOT__" in body and mid in body,
              "status=%d" % code)

        # 题目增删改查 + star
        api = base + "/api/meeting/" + mid + "?token=" + srv.token
        code, body = _post(api, {"title": "产品方向评审"})
        check("题目「增」：POST 写入并回读", 
              code == 200 and json.loads(body)["meeting"]["title"] == "产品方向评审"
              and json.loads(_get(api)[1])["meeting"]["title"] == "产品方向评审",
              "status=%d" % code)
        code, body = _post(api, {"title": "评审（已修订）", "star": True})
        check("题目「改」与 star 标记",
              code == 200 and json.loads(body)["meeting"]["title"] == "评审（已修订）"
              and json.loads(body)["meeting"]["star"] is True, "status=%d" % code)
        code, body = _post(api, {"title": ""})
        check("题目「删」：清空题目，星标保留、文件不删",
              code == 200 and json.loads(body)["meeting"]["title"] == ""
              and json.loads(body)["meeting"]["star"] is True
              and os.path.exists(srv.archive_path), "status=%d" % code)
        code, body = _get(base + "/transcript.md?token=" + srv.token)
        check("导出随题目清空同步去掉 title 字段",
              code == 200 and "title:" not in body, "status=%d" % code)
        code, body = _post(api, {"title": "最终题目"})
        check("题目「查」：历史列表可检索到",
              code == 200 and "最终题目" in _get(base + "/meetings.json?token=" + srv.token)[1],
              "status=%d" % code)
        code, body = _post(api, {"oops": 1})
        check("非法字段被拒 400", code == 400, "status=%d" % code)
        code, body = _post(api, {"star": "yes"})
        check("star 类型错误被拒 400", code == 400, "status=%d" % code)
        code, body = _post(base + "/api/meeting/" + mid, {"title": "x"})
        check("无 token 的 POST 被拒 403", code == 403, "status=%d" % code)
        code, body = _get(base + "/api/meeting/19990101_000000?token=" + srv.token)
        check("不存在的会议返回 404", code == 404, "status=%d" % code)

        # 单场页：首屏注入全文，供复现与 AI 插件读 DOM
        code, body = _get(base + "/m/" + mid + "?token=" + srv.token)
        check("单场会议页首屏注入全文与会议标识",
              code == 200 and "window.__MEETING_BOOT__" in body
              and "第一句原文" in body and "最终题目" in body, "status=%d" % code)
        code, body = _get(base + "/m/" + mid + ".md?token=" + srv.token)
        check("单场原始 Markdown 可下载",
              code == 200 and "第一句原文" in body, "status=%d" % code)
        code, body = _get(base + "/api/meeting/" + mid + "?token=" + srv.token)
        detail = json.loads(body)
        check("单场 JSON 结构化段数与事实源一致",
              code == 200 and len(detail["segments"]) == 4
              and detail["meeting"]["segments"] == 4
              and detail["meeting"]["title"] == "最终题目",
              "segments=%d" % len(detail["segments"]))

        # legacy 识别与显式迁移
        legacy_id = "20260101_090000"
        legacy_path = os.path.join(ARCHIVE_DIR, "0001_%s.md" % legacy_id)
        with open(legacy_path, "w", encoding="utf-8") as f:
            f.write("---\nmeeting_id: %s\n---\n\n**[09:00:00]** 旧格式的一段\n" % legacy_id)
        before = json.loads(_get(base + "/meetings.json?token=" + srv.token)[1])
        check("旧扁平存档自动识别为 legacy 且按日期归组",
              before["total"] == 3 and before["legacy"] == 1
              and any(m["id"] == legacy_id for g in before["groups"]
                      for m in g["meetings"] if m["legacy"]),
              "total=%d legacy=%d" % (before["total"], before["legacy"]))
        dry = migrate_archives(dry_run=True)
        check("--dry-run 不改动文件",
              legacy_id in dry["planned"] and os.path.exists(legacy_path), "")
        moved = migrate_archives()
        after = json.loads(_get(base + "/meetings.json?token=" + srv.token)[1])
        check("迁移后文件进入日期目录、内容不丢、列表不再有 legacy",
              legacy_id in moved["moved"]
              and os.path.exists(os.path.join(ARCHIVE_DIR, "2026-01-01", legacy_id + ".md"))
              and not os.path.exists(legacy_path)
              and after["total"] == 3 and after["legacy"] == 0
              and "旧格式的一段" in open(
                  os.path.join(ARCHIVE_DIR, "2026-01-01", legacy_id + ".md"),
                  encoding="utf-8").read(),
              "moved=%s" % moved["moved"])

        check("发现文件写入且 token 一致",
              os.path.exists(DISCOVERY_PATH) and
              json.load(open(DISCOVERY_PATH, encoding="utf-8")).get("token") == srv.token, "")
        check("双击快捷方式写入且含当前 token",
              os.path.exists(SHORTCUT_PATH) and
              srv.token in open(SHORTCUT_PATH, encoding="utf-8").read(), "")
    finally:
        srv.stop()
    check("停止后发现文件按 token 归属清除", not os.path.exists(DISCOVERY_PATH), "")
    check("停止后快捷方式失效化且不再含 token",
          os.path.exists(SHORTCUT_PATH) and
          srv.token not in open(SHORTCUT_PATH, encoding="utf-8").read(), "")
    with open(srv.archive_path, encoding="utf-8") as f:
        arc_end = f.read()
    check("停止时存档写入结束标记与事实源段数", "ended_at" in arc_end, "")
    end_meta = _read_meta(meta_path_for(srv.archive_path))
    check("停止后 meta 保留题目/star 并写入 ended_at",
          end_meta.get("title") == "最终题目" and end_meta.get("star") is True
          and bool(end_meta.get("ended_at")), "title=%s" % end_meta.get("title"))
    try:
        for root, dirs, files in os.walk(tmp_root, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(tmp_root)
    except OSError:
        pass
    ARCHIVE_DIR, DISCOVERY_PATH, SHORTCUT_PATH = saved

    # ---- 控制面（I-068）：未挂核心时明确只读；挂了核心时动作真影响状态 ----
    ro = WebLiveServer(port=0, write_discovery=False, archive=False)
    rb = "http://127.0.0.1:%d" % ro.port
    try:
        code, body = _get(rb + "/api/control/state?token=" + ro.token)
        check("未挂运行核心时控制 state 返回只读说明",
              code == 200 and json.loads(body).get("available") is False
              and json.loads(body).get("readonly") is True, "status=%d" % code)
        code, body = _post(rb + "/api/control/action?token=" + ro.token,
                           {"action": "start"})
        check("未挂运行核心时控制动作被拒且不假装成功",
              code == 409 and json.loads(body).get("ok") is False, "status=%d" % code)
        code, body = _get(rb + "/api/control/state")
        check("控制 state 也需要 token", code == 403, "status=%d" % code)
        code, body = _get(rb + "/health")
        check("health 标明本实例是否有控制面",
              json.loads(body).get("control") is False, body.strip()[:100])
    finally:
        ro.stop()

    import live_core
    launched = []

    def fake_runner(engine):
        def run(args, stop, res_q, level):
            launched.append(engine)
            res_q.put(("final", "控制面自检段落"))
            while not stop.is_set():
                if stop.wait(0.05):
                    break
        return run

    core = live_core.LiveCore(pipeline_factory=fake_runner,
                              translator=lambda t: "translated: " + t)
    cs = WebLiveServer(port=0, write_discovery=False, archive=False, control=core)
    core.web = cs   # 事件走与控制端点同一个服务实例
    cb = "http://127.0.0.1:%d" % cs.port
    try:
        code, body = _get(cb + "/api/control/state?token=" + cs.token)
        st = json.loads(body)
        check("挂了运行核心时 state 返回可用状态",
              code == 200 and st.get("available") is True
              and st["state"]["running"] is False
              and st["state"]["engine"] == "sensevoice", "status=%d" % code)
        code, body = _post(cb + "/api/control/action?token=" + cs.token,
                           {"action": "start"})
        check("POST start 真的启动核心并回running=true",
              code == 200 and json.loads(body)["state"]["running"] is True
              and launched == ["sensevoice"], "launched=%s" % launched)
        code, body = _post(cb + "/api/control/action?token=" + cs.token,
                           {"action": "configure", "patch": {"engine": "zipformer"}})
        check("换引擎自动重启 pipeline 且通话不中断",
              code == 200 and json.loads(body)["state"]["engine"] == "zipformer"
              and json.loads(body)["state"]["running"] is True
              and launched[-1] == "zipformer" and len(launched) >= 2,
              "launched=%s" % launched)
        code, body = _post(cb + "/api/control/action?token=" + cs.token,
                           {"action": "configure", "patch": {"engine": "nope"}})
        check("非法引擎被拒绝且不改状态", code == 400
              and json.loads(body).get("ok") is False
              and json.loads(body)["state"]["engine"] == "zipformer", "status=%d" % code)
        code, body = _post(cb + "/api/control/action?token=" + cs.token,
                           {"action": "configure",
                            "patch": {"source": "mic", "translate": False}})
        check("音源与翻译开关写入状态",
              json.loads(body)["state"]["source"] == "mic"
              and json.loads(body)["state"]["translate"] is False, "")
        code, body = _post(cb + "/api/control/action?token=" + cs.token,
                           {"action": "bogus"})
        check("未知动作被拒", code == 400 and json.loads(body).get("ok") is False,
              "status=%d" % code)
        code, body = _post(cb + "/api/control/action?token=" + cs.token,
                           {"action": "stop"})
        check("POST stop 真的停止核心", code == 200
              and json.loads(body)["state"]["running"] is False, "status=%d" % code)
        code, body = _get(cb + "/health")
        check("health 标明控制面可用", json.loads(body).get("control") is True, "")
        arrived = False
        for _ in range(40):   # 等真实事件穿过 queue 消费循环，不伪造结果
            if any(e["text"] == "控制面自检段落" for e in cs.bus.snapshot()):
                arrived = True
                break
            time.sleep(0.05)
        code, body = _get(cb + "/transcript.json?token=" + cs.token)
        check("控制面启动的事件真的发布到事实源",
              arrived and "控制面自检段落" in json.loads(body).get("text", ""),
              "text=%s" % json.loads(body).get("text", "")[:60])
    finally:
        cs.stop()
        core.close()

    failed = [r for r in results if not r[1]]
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(EVIDENCE_DIR, "self_test_%s.txt" % stamp)
    with open(path, "w", encoding="utf-8") as f:
        f.write("whisper web live --self-test  %s\n" % datetime.now().isoformat(timespec="seconds"))
        f.write("python: %s\n" % sys.version.split()[0])
        f.write("port: %d (动态)\n\n" % srv.port)
        for name, ok, detail in results:
            f.write("[%s] %s  %s\n" % ("PASS" if ok else "FAIL", name, detail))
        f.write("\n%d/%d passed\n" % (len(results) - len(failed), len(results)))
    print("\n%d/%d passed -> %s" % (len(results) - len(failed), len(results), path))
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(description="whisper 本地信息源旁路层（纯标准库）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="起始端口，占用则递增，最后回退动态端口")
    ap.add_argument("--replay", default=None, help="回放既有 transcript 文件（无需音频设备）")
    ap.add_argument("--speed", type=float, default=20.0, help="回放加速倍数，默认 20")
    ap.add_argument("--self-test", action="store_true", help="端到端自检并写证据")
    ap.add_argument("--no-discovery", action="store_true", help="不写 web_live.json 与双击快捷方式")
    ap.add_argument("--no-open", action="store_true", help="不要自动打开浏览器")
    ap.add_argument("--no-archive", action="store_true", help="不写 meetings/ 会议存档")
    ap.add_argument("--migrate-archives", action="store_true",
                    help="把旧扁平 meetings/<no>_<id>.md 迁移到 <date>/<id>.md，迁移后退出")
    ap.add_argument("--dry-run", action="store_true", help="配合 --migrate-archives 只打印计划")
    args = ap.parse_args()
    if args.self_test:
        return run_self_test()
    if args.migrate_archives:
        r = migrate_archives(dry_run=args.dry_run)
        verb = "计划迁移" if args.dry_run else "已迁移"
        print("%s %d 场：%s" % (verb, len(r["moved"] or r["planned"]),
                               ", ".join(r["moved"] or r["planned"]) or "无"))
        if r["conflicts"]:
            print("目标文件已存在、保持不动：%s" % ", ".join(r["conflicts"]))
        print("原事实源内容不会被修改；冲突文件请手动核对后再处理。")
        return 0
    srv = start(port=args.port, write_discovery=not args.no_discovery,
                open_browser=not args.no_open, archive=not args.no_archive)
    print("web live 已启动：%s" % srv.url)
    print(srv.summary())
    print(srv.meeting_line())
    print("历史会议：http://127.0.0.1:%d/history?token=%s" % (srv.port, srv.token))
    if args.no_open:
        print("请完整复制上面的 URL 到浏览器，不要照着屏幕手敲 token。")
    elif not args.no_discovery:
        print("已在默认浏览器打开；若没弹出，双击 %s" % SHORTCUT_PATH)
    print("扩展也用上面这条 URL 配置。Ctrl+C 结束。")
    if args.replay:
        n = replay_file(srv, args.replay, speed=args.speed)
        print("回放完成：%d 段（来源 %s，加速 %.0f 倍）" % (n, args.replay, args.speed))
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n正在停止…")
    finally:
        srv.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
