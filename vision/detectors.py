"""
Person detection + multi-object tracking.

Primary (ML):  YOLOv8n person detector + ByteTrack multi-object tracker
               via the `ultralytics` package. Runs on a laptop CPU.
Fallback:      OpenCV HOG + upper-body Haar cascade with a centroid tracker,
               used automatically if ultralytics / torch isn't installed,
               or on request with --classic.

Both return the same thing: a list of Track(track_id, box=(x, y, w, h), conf).
The camera only tracks movement. It never identifies who someone is.
"""
import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import List, Tuple

import cv2
import numpy as np


@dataclass
class Track:
    track_id: int
    box: Tuple[int, int, int, int]
    conf: float

    @property
    def center(self) -> Tuple[int, int]:
        x, y, w, h = self.box
        return x + w // 2, y + h // 2


class YoloByteTrack:
    def __init__(self, model: str = "yolov8n.pt", conf: float = 0.4, imgsz: int = 640, device=None):
        from ultralytics import YOLO          # imported lazily so the fallback works without torch
        self.model = YOLO(model)
        self.conf, self.imgsz, self.device = conf, imgsz, device
        self.name = f"{model.replace('.pt', '')} + ByteTrack"

    def update(self, frame) -> List[Track]:
        result = self.model.track(frame, persist=True, classes=[0], conf=self.conf, imgsz=self.imgsz,
                                  tracker="bytetrack.yaml", device=self.device, verbose=False)[0]
        boxes = result.boxes
        if boxes is None or boxes.id is None:
            return []
        out = []
        for xyxy, tid, c in zip(boxes.xyxy.cpu().numpy(), boxes.id.int().cpu().tolist(),
                                boxes.conf.cpu().tolist()):
            x1, y1, x2, y2 = (int(v) for v in xyxy)
            out.append(Track(int(tid), (x1, y1, x2 - x1, y2 - y1), float(c)))
        return out


class CentroidTracker:
    def __init__(self, max_disappeared: int = 15, max_distance: int = 120):
        self.next_id = 1
        self.objects: "OrderedDict[int, Tuple[int, int]]" = OrderedDict()
        self.boxes = {}
        self.missing = {}
        self.max_disappeared, self.max_distance = max_disappeared, max_distance

    def _register(self, c, box):
        self.objects[self.next_id], self.boxes[self.next_id], self.missing[self.next_id] = c, box, 0
        self.next_id += 1

    def _drop(self, oid):
        for d in (self.objects, self.boxes, self.missing):
            d.pop(oid, None)

    def update(self, rects) -> List[Tuple[int, tuple]]:
        if not rects:
            for oid in list(self.missing):
                self.missing[oid] += 1
                if self.missing[oid] > self.max_disappeared:
                    self._drop(oid)
            return []
        cents = [(x + w // 2, y + h // 2) for x, y, w, h in rects]
        if not self.objects:
            for c, b in zip(cents, rects):
                self._register(c, b)
        else:
            ids, old = list(self.objects), list(self.objects.values())
            pairs = sorted(((math.dist(o, c), i, j) for i, o in enumerate(old) for j, c in enumerate(cents)))
            used_i, used_j = set(), set()
            for d, i, j in pairs:
                if i in used_i or j in used_j or d > self.max_distance:
                    continue
                oid = ids[i]
                self.objects[oid], self.boxes[oid], self.missing[oid] = cents[j], rects[j], 0
                used_i.add(i)
                used_j.add(j)
            for i, oid in enumerate(ids):
                if i not in used_i:
                    self.missing[oid] += 1
                    if self.missing[oid] > self.max_disappeared:
                        self._drop(oid)
            for j, (c, b) in enumerate(zip(cents, rects)):
                if j not in used_j:
                    self._register(c, b)
        return [(oid, self.boxes[oid]) for oid in self.objects if self.missing.get(oid, 1) == 0]


class ClassicDetector:
    name = "HOG + Haar (classic fallback)"

    def __init__(self):
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.upper = self._cascade("haarcascade_upperbody.xml")
        self.face = self._cascade("haarcascade_frontalface_default.xml")
        self.tracker = CentroidTracker()

    @staticmethod
    def _cascade(name):
        try:
            c = cv2.CascadeClassifier(cv2.data.haarcascades + name)
            return None if c.empty() else c
        except Exception:
            return None

    def _detect(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        rects, scores = [], []
        uppers = self.upper.detectMultiScale(gray, 1.12, 5, minSize=(100, 100)) if self.upper else []
        for (x, y, w, h) in uppers:
            rects.append([int(x), int(y), int(w), int(h)]); scores.append(0.85)
        boxes, weights = self.hog.detectMultiScale(frame, winStride=(8, 8), padding=(8, 8), scale=1.05)
        for (x, y, w, h), wt in zip(boxes, np.ravel(weights) if len(weights) else []):
            if wt > 0.45 and w >= 80 and h >= 140:
                rects.append([int(x), int(y), int(w), int(h)]); scores.append(float(wt))
        if not rects and self.face is not None:
            for (x, y, w, h) in self.face.detectMultiScale(gray, 1.15, 5, minSize=(60, 60)):
                rects.append([max(0, int(x - w * 0.4)), max(0, int(y - h * 0.2)), int(w * 1.8), int(h * 2.5)])
                scores.append(0.7)
        if not rects:
            return []
        keep = cv2.dnn.NMSBoxes(rects, scores, 0.4, 0.4)
        return [tuple(rects[i]) for i in np.array(keep).flatten()] if len(keep) else []

    def update(self, frame) -> List[Track]:
        return [Track(oid, box, 0.0) for oid, box in self.tracker.update(self._detect(frame))]


def build_detector(classic: bool = False, model: str = "yolov8n.pt", conf: float = 0.4):
    if not classic:
        try:
            return YoloByteTrack(model=model, conf=conf)
        except Exception as exc:
            print(f"[vision] YOLO unavailable ({exc!r}); using the classic detector.")
    return ClassicDetector()
