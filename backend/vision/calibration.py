"""Desk calibration: four camera-space corners -> normalized battlefield via homography.

Corners are given in camera pixels in the order TL, TR, BR, BL. They are saved
together with the frame size they were picked on, so a later resolution change
rescales them instead of silently producing a wrong mapping. Calibrations are
stored per camera (AVFoundation unique ID): switching cameras never reuses
another camera's corners.
"""

import json
import logging
import math
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from backend.config import CALIBRATION_FILE, settings

logger = logging.getLogger("desk_defender.calibration")

CORNER_NAMES = ["top-left", "top-right", "bottom-right", "bottom-left"]


def validate_quad(points: Sequence[Sequence[float]], frame_size: Optional[Tuple[int, int]] = None) -> Tuple[bool, str]:
    """Checks that the 4 points form a reasonable, clockwise, convex quadrilateral."""
    if points is None or len(points) != 4:
        return False, f"Expected 4 corner points, got {0 if points is None else len(points)}."
    try:
        pts = np.array(points, dtype=np.float64).reshape(4, 2)
    except (TypeError, ValueError):
        return False, "Corner points must be [x, y] number pairs."
    if not np.all(np.isfinite(pts)):
        return False, "Corner points must be finite numbers."

    if frame_size:
        w, h = frame_size
        margin = 0.02 * max(w, h)
        for name, (x, y) in zip(CORNER_NAMES, pts):
            if x < -margin or y < -margin or x > w + margin or y > h + margin:
                return False, f"The {name} corner ({x:.0f}, {y:.0f}) lies outside the {w}x{h} camera frame."

    for i in range(4):
        for j in range(i + 1, 4):
            if np.linalg.norm(pts[i] - pts[j]) < 20:
                return False, f"The {CORNER_NAMES[i]} and {CORNER_NAMES[j]} corners are too close together."

    # Signed area (shoelace). Image y points down, so TL->TR->BR->BL is positive.
    x, y = pts[:, 0], pts[:, 1]
    signed = 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    area = abs(signed)
    min_area = 0.04 * frame_size[0] * frame_size[1] if frame_size else 5000.0
    if area < min_area:
        return False, (f"The selected area is too small ({area:.0f} px²). Select the corners of the whole "
                       "playable desk area.")
    if signed < 0:
        return False, "Corners are in the wrong order. Select them clockwise: top-left, top-right, bottom-right, bottom-left."

    # Convexity: all cross products of consecutive edges share the sign.
    crosses = []
    for i in range(4):
        a, b, c = pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]
        e1, e2 = b - a, c - b
        crosses.append(e1[0] * e2[1] - e1[1] * e2[0])
    if not (all(c > 0 for c in crosses) or all(c < 0 for c in crosses)):
        return False, "The corners do not form a convex shape. Check that no edges cross."

    # Interior angles: reject extreme perspective that would make the mapping unstable.
    for i in range(4):
        prev_pt, pt, next_pt = pts[i - 1], pts[i], pts[(i + 1) % 4]
        v1, v2 = prev_pt - pt, next_pt - pt
        cosang = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))
        angle = math.degrees(math.acos(max(-1.0, min(1.0, cosang))))
        if angle < 25 or angle > 155:
            return False, (f"The angle at the {CORNER_NAMES[i]} corner is {angle:.0f}°, which is too extreme. "
                           "Point the camera more directly down at the desk.")
    return True, "Calibration looks good."


