"""
Vision adapter — turns any supported camera payload into per-person crossings.

Primary format (sent by vision/ for every unique track that crosses the tripwire):
    {"event": "PERSON_CROSSING", "track_id": 7, "direction": "IN"|"OUT",
     "timestamp": float, "confidence": 0.81, "snapshot_base64": "data:image/jpeg;base64,..."}

Legacy formats still accepted:
  * restricted script:  {"persons_detected": 2, "snapshot_base64": "..."}
      -> N inbound crossings with synthetic track ids
  * old cctv_engine.py: {"event": "AUTHORIZED_ENTRY"|"TAILGATING_BREACH"|"UNAUTHORIZED_CROSSING",
                         "person_id": 3, ...}
      -> one inbound crossing (the backend re-decides authorisation itself)
"""
import uuid
from dataclasses import dataclass
from typing import List, Optional

from .hardware import normalize_ts

_OLD_ENGINE_EVENTS = {"AUTHORIZED_ENTRY", "TAILGATING_BREACH", "UNAUTHORIZED_CROSSING"}


@dataclass
class Crossing:
    track_id: str
    direction: str          # IN | OUT
    ts: float
    snapshot_b64: Optional[str] = None
    confidence: Optional[float] = None
    source: str = "vision"
    snapshot_file: Optional[str] = None   # set by the backend once saved to disk


def parse_vision(data: dict, now: float) -> List[Crossing]:
    if not isinstance(data, dict):
        return []
    ev = str(data.get("event") or "").strip().upper()
    ts = normalize_ts(data.get("timestamp"), now)
    snap = data.get("snapshot_base64")

    if ev in ("PERSON_CROSSING", "CROSSING"):
        direction = str(data.get("direction", "")).strip().upper()
        if direction not in ("IN", "OUT") or data.get("track_id") is None:
            return []
        conf = data.get("confidence")
        return [Crossing(str(data["track_id"]), direction, ts, snap,
                         float(conf) if conf is not None else None,
                         str(data.get("source") or "vision"))]

    if ev in _OLD_ENGINE_EVENTS:
        tid = data.get("person_id") or uuid.uuid4().hex[:6]
        return [Crossing(f"cctv-{tid}", "IN", ts, snap, source="cctv_engine")]

    if not ev and "persons_detected" in data:
        try:
            n = max(0, int(data.get("persons_detected") or 0))
        except (TypeError, ValueError):
            n = 0
        batch = uuid.uuid4().hex[:6]
        return [Crossing(f"legacy-{batch}-{i + 1}", "IN", ts, snap, source="legacy")
                for i in range(n)]

    return []
