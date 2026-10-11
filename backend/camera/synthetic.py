"""SIMULATED development camera.

Renders a synthetic top-down desk with colour-coded objects so the CV pipeline
and game mechanics can be exercised without hardware. It is only used when the
player explicitly selects it (or DESK_DEFENDER_SIMULATED=1). Every frame carries
a visible "SIMULATED" watermark and every API status reports is_simulated=True.
"""

import threading
import time
from typing import Dict, List, Optional

import cv2
import numpy as np

FRAME_W, FRAME_H = 1280, 720
# Play-area quad inside the synthetic frame (slight perspective, like a real phone mount).
SCENE_QUAD = [[170.0, 95.0], [1110.0, 95.0], [1175.0, 655.0], [105.0, 655.0]]
VIRTUAL_W, VIRTUAL_H = 1000, 700

# Pure key colours (BGR) used by the synthetic colour detector.
KIND_COLORS = {
    "book": (40, 40, 220),
    "bottle": (220, 160, 30),
    "cup": (30, 200, 230),
    "box": (40, 160, 60),
    "pencil holder": (200, 60, 200),
}
KIND_SIZES = {
    "book": (95, 135),
    "bottle": (52, 52),
    "cup": (58, 58),
    "box": (130, 110),
    "pencil holder": (56, 56),
}


class SyntheticDesk:
    """Scene state of the simulated desk; objects live in virtual battlefield coordinates."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counter = 0
        self.objects: Dict[str, Dict] = {}
        self.reset()
        src = np.array([[0, 0], [VIRTUAL_W, 0], [VIRTUAL_W, VIRTUAL_H], [0, VIRTUAL_H]], dtype=np.float32)
        self._to_frame = cv2.getPerspectiveTransform(src, np.array(SCENE_QUAD, dtype=np.float32))
        self._background = self._render_background()

    def reset(self) -> None:
        with self._lock:
            self.objects.clear()
            self._counter = 0
        for kind, x, y in [("book", 420, 220), ("book", 420, 500), ("bottle", 600, 350),
                           ("cup", 300, 360), ("box", 720, 140), ("pencil holder", 640, 520)]:
            self.add_object(kind, x, y)

    def add_object(self, kind: str, x: float, y: float) -> Dict:
        if kind not in KIND_COLORS:
            raise ValueError(f"Unknown synthetic object kind '{kind}'")
        with self._lock:
            self._counter += 1
            w, h = KIND_SIZES[kind]
            obj = {"id": f"sim_{self._counter}", "kind": kind, "x": float(x), "y": float(y), "w": w, "h": h}
            self.objects[obj["id"]] = obj
            return dict(obj)

    def move_object(self, obj_id: str, x: float, y: float) -> Optional[Dict]:
        with self._lock:
            obj = self.objects.get(obj_id)
            if not obj:
                return None
            obj["x"] = float(np.clip(x, 0, VIRTUAL_W))
            obj["y"] = float(np.clip(y, 0, VIRTUAL_H))
            return dict(obj)

    def remove_object(self, obj_id: str) -> bool:
        with self._lock:
            return self.objects.pop(obj_id, None) is not None

    def list_objects(self) -> List[Dict]:
        with self._lock:
            return [dict(o) for o in self.objects.values()]

    def _render_background(self) -> np.ndarray:
        frame = np.full((FRAME_H, FRAME_W, 3), (52, 58, 66), dtype=np.uint8)
        noise = np.random.default_rng(7).integers(0, 10, (FRAME_H, FRAME_W, 1), dtype=np.uint8)
        frame = cv2.add(frame, np.repeat(noise, 3, axis=2))
        pts = np.array(SCENE_QUAD, dtype=np.int32)
        cv2.fillPoly(frame, [pts], (92, 98, 104))
        cv2.polylines(frame, [pts], True, (230, 230, 230), 3)
        return frame

    def render(self) -> np.ndarray:
        frame = self._background.copy()
        for obj in self.list_objects():
            hw, hh = obj["w"] / 2, obj["h"] / 2
            corners = np.array([[[obj["x"] - hw, obj["y"] - hh], [obj["x"] + hw, obj["y"] - hh],
                                 [obj["x"] + hw, obj["y"] + hh], [obj["x"] - hw, obj["y"] + hh]]],
                               dtype=np.float32)
            poly = cv2.perspectiveTransform(corners, self._to_frame)[0].astype(np.int32)
            color = KIND_COLORS[obj["kind"]]
            if obj["kind"] in ("bottle", "cup", "pencil holder"):
                center = poly.mean(axis=0).astype(int)
                radius = int(np.linalg.norm(poly[0] - poly[2]) / 2.9)
                cv2.circle(frame, tuple(center), radius, color, -1)
            else:
                cv2.fillPoly(frame, [poly], color)
        cv2.rectangle(frame, (0, 0), (FRAME_W, 34), (0, 0, 0), -1)
        cv2.putText(frame, "SIMULATED CAMERA - DEVELOPMENT MODE (not a real camera feed)", (14, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2, cv2.LINE_AA)
        return frame


def detect_synthetic_objects(frame: np.ndarray, min_area: float = 500.0) -> List[Dict]:
    """Colour-key detector for the simulated desk. Real OpenCV contour analysis on the frame."""
    detections = []
    for kind, bgr in KIND_COLORS.items():
        lower = np.clip(np.array(bgr, dtype=np.int32) - 18, 0, 255).astype(np.uint8)
        upper = np.clip(np.array(bgr, dtype=np.int32) + 18, 0, 255).astype(np.uint8)
        mask = cv2.inRange(frame, lower, upper)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if area < min_area:
                continue
            x, y, w, h = cv2.boundingRect(c)
            solidity = area / max(1.0, cv2.contourArea(cv2.convexHull(c)))
            detections.append({
                "class": kind,
                "confidence": round(float(min(0.99, 0.6 + 0.4 * solidity)), 2),
                "bbox": [float(x), float(y), float(x + w), float(y + h)],
                "source": "simulated",
            })
    return detections


synthetic_desk = SyntheticDesk()


def synthetic_frame_loop(stop_event: threading.Event, on_frame, fps: float = 30.0) -> None:
    interval = 1.0 / fps
    while not stop_event.is_set():
        t0 = time.time()
        on_frame(synthetic_desk.render())
        stop_event.wait(max(0.001, interval - (time.time() - t0)))