class DeskCalibration:
    """Holds the homography between camera pixels and the virtual battlefield."""

    def __init__(self, virtual_width: Optional[int] = None, virtual_height: Optional[int] = None,
                 filepath: Optional[Path] = CALIBRATION_FILE, autoload: bool = True):
        self.virtual_width = int(virtual_width or settings.virtual_width)
        self.virtual_height = int(virtual_height or settings.virtual_height)
        self.filepath = filepath
        self._lock = threading.RLock()
        self.points: Optional[List[List[float]]] = None
        self.frame_size: Optional[Tuple[int, int]] = None
        self.matrix: Optional[np.ndarray] = None
        self.inv_matrix: Optional[np.ndarray] = None
        self.calibrated_at: float = 0.0
        self.camera_unique_id: Optional[str] = None
        self.version = 0
        if autoload and filepath is not None:
            self.load()

    def use_camera(self, camera_uid: Optional[str]) -> bool:
        """Activates the stored calibration of this camera (or none). Returns True if one was found."""
        with self._lock:
            if camera_uid == self.camera_unique_id and self.matrix is not None:
                return True
            self.points = None
            self.matrix = None
            self.inv_matrix = None
            self.frame_size = None
            self.camera_unique_id = camera_uid
            self.version += 1
        return self.load()

    @property
    def is_calibrated(self) -> bool:
        return self.matrix is not None

    def _dst(self) -> np.ndarray:
        w, h = float(self.virtual_width), float(self.virtual_height)
        return np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)

    def set_points(self, points: Sequence[Sequence[float]], frame_size: Optional[Tuple[int, int]] = None,
                   save: bool = True) -> Tuple[bool, str]:
        valid, msg = validate_quad(points, frame_size)
        if not valid:
            return False, msg
        with self._lock:
            self.points = [[float(p[0]), float(p[1])] for p in points]
            self.frame_size = (int(frame_size[0]), int(frame_size[1])) if frame_size else None
            src = np.array(self.points, dtype=np.float32)
            self.matrix = cv2.getPerspectiveTransform(src, self._dst())
            self.inv_matrix = cv2.getPerspectiveTransform(self._dst(), src)
            self.calibrated_at = time.time()
            self.version += 1
        if save:
            self.save()
        logger.info("Calibration set: %s on frame %s", self.points, self.frame_size)
        return True, msg

    def clear(self) -> None:
        with self._lock:
            self.points = None
            self.matrix = None
            self.inv_matrix = None
            self.frame_size = None
            self.version += 1
            store = self._read_store()
            store.pop(self._key(), None)
            self._write_store(store)

    def adapt_to_frame(self, frame_size: Tuple[int, int]) -> None:
        """Rescales saved corners if the camera now delivers a different resolution."""
        with self._lock:
            if not self.points or not self.frame_size or tuple(frame_size) == tuple(self.frame_size):
                return
            sx = frame_size[0] / self.frame_size[0]
            sy = frame_size[1] / self.frame_size[1]
            scaled = [[p[0] * sx, p[1] * sy] for p in self.points]
            logger.info("Rescaling calibration from %s to %s", self.frame_size, frame_size)
        self.set_points(scaled, frame_size)

    # ------------------------------------------------------------------ transforms
    def transform_points(self, pts: np.ndarray) -> np.ndarray:
        with self._lock:
            if self.matrix is None:
                raise RuntimeError("Desk is not calibrated")
            arr = np.asarray(pts, dtype=np.float32).reshape(-1, 1, 2)
            return cv2.perspectiveTransform(arr, self.matrix).reshape(-1, 2)

    def inverse_transform_points(self, pts: np.ndarray) -> np.ndarray:
        with self._lock:
            if self.inv_matrix is None:
                raise RuntimeError("Desk is not calibrated")
            arr = np.asarray(pts, dtype=np.float32).reshape(-1, 1, 2)
            return cv2.perspectiveTransform(arr, self.inv_matrix).reshape(-1, 2)

    def transform_point(self, x: float, y: float) -> Tuple[float, float]:
        out = self.transform_points(np.array([[x, y]]))[0]
        return float(out[0]), float(out[1])

    def inverse_transform_point(self, vx: float, vy: float) -> Tuple[float, float]:
        out = self.inverse_transform_points(np.array([[vx, vy]]))[0]
        return float(out[0]), float(out[1])

    def transform_bbox(self, bbox: Sequence[float]) -> Dict:
        """Maps a camera bbox to battlefield center + footprint (extent of its 4 warped corners)."""
        x1, y1, x2, y2 = bbox
        corners = self.transform_points(np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2],
                                                  [(x1 + x2) / 2, (y1 + y2) / 2]]))
        quad, center = corners[:4], corners[4]
        vw = float(quad[:, 0].max() - quad[:, 0].min())
        vh = float(quad[:, 1].max() - quad[:, 1].min())
        return {"center": (float(center[0]), float(center[1])), "footprint": (vw, vh)}

    def contains_virtual(self, vx: float, vy: float, margin: float = 0.0) -> bool:
        return (-margin <= vx <= self.virtual_width + margin) and (-margin <= vy <= self.virtual_height + margin)

    def warp_frame(self, frame: np.ndarray, size: Optional[Tuple[int, int]] = None) -> np.ndarray:
        with self._lock:
            if self.matrix is None:
                raise RuntimeError("Desk is not calibrated")
            out_w, out_h = size or (self.virtual_width, self.virtual_height)
            scale = np.diag([out_w / self.virtual_width, out_h / self.virtual_height, 1.0])
            return cv2.warpPerspective(frame, scale @ self.matrix, (int(out_w), int(out_h)))

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> Dict:
        with self._lock:
            return {
                "is_calibrated": self.is_calibrated,
                "points": self.points,
                "frame_size": list(self.frame_size) if self.frame_size else None,
                "virtual_width": self.virtual_width,
                "virtual_height": self.virtual_height,
                "calibrated_at": self.calibrated_at,
                "camera_unique_id": self.camera_unique_id,
                "version": self.version,
            }

    def _key(self) -> str:
        return self.camera_unique_id or "default"

    def _read_store(self) -> Dict:
        if self.filepath is None or not self.filepath.exists():
            return {}
        try:
            data = json.loads(self.filepath.read_text())
            return data.get("cameras", {}) if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_store(self, store: Dict) -> None:
        if self.filepath is None:
            return
        try:
            self.filepath.write_text(json.dumps({"cameras": store}, indent=2))
        except OSError as exc:
            logger.error("Failed to save calibration: %s", exc)

    def save(self) -> None:
        if self.filepath is None:
            return
        with self._lock:
            data = self.to_dict()
            data.pop("version", None)
            store = self._read_store()
            store[self._key()] = data
            self._write_store(store)

    def load(self) -> bool:
        """Loads the calibration stored for the active camera."""
        data = self._read_store().get(self._key())
        if not data:
            return False
        try:
            frame_size = tuple(data["frame_size"]) if data.get("frame_size") else None
            if not data.get("points") or frame_size is None:
                logger.warning("Calibration for %s lacks points or frame size - recalibration required", self._key())
                return False
            self.virtual_width = int(data.get("virtual_width", self.virtual_width))
            self.virtual_height = int(data.get("virtual_height", self.virtual_height))
            ok, msg = self.set_points(data["points"], frame_size, save=False)
            if not ok:
                logger.warning("Saved calibration is invalid (%s) - recalibration required", msg)
                return False
            self.calibrated_at = float(data.get("calibrated_at", time.time()))
            logger.info("Loaded calibration for camera %s", self._key())
            return True
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("Failed to read calibration: %s", exc)
            return False


