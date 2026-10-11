"""Object detection: Ultralytics YOLO (COCO classes) plus an optional shape detector.

YOLO only knows the 80 COCO classes, and top-down views of desk items are
harder for it than side views. Objects it cannot classify (boxes, pencil
holders...) can still be picked up by the background-difference shape
detector once an empty-desk reference has been captured; those appear as
"unknown object" and the player assigns their role manually.
"""

import logging
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np

from backend.config import BASE_DIR, PROJECT_DIR, camera_file, effective_vision, settings

logger = logging.getLogger("desk_defender.detector")


def resolve_model_path(name: str) -> str:
    """Finds a local weights file; otherwise returns the name so Ultralytics downloads it."""
    p = Path(name)
    for candidate in (p, PROJECT_DIR / name, BASE_DIR / name, BASE_DIR / "models" / name):
        if candidate.is_file():
            return str(candidate)
    return name


class YoloDetector:
    """Lazy-loaded YOLO model. Loading happens on the vision thread, never on the event loop."""

    def __init__(self):
        self.model = None
        self.status = "not_loaded"  # not_loaded | loading | ready | error
        self.error: Optional[str] = None
        self.device = "cpu"
        self.model_path = ""
        self.class_names: Dict[int, str] = {}
        self._lock = threading.Lock()

    def _pick_device(self) -> str:
        want = settings.vision.device
        if want == "cpu":
            return "cpu"
        try:
            import torch
            if torch.backends.mps.is_available():
                return "mps"
        except Exception:
            pass
        return "cpu"

    def load(self) -> bool:
        with self._lock:
            if self.status == "ready":
                return True
            self.status = "loading"
            try:
                from ultralytics import YOLO
                self.model_path = resolve_model_path(settings.vision.model_path)
                logger.info("Loading YOLO weights from %s", self.model_path)
                self.model = YOLO(self.model_path)
                self.class_names = {int(k): str(v).lower() for k, v in self.model.names.items()}
                self.device = self._pick_device()
                # Warm-up so the first real frame is not slow; also validates the device.
                dummy = np.zeros((384, 640, 3), dtype=np.uint8)
                try:
                    self.model.predict(dummy, device=self.device, verbose=False, imgsz=320)
                except Exception as exc:
                    logger.warning("YOLO warm-up on %s failed (%s); falling back to CPU", self.device, exc)
                    self.device = "cpu"
                    self.model.predict(dummy, device="cpu", verbose=False, imgsz=320)
                self.status = "ready"
                self.error = None
                logger.info("YOLO ready on %s with %d classes", self.device, len(self.class_names))
                return True
            except Exception as exc:
                self.status = "error"
                self.error = (f"Could not load YOLO model '{settings.vision.model_path}': {exc}. "
                              "Place yolov8n.pt in the project root or allow Ultralytics to download it.")
                logger.error(self.error)
                return False

    def detect(self, frame: np.ndarray) -> List[Dict]:
        if self.status != "ready" or self.model is None:
            return []
        v = effective_vision()
        ignored = set(c.lower() for c in v.ignored_classes)
        try:
            results = self.model.predict(
                frame, conf=v.confidence_threshold, iou=v.iou_threshold, imgsz=v.inference_size,
                agnostic_nms=v.class_agnostic_nms, device=self.device, verbose=False,
            )
        except Exception as exc:
            if self.device != "cpu":
                logger.warning("Inference failed on %s (%s); switching to CPU", self.device, exc)
                self.device = "cpu"
                return []
            raise
        detections = []
        for r in results:
            if r.boxes is None:
                continue
            xyxy = r.boxes.xyxy.cpu().numpy()
            confs = r.boxes.conf.cpu().numpy()
            classes = r.boxes.cls.cpu().numpy().astype(int)
            for box, conf, cls_id in zip(xyxy, confs, classes):
                name = self.class_names.get(int(cls_id), f"class_{cls_id}")
                if name in ignored:
                    continue
                detections.append({
                    "class": name,
                    "confidence": round(float(conf), 3),
                    "bbox": [round(float(b), 1) for b in box],
                    "source": "yolo",
                })
        return detections


