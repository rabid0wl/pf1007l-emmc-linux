"""Minimal KMS output: two dumb framebuffers on the first connected connector, page-flipped.

SDL's kmsdrm backend (Alpine ships sdl2-compat over SDL3) segfaults during init on this
armv7/musl box, so this talks to libdrm directly. No GPU is involved: frames are plain
XRGB8888 memory exposed as numpy arrays (height, width, 4) in B, G, R, X byte order.
"""
import ctypes
import ctypes.util
import errno
import fcntl
import mmap
import os
import time

import numpy as np

_drm = ctypes.CDLL(ctypes.util.find_library("drm") or "libdrm.so.2", use_errno=True)

u8, u16, u32, u64 = ctypes.c_uint8, ctypes.c_uint16, ctypes.c_uint32, ctypes.c_uint64


class ModeInfo(ctypes.Structure):
    _fields_ = [("clock", u32),
                ("hdisplay", u16), ("hsync_start", u16), ("hsync_end", u16), ("htotal", u16), ("hskew", u16),
                ("vdisplay", u16), ("vsync_start", u16), ("vsync_end", u16), ("vtotal", u16), ("vscan", u16),
                ("vrefresh", u32), ("flags", u32), ("type", u32), ("name", ctypes.c_char * 32)]


class Res(ctypes.Structure):
    _fields_ = [("count_fbs", ctypes.c_int), ("fbs", ctypes.POINTER(u32)),
                ("count_crtcs", ctypes.c_int), ("crtcs", ctypes.POINTER(u32)),
                ("count_connectors", ctypes.c_int), ("connectors", ctypes.POINTER(u32)),
                ("count_encoders", ctypes.c_int), ("encoders", ctypes.POINTER(u32)),
                ("min_width", u32), ("max_width", u32), ("min_height", u32), ("max_height", u32)]


class Connector(ctypes.Structure):
    _fields_ = [("connector_id", u32), ("encoder_id", u32), ("connector_type", u32),
                ("connector_type_id", u32), ("connection", ctypes.c_int),
                ("mmWidth", u32), ("mmHeight", u32), ("subpixel", ctypes.c_int),
                ("count_modes", ctypes.c_int), ("modes", ctypes.POINTER(ModeInfo)),
                ("count_props", ctypes.c_int), ("props", ctypes.POINTER(u32)),
                ("prop_values", ctypes.POINTER(u64)),
                ("count_encoders", ctypes.c_int), ("encoders", ctypes.POINTER(u32))]


class Encoder(ctypes.Structure):
    _fields_ = [("encoder_id", u32), ("encoder_type", u32), ("crtc_id", u32),
                ("possible_crtcs", u32), ("possible_clones", u32)]


class CreateDumb(ctypes.Structure):
    _fields_ = [("height", u32), ("width", u32), ("bpp", u32), ("flags", u32),
                ("handle", u32), ("pitch", u32), ("size", u64)]


class MapDumb(ctypes.Structure):
    _fields_ = [("handle", u32), ("pad", u32), ("offset", u64)]


def _iowr(nr, size):  # _IOWR('d', nr, size) on Linux/ARM
    return (3 << 30) | (size << 16) | (ord("d") << 8) | nr


DRM_IOCTL_MODE_CREATE_DUMB = _iowr(0xB2, ctypes.sizeof(CreateDumb))
DRM_IOCTL_MODE_MAP_DUMB = _iowr(0xB3, ctypes.sizeof(MapDumb))
DRM_MODE_CONNECTED = 1

_drm.drmModeGetResources.restype = ctypes.POINTER(Res)
_drm.drmModeGetConnector.restype = ctypes.POINTER(Connector)
_drm.drmModeGetEncoder.restype = ctypes.POINTER(Encoder)
_drm.drmModeAddFB.argtypes = [ctypes.c_int, u32, u32, u8, u8, u32, u32, ctypes.POINTER(u32)]
_drm.drmModeSetCrtc.argtypes = [ctypes.c_int, u32, u32, u32, u32, ctypes.POINTER(u32), ctypes.c_int,
                                ctypes.POINTER(ModeInfo)]
_drm.drmModePageFlip.argtypes = [ctypes.c_int, u32, u32, u32, ctypes.c_void_p]


class Display:
    """Owns the panel: width/height are the native (portrait) mode, back() is the frame to draw next."""

    def __init__(self, card=None):
        cards = [card] if card else sorted(f"/dev/dri/{c}" for c in os.listdir("/dev/dri") if c.startswith("card"))
        for path in cards:
            fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
            res = _drm.drmModeGetResources(fd)
            if res:
                break
            os.close(fd)
        else:
            raise RuntimeError("no KMS-capable /dev/dri/card*")
        self.fd = fd
        r = res.contents
        conn = None
        for i in range(r.count_connectors):
            c = _drm.drmModeGetConnector(fd, r.connectors[i])
            if c and c.contents.connection == DRM_MODE_CONNECTED and c.contents.count_modes:
                conn = c.contents
                break
        if conn is None:
            raise RuntimeError("no connected connector")
        self.mode = ModeInfo.from_buffer_copy(conn.modes[0])
        self.conn_id = u32(conn.connector_id)
        enc = _drm.drmModeGetEncoder(fd, conn.encoder_id) if conn.encoder_id else None
        if enc and enc.contents.crtc_id:
            self.crtc = enc.contents.crtc_id
        else:
            self.crtc = r.crtcs[0]
        self.width, self.height = self.mode.hdisplay, self.mode.vdisplay
        self.bufs = [self._dumb() for _ in range(2)]
        self.front = 0
        self.bufs[0][1][:] = 0
        if _drm.drmModeSetCrtc(fd, self.crtc, self.bufs[0][0], 0, 0, ctypes.byref(self.conn_id), 1,
                               ctypes.byref(self.mode)):
            raise OSError(ctypes.get_errno(), "drmModeSetCrtc failed")

    def _dumb(self):
        cd = CreateDumb(height=self.height, width=self.width, bpp=32)
        fcntl.ioctl(self.fd, DRM_IOCTL_MODE_CREATE_DUMB, cd)
        fb = u32()
        if _drm.drmModeAddFB(self.fd, self.width, self.height, 24, 32, cd.pitch, cd.handle, ctypes.byref(fb)):
            raise OSError(ctypes.get_errno(), "drmModeAddFB failed")
        md = MapDumb(handle=cd.handle)
        fcntl.ioctl(self.fd, DRM_IOCTL_MODE_MAP_DUMB, md)
        mm = mmap.mmap(self.fd, cd.size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=md.offset)
        arr = np.frombuffer(mm, dtype=np.uint8).reshape(self.height, cd.pitch // 4, 4)[:, :self.width, :]
        return fb.value, arr, mm

    def back(self):
        """numpy view (height, width, 4) BGRX of the buffer that is not on screen."""
        return self.bufs[1 - self.front][1]

    def flip(self):
        nxt = 1 - self.front
        for _ in range(100):  # a previous flip may still be pending until the next vblank
            if _drm.drmModePageFlip(self.fd, self.crtc, self.bufs[nxt][0], 0, None) == 0:
                break
            if ctypes.get_errno() != errno.EBUSY:
                raise OSError(ctypes.get_errno(), "drmModePageFlip failed")
            time.sleep(0.002)
        self.front = nxt
