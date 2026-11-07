"""AEEZO frame slideshow: random (or album) photos from Immich, crossfaded on the panel.

Config: /etc/aeezo-frame/frame.conf (KEY=VALUE), API key: /etc/aeezo-frame/immich.key.
The fetcher process keeps an on-disk cache of panel-ready JPEGs, so the display never waits
on the network and keeps cycling when Immich is unreachable.
"""
import json
import multiprocessing
import os
import random
import select
import signal
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kms import Display  # noqa: E402

CONF_PATH = "/etc/aeezo-frame/frame.conf"
KEY_PATH = "/etc/aeezo-frame/immich.key"
DEFAULTS = {
    "IMMICH_URL": "",            # e.g. http://<server-ip>:2283 (required)
    "SOURCE": "random",          # random | album:<album name>
    "INTERVAL": "30",            # seconds per photo
    "FADE": "2.0",               # crossfade seconds
    "CACHE_DIR": "/var/cache/aeezo-frame",
    "CACHE_MAX": "300",          # photos kept on disk
    "BATCH": "40",               # photos asked for per fetch
    "REFRESH": "1800",           # seconds between fetches once the cache is full
    "SKIP_PREFIXES": "Screenshot,screenshot,Screen Shot",
    "SLEEP_AT": "23:00",          # backlight off at this local time; empty = never sleep
    "WAKE_AT": "05:30",           # ...and back on at this one
    "WAKE_FOR": "120",            # seconds a touch keeps a sleeping screen lit
    "BRIGHT": "8",                # backlight level, 0-10 (linear PWM duty)
}
FONT = "/usr/share/fonts/dejavu/DejaVuSans.ttf"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def load_conf():
    conf = dict(DEFAULTS)
    try:
        for line in open(CONF_PATH):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                conf[k.strip()] = v.strip().strip('"')
    except FileNotFoundError:
        pass
    return conf


# --- composing -------------------------------------------------------------------------------

def compose(data, panel_w, panel_h):
    """Photo bytes -> panel-native (portrait) RGB image, viewer sees landscape panel_h x panel_w."""
    W, H = panel_h, panel_w
    im = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")
    r_img, r_can = im.width / im.height, W / H
    if abs(r_img - r_can) / r_can < 0.2:
        canvas = ImageOps.fit(im, (W, H), Image.Resampling.LANCZOS)          # close enough: fill
    else:
        bg = ImageOps.fit(im, (W // 8, H // 8), Image.Resampling.BILINEAR)   # blur cheaply at 1/8
        bg = bg.filter(ImageFilter.GaussianBlur(4)).resize((W, H), Image.Resampling.BILINEAR)
        canvas = ImageEnhance.Brightness(bg).enhance(0.55)
        fg = ImageOps.contain(im, (W, H), Image.Resampling.LANCZOS)
        canvas.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    return canvas.transpose(Image.Transpose.ROTATE_270)  # same direction as fbcon=rotate:1


def to_bgrx(img):
    return np.frombuffer(img.tobytes("raw", "BGRX"), dtype=np.uint8).reshape(img.height, img.width, 4)


def message(text, panel_w, panel_h):
    W, H = panel_h, panel_w
    img = Image.new("RGB", (W, H), (12, 14, 18))
    g = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, 44)
    w = g.textlength(text, font=f)
    g.text(((W - w) / 2, H / 2 - 30), text, font=f, fill=(170, 175, 185))
    return img.transpose(Image.Transpose.ROTATE_270)


# --- Immich ----------------------------------------------------------------------------------

class Immich:
    def __init__(self, url, key):
        self.url, self.key = url.rstrip("/"), key

    def _req(self, method, path, body=None, timeout=30):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"x-api-key": self.key, "Accept": "application/json",
                                              **({"Content-Type": "application/json"} if data else {})})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    def candidates(self, source, n):
        if source == "random":
            return json.loads(self._req("POST", "/api/search/random", {"size": n, "type": "IMAGE"}))
        if source.startswith("album:"):
            name = source.split(":", 1)[1]
            albums = json.loads(self._req("GET", "/api/albums"))
            match = [a for a in albums if a.get("albumName") == name]
            if not match:
                raise LookupError(f"no album named {name!r}")
            assets = json.loads(self._req("GET", f"/api/albums/{match[0]['id']}")).get("assets", [])
            return random.sample(assets, min(n, len(assets)))
        raise ValueError(f"unknown SOURCE {source!r}")

    def preview(self, asset_id):
        return self._req("GET", f"/api/assets/{urllib.parse.quote(asset_id)}/thumbnail?size=preview", timeout=60)


