"""Real-time tower defense simulation.

Runs on its own thread with a fixed timestep (settings.game.tick_hz), fully
decoupled from camera inference and from rendering. All timers use the game
clock, which only advances while the game is RUNNING, so pausing freezes
cooldowns, sabotage timers and spawns.

Physical objects reach the simulation as tracker snapshots. Structures are
persistent per tracked object: moving an object moves its structure (keeping
level, health and kills) and triggers a navigation rebuild + reroute only when
the obstacle layout actually changed.
"""

import json
import logging
import math
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Tuple

from backend.config import HIGHSCORES_FILE, settings
from backend.game.enemy_ai import DifficultyDirector, TacticalAI, build_wave_report, difficulty_label
from backend.game.models import (ACTIVE_STATUSES, BaseCore, Enemy, GameStatus, Projectile, Structure,
                                 WaveStats)
from backend.game.pathfinding import AStarRouter, NavigationGrid
from backend.game.structures import (apply_support_auras, change_role, create_structure, custom_key,
                                     upgrade_cost, upgrade_structure)

logger = logging.getLogger("desk_defender.simulation")


class GameSimulation:
    def __init__(self, object_source: Optional[Callable[[], List[Dict]]] = None,
                 highscores_file=HIGHSCORES_FILE):
        g = settings.game
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._object_source = object_source
        self._highscores_file = highscores_file

        self.grid = NavigationGrid(g.battlefield_width, g.battlefield_height, g.grid_cell_size, g.obstacle_margin)
        self.router = AStarRouter(self.grid)
        self.ai = TacticalAI(self.grid, self.router)
        self.director = DifficultyDirector()

        self.status = GameStatus.IDLE
        self.base = BaseCore(g.base_x, g.base_y, g.base_radius, g.base_max_health, g.base_max_health)
        self.structures: Dict[str, Structure] = {}
        self.enemies: List[Enemy] = []
        self.projectiles: List[Projectile] = []
        self.events: Deque[Dict] = deque(maxlen=400)
        self.time = 0.0
        self.tick = 0
        self.wave = 0
        self.total_waves = len(g.waves)
        self.score = 0
        self.credits = g.starting_currency
        self.kills = 0
        self.player_name = "Player"
        self.wave_stats = WaveStats(wave=0)
        self.history: List[Dict] = []
        self.last_summary: Optional[Dict] = None
        self.final_result: Optional[Dict] = None
        self.ability_ready_at: Dict[str, float] = {k: 0.0 for k in g.abilities}
        self._ghosts: List[Tuple[float, Structure]] = []
        self._roster: List[str] = []
        self._spawn_interval = 1.2
        self._spawn_timer = 0.0
        self._ids = 0
        self._nav_signature = None
        self._nav_dirty = True
        self.no_path = False
        self.tick_ms = 0.0
        self.actual_hz = 0.0
        self._recorded = False

    # ------------------------------------------------------------------ thread
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="game-simulation", daemon=True)
        self._thread.start()
        logger.info("Simulation running at %d Hz", settings.game.tick_hz)

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        dt = 1.0 / settings.game.tick_hz
        next_t = time.perf_counter()
        hz_t0, hz_n = time.perf_counter(), 0
        while not self._stop.is_set():
            t0 = time.perf_counter()
            with self._lock:
                try:
                    self.step(dt)
                except Exception:
                    logger.exception("Simulation tick failed")
            self.tick_ms = (time.perf_counter() - t0) * 1000.0
            hz_n += 1
            if t0 - hz_t0 >= 1.0:
                self.actual_hz = hz_n / (t0 - hz_t0)
                hz_t0, hz_n = t0, 0
            next_t += dt
            delay = next_t - time.perf_counter()
            if delay < -0.25:  # fell far behind (e.g. machine asleep) - do not spiral
                next_t = time.perf_counter()
                delay = 0
            self._stop.wait(max(0.0, delay))

    # ------------------------------------------------------------------ helpers
    def _id(self, prefix: str) -> str:
        self._ids += 1
        return f"{prefix}_{self._ids}"

    def _emit(self, event_type: str, **data) -> None:
        data["type"] = event_type
        data["t"] = round(self.time, 2)
        self.events.append(data)

    def drain_events(self) -> List[Dict]:
        with self._lock:
            out = list(self.events)
            self.events.clear()
            return out

    def _breach_costs(self) -> Dict[str, float]:
        return {s.id: 40.0 + s.health / 12.0 for s in self.structures.values() if s.blocks_path}

    # ------------------------------------------------------------------ controls
    def start_game(self, player_name: Optional[str] = None) -> None:
        with self._lock:
            g = settings.game
            if player_name:
                self.player_name = player_name.strip()[:24] or "Player"
            self.status = GameStatus.RUNNING
            self.time = 0.0
            self.wave = 0
            self.score = 0
            self.kills = 0
            self.credits = g.starting_currency
            self.base = BaseCore(g.base_x, g.base_y, g.base_radius, g.base_max_health, g.base_max_health)
            self.enemies.clear()
            self.projectiles.clear()
            self.history.clear()
            self.last_summary = None
            self.final_result = None
            self._recorded = False
            self.ability_ready_at = {k: 0.0 for k in g.abilities}
            self.director.reset()
            # Everything already on the desk at game start is deployed for free.
            for s in self.structures.values():
                s.level = 1
                s.health = s.max_health
                s.destroyed = False
                s.active = True
                s.paid = True
                s.kills = 0
                s.damage_dealt = 0.0
                s.disabled_until = 0.0
                change_role(s, s.role, None if s.role != "custom" else _custom_from_key(s.custom_key))
                s.health = s.max_health
            self._nav_dirty = True
            self._emit("game_started", structures=len(self.structures))
            self._begin_wave(1)

    def pause(self) -> bool:
        with self._lock:
            if self.status == GameStatus.RUNNING:
                self.status = GameStatus.PAUSED
                self._emit("paused")
                return True
            return False

    def resume(self) -> bool:
        with self._lock:
            if self.status == GameStatus.PAUSED:
                self.status = GameStatus.RUNNING
                self._emit("resumed")
                return True
            return False

    def restart(self, player_name: Optional[str] = None) -> None:
        self.start_game(player_name)

    def exit_game(self) -> None:
        with self._lock:
            if self.status in ACTIVE_STATUSES:
                self._finish(GameStatus.GAME_OVER, reason="abandoned")
            self.status = GameStatus.IDLE
            self.enemies.clear()
            self.projectiles.clear()

    def next_wave(self) -> bool:
        with self._lock:
            if self.status != GameStatus.WAVE_ENDED:
                return False
            self.status = GameStatus.RUNNING
            self._begin_wave(self.wave + 1)
            return True

    def upgrade(self, structure_id: str) -> Tuple[bool, str]:
        with self._lock:
            s = self.structures.get(structure_id) or next(
                (x for x in self.structures.values() if x.object_id == structure_id), None)
            if not s:
                return False, f"Structure '{structure_id}' not found."
            ok, self.credits, msg = upgrade_structure(s, self.credits)
            if ok:
                self._nav_dirty = True
                self._emit("upgraded", id=s.id, level=s.level, x=s.x, y=s.y)
            return ok, msg

    def use_ability(self, name: str, x: Optional[float] = None, y: Optional[float] = None) -> Tuple[bool, str]:
        with self._lock:
            abilities = settings.game.abilities
            if name not in abilities:
                return False, f"Unknown ability '{name}'."
            if self.status != GameStatus.RUNNING:
                return False, "Abilities can only be used while a wave is running."
            ab = abilities[name]
            wait = self.ability_ready_at.get(name, 0.0) - self.time
            if wait > 0:
                return False, f"{ab.label} is recharging ({wait:.1f}s)."
            if self.credits < ab.cost:
                return False, f"{ab.label} costs {ab.cost} credits; you have {self.credits}."
            if name == "strike":
                if x is None or y is None:
                    return False, "Orbital Strike needs a target position."
                hits = 0
                for e in self.enemies:
                    if math.hypot(e.x - x, e.y - y) <= ab.radius + e.radius:
                        self._damage_enemy(e, ab.damage, None)
                        hits += 1
                self._emit("strike", x=x, y=y, radius=ab.radius, hits=hits)
            elif name == "emp":
                for e in self.enemies:
                    e.stunned_until = self.time + ab.duration * (0.5 if e.type == "boss" else 1.0)
                self._emit("emp", x=self.base.x, y=self.base.y, count=len(self.enemies))
            elif name == "repair":
                self.base.health = min(self.base.max_health, self.base.health + ab.heal * 40)
                for s in self.structures.values():
                    s.health = min(s.max_health, s.health + ab.heal * s.max_health)
                    if s.destroyed and s.health > 0:
                        s.destroyed = False
                        self._nav_dirty = True
                self._emit("repair", x=self.base.x, y=self.base.y)
            self.credits -= ab.cost
            self.ability_ready_at[name] = self.time + ab.cooldown
            self.wave_stats.abilities_used += 1
            self._cleanup_dead()
            return True, f"{ab.label} activated."

    def set_player_name(self, name: str) -> None:
        with self._lock:
            self.player_name = name.strip()[:24] or "Player"

    # ------------------------------------------------------------------ waves
    def _begin_wave(self, number: int) -> None:
        self.wave = number
        roster, interval = self.director.roster(number - 1)
        self._roster = roster
        self._spawn_interval = interval
        self._spawn_timer = interval * 0.5
        self.wave_stats = WaveStats(wave=number, started_at=self.time, total=len(roster))
        self._emit("wave_started", wave=number, enemies=len(roster), difficulty=self.director.label)
        logger.info("Wave %d: %d enemies, interval %.2fs, difficulty %.2f", number, len(roster), interval,
                    self.director.value)

    def _end_wave(self) -> None:
        g = settings.game
        stats = self.wave_stats
        hp_frac = self.base.health / self.base.max_health
        bonus_score = int(150 * self.wave * hp_frac)
        bonus_credits = g.wave_clear_bonus_credits + 10 * self.wave
        self.score += bonus_score
        self.credits += bonus_credits
        stats.score_earned += bonus_score
        stats.credits_earned += bonus_credits
        change = self.director.adapt(stats, self.base.max_health)
        report = build_wave_report(stats, list(self.structures.values()), self.base.health, self.base.max_health,
                                   self.credits, self.director.value, change, stats.total)
        report["wave_clear_bonus"] = bonus_score
        self.last_summary = report
        self.history.append(report)
        # Field repairs between waves.
        for s in self.structures.values():
            s.health = min(s.max_health, s.health + g.between_wave_repair * s.max_health)
            if s.destroyed:
                s.destroyed = False
                self._nav_dirty = True
        if self.wave >= self.total_waves:
            self._finish(GameStatus.VICTORY)
        else:
            self.status = GameStatus.WAVE_ENDED
            self._emit("wave_ended", wave=self.wave, summary=report)

    def _finish(self, status: GameStatus, reason: str = "") -> None:
        self.status = status
        self.final_result = {
            "outcome": "victory" if status == GameStatus.VICTORY else "defeat",
            "reason": reason or ("all waves cleared" if status == GameStatus.VICTORY else "core destroyed"),
            "score": self.score, "wave_reached": self.wave, "total_waves": self.total_waves,
            "kills": self.kills, "base_health": round(self.base.health, 1),
            "waves": list(self.history), "player": self.player_name,
            "difficulty": round(self.director.value, 2),
        }
        self._emit("game_over", outcome=self.final_result["outcome"], score=self.score)
        if not self._recorded and reason != "abandoned":
            self._recorded = True
            self._record_highscore(self.final_result)

    # ------------------------------------------------------------------ main step
    def step(self, dt: float) -> None:
        self.tick += 1
        self._sync_structures()
        apply_support_auras(list(self.structures.values()), self.time)
        if self._nav_dirty:
            self._rebuild_nav()
        if self.status != GameStatus.RUNNING:
            return
        self.time += dt
        self._spawn(dt)
        self._update_enemies(dt)
        self._update_towers(dt)
        self._update_projectiles(dt)
        self._cleanup_dead()
        self._check_end()

    # ------------------------------------------------------------------ structures
    def _sync_structures(self) -> None:
        if self._object_source is None:
            return
        objs = self._object_source()
        in_game = self.status in ACTIVE_STATUSES
        seen = set()
        for o in objs:
            sid = f"struct_{o['id']}"
            seen.add(sid)
            s = self.structures.get(sid)
            if s is None:
                reclaimed = self._reclaim_ghost(o)
                s = reclaimed or create_structure(o)
                s.id, s.object_id = sid, o["id"]
                if in_game and reclaimed is None:
                    s.paid = False  # placed mid-game: activates once its cost is paid
                if not s.paid:
                    s.active = False
                self.structures[sid] = s
                self._nav_dirty = True
                self._emit("structure_added", id=sid, cls=s.detected_class, role=s.role, x=s.x, y=s.y)
                continue
            new_key = custom_key(o["role"], o.get("custom"))
            if o["role"] != s.role or new_key != s.custom_key:
                old = s.role
                change_role(s, o["role"], o.get("custom"))
                if in_game:
                    s.paid = False
                    s.active = False
                self._nav_dirty = True
                self._emit("role_changed", id=sid, old=old, role=s.role, x=s.x, y=s.y)
            mult = settings.game.roles.get(s.role, settings.game.roles["custom"]).footprint_multiplier
            s.x, s.y = o["center"]
            s.w, s.h = o["footprint"][0] * mult, o["footprint"][1] * mult
            s.detected_class = o["detected_class"]
            s.confidence = o.get("confidence", s.confidence)
            s.source = o.get("source", s.source)
            was_stale, s.stale = s.stale, bool(o.get("is_stale"))
            if s.stale and not was_stale:
                self._emit("structure_lost", id=sid, cls=s.detected_class, x=s.x, y=s.y,
                           grace=o.get("removal_in"))
        for sid in [k for k in self.structures if k not in seen]:
            s = self.structures.pop(sid)
            self._ghosts.append((time.time(), s))
            self._nav_dirty = True
            self._emit("structure_removed", id=sid, cls=s.detected_class, x=s.x, y=s.y)
        # Power up structures placed mid-game once they can be paid for.
        if in_game:
            for s in self.structures.values():
                if not s.paid and self.credits >= s.cost:
                    self.credits -= s.cost
                    s.paid = s.active = True
                    self._nav_dirty = True
                    self._emit("structure_activated", id=s.id, cost=s.cost, x=s.x, y=s.y)
        else:
            for s in self.structures.values():
                s.paid = s.active = True
        now = time.time()
        self._ghosts = [(t, s) for t, s in self._ghosts if now - t < settings.game.ghost_memory_seconds]
        sig = tuple(sorted(
            (s.id, round(s.x / 20), round(s.y / 20), round(s.w / 20), round(s.h / 20), s.blocks_path,
             s.active, s.destroyed, round(s.range * s.buff_range / 20))
            for s in self.structures.values()))
        if sig != self._nav_signature:
            self._nav_signature = sig
            self._nav_dirty = True

    def _reclaim_ghost(self, o: Dict) -> Optional[Structure]:
        """An object that briefly vanished and re-appeared nearby keeps its state (no double charge)."""
        g = settings.game
        best, best_d = None, g.ghost_match_distance
        for i, (_, s) in enumerate(self._ghosts):
            d = math.hypot(s.x - o["center"][0], s.y - o["center"][1])
            if d < best_d and s.role == o["role"]:
                best, best_d = i, d
        if best is None:
            return None
        _, s = self._ghosts.pop(best)
        s.x, s.y = o["center"]
        s.stale = False
        return s

    def place_test_structure(self, obj: Dict) -> Structure:
        """Adds a structure directly (used by tests and the simulation without a tracker)."""
        with self._lock:
            s = create_structure(obj)
            self.structures[s.id] = s
            self._nav_dirty = True
            return s

    def _rebuild_nav(self) -> None:
        g = settings.game
        self.grid.rasterize(list(self.structures.values()), (self.base.x, self.base.y), self.base.radius,
                            keep_free=g.spawn_points)
        self._nav_dirty = False
        for e in self.enemies:
            e.needs_reroute = True
        probe = self.router.find_path(tuple(g.spawn_points[1]), (self.base.x, self.base.y), allow_breach=False)
        was = self.no_path
        self.no_path = not probe.reachable
        if self.no_path and not was:
            self.wave_stats.no_path_events += 1
            self._emit("no_path", message="The core is completely walled off - enemies will breach the weakest barrier.")
        self._emit("nav_rebuilt", version=self.grid.version)

    # ------------------------------------------------------------------ enemies
    def _spawn(self, dt: float) -> None:
        if not self._roster:
            return
        self._spawn_timer += dt
        if self._spawn_timer < self._spawn_interval:
            return
        self._spawn_timer = 0.0
        etype = self._roster.pop(0)
        prof = settings.game.enemies[etype]
        hp = prof.health * self.director.health_multiplier()
        base = (self.base.x, self.base.y)
        lane = self.ai.choose_spawn(etype, prof, settings.game.spawn_points, base, list(self.structures.values()),
                                    self._breach_costs(), hp, self.wave_stats.spawned)
        sx, sy = settings.game.spawn_points[lane]
        e = Enemy(id=self._id("enemy"), type=etype, x=sx, y=sy, radius=prof.radius, health=hp, max_health=hp,
                  speed=prof.speed, reward=prof.reward, base_damage=prof.base_damage,
                  structure_dps=prof.structure_dps, lane=lane, progress_x=sx, progress_y=sy, progress_t=self.time,
                  straight_length=math.hypot(base[0] - sx, base[1] - sy))
        self._plan(e)
        e.planned_length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(e.path, e.path[1:]))
        self.enemies.append(e)
        self.wave_stats.spawned += 1
        self._emit("enemy_spawned", id=e.id, etype=etype, x=sx, y=sy, lane=lane)

    def _plan(self, e: Enemy) -> None:
        if self._nav_dirty:
            self._rebuild_nav()
        prof = settings.game.enemies[e.type]
        goal = (self.base.x, self.base.y)
        e.goal = "base"
        e.target_structure = None
        if e.type == "saboteur" and self.time >= e.sabotage_ready_at:
            target = self.ai.choose_sabotage_target(e, prof, list(self.structures.values()), self.time)
            if target:
                goal = (target.x, target.y)
                e.goal = "sabotage"
                e.target_structure = target.id
        res, intent = self.ai.plan_route((e.x, e.y), goal, prof, e.health, e.speed, self._breach_costs())
        e.path = res.waypoints
        e.path_index = 1
        e.breach_target = res.breach_structure
        e.intent = "sabotaging" if e.goal == "sabotage" else intent
        e.needs_reroute = False
        e.next_decision = self.time + 2.0 + (int(e.id.rsplit("_", 1)[1]) % 10) * 0.1

    def _update_enemies(self, dt: float) -> None:
        now = self.time
        reroutes = 0
        slowers = [s for s in self.structures.values() if s.slow_radius > 0 and s.operational(now)]
        for e in self.enemies:
            if e.health <= 0:
                continue
            prof = settings.game.enemies[e.type]
            if (e.needs_reroute or now >= e.next_decision) and reroutes < settings.game.max_reroutes_per_tick:
                self._plan(e)
                reroutes += 1
            if e.stunned_until > now:
                e.attacking = None
                continue
            # Slow fields: barriers slow enemies hugging them, support towers slow an area.
            mult = 1.0
            for s in slowers:
                if s.behavior == "block":
                    near = abs(e.x - s.x) <= s.w / 2 + s.slow_radius and abs(e.y - s.y) <= s.h / 2 + s.slow_radius
                else:
                    near = math.hypot(e.x - s.x, e.y - s.y) <= s.slow_radius
                if near:
                    mult = min(mult, s.slow_factor)
            e.slow_mult = mult
            # Boss stomp damages nearby structures.
            if prof.stomp_radius > 0:
                for s in self.structures.values():
                    if not s.destroyed and s.active and math.hypot(e.x - s.x, e.y - s.y) <= prof.stomp_radius + s.radius:
                        self._damage_structure(s, prof.stomp_dps * dt)
            # Sabotage when in range of the chosen target.
            if e.goal == "sabotage" and e.target_structure:
                t = self.structures.get(e.target_structure)
                if t is None or not t.operational(now):
                    e.needs_reroute = True
                elif math.hypot(e.x - t.x, e.y - t.y) <= prof.sabotage_range + t.radius:
                    t.disabled_until = now + prof.sabotage_duration
                    e.sabotage_ready_at = now + prof.sabotage_cooldown
                    self.wave_stats.sabotages += 1
                    self._emit("sabotage", enemy=e.id, id=t.id, x=t.x, y=t.y, duration=prof.sabotage_duration)
                    e.needs_reroute = True
                    continue
            self._move(e, dt, mult)
            # Stuck detection: replan if barely moved for 2 s while not attacking.
            if now - e.progress_t >= 2.0:
                if math.hypot(e.x - e.progress_x, e.y - e.progress_y) < 8 and not e.attacking:
                    # Snap to the centre of a free cell; corridors from cell centres are always clear.
                    cx, cy = self.grid.center_of(self.grid.cell_of(e.x, e.y))
                    e.x, e.y = self.grid.nearest_free(cx, cy)
                    e.needs_reroute = True
                e.progress_x, e.progress_y, e.progress_t = e.x, e.y, now
            # Reached the core?
            if math.hypot(e.x - self.base.x, e.y - self.base.y) <= e.radius + self.base.radius:
                self.base.health = max(0.0, self.base.health - e.base_damage)
                self.wave_stats.damage_received += e.base_damage
                self.wave_stats.leaked += 1
                self.wave_stats.leaks_by_lane[e.lane] = self.wave_stats.leaks_by_lane.get(e.lane, 0) + 1
                self._record_path_ratio(e)
                e.health = 0
                e.reward = 0
                self._emit("base_hit", enemy=e.id, etype=e.type, damage=e.base_damage, x=e.x, y=e.y,
                           health=round(self.base.health, 1))

    def _move(self, e: Enemy, dt: float, mult: float) -> None:
        e.attacking = None
        step = e.speed * mult * dt
        while step > 0 and e.path_index < len(e.path):
            tx, ty = e.path[e.path_index]
            dx, dy = tx - e.x, ty - e.y
            dist = math.hypot(dx, dy)
            if dist < 1e-6:
                e.path_index += 1
                continue
            mv = min(step, dist)
            nx, ny = e.x + dx / dist * mv, e.y + dy / dist * mv
            cell = self.grid.cell_of(nx, ny)
            if self.grid.blocked[cell] and not self.grid.blocked[self.grid.cell_of(e.x, e.y)]:
                owner = self.grid.owner[cell]
                s = self.structures.get(owner) if owner else None
                if s and owner == e.breach_target:
                    e.attacking = s.id
                    self._damage_structure(s, e.structure_dps * dt)
                else:
                    e.needs_reroute = True
                return
            e.heading = math.atan2(dy, dx)
            e.distance_travelled += mv
            e.x, e.y = nx, ny
            step -= mv
            if mv >= dist - 1e-6:
                e.path_index += 1
        if e.path_index >= len(e.path):
            if e.goal == "base":
                dx, dy = self.base.x - e.x, self.base.y - e.y
                d = math.hypot(dx, dy)
                if d > 1e-6:
                    e.x += dx / d * min(d, e.speed * mult * dt)
                    e.y += dy / d * min(d, e.speed * mult * dt)
            else:
                e.needs_reroute = True

    def _damage_structure(self, s: Structure, amount: float) -> None:
        if s.destroyed:
            return
        s.health -= amount
        s.damage_taken += amount
        if s.health <= 0:
            s.health = 0.0
            s.destroyed = True
            self.wave_stats.structures_destroyed += 1
            self._nav_dirty = True
            self._emit("structure_destroyed", id=s.id, cls=s.detected_class, x=s.x, y=s.y)

    def _record_path_ratio(self, e: Enemy) -> None:
        if e.straight_length > 50:
            self.wave_stats.path_ratio_samples.append(max(1.0, e.planned_length / e.straight_length))

    # ------------------------------------------------------------------ towers & projectiles
    def _update_towers(self, dt: float) -> None:
        now = self.time
        for s in self.structures.values():
            if s.behavior != "attack" or not s.operational(now) or s.fire_rate <= 0:
                continue
            s.cooldown -= dt
            rng = s.range * s.buff_range
            target, best = None, None
            for e in self.enemies:
                if e.health <= 0:
                    continue
                d = math.hypot(e.x - s.x, e.y - s.y)
                if d > rng + e.radius:
                    continue
                # Target the enemy closest to the core (most dangerous), tie-break by distance.
                key = math.hypot(e.x - self.base.x, e.y - self.base.y) + d * 0.1
                if best is None or key < best:
                    target, best = e, key
            if target is None:
                continue
            s.aim = math.atan2(target.y - s.y, target.x - s.x)
            if s.cooldown > 0:
                continue
            s.cooldown = 1.0 / s.fire_rate
            dmg = s.damage * s.buff_damage
            self.projectiles.append(Projectile(id=self._id("p"), source_id=s.id, target_id=target.id, x=s.x, y=s.y,
                                               tx=target.x, ty=target.y, speed=s.projectile_speed, damage=dmg,
                                               kind="heavy" if s.buffed or s.level > 1 else "bolt"))

    def _update_projectiles(self, dt: float) -> None:
        lookup = {e.id: e for e in self.enemies if e.health > 0}
        alive = []
        for p in self.projectiles:
            t = lookup.get(p.target_id)
            if t:
                p.tx, p.ty = t.x, t.y
            dx, dy = p.tx - p.x, p.ty - p.y
            dist = math.hypot(dx, dy)
            step = p.speed * dt
            if dist <= step + (t.radius if t else 4):
                if t:
                    self._damage_enemy(t, p.damage, p.source_id)
                    self._emit("hit", x=round(p.tx), y=round(p.ty), k=p.kind)
                continue
            p.x += dx / dist * step
            p.y += dy / dist * step
            alive.append(p)
        self.projectiles = alive

    def _damage_enemy(self, e: Enemy, amount: float, source_id: Optional[str]) -> None:
        if e.health <= 0:
            return
        e.health -= amount
        src = self.structures.get(source_id) if source_id else None
        if src:
            src.damage_dealt += amount
        if e.health <= 0:
            self.kills += 1
            self.credits += e.reward
            self.score += e.reward * 10
            self.wave_stats.killed += 1
            self.wave_stats.score_earned += e.reward * 10
            self.wave_stats.credits_earned += e.reward
            self._record_path_ratio(e)
            if src:
                src.kills += 1
                self.wave_stats.kills_by_structure[src.id] = self.wave_stats.kills_by_structure.get(src.id, 0) + 1
                self.wave_stats.structure_names[src.id] = f"{src.detected_class} ({src.object_id})"
            self._emit("enemy_killed", id=e.id, etype=e.type, x=round(e.x), y=round(e.y), reward=e.reward,
                       by=source_id)

    def _cleanup_dead(self) -> None:
        self.enemies = [e for e in self.enemies if e.health > 0]

    def _check_end(self) -> None:
        if self.base.health <= 0:
            self._finish(GameStatus.GAME_OVER)
            return
        if not self._roster and not self.enemies:
            self._end_wave()

    # ------------------------------------------------------------------ high scores
    def _record_highscore(self, result: Dict) -> None:
        entry = {"name": result["player"], "score": result["score"], "wave": result["wave_reached"],
                 "outcome": result["outcome"], "kills": result["kills"], "difficulty": result["difficulty"],
                 "date": time.strftime("%Y-%m-%d %H:%M")}
        scores = load_highscores(self._highscores_file)
        scores.append(entry)
        scores.sort(key=lambda s: -s["score"])
        try:
            self._highscores_file.write_text(json.dumps(scores[:25], indent=2))
        except OSError as exc:
            logger.error("Could not save high score: %s", exc)

    # ------------------------------------------------------------------ snapshot
    def snapshot(self) -> Dict:
        with self._lock:
            now = self.time
            g = settings.game
            return {
                "status": self.status.value,
                "wave": self.wave,
                "total_waves": self.total_waves,
                "time": round(self.time, 2),
                "tick": self.tick,
                "base": self.base.to_dict(),
                "score": self.score,
                "credits": self.credits,
                "kills": self.kills,
                "player_name": self.player_name,
                "difficulty": {"value": round(self.director.value, 2), "label": self.director.label,
                               "min": g.difficulty.minimum, "max": g.difficulty.maximum},
                "spawn_points": g.spawn_points,
                "battlefield": {"width": g.battlefield_width, "height": g.battlefield_height},
                "structures": [s.to_dict(now, upgrade_cost(s)) for s in self.structures.values()],
                "enemies": [e.to_dict(now) for e in self.enemies],
                "projectiles": [p.to_dict() for p in self.projectiles],
                "abilities": {k: {"label": a.label, "cost": a.cost, "cooldown": a.cooldown, "radius": a.radius,
                                  "ready_in": round(max(0.0, self.ability_ready_at.get(k, 0.0) - now), 1)}
                              for k, a in g.abilities.items()},
                "wave_progress": {"spawned": self.wave_stats.spawned, "total": self.wave_stats.total,
                                  "alive": len(self.enemies), "killed": self.wave_stats.killed,
                                  "leaked": self.wave_stats.leaked},
                "nav": {"version": self.grid.version, "no_path": self.no_path, "cell": self.grid.cell},
                "last_summary": self.last_summary,
                "final_result": self.final_result,
                "perf": {"tick_ms": round(self.tick_ms, 2), "hz": round(self.actual_hz, 1)},
            }

    def nav_debug(self) -> Dict:
        with self._lock:
            return {"cols": self.grid.cols, "rows": self.grid.rows, "cell": self.grid.cell,
                    "blocked": [i for i, b in enumerate(self.grid.blocked) if b],
                    "threat": [round(t, 1) for t in self.grid.threat]}


def _custom_from_key(key: Optional[str]) -> Optional[Dict]:
    if not key:
        return None
    try:
        import ast
        return dict(ast.literal_eval(key))
    except (ValueError, SyntaxError):
        return None


def load_highscores(path=HIGHSCORES_FILE) -> List[Dict]:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _tracker_source() -> List[Dict]:
    from backend.vision.tracker import tracker
    return tracker.snapshot(confirmed_only=True)


simulation = GameSimulation(object_source=_tracker_source)
