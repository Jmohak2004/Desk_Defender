"""Desk Defender - FastAPI application entry point.

Run from the project root:
    venv/bin/python -m backend.main            (recommended: requests camera permission on the main thread)
    venv/bin/uvicorn backend.main:app --port 8000
"""

import asyncio
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from backend.camera import permissions  # noqa: F401  (sets OPENCV_AVFOUNDATION_SKIP_AUTH before cv2 opens devices)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import LAST_CAMERA_FILE, router as api_router
from backend.api.websocket import broadcast_loop, router as ws_router
from backend.camera.manager import SIMULATED_ID, camera_manager
from backend.config import PROJECT_DIR, load_runtime_settings, simulation_requested
from backend.game.simulation import simulation
from backend.vision.pipeline import pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("desk_defender")


def _auto_connect() -> None:
    """Reconnects the last used real camera, else a Continuity Camera. Never picks the simulator unless asked."""
    if simulation_requested():
        logger.warning("DESK_DEFENDER_SIMULATED is set - using the SIMULATED development camera")
        camera_manager.connect(SIMULATED_ID)
        return
    devices = [d for d in camera_manager.list_cameras(include_simulated=False)]
    if not devices:
        logger.warning("No cameras found. Open Camera Setup in the app for troubleshooting.")
        return
    preferred = None
    if LAST_CAMERA_FILE.exists():
        try:
            last = json.loads(LAST_CAMERA_FILE.read_text())
            preferred = next((d for d in devices if d["unique_id"] == last.get("unique_id")), None)
        except (OSError, ValueError):
            pass
    preferred = preferred or next((d for d in devices if d["is_continuity"]), None)
    if preferred is None:
        logger.info("No Continuity Camera found; choose a camera in Camera Setup. Found: %s",
                    ", ".join(d["name"] for d in devices))
        return
    logger.info("Auto-connecting to %s (index %s)", preferred["name"], preferred["index"])
    if not camera_manager.connect(preferred["index"]):
        logger.warning("Auto-connect failed: %s", camera_manager.get_status()["error"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Desk Defender backend")
    load_runtime_settings()
    if permissions.IS_MACOS:
        status = permissions.request_authorization()  # main thread: may show the macOS prompt
        logger.info("macOS camera permission: %s", status)
        if status in ("denied", "restricted"):
            logger.error("Camera access is %s. Enable it for this terminal app in System Settings > "
                         "Privacy & Security > Camera, then restart.", status)
    pipeline.start()
    simulation.start()
    threading.Thread(target=_auto_connect, name="camera-autoconnect", daemon=True).start()
    task = asyncio.create_task(broadcast_loop())
    yield
    logger.info("Shutting down")
    task.cancel()
    simulation.stop()
    pipeline.stop()
    camera_manager.disconnect()


app = FastAPI(title="Desk Defender API", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router)
app.include_router(ws_router)

# Serve the production frontend build if it exists (npm run build), so one process can run the demo.
DIST = PROJECT_DIR / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = DIST / path
        if path and candidate.is_file() and DIST in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("DESK_DEFENDER_HOST", "127.0.0.1"),
                port=int(os.environ.get("DESK_DEFENDER_PORT", "8000")), log_level="info")
