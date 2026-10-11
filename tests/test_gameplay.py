"""Simulation: combat, AI, waves, controls and physical-object sync."""

from backend.config import settings
from backend.game.enemy_ai import DifficultyDirector
from backend.game.models import Enemy, GameStatus, WaveStats
from backend.game.simulation import GameSimulation


def obj(oid, cls, role, x, y, w=50, h=50):
    return {"id": oid, "detected_class": cls, "role": role, "center": (x, y), "footprint": (w, h), "confidence": 0.9}


def make_sim(*structures):
    sim = GameSimulation(object_source=None)
    for s in structures:
        sim.place_test_structure(s)
    return sim


def hold_wave(sim):
    """Keeps the wave open (one enemy pending, never spawned) so tests control all enemies."""
    sim._roster = ["scout"]
    sim._spawn_interval = 1e9
    sim._spawn_timer = 0.0


def make_enemy(sim, etype="scout", x=100.0, y=350.0, hp=None):
    prof = settings.game.enemies[etype]
    hp = hp or prof.health
    e = Enemy(id=sim._id("enemy"), type=etype, x=x, y=y, radius=prof.radius, health=hp, max_health=hp,
              speed=prof.speed, reward=prof.reward, base_damage=prof.base_damage, structure_dps=prof.structure_dps,
              lane=1, progress_x=x, progress_y=y)
    sim._plan(e)
    sim.enemies.append(e)
    return e


# ---------------------------------------------------------------- calibration


def test_enemy_breaches_wall_when_no_path():
    wall = obj("w", "box", "heavy_fortification", 600, 350, 60, 700)
    sim = make_sim(wall)
    sim.start_game()
    hold_wave(sim)
    e = make_enemy(sim, "tank", 450, 350)
    assert sim.no_path and e.breach_target == "struct_w"
    for _ in range(30 * 60):
        sim.step(1 / 30)
        if sim.structures["struct_w"].destroyed:
            break
    assert sim.structures["struct_w"].destroyed


def test_tower_damages_and_kills_enemy_in_range():
    sim = make_sim(obj("t", "bottle", "defense_tower", 300, 350))
    sim.start_game()
    hold_wave(sim)
    e = make_enemy(sim, "scout", 250, 350)
    e.speed = 0
    credits = sim.credits
    for _ in range(30 * 5):
        sim.step(1 / 30)
    assert e.health <= 0 and e not in sim.enemies
    assert sim.kills == 1 and sim.credits == credits + e.reward
    assert sim.structures["struct_t"].kills == 1


def test_tower_ignores_enemy_out_of_range():
    sim = make_sim(obj("t", "bottle", "defense_tower", 100, 100))
    sim.start_game()
    hold_wave(sim)
    e = make_enemy(sim, "scout", 800, 600)
    e.speed = 0
    for _ in range(60):
        sim.step(1 / 30)
    assert sim.projectiles == [] and e.health == e.max_health


def test_enemy_reaching_base_damages_it():
    sim = make_sim()
    sim.start_game()
    hold_wave(sim)
    e = make_enemy(sim, "tank", sim.base.x - 80, sim.base.y)
    for _ in range(30 * 4):
        sim.step(1 / 30)
    assert sim.base.health == sim.base.max_health - e.base_damage
    assert sim.wave_stats.leaked == 1


def test_saboteur_disables_tower():
    sim = make_sim(obj("t", "bottle", "defense_tower", 400, 350))
    sim.start_game()
    hold_wave(sim)
    e = make_enemy(sim, "saboteur", 250, 350, hp=100000)
    assert e.goal == "sabotage"
    for _ in range(30 * 6):
        sim.step(1 / 30)
        if sim.structures["struct_t"].disabled_until > sim.time:
            break
    assert sim.wave_stats.sabotages >= 1


def test_abilities():
    sim = make_sim()
    sim.start_game()
    hold_wave(sim)
    sim.credits = 1000
    e = make_enemy(sim, "scout", 400, 400)
    ok, _ = sim.use_ability("strike", 400, 400)
    assert ok and e.health <= 0
    ok, msg = sim.use_ability("strike", 400, 400)
    assert not ok and "recharging" in msg
    e2 = make_enemy(sim, "tank", 300, 300)
    assert sim.use_ability("emp")[0] and e2.stunned_until > sim.time


