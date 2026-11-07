"""Orientation test card for the panel: draws a landscape card, rotates it the way the app will."""
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, "/usr/local/lib/aeezo-frame")
from kms import Display  # noqa: E402

d = Display()
print("panel", d.width, "x", d.height, "crtc", d.crtc, flush=True)
W, H = d.height, d.width  # landscape canvas as the viewer sees it
img = Image.new("RGB", (W, H), (20, 24, 32))
g = ImageDraw.Draw(img)
g.rectangle((0, 0, W, 40), fill=(220, 40, 40))         # red   = top
g.rectangle((0, H - 40, W, H), fill=(40, 200, 60))     # green = bottom
g.rectangle((0, 0, 40, H), fill=(40, 120, 230))        # blue  = left
big = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", 96)
small = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans.ttf", 40)
g.text((300, 300), "THIS SIDE UP", font=big, fill=(255, 230, 120))
g.polygon([(640, 90), (560, 220), (720, 220)], fill=(255, 230, 120))
g.text((330, 470), "red=top  green=bottom  blue=left", font=small, fill=(200, 200, 200))
# same direction as fbcon=rotate:1 (clockwise)
out = img.transpose(Image.Transpose.ROTATE_270)
d.back()[:] = np.frombuffer(out.tobytes("raw", "BGRX"), dtype=np.uint8).reshape(d.height, d.width, 4)
d.flip()
time.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 30)
