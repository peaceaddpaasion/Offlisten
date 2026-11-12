# -*- coding: utf-8 -*-
"""
轻量悬浮字幕（I-067 / I-068）。只在 `live --headless --overlay` 时加载。

与 SubtitleApp 的区别：这里只有两行文字，没有控制条、历史区、设置行、托盘。
tkinter 必须在主线程，所以由 run_headless 把主线程交给 run()；采集、识别、
HTTP 服务、运行核心消费循环全在后台线程。浮层关闭即结束整个进程。
"""
import queue


class Overlay:
    def __init__(self):
        self.q = queue.Queue()
        self.root = None
        self.final_lb = None
        self.trans_lb = None

    def push(self, kind, text):
        """后台线程调用；只入队，绝不碰 tkinter 控件。"""
        self.q.put((kind, text))

    def run(self):
        import tkinter as tk
        root = tk.Tk()
        self.root = root
        root.title("本地转写 · 悬浮字幕")
        root.attributes("-topmost", True)
        root.overrideredirect(True)
        root.configure(bg="#101418")

        width = max(480, root.winfo_screenwidth() - 80)
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        frame = tk.Frame(root, bg="#101418", padx=14, pady=8)
        frame.pack(fill="x")

        self.final_lb = tk.Label(frame, text="等待转写", anchor="w", justify="left",
                                 bg="#101418", fg="#f2f4f6", wraplength=width - 28,
                                 font=("Microsoft YaHei", 18))
        self.final_lb.pack(fill="x")
        self.trans_lb = tk.Label(frame, text="", anchor="w", justify="left",
                                 bg="#101418", fg="#b9c0c7", wraplength=width - 28,
                                 font=("Microsoft YaHei", 14))
        self.trans_lb.pack(fill="x")

        root.update_idletasks()
        h = frame.winfo_reqheight()
        root.geometry("%dx%d+%d+%d" % (width, h, (sw - width) // 2, sh - h - 48))

        def close(_event=None):
            root.quit()
            root.destroy()

        root.bind("<Escape>", close)
        root.bind("<Button-3>", close)

        def tick():
            last = None
            for _ in range(50):
                try:
                    last = self.q.get_nowait()
                except queue.Empty:
                    break
            if last is not None:
                # 一次 tick 内只呈现最终状态，避免中间态闪字
                kind, text = last
                if kind == "final":
                    self.final_lb.config(text=text, fg="#f2f4f6")
                    self.trans_lb.config(text="")
                elif kind == "part":
                    self.final_lb.config(text=text, fg="#9aa0a6")
                    self.trans_lb.config(text="")
                elif kind == "trans":
                    self.trans_lb.config(text="译 " + text)
            root.after(100, tick)

        root.after(100, tick)
        root.mainloop()
