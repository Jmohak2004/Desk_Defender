"""Deterministic, utility-based tactical AI and adaptive difficulty director.

Each decision scores candidate actions with explicit formulas over measurable
quantities (route length, tower exposure, enemy health, tower value) and picks
the best. No randomness and no LLM in the loop, so behaviour is reproducible.

  route utility  = reach_value * survival - time_weight * travel_time
  survival       = max(0, 1 - expected_damage / current_health)
  expected_damage= sum over route cells of tower DPS * time spent in the cell

Profiles differ in how much they fear damage (threat_aversion): scouts take
the least-defended open lane, tanks bulldoze the shortest route, saboteurs
hunt the most valuable tower they can reach, the boss walks straight in.
"""

import math
from typing import Dict, List, Optional, Sequence, Tuple

from backend.config import EnemyProfile, settings
from backend.game.models import Enemy, Structure, WaveStats
from backend.game.pathfinding import AStarRouter, NavigationGrid, PathResult

REACH_VALUE = 100.0
TIME_WEIGHT = 1.2


def difficulty_label(d: float) -> str:
    if d < 0.9:
        return "Relaxed"
    if d < 1.1:
        return "Balanced"
    if d < 1.35:
        return "Aggressive"
    return "Relentless"


class TacticalAI:
    def __init__(self, grid: NavigationGrid, router: AStarRouter):
        self.grid = grid
        self.router = router
        self._lane_cache: Dict[Tuple[int, str, int], Tuple[float, PathResult]] = {}

    # ------------------------------------------------------------------ routes
    def _expected_damage(self, result: PathResult, speed: float) -> float:
        # exposure = sum(threat * cell_len); time in cell = cell_len / speed
        return result.expected_dps_time / max(1.0, speed)

    def route_utility(self, result: PathResult, profile: EnemyProfile, health: float, speed: float) -> float:
        if not result.reachable:
            return -1e9
        exp_dmg = self._expected_damage(result, speed)
        aversion = max(0.0, profile.threat_aversion)
        survival = max(0.0, 1.0 - exp_dmg * (0.25 + 0.25 * aversion) / max(1.0, health))
        travel_time = result.length / max(1.0, speed)
        breach_penalty = 40.0 if result.breach_structure else 0.0
        return REACH_VALUE * survival - TIME_WEIGHT * travel_time - breach_penalty

    def plan_route(self, start: Tuple[float, float], goal: Tuple[float, float], profile: EnemyProfile,
                   health: float, speed: float, breach_costs: Dict[str, float]) -> Tuple[PathResult, str]:
        """Evaluates a direct and a threat-avoiding route and returns the higher-utility one."""
        weights = [0.0]
        if profile.threat_aversion > 0.5:
            weights.append(profile.threat_aversion * 2.5)
        best: Optional[Tuple[float, PathResult, float]] = None
        for w in weights:
            res = self.router.find_path(start, goal, threat_weight=w, breach_costs=breach_costs)
            u = self.route_utility(res, profile, health, speed)
            if best is None or u > best[0] + 1e-6:
                best = (u, res, w)
        _, res, w = best
        if res.breach_structure:
            intent = "breaching"
        elif w > 0 and len(weights) > 1:
            intent = "flanking"
        else:
            intent = "advancing"
        return res, intent

    def choose_spawn(self, enemy_type: str, profile: EnemyProfile, spawn_points: Sequence[Sequence[float]],
                     base: Tuple[float, float], structures: Sequence[Structure], breach_costs: Dict[str, float],
                     health: float, ordinal: int) -> int:
        """Picks the spawn lane with the best utility for this enemy type (cached per nav version)."""
        scores = []
        for lane, sp in enumerate(spawn_points):
            key = (lane, enemy_type, self.grid.version)
            cached = self._lane_cache.get(key)
            if cached is None:
                res, _ = self.plan_route((sp[0], sp[1]), base, profile, health, profile.speed, breach_costs)
                u = self.route_utility(res, profile, health, profile.speed)
                if enemy_type == "saboteur":
                    # Saboteurs favour lanes passing close to valuable towers.
                    u += 0.15 * sum(_tower_value(s) for s in structures if s.behavior == "attack"
                                    and _min_dist_to_path(s, res.waypoints) < profile.sabotage_range * 2)
                cached = (u, res)
                self._lane_cache[key] = cached
            scores.append(cached[0])
        if len(self._lane_cache) > 400:
            self._lane_cache.clear()
        ranked = sorted(range(len(scores)), key=lambda i: -scores[i])
        # Spread near-equal lanes deterministically so waves do not stack on one pixel.
        top = [i for i in ranked if scores[i] >= scores[ranked[0]] - 6.0]
        return top[ordinal % len(top)]

    # ------------------------------------------------------------------ sabotage
    def choose_sabotage_target(self, enemy: Enemy, profile: EnemyProfile, structures: Sequence[Structure],
                               now: float) -> Optional[Structure]:
        best, best_u = None, 8.0  # minimum utility worth diverting for
        for s in structures:
            if s.behavior not in ("attack", "support") or not s.operational(now):
                continue
            dist = math.hypot(s.x - enemy.x, s.y - enemy.y)
            exposure = self.grid.threat_at(s.x, s.y) * (dist / max(1.0, enemy.speed)) * 0.15
            u = _tower_value(s) / (1.0 + dist / 220.0) - exposure * 50.0 / max(1.0, enemy.health)
            if u > best_u:
                best, best_u = s, u
        return best


