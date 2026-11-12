# -*- coding: utf-8 -*-
"""ULW 0x1f 二分排查：逐个变体找能过的组合。"""
import ctypes, struct, time
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
    if msg == 0x0010:
        user32.DestroyWindow(hwnd); return 0
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
wc.lpszClassName = "VarULW"
wc.hInstance = k32.GetModuleHandleW(None)
user32.RegisterClassW(ctypes.byref(wc))

img = Image.new("RGBA", (400, 120), (200, 30, 30, 160))
arr = np.ascontiguousarray(np.array(img)[:, :, [2, 1, 0, 3]])
a = arr[:, :, 3:4].astype(np.uint16)
arr[:, :, :3] = (arr[:, :, :3] * a // 255).astype(np.uint8)

def try_variant(name, w=400, h=120, top_down=True, premul=True, hdc_dst=True,
                ex=0x80000 | 0x8 | 0x80, alpha_mode=1):
    data = arr.copy()
    if not premul:
        data = np.ascontiguousarray(np.array(img)[:, :, [2, 1, 0, 3]])
    bmi = ctypes.create_string_buffer(40)
    struct.pack_into("IiiHHIIiiII", bmi, 0, 40, w, -h if top_down else h, 1, 32, 0, 0, 0, 0, 0, 0)
    if not top_down:  # bottom-up: 翻转行
        data = data[::-1].copy()
    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    bits = VOIDP()
    r = gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    if not r or not bits:
        print(name, "-> DIB failed"); return
    ctypes.memmove(bits, data.ctypes.data, data.nbytes)
    old = gdi32.SelectObject(hdc_mem, bits)
    blend = BLENDFUNCTION(0, 0, 255, 1 if premul and alpha_mode == 1 else 0)
    sca = 255 if alpha_mode == 1 else 200
    blend.SourceConstantAlpha = sca
    pt_src = POINT(0, 0); size = SIZE(w, h); pt_dst = POINT(300, 300)
    hwnd = user32.CreateWindowExW(ex, "VarULW", name, 0x80000000 | 0x10000000,
                                  300, 300, w, h, None, None, wc.hInstance, None)
    ok = user32.UpdateLayeredWindow(hwnd, hdc_screen if hdc_dst else None,
                                    ctypes.byref(pt_dst), ctypes.byref(size),
                                    hdc_mem, ctypes.byref(pt_src), 0,
                                    ctypes.byref(blend), 2)
    err = hex(k32.GetLastError() & 0xFFFFFFFF)
    print(f"{name}: ULW={'OK' if ok else 'FAIL'} err={err}")
    user32.DestroyWindow(hwnd)
    gdi32.SelectObject(hdc_mem, old)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_screen)

try_variant("V1 基线(topdown+premul)")
try_variant("V2 bottom-up", top_down=False)
try_variant("V3 hdcDst=None", hdc_dst=False)
try_variant("V4 非预乘+SCA200", premul=False, alpha_mode=0)
try_variant("V5 无TOOLWINDOW", ex=0x80000 | 0x8)
try_variant("V6 无TOPMOST", ex=0x80000 | 0x80)
