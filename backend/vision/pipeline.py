"""Frame processing pipeline.

Runs on its own thread at a configurable rate that is independent of the
camera rate and the game tick: it always takes the *newest* camera frame
(older frames are simply dropped), runs detection, updates the tracker and
publishes results. Preview JPEGs are rendered on demand per variant and
cached per camera frame, so several viewers share one encode.
"""

import logging
import threading
import time
from collections import deque
from typing import Dict, List, Optional

import cv2
import numpy as np

from backend.camera.manager import camera_manager
from backend.camera.synthetic import detect_synthetic_objects
from backend.config import effective_vision, settings
from backend.vision.calibration import calibration
from backend.vision.camera_motion import camera_motion
from backend.vision.detector import merge_shape_detections, shape_detector, yolo_detector
from backend.vision.tracker import tracker

logger = logging.getLogger("desk_defender.pipeline")

tracker.set_transform(calibration.transform_bbox)

ROLE_COLORS_BGR = {
    "barrier": (11, 158, 245),
    "heavy_fortification": (0, 110, 230),
    "defense_tower": (255, 240, 0),
    "support_tower": (247, 85, 168),
    "custom": (220, 220, 220),
}


_active_camera_uid: Optional[str] = "__none__"
_context_lock = threading.Lock()


def activate_camera_context(uid: Optional[str]) -> None:
    """Loads calibration + references belonging to this camera; called whenever the camera changes."""
    global _active_camera_uid
    with _context_lock:
        if uid == _active_camera_uid:
            return
        _active_camera_uid = uid
        if uid is None:
            return
        found = calibration.use_camera(uid)
        camera_motion.use_camera(uid)
        shape_detector.use_camera(uid)
        tracker.reset()
        logger.info("Camera context %s: %s", uid, "calibration loaded" if found else "not calibrated yet")


