# -*- coding: utf-8 -*-
"""模式往返压测：浮层→极简→浮层→黑色，字幕标签必须始终在位。"""
import sys
sys.argv = ["x", "live"]
import tkinter as tk
import pc_transcriber as pt

class A: pass
a = A()
a.source, a.engine, a.device, a.save = "loopback", "sensevoice", None, None
a.no_translate, a.model_dir = False, pt.MODEL_DIR

def check(tag):
    fm = app.final_lb.winfo_manager()
    tm = app.trans_lb.winfo_manager()
    print(f"[{tag}] bg={app.cfg['bg']} final={fm or '未打包'} trans={tm or '未打包'}", flush=True)
    if app.cfg["bg"] != "OVERLAY":
        assert fm and tm, f"{tag}: 非浮层模式下字幕标签丢失！ bg={app.cfg['bg']}"

seq = [
    (6,  lambda: (app.cfg.__setitem__("bg", "OVERLAY"), app.apply_look(), check("浮层"))),
    (8,  lambda: app.toggle_slim()),          # 极简开 = SLIM_LIGHT
    (9,  lambda: check("极简(浅底板)")),
    (11, lambda: app.toggle_slim()),          # 极简关
    (12, lambda: check("极简关")),
    (14, lambda: app.toggle_slim()),          # 再开（此时 prev=OVERLAY 路径）
    (15, lambda: check("极简再开")),
    (17, lambda: app.toggle_slim()),
    (18, lambda: check("再关")),
    (20, lambda: app.stop.set()),
    (22, lambda: app.quit_all()),
]
orig = tk.Tk.mainloop
def patched(self, *args2):
    for t, fn in seq:
        self.after(int(t * 1000), fn)
    return orig(self, *args2)
tk.Tk.mainloop = patched

app = pt.SubtitleApp(a)
app.root.mainloop()
print("MODE SWITCH OK")
