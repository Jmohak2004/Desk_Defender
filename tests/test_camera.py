"""Camera lifecycle, disconnect handling and the simulated camera."""

import time

import numpy as np

from backend.camera.manager import CameraManager
from backend.camera.synthetic import SyntheticDesk, detect_synthetic_objects
from backend.config import settings


def test_synthetic_detector_finds_objects():
    desk = SyntheticDesk()
    dets = detect_synthetic_objects(desk.render())
    kinds = sorted(d["class"] for d in dets)
    assert kinds == sorted(o["kind"] for o in desk.list_objects())


# ---------------------------------------------------------------- pathfinding


def test_camera_simulated_lifecycle():
    cam = CameraManager()
    assert cam.connect("simulated")
    ok, frame, _ = cam.read_frame()
    assert ok and frame.shape == (720, 1280, 3)
    st = cam.get_status()
    assert st["connected"] and st["is_simulated"]
    cam.disconnect()
    assert not cam.get_status()["connected"] and cam.read_frame()[0] is False


def test_camera_invalid_id_reports_error():
    cam = CameraManager()
    assert not cam.connect("not-a-camera")
    st = cam.get_status()
    assert st["state"] == "error" and "Invalid camera id" in st["error"] and not st["connected"]


class _FlakyCapture:
    """Stand-in for cv2.VideoCapture that streams, then drops."""

    def __init__(self, frames_before_drop):
        self.left = frames_before_drop
        self.released = False

    def read(self):
        if self.left > 0:
            self.left -= 1
            time.sleep(0.005)
            return True, np.zeros((72, 128, 3), np.uint8)
        time.sleep(0.001)
        return False, None

    def isOpened(self):
        return not self.released

    def release(self):
        self.released = True


def test_camera_disconnect_is_detected_and_reconnects(monkeypatch):
    from backend.camera import manager as mgr

    monkeypatch.setattr(settings.camera, "reconnect_interval_s", 0.05)
    cam = CameraManager()
    opens = []

    states_at_reopen = []

    def fake_open(index, w, h):
        if opens:
            states_at_reopen.append(cam.get_status()["state"])
        cap = _FlakyCapture(5 if not opens else 10_000)
        opens.append(cap)
        with cam._lock:
            cam._store_frame(np.zeros((72, 128, 3), np.uint8))
        return cap, ""

    monkeypatch.setattr(cam, "_open_capture", fake_open)
    monkeypatch.setattr(cam, "list_cameras", lambda include_simulated=True: [
        {"id": 0, "index": 0, "name": "iPhone Camera", "unique_id": "U1", "is_continuity": True}])
    monkeypatch.setattr(mgr.permissions, "authorization_status", lambda: "authorized")
    assert cam.connect(0)
    deadline = time.time() + 5
    while time.time() < deadline:
        if len(opens) >= 2 and cam.get_status()["state"] == "streaming":
            break
        time.sleep(0.005)
    assert states_at_reopen and states_at_reopen[0] == "reconnecting", "drop must be reported"
    assert len(opens) >= 2 and cam.get_status()["state"] == "streaming"
    assert opens[0].released
    cam.disconnect()
    assert opens[-1].released and cam.get_status()["state"] == "disconnected"


def test_camera_missing_device_keeps_retrying_with_message(monkeypatch):
    monkeypatch.setattr(settings.camera, "reconnect_interval_s", 0.05)
    cam = CameraManager()
    calls = {"n": 0}

    def fake_open(index, w, h):
        calls["n"] += 1
        return (_FlakyCapture(2), "") if calls["n"] == 1 else (None, "gone")

    devices = [{"id": 0, "index": 0, "name": "iPhone Camera", "unique_id": "U1", "is_continuity": True}]
    monkeypatch.setattr(cam, "_open_capture", fake_open)
    monkeypatch.setattr(cam, "list_cameras", lambda include_simulated=True: list(devices))
    from backend.camera import manager as mgr
    monkeypatch.setattr(mgr.permissions, "authorization_status", lambda: "authorized")
    with cam._lock:
        cam._store_frame(np.zeros((72, 128, 3), np.uint8))
    assert cam.connect(0)
    devices.clear()  # iPhone walked away
    deadline = time.time() + 3
    while time.time() < deadline and "no longer available" not in (cam.get_status()["error"] or ""):
        time.sleep(0.01)
    st = cam.get_status()
    assert "no longer available" in st["error"] and not st["connected"]
    cam.disconnect()