def _tower_value(s: Structure) -> float:
    if s.behavior == "support":
        return 30.0 + 10.0 * s.level
    return s.damage * s.buff_damage * s.fire_rate * (1.0 + 0.3 * (s.level - 1))


def _min_dist_to_path(s: Structure, pts: Sequence[Sequence[float]]) -> float:
    return min((math.hypot(p[0] - s.x, p[1] - s.y) for p in pts), default=1e9)


# ---------------------------------------------------------------------- director
class DifficultyDirector:
    """Adapts enemy count/health between waves, clamped to configured min/max."""

    def __init__(self):
        self.value = settings.game.difficulty.initial

    def reset(self) -> None:
        self.value = settings.game.difficulty.initial

    @property
    def label(self) -> str:
        return difficulty_label(self.value)

    def adapt(self, stats: WaveStats, base_max: float) -> str:
        cfg = settings.game.difficulty
        before = self.value
        dmg_frac = stats.damage_received / max(1.0, base_max)
        if stats.leaked == 0:
            self.value += cfg.step_up
        elif dmg_frac > 0.25:
            self.value -= cfg.step_down
        elif dmg_frac > 0.1:
            self.value -= cfg.step_down / 2
        self.value = round(min(cfg.maximum, max(cfg.minimum, self.value)), 3)
        if self.value > before:
            return "up"
        if self.value < before:
            return "down"
        return "same"

    def roster(self, wave_index: int) -> Tuple[List[str], float]:
        waves = settings.game.waves
        wave = waves[min(wave_index, len(waves) - 1)]
        scale = 1.0 + (self.value - 1.0) * 0.6
        roster: List[str] = []
        for etype, count in wave.enemies.items():
            n = count if etype == "boss" else max(1, round(count * scale))
            roster.extend([etype] * n)
        # Deterministic interleave: spread heavy units through the wave.
        order = {"scout": 0, "saboteur": 1, "tank": 2, "boss": 3}
        roster.sort(key=lambda t: order.get(t, 0))
        interleaved: List[str] = []
        buckets = {t: [x for x in roster if x == t] for t in order}
        while any(buckets.values()):
            for t in ("scout", "scout", "saboteur", "tank", "scout", "boss"):
                if buckets.get(t):
                    interleaved.append(buckets[t].pop())
        # Bosses arrive at the end of their wave.
        bosses = [t for t in interleaved if t == "boss"]
        interleaved = [t for t in interleaved if t != "boss"] + bosses
        return interleaved, wave.spawn_interval / math.sqrt(self.value)

    def health_multiplier(self) -> float:
        return self.value