def suggest_corners(frame: np.ndarray) -> Tuple[List[List[float]], str]:
    """Best-effort detection of a desk mat / sheet as the largest bright-edged quadrilateral.

    Falls back to a 10% inset rectangle. The player always reviews and adjusts.
    """
    h, w = frame.shape[:2]
    fallback = [[w * 0.1, h * 0.1], [w * 0.9, h * 0.1], [w * 0.9, h * 0.9], [w * 0.1, h * 0.9]]
    scale = 640.0 / max(w, h)
    small = cv2.resize(frame, (int(w * scale), int(h * scale)))
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    edges = cv2.dilate(cv2.Canny(gray, 40, 120), np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    best, best_area = None, 0.0
    frame_area = small.shape[0] * small.shape[1]
    for c in contours:
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        area = cv2.contourArea(approx)
        if len(approx) == 4 and cv2.isContourConvex(approx) and 0.15 * frame_area < area < 0.97 * frame_area:
            if area > best_area:
                best, best_area = approx.reshape(4, 2).astype(np.float64) / scale, area
    if best is None:
        return fallback, "No clear desk outline found - showing a default rectangle. Drag the corners into place."
    # Order TL, TR, BR, BL
    s = best.sum(axis=1)
    d = np.diff(best, axis=1).ravel()
    ordered = [best[np.argmin(s)], best[np.argmin(d)], best[np.argmax(s)], best[np.argmax(d)]]
    pts = [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in ordered]
    ok, _ = validate_quad(pts, (w, h))
    if not ok:
        return fallback, "Detected outline was not usable - showing a default rectangle. Drag the corners into place."
    return pts, "Detected a likely desk outline. Check every corner before confirming."


calibration = DeskCalibration(autoload=False)  # activated per camera by the pipeline
