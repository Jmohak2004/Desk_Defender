"""HTTP endpoints. Blocking work (camera open, JPEG encode) runs in FastAPI's threadpool."""

import json
import time
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from backend.api.schemas import (AbilityRequest, CalibrationRequest, ConnectRequest, RoleRequest, SimObjectCreate,
                                 SimObjectMove, StartRequest)
from backend.camera import permissions
from backend.camera.manager import SIMULATED_ID, camera_manager
from backend.camera.synthetic import SCENE_QUAD, synthetic_desk
from backend.config import (DATA_DIR, apply_runtime_settings, effective_vision, runtime_settings_dict, settings,
                            simulation_requested)
from backend.game.simulation import load_highscores, simulation
from backend.vision.calibration import calibration, suggest_corners
from backend.vision.camera_motion import camera_motion
from backend.vision.detector import shape_detector, yolo_detector
from backend.vision.pipeline import activate_camera_context, pipeline, placeholder_jpeg
from backend.vision.tracker import tracker

router = APIRouter(prefix="/api")

LAST_CAMERA_FILE = DATA_DIR / "last_camera.json"


def remember_camera(status: Dict) -> None:
    if status.get("camera_id") is None:
        return
    devices = camera_manager.list_cameras()
    dev = next((d for d in devices if d["id"] == status["camera_id"]), None)
    if dev:
        LAST_CAMERA_FILE.write_text(json.dumps({"unique_id": dev["unique_id"], "name": dev["name"]}))


# ------------------------------------------------------------------ health / diagnostics
@router.get("/health")
def health():
    cam = camera_manager.get_status()
    return {
        "status": "ok",
        "service": "desk-defender",
        "time": time.time(),
        "camera_connected": cam["connected"],
        "camera_simulated": cam["is_simulated"],
        "camera_permission": cam["permission"],
        "calibrated": calibration.is_calibrated,
        "model_status": yolo_detector.status,
        "game_status": simulation.status.value,
    }


@router.get("/diagnostics")
def diagnostics():
    return {
        "camera": camera_manager.get_status(),
        "devices": camera_manager.list_cameras(),
        "avfoundation_available": permissions.HAS_AVFOUNDATION,
        "pipeline": pipeline.get_status(),
        "calibration": calibration.to_dict(),
        "simulation_env": simulation_requested(),
        "model_path": yolo_detector.model_path or settings.vision.model_path,
    }


# ------------------------------------------------------------------ cameras
@router.get("/cameras")
def list_cameras():
    return camera_manager.list_cameras()


@router.get("/cameras/{index}/snapshot")
def camera_snapshot(index: int):
    data = camera_manager.snapshot(index)
    if data is None:
        raise HTTPException(503, f"Camera {index} did not return a frame (it may be busy, asleep or not permitted).")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/camera/connect")
def connect_camera(req: ConnectRequest):
    if str(req.camera_id) != SIMULATED_ID and simulation.status.value == "running":
        simulation.pause()
    ok = camera_manager.connect(req.camera_id, req.width, req.height)
    status = camera_manager.get_status()
    if not ok:
        raise HTTPException(400, status.get("error") or "Failed to connect to camera")
    if not status["is_simulated"]:
        remember_camera(status)
    activate_camera_context(status.get("unique_id"))
    return status


@router.post("/camera/disconnect")
def disconnect_camera():
    camera_manager.disconnect()
    return camera_manager.get_status()


@router.get("/camera/status")
def camera_status():
    return camera_manager.get_status()