class Fetcher(multiprocessing.Process):
    """Separate process, not a thread: Pillow holds the GIL in parts of decode/compose, which
    starved the crossfade's main loop (13 fps -> 9). The cache directory is the only shared state."""

    def __init__(self, conf, panel_w, panel_h):
        super().__init__(daemon=True)
        self.conf, self.pw, self.ph = conf, panel_w, panel_h
        self.dir = conf["CACHE_DIR"]
        os.makedirs(self.dir, exist_ok=True)
        self.skip = tuple(p for p in conf["SKIP_PREFIXES"].split(",") if p)
        self.status = "starting"

    def cached(self):
        return sorted(f for f in os.listdir(self.dir) if f.endswith(".jpg"))

    def prune(self):
        files = sorted((os.path.getmtime(os.path.join(self.dir, f)), f) for f in self.cached())
        for _, f in files[: max(0, len(files) - int(self.conf["CACHE_MAX"]))]:
            os.remove(os.path.join(self.dir, f))

    def fetch_once(self, api):
        got = 0
        for a in api.candidates(self.conf["SOURCE"], int(self.conf["BATCH"])):
            if a.get("type") != "IMAGE" or a.get("isTrashed") or a.get("isArchived"):
                continue
            if (a.get("originalFileName") or "").startswith(self.skip):
                continue
            dest = os.path.join(self.dir, a["id"] + ".jpg")
            if os.path.exists(dest):
                continue
            img = compose(api.preview(a["id"]), self.pw, self.ph)
            img.save(dest + ".tmp", "JPEG", quality=90)
            os.replace(dest + ".tmp", dest)
            got += 1
        self.prune()
        return got

    def run(self):
        os.nice(19)  # composing is ~1s of CPU per photo; only take what the crossfade leaves
        backoff = 30
        while True:
            try:
                key = open(KEY_PATH).read().strip()
                api = Immich(self.conf["IMMICH_URL"], key)
                got = self.fetch_once(api)
                self.status = "ok"
                log(f"fetched {got} new, cache {len(self.cached())}")
                backoff = 30
                full = len(self.cached()) >= int(self.conf["CACHE_MAX"])
                time.sleep(float(self.conf["REFRESH"]) if full or got == 0 else 5)
            except FileNotFoundError:
                self.status = "no API key"
                log(f"waiting for {KEY_PATH}")
                time.sleep(30)
            except Exception as e:  # network down, Immich restarting, bad photo: keep showing the cache
                self.status = f"fetch error: {e}"
                log("fetch error:", repr(e))
                time.sleep(backoff)
                backoff = min(backoff * 2, 1800)


# --- touch -----------------------------------------------------------------------------------

