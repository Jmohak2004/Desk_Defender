"""Object tracking with stable IDs, temporal smoothing and stale handling.

Detections arrive in camera pixels (or virtual coordinates for shape blobs),
are mapped into battlefield coordinates, and are associated with existing
tracks by a global greedy assignment on a cost combining distance, class
agreement and overlap. Positions are smoothed with an EMA plus a deadband so
detection jitter does not move structures, while genuine moves are followed.
"""

import logging
import math
import threading
import time
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple

from backend.config import CustomStructureConfig, role_for_class, settings

logger = logging.getLogger("desk_defender.tracker")


class Track:
    def __init__(self, track_id: str, det: Dict, now: float):
        self.id = track_id
        self.class_votes: Dict[str, float] = defaultdict(float)
        self.class_votes[det["class"]] += det["confidence"]
        self.detected_class = det["class"]
        self.confidence = det["confidence"]
        self.source = det.get("source", "yolo")
        self.bbox = det.get("bbox")
        self.center = det["center"]
        self.footprint = det["footprint"]
        self.committed_center = det["center"]  # last position that counted as a physical move
        self.hits = 1
        self.first_seen = now
        self.last_seen = now
        self.missed = 0
        self.role_override: Optional[str] = None
        self.custom: Optional[CustomStructureConfig] = None
        self.move_count = 0
        self.last_moved_at = 0.0

    def update(self, det: Dict, now: float) -> None:
        v = settings.vision
        self.hits += 1
        self.missed = 0
        self.last_seen = now
        self.bbox = det.get("bbox")
        self.source = det.get("source", self.source)
        # Confidence-weighted class vote with decay so the label stabilises.
        for k in list(self.class_votes):
            self.class_votes[k] *= 0.9
        self.class_votes[det["class"]] += det["confidence"]
        self.detected_class = max(self.class_votes.items(), key=lambda kv: kv[1])[0]
        self.confidence = round(0.7 * self.confidence + 0.3 * det["confidence"], 3)

        dx = det["center"][0] - self.center[0]
        dy = det["center"][1] - self.center[1]
        if math.hypot(dx, dy) > v.jitter_deadband:
            a = v.position_smoothing_alpha
            # Large jumps converge faster so a moved object does not lag for seconds.
            if math.hypot(dx, dy) > 4 * v.move_event_threshold:
                a = max(a, 0.6)
            self.center = (self.center[0] + a * dx, self.center[1] + a * dy)
        a = v.position_smoothing_alpha
        self.footprint = (self.footprint[0] + a * (det["footprint"][0] - self.footprint[0]),
                          self.footprint[1] + a * (det["footprint"][1] - self.footprint[1]))
        if math.hypot(self.center[0] - self.committed_center[0],
                      self.center[1] - self.committed_center[1]) > v.move_event_threshold:
            self.committed_center = self.center
            self.move_count += 1
            self.last_moved_at = now

    @property
    def role(self) -> str:
        return self.role_override or role_for_class(self.detected_class)

    def to_dict(self, now: float) -> Dict:
        v = settings.vision
        stale_for = now - self.last_seen if self.missed > 0 else 0.0
        return {
            "id": self.id,
            "detected_class": self.detected_class,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "bbox": [round(b, 1) for b in self.bbox] if self.bbox else None,
            "center": [round(self.center[0], 1), round(self.center[1], 1)],
            "footprint": [round(self.footprint[0], 1), round(self.footprint[1], 1)],
            "role": self.role,
            "default_role": role_for_class(self.detected_class),
            "is_manual_role": self.role_override is not None,
            "custom": self.custom.model_dump() if self.custom else None,
            "confirmed": self.hits >= v.tracker_min_hits,
            "is_stale": self.missed > 0,
            "stale_seconds": round(stale_for, 2),
            "removal_in": round(max(0.0, v.stale_grace_seconds - stale_for), 2) if self.missed > 0 else None,
            "last_seen": self.last_seen,
            "first_seen": self.first_seen,
            "move_count": self.move_count,
            "last_moved_at": self.last_moved_at,
        }


