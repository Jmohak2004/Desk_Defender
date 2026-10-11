# Desk Defender

A real-time tower defense game where **your physical desk is the map**. An iPhone mounted above the desk streams to the
Mac through Apple's Continuity Camera; Python + OpenCV + YOLO detect the objects on the desk, a homography maps them onto a
virtual battlefield, and they become game structures. Books are walls, bottles and cups are turrets, boxes are fortresses,
a pencil holder powers nearby towers. Enemies plan A* routes around whatever is on the desk, so **moving a real object
changes the battle immediately**.

---

## Architecture

```
 iPhone (Continuity Camera)
        │  AVFoundation
        ▼
┌──────────────────────────── Python backend (FastAPI, :8000) ─────────────────────────────┐
│                                                                                          │
│  camera/manager.py ──► newest-frame buffer (size 1, stale frames dropped)                │
│    capture thread, auto-reconnect by device unique ID                                    │
│        │                                                                                 │
│        ▼                     (own thread, 1–15 Hz, never blocks the event loop)          │
│  vision/pipeline.py ──► detector.py (YOLO on Apple GPU/MPS + empty-desk shape detector)  │
│        │               ──► calibration.py (homography camera px → 1000×700 battlefield)  │
│        │               ──► tracker.py (stable IDs, smoothing, re-ID, stale grace)        │
│        │               ──► camera_motion.py (ORB check: “camera moved, recalibrate”)     │
│        ▼                                                                                 │
│  game/simulation.py  (own thread, fixed 30 Hz timestep, game clock pauses)               │
│    structures.py · pathfinding.py (A* + threat layer) · enemy_ai.py (utility AI, director)│
│        │                                                                                 │
│  api/routes.py (REST, MJPEG stream)       api/websocket.py (/ws/game, typed, seq-numbered)│
└────────┼───────────────────────────────────────────┼─────────────────────────────────────┘
         │ HTTP + multipart MJPEG                     │ state 30 Hz · vision ≤10 Hz · acks
         ▼                                            ▼
┌────────────────────── React + TypeScript frontend (Vite, :5173) ──────────────────────────┐
│ Zustand store · Canvas 2.5D battlefield (60 fps, interpolated) · particles · WebAudio     │
│ Pages: Home · Camera Setup · Calibration · Battlefield · Results · Settings · Scores · Help│
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

Camera capture, vision, simulation and rendering are independent loops: the game keeps a stable 30 Hz tick and the UI
renders at display rate even when detection runs slower.

```
backend/
  main.py                 FastAPI app, lifespan (camera permission, threads, auto-connect)
  config.py               ALL tunables: roles, class→role mapping, enemies, waves, abilities, vision thresholds
  camera/manager.py       CameraManager: list_cameras · connect · read_frame · get_status · disconnect
  camera/permissions.py   macOS camera permission (main thread) + AVFoundation discovery
  camera/synthetic.py     SIMULATED dev camera + colour-key detector (explicit opt-in only)
  vision/                 calibration · detector · tracker · pipeline · camera_motion
  game/                   models · simulation · pathfinding · enemy_ai · structures
  api/                    routes (REST) · websocket · schemas (validated payloads)
  data/                   runtime JSON: per-camera calibration, references, settings, high scores
frontend/src/
  components/             Battlefield, CameraPreview, CalibrationCanvas, GameHUD, ObjectAssignmentPanel, ...
  pages/                  Home, CameraSetup, Calibration, Game, Results, Settings, HighScores, HowToPlay
  hooks/                  useGameSocket (singleton WS, acks), useCameraState
  store/gameStore.ts      Zustand state;   types/game.ts  wire types;   utils/  homography, audio, particles
tests/                         48 automated tests, one file per layer (config, calibration, camera,
                               tracking, pathfinding, gameplay, api)
start.sh                       one-command launcher
```

---

## Prerequisites

| | |
|---|---|
| Mac | macOS 13 Ventura or newer (Apple Silicon recommended - YOLO runs on the GPU via MPS) |
| iPhone | iPhone XR or newer, iOS 16+, signed in to the **same Apple Account** as the Mac |
| Python | 3.11, 3.12 or 3.13 (`brew install python@3.12`) |
| Node.js | 18+ (`brew install node`) |
| Mount | Anything that holds the phone ~50–80 cm above the desk, rear camera pointing down, in landscape |

## Setup (exact commands)

```bash
cd /path/to/desk-defender

# Python backend in a virtual environment
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt

