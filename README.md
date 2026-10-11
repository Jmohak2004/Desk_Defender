# Desk Defender

An AI-powered physical-world tower defense game: an iPhone above your desk streams through macOS Continuity Camera,
YOLO + OpenCV detect the objects on the desk, and they become towers and walls on a virtual battlefield.

> Work in progress - the project is being built up layer by layer. See the commit history.

## Backend setup (macOS)

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

## Tests

```bash
venv/bin/python -m pytest tests -q
```

All gameplay balance values and the class → role mapping live in `backend/config.py`.
