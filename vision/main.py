"""
AegisGate vision module (owner: Abhinav).

Opens the webcam, detects and tracks people, and sends one event per unique
track that crosses the virtual tripwire (IN or OUT) to the backend.

Run from the repository root:
    python -m vision.main                       # webcam 0, vertical line in the middle
    python -m vision.main --camera 1            # external USB camera
    python -m vision.main --orientation horizontal --position 0.6 --invert
    python -m vision.main --source demo.mp4     # test with a recorded video
    python -m vision.main --classic             # no YOLO / torch needed

Keys in the preview window:
    a / d   move the line (left/right or up/down)     o   switch vertical / horizontal
    The grey dashed lines are the arm zone: walk from beyond one to beyond the other to count.
    r       reverse IN/OUT direction                  m   mirror camera on/off
    c       clear counters                            q   quit
"""
import argparse
import os
import time

import cv2

from .client import BackendClient
from .detectors import build_detector
from .tripwire import Tripwire, TripwireConfig

PINK = (139, 61, 255)       # BGR of #FF3D8B
NAVY = (61, 27, 15)         # BGR of #0F1B3D
WHITE = (255, 255, 255)
MIN_HITS_FOR_UNIQUE = 5     # frames a track must live before it counts as a person


def parse_args():
    p = argparse.ArgumentParser(description="AegisGate webcam person tracker")
    p.add_argument("--camera", type=int, default=int(os.getenv("CAMERA_INDEX", 0)))
    p.add_argument("--source", default=None, help="video file instead of a webcam")
    p.add_argument("--backend", default=os.getenv("BACKEND_URL", "http://localhost:8000"))
    p.add_argument("--gate-id", default=os.getenv("GATE_ID", "gate-01"))
    p.add_argument("--orientation", choices=["vertical", "horizontal"],
                   default=os.getenv("TRIPWIRE_ORIENTATION", "vertical"))
    p.add_argument("--position", type=float, default=float(os.getenv("TRIPWIRE_POSITION", 0.5)))
    p.add_argument("--invert", action="store_true", default=os.getenv("TRIPWIRE_INVERT", "0") == "1",
                   help="swap IN and OUT")
    p.add_argument("--arm", type=float, default=float(os.getenv("TRIPWIRE_ARM", 0.12)),
                   help="how far past the line (fraction of frame) a person must go to count")
    p.add_argument("--no-mirror", action="store_true", help="don't flip the webcam image")
    p.add_argument("--model", default=os.getenv("YOLO_MODEL", "yolov8n.pt"))
    p.add_argument("--conf", type=float, default=0.4)
    p.add_argument("--classic", action="store_true", help="use HOG/Haar instead of YOLO")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--headless", action="store_true", help="no preview window")
    return p.parse_args()