class VisionPipeline:
    def __init__(self):
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._raw_detections: List[Dict] = []
        self._last_frame_id = -1
        self._inference_ms = deque(maxlen=30)
        self._det_times = deque(maxlen=30)
        self._last_motion_check = 0.0
        self._status_message: Optional[str] = None
        self._preview_cache: Dict[str, tuple] = {}
        self._preview_locks = {k: threading.Lock() for k in ("overlay", "raw", "warped")}
        self.version = 0

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, name="vision-pipeline", daemon=True)
        self._thread.start()
        logger.info("Vision pipeline started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

    def _worker(self) -> None:
        while not self._stop.is_set():
            cam = camera_manager.get_status()
            if cam["connected"] and not cam["is_simulated"] and yolo_detector.status == "not_loaded":
                self._status_message = "Loading YOLO model..."
                yolo_detector.load()
            v = effective_vision()
            interval = 1.0 / max(0.5, v.inference_fps)
            t0 = time.time()
            try:
                self._process_once(cam)
            except Exception as exc:  # keep the thread alive; surface the error
                logger.exception("Vision pipeline error")
                self._status_message = f"Vision error: {exc}"
            self._stop.wait(max(0.005, interval - (time.time() - t0)))

    def _process_once(self, cam: Dict) -> None:
        if cam.get("unique_id"):
            activate_camera_context(cam["unique_id"])
        ok, frame, _ = camera_manager.read_frame()
        if not ok or frame is None:
            self._status_message = "Waiting for camera frames"
            return
        frame_id = camera_manager.frame_id
        if frame_id == self._last_frame_id:
            return
        self._last_frame_id = frame_id
        h, w = frame.shape[:2]
        if calibration.is_calibrated:
            calibration.adapt_to_frame((w, h))

        t0 = time.perf_counter()
        if cam["is_simulated"]:
            detections = detect_synthetic_objects(frame)
        else:
            if yolo_detector.status != "ready":
                self._status_message = yolo_detector.error or "YOLO model not ready"
                detections = []
            else:
                detections = yolo_detector.detect(frame)
            if calibration.is_calibrated and settings.vision.shape_detection_enabled and shape_detector.has_reference:
                warped = calibration.warp_frame(frame, (500, 350))
                yolo_virtual = []
                for d in detections:
                    m = calibration.transform_bbox(d["bbox"])
                    (cx, cy), (fw, fh) = m["center"], m["footprint"]
                    yolo_virtual.append([cx - fw / 2, cy - fh / 2, cx + fw / 2, cy + fh / 2])
                detections += merge_shape_detections(yolo_virtual, shape_detector.detect(warped))
        elapsed = (time.perf_counter() - t0) * 1000.0

        if calibration.is_calibrated:
            tracker.update(detections)
            self._status_message = None if cam["is_simulated"] or yolo_detector.status == "ready" else self._status_message
            now = time.time()
            if now - self._last_motion_check > settings.vision.motion_check_interval_s:
                self._last_motion_check = now
                camera_motion.check(frame, settings.vision.motion_warning_threshold)
        else:
            self._status_message = "Desk not calibrated - detections are shown but not mapped to the battlefield"

        with self._lock:
            self._raw_detections = detections
            self._inference_ms.append(elapsed)
            self._det_times.append(time.time())
            self.version += 1

    # ------------------------------------------------------------------ status
    def get_status(self) -> Dict:
        with self._lock:
            times = list(self._det_times)
            det_fps = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 and times[-1] > times[0] else 0.0
            if times and time.time() - times[-1] > 2.0:
                det_fps = 0.0
            inf = sum(self._inference_ms) / len(self._inference_ms) if self._inference_ms else 0.0
            raw_count = len(self._raw_detections)
        v = effective_vision()
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "detection_fps": round(det_fps, 1),
            "target_detection_fps": v.inference_fps,
            "inference_ms": round(inf, 1),
            "raw_detections": raw_count,
            "model_status": yolo_detector.status,
            "model_device": yolo_detector.device,
            "model_error": yolo_detector.error,
            "shape_reference": shape_detector.has_reference,
            "shape_detection_enabled": settings.vision.shape_detection_enabled,
            "low_performance_mode": settings.vision.low_performance_mode,
            "message": self._status_message,
            "camera_motion": camera_motion.to_dict(),
        }

    def raw_detections(self) -> List[Dict]:
        with self._lock:
            return list(self._raw_detections)

    # ------------------------------------------------------------------ previews
    def render_jpeg(self, variant: str = "overlay") -> Optional[bytes]:
        if variant not in self._preview_locks:
            variant = "overlay"
        ok, frame, _ = camera_manager.read_frame()
        if not ok or frame is None:
            return None
        key = (camera_manager.frame_id, self.version, calibration.version)
        cached = self._preview_cache.get(variant)
        if cached and cached[0] == key:
            return cached[1]
        with self._preview_locks[variant]:
            cached = self._preview_cache.get(variant)
            if cached and cached[0] == key:
                return cached[1]
            v = effective_vision()
            if variant == "warped":
                if not calibration.is_calibrated:
                    return None
                img = calibration.warp_frame(frame, (700, 490))
            else:
                h, w = frame.shape[:2]
                scale = min(1.0, v.preview_width / w)
                img = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale < 1.0 else frame.copy()
                if variant == "overlay":
                    self._draw_overlay(img, scale)
            ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), v.preview_jpeg_quality])
            if not ok:
                return None
            data = buf.tobytes()
            self._preview_cache[variant] = (key, data)
            return data

    def _draw_overlay(self, img: np.ndarray, scale: float) -> None:
        font = cv2.FONT_HERSHEY_SIMPLEX
        if calibration.is_calibrated and calibration.points:
            pts = (np.array(calibration.points) * scale).astype(np.int32)
            cv2.polylines(img, [pts], True, (255, 220, 0), 2, cv2.LINE_AA)
            for label, (x, y) in zip(("TL", "TR", "BR", "BL"), pts):
                cv2.circle(img, (int(x), int(y)), 6, (255, 220, 0), -1, cv2.LINE_AA)
                cv2.putText(img, label, (int(x) + 8, int(y) - 8), font, 0.45, (255, 220, 0), 1, cv2.LINE_AA)

            for obj in tracker.snapshot():
                cx, cy = obj["center"]
                fw, fh = obj["footprint"]
                quad = np.array([[cx - fw / 2, cy - fh / 2], [cx + fw / 2, cy - fh / 2],
                                 [cx + fw / 2, cy + fh / 2], [cx - fw / 2, cy + fh / 2]])
                poly = (calibration.inverse_transform_points(quad) * scale).astype(np.int32)
                color = ROLE_COLORS_BGR.get(obj["role"], (220, 220, 220))
                if obj["is_stale"]:
                    color = (110, 110, 110)
                thickness = 2 if obj["confirmed"] else 1
                cv2.polylines(img, [poly], True, color, thickness, cv2.LINE_AA)
                status = " LOST" if obj["is_stale"] else ("" if obj["confirmed"] else " ?")
                label = f"{obj['id']} {obj['detected_class']} {int(obj['confidence'] * 100)}% > {obj['role'].replace('_', ' ')}{status}"
                x0, y0 = int(poly[:, 0].min()), int(poly[:, 1].min())
                fs = 0.55
                (tw, th), _ = cv2.getTextSize(label, font, fs, 1)
                cv2.rectangle(img, (x0, max(0, y0 - th - 8)), (x0 + tw + 6, y0), color, -1)
                cv2.putText(img, label, (x0 + 3, y0 - 5), font, fs, (15, 15, 15), 1, cv2.LINE_AA)
        else:
            # Uncalibrated: show raw detections so the player can verify the model works.
            for d in self.raw_detections():
                if "bbox" not in d:
                    continue
                x1, y1, x2, y2 = (np.array(d["bbox"]) * scale).astype(int)
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 200, 255), 2)
                cv2.putText(img, f"{d['class']} {int(d['confidence'] * 100)}%", (x1 + 3, max(14, y1 - 5)),
                            font, 0.45, (0, 200, 255), 1, cv2.LINE_AA)
            cv2.putText(img, "NOT CALIBRATED", (14, img.shape[0] - 16), font, 0.7, (0, 80, 255), 2, cv2.LINE_AA)


pipeline = VisionPipeline()


def placeholder_jpeg(message: str, width: int = 960, height: int = 540) -> bytes:
    img = np.full((height, width, 3), (20, 14, 10), dtype=np.uint8)
    for y in range(0, height, 4):
        img[y:y + 1] = (26, 20, 16)
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, "NO CAMERA SIGNAL", (width // 2 - 170, height // 2 - 10), font, 1.0, (0, 170, 255), 2, cv2.LINE_AA)
    (tw, _), _ = cv2.getTextSize(message, font, 0.55, 1)
    cv2.putText(img, message[:90], (max(10, width // 2 - tw // 2), height // 2 + 30), font, 0.55,
                (200, 200, 200), 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()
