# -*- coding: utf-8 -*-
"""Win32 分层窗浮层：UpdateLayeredWindow 真·逐像素 alpha。

底板半透明是真实的（每像素 alpha 与屏幕合成），文字用 PIL 描边渲染、全实锐利。
拖动 = WM_NCLBUTTONDOWN/HTCAPTION 原生拖拽。进程退出/窗口销毁自动清理。
"""
import ctypes
import threading
import numpy as np
from PIL import Image, ImageDraw, ImageFont

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_LBUTTONDOWN = 0x0201
WM_NCLBUTTONDOWN = 0x00A1
HTCAPTION = 2
ULW_ALPHA = 2
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1

LRESULT = ctypes.c_ssize_t

WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_uint, WPARAM, LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", ctypes.c_void_p), ("hIcon", ctypes.c_void_p),
                ("hCursor", ctypes.c_void_p), ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", ctypes.c_wchar_p), ("lpszClassName", ctypes.c_wchar_p)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", WPARAM), ("lParam", LPARAM),
                ("time", ctypes.c_uint),
                ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long)]


def _wndproc(hwnd, msg, wp, lp):
    if msg == WM_CLOSE:
        user32.DestroyWindow(hwnd)
        return 0
    if msg == WM_LBUTTONDOWN:
        user32.SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)  # 原生拖拽
        return 0
    return user32.DefWindowProcW(hwnd, msg, wp, lp)


VOIDP = ctypes.c_void_p

gdi32.SelectObject.argtypes = [VOIDP, VOIDP]
gdi32.SelectObject.restype = VOIDP
gdi32.CreateDIBSection.argtypes = [VOIDP, VOIDP, ctypes.c_uint, ctypes.POINTER(VOIDP), VOIDP, ctypes.c_uint]
gdi32.DeleteDC.argtypes = [VOIDP]
user32.GetDC.argtypes = [VOIDP]
user32.ReleaseDC.argtypes = [VOIDP, VOIDP]
user32.UpdateLayeredWindow.argtypes = [VOIDP, VOIDP, ctypes.POINTER(POINT), ctypes.POINTER(SIZE), VOIDP, ctypes.POINTER(POINT), ctypes.c_uint, ctypes.POINTER(BLENDFUNCTION), ctypes.c_uint]
user32.PostMessageW.argtypes = [VOIDP, ctypes.c_uint, WPARAM, LPARAM]
user32.SendMessageW.argtypes = [VOIDP, ctypes.c_uint, WPARAM, LPARAM]
user32.DestroyWindow.argtypes = [VOIDP]
user32.DefWindowProcW.argtypes = [VOIDP, ctypes.c_uint, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [ctypes.c_uint, VOIDP, VOIDP, ctypes.c_uint,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   VOIDP, VOIDP, VOIDP, VOIDP]
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), VOIDP, ctypes.c_uint, ctypes.c_uint]
user32.CreateWindowExW.restype = VOIDP
k32 = ctypes.windll.kernel32
k32.GetModuleHandleW.restype = VOIDP
k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]

_wndproc_ref = WNDPROC(_wndproc)   # 防 GC
_wc_registered = False
FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"


class OverlayWindow:
    """独立线程跑消息循环；update(rgba_image) 从任意线程推送像素。"""

    def __init__(self):
        self.hwnd = None
        self._running = True
        self._first_img = self._first_x = self._first_y = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._ready = threading.Event()

    # ---- 生命周期 ----
    def start(self, x, y, img):
        self._thread.start()
        self._ready.wait(3)
        self.update(img, x, y)

    def _loop(self):
        global _wc_registered
        hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
        if not _wc_registered:
            wc = WNDCLASSW()
            wc.style = 0
            wc.lpfnWndProc = _wndproc_ref
            wc.hInstance = hinst
            wc.hCursor = user32.LoadCursorW(None, 32512)
            wc.lpszClassName = "WhisperOverlayLayer"
            user32.RegisterClassW(ctypes.byref(wc))
            _wc_registered = True
        w, h = 400, 90
        self.hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
            "WhisperOverlayLayer", "WhisperOverlay", WS_POPUP | WS_VISIBLE,
            0, 0, w, h, None, None, hinst, None)
        print("[overlay] hwnd:", hex(self.hwnd or 0))
        self._ready.set()
        if getattr(self, "_first_img", None) is not None:
            try:
                self.update(self._first_img, self._first_x, self._first_y)
            except Exception as e:
                print("[overlay] 首帧同线程推送失败:", e)
        msg = MSG()
        while self._running:
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def close(self):
        self._running = False
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    # ---- 像素推送 ----
    def update(self, img, x=None, y=None):
        """img: PIL RGBA。底板/文字的 alpha 即真实透明度。"""
        if not self.hwnd:
            return
        w, h = img.size
        arr = np.ascontiguousarray(np.array(img)[:, :, [2, 1, 0, 3]])  # RGBA->BGRA
        a = arr[:, :, 3:4].astype(np.uint16)
        arr[:, :, :3] = (arr[:, :, :3] * a // 255).astype(np.uint8)    # 预乘 alpha

        bmi = ctypes.create_string_buffer(40)
        import struct
        struct.pack_into("IiiHHIIiiII", bmi, 0, 40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        hdc_screen = user32.GetDC(None)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        bits = ctypes.c_void_p()
        gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), 0,
                               ctypes.byref(bits), None, 0)
        if bits.value:
            ctypes.memmove(bits.value, arr.ctypes.data, arr.nbytes)
            old = gdi32.SelectObject(hdc_mem, bits.value)
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            pt_src = POINT(0, 0)
            size = SIZE(w, h)
            ppt = POINT(x, y) if (x is not None and y is not None) else None
            ok = user32.UpdateLayeredWindow(self.hwnd, hdc_screen,
                                       ctypes.byref(ppt) if ppt else None,
                                       ctypes.byref(size), hdc_mem,
                                       ctypes.byref(pt_src), 0,
                                       ctypes.byref(blend), ULW_ALPHA)
            if not ok:
                print("[overlay] ULW failed:", hex(ctypes.windll.kernel32.GetLastError() & 0xFFFFFFFF))
            gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_screen)


def render_overlay(final, trans, font_size=16, plate_alpha=150, width_limit=1200,
                   final_color=(255, 255, 255, 255), trans_color=(255, 213, 74, 255)):
    """渲染浮层 RGBA：半透明圆角底板 + 描边文字。返回 (image, text_height)。"""
    f1 = ImageFont.truetype(FONT_PATH, font_size)
    f2 = ImageFont.truetype(FONT_PATH, max(12, font_size - 2))
    tmp = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    stroke = 0   # 底板保证对比度，无需描边
    b1 = tmp.textbbox((0, 0), final, font=f1, stroke_width=stroke)
    w = b1[2] + 28
    lines_h = b1[3] + 8
    if trans:
        b2 = tmp.textbbox((0, 0), trans, font=f2, stroke_width=stroke)
        w = max(w, b2[2] + 28)
        lines_h += b2[3] + 10
    img = Image.new("RGBA", (w, lines_h + 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, lines_h + 15), radius=10,
                        fill=(10, 12, 16, plate_alpha), outline=(90, 96, 104, 180), width=1)
    d.text((14, 8), final, font=f1, fill=final_color, stroke_width=0)
    if trans:
        d.text((14, b1[3] + 14), trans, font=f2, fill=trans_color, stroke_width=0)
    return img
