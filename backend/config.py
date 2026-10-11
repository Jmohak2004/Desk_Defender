"""Central configuration for Desk Defender.

Every gameplay balance value, role mapping and vision threshold lives here so the
game can be tuned without touching simulation code. Runtime-adjustable settings
(camera resolution, inference rate, thresholds) are persisted to data/settings.json.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("desk_defender.config")

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = Path(os.environ.get("DESK_DEFENDER_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
CALIBRATION_FILE = DATA_DIR / "calibration.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
HIGHSCORES_FILE = DATA_DIR / "highscores.json"

# Development-only synthetic camera. Never selected automatically unless this is set.
SIMULATION_ENV_FLAG = "DESK_DEFENDER_SIMULATED"


def camera_file(prefix: str, camera_uid: str, ext: str) -> Path:
    """Per-camera data file, e.g. motion_ref_<uid>.jpg. Calibration data never leaks across cameras."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", camera_uid or "default")[:64]
    return DATA_DIR / f"{prefix}_{safe}.{ext}"


def simulation_requested() -> bool:
    return os.environ.get(SIMULATION_ENV_FLAG, "").lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Camera / vision (runtime adjustable)
# ---------------------------------------------------------------------------

class CameraConfig(BaseModel):
    width: int = 1920
    height: int = 1080
    reconnect_interval_s: float = 2.0
    max_consecutive_failures: int = 45
    stall_timeout_s: float = 3.0


class VisionConfig(BaseModel):
    model_path: str = "yolov8n.pt"
    device: str = "auto"  # auto | mps | cpu
    inference_fps: float = 8.0
    inference_size: int = 640
    confidence_threshold: float = 0.30
    iou_threshold: float = 0.45
    class_agnostic_nms: bool = True
    # Classes that are never game objects (the desk itself, people, furniture).
    ignored_classes: List[str] = [
        "person", "dining table", "bed", "couch", "chair", "bench", "toilet",
        "sink", "refrigerator", "oven", "car", "bus", "truck", "train", "airplane",
    ]
    # Detections covering more than this fraction of the play area are ignored.
    max_area_fraction: float = 0.35
    # Background-difference detector for objects YOLO does not know (boxes, holders).
    shape_detection_enabled: bool = True
    shape_min_area: float = 900.0      # virtual units^2
    shape_diff_threshold: int = 38
    # Tracking
    tracker_max_distance: float = 120.0   # virtual units
    tracker_min_hits: int = 2             # detections before a track becomes a structure
    reid_max_distance: float = 650.0      # pick-up-and-place moves: re-identify same-class objects this far
    stale_grace_seconds: float = 3.0      # missing time before the structure is removed
    position_smoothing_alpha: float = 0.35
    jitter_deadband: float = 5.0          # virtual units of movement treated as noise
    move_event_threshold: float = 18.0    # movement that counts as a physical reposition
    footprint_scale: float = 0.9
    footprint_min: float = 28.0
    footprint_max: float = 260.0
    # Camera motion warning
    motion_check_interval_s: float = 2.0
    motion_warning_threshold: float = 0.04  # fraction of frame diagonal
    # Preview stream
    preview_fps: float = 15.0
    preview_width: int = 960
    preview_jpeg_quality: int = 72
    low_performance_mode: bool = False


# ---------------------------------------------------------------------------
# Roles: deterministic mapping from detected class -> structure role
# ---------------------------------------------------------------------------

DEFAULT_ROLE_MAPPINGS: Dict[str, str] = {
    "book": "barrier",
    "keyboard": "barrier",
    "remote": "barrier",
    "laptop": "heavy_fortification",
    "bottle": "defense_tower",
    "cup": "defense_tower",
    "wine glass": "defense_tower",
    "bowl": "defense_tower",
    "can": "defense_tower",
    "box": "heavy_fortification",
    "suitcase": "heavy_fortification",
    "backpack": "heavy_fortification",
    "handbag": "heavy_fortification",
    "pencil holder": "support_tower",
    "vase": "support_tower",
    "potted plant": "support_tower",
    "clock": "support_tower",
    "cell phone": "support_tower",
    "mouse": "defense_tower",
    "scissors": "defense_tower",
}
UNKNOWN_ROLE = "custom"


