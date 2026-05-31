import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid


# ─── Track State ──────────────────────────────────────────────
@dataclass
class Track:
    track_id: int
    visitor_id: str
    bbox: Tuple                    # (x1, y1, x2, y2)
    centroid: Tuple                # (cx, cy)
    first_seen: datetime
    last_seen: datetime
    is_active: bool = True
    is_staff: bool = False
    zone_id: Optional[str] = None
    zone_enter_time: Optional[datetime] = None
    session_seq: int = 0
    trajectory: List[Tuple] = field(default_factory=list)
    exited: bool = False


# ─── Re-ID Tracker ────────────────────────────────────────────
class ReIDTracker:
    def __init__(
        self,
        max_lost_frames: int = 30,
        reentry_window_sec: int = 300,
        iou_threshold: float = 0.3,
        distance_threshold: float = 100.0,
    ):
        self.max_lost_frames = max_lost_frames
        self.reentry_window_sec = reentry_window_sec
        self.iou_threshold = iou_threshold
        self.distance_threshold = distance_threshold

        self.active_tracks: Dict[int, Track] = {}
        self.lost_tracks: Dict[int, Track] = {}
        # visitor_id -> (exit_time, last_known_centroid)
        self.exited_visitors: Dict[str, Tuple] = {}
        self._lost_counters: Dict[int, int] = {}
        self._next_track_id = 1

    # ── Centroid ──────────────────────────────────────────────
    def _centroid(self, bbox: Tuple) -> Tuple:
        x1, y1, x2, y2 = bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    # ── IoU ───────────────────────────────────────────────────
    def _iou(self, a: Tuple, b: Tuple) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter == 0:
            return 0.0
        area_a = (ax2 - ax1) * (ay2 - ay1)
        area_b = (bx2 - bx1) * (by2 - by1)
        return inter / (area_a + area_b - inter)

    # ── Distance ──────────────────────────────────────────────
    def _distance(self, c1: Tuple, c2: Tuple) -> float:
        return float(np.sqrt((c1[0] - c2[0])**2 + (c1[1] - c2[1])**2))

    # ── Match Detections to Tracks ────────────────────────────
    def _match(self, detections: List[Tuple]) -> Dict[int, int]:
        """Returns {detection_idx: track_id}"""
        matches = {}
        used_tracks = set()

        for d_idx, bbox in enumerate(detections):
            best_track_id = None
            best_score = -1

            for track_id, track in self.active_tracks.items():
                if track_id in used_tracks:
                    continue
                iou = self._iou(bbox, track.bbox)
                dist = self._distance(self._centroid(bbox), track.centroid)
                if iou > self.iou_threshold or dist < self.distance_threshold:
                    score = iou - (dist / 1000)
                    if score > best_score:
                        best_score = score
                        best_track_id = track_id

            if best_track_id is not None:
                matches[d_idx] = best_track_id
                used_tracks.add(best_track_id)

        return matches

    # ── Check Re-entry by proximity to exited visitor ─────────
    def _find_reentry_visitor(self, bbox: Tuple, now: datetime) -> Optional[str]:
        """
        Check if this new detection is likely a re-entering visitor.
        Strategy: find an exited visitor whose last known centroid is
        close to this detection's centroid, within the reentry window.

        This solves the key edge case: same person re-entering from
        the same direction 3 seconds later — we match by proximity
        to their last known position, not by generating a new UUID first.
        """
        new_centroid = self._centroid(bbox)
        best_visitor_id = None
        best_distance = float("inf")

        for visitor_id, (exit_time, last_centroid) in self.exited_visitors.items():
            delta = (now - exit_time).total_seconds()
            if delta > self.reentry_window_sec:
                continue
            dist = self._distance(new_centroid, last_centroid)
            # Within 150px of last known position — likely same person
            if dist < 150.0 and dist < best_distance:
                best_distance = dist
                best_visitor_id = visitor_id

        return best_visitor_id

    # ── Update Tracks ─────────────────────────────────────────
    def update(
        self,
        detections: List[Tuple],  # list of (bbox, confidence)
        now: datetime,
    ) -> List[Dict]:
        """
        Update tracker with new detections.
        Returns list of track updates with visitor_id and status.
        """
        bboxes  = [d[0] for d in detections]
        confs   = [d[1] for d in detections]
        matches = self._match(bboxes)
        results = []

        matched_track_ids = set(matches.values())

        # ── Update matched tracks ──────────────────────────────
        for d_idx, track_id in matches.items():
            track = self.active_tracks[track_id]
            track.bbox     = bboxes[d_idx]
            track.centroid = self._centroid(bboxes[d_idx])
            track.last_seen = now
            track.trajectory.append(track.centroid)
            self._lost_counters[track_id] = 0
            track.session_seq += 1

            results.append({
                "track_id":    track_id,
                "visitor_id":  track.visitor_id,
                "bbox":        track.bbox,
                "centroid":    track.centroid,
                "confidence":  confs[d_idx],
                "is_staff":    track.is_staff,
                "status":      "TRACKED",
                "session_seq": track.session_seq,
            })

        # ── New detections ─────────────────────────────────────
        for d_idx, (bbox, conf) in enumerate(detections):
            if d_idx in matches:
                continue

            # Check if this is a re-entering visitor BEFORE generating new ID
            # This is the critical fix — we match by proximity to exited centroid
            reentry_visitor_id = self._find_reentry_visitor(bbox, now)

            if reentry_visitor_id:
                # Re-entry: reuse same visitor_id, remove from exited dict
                visitor_id = reentry_visitor_id
                del self.exited_visitors[visitor_id]
                status = "REENTRY"
            else:
                # Genuinely new visitor
                visitor_id = f"VIS_{uuid.uuid4().hex[:6]}"
                status = "NEW"

            track = Track(
                track_id=self._next_track_id,
                visitor_id=visitor_id,
                bbox=bbox,
                centroid=self._centroid(bbox),
                first_seen=now,
                last_seen=now,
                trajectory=[self._centroid(bbox)],
            )

            self.active_tracks[self._next_track_id] = track
            self._lost_counters[self._next_track_id] = 0
            self._next_track_id += 1

            results.append({
                "track_id":    track.track_id,
                "visitor_id":  visitor_id,
                "bbox":        bbox,
                "centroid":    track.centroid,
                "confidence":  conf,
                "is_staff":    False,
                "status":      status,
                "session_seq": 0,
            })

        # ── Lost tracks ────────────────────────────────────────
        for track_id in list(self.active_tracks.keys()):
            if track_id not in matched_track_ids:
                self._lost_counters[track_id] = (
                    self._lost_counters.get(track_id, 0) + 1
                )
                if self._lost_counters[track_id] > self.max_lost_frames:
                    track = self.active_tracks.pop(track_id)
                    track.exited = True
                    # Store exit time AND last known centroid for re-entry matching
                    self.exited_visitors[track.visitor_id] = (
                        track.last_seen,
                        track.centroid,
                    )
                    self.lost_tracks[track_id] = track
                    results.append({
                        "track_id":    track_id,
                        "visitor_id":  track.visitor_id,
                        "bbox":        track.bbox,
                        "centroid":    track.centroid,
                        "confidence":  0.0,
                        "is_staff":    track.is_staff,
                        "status":      "EXITED",
                        "session_seq": track.session_seq,
                    })

        return results

    # ── Helpers ───────────────────────────────────────────────
    def get_track(self, track_id: int) -> Optional[Track]:
        return self.active_tracks.get(track_id)

    def set_staff(self, track_id: int, is_staff: bool):
        if track_id in self.active_tracks:
            self.active_tracks[track_id].is_staff = is_staff

    def reset(self):
        self.active_tracks.clear()
        self.lost_tracks.clear()
        self.exited_visitors.clear()
        self._lost_counters.clear()
        self._next_track_id = 1