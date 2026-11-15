import time
import config

class ZoneManager:
    """
    Manages the two regions divided vertically by the red line in the middle:
    - REGION 1 (LEFT of Vertical Red Line): Public corridor / approach area (Groups can roam freely with 0 alerts)
    - VERTICAL RED LINE (Middle X of screen): Checkpoint boundary
    - REGION 2 (RIGHT of Vertical Red Line): Secure / monitored interior zone
    """
    def __init__(self, frame_w, frame_h):
        self.w = frame_w
        self.h = frame_h

        # Vertical Red Divider Line right in the middle X
        self.divider_x = int(frame_w * config.DIVIDER_LINE_X_RATIO)

        # Access & Authorization State
        self.authorized_credits = 0
        self.transit_window_expiry = 0.0
        self.total_card_taps = 0
        self.total_authorized_entered = 0
        self.total_tailgating_breaches = 0
        self.total_unauthorized_crossings = 0

    def tap_badge(self, count=1):
        """Simulates or receives an RFID badge tap event."""
        now = time.time()
        self.total_card_taps += count
        self.authorized_credits += count
        self.transit_window_expiry = now + config.TRANSIT_WINDOW_SECONDS
        return self.total_card_taps

    def is_transit_window_active(self):
        """Returns True if the transit authorization window is open."""
        return time.time() < self.transit_window_expiry and self.authorized_credits > 0

    def get_remaining_window_time(self):
        """Returns remaining seconds of authorized window."""
        return max(0.0, self.transit_window_expiry - time.time())

    def determine_region(self, cx, cy):
        """
        Determines which region a person is currently in:
        - 'REGION_1': Left of the vertical red line (Public / Roaming allowed)
        - 'ON_LINE': Directly touching or crossing the vertical red line
        - 'REGION_2': Right of the vertical red line (Secure zone)
        """
        threshold = config.CORRIDOR_THRESHOLD_PX
        if abs(cx - self.divider_x) <= threshold:
            return "ON_LINE"
        elif cx < self.divider_x:
            return "REGION_1"
        else:
            return "REGION_2"

    def evaluate_crossing(self, obj_id, track_data):
        """
        Evaluates if an individual has crossed the vertical red line from Left (Region 1) to Right (Region 2).
        Enforces:
        - If roaming only in Region 1: NO ALARMS (returns 'NONE')
        - If crossed with active badge tap: 'AUTHORIZED' (Green)
        - If crossed right behind an authorized user: 'TAILGATING' (Red Alarm)
        - If crossed with 0 badge taps: 'UNAUTHORIZED_CROSSING' (Red Alarm)
        """
        traj = track_data.get('trajectory', [])
        cx, cy = track_data['centroid']

        if len(traj) < 2:
            return "NONE"

        # Check trajectory progression: was previously on the Left (x < divider_x) and now on the Right (cx > divider_x + 10)
        min_prev_x = min([pt[0] for pt in traj[:-1]])
        now_in_region_2 = (cx > self.divider_x + 10)
        started_in_region_1 = (min_prev_x < self.divider_x)

        crossed = started_in_region_1 and now_in_region_2

        if crossed:
            if self.authorized_credits > 0:
                self.authorized_credits -= 1
                self.total_authorized_entered += 1
                return "AUTHORIZED"
            else:
                rem_time = self.get_remaining_window_time()
                if rem_time > 0.0 or (time.time() - self.transit_window_expiry < 3.0):
                    # Slipped through during or immediately after someone else's window!
                    self.total_tailgating_breaches += 1
                    return "TAILGATING"
                else:
                    # Crossed with zero authorized badge taps
                    self.total_unauthorized_crossings += 1
                    return "UNAUTHORIZED_CROSSING"

        return "NONE"

    def adjust_divider_x(self, delta_x):
        """Interactively moves the vertical red divider line left or right."""
        self.divider_x = max(50, min(self.w - 50, self.divider_x + delta_x))
