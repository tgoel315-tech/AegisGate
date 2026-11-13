import numpy as np
from collections import OrderedDict
import math
import config

class CCTVTracker:
    """
    Centroid and trajectory tracker optimized for CCTV choke-point surveillance.
    Maintains:
    - Persistent person IDs
    - Full movement trajectory vectors (dx, dy, speed, heading angle)
    - Sequential zone history (e.g., ['APPROACH', 'PORTAL', 'SECURE'])
    - Occlusion resilience buffer
    """
    def __init__(self, max_disappeared=15, max_distance=85):
        self.next_object_id = 1
        self.objects = OrderedDict()          # object_id -> (cx, cy)
        self.boxes = OrderedDict()            # object_id -> (x, y, w, h)
        self.disappeared = OrderedDict()      # object_id -> missed frame count
        self.trajectories = OrderedDict()     # object_id -> list of recent (cx, cy)
        self.zone_history = OrderedDict()     # object_id -> list of visited zone names
        self.has_entered = set()              # Set of object_ids confirmed inside secure zone
        self.max_disappeared = max_disappeared
        self.max_distance = max_distance

    def register(self, centroid, box, initial_zone="APPROACH"):
        obj_id = self.next_object_id
        self.objects[obj_id] = centroid
        self.boxes[obj_id] = box
        self.disappeared[obj_id] = 0
        self.trajectories[obj_id] = [centroid]
        self.zone_history[obj_id] = [initial_zone]
        self.next_object_id += 1
        return obj_id

    def deregister(self, object_id):
        if object_id in self.objects:
            del self.objects[object_id]
        if object_id in self.boxes:
            del self.boxes[object_id]
        if object_id in self.disappeared:
            del self.disappeared[object_id]
        if object_id in self.trajectories:
            del self.trajectories[object_id]
        if object_id in self.zone_history:
            del self.zone_history[object_id]

    def update(self, rects, current_zones=None):
        """
        Updates object positions with newly detected bounding boxes.
        current_zones: optional dict of {index: zone_name} for newly detected bounding boxes
        """
        if len(rects) == 0:
            for object_id in list(self.disappeared.keys()):
                self.disappeared[object_id] += 1
                if self.disappeared[object_id] > self.max_disappeared:
                    self.deregister(object_id)
            return self.get_active_tracks()

        input_centroids = np.zeros((len(rects), 2), dtype="int")
        for i, (x, y, w, h) in enumerate(rects):
            input_centroids[i] = (int(x + w / 2.0), int(y + h / 2.0))

        if len(self.objects) == 0:
            for i in range(len(input_centroids)):
                init_z = current_zones.get(i, "APPROACH") if current_zones else "APPROACH"
                self.register(input_centroids[i], rects[i], initial_zone=init_z)
        else:
            object_ids = list(self.objects.keys())
            object_centroids = list(self.objects.values())

            # Distance matrix
            D = np.zeros((len(object_centroids), len(input_centroids)), dtype="float")
            for r in range(len(object_centroids)):
                for c in range(len(input_centroids)):
                    dx = object_centroids[r][0] - input_centroids[c][0]
                    dy = object_centroids[r][1] - input_centroids[c][1]
                    D[r, c] = math.hypot(dx, dy)

            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]

            used_rows = set()
            used_cols = set()

            for (row, col) in zip(rows, cols):
                if row in used_rows or col in used_cols:
                    continue

                if D[row, col] > self.max_distance:
                    continue

                obj_id = object_ids[row]
                new_pt = input_centroids[col]

                # Update position
                self.objects[obj_id] = new_pt
                self.boxes[obj_id] = rects[col]
                self.disappeared[obj_id] = 0

                # Append to trajectory history (keep last N points)
                traj = self.trajectories[obj_id]
                traj.append(new_pt)
                if len(traj) > config.TRAJECTORY_HISTORY_LEN:
                    traj.pop(0)

                # Record zone if changed
                if current_zones and col in current_zones:
                    curr_z = current_zones[col]
                    if len(self.zone_history[obj_id]) == 0 or self.zone_history[obj_id][-1] != curr_z:
                        self.zone_history[obj_id].append(curr_z)

                used_rows.add(row)
                used_cols.add(col)

            unused_rows = set(range(0, D.shape[0])).difference(used_rows)
            unused_cols = set(range(0, D.shape[1])).difference(used_cols)

            for row in unused_rows:
                obj_id = object_ids[row]
                self.disappeared[obj_id] += 1
                if self.disappeared[obj_id] > self.max_disappeared:
                    self.deregister(obj_id)

            for col in unused_cols:
                init_z = current_zones.get(col, "APPROACH") if current_zones else "APPROACH"
                self.register(input_centroids[col], rects[col], initial_zone=init_z)

        return self.get_active_tracks()

    def get_velocity_vector(self, object_id):
        """
        Calculates the velocity vector (vx, vy), average speed,
        and motion state ('LOITERING', 'PASSING_SIDEWAYS', 'ENTERING')
        """
        traj = self.trajectories.get(object_id, [])
        if len(traj) < 3:
            return 0.0, 0.0, 0.0, "TRACKING_INIT"

        # Calculate displacement from oldest to newest point in buffer
        old_x, old_y = traj[0]
        cur_x, cur_y = traj[-1]
        frames_span = len(traj) - 1

        vx = (cur_x - old_x) / frames_span
        vy = (cur_y - old_y) / frames_span
        speed = math.hypot(vx, vy)

        if speed < config.LOITERING_VELOCITY_MAX:
            state = "LOITERING"
        elif abs(vx) > abs(vy) * 1.5:
            state = "PASSING_SIDEWAYS"
        elif vy > config.MIN_CROSSING_VELOCITY:
            state = "ENTERING_FORWARD"
        elif vy < -config.MIN_CROSSING_VELOCITY:
            state = "EXITING_BACKWARD"
        else:
            state = "ROAMING"

        return vx, vy, speed, state

    def get_active_tracks(self):
        """Returns dict of active object tracks with boxes, centroids, and zone history."""
        active = {}
        for obj_id in self.objects.keys():
            vx, vy, speed, state = self.get_velocity_vector(obj_id)
            active[obj_id] = {
                'centroid': self.objects[obj_id],
                'box': self.boxes[obj_id],
                'trajectory': self.trajectories.get(obj_id, []),
                'zones': self.zone_history.get(obj_id, []),
                'vx': vx,
                'vy': vy,
                'speed': speed,
                'motion_state': state
            }
        return active
