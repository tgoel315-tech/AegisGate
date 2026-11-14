"""
Direction-aware virtual tripwire (Feature 2).

Each tracked person keeps a *stable side* of the line (A or B). A crossing is
reported only when the person is seen on the other side, outside a dead band
around the line, for `confirm_frames` consecutive frames. After a crossing the
same track can't produce another one for `cooldown_s` seconds. Together these
stop jitter near the line from counting the same person repeatedly.

    vertical line   : side A = left of the line,  side B = right
    horizontal line : side A = above the line,    side B = below
    A -> B = IN, B -> A = OUT   (swap with invert=True)
"""
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional, Tuple


@dataclass
class TripwireConfig:
    orientation: str = "vertical"       # vertical | horizontal
    position: float = 0.5               # 0..1 of frame width (vertical) or height (horizontal)
    band_px: int = 25                   # dead band either side of the line
    invert: bool = False                # swap IN / OUT
    confirm_frames: int = 2
    cooldown_s: float = 2.0
    forget_after_s: float = 10.0


@dataclass
class _TrackState:
    side: Optional[str] = None
    candidate: Optional[str] = None
    candidate_n: int = 0
    last_cross: float = -1e9
    last_seen: float = field(default_factory=time.time)


class Tripwire:
    def __init__(self, cfg: TripwireConfig, frame_w: int, frame_h: int):
        self.cfg = cfg
        self.w, self.h = frame_w, frame_h
        self.states: Dict[str, _TrackState] = {}

    # ---------------------------------------------------------- geometry
    @property
    def coord(self) -> int:
        size = self.w if self.cfg.orientation == "vertical" else self.h
        return int(size * self.cfg.position)

    def endpoints(self) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        c = self.coord
        if self.cfg.orientation == "vertical":
            return (c, 0), (c, self.h)
        return (0, c), (self.w, c)

    def side_of(self, point: Tuple[float, float]) -> Optional[str]:
        v = point[0] if self.cfg.orientation == "vertical" else point[1]
        if v < self.coord - self.cfg.band_px:
            return "A"
        if v > self.coord + self.cfg.band_px:
            return "B"
        return None                       # inside the dead band: no decision

    def in_label_side(self) -> str:
        """Which side is 'inside' (where IN crossings end up)."""
        return "A" if self.cfg.invert else "B"

    # ---------------------------------------------------------- controls
    def move(self, delta: float) -> None:
        self.cfg.position = min(0.95, max(0.05, self.cfg.position + delta))

    def toggle_orientation(self) -> None:
        self.cfg.orientation = "horizontal" if self.cfg.orientation == "vertical" else "vertical"
        self.states.clear()

    def reverse(self) -> None:
        self.cfg.invert = not self.cfg.invert

    def resize(self, w: int, h: int) -> None:
        self.w, self.h = w, h

    # ---------------------------------------------------------- logic
    def update(self, track_id, point: Tuple[float, float], now: Optional[float] = None) -> Optional[str]:
        """Feed one track position. Returns 'IN', 'OUT' or None."""
        now = time.time() if now is None else now
        tid = str(track_id)
        st = self.states.setdefault(tid, _TrackState(last_seen=now))
        st.last_seen = now
        side = self.side_of(point)
        if side is None:
            return None
        if st.side is None:                # first confident position = where they came from
            st.side = side
            return None
        if side == st.side:
            st.candidate, st.candidate_n = None, 0
            return None

        if st.candidate == side:
            st.candidate_n += 1
        else:
            st.candidate, st.candidate_n = side, 1
        if st.candidate_n < self.cfg.confirm_frames:
            return None

        previous, st.side = st.side, side
        st.candidate, st.candidate_n = None, 0
        if now - st.last_cross < self.cfg.cooldown_s:
            return None
        st.last_cross = now
        direction = "IN" if (previous, side) == ("A", "B") else "OUT"
        if self.cfg.invert:
            direction = "OUT" if direction == "IN" else "IN"
        return direction

    def forget_stale(self, now: Optional[float] = None, active: Iterable = ()) -> None:
        now = time.time() if now is None else now
        keep = {str(a) for a in active}
        self.states = {k: v for k, v in self.states.items()
                       if k in keep or now - v.last_seen < self.cfg.forget_after_s}
