"""Real-time WebSocket channel (/ws/game).

Server -> client messages (all carry `seq` and server timestamp `ts`):
  hello   - protocol version, sent once on connect
  state   - game snapshot + drained gameplay events; 30 Hz while running, 5 Hz otherwise
  vision  - tracked objects, camera + pipeline status; only when they change (<= 10 Hz) plus 1 Hz heartbeat
  ack     - reply to a client action (ok / message / request_id)
  error   - invalid message or failed action

Client -> server messages are validated against backend.api.schemas.ClientMessage.
"""

import asyncio
import itertools
import json
import logging
import time
from typing import Any, Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from backend.api.schemas import client_message_adapter
from backend.camera.manager import camera_manager
from backend.camera.synthetic import synthetic_desk
from backend.game.simulation import simulation
from backend.vision.calibration import calibration
from backend.vision.pipeline import pipeline
from backend.vision.tracker import tracker

logger = logging.getLogger("desk_defender.websocket")

PROTOCOL_VERSION = 2
router = APIRouter()
_seq = itertools.count(1)


def envelope(msg_type: str, **payload: Any) -> Dict[str, Any]:
    return {"type": msg_type, "seq": next(_seq), "ts": round(time.time(), 3), **payload}


class ConnectionManager:
    def __init__(self):
        self.clients: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)
        logger.info("WebSocket client connected (%d total)", len(self.clients))

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def send(self, ws: WebSocket, message: Dict[str, Any]) -> None:
        await asyncio.wait_for(ws.send_text(json.dumps(message, separators=(",", ":"))), timeout=1.0)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        if not self.clients:
            return
        text = json.dumps(message, separators=(",", ":"))
        dead = []
        for ws in list(self.clients):
            try:
                await asyncio.wait_for(ws.send_text(text), timeout=1.0)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


def vision_payload() -> Dict[str, Any]:
    cam = camera_manager.get_status()
    cam.pop("troubleshooting", None)
    payload = {
        "objects": tracker.snapshot(),
        "suppressed": tracker.suppressed(),
        "camera": cam,
        "pipeline": pipeline.get_status(),
        "calibration": {"is_calibrated": calibration.is_calibrated, "version": calibration.version,
                        "frame_size": list(calibration.frame_size) if calibration.frame_size else None},
    }
    if cam["is_simulated"]:
        payload["sim_objects"] = synthetic_desk.list_objects()
    return payload


def handle_action(msg) -> Dict[str, Any]:
    """Executes a validated client action and returns (ok, message)."""
    a = msg.action
    if a in ("start", "restart"):
        cam = camera_manager.get_status()
        if not cam["connected"]:
            return {"ok": False, "message": "No camera connected - open Camera Setup first."}
        if not calibration.is_calibrated:
            return {"ok": False, "message": "Desk is not calibrated - open Calibration first."}
        simulation.start_game(msg.player_name)
        return {"ok": True, "message": "Game started"}
    if a == "pause":
        return {"ok": simulation.pause(), "message": "Paused"}
    if a == "resume":
        return {"ok": simulation.resume(), "message": "Resumed"}
    if a == "next_wave":
        ok = simulation.next_wave()
        return {"ok": ok, "message": "Next wave" if ok else "No wave to start"}
    if a == "exit":
        simulation.exit_game()
        return {"ok": True, "message": "Exited game"}
    if a == "ping":
        return {"ok": True, "message": "pong"}
    if a == "set_role":
        ok = tracker.set_role(msg.object_id, msg.role, msg.custom)
        return {"ok": ok, "message": f"{msg.object_id} -> {msg.role}" if ok else f"{msg.object_id} is not tracked"}
    if a == "remove_object":
        ok = tracker.remove(msg.object_id)
        return {"ok": ok, "message": f"Removed {msg.object_id}" if ok else f"{msg.object_id} is not tracked"}
    if a == "upgrade":
        ok, text = simulation.upgrade(msg.structure_id)
        return {"ok": ok, "message": text}
    if a == "ability":
        ok, text = simulation.use_ability(msg.ability, msg.x, msg.y)
        return {"ok": ok, "message": text}
    if a == "sim_move":
        if not camera_manager.get_status()["is_simulated"]:
            return {"ok": False, "message": "Simulated objects can only be moved with the SIMULATED camera"}
        ok = synthetic_desk.move_object(msg.sim_id, msg.x, msg.y) is not None
        return {"ok": ok, "message": "moved" if ok else "unknown simulated object"}
    return {"ok": False, "message": f"Unhandled action {a}"}


@router.websocket("/ws/game")
async def game_socket(ws: WebSocket):
    await manager.connect(ws)
    try:
        await manager.send(ws, envelope("hello", protocol=PROTOCOL_VERSION))
        await manager.send(ws, envelope("state", game=await asyncio.to_thread(simulation.snapshot), events=[]))
        await manager.send(ws, envelope("vision", **await asyncio.to_thread(vision_payload)))
        while True:
            text = await ws.receive_text()
            if len(text) > 8192:
                await manager.send(ws, envelope("error", code="too_large", message="Message too large"))
                continue
            try:
                msg = client_message_adapter.validate_json(text)
            except ValidationError as exc:
                errs = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3])
                await manager.send(ws, envelope("error", code="invalid_message", message=errs))
                continue
            try:
                result = await asyncio.to_thread(handle_action, msg)
            except ValueError as exc:
                result = {"ok": False, "message": str(exc)}
            await manager.send(ws, envelope("ack", action=msg.action, request_id=msg.request_id, **result))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
    finally:
        manager.disconnect(ws)
        logger.info("WebSocket client disconnected (%d left)", len(manager.clients))


async def broadcast_loop() -> None:
    last_state = 0.0
    last_vision = 0.0
    last_vision_key = None
    while True:
        try:
            now = time.time()
            if manager.clients:
                running = simulation.status.value == "running"
                if now - last_state >= (1 / 30 if running else 1 / 5):
                    last_state = now
                    game = await asyncio.to_thread(simulation.snapshot)
                    events = simulation.drain_events()
                    await manager.broadcast(envelope("state", game=game, events=events))
                key = (tracker.version, pipeline.version, calibration.version, camera_manager.get_status()["state"])
                if (key != last_vision_key and now - last_vision >= 0.1) or now - last_vision >= 1.0:
                    last_vision_key = key
                    last_vision = now
                    await manager.broadcast(envelope("vision", **await asyncio.to_thread(vision_payload)))
            else:
                simulation.drain_events()
            await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Broadcast loop error")
            await asyncio.sleep(0.2)
