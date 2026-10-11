"""Test setup: isolate persisted data and never touch real cameras."""

import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="desk_defender_test_")
os.environ["DESK_DEFENDER_DATA_DIR"] = _TMP
os.environ["DESK_DEFENDER_SIMULATED"] = "1"  # the app under test uses the labelled simulated camera
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
