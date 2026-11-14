"""
The five required demonstration scenarios, run against the real correlator
with a controlled clock. Run:  pytest -q
"""
import pytest

from backend.app.adapters.hardware import parse_hardware
from backend.app.adapters.vision import Crossing, parse_vision
from backend.app.config import Settings
from backend.app.core.correlator import Correlator
from backend.app.core.frames import FrameStore
from backend.app.db import Store
from backend.app.reports.pdf import build_incident_pdf

T0 = 1_800_000_000.0


@pytest.fixture
def eng(tmp_path):
    s = Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 't.db'}",
                 held_open_threshold_s=10, session_window_s=8, camera_grace_s=3,
                 unauth_decision_delay_s=2)
    return Correlator(s, Store(s.database_url), FrameStore())


def hw(eng, event, t, **kw):
    # exact restricted-script payload
    return eng.handle_hardware(parse_hardware({"event": event, "timestamp": t, **kw}, t), now=t)


def cross(eng, tid, t, direction="IN"):
    return eng.handle_crossing(Crossing(str(tid), direction, t), now=t)


def types(eng):
    return sorted(i["type"] for i in eng.store.list_incidents())


def test_normal_entry(eng):
    hw(eng, "BADGE_TAP", T0, badge_id="E2806892", holder_name="Dr. Sarah Connor")
    hw(eng, "DOOR_OPEN", T0 + 1)
    msgs = cross(eng, 1, T0 + 2)
    hw(eng, "DOOR_CLOSE", T0 + 4)
    eng.tick(now=T0 + 20)
    assert any(m["type"] == "ENTRY" for m in msgs)
    assert types(eng) == []
    assert eng.store.list_records()[0]["holder"] == "Dr. Sarah Connor"


def test_tailgating(eng):
    hw(eng, "BADGE_TAP", T0, badge_id="E2806892", holder_name="Dr. Sarah Connor")
    hw(eng, "DOOR_OPEN", T0 + 1)
    cross(eng, 1, T0 + 2)
    cross(eng, 2, T0 + 3)
    eng.tick(now=T0 + 5)
    incs = eng.store.list_incidents()
    assert [i["type"] for i in incs] == ["TAILGATING"]
    inc = incs[0]
    assert inc["extra_persons"] == 1 and inc["badge"]["badge_id"] == "E2806892"
    assert inc["risk"]["score"] >= 45 and inc["snapshots"]
    # a third person updates the same incident and raises the score
    cross(eng, 3, T0 + 4)
    inc2 = eng.store.list_incidents()[0]
    assert inc2["id"] == inc["id"] and inc2["extra_persons"] == 2
    assert inc2["risk"]["score"] > inc["risk"]["score"]


def test_same_track_not_double_counted(eng):
    hw(eng, "BADGE_TAP", T0, badge_id="E2806892")
    cross(eng, 7, T0 + 1)
    cross(eng, 7, T0 + 1.5)          # jitter on the line -> duplicate
    assert types(eng) == []
    assert eng.counts["in"] == 1


def test_unauthorized_entry(eng):
    cross(eng, 9, T0)
    assert types(eng) == []          # waits for a late badge event
    eng.tick(now=T0 + 3)
    assert types(eng) == ["UNAUTHORIZED_ENTRY"]


def test_late_badge_event_claims_crossing(eng):
    cross(eng, 4, T0 + 0.5)          # camera event processed first
    hw(eng, "BADGE_TAP", T0, badge_id="E2806892")   # badge tapped at T0, arrives late
    eng.tick(now=T0 + 5)
    assert types(eng) == []


def test_forced_door(eng):
    msgs = hw(eng, "DOOR_OPEN", T0)
    assert any(m["type"] == "FORCED_ENTRY" and m["status"] == "BREACH" for m in msgs)
    assert types(eng) == ["FORCED_DOOR"]


def test_door_after_6s_is_forced(eng):
    hw(eng, "BADGE_TAP", T0, badge_id="E2806892")
    hw(eng, "DOOR_OPEN", T0 + 7)
    assert types(eng) == ["FORCED_DOOR"]


def test_rejected_badge_then_door_is_forced(eng):
    hw(eng, "BADGE_TAP", T0, badge_id="FFFF0000")
    hw(eng, "DOOR_OPEN", T0 + 1)
    assert types(eng) == ["FORCED_DOOR", "UNAUTHORIZED_BADGE"]
    forced = [i for i in eng.store.list_incidents() if i["type"] == "FORCED_DOOR"][0]
    assert any(b["factor"] == "Rejected badges" for b in forced["risk"]["breakdown"])


def test_door_held_open(eng):
    hw(eng, "DOOR_CLOSE", T0 - 5)     # firmware supports close events
    hw(eng, "BADGE_TAP", T0, badge_id="E2806892")
    hw(eng, "DOOR_OPEN", T0 + 1)
    eng.tick(now=T0 + 8)
    assert types(eng) == []
    eng.tick(now=T0 + 12)
    assert types(eng) == ["DOOR_HELD_OPEN"]
    hw(eng, "DOOR_CLOSE", T0 + 30)
    inc = eng.store.list_incidents()[0]
    assert inc["door"]["open_duration_s"] == 29.0


def test_held_open_disabled_without_close_events(eng):
    hw(eng, "BADGE_TAP", T0, badge_id="E2806892")
    hw(eng, "DOOR_OPEN", T0 + 1)
    eng.tick(now=T0 + 60)
    assert types(eng) == []


def test_legacy_vision_payload(eng):
    hw(eng, "BADGE_TAP", T0, badge_id="E2806892")
    for c in parse_vision({"persons_detected": 2, "timestamp": T0 + 1}, T0 + 1):
        eng.handle_crossing(c, now=T0 + 1)
    assert types(eng) == ["TAILGATING"]


def test_esp32_uptime_timestamp_is_replaced():
    evt = parse_hardware({"event": "BADGE_TAP", "badge_id": "x", "timestamp": 123456}, T0)
    assert evt.ts == T0


def test_pdf_report(eng, tmp_path):
    hw(eng, "BADGE_TAP", T0, badge_id="E2806892", holder_name="Dr. Sarah Connor")
    cross(eng, 1, T0 + 1)
    cross(eng, 2, T0 + 2)
    inc = eng.store.list_incidents()[0]
    pdf = build_incident_pdf(inc, eng.s.snapshot_dir)
    assert pdf[:4] == b"%PDF" and len(pdf) > 5000