class RoleStats(BaseModel):
    label: str
    behavior: str            # attack | block | support
    cost: int                # credits charged when the structure is activated mid-game
    durability: float
    blocks_path: bool
    footprint_multiplier: float = 1.0
    range: float = 0.0
    damage: float = 0.0
    fire_rate: float = 0.0   # shots / second
    projectile_speed: float = 520.0
    slow_factor: float = 1.0  # movement multiplier applied to enemies in the slow zone
    slow_radius: float = 0.0
    buff_radius: float = 0.0
    buff_damage_multiplier: float = 1.0
    buff_range_multiplier: float = 1.0
    path_cost: float = 1.0   # soft avoidance for passable structures


DEFAULT_ROLES: Dict[str, RoleStats] = {
    "barrier": RoleStats(
        label="Barrier", behavior="block", cost=40, durability=320.0, blocks_path=True,
        slow_factor=0.55, slow_radius=34.0,
    ),
    "defense_tower": RoleStats(
        label="Defense Tower", behavior="attack", cost=60, durability=220.0, blocks_path=False,
        range=225.0, damage=34.0, fire_rate=1.5, path_cost=4.0,
    ),
    "heavy_fortification": RoleStats(
        label="Heavy Fortification", behavior="block", cost=80, durability=900.0, blocks_path=True,
        footprint_multiplier=1.25,
    ),
    "support_tower": RoleStats(
        label="Support Tower", behavior="support", cost=70, durability=260.0, blocks_path=False,
        slow_factor=0.6, slow_radius=150.0, buff_radius=190.0,
        buff_damage_multiplier=1.35, buff_range_multiplier=1.15, path_cost=3.0,
    ),
    "custom": RoleStats(
        label="Custom Structure", behavior="attack", cost=50, durability=260.0, blocks_path=False,
        range=170.0, damage=22.0, fire_rate=1.0, path_cost=3.0,
    ),
}


class CustomStructureConfig(BaseModel):
    """Per-object overrides for the Custom role, set from the assignment panel."""
    behavior: str = "attack"  # attack | block | support
    durability: Optional[float] = None
    range: Optional[float] = None
    damage: Optional[float] = None
    fire_rate: Optional[float] = None
    cost: Optional[int] = None


# ---------------------------------------------------------------------------
# Enemies, waves, abilities
# ---------------------------------------------------------------------------

class EnemyProfile(BaseModel):
    health: float
    speed: float
    radius: float
    reward: int
    base_damage: float
    structure_dps: float          # damage per second when breaching a structure
    threat_aversion: float        # how strongly the AI avoids tower coverage
    sabotage_range: float = 0.0
    sabotage_duration: float = 0.0
    sabotage_cooldown: float = 0.0
    stomp_radius: float = 0.0
    stomp_dps: float = 0.0


DEFAULT_ENEMIES: Dict[str, EnemyProfile] = {
    "scout": EnemyProfile(health=48, speed=112, radius=12, reward=12, base_damage=6,
                          structure_dps=8, threat_aversion=6.0),
    "tank": EnemyProfile(health=300, speed=46, radius=20, reward=30, base_damage=16,
                         structure_dps=30, threat_aversion=0.4),
    "saboteur": EnemyProfile(health=110, speed=78, radius=14, reward=24, base_damage=10,
                             structure_dps=12, threat_aversion=2.0, sabotage_range=95,
                             sabotage_duration=4.5, sabotage_cooldown=7.0),
    "boss": EnemyProfile(health=1700, speed=34, radius=30, reward=180, base_damage=40,
                         structure_dps=70, threat_aversion=0.0, stomp_radius=80, stomp_dps=18),
}


