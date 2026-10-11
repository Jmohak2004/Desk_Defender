"""Camera discovery and lifecycle for Desk Defender.

CameraManager exposes the interface required by the game:
    list_cameras(), connect(camera_id), read_frame(), get_status(), disconnect()

Real cameras are opened through OpenCV's AVFoundation backend. The capture
thread keeps only the most recent frame (a bounded buffer of one), so slow
consumers always process fresh frames instead of a growing backlog. If the
stream drops (iPhone locked, moved away, cable pulled) the manager reports the
failure and keeps trying to reopen the *same physical device*, re-resolving
its OpenCV index by AVFoundation unique ID.
"""

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from backend.camera import permissions
from backend.camera.synthetic import synthetic_desk, synthetic_frame_loop
from backend.config import settings

logger = logging.getLogger("desk_defender.camera")

SIMULATED_ID = "simulated"

TROUBLESHOOTING = [
    "Use an iPhone XR or newer on iOS 16+ and a Mac on macOS Ventura 13+, signed in to the same Apple Account with two-factor authentication.",
    "Turn on Wi-Fi and Bluetooth on both devices and keep the iPhone near the Mac (or connect it by USB).",
    "On the iPhone: Settings > General > AirPlay & Continuity (or AirPlay & Handoff) > Continuity Camera must be ON.",
    "Mount the iPhone in landscape, screen off/locked, rear cameras pointing at the desk, and keep it still.",
    "Allow camera access for the app that launched the backend (Terminal, iTerm or VS Code) in System Settings > Privacy & Security > Camera, then restart the backend.",
    "Quit other apps that may hold the camera (FaceTime, Zoom, Photo Booth, browsers using the webcam).",
    "If the iPhone is not listed, click Refresh; on the iPhone a 'Connected to Mac' screen should appear when the stream starts.",
]


