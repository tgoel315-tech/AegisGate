"""
Direction-aware virtual tripwire (Feature 2).

Arming rule: a crossing is counted only when a person
  1. was seen clearly on one side, at least `arm_ratio` of the frame away from the line
     (the track is "armed" on that side), and then
  2. is seen clearly on the OTHER side, again at least that far away,
     for `confirm_frames` consecutive frames.
Someone standing or swaying near the line never satisfies both, so they are
never counted. After a crossing, the same track can't count again for
`cooldown_s` seconds.

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
    arm_ratio: float = 0.12             # how far past the line counts as "clearly on a side"
    band_px: int = 25                   # minimum arm distance in pixels
    invert: bool = False                # swap IN / OUT
    confirm_frames: int = 2
    cooldown_s: float = 3.0
    forget_after_s: float = 10.0


@dataclass
class _TrackState:
    armed: Optional[str] = None         # side where the track was last clearly seen
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
    def size(self) -> int:
        return self.w if self.cfg.orientation == "vertical" else self.h

    @property
    def coord(self) -> int:
        return int(self.size * self.cfg.position)

    @property
    def arm_px(self) -> int:
        return max(self.cfg.band_px, int(self.size * self.cfg.arm_ratio))

    def _line(self, c: int) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        if self.cfg.orientation == "vertical":
            return (c, 0), (c, self.h)
        return (0, c), (self.w, c)

    def endpoints(self):
        return self._line(self.coord)

    def arm_lines(self):
        """The two 'clearly on a side' boundaries, for drawing."""
        return self._line(self.coord - self.arm_px), self._line(self.coord + self.arm_px)

    def side_of(self, point: Tuple[float, float]) -> Tuple[str, bool]:
        """Returns (side, far_enough)."""
        v = point[0] if self.cfg.orientation == "vertical" else point[1]
        d = v - self.coord
        return ("A" if d < 0 else "B"), abs(d) >= self.arm_px

    def in_label_side(self) -> str:
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
        st = self.states.setdefault(str(track_id), _TrackState(last_seen=now))
        st.last_seen = now
        side, far = self.side_of(point)

        if not far:                              # near the line: never decides anything
            st.candidate_n = 0
            return None
        if st.armed is None:                     # first clear position = where they came from
            st.armed = side
            return None
        if side == st.armed:
            st.candidate_n = 0
            return None

        st.candidate_n += 1                      # clearly on the opposite side
        if st.candidate_n < self.cfg.confirm_frames:
            return None
        previous, st.armed, st.candidate_n = st.armed, side, 0
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
