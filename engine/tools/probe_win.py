# -*- coding: utf-8 -*-
"""精确取证：只截应用窗口矩形，放大 2 倍，剔除背后视频干扰。"""
import sys
sys.argv = ["x", "live"]
import tkinter as tk
from PIL import ImageGrab
import pc_transcriber as pt

class A: pass
a = A()
a.source, a.engine, a.device, a.save = "loopback", "sensevoice", None, None
a.no_translate, a.model_dir = False, pt.MODEL_DIR

def snap():
    x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
    w, h = app.root.winfo_width(), app.root.winfo_height()
    im = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    im.resize((w * 2, h * 2)).save("win_probe.png")
    print("window rect:", x, y, w, h)

seq = [
    (6,  lambda: (app.cfg.__setitem__("bg", "CLEAR"), app.apply_look(), app.set_width(70),
                  app.ui_q.put(("final", "所以你真的需要算的就只有E的-2分之Y次方，对吧？")))),
    (9,  lambda: app.ui_q.put(("trans", "所以你真正需要计算的就是 E^(-2/Y)，对吧？"))),
    (12, lambda: snap()),
    (14, lambda: app.stop.set()),
    (16, lambda: app.quit_all()),
]
orig = tk.Tk.mainloop
def patched(self, *args2):
    for t, fn in seq:
        self.after(int(t * 1000), fn)
    return orig(self, *args2)
tk.Tk.mainloop = patched

app = pt.SubtitleApp(a)
app.root.mainloop()
print("PROBE OK")