class Touch:
    """Taps on the Silead panel as landscape coordinates (what the viewer sees, 1280x800).

    The DT already maps the controller onto the panel's native portrait frame (inverted + swapped,
    verified with corner taps); fbcon-style rotation then gives landscape = (native_y, H - native_x).
    """

    def __init__(self, panel_w=800, panel_h=1280):
        self.dev, self.pw, self.ph = None, panel_w, panel_h
        self.x = self.y = None
        self.down = False
        try:
            import evdev
            from evdev import ecodes
            for path in evdev.list_devices():
                d = evdev.InputDevice(path)
                if "silead" in d.name:
                    self.dev = d
                    caps = dict(d.capabilities(absinfo=True)).get(ecodes.EV_ABS, [])
                    info = {code: ai for code, ai in caps}
                    self.xmax = (info.get(ecodes.ABS_MT_POSITION_X) or info.get(ecodes.ABS_X)).max
                    self.ymax = (info.get(ecodes.ABS_MT_POSITION_Y) or info.get(ecodes.ABS_Y)).max
                    break
        except Exception as e:
            log("touch unavailable:", e)
            self.dev = None

    def fds(self):
        return [self.dev.fd] if self.dev else []

    def taps(self):
        """Drain pending events; return the list of new touch-downs as (lx, ly) landscape pixels."""
        from evdev import ecodes
        out = []
        try:
            for ev in self.dev.read():
                if ev.type == ecodes.EV_ABS and ev.code in (ecodes.ABS_MT_POSITION_X, ecodes.ABS_X):
                    self.x = ev.value
                elif ev.type == ecodes.EV_ABS and ev.code in (ecodes.ABS_MT_POSITION_Y, ecodes.ABS_Y):
                    self.y = ev.value
                elif ev.type == ecodes.EV_KEY and ev.code == ecodes.BTN_TOUCH:
                    self.down = ev.value == 1
                    if self.down:
                        self.pending = True
                elif ev.type == ecodes.EV_SYN and getattr(self, "pending", False) and self.x is not None:
                    nx, ny = self.x / self.xmax * self.pw, self.y / self.ymax * self.ph
                    out.append((ny, self.pw - nx))
                    self.pending = False
        except BlockingIOError:
            pass
        return out


# --- backlight -------------------------------------------------------------------------------

class Screen:
    """The only writer of the backlight. Dark between SLEEP_AT and WAKE_AT (local time); a touch
    lights it for WAKE_FOR seconds, and that waking touch is swallowed (it doesn't also skip the
    photo)."""
    GRACE = 1.0  # also swallow the rest of a waking double-tap

    def __init__(self, conf, path="/sys/class/backlight/backlight/bl_power"):
        self.path = path
        self.level_path = os.path.join(os.path.dirname(path), "brightness")
        hm = lambda v: int(v.split(":")[0]) * 60 + int(v.split(":")[1]) if v.strip() else None
        self.sleep_at, self.wake_at = hm(conf["SLEEP_AT"]), hm(conf["WAKE_AT"])
        self.wake_for = float(conf["WAKE_FOR"])
        self.bright = int(conf["BRIGHT"])
        self.on, self.lit_until, self.woke_at, self.level = None, 0.0, -1e9, None

    def night(self, t=None):
        if self.sleep_at is None or self.wake_at is None or self.sleep_at == self.wake_at:
            return False
        lt = time.localtime(t)
        m = lt.tm_hour * 60 + lt.tm_min
        if self.sleep_at < self.wake_at:
            return self.sleep_at <= m < self.wake_at
        return m >= self.sleep_at or m < self.wake_at  # spans midnight

    def set(self, on):
        if on == self.on:
            return
        try:
            with open(self.path, "w") as f:
                f.write("0" if on else "4")  # FB_BLANK_UNBLANK / FB_BLANK_POWERDOWN
            log("screen", "on" if on else "off")
            if on and self.on is False:
                self.woke_at = time.monotonic()
            self.on = on
        except OSError as e:
            if self.on is None:
                log("backlight unavailable:", e)
            self.on = on

    def set_level(self, n):
        if n == self.level:
            return
        try:
            with open(self.level_path, "w") as f:
                f.write(str(n))
            log("brightness", n)
        except OSError as e:
            if self.level is None:
                log("brightness unavailable:", e)
        self.level = n

    def update(self):
        """Apply the schedule; returns whether the screen is lit."""
        self.set(not self.night() or time.monotonic() < self.lit_until)
        if self.on:
            self.set_level(self.bright)
        return self.on

    def touched(self):
        """Call on every tap. True = swallow it (it woke the screen, or came right after)."""
        self.lit_until = time.monotonic() + self.wake_for
        was_dark = self.on is False
        self.update()
        return was_dark or time.monotonic() - self.woke_at < self.GRACE


# --- display loop ----------------------------------------------------------------------------

