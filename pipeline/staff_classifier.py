import numpy as np
import cv2
from typing import Tuple, Dict
from collections import defaultdict


# Staff uniform color ranges
STAFF_UNIFORM_COLORS = [
    {"lower": np.array([100, 50, 50]),  "upper": np.array([130, 255, 255])},  # Blue uniform range
    {"lower": np.array([0, 0, 200]),    "upper": np.array([180, 30, 255])},   # White uniform range
    {"lower": np.array([100, 50, 20]),  "upper": np.array([130, 255, 80])},   # Dark navy uniform range
]

# Classification thresholds
COLOR_WEIGHT       = 0.4
ZONE_WEIGHT        = 0.3
DWELL_WEIGHT       = 0.3
STAFF_SCORE_THRESH = 0.55
COLOR_THRESHOLD    = 0.30
STAFF_ZONE_MIN     = 4       # Minimum zones visited before increasing staff confidence
DWELL_THRESH_MS    = 30000   # <30s avg dwell = likely staff
SCREEN_TIME_THRESH = 0.75   # Dwell-time threshold used in scoring


# Visitor Stats Tracker
class VisitorStats:
    def __init__(self):
        self.zones_visited: set   = set()
        self.total_frames: int    = 0
        self.zone_dwell_ms: Dict  = defaultdict(int)
        self.last_zone: str       = None
        self.zone_enter_frame: int = 0

    def update(self, zone_id: str, frame_idx: int):
        self.total_frames += 1
        if zone_id:
            if zone_id != self.last_zone:
                self.zones_visited.add(zone_id)
                self.last_zone = zone_id
                self.zone_enter_frame = frame_idx

    def avg_dwell_ms(self, fps: float) -> float:
        if not self.zones_visited:
            return 0.0
        total_dwell = sum(self.zone_dwell_ms.values())
        return total_dwell / len(self.zones_visited) if self.zones_visited else 0.0

    def zone_count(self) -> int:
        return len(self.zones_visited)


# Main Staff Classifier
class StaffClassifier:
    def __init__(
        self,
        threshold: float = STAFF_SCORE_THRESH,
        total_frames: int = 1000,
    ):
        self.threshold     = threshold
        self.total_frames  = total_frames
        self._cache: Dict[str, bool]         = {}
        self._scores: Dict[str, float]       = {}
        self._stats: Dict[str, VisitorStats] = defaultdict(VisitorStats)

    # Color Signal
    def _color_score(self, frame: np.ndarray, bbox: Tuple) -> float:
        x1, y1, x2, y2 = map(int, bbox)
        h = y2 - y1
        torso_y1 = y1 + int(h * 0.25)
        torso_y2 = y1 + int(h * 0.75)
        torso = frame[torso_y1:torso_y2, x1:x2]

        if torso.size == 0:
            return 0.0

        hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
        total_pixels = hsv.shape[0] * hsv.shape[1]
        if total_pixels == 0:
            return 0.0

        max_ratio = 0.0
        for color in STAFF_UNIFORM_COLORS:
            mask  = cv2.inRange(hsv, color["lower"], color["upper"])
            ratio = cv2.countNonZero(mask) / total_pixels
            max_ratio = max(max_ratio, ratio)

        return min(max_ratio / COLOR_THRESHOLD, 1.0)

    # Zone Signal
    def _zone_score(self, visitor_id: str) -> float:
        zone_count = self._stats[visitor_id].zone_count()
        return min(zone_count / STAFF_ZONE_MIN, 1.0)

    #  Dwell Signal
    def _dwell_score(self, visitor_id: str, fps: float) -> float:
        avg_dwell = self._stats[visitor_id].avg_dwell_ms(fps)
        if avg_dwell == 0:
            return 0.0
        # Low dwell = high staff score
        if avg_dwell < DWELL_THRESH_MS:
            return 1.0 - (avg_dwell / DWELL_THRESH_MS)
        return 0.0

    # Combined Score
    def _compute_score(
        self,
        frame: np.ndarray,
        bbox: Tuple,
        visitor_id: str,
        fps: float = 15.0,
    ) -> float:
        color_s = self._color_score(frame, bbox)
        zone_s  = self._zone_score(visitor_id)
        dwell_s = self._dwell_score(visitor_id, fps)

        score = (
            color_s * COLOR_WEIGHT +
            zone_s  * ZONE_WEIGHT  +
            dwell_s * DWELL_WEIGHT
        )
        return round(score, 4)

    # Update Stats
    def update_stats(
        self,
        visitor_id: str,
        zone_id: str,
        frame_idx: int,
        dwell_ms: int = 0,
    ):
        self._stats[visitor_id].update(zone_id, frame_idx)
        if zone_id and dwell_ms > 0:
            self._stats[visitor_id].zone_dwell_ms[zone_id] += dwell_ms

    # Main Classify
    def classify(
        self,
        frame: np.ndarray,
        bbox: Tuple,
        visitor_id: str,
        fps: float = 15.0,
    ) -> Tuple[bool, float]:
        # Return cached after enough data collected
        if visitor_id in self._cache:
            return self._cache[visitor_id], self._scores.get(visitor_id, 0.0)

        score    = self._compute_score(frame, bbox, visitor_id, fps)
        is_staff = score >= self.threshold

        # Cache only after visitor has been seen enough
        if self._stats[visitor_id].total_frames >= 10:
            self._cache[visitor_id]  = is_staff
            self._scores[visitor_id] = score

        return is_staff, score

    def mark_as_staff(self, visitor_id: str):
        self._cache[visitor_id]  = True
        self._scores[visitor_id] = 1.0

    def is_known_staff(self, visitor_id: str) -> bool:
        return self._cache.get(visitor_id, False)

    def reset(self):
        self._cache.clear()
        self._scores.clear()
        self._stats.clear()