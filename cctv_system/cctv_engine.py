import cv2
import numpy as np
import time
import base64
import json
import threading
from urllib import request as url_request

from tracker import CCTVTracker
from zone_manager import ZoneManager
import config

class CCTVEngine:
    def __init__(self, frame_w=config.FRAME_WIDTH, frame_h=config.FRAME_HEIGHT):
        print("[INIT] Initializing Clean CCTV Anti-Tailgating Monitor...")
        self.w = frame_w
        self.h = frame_h
        self.laterally_invert = config.LATERALLY_INVERT

        # 1. Multi-modal Person Detectors (High precision, noise-filtered)
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

        cascade_path = cv2.data.haarcascades + "haarcascade_upperbody.xml"
        self.upper_cascade = cv2.CascadeClassifier(cascade_path)

        face_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.face_cascade = cv2.CascadeClassifier(face_path)

        # 2. Tracking & Region Manager
        self.tracker = CCTVTracker(max_disappeared=15, max_distance=100)
        self.zone_mgr = ZoneManager(frame_w, frame_h)

        # 3. System States & Alerts
        self.current_alert = None
        self.alert_expiry = 0.0
        self.backend_online = False
        self.last_backend_msg = "Standby"

        print("[OK] Clean CCTV Engine Ready.")
        print(f"     - Lateral Invert (Mirror): {'ENABLED' if self.laterally_invert else 'DISABLED'}")
        print(f"     - Vertical Red Line: Positioned at X={self.zone_mgr.divider_x}")

    def detect_persons(self, frame):
        """
        High-precision person detection.
        Rejects tiny noise patches, clothes folds, and artifacts.
        Only detects genuine human upper bodies, full bodies, or faces.
        """
        rects = []
        scores = []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 1. Upperbody Cascade (Primary for webcam / indoor views)
        # minSize=(100, 100) and minNeighbors=5 prevents false alarms on clothing/furniture
        upper_bodies = self.upper_cascade.detectMultiScale(
            gray, scaleFactor=1.12, minNeighbors=5, minSize=(100, 100)
        )
        for (x, y, w, h) in upper_bodies:
            rects.append([int(x), int(y), int(w), int(h)])
            scores.append(0.85)

        # 2. HOG Person Detector (High confidence threshold)
        boxes_hog, weights_hog = self.hog.detectMultiScale(
            frame, winStride=(8, 8), padding=(8, 8), scale=1.05
        )
        for (x, y, w, h), weight in zip(boxes_hog, weights_hog):
            # Only accept high-confidence detections of full human scale
            if weight > 0.45 and w >= 80 and h >= 140:
                rects.append([int(x), int(y), int(w), int(h)])
                scores.append(float(weight))

        # 3. Face Detector fallback (if upper body was missed)
        if len(rects) == 0:
            faces = self.face_cascade.detectMultiScale(
                gray, scaleFactor=1.15, minNeighbors=5, minSize=(60, 60)
            )
            for (x, y, w, h) in faces:
                # Estimate torso around the face
                bx = max(0, int(x - w * 0.4))
                by = max(0, int(y - h * 0.2))
                bw = int(w * 1.8)
                bh = int(h * 2.5)
                rects.append([bx, by, bw, bh])
                scores.append(0.70)

        if len(rects) == 0:
            return []

        # Non-Maximum Suppression to remove duplicate bounding boxes
        indices = cv2.dnn.NMSBoxes(rects, scores, 0.40, 0.40)
        filtered = []
        if len(indices) > 0:
            for i in indices.flatten():
                filtered.append(rects[i])
        return filtered

    def dispatch_event_async(self, event_type, frame, details=None):
        """Asynchronously dispatches snapshot and JSON event to backend."""
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 65]
        _, buffer = cv2.imencode('.jpg', frame, encode_param)
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')

        payload = {
            "source": "CCTV_CAMERA",
            "event": event_type,
            "card_taps": self.zone_mgr.total_card_taps,
            "authorized_entered": self.zone_mgr.total_authorized_entered,
            "tailgating_breaches": self.zone_mgr.total_tailgating_breaches,
            "unauthorized_crossings": self.zone_mgr.total_unauthorized_crossings,
            "credits_remaining": self.zone_mgr.authorized_credits,
            "snapshot_base64": f"data:image/jpeg;base64,{jpg_as_text}",
            "timestamp": time.time()
        }
        if details:
            payload.update(details)

        thread = threading.Thread(target=self._send_payload, args=(payload,))
        thread.daemon = True
        thread.start()

    def _send_payload(self, payload):
        try:
            data_bytes = json.dumps(payload).encode('utf-8')
            req = url_request.Request(
                config.BACKEND_URL,
                data=data_bytes,
                headers={'Content-Type': 'application/json'}
            )
            with url_request.urlopen(req, timeout=config.EVENT_TIMEOUT) as resp:
                status = resp.getcode()
                self.backend_online = (status == 200)
                self.last_backend_msg = f"HTTP {status}"
        except Exception:
            self.backend_online = False
            self.last_backend_msg = "Backend Offline"

    def draw_hud(self, frame, active_tracks, fps):
        """Clean, professional, uncluttered CCTV UI overlay."""
        h, w = frame.shape[:2]
        now = time.time()
        div_x = self.zone_mgr.divider_x

        is_window_active = self.zone_mgr.is_transit_window_active()
        rem_time = self.zone_mgr.get_remaining_window_time()

        # ----------------- 1. Clean Vertical Red Divider Line -----------------
        # Red line
        cv2.line(frame, (div_x, 0), (div_x, h), (0, 0, 255), 2)

        # Region Headers (Clean & Subdued)
        cv2.putText(frame, "PUBLIC ZONE", (div_x - 140, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.putText(frame, "SECURE ZONE", (div_x + 20, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 220, 255), 1, cv2.LINE_AA)

        # ----------------- 2. Clean Bounding Boxes (No Spider Webs) -----------------
        for obj_id, track in active_tracks.items():
            (x, y, bw, bh) = track['box']
            (cx, cy) = track['centroid']
            curr_region = self.zone_mgr.determine_region(cx, cy)

            if curr_region == "REGION_1":
                color = (220, 180, 100) # Cyan/Blue for public side
                label = f"Person #{obj_id}"
            elif curr_region == "ON_LINE":
                color = (0, 255, 255)   # Yellow when at boundary
                label = f"Person #{obj_id} [Crossing]"
            else:
                color = (0, 255, 100)   # Green for secure side
                label = f"Person #{obj_id} [Secure]"

            # Bounding box
            cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)

            # Compact tag pill above box
            (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(frame, (x, max(0, y - 20)), (x + lw + 6, y), color, -1)
            cv2.putText(frame, label, (x + 3, max(12, y - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)

        # ----------------- 3. Clean Compact Status Header -----------------
        # Dark header pill at top left
        cv2.rectangle(frame, (10, 10), (380, 48), (20, 20, 20), -1)

        if self.current_alert and now < self.alert_expiry:
            status_dot = (0, 0, 255) # Red
            status_text = f"ALARM: {self.current_alert}!"
            text_color = (0, 0, 255)
            cv2.rectangle(frame, (10, 10), (380, 48), (0, 0, 255), 2)
        elif is_window_active:
            status_dot = (0, 255, 100) # Green
            status_text = f"GATE ARMED ({rem_time:.1f}s) | 1 Person Allowed"
            text_color = (0, 255, 100)
            cv2.rectangle(frame, (10, 10), (380, 48), (0, 255, 100), 1)
        else:
            status_dot = (180, 180, 180) # Gray
            status_text = "GATE STANDBY | Public Area Ignored"
            text_color = (220, 220, 220)
            cv2.rectangle(frame, (10, 10), (380, 48), (60, 60, 60), 1)

        # Status Dot
        cv2.circle(frame, (25, 29), 5, status_dot, -1)
        cv2.putText(frame, status_text, (38, 33),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, text_color, 1, cv2.LINE_AA)

        # ----------------- 4. Compact Stats Pill (Top Right) -----------------
        stats_w, stats_h = 240, 50
        sx = w - stats_w - 10
        cv2.rectangle(frame, (sx, 10), (sx + stats_w, 10 + stats_h), (20, 20, 20), -1)
        cv2.rectangle(frame, (sx, 10), (sx + stats_w, 10 + stats_h), (60, 60, 60), 1)

        cv2.putText(frame, f"Card Taps : {self.zone_mgr.total_card_taps}  [Tap: 'T']", (sx + 10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 255, 255), 1, cv2.LINE_AA)
        
        breaches = self.zone_mgr.total_tailgating_breaches + self.zone_mgr.total_unauthorized_crossings
        breach_color = (0, 0, 255) if breaches > 0 else (180, 180, 180)
        cv2.putText(frame, f"Entered: {self.zone_mgr.total_authorized_entered} | Breaches: {breaches}", (sx + 10, 48),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, breach_color, 1, cv2.LINE_AA)

        # ----------------- 5. Minimalist Bottom Controls Bar -----------------
        cv2.rectangle(frame, (0, h - 25), (w, h), (15, 15, 15), -1)
        controls_text = f"FPS: {fps:.1f} | [A/D] Move Red Line | [T] Tap Card | [F] Mirror | [C] Reset | [Q] Quit"
        cv2.putText(frame, controls_text, (15, h - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1, cv2.LINE_AA)

    def trigger_alert(self, alert_text, duration=3.5):
        self.current_alert = alert_text
        self.alert_expiry = time.time() + duration

    def run(self, source=None):
        """Main real-time camera monitoring loop."""
        video_src = source if source is not None else config.CAMERA_SOURCE
        print(f"[START] Opening camera capture on: {video_src}...")

        if isinstance(video_src, int) or (isinstance(video_src, str) and video_src.isdigit()):
            cam_idx = int(video_src)
            cap = cv2.VideoCapture(cam_idx, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(cam_idx)
        else:
            cap = cv2.VideoCapture(video_src)

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.h)

        if not cap.isOpened():
            print(f"\n[ERROR] Could not open camera {video_src}.")
            print("Make sure your webcam is connected and not occupied by another app.\n")
            return

        print("[RUNNING] Clean CCTV Feed Active.")
        print("  - False-positive noise filter: Active.")
        print("  - Laterally Inverted (Mirror Mode): Active.")
        print(f"  - Vertical Red Line: X={self.zone_mgr.divider_x}.")
        print("  - Press 't' or 'SPACE' to simulate Card Tap.")
        print("  - Press 'a' / 'd' to move Vertical Line LEFT / RIGHT.")
        print("  - Press 'q' or 'ESC' to quit.\n")

        fps_start = time.time()
        fps_count = 0
        fps = 0.0

        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.03)
                continue

            # Mirror Horizontally (Lateral Invert)
            if self.laterally_invert:
                frame = cv2.flip(frame, 1)

            fps_count += 1
            if time.time() - fps_start >= 1.0:
                fps = fps_count / (time.time() - fps_start)
                fps_count = 0
                fps_start = time.time()

            # 1. Detect genuine persons (noise-filtered)
            detected_rects = self.detect_persons(frame)

            detected_regions = {}
            for i, (bx, by, bw, bh) in enumerate(detected_rects):
                cx = int(bx + bw / 2.0)
                cy = int(by + bh / 2.0)
                detected_regions[i] = self.zone_mgr.determine_region(cx, cy)

            # 2. Update tracker
            active_tracks = self.tracker.update(detected_rects, current_zones=detected_regions)

            # 3. Evaluate crossing of the vertical red line
            for obj_id, track in active_tracks.items():
                if obj_id in self.tracker.has_entered:
                    continue

                crossing_result = self.zone_mgr.evaluate_crossing(obj_id, track)

                if crossing_result == "AUTHORIZED":
                    self.tracker.has_entered.add(obj_id)
                    print(f"[VERIFIED] Person #{obj_id} entered securely (Card matched).")
                    self.dispatch_event_async("AUTHORIZED_ENTRY", frame, {"person_id": obj_id})

                elif crossing_result == "TAILGATING":
                    self.tracker.has_entered.add(obj_id)
                    print(f"[ALARM] TAILGATING DETECTED! Person #{obj_id} crossed without badge tap!")
                    self.trigger_alert(f"TAILGATING (Person #{obj_id})", duration=3.5)
                    self.dispatch_event_async("TAILGATING_BREACH", frame, {"person_id": obj_id})

                elif crossing_result == "UNAUTHORIZED_CROSSING":
                    self.tracker.has_entered.add(obj_id)
                    print(f"[ALARM] UNAUTHORIZED! Person #{obj_id} crossed with 0 badge taps!")
                    self.trigger_alert(f"UNAUTHORIZED (Person #{obj_id})", duration=3.5)
                    self.dispatch_event_async("UNAUTHORIZED_CROSSING", frame, {"person_id": obj_id})

            # 4. Render Clean HUD
            self.draw_hud(frame, active_tracks, fps)
            cv2.imshow(config.WINDOW_TITLE, frame)

            # 5. Handle Keyboard Controls
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:
                break
            elif key == ord('t') or key == 32:    # 't' or Space: Tap Card
                total = self.zone_mgr.tap_badge()
                print(f"[HARDWARE] Badge tapped! Total: {total}. Transit window open for {config.TRANSIT_WINDOW_SECONDS}s.")
                self.dispatch_event_async("CARD_TAPPED", frame, {"total_taps": total})
            elif key == ord('a'):                 # Move vertical line LEFT
                self.zone_mgr.adjust_divider_x(-15)
            elif key == ord('d'):                 # Move vertical line RIGHT
                self.zone_mgr.adjust_divider_x(15)
            elif key == ord('f'):                 # Toggle mirror mode
                self.laterally_invert = not self.laterally_invert
            elif key == ord('c'):                 # Reset counters
                self.zone_mgr.total_card_taps = 0
                self.zone_mgr.total_authorized_entered = 0
                self.zone_mgr.total_tailgating_breaches = 0
                self.zone_mgr.total_unauthorized_crossings = 0
                self.zone_mgr.authorized_credits = 0
                self.tracker.has_entered.clear()
                self.current_alert = None
                print("[RESET] All counters reset to 0.")
            elif key == ord('p'):                 # Manual snapshot
                self.dispatch_event_async("MANUAL_SNAPSHOT", frame)

        cap.release()
        cv2.destroyAllWindows()
        print("[FINISHED] CCTV Engine shut down cleanly.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Clean CCTV Anti-Tailgating & Region Monitor")
    parser.add_argument("--source", type=str, default=None, help="Camera index (e.g. 0)")
    args = parser.parse_args()

    src = args.source
    if src is not None and src.isdigit():
        src = int(src)

    engine = CCTVEngine()
    engine.run(source=src)