_POOL = ThreadPoolExecutor(os.cpu_count() or 1)


def crossfade(disp, cur, nxt, seconds):
    """cur/nxt: (h, w, 4) uint8 BGRX; returns frames drawn.

    frame = a + ((b - a) * w >> 7) with a 7-bit weight, so (b - a) * w stays inside int16, in
    horizontal stripes across all cores (numpy drops the GIL in its loops). ~15 fps on the A33
    vs ~5 for a single-threaded a*(256-w) + b*w; endpoints are exact.
    """
    a = cur.astype(np.int16)
    diff = nxt.astype(np.int16) - a
    tmp = np.empty_like(a)
    n = _POOL._max_workers
    rows = np.linspace(0, a.shape[0], n + 1, dtype=int)

    def stripe(i, w, back):
        s = slice(rows[i], rows[i + 1])
        np.multiply(diff[s], w, out=tmp[s])
        np.right_shift(tmp[s], 7, out=tmp[s])
        np.add(tmp[s], a[s], out=tmp[s])
        back[s] = tmp[s]

    t0, frames = time.monotonic(), 0
    while True:
        k = min(1.0, (time.monotonic() - t0) / seconds) if seconds > 0 else 1.0
        w, back = int(k * 128), disp.back()
        list(_POOL.map(lambda i: stripe(i, w, back), range(n)))
        disp.flip()
        frames += 1
        if k >= 1.0:
            return frames


def slideshow(disp, conf, fetcher, touch, screen, state):
    """Photo loop, forever. A tap skips to the next photo."""
    while True:
        if not screen.update():  # dark: don't burn four cores crossfading for nobody
            r, _, _ = select.select(touch.fds(), [], [], 5)
            if r and touch.taps():
                screen.touched()
            continue
        files = fetcher.cached()
        if not files:
            time.sleep(2)
            continue
        if not state["order"]:  # new shuffled pass over everything cached, avoiding an immediate repeat
            state["order"] = [f for f in files if f not in state["recent"][-1:]] or files
            random.shuffle(state["order"])
        f = state["order"].pop()
        path = os.path.join(fetcher.dir, f)
        if not os.path.exists(path):  # pruned meanwhile
            continue
        try:
            nxt = to_bgrx(Image.open(path).convert("RGB"))
        except Exception as e:
            log("bad cache file", f, e)
            os.remove(path)
            continue
        t0 = time.monotonic()
        frames = crossfade(disp, state["cur"], nxt, float(conf["FADE"]))
        dt = time.monotonic() - t0
        log(f"showing {f[:8]} ({frames} fade frames, {frames / dt:.1f} fps)")
        state["cur"], state["recent"] = nxt, (state["recent"] + [f])[-50:]
        deadline = time.monotonic() + float(conf["INTERVAL"])
        while (left := deadline - time.monotonic()) > 0:
            r, _, _ = select.select(touch.fds(), [], [], left)
            if r and touch.taps() and not screen.touched():
                log("tap: next")
                break


def main():
    conf = load_conf()
    disp = Display()
    pw, ph = disp.width, disp.height
    log(f"panel {pw}x{ph}, source {conf['SOURCE']}, interval {conf['INTERVAL']}s")
    shown = to_bgrx(message("AEEZO frame: loading" if conf["IMMICH_URL"] else "set IMMICH_URL in frame.conf", pw, ph))
    disp.back()[:] = shown
    disp.flip()
    fetcher = Fetcher(conf, pw, ph)
    if conf["IMMICH_URL"]:
        fetcher.start()
    else:
        log(f"IMMICH_URL is not set in {CONF_PATH}; showing whatever is already cached")
    touch = Touch(pw, ph)
    screen = Screen(conf)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))  # so the finally below relights the panel
    try:
        slideshow(disp, conf, fetcher, touch, screen, {"order": [], "recent": [], "cur": shown})
    finally:
        screen.set(True)  # never leave the panel dark with nothing running to change it
        screen.set_level(screen.bright)


if __name__ == "__main__":
    main()