class ShapeDetector:
    """Finds objects on the warped desk by differencing against an empty-desk reference."""

    WORK_SCALE = 0.5  # work at 500x350 for speed

    def __init__(self):
        self.reference: Optional[np.ndarray] = None
        self.reference_calibration_version: Optional[int] = None
        self.camera_uid = "default"

    def _file(self) -> Path:
        return camera_file("empty_desk", self.camera_uid, "png")

    def use_camera(self, uid: str) -> None:
        self.camera_uid = uid or "default"
        self.reference = None
        self.load_reference()

    @property
    def has_reference(self) -> bool:
        return self.reference is not None

    def _prep(self, warped: np.ndarray) -> np.ndarray:
        lab = cv2.cvtColor(warped, cv2.COLOR_BGR2LAB)
        return cv2.GaussianBlur(lab, (7, 7), 0)

    def set_reference(self, warped_bgr: np.ndarray, calibration_version: int) -> None:
        h, w = warped_bgr.shape[:2]
        small = cv2.resize(warped_bgr, (int(w * self.WORK_SCALE), int(h * self.WORK_SCALE)))
        self.reference = self._prep(small)
        self.reference_calibration_version = calibration_version
        cv2.imwrite(str(self._file()), small)
        logger.info("Captured empty-desk reference for shape detection")

    def load_reference(self) -> None:
        if self._file().exists():
            img = cv2.imread(str(self._file()))
            if img is not None:
                self.reference = self._prep(img)

    def clear_reference(self) -> None:
        self.reference = None
        if self._file().exists():
            self._file().unlink()

    def detect(self, warped_bgr: np.ndarray) -> List[Dict]:
        """Returns detections with bboxes in *virtual* coordinates (key 'virtual_bbox')."""
        if self.reference is None:
            return []
        v = settings.vision
        h, w = warped_bgr.shape[:2]
        small = cv2.resize(warped_bgr, (self.reference.shape[1], self.reference.shape[0]))
        cur = self._prep(small)
        diff = cv2.absdiff(cur, self.reference).astype(np.float32)
        # Down-weight lightness so soft shadows / exposure drift trigger less than colour change.
        score = 0.45 * diff[:, :, 0] + diff[:, :, 1] + diff[:, :, 2]
        mask = (score > v.shape_diff_threshold).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        sx = w / small.shape[1] * (settings.virtual_width / w)
        sy = h / small.shape[0] * (settings.virtual_height / h)
        total = settings.virtual_width * settings.virtual_height
        out = []
        for c in contours:
            x, y, bw, bh = cv2.boundingRect(c)
            area_v = cv2.contourArea(c) * sx * sy
            if area_v < v.shape_min_area or bw * bh * sx * sy > v.max_area_fraction * total:
                continue
            fill = cv2.contourArea(c) / max(1.0, bw * bh)
            out.append({
                "class": "unknown object",
                "confidence": round(float(min(0.9, 0.35 + 0.5 * fill)), 2),
                "virtual_bbox": [x * sx, y * sy, (x + bw) * sx, (y + bh) * sy],
                "source": "shape",
            })
        return out


def _iou(a: List[float], b: List[float]) -> float:
    ix1, iy1, ix2, iy2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def merge_shape_detections(yolo_virtual: List[List[float]], shapes: List[Dict]) -> List[Dict]:
    """Drops shape blobs already explained by a YOLO detection."""
    kept = []
    for s in shapes:
        sb = s["virtual_bbox"]
        cx, cy = (sb[0] + sb[2]) / 2, (sb[1] + sb[3]) / 2
        explained = any(_iou(sb, yb) > 0.2 or (yb[0] <= cx <= yb[2] and yb[1] <= cy <= yb[3])
                        for yb in yolo_virtual)
        if not explained:
            kept.append(s)
    return kept


yolo_detector = YoloDetector()
shape_detector = ShapeDetector()


def timed(fn, *args):
    t0 = time.perf_counter()
    out = fn(*args)
    return out, (time.perf_counter() - t0) * 1000.0
