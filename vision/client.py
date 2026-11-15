"""
Non-blocking HTTP client for the backend.

* Crossing events are queued and retried (they are evidence; don't drop them).
* Preview frames are "latest wins": only the newest frame is sent, ~5 per second.
"""
import base64
import queue
import threading
import time
from typing import Optional

import requests

HEADERS = {"ngrok-skip-browser-warning": "1"}


def to_b64(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


class BackendClient:
    def __init__(self, base_url: str, frame_interval_s: float = 0.2):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.events: "queue.Queue[dict]" = queue.Queue(maxsize=500)
        self._frame: Optional[dict] = None
        self._lock = threading.Lock()
        self.frame_interval_s = frame_interval_s
        self.online = False
        self.sent = 0
        threading.Thread(target=self._event_worker, daemon=True).start()
        threading.Thread(target=self._frame_worker, daemon=True).start()

    def send_crossing(self, track_id, direction: str, ts: float, conf: float, jpeg: Optional[bytes],
                      gate_id: str = "gate-01") -> None:
        payload = {"event": "PERSON_CROSSING", "gate_id": gate_id, "track_id": track_id,
                   "direction": direction, "timestamp": ts, "confidence": round(conf, 3),
                   "source": "vision"}
        if jpeg:
            payload["snapshot_base64"] = to_b64(jpeg)
        try:
            self.events.put_nowait(payload)
        except queue.Full:
            print("[vision] event queue full — backend unreachable?")

    def push_frame(self, jpeg: bytes, stats: dict) -> None:
        with self._lock:
            self._frame = {"jpeg_base64": base64.b64encode(jpeg).decode(), "stats": stats}

    def _post(self, path: str, payload: dict, timeout: float) -> bool:
        try:
            r = self.session.post(self.base + path, json=payload, timeout=timeout)
            self.online = r.ok
            return r.ok
        except requests.RequestException:
            self.online = False
            return False

    def _event_worker(self) -> None:
        while True:
            payload = self.events.get()
            for attempt in range(5):
                if self._post("/api/event/vision", payload, timeout=3):
                    self.sent += 1
                    break
                time.sleep(0.5 * (attempt + 1))
            else:
                print(f"[vision] gave up sending crossing for track {payload['track_id']}")

    def _frame_worker(self) -> None:
        while True:
            time.sleep(self.frame_interval_s)
            with self._lock:
                frame, self._frame = self._frame, None
            if frame:
                self._post("/api/vision/frame", frame, timeout=2)
