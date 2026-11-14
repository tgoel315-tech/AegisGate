"""
Hardware simulator — sends events in EXACTLY the format the restricted
hardware script consumes, so the backend can be tested without the ESP32.

Format (derived from hardware/restricted/restricted_hardware_script.py):
    POST /api/event/hardware
    {"event": "BADGE_TAP", "badge_id": "...", "holder_name": "...", "timestamp": <epoch s>}
    {"event": "DOOR_OPEN", "timestamp": <epoch s>}
    {"event": "DOOR_CLOSE", "timestamp": <epoch s>}   <- see README: not in the restricted script

Usage:
    python hardware/simulator.py tap --badge E2806892 --name "Dr. Sarah Connor"
    python hardware/simulator.py tap --badge FFFF0000            (unknown badge)
    python hardware/simulator.py door-open
    python hardware/simulator.py door-close
"""
import argparse
import time

import requests


def send(backend: str, payload: dict) -> None:
    url = backend.rstrip("/") + "/api/event/hardware"
    r = requests.post(url, json=payload, timeout=5,
                      headers={"ngrok-skip-browser-warning": "1"})
    print(r.status_code, r.text)


def main() -> None:
    p = argparse.ArgumentParser(description="AegisGate ESP32 simulator")
    p.add_argument("action", choices=["tap", "door-open", "door-close"])
    p.add_argument("--backend", default="http://localhost:8000")
    p.add_argument("--badge", default="E2806892")
    p.add_argument("--name", default=None)
    a = p.parse_args()

    now = time.time()
    if a.action == "tap":
        payload = {"event": "BADGE_TAP", "badge_id": a.badge, "timestamp": now}
        if a.name:
            payload["holder_name"] = a.name
    elif a.action == "door-open":
        payload = {"event": "DOOR_OPEN", "timestamp": now}
    else:
        payload = {"event": "DOOR_CLOSE", "timestamp": now}
    send(a.backend, payload)


if __name__ == "__main__":
    main()
