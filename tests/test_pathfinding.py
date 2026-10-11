"""Structures and A* navigation."""

import numpy as np

from backend.config import settings
from backend.game.pathfinding import AStarRouter, NavigationGrid
from backend.game.structures import apply_support_auras, create_structure, upgrade_structure


def obj(oid, cls, role, x, y, w=50, h=50):
    return {"id": oid, "detected_class": cls, "role": role, "center": (x, y), "footprint": (w, h), "confidence": 0.9}


def test_custom_role_overrides():
    s = create_structure({**obj("c", "unknown object", "custom", 100, 100),
                          "custom": {"behavior": "block", "durability": 777}})
    assert s.behavior == "block" and s.blocks_path and s.max_health == 777


# ---------------------------------------------------------------- tracking


def test_pathfinding_routes_around_barrier():
    grid = NavigationGrid(1000, 700, 25)
    router = AStarRouter(grid)
    wall = create_structure(obj("b", "book", "barrier", 500, 350, 80, 400))
    grid.rasterize([wall], (935, 350), 38)
    res = router.find_path((50, 350), (935, 350))
    assert res.reachable and res.breach_structure is None
    assert res.length > 885 + 20  # longer than the straight line
    for a, b in zip(res.waypoints, res.waypoints[1:]):
        for t in np.linspace(0, 1, 40):  # no segment enters the barrier
            x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            assert not (abs(x - 500) < 40 and abs(y - 350) < 200)


def test_towers_do_not_block_movement():
    grid = NavigationGrid(1000, 700, 25)
    tower = create_structure(obj("t", "bottle", "defense_tower", 500, 350, 60, 60))
    grid.rasterize([tower], (935, 350), 38)
    assert not grid.is_blocked_at(500, 350)
    assert grid.threat_at(500, 350) > 0


def test_no_path_triggers_breach_plan():
    grid = NavigationGrid(1000, 700, 25)
    router = AStarRouter(grid)
    wall = create_structure(obj("w", "box", "heavy_fortification", 600, 350, 60, 700))
    grid.rasterize([wall], (935, 350), 38)
    assert router.find_path((50, 350), (935, 350), allow_breach=False).reachable is False
    res = router.find_path((50, 350), (935, 350), allow_breach=True)
    assert res.reachable and res.breach_structure == wall.id


def test_threat_aware_route_avoids_towers():
    grid = NavigationGrid(1000, 700, 25)
    router = AStarRouter(grid)
    towers = [create_structure(obj(f"t{i}", "cup", "defense_tower", 500, y)) for i, y in enumerate((250, 350, 450))]
    grid.rasterize(towers, (935, 350), 38)
    direct = router.find_path((50, 350), (935, 350), threat_weight=0)
    cautious = router.find_path((50, 350), (935, 350), threat_weight=15)
    assert cautious.expected_dps_time < direct.expected_dps_time


# ---------------------------------------------------------------- combat


def test_support_aura_buffs_nearby_tower_only():
    near = create_structure(obj("a", "bottle", "defense_tower", 400, 300))
    sup = create_structure(obj("b", "pencil holder", "support_tower", 450, 300))
    far = create_structure(obj("c", "cup", "defense_tower", 900, 100))
    apply_support_auras([near, sup, far], 0.0)
    assert near.buffed and near.buff_damage > 1 and not far.buffed


def test_upgrade_costs_credits_and_scales():
    s = create_structure(obj("a", "bottle", "defense_tower", 400, 300))
    dmg = s.damage
    ok, credits, _ = upgrade_structure(s, 50)
    assert not ok and credits == 50
    ok, credits, _ = upgrade_structure(s, 500)
    assert ok and credits == 500 - settings.game.upgrade_costs[0] and s.level == 2 and s.damage > dmg