# ---------------------------------------------------------------- waves & controls


def test_wave_progression_and_victory():
    sim = make_sim(*(obj(f"t{i}", "bottle", "defense_tower", x, y) for i, (x, y) in enumerate(
        [(300, 200), (300, 500), (600, 350), (800, 250), (800, 450), (500, 150), (500, 550)])))
    sim.start_game()
    assert sim.wave == 1 and sim.status == GameStatus.RUNNING
    seen = []
    for _ in range(30 * 60 * 20):
        sim.step(1 / 30)
        if sim.status == GameStatus.WAVE_ENDED:
            seen.append(sim.last_summary["wave_number"])
            assert sim.last_summary["suggestions"]
            for s in list(sim.structures.values()):
                sim.upgrade(s.id)
            assert sim.next_wave()
        if sim.status in (GameStatus.VICTORY, GameStatus.GAME_OVER):
            break
    assert seen == list(range(1, sim.total_waves))
    assert sim.status == GameStatus.VICTORY and sim.final_result["outcome"] == "victory"


def test_defeat_when_base_destroyed():
    sim = make_sim()
    sim.start_game()
    for _ in range(30 * 60 * 5):
        sim.step(1 / 30)
        if sim.status == GameStatus.WAVE_ENDED:
            sim.next_wave()
        if sim.status == GameStatus.GAME_OVER:
            break
    assert sim.status == GameStatus.GAME_OVER and sim.base.health == 0


def test_pause_freezes_game_clock_and_resume_restart():
    sim = make_sim()
    sim.start_game()
    for _ in range(30):
        sim.step(1 / 30)
    assert sim.pause() and sim.status == GameStatus.PAUSED
    t, enemies = sim.time, [(e.x, e.y) for e in sim.enemies]
    for _ in range(90):
        sim.step(1 / 30)
    assert sim.time == t and [(e.x, e.y) for e in sim.enemies] == enemies
    assert sim.resume() and sim.status == GameStatus.RUNNING
    sim.step(1 / 30)
    assert sim.time > t
    sim.restart()
    assert sim.wave == 1 and sim.score == 0 and sim.enemies == [] and sim.time == 0


def test_moving_object_moves_structure_and_reroutes():
    objects = [{**obj("b", "book", "barrier", 500, 350, 90, 300), "custom": None}]
    sim = GameSimulation(object_source=lambda: [dict(o) for o in objects])
    sim.start_game()
    hold_wave(sim)
    sim.step(1 / 30)
    e = make_enemy(sim, "tank", 100, 350)
    v0 = sim.grid.version
    objects[0]["center"] = (300, 120)
    sim.step(1 / 30)
    s = sim.structures["struct_b"]
    assert (s.x, s.y) == (300, 120)
    assert sim.grid.version > v0
    assert not sim.grid.is_blocked_at(500, 350) and sim.grid.is_blocked_at(300, 120)
    sim.step(1 / 30)
    assert not e.needs_reroute  # path recomputed


def test_mid_game_placement_costs_credits():
    objects = []
    sim = GameSimulation(object_source=lambda: [dict(o) for o in objects])
    sim.start_game()
    hold_wave(sim)
    credits = sim.credits
    objects.append({**obj("n", "cup", "cup", 400, 400), "role": "defense_tower"})
    sim.step(1 / 30)
    cost = settings.game.roles["defense_tower"].cost
    assert sim.credits == credits - cost and sim.structures["struct_n"].active


def test_director_respects_limits():
    d = DifficultyDirector()
    for _ in range(30):
        d.adapt(WaveStats(wave=1, leaked=0), 100)
    assert d.value == settings.game.difficulty.maximum
    for _ in range(30):
        d.adapt(WaveStats(wave=1, leaked=5, damage_received=60), 100)
    assert d.value == settings.game.difficulty.minimum


# ---------------------------------------------------------------- transport