class ObjectTracker:
    """Thread-safe tracker. The vision thread calls update(); API/game threads read snapshots."""

    def __init__(self, transform_bbox: Optional[Callable[[List[float]], Dict]] = None):
        self._lock = threading.RLock()
        self._tracks: Dict[str, Track] = {}
        self._next_id = 1
        self._suppressed: List[Dict] = []  # manually removed false detections
        self._transform_bbox = transform_bbox
        self.version = 0

    def set_transform(self, fn: Callable[[List[float]], Dict]) -> None:
        self._transform_bbox = fn

    # ------------------------------------------------------------------ mapping
    def _to_virtual(self, det: Dict) -> Optional[Dict]:
        v = settings.vision
        if "virtual_bbox" in det:
            x1, y1, x2, y2 = det["virtual_bbox"]
            center = ((x1 + x2) / 2, (y1 + y2) / 2)
            footprint = (x2 - x1, y2 - y1)
        else:
            if self._transform_bbox is None:
                return None
            mapped = self._transform_bbox(det["bbox"])
            center, footprint = mapped["center"], mapped["footprint"]
        W, H = settings.virtual_width, settings.virtual_height
        # Ignore anything whose centre falls outside the calibrated play area.
        if not (-10 <= center[0] <= W + 10 and -10 <= center[1] <= H + 10):
            return None
        if footprint[0] * footprint[1] > v.max_area_fraction * W * H:
            return None
        fw = min(v.footprint_max, max(v.footprint_min, footprint[0] * v.footprint_scale))
        fh = min(v.footprint_max, max(v.footprint_min, footprint[1] * v.footprint_scale))
        out = dict(det)
        out["center"] = (min(W, max(0.0, center[0])), min(H, max(0.0, center[1])))
        out["footprint"] = (fw, fh)
        return out

    def _is_suppressed(self, det: Dict) -> bool:
        for s in self._suppressed:
            if math.hypot(det["center"][0] - s["center"][0], det["center"][1] - s["center"][1]) < s["radius"]:
                if s["class"] == det["class"] or det.get("source") == "shape":
                    return True
        return False

    # ------------------------------------------------------------------ update
    def update(self, detections: List[Dict], now: Optional[float] = None) -> List[Dict]:
        now = time.time() if now is None else now
        v = settings.vision
        with self._lock:
            mapped = [m for m in (self._to_virtual(d) for d in detections) if m is not None]
            mapped = [m for m in mapped if not self._is_suppressed(m)]

            # Build candidate pairs and assign globally cheapest first.
            pairs: List[Tuple[float, str, int]] = []
            for tid, tr in self._tracks.items():
                for di, det in enumerate(mapped):
                    dist = math.hypot(det["center"][0] - tr.center[0], det["center"][1] - tr.center[1])
                    gate = v.tracker_max_distance * (1.6 if tr.missed > 0 else 1.0)
                    if dist > gate:
                        continue
                    same = det["class"] == tr.detected_class or det["class"] in tr.class_votes
                    cost = dist * (1.0 if same else 1.5)
                    cost -= 30.0 * _box_iou(det, tr)
                    pairs.append((cost, tid, di))
            pairs.sort(key=lambda p: p[0])
            used_tracks, used_dets = set(), set()
            for _, tid, di in pairs:
                if tid in used_tracks or di in used_dets:
                    continue
                self._tracks[tid].update(mapped[di], now)
                used_tracks.add(tid)
                used_dets.add(di)

            # Re-identification: an object picked up and put down elsewhere jumps further than the
            # gate. Match leftover detections to leftover confirmed tracks of the same class.
            reid: List[Tuple[float, str, int]] = []
            for tid, tr in self._tracks.items():
                if tid in used_tracks or tr.hits < v.tracker_min_hits:
                    continue
                for di, det in enumerate(mapped):
                    if di in used_dets or det["class"] not in tr.class_votes:
                        continue
                    dist = math.hypot(det["center"][0] - tr.center[0], det["center"][1] - tr.center[1])
                    if dist <= v.reid_max_distance:
                        reid.append((dist, tid, di))
            for _, tid, di in sorted(reid):
                if tid in used_tracks or di in used_dets:
                    continue
                tr = self._tracks[tid]
                tr.center = mapped[di]["center"]  # jump straight to the new spot; the UI animates the slide
                tr.update(mapped[di], now)
                used_tracks.add(tid)
                used_dets.add(di)

            for di, det in enumerate(mapped):
                if di in used_dets:
                    continue
                tid = f"obj_{self._next_id}"
                self._next_id += 1
                self._tracks[tid] = Track(tid, det, now)

            for tid in list(self._tracks):
                tr = self._tracks[tid]
                if tid in used_tracks or tr.last_seen == now:
                    continue
                tr.missed += 1
                # Unconfirmed one-off detections vanish immediately; confirmed ones get a grace period.
                if tr.hits < v.tracker_min_hits and tr.missed >= 2:
                    del self._tracks[tid]
                elif now - tr.last_seen > v.stale_grace_seconds:
                    logger.info("Track %s (%s) lost for %.1fs - removing", tid, tr.detected_class, now - tr.last_seen)
                    del self._tracks[tid]
            self.version += 1
            return [t.to_dict(now) for t in self._tracks.values()]

    # ------------------------------------------------------------------ player actions
    def snapshot(self, confirmed_only: bool = False) -> List[Dict]:
        now = time.time()
        with self._lock:
            items = [t.to_dict(now) for t in self._tracks.values()]
        return [i for i in items if i["confirmed"]] if confirmed_only else items

    def get(self, track_id: str) -> Optional[Dict]:
        with self._lock:
            t = self._tracks.get(track_id)
            return t.to_dict(time.time()) if t else None

    def set_role(self, track_id: str, role: str, custom: Optional[CustomStructureConfig] = None) -> bool:
        if role not in settings.game.roles:
            raise ValueError(f"Unknown role '{role}'. Valid roles: {', '.join(settings.game.roles)}")
        with self._lock:
            t = self._tracks.get(track_id)
            if not t:
                return False
            t.role_override = None if role == role_for_class(t.detected_class) and custom is None else role
            t.custom = custom if role == "custom" else None
            self.version += 1
            logger.info("Object %s (%s) assigned role %s", track_id, t.detected_class, role)
            return True

    def remove(self, track_id: str, suppress: bool = True) -> bool:
        """Removes a (false) detection and suppresses re-detection at that spot."""
        with self._lock:
            t = self._tracks.pop(track_id, None)
            if not t:
                return False
            if suppress:
                self._suppressed.append({
                    "class": t.detected_class, "center": t.center,
                    "radius": max(40.0, max(t.footprint) * 0.6), "id": track_id,
                })
            self.version += 1
            return True

    def suppressed(self) -> List[Dict]:
        with self._lock:
            return [{"id": s["id"], "class": s["class"], "center": [round(s["center"][0]), round(s["center"][1])]}
                    for s in self._suppressed]

    def clear_suppressed(self) -> None:
        with self._lock:
            self._suppressed.clear()
            self.version += 1

    def reset(self) -> None:
        with self._lock:
            self._tracks.clear()
            self._suppressed.clear()
            self.version += 1


def _box_iou(det: Dict, tr: Track) -> float:
    (cx1, cy1), (w1, h1) = det["center"], det["footprint"]
    (cx2, cy2), (w2, h2) = tr.center, tr.footprint
    ax1, ay1, ax2, ay2 = cx1 - w1 / 2, cy1 - h1 / 2, cx1 + w1 / 2, cy1 + h1 / 2
    bx1, by1, bx2, by2 = cx2 - w2 / 2, cy2 - h2 / 2, cx2 + w2 / 2, cy2 + h2 / 2
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = w1 * h1 + w2 * h2 - inter
    return inter / union if union > 0 else 0.0


tracker = ObjectTracker()
