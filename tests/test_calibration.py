"""Calibration, homography mapping and validation."""

import pytest

from backend.vision.calibration import DeskCalibration, validate_quad

FRAME = (1280, 720)
QUAD = [[100.0, 100.0], [900.0, 100.0], [900.0, 600.0], [100.0, 600.0]]
# Perspective quad (same shape as the simulated desk)
SCENE_QUAD = [[170.0, 95.0], [1110.0, 95.0], [1175.0, 655.0], [105.0, 655.0]]


def test_calibration_maps_corners_and_center():
    cal = DeskCalibration(1000, 700, filepath=None)
    ok, msg = cal.set_points(QUAD, FRAME)
    assert ok, msg
    for (cx, cy), (vx, vy) in zip(QUAD, [(0, 0), (1000, 0), (1000, 700), (0, 700)]):
        tx, ty = cal.transform_point(cx, cy)
        assert abs(tx - vx) < 0.5 and abs(ty - vy) < 0.5
    assert all(abs(a - b) < 0.5 for a, b in zip(cal.transform_point(500, 350), (500, 350)))
    back = cal.inverse_transform_point(*cal.transform_point(321, 456))
    assert abs(back[0] - 321) < 0.5 and abs(back[1] - 456) < 0.5


def test_calibration_perspective_quad():
    cal = DeskCalibration(1000, 700, filepath=None)
    assert cal.set_points(SCENE_QUAD, FRAME)[0]
    vx, vy = cal.transform_point(*SCENE_QUAD[2])
    assert abs(vx - 1000) < 0.5 and abs(vy - 700) < 0.5


def test_calibration_save_and_reload(tmp_path):
    f = tmp_path / "cal.json"
    cal = DeskCalibration(1000, 700, filepath=f, autoload=False)
    cal.set_points(QUAD, FRAME)
    again = DeskCalibration(1000, 700, filepath=f)
    assert again.is_calibrated and again.points == QUAD and again.frame_size == FRAME


def test_calibration_rescales_with_resolution(tmp_path):
    cal = DeskCalibration(1000, 700, filepath=None)
    cal.set_points(QUAD, FRAME)
    cal.adapt_to_frame((1920, 1080))
    vx, vy = cal.transform_point(900 * 1.5, 600 * 1.5)
    assert abs(vx - 1000) < 0.5 and abs(vy - 700) < 0.5


@pytest.mark.parametrize("points,fragment", [
    ([[0, 0], [10, 10]], "Expected 4"),
    ([[10, 10], [20, 20], [30, 30], [40, 40]], ""),
    ([[100, 100], [100, 600], [900, 600], [900, 100]], "order"),          # counter-clockwise
    ([[100, 100], [900, 600], [900, 100], [100, 600]], ""),               # self-intersecting
    ([[100, 100], [900, 100], [900, 600], [100, 600.0], ], None),          # valid control
    ([[-500, 100], [900, 100], [900, 600], [100, 600]], "outside"),
    ([[100, 100], [140, 100], [140, 130], [100, 130]], "too small"),
    ([[100, 100], [1200, 100], [700, 130], [600, 130]], ""),               # extreme / degenerate
])
def test_invalid_calibration_rejected(points, fragment):
    ok, msg = validate_quad(points, FRAME)
    if fragment is None:
        assert ok, msg
    else:
        assert not ok
        assert fragment.lower() in msg.lower()


def test_uncalibrated_transform_raises():
    cal = DeskCalibration(filepath=None)
    with pytest.raises(RuntimeError):
        cal.transform_point(1, 1)


# ---------------------------------------------------------------- roles


def test_calibration_is_per_camera(tmp_path):
    f = tmp_path / "cal.json"
    cal = DeskCalibration(1000, 700, filepath=f, autoload=False)
    cal.use_camera("iphone")
    assert cal.set_points(QUAD, FRAME)[0]
    assert not cal.use_camera("webcam") and not cal.is_calibrated  # never reuse another camera's corners
    assert cal.use_camera("iphone") and cal.points == QUAD
    cal.clear()
    assert not DeskCalibration(1000, 700, filepath=f, autoload=False).use_camera("iphone")
