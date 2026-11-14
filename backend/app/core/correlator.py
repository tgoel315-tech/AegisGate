"""
Correlation engine — Features 2, 3 and 4 live here.

Inputs (already normalised by the adapters):
  * HardwareEvent  BADGE_TAP / DOOR_OPEN / DOOR_CLOSE
  * Crossing       one per unique track id, direction IN / OUT

How the three sources are correlated
  1. An AUTHORISED badge tap opens an AccessSession for SESSION_WINDOW_S seconds
     that allows ALLOWED_PER_TAP people through.
  2. Each inbound crossing is matched to the newest session whose window
     (plus CAMERA_GRACE_S for late camera events) contains the crossing time.
       - within the allowance            -> authorised entry (entry/exit record)
       - beyond the allowance            -> TAILGATING incident (one per session,
                                            updated for every extra person)
       - no session                      -> held for UNAUTH_DECISION_DELAY_S in case
                                            the badge event is late, then
                                            UNAUTHORIZED_ENTRY incident
  3. DOOR_OPEN with no authorised tap in the previous FORCED_DOOR_WINDOW_S (6 s,
     same as the restricted script) -> FORCED_DOOR incident.
     Door open longer than HELD_OPEN_THRESHOLD_S -> DOOR_HELD_OPEN incident.
  4. Outbound crossings are counted and close the oldest open entry record.
  5. The same (track id, direction) inside CROSSING_DEDUPE_S is ignored.

Every handler returns a list of WebSocket messages for the dashboard.
"""
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .. import badges
from ..adapters.hardware import HardwareEvent
from ..adapters.vision import Crossing
from ..config import Settings
from ..db import Store
from .frames import FrameStore, decode_b64_image, placeholder_frame
from .risk import RiskContext, gate_risk, score_incident

LEGACY_TYPE = {"FORCED_DOOR": "FORCED_ENTRY"}   # names the restricted script broadcasts
TITLES = {
    "TAILGATING": "Tailgating",
    "UNAUTHORIZED_ENTRY": "Unauthorised entry",
    "FORCED_DOOR": "Forced door",
    "DOOR_HELD_OPEN": "Door held open",
    "UNAUTHORIZED_BADGE": "Rejected badge",
}


def hhmmss(ts: Optional[float]) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "--:--:--"


@dataclass
class AccessSession:
    id: str
    badge_id: Optional[str]
    holder: str
    opened_at: float
    expires_at: float
    allowed: int
    in_crossings: List[dict] = field(default_factory=list)
    door_opened_at: Optional[float] = None
    door_closed_at: Optional[float] = None
    incident_id: Optional[str] = None

    def summary(self) -> dict:
        return {"id": self.id, "badge_id": self.badge_id, "holder": self.holder,
                "opened_at": self.opened_at, "expires_at": self.expires_at,
                "allowed": self.allowed, "in_count": len(self.in_crossings),
                "door_opened_at": self.door_opened_at, "door_closed_at": self.door_closed_at}