class CameraManager:
    """Manages camera discovery, connection, frame grabbing, reconnection and diagnostics."""

    def __init__(self):
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cap: Optional[cv2.VideoCapture] = None

        self._camera_id: Optional[Any] = None
        self._camera_name: str = "None"
        self._unique_id: Optional[str] = None
        self._is_continuity = False
        self._is_simulated = False
        self._requested_size: Tuple[int, int] = (settings.camera.width, settings.camera.height)

        self._state = "disconnected"  # disconnected | connecting | streaming | reconnecting | error
        self._error: Optional[str] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_ts = 0.0
        self._frame_id = 0
        self._fps = 0.0
        self._fps_count = 0
        self._fps_t0 = time.time()
        self._reconnect_attempts = 0
        self._device_cache: List[Dict] = []

    # ------------------------------------------------------------------ discovery
    def list_cameras(self, include_simulated: bool = True) -> List[Dict[str, Any]]:
        """Enumerates cameras. Uses AVFoundation names when PyObjC is available, else probes OpenCV indices."""
        devices: List[Dict[str, Any]] = []
        avf = permissions.discover_avfoundation_devices() if permissions.IS_MACOS else []
        if avf:
            for d in avf:
                devices.append({
                    "id": d["index"], "index": d["index"], "name": d["name"], "unique_id": d["unique_id"],
                    "model_id": d["model_id"], "device_type": d["device_type"],
                    "is_continuity": d["is_continuity"], "is_desk_view": d["is_desk_view"],
                    "is_simulated": False, "discovery": "avfoundation",
                })
        else:
            devices.extend(self._probe_opencv_indices())

        if include_simulated:
            devices.append({
                "id": SIMULATED_ID, "index": None, "name": "SIMULATED desk (development mode)",
                "unique_id": SIMULATED_ID, "model_id": "", "device_type": "Synthetic",
                "is_continuity": False, "is_desk_view": False, "is_simulated": True, "discovery": "synthetic",
            })
        self._device_cache = devices
        return devices

    def _probe_opencv_indices(self, max_index: int = 5) -> List[Dict[str, Any]]:
        """Fallback discovery: try opening indices. Skips the index currently streaming."""
        found = []
        backend = cv2.CAP_AVFOUNDATION if permissions.IS_MACOS else cv2.CAP_ANY
        for idx in range(max_index):
            if self._camera_id == idx and self._state == "streaming":
                found.append({"id": idx, "index": idx, "name": f"Camera {idx}", "unique_id": f"index:{idx}",
                              "model_id": "", "device_type": "Unknown", "is_continuity": False,
                              "is_desk_view": False, "is_simulated": False, "discovery": "opencv-probe"})
                continue
            cap = cv2.VideoCapture(idx, backend)
            ok = cap.isOpened()
            cap.release()
            if ok:
                found.append({"id": idx, "index": idx, "name": f"Camera {idx}", "unique_id": f"index:{idx}",
                              "model_id": "", "device_type": "Unknown", "is_continuity": False,
                              "is_desk_view": False, "is_simulated": False, "discovery": "opencv-probe"})
        return found

    def snapshot(self, index: int, width: int = 320) -> Optional[bytes]:
        """Grabs one JPEG thumbnail from a camera index so the player can identify it visually."""
        if self._camera_id == index and self._state == "streaming":
            ok, frame, _ = self.read_frame()
        else:
            if permissions.authorization_status() in ("denied", "restricted"):
                return None
            cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION if permissions.IS_MACOS else cv2.CAP_ANY)
            ok, frame = False, None
            if cap.isOpened():
                deadline = time.time() + 4.0
                while time.time() < deadline:
                    ok, frame = cap.read()
                    # Continuity Camera delivers a few black frames while the stream warms up.
                    if ok and frame is not None and frame.mean() > 4:
                        break
                    time.sleep(0.05)
            cap.release()
        if not ok or frame is None:
            return None
        h, w = frame.shape[:2]
        thumb = cv2.resize(frame, (width, int(h * width / w)))
        ok, buf = cv2.imencode(".jpg", thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        return buf.tobytes() if ok else None

    # ------------------------------------------------------------------ lifecycle
    def connect(self, camera_id: Any, width: Optional[int] = None, height: Optional[int] = None) -> bool:
        """Connects to a camera index (int / numeric string) or the explicit SIMULATED camera."""
        with self._lifecycle_lock:
            self._stop_capture()
            w = int(width or settings.camera.width)
            h = int(height or settings.camera.height)
            with self._lock:
                self._requested_size = (w, h)
                self._error = None
                self._reconnect_attempts = 0
                self._latest_frame = None
                self._state = "connecting"

            if str(camera_id) == SIMULATED_ID:
                return self._start_simulated()

            try:
                index = int(camera_id)
            except (TypeError, ValueError):
                self._fail(f"Invalid camera id '{camera_id}'. Choose a camera from the list.")
                return False

            perm = permissions.authorization_status()
            if perm in ("denied", "restricted"):
                self._fail("macOS denied camera access. Open System Settings > Privacy & Security > Camera, "
                           "enable it for the app running the backend (Terminal / iTerm / VS Code), then restart the backend.")
                return False

            info = next((d for d in (self._device_cache or self.list_cameras()) if d.get("index") == index), None)
            cap, err = self._open_capture(index, w, h)
            if cap is None:
                self._fail(err)
                return False

            with self._lock:
                self._cap = cap
                self._camera_id = index
                self._camera_name = info["name"] if info else f"Camera {index}"
                self._unique_id = info["unique_id"] if info else None
                self._is_continuity = bool(info and info.get("is_continuity"))
                self._is_simulated = False
                self._state = "streaming"
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._capture_worker, name="camera-capture", daemon=True)
            self._thread.start()
            logger.info("Connected to camera '%s' (index %s)", self._camera_name, index)
            return True

    def _open_capture(self, index: int, w: int, h: int) -> Tuple[Optional[cv2.VideoCapture], str]:
        backend = cv2.CAP_AVFOUNDATION if permissions.IS_MACOS else cv2.CAP_ANY
        try:
            cap = cv2.VideoCapture(index, backend)
        except Exception as exc:  # pragma: no cover - driver specific
            return None, f"OpenCV raised while opening camera {index}: {exc}"
        if not cap.isOpened():
            cap.release()
            hint = " Camera permission has not been granted yet." if permissions.authorization_status() == "not_determined" else ""
            return None, (f"Could not open camera index {index}.{hint} Make sure the device is connected, "
                          "not in use by another app, and that camera access is allowed.")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        deadline = time.time() + 6.0
        while time.time() < deadline:
            ok, frame = cap.read()
            if ok and frame is not None and frame.size > 0:
                with self._lock:
                    self._store_frame(frame)
                return cap, ""
            time.sleep(0.05)
        cap.release()
        return None, (f"Camera {index} opened but produced no frames within 6 s. For Continuity Camera, "
                      "keep the iPhone locked, nearby, and in landscape, then try again.")

    def _start_simulated(self) -> bool:
        with self._lock:
            self._camera_id = SIMULATED_ID
            self._camera_name = "SIMULATED desk (development mode)"
            self._unique_id = SIMULATED_ID
            self._is_continuity = False
            self._is_simulated = True
            self._state = "streaming"
            self._store_frame(synthetic_desk.render())
        self._stop_event.clear()

        def on_frame(frame: np.ndarray) -> None:
            with self._lock:
                self._store_frame(frame)

        self._thread = threading.Thread(target=synthetic_frame_loop, args=(self._stop_event, on_frame),
                                        name="camera-simulated", daemon=True)
        self._thread.start()
        logger.warning("Connected to the SIMULATED development camera")
        return True

    def _store_frame(self, frame: np.ndarray) -> None:
        """Caller holds self._lock. Keeps only the newest frame."""
        now = time.time()
        self._latest_frame = frame
        self._latest_ts = now
        self._frame_id += 1
        self._fps_count += 1
        if now - self._fps_t0 >= 1.0:
            self._fps = self._fps_count / (now - self._fps_t0)
            self._fps_count = 0
            self._fps_t0 = now

    def _capture_worker(self) -> None:
        failures = 0
        cfg = settings.camera
        while not self._stop_event.is_set():
            cap = self._cap
            if cap is None:
                self._reconnect_loop()
                failures = 0
                continue
            ok, frame = cap.read()
            if ok and frame is not None and frame.size > 0:
                failures = 0
                with self._lock:
                    self._store_frame(frame)
                    if self._state != "streaming":
                        self._state = "streaming"
                        self._error = None
                continue
            failures += 1
            if failures >= cfg.max_consecutive_failures:
                logger.warning("Camera stream lost after %d failed reads; reconnecting", failures)
                with self._lock:
                    self._state = "reconnecting"
                    self._error = "Camera stream lost. Trying to reconnect... (is the iPhone still nearby and unlocked/mounted?)"
                    self._fps = 0.0
                try:
                    cap.release()
                except Exception:
                    pass
                self._cap = None
            else:
                time.sleep(0.02)

    def _reconnect_loop(self) -> None:
        """Re-resolves the device index by unique ID (indices can shift) and tries to reopen it."""
        cfg = settings.camera
        while not self._stop_event.is_set():
            self._reconnect_attempts += 1
            index = self._camera_id
            if self._unique_id and not self._unique_id.startswith("index:"):
                match = next((d for d in self.list_cameras(include_simulated=False)
                              if d["unique_id"] == self._unique_id), None)
                if match is None:
                    with self._lock:
                        self._error = (f"'{self._camera_name}' is no longer available (attempt {self._reconnect_attempts}). "
                                       "Bring the iPhone back near the Mac; reconnection is automatic.")
                    self._stop_event.wait(cfg.reconnect_interval_s)
                    continue
                index = match["index"]
            cap, err = self._open_capture(int(index), *self._requested_size)
            if cap is not None:
                with self._lock:
                    self._cap = cap
                    self._camera_id = index
                    self._state = "streaming"
                    self._error = None
                logger.info("Camera reconnected (index %s) after %d attempts", index, self._reconnect_attempts)
                self._reconnect_attempts = 0
                return
            with self._lock:
                self._error = f"Reconnect attempt {self._reconnect_attempts} failed: {err}"
            self._stop_event.wait(cfg.reconnect_interval_s)

    def _fail(self, message: str) -> None:
        logger.error(message)
        with self._lock:
            self._state = "error"
            self._error = message
            self._camera_id = None
            self._camera_name = "None"
            self._is_simulated = False

    def _stop_capture(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=7.0)
        self._thread = None
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def disconnect(self) -> None:
        """Stops capture and releases the device."""
        with self._lifecycle_lock:
            self._stop_capture()
            with self._lock:
                self._state = "disconnected"
                self._camera_id = None
                self._camera_name = "None"
                self._unique_id = None
                self._is_simulated = False
                self._is_continuity = False
                self._latest_frame = None
                self._error = None
                self._fps = 0.0

    # ------------------------------------------------------------------ frames / status
    def read_frame(self) -> Tuple[bool, Optional[np.ndarray], float]:
        """Returns (ok, newest_frame, timestamp). The frame is shared - copy before drawing on it."""
        with self._lock:
            if self._latest_frame is None or self._state not in ("streaming", "reconnecting"):
                return False, None, 0.0
            if time.time() - self._latest_ts > settings.camera.stall_timeout_s and not self._is_simulated:
                return False, None, self._latest_ts
            return True, self._latest_frame, self._latest_ts

    @property
    def frame_id(self) -> int:
        return self._frame_id

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            resolution = None
            if self._latest_frame is not None:
                h, w = self._latest_frame.shape[:2]
                resolution = [w, h]
            stalled = (self._state == "streaming" and not self._is_simulated and self._latest_ts > 0
                       and time.time() - self._latest_ts > settings.camera.stall_timeout_s)
            return {
                "state": "stalled" if stalled else self._state,
                "connected": self._state == "streaming" and not stalled,
                "camera_id": self._camera_id,
                "camera_name": self._camera_name,
                "unique_id": self._unique_id,
                "is_continuity": self._is_continuity,
                "is_simulated": self._is_simulated,
                "fps": round(self._fps, 1),
                "resolution": resolution,
                "requested_resolution": list(self._requested_size),
                "frame_count": self._frame_id,
                "last_frame_age_s": round(time.time() - self._latest_ts, 2) if self._latest_ts else None,
                "reconnect_attempts": self._reconnect_attempts,
                "error": ("No frames received for several seconds - the camera may have frozen or been taken by another app."
                          if stalled else self._error),
                "permission": permissions.authorization_status(),
                "troubleshooting": TROUBLESHOOTING,
            }


camera_manager = CameraManager()
