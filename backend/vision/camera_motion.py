"""Detects when the camera has been bumped since calibration.

A grayscale reference is stored when the desk is calibrated. Periodically the
current frame is matched against it with ORB features and a RANSAC homography;
if the frame corners move by more than a threshold, the player is warned to
recalibrate. When too few features match (featureless desk, poor light) the
result is reported as "uncertain" rather than raising a false alarm.
"""

import logging
import time
from typing import Dict, Optional

import cv2
import numpy as np

from backend.config import camera_file

logger = logging.getLogger("desk_defender.camera_motion")

WORK_WIDTH = 640


class CameraMotionMonitor:
    def __init__(self):
        self._orb = cv2.ORB_create(nfeatures=1200)
        self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self._ref_kp = None
        self._ref_desc = None
        self._ref_shape = None
        self.state = "no_reference"  # no_reference | stable | moved | uncertain
        self.shift = 0.0
        self.checked_at = 0.0
        self.camera_uid: str = "default"

    def _file(self):
        return camera_file("motion_ref", self.camera_uid, "jpg")

    def use_camera(self, uid: str) -> None:
        self.camera_uid = uid or "default"
        self._ref_kp = self._ref_desc = None
        self.state = "no_reference"
        self.shift = 0.0
        self._load()

    def _prep(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (WORK_WIDTH, int(h * WORK_WIDTH / w)))

    def set_reference(self, frame: np.ndarray) -> None:
        gray = self._prep(frame)
        self._ref_kp, self._ref_desc = self._orb.detectAndCompute(gray, None)
        self._ref_shape = gray.shape
        self.state = "stable"
        self.shift = 0.0
        cv2.imwrite(str(self._file()), gray)

    def clear(self) -> None:
        self._ref_kp = self._ref_desc = None
        self.state = "no_reference"
        if self._file().exists():
            self._file().unlink()

    def _load(self) -> None:
        if self._file().exists():
            gray = cv2.imread(str(self._file()), cv2.IMREAD_GRAYSCALE)
            if gray is not None:
                self._ref_kp, self._ref_desc = self._orb.detectAndCompute(gray, None)
                self._ref_shape = gray.shape
                self.state = "stable"

    def check(self, frame: np.ndarray, threshold: float) -> str:
        self.checked_at = time.time()
        if self._ref_desc is None or len(self._ref_kp) < 30:
            self.state = "no_reference" if self._ref_desc is None else "uncertain"
            return self.state
        gray = self._prep(frame)
        if gray.shape != self._ref_shape:
            self.state = "moved"  # resolution / aspect changed - corners are no longer valid
            return self.state
        kp, desc = self._orb.detectAndCompute(gray, None)
        if desc is None or len(kp) < 30:
            self.state = "uncertain"
            return self.state
        matches = sorted(self._matcher.match(self._ref_desc, desc), key=lambda m: m.distance)[:300]
        if len(matches) < 25:
            self.state = "uncertain"
            return self.state
        src = np.float32([self._ref_kp[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        dst = np.float32([kp[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
        H, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
        if H is None or inliers is None or int(inliers.sum()) < 20:
            self.state = "uncertain"
            return self.state
        h, w = gray.shape
        corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
        moved = cv2.perspectiveTransform(corners, H)
        self.shift = float(np.mean(np.linalg.norm(moved - corners, axis=2)) / np.hypot(w, h))
        self.state = "moved" if self.shift > threshold else "stable"
        return self.state

    def to_dict(self) -> Dict:
        return {"state": self.state, "shift": round(self.shift, 4), "checked_at": self.checked_at}


camera_motion = CameraMotionMonitor()