# Frontend
npm --prefix frontend install
```

Or simply run `./start.sh --setup`, which does the same.

### YOLO model

The detector uses Ultralytics **YOLOv8n** (`yolov8n.pt`, 80 COCO classes). The weights file is already in the project root.
If it is missing, Ultralytics downloads it automatically on first use (needs internet once), or fetch it manually:

```bash
curl -L -o yolov8n.pt https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8n.pt
```

To use another model (e.g. `yolov8s.pt` for better accuracy), change `VisionConfig.model_path` in `backend/config.py`.
The model is searched in the project root, `backend/` and `backend/models/`.

---

## Running

```bash
./start.sh            # backend on :8000 + frontend dev server on http://localhost:5173 (opens the browser)
./start.sh --prod     # builds the UI and serves everything from http://localhost:8000 (best for the demo)
./start.sh --sim      # SIMULATED camera - development without hardware (clearly labelled in the UI)
```

Manual equivalent (two terminals, from the project root):

```bash
venv/bin/python -m backend.main          # terminal 1 - backend (http://127.0.0.1:8000, API docs at /docs)
npm --prefix frontend run dev            # terminal 2 - frontend (http://localhost:5173)
```

Always start the backend with `python -m backend.main` from **Terminal / iTerm / VS Code's terminal** - see permissions below.

---

## Continuity Camera

1. On the iPhone: **Settings → General → AirPlay & Continuity** (older iOS: *AirPlay & Handoff*) → **Continuity Camera** on.
2. Wi-Fi and Bluetooth on for both devices, same Apple Account, phone close to the Mac (USB also works).
3. Mount the phone in **landscape**, locked/screen-off, rear camera facing the desk, and keep it still.
4. When the backend opens it, the phone shows *“Connected to Mac”*.

### macOS camera permission

On first launch the backend asks macOS for camera access (a system dialog appears). macOS grants the permission to the
**app that launched Python** - Terminal, iTerm or Visual Studio Code. If you clicked *Don't Allow*:

**System Settings → Privacy & Security → Camera →** enable Terminal / iTerm / Visual Studio Code → restart the backend.

> Why the backend does this itself: OpenCV can only request camera permission from the process main thread, while FastAPI
> handlers run on worker threads. `camera/permissions.py` requests it on the main thread at startup and then tells OpenCV
> to skip its own request.

### Selecting the iPhone camera

The backend never assumes a camera index (and there is no `/dev/video0` on macOS). It lists devices through AVFoundation
in the same order OpenCV's AVFoundation backend indexes them, with real names (e.g. *iPhone Camera*, *MacBook Air Camera*).
On startup it reconnects the camera used last time, or the Continuity Camera if one is present. To pick manually:

1. Open **Camera Setup**.
2. Click *Show a snapshot* under each camera to see what it is pointed at - this confirms the index visually.
3. Click **Use** on the iPhone. The live preview, measured FPS, resolution and permission state are shown.
4. Change resolution (720p / 1080p / 4K) and the detection frequency there.

If the iPhone walks away, the stream drops, or the phone locks, the status changes to *reconnecting* and the backend keeps
trying to reopen **the same device** (matched by unique ID, since indices can shift).

---

## Calibrating the desk

1. Mark a rectangular play area (desk mat, A3 sheet, or four pieces of tape) fully in view of the camera.
2. Open **Calibrate** and click the four corners **clockwise from top-left**, or press **Auto-detect** (finds a clear
   rectangular outline when there is one) and correct the result.
3. Drag handles to adjust; for precision press **Tab** to choose a corner and nudge it with the arrow keys.
   The projected violet grid shows how the 1000×700 battlefield will lie on the desk; bad shapes (wrong order, crossed,
   too small, extreme angles, off-frame) are rejected with an explanation.
4. **Confirm calibration.** It is saved to `backend/data/calibration.json` **per camera** and reloaded automatically.
5. Optional but recommended: clear the desk and press **Capture empty desk**. Objects YOLO cannot name (boxes, pencil
   holders...) are then detected as *unknown object*, and you assign their role manually.

Recalibrate whenever the phone, mount or desk moves. The game compares each frame with the calibration-time view and shows a
**“camera moved - recalibrate”** banner when it detects a shift; when the desk has too little texture to judge, it says
nothing rather than guessing.

---

## Playing

| Object (COCO class) | Default role | Behaviour |
|---|---|---|
| book, keyboard, remote | **Barrier** | blocks paths, slows enemies brushing past, has durability |
| bottle, cup, wine glass, bowl, mouse | **Defense Tower** | shoots enemies in range, does not block movement |
| box, suitcase, backpack, laptop | **Heavy Fortification** | large, very durable obstacle |
| pencil holder, vase, potted plant, clock, cell phone | **Support Tower** | buffs towers in its aura, slows enemies |
| anything else / unknown object | **Custom** | pick behaviour (attack / block / support) and stats yourself |

All mappings and stats are in `backend/config.py` (`DEFAULT_ROLE_MAPPINGS`, `DEFAULT_ROLES`). The model cannot recognise
every object, and top-down views are harder than side views; confidence is shown for every detection. Click any object to
change its role, or **Remove** a false detection (it is then ignored at that spot; *Restore* undoes this).

- Enemies spawn from the left, top and bottom edges and head for the **core** on the right.
  - **Scouts** are fast and take the least-defended route.
  - **Tanks** push the shortest route.
  - **Saboteurs** hunt your most valuable tower and disable it for a few seconds.
  - **Bosses** appear in waves 5 and 8 and crush nearby structures.
- If you wall the core off completely, enemies breach the weakest barrier instead of getting stuck.
- Objects on the desk at game start are free. Objects added or re-assigned mid-game cost credits to power up.
- Credits from kills buy upgrades and abilities: **Orbital Strike** (key 1), **EMP** (2) and **Repair** (3).
- After each wave a report lists what happened, all computed from recorded stats: route lengthening caused by your
  obstacles, top tower, idle towers, leaks per entrance, sabotage count. It also gives suggestions.
- The AI director raises or lowers the next wave's difficulty within fixed limits (×0.75 to ×1.8).
- Keys: **Space** pause/resume · **1/2/3** abilities · **V** cycle split/battle/camera view · **D** debug overlay · **Esc** cancel.

---

## Real vs simulated input

The **real camera is the default**. The backend never switches to a fake camera on its own: if no camera is found it says so
and shows troubleshooting steps.

For development without hardware there is an explicitly labelled **SIMULATED** camera:

```bash
./start.sh --sim                                   # or
DESK_DEFENDER_SIMULATED=1 venv/bin/python -m backend.main
```

or select *Simulated desk* in Camera Setup. In this mode:
- Every frame carries a "SIMULATED CAMERA" watermark, and the UI shows a SIMULATED badge and banner.
- Objects are coloured shapes on a synthetic desk, detected by a real OpenCV colour-contour detector rather than YOLO.
- The *Simulated desk* panel lets you add objects and drag them around the battlefield, which runs the full
  camera → detection → tracking → game loop.
- Calibration, references and the "last camera" are stored per camera, so simulated runs never affect the iPhone's
  calibration.

---

## Tests

```bash
venv/bin/python -m pytest tests -q
```

48 tests cover:
- Coordinate transformation and calibration persistence, per-camera isolation, invalid calibration input (8 cases).
- Role mapping and custom roles.
- Tracking: jitter, real moves, re-identification of picked-up objects, class flicker, stale grace and removal,
  false-positive suppression.
- A* around barriers, towers not blocking, no-path breach planning and actual breaching, threat-aware routing.
- Combat: tower damage and kill, out-of-range, base damage, support aura, upgrades, sabotage, abilities.
- Waves to victory, defeat, pause/resume/restart with a frozen game clock, moving objects rerouting enemies, mid-game costs,
  difficulty limits.
- WebSocket payload validation and an end-to-end HTTP + WebSocket test.
- Camera: lifecycle, invalid IDs, stream drop with automatic reconnect, device disappearing.

Tests use a temporary data directory and the simulated camera; they never open your real camera.

Frontend type-check / production build: `npm --prefix frontend run build`.

---

## Measured performance (this machine)

Measured on an Apple M4 MacBook Air, macOS 26.6, iPhone Continuity Camera at 1920×1080. Your numbers will differ; the
debug overlay (**D**) shows live values.

| What | Measured |
|---|---|
| Continuity Camera capture | ~29.6 fps at 1920×1080 |
| YOLOv8n inference (MPS, 640 px, full 1080p frame in) | ~9 ms isolated, ~17–22 ms inside the running server |
| Detection loop | ~7.7 Hz at the default 8 Hz target (configurable 1–15 Hz) |
| Simulation tick (6 structures, full waves) | 0.13 ms average, ~20 ms worst case (path replans) |
| Object moved → structure moved (simulated camera) | ~0.27 s |

If detection is slow on your Mac, enable **Settings → Low-performance mode** (3 Hz detection, 416 px inference, lighter preview).

---

## API

REST (`http://127.0.0.1:8000/docs` for the interactive schema):

