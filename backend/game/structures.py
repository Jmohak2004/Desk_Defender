"""Structure creation, upgrades and support auras - all driven by config.ROLE stats."""

import math
from typing import Dict, List, Optional, Tuple

from backend.config import CustomStructureConfig, RoleStats, settings
from backend.game.models import Structure


def role_stats(role: str, custom: Optional[Dict] = None) -> RoleStats:
    """Returns stats for a role; the Custom role merges per-object overrides."""
    roles = settings.game.roles
    base = roles.get(role, roles["custom"])
    if role != "custom" or not custom:
        return base
    cfg = CustomStructureConfig.model_validate(custom)
    # Custom structures inherit the mechanics of the behaviour they imitate.
    template = {"attack": roles["defense_tower"], "block": roles["barrier"], "support": roles["support_tower"]}[cfg.behavior]
    merged = template.model_copy(update={"label": base.label, "cost": base.cost, "durability": base.durability})
    updates = {k: v for k, v in {
        "durability": cfg.durability, "range": cfg.range, "damage": cfg.damage,
        "fire_rate": cfg.fire_rate, "cost": cfg.cost,
    }.items() if v is not None}
    return merged.model_copy(update=updates)


def custom_key(role: str, custom: Optional[Dict]) -> Optional[str]:
    if role != "custom" or not custom:
        return None
    return repr(sorted(custom.items()))


def create_structure(obj: Dict) -> Structure:
    """Builds a structure from a tracker snapshot dict."""
    stats = role_stats(obj["role"], obj.get("custom"))
    fw, fh = obj["footprint"]
    m = stats.footprint_multiplier
    s = Structure(
        id=f"struct_{obj['id']}", object_id=obj["id"], detected_class=obj["detected_class"],
        role=obj["role"], behavior=stats.behavior, x=obj["center"][0], y=obj["center"][1],
        w=fw * m, h=fh * m, max_health=stats.durability, health=stats.durability, cost=stats.cost,
        blocks_path=stats.blocks_path, confidence=obj.get("confidence", 1.0),
        source=obj.get("source", "yolo"), stale=obj.get("is_stale", False),
        custom_key=custom_key(obj["role"], obj.get("custom")),
    )
    apply_stats(s, stats)
    return s


def apply_stats(s: Structure, stats: RoleStats) -> None:
    s.behavior = stats.behavior
    s.blocks_path = stats.blocks_path
    s.cost = stats.cost
    s.range = stats.range
    s.damage = stats.damage
    s.fire_rate = stats.fire_rate
    s.projectile_speed = stats.projectile_speed
    s.slow_factor = stats.slow_factor
    s.slow_radius = stats.slow_radius
    s.buff_radius = stats.buff_radius
    s.buff_damage_multiplier = stats.buff_damage_multiplier
    s.buff_range_multiplier = stats.buff_range_multiplier
    s.path_cost = stats.path_cost
    s.max_health = stats.durability
    s.health = min(s.health, s.max_health)
    for _ in range(s.level - 1):
        _scale_level(s)


def change_role(s: Structure, role: str, custom: Optional[Dict]) -> None:
    """Re-skins a structure with a new role. Upgrades reset; health fraction is kept."""
    frac = s.health / s.max_health if s.max_health > 0 else 1.0
    stats = role_stats(role, custom)
    s.role = role
    s.level = 1
    s.custom_key = custom_key(role, custom)
    apply_stats(s, stats)
    s.health = s.max_health * frac


def upgrade_cost(s: Structure) -> Optional[int]:
    costs = settings.game.upgrade_costs
    return costs[s.level - 1] if s.level - 1 < len(costs) else None


def _scale_level(s: Structure) -> None:
    m = settings.game.upgrade_multiplier
    s.max_health *= m
    if s.behavior == "attack":
        s.damage *= m
        s.range *= 1.1
        s.fire_rate *= 1.15
    elif s.behavior == "support":
        s.buff_radius *= 1.1
        s.slow_radius *= 1.1
        s.buff_damage_multiplier += 0.1
        s.slow_factor = max(0.3, s.slow_factor - 0.05)


def upgrade_structure(s: Structure, credits: int) -> Tuple[bool, int, str]:
    cost = upgrade_cost(s)
    if cost is None:
        return False, credits, f"{s.detected_class} is already at max level {s.level}."
    if s.destroyed:
        return False, credits, "Destroyed structures must be repaired before upgrading."
    if credits < cost:
        return False, credits, f"Not enough credits: upgrade costs {cost}, you have {credits}."
    frac = s.health / s.max_health
    s.level += 1
    _scale_level(s)
    s.health = s.max_health * max(frac, 0.5)
    return True, credits - cost, f"{s.detected_class.title()} upgraded to level {s.level}."


def apply_support_auras(structures: List[Structure], now: float) -> None:
    supports = [s for s in structures if s.behavior == "support" and s.operational(now)]
    for s in structures:
        s.buffed = False
        s.buff_damage = 1.0
        s.buff_range = 1.0
        if s.behavior != "attack":
            continue
        for sup in supports:
            if math.hypot(s.x - sup.x, s.y - sup.y) <= sup.buff_radius:
                s.buffed = True
                s.buff_damage = max(s.buff_damage, sup.buff_damage_multiplier)
                s.buff_range = max(s.buff_range, sup.buff_range_multiplier)
