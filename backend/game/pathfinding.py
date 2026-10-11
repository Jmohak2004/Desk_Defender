"""A* navigation on a grid over the normalized battlefield.

Layers per cell:
  blocked  - impassable (barriers / fortifications, inflated by an enemy-size margin)
  owner    - which structure blocks the cell (for breaching when no path exists)
  soft     - extra traversal cost for passable structures (towers occupy space)
  threat   - tower DPS covering the cell, used by the tactical AI to weigh routes

Paths are smoothed with line-of-sight string pulling that never crosses a
blocked cell, so smoothed segments cannot cut through obstacles.
"""

import heapq
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from backend.game.models import Structure

SQRT2 = math.sqrt(2.0)


@dataclass
class PathResult:
    waypoints: List[List[float]]
    cells: List[int]
    length: float
    breach_structure: Optional[str]
    expected_dps_time: float  # integral of threat over time-in-cell (per unit speed)
    reachable: bool


class NavigationGrid:
    def __init__(self, width: int, height: int, cell_size: int, margin: float = 14.0):
        self.width = width
        self.height = height
        self.cell = cell_size
        self.cols = int(math.ceil(width / cell_size))
        self.rows = int(math.ceil(height / cell_size))
        self.margin = margin
        n = self.cols * self.rows
        self.blocked: List[bool] = [False] * n
        self.owner: List[Optional[str]] = [None] * n
        self.soft: List[float] = [0.0] * n
        self.threat: List[float] = [0.0] * n
        self.max_threat = 1.0
        self.version = 0
        self._neighbors = self._build_neighbors()
        cx = (np.arange(self.cols) + 0.5) * cell_size
        cy = (np.arange(self.rows) + 0.5) * cell_size
        self._gx, self._gy = np.meshgrid(cx, cy)

    def _build_neighbors(self) -> List[List[Tuple[int, float, int, int]]]:
        out = []
        for r in range(self.rows):
            for c in range(self.cols):
                lst = []
                for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)):
                    nc, nr = c + dc, r + dr
                    if 0 <= nc < self.cols and 0 <= nr < self.rows:
                        diag = dc != 0 and dr != 0
                        # For diagonals remember the two orthogonal cells to forbid corner cutting.
                        a = r * self.cols + nc if diag else -1
                        b = nr * self.cols + c if diag else -1
                        lst.append((nr * self.cols + nc, SQRT2 if diag else 1.0, a, b))
                out.append(lst)
        return out

    # ------------------------------------------------------------------ coordinates
    def cell_of(self, x: float, y: float) -> int:
        c = min(self.cols - 1, max(0, int(x // self.cell)))
        r = min(self.rows - 1, max(0, int(y // self.cell)))
        return r * self.cols + c

    def center_of(self, idx: int) -> Tuple[float, float]:
        r, c = divmod(idx, self.cols)
        return (c + 0.5) * self.cell, (r + 0.5) * self.cell

    def is_blocked_at(self, x: float, y: float) -> bool:
        return self.blocked[self.cell_of(x, y)]

    # ------------------------------------------------------------------ rasterization
    def rasterize(self, structures: Sequence[Structure], base_pos: Tuple[float, float], base_radius: float,
                  keep_free: Sequence[Tuple[float, float]] = (), now: float = 0.0) -> None:
        blocked = np.zeros((self.rows, self.cols), dtype=bool)
        owner = np.full((self.rows, self.cols), -1, dtype=np.int32)
        soft = np.zeros((self.rows, self.cols), dtype=np.float32)
        threat = np.zeros((self.rows, self.cols), dtype=np.float32)
        ids: List[str] = []
        gx, gy = self._gx, self._gy
        for s in structures:
            if not s.active or s.destroyed:
                continue
            hw, hh = s.w / 2 + self.margin, s.h / 2 + self.margin
            inside = (np.abs(gx - s.x) <= hw) & (np.abs(gy - s.y) <= hh)
            if s.blocks_path:
                ids.append(s.id)
                blocked |= inside
                owner[inside] = len(ids) - 1
                if s.slow_radius > 0:
                    ring = (np.abs(gx - s.x) <= hw + s.slow_radius) & (np.abs(gy - s.y) <= hh + s.slow_radius)
                    soft[ring & ~inside] += 0.6
            else:
                soft[inside] += s.path_cost
            if s.behavior == "attack" and s.damage > 0:
                rng = s.range * s.buff_range
                cover = (gx - s.x) ** 2 + (gy - s.y) ** 2 <= rng * rng
                threat[cover] += s.damage * s.buff_damage * s.fire_rate
        free_r = base_radius + self.cell
        base_mask = (gx - base_pos[0]) ** 2 + (gy - base_pos[1]) ** 2 <= free_r * free_r
        blocked[base_mask] = False
        owner[base_mask] = -1
        for (fx, fy) in keep_free:
            m = (gx - fx) ** 2 + (gy - fy) ** 2 <= (self.cell * 1.2) ** 2
            blocked[m] = False
            owner[m] = -1
        self.blocked = blocked.ravel().tolist()
        flat_owner = owner.ravel().tolist()
        self.owner = [ids[o] if o >= 0 else None for o in flat_owner]
        self.soft = soft.ravel().tolist()
        self.threat = threat.ravel().tolist()
        self.max_threat = max(1.0, float(threat.max()))
        self.version += 1

    def nearest_free(self, x: float, y: float) -> Tuple[float, float]:
        start = self.cell_of(x, y)
        if not self.blocked[start]:
            return x, y
        seen = {start}
        frontier = [start]
        while frontier:
            nxt = []
            for idx in frontier:
                for n, _, _, _ in self._neighbors[idx]:
                    if n in seen:
                        continue
                    if not self.blocked[n]:
                        return self.center_of(n)
                    seen.add(n)
                    nxt.append(n)
            frontier = nxt
        return x, y

    def threat_at(self, x: float, y: float) -> float:
        return self.threat[self.cell_of(x, y)]


class AStarRouter:
    def __init__(self, grid: NavigationGrid):
        self.grid = grid

    def find_path(self, start: Tuple[float, float], goal: Tuple[float, float], threat_weight: float = 0.0,
                  allow_breach: bool = True, breach_costs: Optional[Dict[str, float]] = None) -> PathResult:
        """A* from start to goal. If the goal is walled off, plans a breach through the cheapest obstacle."""
        g = self.grid
        sx, sy = g.nearest_free(*start) if g.blocked[g.cell_of(*start)] else start
        s_idx, g_idx = g.cell_of(sx, sy), g.cell_of(*goal)
        cells = self._astar(s_idx, g_idx, threat_weight, None)
        breach_id = None
        if cells is None and allow_breach:
            cells = self._astar(s_idx, g_idx, threat_weight, breach_costs or {})
            if cells is not None:
                breach_id = next((g.owner[c] for c in cells if g.blocked[c]), None)
        if cells is None:
            return PathResult([[start[0], start[1]], [goal[0], goal[1]]], [], math.hypot(goal[0] - start[0], goal[1] - start[1]),
                              None, 0.0, False)
        tw = threat_weight / g.max_threat
        pts = [list(start)] + [list(g.center_of(c)) for c in cells[1:-1]] + [list(goal)]
        penalties = [g.soft[c] + tw * g.threat[c] for c in cells]
        if len(penalties) != len(pts):
            penalties = [0.0] * len(pts)
        waypoints = self._smooth(pts, penalties, tw)
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(waypoints, waypoints[1:]))
        exposure = sum(g.threat[c] for c in cells) * g.cell
        return PathResult(waypoints, cells, length, breach_id, exposure, True)

    def _astar(self, start: int, goal: int, threat_weight: float,
               breach_costs: Optional[Dict[str, float]]) -> Optional[List[int]]:
        g = self.grid
        blocked, soft, threat, owner, nbrs = g.blocked, g.soft, g.threat, g.owner, g._neighbors
        cols = g.cols
        gr, gc = divmod(goal, cols)
        tw = threat_weight / g.max_threat
        breach = breach_costs is not None

        def h(idx: int) -> float:
            r, c = divmod(idx, cols)
            dx, dy = abs(c - gc), abs(r - gr)
            return (dx + dy) + (SQRT2 - 2) * min(dx, dy)

        open_heap = [(h(start), 0.0, start)]
        came: Dict[int, int] = {}
        best = {start: 0.0}
        closed = set()
        while open_heap:
            _, cost, cur = heapq.heappop(open_heap)
            if cur == goal:
                path = [cur]
                while cur in came:
                    cur = came[cur]
                    path.append(cur)
                path.reverse()
                return path
            if cur in closed:
                continue
            closed.add(cur)
            for n, step, a, b in nbrs[cur]:
                if n in closed:
                    continue
                if blocked[n]:
                    if not breach:
                        continue
                    extra = breach_costs.get(owner[n], 60.0) if owner[n] else 60.0
                else:
                    extra = 0.0
                if a >= 0 and (blocked[a] or blocked[b]) and not breach:
                    continue  # no corner cutting around obstacles
                ncost = cost + step * (1.0 + soft[n] + tw * threat[n]) + extra
                if ncost < best.get(n, 1e18):
                    best[n] = ncost
                    came[n] = cur
                    heapq.heappush(open_heap, (ncost + h(n), ncost, n))
        return None

    def line_of_sight(self, a: Sequence[float], b: Sequence[float], max_penalty: float = float("inf"),
                      tw: float = 0.0) -> bool:
        """True if the segment crosses no blocked cell and no cell costlier than max_penalty."""
        g = self.grid
        dist = math.hypot(b[0] - a[0], b[1] - a[1])
        if dist < 1e-6:
            return True
        steps = max(1, int(dist / (g.cell / 3)))
        # Sample a corridor (centre line plus both sides) so movement that rounds a few
        # pixels sideways can never step into a blocked cell next to the segment.
        off = g.cell * 0.35
        px, py = -(b[1] - a[1]) / dist * off, (b[0] - a[0]) / dist * off
        for i in range(steps + 1):
            t = i / steps
            x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            idx = g.cell_of(x, y)
            if g.blocked[idx] or g.blocked[g.cell_of(x + px, y + py)] or g.blocked[g.cell_of(x - px, y - py)]:
                return False
            if g.soft[idx] + tw * g.threat[idx] > max_penalty + 0.05:
                return False
        return True

    def _smooth(self, pts: List[List[float]], penalties: List[float], tw: float) -> List[List[float]]:
        """String pulling: skip waypoints while the shortcut is clear and no costlier than the original."""
        if len(pts) <= 2:
            return pts
        out = [pts[0]]
        i = 0
        n = len(pts)
        while i < n - 1:
            j = i + 1
            limit = max(penalties[i], penalties[j])
            while j + 1 < n:
                cand_limit = max(limit, penalties[j + 1])
                if not self.line_of_sight(pts[i], pts[j + 1], cand_limit, tw):
                    break
                j += 1
                limit = cand_limit
            out.append(pts[j])
            i = j
        return [[round(p[0], 1), round(p[1], 1)] for p in out]