class WaveDefinition(BaseModel):
    enemies: Dict[str, int]
    spawn_interval: float


DEFAULT_WAVES: List[WaveDefinition] = [
    WaveDefinition(enemies={"scout": 7}, spawn_interval=1.4),
    WaveDefinition(enemies={"scout": 7, "tank": 2}, spawn_interval=1.3),
    WaveDefinition(enemies={"scout": 8, "tank": 3, "saboteur": 2}, spawn_interval=1.2),
    WaveDefinition(enemies={"scout": 10, "tank": 4, "saboteur": 3}, spawn_interval=1.1),
    WaveDefinition(enemies={"scout": 8, "tank": 4, "saboteur": 3, "boss": 1}, spawn_interval=1.1),
    WaveDefinition(enemies={"scout": 12, "tank": 6, "saboteur": 4}, spawn_interval=0.95),
    WaveDefinition(enemies={"scout": 12, "tank": 8, "saboteur": 6}, spawn_interval=0.9),
    WaveDefinition(enemies={"scout": 14, "tank": 7, "saboteur": 6, "boss": 2}, spawn_interval=0.85),
]


class AbilityConfig(BaseModel):
    label: str
    cost: int
    cooldown: float
    radius: float = 0.0
    damage: float = 0.0
    duration: float = 0.0
    heal: float = 0.0


DEFAULT_ABILITIES: Dict[str, AbilityConfig] = {
    "strike": AbilityConfig(label="Orbital Strike", cost=90, cooldown=12.0, radius=95.0, damage=160.0),
    "emp": AbilityConfig(label="EMP Pulse", cost=130, cooldown=25.0, duration=3.0),
    "repair": AbilityConfig(label="Nano Repair", cost=110, cooldown=30.0, heal=0.35),
}


class DifficultyConfig(BaseModel):
    initial: float = 1.0
    minimum: float = 0.75
    maximum: float = 1.8
    step_up: float = 0.1
    step_down: float = 0.15


class GameConfig(BaseModel):
    tick_hz: int = 30
    battlefield_width: int = 1000
    battlefield_height: int = 700
    grid_cell_size: int = 25
    obstacle_margin: float = 14.0
    base_x: float = 935.0
    base_y: float = 350.0
    base_radius: float = 38.0
    base_max_health: float = 100.0
    starting_currency: int = 220
    spawn_points: List[List[float]] = [[15, 110], [15, 350], [15, 590], [260, 15], [260, 685]]
    upgrade_costs: List[int] = [100, 180]   # cost to reach level 2, level 3
    upgrade_multiplier: float = 1.3
    wave_clear_bonus_credits: int = 60
    between_wave_repair: float = 0.25
    ghost_memory_seconds: float = 12.0      # re-acquired objects keep paid/upgrade state
    ghost_match_distance: float = 140.0
    max_reroutes_per_tick: int = 8
    roles: Dict[str, RoleStats] = Field(default_factory=lambda: dict(DEFAULT_ROLES))
    enemies: Dict[str, EnemyProfile] = Field(default_factory=lambda: dict(DEFAULT_ENEMIES))
    waves: List[WaveDefinition] = Field(default_factory=lambda: list(DEFAULT_WAVES))
    abilities: Dict[str, AbilityConfig] = Field(default_factory=lambda: dict(DEFAULT_ABILITIES))
    difficulty: DifficultyConfig = Field(default_factory=DifficultyConfig)


class AppSettings(BaseModel):
    camera: CameraConfig = Field(default_factory=CameraConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    game: GameConfig = Field(default_factory=GameConfig)
    role_mappings: Dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_ROLE_MAPPINGS))
    virtual_width: int = 1000
    virtual_height: int = 700


