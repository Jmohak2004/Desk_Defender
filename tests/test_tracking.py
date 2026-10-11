"""Object tracking: stable IDs, smoothing, stale handling, suppression."""

import pytest

from backend.config import settings
from backend.vision.calibration import DeskCalibration
from backend.vision.tracker import ObjectTracker


def _tracker():
    cal = DeskCalibration(1000, 700, filepath=None)
    cal.set_points([[0, 0], [1000, 0], [1000, 700], [0, 700]], (1000, 700))
    return ObjectTracker(cal.transform_bbox)


def test_tracking_stable_id_under_jitter_and_movement():
    tr = _tracker()
    t = 1000.0
    tr.update([{"class": "book", "confidence": 0.9, "bbox": [200, 200, 300, 330]}], now=t)
    tr.update([{"class": "book", "confidence": 0.9, "bbox": [201, 199, 301, 331]}], now=t + 0.1)
    objs = tr.snapshot()
    assert len(objs) == 1 and objs[0]["confirmed"]
    oid = objs[0]["id"]
    c0 = objs[0]["center"]
    for i in range(10):  # +-2 px noise must not move it
        d = 2 if i % 2 else -2
        tr.update([{"class": "book", "confidence": 0.9, "bbox": [200 + d, 200 - d, 300 + d, 330 - d]}], now=t + 0.2 + i * 0.1)
    objs = tr.snapshot()
    assert objs[0]["id"] == oid and objs[0]["center"] == c0 and objs[0]["move_count"] == 0
    for i in range(12):  # genuine 90 px move
        tr.update([{"class": "book", "confidence": 0.9, "bbox": [290, 200, 390, 330]}], now=t + 2 + i * 0.1)
    objs = tr.snapshot()
    assert len(objs) == 1 and objs[0]["id"] == oid
    assert abs(objs[0]["center"][0] - 340) < 6 and objs[0]["move_count"] >= 1


def test_tracking_class_flicker_keeps_majority_label():
    tr = _tracker()
    for i in range(6):
        cls = "cup" if i != 3 else "bottle"
        tr.update([{"class": cls, "confidence": 0.8, "bbox": [500, 300, 550, 350]}], now=10 + i * 0.1)
    assert tr.snapshot()[0]["detected_class"] == "cup"


def test_tracking_stale_grace_then_removal():
    tr = _tracker()
    tr.update([{"class": "cup", "confidence": 0.9, "bbox": [500, 300, 550, 350]}], now=0.0)
    tr.update([{"class": "cup", "confidence": 0.9, "bbox": [500, 300, 550, 350]}], now=0.1)
    tr.update([], now=1.0)
    o = tr.snapshot()[0]
    assert o["is_stale"]
    tr.update([], now=0.1 + settings.vision.stale_grace_seconds + 0.5)
    assert tr.snapshot() == []


def test_single_frame_false_positive_never_confirms():
    tr = _tracker()
    tr.update([{"class": "cup", "confidence": 0.4, "bbox": [500, 300, 550, 350]}], now=0.0)
    assert not tr.snapshot()[0]["confirmed"]
    tr.update([], now=0.1)
    tr.update([], now=0.2)
    assert tr.snapshot() == []


def test_manual_removal_suppresses_redetection():
    tr = _tracker()
    det = [{"class": "remote", "confidence": 0.5, "bbox": [100, 100, 160, 140]}]
    tr.update(det, now=0)
    tr.update(det, now=0.1)
    oid = tr.snapshot()[0]["id"]
    assert tr.remove(oid)
    tr.update(det, now=0.2)
    assert tr.snapshot() == []
    tr.clear_suppressed()
    tr.update(det, now=0.3)
    assert len(tr.snapshot()) == 1


def test_role_override():
    tr = _tracker()
    det = [{"class": "book", "confidence": 0.9, "bbox": [100, 100, 200, 200]}]
    tr.update(det, now=0)
    oid = tr.snapshot()[0]["id"]
    assert tr.set_role(oid, "defense_tower")
    assert tr.get(oid)["role"] == "defense_tower" and tr.get(oid)["is_manual_role"]
    with pytest.raises(ValueError):
        tr.set_role(oid, "laser_shark")


def test_tracking_reidentifies_relocated_object():
    tr = _tracker()
    a = [{"class": "book", "confidence": 0.9, "bbox": [100, 100, 200, 230]}]
    tr.update(a, now=0)
    tr.update(a, now=0.1)
    oid = tr.snapshot()[0]["id"]
    moved = [{"class": "book", "confidence": 0.9, "bbox": [600, 400, 700, 530]}]  # picked up, placed far away
    tr.update(moved, now=0.2)
    objs = tr.snapshot()
    assert len(objs) == 1 and objs[0]["id"] == oid and objs[0]["center"] == [650.0, 465.0] and objs[0]["move_count"] == 1
