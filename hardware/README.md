# Hardware interface (owner: Alok)

`restricted/restricted_hardware_script.py` is the restricted script, kept **verbatim**.
Nothing in AegisGate imports, edits or replaces it. The backend implements the same
HTTP contract through an adapter (`backend/app/adapters/hardware.py`).

## What the restricted script does

| Item | Detail |
|---|---|
| Transport | HTTP `POST` with a JSON body, plus a WebSocket at `/ws` for listeners |
| Endpoint | `POST /api/event/hardware` |
| Badge event | `{"event": "BADGE_TAP", "badge_id": str, "holder_name": str, "timestamp": float}` |
| Door event | `{"event": "DOOR_OPEN", "timestamp": float}` |
| Forced-door rule | `DOOR_OPEN` more than **6.0 s** after the last badge tap means forced entry |
| Vision endpoint | `POST /api/event/vision` with `{"persons_detected": int, "snapshot_base64": str}` |
| Broadcasts | `GATE_STATUS/UNLOCKED`, `FORCED_ENTRY` (status `BREACH`), `TAILGATING` (status `BREACH`) |
| Response | `{"status": "ok"}` (hardware), `{"status": "processed"}` (vision) |

AegisGate keeps all of the above: same paths, same field names, same 6.0 s rule and the
same broadcast `type` names. It returns the same `status` values too, so the ESP32 needs no change.

## Limitations of the fixed interface (please confirm with Alok)

1. **There is no door-closed event.** You can't detect "door held open" without one.
   The backend accepts `DOOR_CLOSE`, `DOOR_CLOSED` or `DOOR_SHUT` if the firmware sends any of them.
   Held-open detection switches on automatically the first time such an event arrives,
   or when you set `HELD_OPEN_REQUIRES_CLOSE_EVENT=false`. Until then, door-held-open
   incidents only appear in the simulator and demo scenarios.
2. **There is no explicit "denied" flag.** The backend decides authorisation itself:
   a tap is authorised if `badge_id` is in `backend/app/badges.py`, or if the
   firmware supplied a `holder_name` (configurable with `AUTHORIZE_BY_HOLDER_NAME`).
3. **There is no command channel back to the ESP32.** The backend **cannot** sound the
   buzzer, change LEDs or lock the door. The dashboard never claims it does.
4. **`timestamp` may be ESP32 uptime (millis), not epoch seconds.** Values that don't
   look like a recent epoch are replaced with the server's receive time.
5. **There is no gate id.** Everything is treated as gate `gate-01`.

## Connecting the real board

Step-by-step (Wi-Fi, laptop IP, firewall, checks): [`docs/CONNECT_EVERYTHING.md`](../docs/CONNECT_EVERYTHING.md#part-c--connect-the-esp32-hardware).

## Testing without the board

```bash
python hardware/simulator.py tap --badge E2806892 --name "Dr. Sarah Connor"
python hardware/simulator.py door-open
python hardware/simulator.py door-close
```