```
GET  /api/health                      GET  /api/diagnostics
GET  /api/cameras                     GET  /api/cameras/{index}/snapshot
POST /api/camera/connect {camera_id, width?, height?}
POST /api/camera/disconnect           GET  /api/camera/status
GET  /api/stream?variant=overlay|raw|warped     (multipart MJPEG)
GET  /api/calibration   POST /api/calibration {points, frame_size}   DELETE /api/calibration
GET  /api/calibration/suggest         POST|DELETE /api/calibration/empty-desk
POST /api/game/start {player_name?}   POST /api/game/pause|resume|restart|next-wave|exit
POST /api/game/ability {ability, x?, y?}      GET /api/game/state
POST /api/structures/{id}/upgrade
GET  /api/objects   POST /api/objects/{object_id}/role {role, custom?}   DELETE /api/objects/{object_id}
GET|DELETE /api/objects/suppressed
GET  /api/config    GET|PUT /api/settings    GET /api/highscores
/api/sim/*          simulated-desk controls (only while the SIMULATED camera is active)
```

WebSocket `/ws/game`. Every server message has `type`, a monotonically increasing `seq` and a server timestamp `ts`.
- `hello`: sent once on connect.
- `state`: game snapshot plus gameplay events since the last message (kills, hits, base hits, wave start/end, sabotage,
  structure added/moved/removed...). Sent at 30 Hz while running, 5 Hz otherwise.
