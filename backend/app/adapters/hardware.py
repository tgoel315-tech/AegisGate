"""
Hardware adapter — converts the RESTRICTED hardware payloads into one internal shape.

Accepted (exactly what the restricted script reads):
    {"event": "BADGE_TAP", "badge_id": str, "holder_name": str, "timestamp": float}
    {"event": "DOOR_OPEN", "timestamp": float}
Also accepted, if the firmware sends them (see hardware/README.md, limitation 1):
    {"event": "DOOR_CLOSE" | "DOOR_CLOSED" | "DOOR_SHUT", "timestamp": float}
Backwards compatible with the earlier repo format:
    {"badge_uid": str, "device_id": str, "door_sensor": "OPEN"|"CLOSED"}
"""
from dataclasses import dataclass, field
from typing import Any, Optional

_ALIASES = {
    "BADGE_TAP": "BADGE_TAP",
    "CARD_TAP": "BADGE_TAP",
    "DOOR_OPEN": "DOOR_OPEN",
    "DOOR_OPENED": "DOOR_OPEN",
    "DOOR_CLOSE": "DOOR_CLOSE",
    "DOOR_CLOSED": "DOOR_CLOSE",
    "DOOR_SHUT": "DOOR_CLOSE",
}


@dataclass
class HardwareEvent:
    kind: str                      # BADGE_TAP | DOOR_OPEN | DOOR_CLOSE
    ts: float
    badge_id: Optional[str] = None
    holder_name: Optional[str] = None
    raw: dict = field(default_factory=dict)


def normalize_ts(value: Any, now: float) -> float:
    """Accept epoch seconds or epoch ms. ESP32 uptime millis or junk -> server time."""
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return now
    if ts > 1e12:          # epoch milliseconds
        ts /= 1000.0
    if ts < 1_600_000_000 or abs(ts - now) > 3600:
        return now          # uptime counter or badly-set clock
    return ts


def parse_hardware(data: dict, now: float) -> Optional[HardwareEvent]:
    if not isinstance(data, dict):
        return None
    kind = _ALIASES.get(str(data.get("event") or "").strip().upper())
    badge_id = data.get("badge_id")

    if kind is None and data.get("badge_uid"):          # legacy repo format
        kind, badge_id = "BADGE_TAP", data.get("badge_uid")
    if kind is None and str(data.get("door_sensor", "")).upper() in ("OPEN", "CLOSED"):
        kind = "DOOR_OPEN" if str(data["door_sensor"]).upper() == "OPEN" else "DOOR_CLOSE"
    if kind is None:
        return None

    return HardwareEvent(
        kind=kind,
        ts=normalize_ts(data.get("timestamp"), now),
        badge_id=str(badge_id).strip().upper() if badge_id else None,
        holder_name=data.get("holder_name"),
        raw=data,
    )