# ---------------------------------------------------------------------- summary
def build_wave_report(stats: WaveStats, structures: Sequence[Structure], base_health: float, base_max: float,
                      credits: int, difficulty: float, change: str, spawn_count: int) -> Dict:
    """Wave summary computed only from recorded statistics."""
    towers = [s for s in structures if s.behavior == "attack" and s.active]
    blockers = [s for s in structures if s.behavior == "block" and s.active]
    supports = [s for s in structures if s.behavior == "support" and s.active]
    ratio = sum(stats.path_ratio_samples) / len(stats.path_ratio_samples) if stats.path_ratio_samples else 1.0

    impact: List[str] = []
    suggestions: List[str] = []
    if stats.path_ratio_samples:
        pct = (ratio - 1.0) * 100
        if blockers:
            impact.append(f"Your obstacles made enemy routes {pct:.0f}% longer than a straight line to the core.")
        else:
            impact.append(f"Enemy routes were only {pct:.0f}% longer than a straight line - nothing blocked them.")
    if stats.kills_by_structure:
        top_id, top_kills = max(stats.kills_by_structure.items(), key=lambda kv: kv[1])
        name = stats.structure_names.get(top_id, top_id)
        share = 100 * top_kills / max(1, sum(stats.kills_by_structure.values()))
        impact.append(f"Top defender: {name} with {top_kills} kills ({share:.0f}% of tower kills).")
    idle = [s for s in towers if stats.kills_by_structure.get(s.id, 0) == 0]
    if towers and idle:
        impact.append(f"{len(idle)} of {len(towers)} towers scored no kills this wave.")
    if stats.sabotages:
        impact.append(f"Saboteurs disabled your towers {stats.sabotages} time(s).")
    if stats.structures_destroyed:
        impact.append(f"{stats.structures_destroyed} structure(s) were destroyed by breaching enemies.")
    if stats.no_path_events:
        impact.append("You fully walled off the core at least once, so enemies had to breach a barrier.")

    if stats.leaked:
        lane_names = {0: "upper-left", 1: "middle-left", 2: "lower-left", 3: "top", 4: "bottom"}
        worst_lane = max(stats.leaks_by_lane.items(), key=lambda kv: kv[1])[0] if stats.leaks_by_lane else None
        where = f" Most leaks came from the {lane_names.get(worst_lane, 'side')} entrance." if worst_lane is not None else ""
        suggestions.append(f"{stats.leaked} enemies reached the core.{where} Put a tower (bottle or cup) covering that approach.")
    if len(towers) < 2:
        suggestions.append("You have fewer than two towers. Add bottles or cups - towers are your only steady damage.")
    if not blockers:
        suggestions.append("Add books or a box to form a maze: longer routes mean more time under tower fire.")
    elif ratio < 1.12:
        suggestions.append("Your barriers are not on the enemies' path. Slide them between the entrances and the core.")
    if idle and len(idle) >= max(1, len(towers) // 2):
        suggestions.append("Several towers had nothing in range. Move them next to the routes shown as dotted lines.")
    if towers and not supports and len(towers) >= 2:
        suggestions.append("Place a support object (pencil holder, vase or phone) near your tower cluster for a damage buff.")
    if stats.sabotages >= 2:
        suggestions.append("Saboteurs keep reaching your towers - spread towers out or shield them with a barrier.")
    up_cost = settings.game.upgrade_costs[0]
    if credits >= up_cost and towers:
        suggestions.append(f"You have {credits} credits banked. Upgrade your best tower ({up_cost} credits).")
    if not suggestions:
        suggestions.append("Flawless layout. Expect the director to send a tougher wave next.")

    return {
        "wave_number": stats.wave,
        "enemies_defeated": stats.killed,
        "enemies_total": spawn_count,
        "enemies_leaked": stats.leaked,
        "damage_received": round(stats.damage_received, 1),
        "base_health_remaining": round(base_health, 1),
        "base_health_max": base_max,
        "score_earned": stats.score_earned,
        "credits_earned": stats.credits_earned,
        "structures_used": len([s for s in structures if s.active]),
        "structures_destroyed": stats.structures_destroyed,
        "route_length_ratio": round(ratio, 2),
        "sabotages": stats.sabotages,
        "abilities_used": stats.abilities_used,
        "ai_difficulty": difficulty_label(difficulty),
        "ai_difficulty_value": round(difficulty, 2),
        "difficulty_change": change,
        "strategy_impact": impact,
        "suggestions": suggestions,
    }