class Correlator:
    def __init__(self, settings: Settings, store: Store, frames: FrameStore):
        self.s = settings
        self.store = store
        self.frames = frames
        self.lock = threading.RLock()
        self._reset_state()
        self._restore_counts()

    def _restore_counts(self) -> None:
        """Rebuild crossing counters from the database after a backend restart."""
        for e in self.store.list_events(limit=100_000):
            if e["kind"] == "SYSTEM" and e["title"] == "System reset":
                break
            data = e.get("data") or {}
            if e["kind"] == "CROSSING" and data.get("direction") in ("IN", "OUT"):
                self.counts["in" if data["direction"] == "IN" else "out"] += 1
                self.crossers.add(str(data.get("track_id")))

    # ------------------------------------------------------------------ state
    def _reset_state(self) -> None:
        self.sessions: List[AccessSession] = []
        self.pending: List[Tuple[Crossing, float]] = []
        self.seen: Dict[Tuple[str, str], float] = {}
        self.door = {"state": "UNKNOWN", "since": None, "authorized": None,
                     "session_id": None, "held_incident_id": None, "forced_incident_id": None}
        self.close_event_seen = False
        self.last_badge: Optional[dict] = None
        self.last_auth_tap_ts: Optional[float] = None
        self.last_forced_at: Optional[float] = None
        self.denied_taps: deque = deque(maxlen=50)
        self.counts = {"in": 0, "out": 0}
        self.crossers: set = set()
        self.last_breach_at = 0.0
        self.open_unauth: Optional[Tuple[str, float]] = None
        self.version = 0

    def reset(self) -> List[dict]:
        with self.lock:
            self.store.reset()
            self._reset_state()
            self.store.add_event(self.s.gate_id, "SYSTEM", "System reset", "All records cleared")
            self.version += 1
            return [{"type": "SYSTEM_RESET"}]

    # ------------------------------------------------------------ hardware
    def handle_hardware(self, evt: HardwareEvent, now: Optional[float] = None) -> List[dict]:
        now = now or time.time()
        with self.lock:
            if evt.kind == "BADGE_TAP":
                msgs = self._badge(evt, now)
            elif evt.kind == "DOOR_OPEN":
                msgs = self._door_open(evt, now)
            elif evt.kind == "DOOR_CLOSE":
                msgs = self._door_close(evt, now)
            else:
                msgs = []
            self.version += 1
            return msgs

    def _badge(self, evt: HardwareEvent, now: float) -> List[dict]:
        info = badges.lookup(evt.badge_id)
        holder_name = badges.clean_holder(evt.holder_name)
        authorized = info is not None or (self.s.authorize_by_holder_name and holder_name is not None)
        holder = holder_name or (info or {}).get("name") or "Unknown holder"
        self.last_badge = {"time": evt.ts, "holder_name": holder, "badge_id": evt.badge_id,
                           "authorized": authorized}
        msgs: List[dict] = []

        if not authorized:
            self.denied_taps.append(evt.ts)
            self.store.add_event(self.s.gate_id, "BADGE", f"Badge rejected · {evt.badge_id or 'no id'}",
                                 "Not on the authorised list — no access session opened",
                                 data=self.last_badge, ts=evt.ts, severity="LOW")
            inc = self._new_incident("UNAUTHORIZED_BADGE", evt.ts,
                                     f"Rejected badge {evt.badge_id or '(no id)'} at {hhmmss(evt.ts)}",
                                     badge=self.last_badge)
            msgs.append({"type": "BADGE_DENIED", "badge": self.last_badge})
            msgs.append(self._finalize(inc, now, created=True))
            return msgs

        session = AccessSession(
            id=f"ses_{uuid.uuid4().hex[:8]}", badge_id=evt.badge_id, holder=holder,
            opened_at=evt.ts, expires_at=evt.ts + self.s.session_window_s,
            allowed=self.s.allowed_per_tap)
        self.sessions.append(session)
        self.last_auth_tap_ts = evt.ts
        self.store.add_event(self.s.gate_id, "BADGE", f"Badge tap · {holder}",
                             f"{evt.badge_id or '—'} · access granted for {self.s.session_window_s:.0f} s",
                             data=self.last_badge, ts=evt.ts)
        # Same shape the restricted script broadcasts.
        msgs.append({"type": "GATE_STATUS", "status": "UNLOCKED",
                     "holder": {"time": evt.ts, "holder_name": holder, "badge_id": evt.badge_id}})

        # A late badge event can still claim crossings that are waiting.
        still_pending = []
        for crossing, deadline in sorted(self.pending, key=lambda p: p[0].ts):
            if self._session_for(crossing.ts) is session:
                msgs += self._assign(session, crossing, self._snapshot_for(crossing), now)
            else:
                still_pending.append((crossing, deadline))
        self.pending = still_pending
        return msgs

    def _door_open(self, evt: HardwareEvent, now: float) -> List[dict]:
        authorized = (self.last_auth_tap_ts is not None
                      and 0 <= evt.ts - self.last_auth_tap_ts <= self.s.forced_door_window_s)
        session = self._session_for(evt.ts) if authorized else None
        self.door.update(state="OPEN", since=evt.ts, authorized=authorized,
                         session_id=session.id if session else None,
                         held_incident_id=None, forced_incident_id=None)
        msgs = [{"type": "DOOR", "state": "OPEN", "authorized": authorized, "timestamp": evt.ts}]

        if authorized:
            if session:
                session.door_opened_at = evt.ts
            gap = evt.ts - self.last_auth_tap_ts
            self.store.add_event(self.s.gate_id, "DOOR", "Door opened",
                                 f"Authorised · {gap:.1f} s after badge tap", ts=evt.ts)
            return msgs

        self.last_forced_at = evt.ts
        detail = ("No badge tap yet" if self.last_auth_tap_ts is None
                  else f"Last authorised tap {evt.ts - self.last_auth_tap_ts:.0f} s earlier (limit "
                       f"{self.s.forced_door_window_s:.0f} s)")
        self.store.add_event(self.s.gate_id, "DOOR", "Door opened without authorisation", detail,
                             ts=evt.ts, severity="HIGH")
        inc = self._new_incident("FORCED_DOOR", evt.ts,
                                 "CRITICAL: Door forced open without valid card tap!",
                                 door={"opened_at": evt.ts, "closed_at": None, "open_duration_s": None,
                                       "authorized": False, "detail": detail},
                                 badge=self.last_badge)
        self._attach_frame(inc, "door forced")
        self.door["forced_incident_id"] = inc["id"]
        msgs.append(self._finalize(inc, now, created=True))
        return msgs

    def _door_close(self, evt: HardwareEvent, now: float) -> List[dict]:
        self.close_event_seen = True
        opened = self.door.get("since") if self.door["state"] == "OPEN" else None
        duration = (evt.ts - opened) if opened else None
        msgs = [{"type": "DOOR", "state": "CLOSED", "timestamp": evt.ts}]
        linked = []
        for s in self.sessions:
            if s.id == self.door.get("session_id"):
                s.door_closed_at = evt.ts
                if s.incident_id:
                    linked.append(s.incident_id)
        self.store.add_event(self.s.gate_id, "DOOR", "Door closed",
                             f"Open for {duration:.0f} s" if duration is not None else "", ts=evt.ts)
        for inc_id in [self.door.get("held_incident_id"), self.door.get("forced_incident_id")] + linked:
            inc = self.store.get_incident(inc_id) if inc_id else None
            if inc:
                inc.setdefault("door", {}).update(opened_at=inc["door"].get("opened_at") or opened,
                                                  closed_at=evt.ts, open_duration_s=round(duration or 0, 1))
                msgs.append(self._finalize(inc, now, created=False))
        self.door.update(state="CLOSED", since=evt.ts, authorized=None, session_id=None,
                         held_incident_id=None, forced_incident_id=None)
        return msgs

    # -------------------------------------------------------------- vision
    def handle_crossing(self, c: Crossing, now: Optional[float] = None) -> List[dict]:
        now = now or time.time()
        with self.lock:
            key = (c.track_id, c.direction)
            last = self.seen.get(key)
            if last is not None and abs(c.ts - last) < self.s.crossing_dedupe_s:
                return []                                    # duplicate report of same crossing
            self.seen[key] = c.ts
            self.version += 1

            msgs = [{"type": "CROSSING", "track_id": c.track_id, "direction": c.direction,
                     "timestamp": c.ts}]
            self.crossers.add(c.track_id)
            if c.direction == "OUT":
                self.counts["out"] += 1
                rec = self.store.close_oldest_open_record(c.ts)
                who = (rec or {}).get("holder") or f"track {c.track_id}"
                self.store.add_event(self.s.gate_id, "CROSSING", f"Exit · {who}",
                                     f"Track {c.track_id} crossed OUT", ts=c.ts,
                                     data={"direction": "OUT", "track_id": c.track_id})
                return msgs

            self.counts["in"] += 1
            snapshot = self._snapshot_for(c)
            self.store.add_event(self.s.gate_id, "CROSSING", f"Track {c.track_id} crossed IN",
                                 f"confidence {c.confidence:.2f}" if c.confidence else c.source,
                                 data={"snapshot": snapshot, "direction": "IN", "track_id": c.track_id},
                                 ts=c.ts)
            session = self._session_for(c.ts)
            if session:
                msgs += self._assign(session, c, snapshot, now)
            else:
                self.pending.append((c, now + self.s.unauth_decision_delay_s))
                c.snapshot_b64 = None                        # already saved to disk
                c.snapshot_file = snapshot
            return msgs

    def _assign(self, session: AccessSession, c: Crossing, snapshot: str, now: float) -> List[dict]:
        authorized = len(session.in_crossings) < session.allowed
        entry = {"track_id": c.track_id, "direction": "IN", "ts": c.ts, "snapshot": snapshot,
                 "authorized": authorized, "confidence": c.confidence}
        session.in_crossings.append(entry)

        if authorized:
            rec = self.store.add_record(self.s.gate_id, session.badge_id, session.holder, c.track_id, c.ts)
            self.store.add_event(self.s.gate_id, "ENTRY", f"Authorised entry · {session.holder}",
                                 f"Track {c.track_id} matched badge {session.badge_id or '—'}", ts=c.ts)
            return [{"type": "ENTRY", "status": "NORMAL",
                     "message": "1 Person Verified. Normal Passage.", "record": rec}]

        extra = len(session.in_crossings) - session.allowed
        badge = {"badge_id": session.badge_id, "holder_name": session.holder, "time": session.opened_at,
                 "authorized": True}
        message = (f"VIOLATION: Tailgating detected! {len(session.in_crossings)} persons entered on 1 tap "
                   f"by {session.holder}.")
        door = {"opened_at": session.door_opened_at, "closed_at": session.door_closed_at,
                "open_duration_s": None, "authorized": True if session.door_opened_at else None}
        existing = self.store.get_incident(session.incident_id) if session.incident_id else None
        if existing:
            existing.update(crossings=list(session.in_crossings), extra_persons=extra, message=message,
                            session=session.summary(), door=door)
            existing["snapshots"] = [x["snapshot"] for x in session.in_crossings if x.get("snapshot")]
            return [self._finalize(existing, now, created=False)]

        inc = self._new_incident("TAILGATING", c.ts, message, badge=badge, session=session.summary(),
                                 crossings=list(session.in_crossings), door=door)
        inc["extra_persons"] = extra
        inc["snapshots"] = [x["snapshot"] for x in session.in_crossings if x.get("snapshot")]
        session.incident_id = inc["id"]
        return [self._finalize(inc, now, created=True)]

    # ---------------------------------------------------------------- tick
    def tick(self, now: Optional[float] = None) -> List[dict]:
        """Runs every 0.5 s: resolves waiting crossings and door timers."""
        now = now or time.time()
        msgs: List[dict] = []
        with self.lock:
            still = []
            for c, deadline in self.pending:
                session = self._session_for(c.ts)
                if session:
                    msgs += self._assign(session, c, c.snapshot_file, now)
                elif now >= deadline:
                    msgs += self._unauthorized(c, now)
                else:
                    still.append((c, deadline))
            self.pending = still

            held_enabled = self.close_event_seen or not self.s.held_open_requires_close_event
            if (held_enabled and self.door["state"] == "OPEN" and not self.door["held_incident_id"]
                    and self.door["since"] and now - self.door["since"] > self.s.held_open_threshold_s):
                msgs += self._held_open(now)

            cutoff = now - 120
            self.sessions = [s for s in self.sessions if s.expires_at > cutoff]
            self.seen = {k: v for k, v in self.seen.items() if v > now - 60}
            if msgs:
                self.version += 1
        return msgs

    def _unauthorized(self, c: Crossing, now: float) -> List[dict]:
        entry = {"track_id": c.track_id, "direction": "IN", "ts": c.ts,
                 "snapshot": c.snapshot_file, "authorized": False,
                 "confidence": c.confidence}
        if self.open_unauth and c.ts - self.open_unauth[1] <= 10:
            inc = self.store.get_incident(self.open_unauth[0])
            if inc:
                inc["crossings"].append(entry)
                inc["snapshots"] = [x["snapshot"] for x in inc["crossings"] if x.get("snapshot")]
                n = len(inc["crossings"])
                inc["message"] = f"{n} people crossed the tripwire with no authorised badge tap."
                self.open_unauth = (inc["id"], c.ts)
                return [self._finalize(inc, now, created=False)]
        inc = self._new_incident("UNAUTHORIZED_ENTRY", c.ts,
                                 f"Track {c.track_id} crossed IN with no authorised access session.",
                                 crossings=[entry], badge=self.last_badge)
        inc["snapshots"] = [entry["snapshot"]] if entry["snapshot"] else []
        self.open_unauth = (inc["id"], c.ts)
        return [self._finalize(inc, now, created=True)]

    def _held_open(self, now: float) -> List[dict]:
        since = self.door["since"]
        session = next((s for s in self.sessions if s.id == self.door.get("session_id")), None)
        inc = self._new_incident(
            "DOOR_HELD_OPEN", now,
            f"Door has been open for more than {self.s.held_open_threshold_s:.0f} s.",
            door={"opened_at": since, "closed_at": None, "open_duration_s": round(now - since, 1),
                  "authorized": self.door.get("authorized")},
            session=session.summary() if session else None,
            badge=self.last_badge if self.door.get("authorized") else None)
        if session:
            inc["crossings"] = list(session.in_crossings)
        self._attach_frame(inc, "door held open")
        self.door["held_incident_id"] = inc["id"]
        self.store.add_event(self.s.gate_id, "DOOR", "Door held open",
                             f"Open since {hhmmss(since)}", ts=now, severity="MEDIUM")
        return [self._finalize(inc, now, created=True)]

    # ------------------------------------------------------------ helpers
    def _session_for(self, ts: float) -> Optional[AccessSession]:
        matches = [s for s in self.sessions
                   if s.opened_at - 1.0 <= ts <= s.expires_at + self.s.camera_grace_s]
        return max(matches, key=lambda s: s.opened_at) if matches else None

    def _save_jpeg(self, jpeg: bytes) -> str:
        name = f"snap_{uuid.uuid4().hex[:12]}.jpg"
        (self.s.snapshot_dir / name).write_bytes(jpeg)
        return name

    def _snapshot_for(self, c: Crossing) -> str:
        if c.snapshot_file:
            return c.snapshot_file
        jpeg = decode_b64_image(c.snapshot_b64) or self.frames.fresh_jpeg() or placeholder_frame(
            f"TRACK {c.track_id} CROSSED {c.direction}", "No camera frame available (simulated event)")
        name = self._save_jpeg(jpeg)
        c.snapshot_file = name
        return name

    def _attach_frame(self, inc: dict, label: str) -> None:
        jpeg = self.frames.fresh_jpeg()
        if jpeg is None:
            jpeg = placeholder_frame(label.upper(), "No camera frame available at the time")
        inc.setdefault("snapshots", []).append(self._save_jpeg(jpeg))

    def _new_incident(self, itype: str, ts: float, message: str, badge=None, session=None,
                      crossings=None, door=None) -> dict:
        return {
            "id": f"INC-{datetime.fromtimestamp(ts).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
            "type": itype, "title": TITLES.get(itype, itype), "gate_id": self.s.gate_id,
            "created_at": ts, "updated_at": ts, "status": "OPEN", "message": message,
            "badge": badge, "session": session, "crossings": crossings or [], "door": door or {},
            "snapshots": [], "extra_persons": 0, "risk": {"score": 0, "severity": "LOW", "breakdown": []},
        }

    def _risk_context(self, inc: dict, now: float) -> RiskContext:
        others = [i for i in self.store.list_incidents(limit=50, since=now - 600) if i["id"] != inc["id"]]
        return RiskContext(
            door_forced_recent=bool(self.last_forced_at and now - self.last_forced_at <= 60),
            denied_taps_recent=len([t for t in self.denied_taps if now - t <= 300]),
            door_held_now=self.door["state"] == "OPEN" and bool(self.door.get("held_incident_id")),
            other_incidents_recent=len(others),
            held_open_threshold_s=self.s.held_open_threshold_s,
        )

    def _finalize(self, inc: dict, now: float, created: bool) -> dict:
        inc["updated_at"] = now
        inc["risk"] = score_incident(inc, self._risk_context(inc, now))
        self.store.save_incident(inc)
        if inc["type"] != "UNAUTHORIZED_BADGE":
            self.last_breach_at = now
        if created:
            self.store.add_event(self.s.gate_id, "INCIDENT", f"{inc['title']} · risk {inc['risk']['score']}",
                                 inc["message"], ts=inc["created_at"], severity=inc["risk"]["severity"],
                                 incident_id=inc["id"])
        badge = inc.get("badge") or {}
        return {
            # Same keys as the restricted script's alert broadcast, plus the full incident.
            "type": LEGACY_TYPE.get(inc["type"], inc["type"]),
            "status": "BREACH" if inc["type"] != "UNAUTHORIZED_BADGE" else "WARNING",
            "message": inc["message"], "timestamp": inc["created_at"],
            "holder_name": badge.get("holder_name"), "badge_id": badge.get("badge_id"),
            "snapshot": f"/snapshots/{inc['snapshots'][0]}" if inc.get("snapshots") else None,
            "event": "INCIDENT_CREATED" if created else "INCIDENT_UPDATED",
            "incident": {k: inc[k] for k in ("id", "type", "title", "created_at", "updated_at")}
                        | {"score": inc["risk"]["score"], "severity": inc["risk"]["severity"]},
        }

    # --------------------------------------------------------------- views
    def state(self, now: Optional[float] = None) -> dict:
        now = now or time.time()
        with self.lock:
            active = [s for s in self.sessions if s.opened_at <= now <= s.expires_at]
            session = max(active, key=lambda s: s.opened_at) if active else None
            if now - self.last_breach_at < 10:
                status = "BREACH"
            elif self.door["state"] == "OPEN" and self.door.get("held_incident_id"):
                status = "HELD OPEN"
            elif self.door["state"] == "OPEN":
                status = "OPEN"
            elif session:
                status = "UNLOCKED"
            else:
                status = "SECURED"
            recent = self.store.list_incidents(limit=100, since=now - self.s.risk_window_s)
            vision = dict(self.frames.stats or {})
            return {
                "gate_id": self.s.gate_id,
                "status": status,
                "door": {"state": self.door["state"], "since": self.door["since"],
                         "open_for_s": round(now - self.door["since"], 1)
                         if self.door["state"] == "OPEN" and self.door["since"] else None,
                         "authorized": self.door.get("authorized"),
                         "close_events_supported": self.close_event_seen},
                "session": ({**session.summary(), "remaining_s": round(session.expires_at - now, 1)}
                            if session else None),
                "last_badge": self.last_badge,
                "counts": {"in": self.counts["in"], "out": self.counts["out"],
                           "unique_crossers": len(self.crossers),
                           "inside": self.store.count_inside()},
                "vision": {"online": self.frames.online,
                           "unique_people": vision.get("unique_people"),
                           "active_tracks": vision.get("active_tracks"),
                           "fps": vision.get("fps"), "detector": vision.get("detector")},
                "risk": gate_risk(recent, now, self.s.risk_window_s),
                "version": self.version,
            }
