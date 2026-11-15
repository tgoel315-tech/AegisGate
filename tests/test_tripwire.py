from vision.tripwire import Tripwire, TripwireConfig


def walk(wire, tid, xs, y=200, t0=0.0, dt=0.1):
    out = []
    for i, x in enumerate(xs):
        d = wire.update(tid, (x, y), now=t0 + i * dt)
        if d:
            out.append(d)
    return out


def test_left_to_right_is_in():
    w = Tripwire(TripwireConfig(), 640, 480)
    assert walk(w, 1, [100, 200, 280, 340, 360, 400, 450]) == ["IN"]


def test_right_to_left_is_out():
    w = Tripwire(TripwireConfig(), 640, 480)
    assert walk(w, 1, [500, 400, 360, 300, 280, 200, 150]) == ["OUT"]


def test_invert_swaps_direction():
    w = Tripwire(TripwireConfig(invert=True), 640, 480)
    assert walk(w, 1, [100, 200, 360, 400, 450]) == ["OUT"]


def test_jitter_on_line_counts_once():
    w = Tripwire(TripwireConfig(), 640, 480)
    xs = [100, 200, 350, 360, 330, 310, 350, 365, 330, 360, 400, 420]
    assert walk(w, 1, xs) == ["IN"]


def test_two_people_counted_separately():
    w = Tripwire(TripwireConfig(), 640, 480)
    assert walk(w, 1, [100, 200, 400, 420]) == ["IN"]
    assert walk(w, 2, [120, 220, 410, 430], t0=0.5) == ["IN"]


def test_horizontal_line():
    w = Tripwire(TripwireConfig(orientation="horizontal", position=0.5), 640, 480)
    out = [w.update(1, (300, y), now=i * 0.1) for i, y in enumerate([50, 150, 300, 320, 400])]
    assert [d for d in out if d] == ["IN"]


def test_cooldown_blocks_instant_bounce():
    w = Tripwire(TripwireConfig(cooldown_s=2.0), 640, 480)
    assert walk(w, 1, [100, 400, 410, 100, 90], dt=0.1) == ["IN"]


def test_person_swaying_near_line_never_counts():
    """The reported bug: someone sitting/standing at the line produced IN/OUT/IN/OUT."""
    import math
    w = Tripwire(TripwireConfig(), 640, 480)
    xs = [320 + 60 * math.sin(i / 3) for i in range(300)]       # +/-60 px around the line, 30 s
    assert walk(w, 1, xs) == []


def test_walk_in_then_back_out_counts_both():
    w = Tripwire(TripwireConfig(), 640, 480)
    xs = [80, 150, 250, 330, 420, 500, 520] + [520] * 40 + [500, 420, 330, 250, 150, 90]
    assert walk(w, 1, xs) == ["IN", "OUT"]


def test_arm_distance_scales_with_frame():
    w = Tripwire(TripwireConfig(arm_ratio=0.12), 1280, 720)
    assert w.arm_px == 153