- `vision`: tracked objects with class, confidence, footprint and role, plus camera and pipeline status. Sent only when
  something changed (≤10 Hz), plus a 1 Hz heartbeat.
- `ack` / `error`: replies to client messages.

Client messages are validated by Pydantic (`backend/api/schemas.py`):
`start | restart {player_name?}`, `pause`, `resume`, `next_wave`, `exit`, `ping`, `set_role {object_id, role, custom?}`,
`remove_object {object_id}`, `upgrade {structure_id}`, `ability {ability, x?, y?}`, `sim_move {sim_id, x, y}`.
Each may carry a `request_id`, which is echoed in the `ack`.

---

## Troubleshooting

**The iPhone does not appear in Camera Setup**
- Check the Continuity Camera requirements above; toggle Wi-Fi/Bluetooth on both devices; unlock the phone once and lock it again.
- Click **Refresh**. In a terminal, `system_profiler SPCameraDataType` must list *iPhone Camera*. If it doesn't, macOS itself
  does not see the phone.
- Restart the iPhone or plug it in with a cable.

**“macOS denied camera access” / permission = denied**
- System Settings → Privacy & Security → Camera → enable the terminal app you start the backend from, then restart it.
- To reset the decision: `tccutil reset Camera` (then relaunch and accept the prompt).

**Camera opens but the preview stays black or says “stalled”**
- Another app (FaceTime, Zoom, Photo Booth, a browser tab) may hold the camera - quit it and press **Use** again.
- Continuity Camera delivers a few black frames while starting; wait 2–3 seconds.

**Wrong camera at an index**
- Use the snapshot thumbnails. The *iPhone Desk View* virtual camera is intentionally not listed: OpenCV cannot open it.

**Objects are not detected**
- See the camera view (split view): uncalibrated, raw YOLO boxes are shown; after calibration only objects inside the play
  area become structures.
- Lower the confidence threshold in Settings, improve lighting, raise the phone a little, or capture an empty-desk
  reference so unknown items are picked up.
- `person` and `dining table` are ignored on purpose (see `VisionConfig.ignored_classes`).

**Dependency / model errors**
- `ModuleNotFoundError`: activate the venv (`source venv/bin/activate`) or run `./start.sh --setup`.
- `Could not load YOLO model`: put `yolov8n.pt` in the project root (command above) or allow the first-run download.
- MPS errors: the detector falls back to CPU automatically. You can force CPU in Settings → Inference device.
- `Address already in use` on :8000 / :5173: `lsof -i :8000` and stop the old process.
- `ModuleNotFoundError: AVFoundation`: `pip install pyobjc-framework-AVFoundation`. Without it, cameras are still found
  by probing OpenCV indices, but without names.

**Platform notes**: the camera code targets macOS (AVFoundation). On other systems the CameraManager falls back to probing
OpenCV indices; the rest of the game is platform-independent.
