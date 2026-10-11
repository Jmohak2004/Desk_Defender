"""Game-state data models.

Internal simulation entities are dataclasses (cheap attribute access in the
30 Hz loop). They serialise to compact, rounded dicts for the WebSocket.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class GameStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    WAVE_ENDED = "wave_ended"
    VICTORY = "victory"
    GAME_OVER = "game_over"


ACTIVE_STATUSES = (GameStatus.RUNNING, GameStatus.PAUSED, GameStatus.WAVE_ENDED)


def r1(v: float) -> float:
    return round(float(v), 1)


@dataclass
class Structure:
    id: str
    object_id: str
    detected_class: str
    role: str
    behavior: str            # attack | block | support
    x: float
    y: float
    w: float
    h: float
    max_health: float
    health: float
    cost: int
    blocks_path: bool
    range: float = 0.0
    damage: float = 0.0
    fire_rate: float = 0.0
    projectile_speed: float = 520.0
    slow_factor: float = 1.0
    slow_radius: float = 0.0
    buff_radius: float = 0.0
    buff_damage_multiplier: float = 1.0
    buff_range_multiplier: float = 1.0
    path_cost: float = 1.0
    level: int = 1
    confidence: float = 1.0
    source: str = "yolo"
    stale: bool = False
    active: bool = True       # powered (paid for)
    paid: bool = True
    destroyed: bool = False
    buffed: bool = False
    buff_damage: float = 1.0
    buff_range: float = 1.0
    cooldown: float = 0.0
    disabled_until: float = 0.0
    aim: float = 0.0
    kills: int = 0
    damage_dealt: float = 0.0
    damage_taken: float = 0.0
    custom_key: Optional[str] = None

    @property
    def radius(self) -> float:
        return max(self.w, self.h) / 2.0

    def operational(self, now: float) -> bool:
        return self.active and not self.destroyed and self.disabled_until <= now

    def to_dict(self, now: float, upgrade_cost: Optional[int]) -> Dict:
        return {
            "id": self.id, "object_id": self.object_id, "detected_class": self.detected_class,
            "role": self.role, "behavior": self.behavior,
            "x": r1(self.x), "y": r1(self.y), "w": r1(self.w), "h": r1(self.h),
            "health": r1(self.health), "max_health": r1(self.max_health), "level": self.level,
            "range": r1(self.range * self.buff_range), "damage": r1(self.damage * self.buff_damage),
            "fire_rate": round(self.fire_rate, 2), "slow_radius": r1(self.slow_radius),
            "buff_radius": r1(self.buff_radius), "blocks_path": self.blocks_path,
            "confidence": round(self.confidence, 2), "source": self.source, "stale": self.stale,
            "active": self.active, "destroyed": self.destroyed, "buffed": self.buffed,
            "disabled_for": r1(max(0.0, self.disabled_until - now)), "aim": round(self.aim, 2),
            "kills": self.kills, "damage_dealt": r1(self.damage_dealt), "cost": self.cost,
            "upgrade_cost": upgrade_cost,
        }


@dataclass
class Enemy:
    id: str
    type: str
    x: float
    y: float
    radius: float
    health: float
    max_health: float
    speed: float
    reward: int
    base_damage: float
    structure_dps: float
    lane: int
    path: List[List[float]] = field(default_factory=list)
    path_index: int = 1
    intent: str = "advancing"
    goal: str = "base"            # base | sabotage
    target_structure: Optional[str] = None
    breach_target: Optional[str] = None
    attacking: Optional[str] = None
    needs_reroute: bool = False
    next_decision: float = 0.0
    sabotage_ready_at: float = 0.0
    stunned_until: float = 0.0
    slow_mult: float = 1.0
    heading: float = 0.0
    distance_travelled: float = 0.0
    planned_length: float = 0.0
    straight_length: float = 0.0
    progress_x: float = 0.0
    progress_y: float = 0.0
    progress_t: float = 0.0

    def to_dict(self, now: float) -> Dict:
        remaining = self.path[self.path_index:self.path_index + 24]
        return {
            "id": self.id, "type": self.type, "x": r1(self.x), "y": r1(self.y), "r": self.radius,
            "health": r1(self.health), "max_health": r1(self.max_health), "intent": self.intent,
            "path": [[r1(p[0]), r1(p[1])] for p in remaining], "heading": round(self.heading, 2),
            "stunned": self.stunned_until > now, "slowed": self.slow_mult < 0.99,
            "attacking": self.attacking, "target": self.target_structure or self.breach_target,
        }


@dataclass
class Projectile:
    id: str
    source_id: str
    target_id: str
    x: float
    y: float
    tx: float
    ty: float
    speed: float
    damage: float
    kind: str = "bolt"   # bolt | heavy

    def to_dict(self) -> Dict:
        return {"id": self.id, "x": r1(self.x), "y": r1(self.y), "tx": r1(self.tx), "ty": r1(self.ty), "k": self.kind}


@dataclass
class BaseCore:
    x: float
    y: float
    radius: float
    health: float
    max_health: float

    def to_dict(self) -> Dict:
        return {"x": self.x, "y": self.y, "radius": self.radius, "health": r1(self.health), "max_health": self.max_health}


@dataclass
class WaveStats:
    wave: int
    started_at: float = 0.0
    spawned: int = 0
    total: int = 0
    killed: int = 0
    leaked: int = 0
    damage_received: float = 0.0
    score_earned: int = 0
    credits_earned: int = 0
    structures_destroyed: int = 0
    sabotages: int = 0
    abilities_used: int = 0
    leaks_by_lane: Dict[int, int] = field(default_factory=dict)
    path_ratio_samples: List[float] = field(default_factory=list)
    kills_by_structure: Dict[str, int] = field(default_factory=dict)
    structure_names: Dict[str, str] = field(default_factory=dict)
    no_path_events: int = 0
