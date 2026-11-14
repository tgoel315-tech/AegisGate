"""
Latest camera frame + vision stats pushed by the vision module.
The backend never opens the webcam itself (Windows only lets one process use it).
"""
import base64
import io
import time
from datetime import datetime
from typing import Optional

from PIL import Image, ImageDraw

NAVY = (15, 27, 61)
WHITE = (255, 255, 255)
PINK = (255, 61, 139)


def decode_b64_image(data: Optional[str]) -> Optional[bytes]:
    if not data:
        return None
    if "," in data and data.strip().startswith("data:"):
        data = data.split(",", 1)[1]
    try:
        return base64.b64decode(data)
    except Exception:
        return None


def placeholder_frame(title: str, subtitle: str = "", w: int = 640, h: int = 480) -> bytes:
    img = Image.new("RGB", (w, h), NAVY)
    d = ImageDraw.Draw(img)
    for x in range(0, w, 40):
        d.line([(x, 0), (x, h)], fill=(27, 39, 75))
    for y in range(0, h, 40):
        d.line([(0, y), (w, y)], fill=(27, 39, 75))
    d.line([(w // 2, 0), (w // 2, h)], fill=PINK, width=2)
    d.text((20, 20), title, fill=WHITE)
    if subtitle:
        d.text((20, 40), subtitle, fill=(180, 186, 205))
    d.text((20, h - 24), datetime.now().strftime("CAM-01  %Y-%m-%d %H:%M:%S"), fill=(180, 186, 205))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


class FrameStore:
    def __init__(self, stale_s: float = 3.0):
        self.stale_s = stale_s
        self.jpeg: Optional[bytes] = None
        self.updated_at = 0.0
        self.stats: dict = {}
        self.stats_at = 0.0

    def push(self, jpeg: Optional[bytes], stats: Optional[dict]) -> None:
        now = time.time()
        if jpeg:
            self.jpeg, self.updated_at = jpeg, now
        if stats is not None:
            self.stats, self.stats_at = stats, now

    @property
    def online(self) -> bool:
        return time.time() - max(self.updated_at, self.stats_at) < self.stale_s

    def fresh_jpeg(self) -> Optional[bytes]:
        if self.jpeg and time.time() - self.updated_at < self.stale_s:
            return self.jpeg
        return None

    def current(self) -> bytes:
        return self.fresh_jpeg() or placeholder_frame(
            "NO CAMERA SIGNAL", "Start the vision module:  python -m vision.main")
