"""WebSocket payload validation and an HTTP + WebSocket end-to-end run (simulated camera)."""

import time

import pytest
from pydantic import ValidationError

from backend.api.schemas import client_message_adapter


def test_ws_payload_validation():
    assert client_message_adapter.validate_python({"action": "pause"}).action == "pause"
    m = client_message_adapter.validate_python({"action": "set_role", "object_id": "obj_1", "role": "barrier"})
    assert m.role == "barrier"
    m = client_message_adapter.validate_python({"action": "ability", "ability": "strike", "x": 10, "y": 20})
    assert m.x == 10
    for bad in ({"action": "fly"}, {"action": "set_role", "object_id": "o", "role": "dragon"},
                {"action": "ability", "ability": "nuke"}, {"action": "upgrade"}, {},
                {"action": "set_role", "object_id": "o", "role": "custom", "custom": {"behavior": "teleport"}},
                {"action": "sim_move", "sim_id": "s", "x": -5, "y": 1}):
        with pytest.raises(ValidationError):
            client_message_adapter.validate_python(bad)


def test_websocket_and_http_end_to_end():
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        deadline = time.time() + 5
        while not client.get("/api/camera/status").json()["connected"] and time.time() < deadline:
            time.sleep(0.1)
        status = client.get("/api/camera/status").json()
        assert status["connected"] and status["is_simulated"]  # explicitly requested via env flag
        assert client.post("/api/game/start", json={}).status_code == 409 or client.get("/api/calibration").json()["is_calibrated"]
        sugg = client.get("/api/calibration/suggest").json()
        r = client.post("/api/calibration", json={"points": sugg["points"], "frame_size": sugg["frame_size"]})
        assert r.status_code == 200, r.text
        assert client.post("/api/calibration", json={"points": [[0, 0], [1, 1], [2, 2], [3, 3]]}).status_code == 400
        with client.websocket_connect("/ws/game") as ws:
            first = [ws.receive_json()["type"] for _ in range(2)]
            assert first == ["hello", "state"]
            while ws.receive_json()["type"] != "vision":
                pass
            ws.send_text('{"action": "warp"}')
            msg = ws.receive_json()
            while msg["type"] != "error":
                msg = ws.receive_json()
            assert msg["code"] == "invalid_message"
            ws.send_json({"action": "start", "request_id": "r1"})
            seqs = []
            while True:
                msg = ws.receive_json()
                seqs.append(msg["seq"])
                if msg["type"] == "ack":
                    assert msg["ok"] and msg["request_id"] == "r1"
                    break
            assert seqs == sorted(seqs)
            # objects from the simulated desk reach the game as structures
            deadline = time.time() + 6
            while time.time() < deadline:
                state = client.get("/api/game/state").json()
                if len(state["structures"]) >= 5:
                    break
                time.sleep(0.2)
            assert len(state["structures"]) >= 5
            ws.send_json({"action": "pause"})
        assert client.post("/api/game/resume").json()["status"] == "running"
        assert client.post("/api/game/exit").json()["status"] == "idle"
        assert client.get("/api/stream?variant=bogus").status_code == 422


# ---------------------------------------------------------------- camera
