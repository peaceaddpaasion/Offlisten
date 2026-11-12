# -*- coding: utf-8 -*-
"""复现用户操作：背景键连按扫过全部档位×3圈，每步断言不变量。"""
import sys
sys.argv = ["x", "live"]
import tkinter as tk
import pc_transcriber as pt

class A: pass
a = A()
a.source, a.engine, a.device, a.save = "loopback", "sensevoice", None, None
a.no_translate, a.model_dir = False, pt.MODEL_DIR

errors = []

def check(tag):
    bg = app.cfg["bg"]
    overlay = bg == "OVERLAY"
    lb = bool(app.final_lb.winfo_manager())
    cv = bool(app.canvas.winfo_manager()) if getattr(app, "canvas", None) else False
    pw = getattr(app, "plate_win", None) is not None
    if overlay:
        if lb: errors.append(f"{tag}: 浮层下标签未收起")
        if not cv: errors.append(f"{tag}: 浮层下画布未显示")
        if not pw: errors.append(f"{tag}: 浮层下底板窗丢失")
    else:
        if not lb: errors.append(f"{tag}: 非浮层下字幕标签丢失!")
        if cv: errors.append(f"{tag}: 非浮层下画布残留")
        if pw: errors.append(f"{tag}: 非浮层下底板窗残留")
    # 文字同步：非浮层下标签文字应等于画布文字（离开浮层时回填）
    if not overlay and cv is False and getattr(app, "canvas", None):
        pass

seq = [
    (5,  lambda: app.ui_q.put(("final", "恒定文字串：检查模式切换不丢字。"))),
]
# 3 圈 × 每 0.4s 一档
t = 6
for loop in range(3):
    for name, val in pt.BACKGROUNDS:
        seq.append((t, (lambda v=val, n=name, tt=t:
                        (app.cfg.__setitem__("bg", v), app.apply_look(),
                         check(f"L{loop} {n}")))))
        t += 1  # 实际间隔在下方统一改
# 重新编排：0.5s 一步
seq = [(5, lambda: app.ui_q.put(("final", "恒定文字串：检查模式切换不丢字。")))]
t = 6
for loop in range(3):
    for name, val in pt.BACKGROUNDS:
        seq.append((round(t, 1), (lambda v=val, n=name:
                    (app.cfg.__setitem__("bg", v), app.apply_look(),
                     check(f"L{loop}-{n}")))))
        t += 0.5
seq.append((round(t + 1, 1), lambda: print("ERRORS:", len(errors), flush=True) or errors))
seq.append((round(t + 2, 1), lambda: app.stop.set()))
seq.append((round(t + 3, 1), lambda: app.quit_all()))

orig = tk.Tk.mainloop
def patched(self, *args2):
    for tt, fn in seq:
        self.after(int(tt * 1000), fn)
    return orig(self, *args2)
tk.Tk.mainloop = patched

app = pt.SubtitleApp(a)
app.root.mainloop()
print("CYCLE STRESS DONE")