def open_capture(args):
    if args.source:
        return cv2.VideoCapture(args.source)
    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        cap = cv2.VideoCapture(args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    return cap


def draw(frame, tracks, wire, counts, unique, fps, detector_name, online, flashes):
    h, w = frame.shape[:2]
    for (ax1, ay1), (ax2, ay2) in wire.arm_lines():          # "clearly on a side" boundaries
        for i in range(0, max(h, w), 14):                    # dashed
            if wire.cfg.orientation == "vertical":
                cv2.line(frame, (ax1, i), (ax1, min(i + 6, h)), (120, 120, 120), 1)
            else:
                cv2.line(frame, (i, ay1), (min(i + 6, w), ay1), (120, 120, 120), 1)
    (x1, y1), (x2, y2) = wire.endpoints()
    cv2.line(frame, (x1, y1), (x2, y2), PINK, 2)
    # IN arrow
    c = wire.coord
    if wire.cfg.orientation == "vertical":
        a, b = ((c - 40, 40), (c + 40, 40)) if wire.in_label_side() == "B" else ((c + 40, 40), (c - 40, 40))
    else:
        a, b = ((40, c - 40), (40, c + 40)) if wire.in_label_side() == "B" else ((40, c + 40), (40, c - 40))
    cv2.arrowedLine(frame, a, b, PINK, 2, tipLength=0.35)
    cv2.putText(frame, "IN", (b[0] + 6, b[1] + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, PINK, 1, cv2.LINE_AA)

    now = time.time()
    for t in tracks:
        x, y, bw, bh = t.box
        col = PINK if now < flashes.get(t.track_id, 0) else WHITE
        cv2.rectangle(frame, (x, y), (x + bw, y + bh), col, 2)
        label = f"ID {t.track_id}"
        cv2.rectangle(frame, (x, max(0, y - 18)), (x + 8 + 9 * len(label), y), col, -1)
        cv2.putText(frame, label, (x + 4, max(12, y - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, NAVY, 1, cv2.LINE_AA)
        cv2.circle(frame, t.center, 3, col, -1)

    bar = f"IN {counts['IN']}   OUT {counts['OUT']}   PEOPLE {unique}   {fps:4.1f} FPS"
    cv2.rectangle(frame, (0, h - 26), (w, h), NAVY, -1)
    cv2.putText(frame, bar, (10, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1, cv2.LINE_AA)
    status = f"{detector_name} | backend {'online' if online else 'OFFLINE'}"
    cv2.putText(frame, status, (w - 10 - 7 * len(status), h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                WHITE if online else PINK, 1, cv2.LINE_AA)


def main():
    args = parse_args()
    detector = build_detector(classic=args.classic, model=args.model, conf=args.conf)
    client = BackendClient(args.backend)
    cap = open_capture(args)
    if not cap.isOpened():
        raise SystemExit(f"Could not open camera {args.camera}. Close other apps using it or try --camera 1.")

    ok, frame = cap.read()
    if not ok:
        raise SystemExit("Camera opened but returned no frames.")
    h, w = frame.shape[:2]
    wire = Tripwire(TripwireConfig(orientation=args.orientation, position=args.position,
                                   arm_ratio=args.arm, invert=args.invert), w, h)
    mirror = not args.no_mirror and not args.source
    counts = {"IN": 0, "OUT": 0}
    hits, people, flashes = {}, set(), {}
    fps, frames_n, t_fps = 0.0, 0, time.time()
    print(f"[vision] {detector.name} | camera {args.source or args.camera} | backend {args.backend}")

    while True:
        ok, frame = cap.read()
        if not ok:
            if args.source:
                break
            time.sleep(0.02)
            continue
        if mirror:
            frame = cv2.flip(frame, 1)
        fh, fw = frame.shape[:2]
        if (fw, fh) != (wire.w, wire.h):
            wire.resize(fw, fh)

        tracks = detector.update(frame)
        now = time.time()
        for t in tracks:
            hits[t.track_id] = hits.get(t.track_id, 0) + 1
            if hits[t.track_id] >= MIN_HITS_FOR_UNIQUE:
                people.add(t.track_id)
            direction = wire.update(t.track_id, t.center, now)
            if direction:
                counts[direction] += 1
                flashes[t.track_id] = now + 1.0
                evidence = frame.copy()
                x, y, bw, bh = t.box
                cv2.rectangle(evidence, (x, y), (x + bw, y + bh), PINK, 3)
                cv2.putText(evidence, f"ID {t.track_id} {direction}  {time.strftime('%H:%M:%S')}",
                            (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, PINK, 2, cv2.LINE_AA)
                (x1, y1), (x2, y2) = wire.endpoints()
                cv2.line(evidence, (x1, y1), (x2, y2), PINK, 2)
                ok_j, jpg = cv2.imencode(".jpg", evidence, [cv2.IMWRITE_JPEG_QUALITY, 75])
                client.send_crossing(t.track_id, direction, now, t.conf, jpg.tobytes() if ok_j else None,
                                     gate_id=args.gate_id)
                print(f"[vision] track {t.track_id} crossed {direction}")
        wire.forget_stale(now, active=[t.track_id for t in tracks])

        frames_n += 1
        if now - t_fps >= 1.0:
            fps, frames_n, t_fps = frames_n / (now - t_fps), 0, now

        draw(frame, tracks, wire, counts, len(people), fps, detector.name, client.online, flashes)
        ok_j, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok_j:
            client.push_frame(jpg.tobytes(), {
                "unique_people": len(people), "active_tracks": len(tracks), "fps": round(fps, 1),
                "detector": detector.name, "in": counts["IN"], "out": counts["OUT"],
                "tripwire": {"orientation": wire.cfg.orientation, "position": round(wire.cfg.position, 3),
                             "invert": wire.cfg.invert}})

        if args.headless:
            continue
        cv2.imshow("AegisGate vision", frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        elif key == ord("a"):
            wire.move(-0.02)
        elif key == ord("d"):
            wire.move(0.02)
        elif key == ord("o"):
            wire.toggle_orientation()
        elif key == ord("r"):
            wire.reverse()
            print(f"[vision] IN/OUT reversed (invert={wire.cfg.invert})")
        elif key == ord("m"):
            mirror = not mirror
        elif key == ord("c"):
            counts = {"IN": 0, "OUT": 0}
            people.clear()

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