# Fields the UI may change at runtime. Everything else is edited in this file.
RUNTIME_FIELDS = {
    "camera": ["width", "height"],
    "vision": [
        "inference_fps", "inference_size", "confidence_threshold", "device",
        "shape_detection_enabled", "stale_grace_seconds", "position_smoothing_alpha",
        "jitter_deadband", "move_event_threshold", "preview_fps", "low_performance_mode",
    ],
}

LOW_PERFORMANCE_OVERRIDES = {"inference_fps": 3.0, "inference_size": 416, "preview_fps": 8.0,
                             "preview_width": 640}


def role_for_class(detected_class: str, mappings: Optional[Dict[str, str]] = None) -> str:
    """Deterministic class -> role mapping. Exact match first, then substring match."""
    mappings = mappings if mappings is not None else settings.role_mappings
    cls = detected_class.lower().strip()
    if cls in mappings:
        return mappings[cls]
    for key, role in mappings.items():
        if key in cls:
            return role
    return UNKNOWN_ROLE


def runtime_settings_dict() -> Dict[str, Dict]:
    return {
        section: {f: getattr(getattr(settings, section), f) for f in fields}
        for section, fields in RUNTIME_FIELDS.items()
    }


def apply_runtime_settings(update: Dict[str, Dict], persist: bool = True) -> Dict[str, Dict]:
    """Validates and applies a partial runtime settings update."""
    for section, values in update.items():
        if section not in RUNTIME_FIELDS or not isinstance(values, dict):
            raise ValueError(f"Unknown settings section '{section}'")
        target = getattr(settings, section)
        merged = target.model_dump()
        for key, value in values.items():
            if key not in RUNTIME_FIELDS[section]:
                raise ValueError(f"Setting '{section}.{key}' cannot be changed at runtime")
            merged[key] = value
        validated = type(target).model_validate(merged)
        _check_ranges(section, validated)
        setattr(settings, section, validated)
    if persist:
        save_runtime_settings()
    return runtime_settings_dict()


def _check_ranges(section: str, cfg: BaseModel) -> None:
    if section == "vision":
        v: VisionConfig = cfg  # type: ignore[assignment]
        if not 0.5 <= v.inference_fps <= 30:
            raise ValueError("inference_fps must be between 0.5 and 30")
        if not 0.05 <= v.confidence_threshold <= 0.95:
            raise ValueError("confidence_threshold must be between 0.05 and 0.95")
        if v.inference_size not in (320, 416, 480, 640, 800, 960):
            raise ValueError("inference_size must be one of 320, 416, 480, 640, 800, 960")
        if v.device not in ("auto", "mps", "cpu"):
            raise ValueError("device must be auto, mps or cpu")
        if not 0.05 <= v.position_smoothing_alpha <= 1.0:
            raise ValueError("position_smoothing_alpha must be between 0.05 and 1")
        if not 0.5 <= v.stale_grace_seconds <= 30:
            raise ValueError("stale_grace_seconds must be between 0.5 and 30")
    if section == "camera":
        c: CameraConfig = cfg  # type: ignore[assignment]
        if (c.width, c.height) not in ((640, 480), (1280, 720), (1920, 1080), (3840, 2160)):
            raise ValueError("Resolution must be 640x480, 1280x720, 1920x1080 or 3840x2160")


def effective_vision() -> VisionConfig:
    """Vision settings with low-performance overrides applied."""
    v = settings.vision
    if not v.low_performance_mode:
        return v
    return v.model_copy(update=LOW_PERFORMANCE_OVERRIDES)


def save_runtime_settings() -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(runtime_settings_dict(), indent=2))
    except OSError as exc:
        logger.error("Failed to save settings: %s", exc)


def load_runtime_settings() -> None:
    if not SETTINGS_FILE.exists():
        return
    try:
        apply_runtime_settings(json.loads(SETTINGS_FILE.read_text()), persist=False)
        logger.info("Loaded runtime settings from %s", SETTINGS_FILE)
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring invalid settings file %s: %s", SETTINGS_FILE, exc)


settings = AppSettings()
