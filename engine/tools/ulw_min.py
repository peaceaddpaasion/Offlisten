# -*- coding: utf-8 -*-
"""最小 ULW 实验：单线程，纯色 RGBA 图。"""
import ctypes, struct
import numpy as np
from PIL import Image

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
k32 = ctypes.windll.kernel32
VOIDP = ctypes.c_void_p
LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, VOIDP, ctypes.c_uint, WPARAM, LPARAM)

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]
class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]
class MSG(ctypes.Structure):
    _fields_ = [("hwnd", VOIDP), ("message", ctypes.c_uint), ("wParam", WPARAM),
                ("lParam", LPARAM), ("time", ctypes.c_uint),
                ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long)]
class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", VOIDP), ("hIcon", VOIDP), ("hCursor", VOIDP),
                ("hbrBackground", VOIDP), ("lpszMenuName", ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p)]

def wndproc(hwnd, msg, wp, lp):
    if msg == 0x0010:  # WM_CLOSE
        user32.DestroyWindow(hwnd)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wp, lp)

user32.DefWindowProcW.argtypes = [VOIDP, ctypes.c_uint, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.restype = VOIDP
user32.CreateWindowExW.argtypes = [ctypes.c_uint, VOIDP, VOIDP, ctypes.c_uint,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   VOIDP, VOIDP, VOIDP, VOIDP]
user32.GetDC.argtypes = [VOIDP]; user32.GetDC.restype = VOIDP
user32.ReleaseDC.argtypes = [VOIDP, VOIDP]
gdi32.CreateCompatibleDC.argtypes = [VOIDP]; gdi32.CreateCompatibleDC.restype = VOIDP
gdi32.DeleteDC.argtypes = [VOIDP]
gdi32.SelectObject.argtypes = [VOIDP, VOIDP]; gdi32.SelectObject.restype = VOIDP
gdi32.CreateDIBSection.argtypes = [VOIDP, VOIDP, ctypes.c_uint, ctypes.POINTER(VOIDP), VOIDP, ctypes.c_uint]
user32.UpdateLayeredWindow.argtypes = [VOIDP, VOIDP, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
                                       VOIDP, ctypes.POINTER(POINT), ctypes.c_uint,
                                       ctypes.POINTER(BLENDFUNCTION), ctypes.c_uint]

wc = WNDCLASSW()
wc.lpfnWndProc = WNDPROC(wndproc)
wc.lpszClassName = "MinULW"
wc.hInstance = k32.GetModuleHandleW(None)
assert user32.RegisterClassW(ctypes.byref(wc)), "RegisterClass failed"

hwnd = user32.CreateWindowExW(0x80000 | 0x8 | 0x80,  # LAYERED|TOPMOST|TOOLWINDOW
    "MinULW", "min", 0x80000000 | 0x10000000,  # POPUP|VISIBLE
    200, 200, 400, 120, None, None, wc.hInstance, None)
print("hwnd:", hex(hwnd or 0))
assert hwnd, "CreateWindowExW failed"

img = Image.new("RGBA", (400, 120), (200, 30, 30, 160))  # 半透明红
arr = np.ascontiguousarray(np.array(img)[:, :, [2, 1, 0, 3]])
a = arr[:, :, 3:4].astype(np.uint16)
arr[:, :, :3] = (arr[:, :, :3] * a // 255).astype(np.uint8)

bmi = ctypes.create_string_buffer(40)
struct.pack_into("IiiHHIIiiII", bmi, 0, 40, 400, -120, 1, 32, 0, 0, 0, 0, 0, 0)
hdc_screen = user32.GetDC(None)
hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
bits = VOIDP()
assert gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0), "DIB failed"
ctypes.memmove(bits, arr.ctypes.data, arr.nbytes)
old = gdi32.SelectObject(hdc_mem, bits)

blend = BLENDFUNCTION(0, 0, 255, 1)
pt_src = POINT(0, 0); size = SIZE(400, 120); pt_dst = POINT(200, 200)
ok = user32.UpdateLayeredWindow(hwnd, hdc_screen, ctypes.byref(pt_dst), ctypes.byref(size),
                                hdc_mem, ctypes.byref(pt_src), 0, ctypes.byref(blend), 2)
print("ULW:", bool(ok), "err:", hex(k32.GetLastError() & 0xFFFFFFFF))

# 消息循环 3 秒
import time
end = time.time() + 3
msg = MSG()
while time.time() < end:
    while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    time.sleep(0.05)
print("MIN ULW DONE")