@router.get("/camera/frame")
def camera_frame(variant: str = Query("overlay", pattern="^(overlay|raw|warped)$")):
    jpg = pipeline.render_jpeg(variant)
    if jpg is None:
        raise HTTPException(503, camera_manager.get_status().get("error") or "No camera frame available")
    return Response(content=jpg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/stream")
def mjpeg_stream(variant: str = Query("overlay", pattern="^(overlay|raw|warped)$")):
    """Multipart MJPEG stream - one long-lived <img> instead of polling JPEGs."""

    def frames():
        last = None
        while True:
            v = effective_vision()
            jpg = pipeline.render_jpeg(variant)
            if jpg is None:
                cam = camera_manager.get_status()
                if variant == "warped" and cam["connected"]:
                    msg = "Calibrate the desk to see the top-down view"
                else:
                    msg = cam.get("error") or ("Camera disconnected - choose a camera in Camera Setup"
                                               if not cam["connected"] else "Waiting for frames...")
                jpg = placeholder_jpeg(msg)
                time.sleep(0.5)
            elif jpg is last:
                time.sleep(0.01)
                continue
            last = jpg
            yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
            time.sleep(1.0 / max(1.0, v.preview_fps))

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------ calibration
@router.get("/calibration")
def get_calibration():
    data = calibration.to_dict()
    data["empty_desk_reference"] = shape_detector.has_reference
    data["camera_motion"] = camera_motion.to_dict()
    return data


@router.get("/calibration/suggest")
def suggest_calibration():
    ok, frame, _ = camera_manager.read_frame()
    if not ok or frame is None:
        raise HTTPException(409, "No camera frame available - connect a camera first.")
    h, w = frame.shape[:2]
    if camera_manager.get_status()["is_simulated"]:
        return {"points": SCENE_QUAD, "frame_size": [w, h], "message": "Simulated desk outline (exact)."}
    pts, msg = suggest_corners(frame)
    return {"points": pts, "frame_size": [w, h], "message": msg}


@router.post("/calibration")
def set_calibration(req: CalibrationRequest):
    ok, frame, _ = camera_manager.read_frame()
    if not ok or frame is None:
        raise HTTPException(409, "Connect a camera before calibrating - corners must match a live frame.")
    h, w = frame.shape[:2]
    pts = req.points
    if req.frame_size and tuple(req.frame_size) != (w, h):
        sx, sy = w / req.frame_size[0], h / req.frame_size[1]
        pts = [[p[0] * sx, p[1] * sy] for p in pts]
    activate_camera_context(camera_manager.get_status().get("unique_id"))
    valid, msg = calibration.set_points(pts, (w, h))
    if not valid:
        raise HTTPException(400, msg)
    camera_motion.set_reference(frame)
    tracker.reset()
    return {**calibration.to_dict(), "message": msg}


@router.delete("/calibration")
def clear_calibration():
    calibration.clear()
    camera_motion.clear()
    tracker.reset()
    return calibration.to_dict()


@router.post("/calibration/empty-desk")
def capture_empty_desk():
    if not calibration.is_calibrated:
        raise HTTPException(409, "Calibrate the desk corners first.")
    ok, frame, _ = camera_manager.read_frame()
    if not ok or frame is None:
        raise HTTPException(409, "No camera frame available.")
    shape_detector.set_reference(calibration.warp_frame(frame), calibration.version)
    tracker.reset()
    return {"empty_desk_reference": True,
            "message": "Empty-desk reference captured. Objects YOLO cannot name will now appear as 'unknown object'."}


@router.delete("/calibration/empty-desk")
def clear_empty_desk():
    shape_detector.clear_reference()
    return {"empty_desk_reference": False}


# ------------------------------------------------------------------ game
def _require_ready():
    cam = camera_manager.get_status()
    if not cam["connected"]:
        raise HTTPException(409, "No camera connected. Open Camera Setup and connect your iPhone (or the labelled simulated camera for development).")
    if not calibration.is_calibrated:
        raise HTTPException(409, "The desk is not calibrated. Open Calibration and mark the four corners.")


@router.post("/game/start")
def start_game(req: Optional[StartRequest] = None):
    _require_ready()
    simulation.start_game(req.player_name if req else None)
    return simulation.snapshot()


@router.post("/game/pause")
def pause_game():
    simulation.pause()
    return simulation.snapshot()


@router.post("/game/resume")
def resume_game():
    simulation.resume()
    return simulation.snapshot()


@router.post("/game/restart")
def restart_game(req: Optional[StartRequest] = None):
    _require_ready()
    simulation.restart(req.player_name if req else None)
    return simulation.snapshot()


@router.post("/game/next-wave")
def next_wave():
    if not simulation.next_wave():
        raise HTTPException(409, "The next wave can only start after a wave has ended.")
    return simulation.snapshot()


@router.post("/game/exit")
def exit_game():
    simulation.exit_game()
    return simulation.snapshot()


@router.post("/game/ability")
def use_ability(req: AbilityRequest):
    ok, msg = simulation.use_ability(req.ability, req.x, req.y)
    if not ok:
        raise HTTPException(409, msg)
    return {"message": msg}


@router.get("/game/state")
def game_state():
    return simulation.snapshot()


@router.get("/game/nav")
def game_nav():
    return simulation.nav_debug()


@router.post("/structures/{structure_id}/upgrade")
def upgrade(structure_id: str):
    ok, msg = simulation.upgrade(structure_id)
    if not ok:
        raise HTTPException(409, msg)
    return {"message": msg}


# ------------------------------------------------------------------ objects
@router.get("/objects")
def list_objects():
    return tracker.snapshot()


@router.post("/objects/{object_id}/role")
def set_role(object_id: str, req: RoleRequest):
    if not tracker.set_role(object_id, req.role, req.custom):
        raise HTTPException(404, f"Object '{object_id}' is not currently tracked.")
    return tracker.get(object_id)


@router.delete("/objects/suppressed")
def restore_suppressed():
    tracker.clear_suppressed()
    return {"suppressed": []}


@router.get("/objects/suppressed")
def list_suppressed():
    return tracker.suppressed()


@router.delete("/objects/{object_id}")
def remove_object(object_id: str):
    if not tracker.remove(object_id):
        raise HTTPException(404, f"Object '{object_id}' is not currently tracked.")
    return {"removed": object_id, "suppressed": tracker.suppressed()}


# ------------------------------------------------------------------ config / settings / scores
@router.get("/config")
def game_config():
    g = settings.game
    return {
        "roles": {k: v.model_dump() for k, v in g.roles.items()},
        "role_mappings": settings.role_mappings,
        "enemies": {k: v.model_dump() for k, v in g.enemies.items()},
        "abilities": {k: v.model_dump() for k, v in g.abilities.items()},
        "waves": [w.model_dump() for w in g.waves],
        "upgrade_costs": g.upgrade_costs,
        "battlefield": {"width": g.battlefield_width, "height": g.battlefield_height},
        "difficulty": g.difficulty.model_dump(),
    }


@router.get("/settings")
def get_settings():
    return runtime_settings_dict()


@router.put("/settings")
def put_settings(update: Dict[str, Dict]):
    try:
        result = apply_runtime_settings(update)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if "device" in update.get("vision", {}) and yolo_detector.status == "ready":
        yolo_detector.device = yolo_detector._pick_device()
    return result


@router.get("/highscores")
def highscores():
    return load_highscores()


# ------------------------------------------------------------------ simulated desk (dev only)
def _require_simulated():
    if not camera_manager.get_status()["is_simulated"]:
        raise HTTPException(409, "Simulated-desk controls are only available while the SIMULATED camera is selected.")


@router.get("/sim/objects")
def sim_objects():
    _require_simulated()
    return synthetic_desk.list_objects()


@router.post("/sim/objects")
def sim_add(req: SimObjectCreate):
    _require_simulated()
    return synthetic_desk.add_object(req.kind, req.x, req.y)


@router.put("/sim/objects/{sim_id}")
def sim_move(sim_id: str, req: SimObjectMove):
    _require_simulated()
    obj = synthetic_desk.move_object(sim_id, req.x, req.y)
    if obj is None:
        raise HTTPException(404, f"Simulated object '{sim_id}' not found")
    return obj


@router.delete("/sim/objects/{sim_id}")
def sim_remove(sim_id: str):
    _require_simulated()
    if not synthetic_desk.remove_object(sim_id):
        raise HTTPException(404, f"Simulated object '{sim_id}' not found")
    return {"removed": sim_id}


@router.post("/sim/reset")
def sim_reset():
    _require_simulated()
    synthetic_desk.reset()
    return synthetic_desk.list_objects()
