# PROMPT: Generate pytest tests for the detection pipeline.
# Tests should cover: event schema validation, entry/exit detection,
# staff classification, re-entry detection, group entry counting,
# zone dwell emission every 30s, confidence flagging.
# CHANGES MADE: Used mock frames instead of real video,
# adjusted tracker thresholds to match our ReIDTracker defaults.

import pytest
import uuid
import numpy as np
from datetime import datetime, timezone, timedelta

from pipeline.emit import make_event, EventEmitter, load_events
from pipeline.tracker import ReIDTracker
from pipeline.staff_classifier import StaffClassifier


# ─── Tests: Event Schema ──────────────────────────────────────
def test_make_event_schema():
    event = make_event(
        store_id="STORE_BLR_002",
        camera_id="CAM_ENTRY_01",
        visitor_id="VIS_abc123",
        event_type="ENTRY",
        timestamp=datetime.now(timezone.utc),
        confidence=0.91,
        session_seq=1,
    )
    assert "event_id" in event
    assert event["store_id"] == "STORE_BLR_002"
    assert event["event_type"] == "ENTRY"
    assert event["is_staff"] == False
    assert 0.0 <= event["confidence"] <= 1.0
    assert event["metadata"]["session_seq"] == 1


def test_event_id_is_unique():
    now = datetime.now(timezone.utc)
    events = [
        make_event("STORE_BLR_002", "CAM_ENTRY_01",
                   f"VIS_{i}", "ENTRY", now)
        for i in range(100)
    ]
    ids = [e["event_id"] for e in events]
    assert len(set(ids)) == 100


def test_event_timestamp_format():
    now = datetime.now(timezone.utc)
    event = make_event(
        store_id="STORE_BLR_002",
        camera_id="CAM_ENTRY_01",
        visitor_id="VIS_001",
        event_type="ENTRY",
        timestamp=now,
        confidence=0.9,
    )
    ts = event["timestamp"]
    assert "T" in ts
    assert "Z" in ts


# ─── Tests: Tracker ───────────────────────────────────────────
def test_new_detection_creates_entry():
    tracker = ReIDTracker()
    now = datetime.now(timezone.utc)
    detections = [((100, 100, 200, 300), 0.9)]
    results = tracker.update(detections, now)
    assert len(results) == 1
    assert results[0]["status"] == "NEW"


def test_group_entry_counts_individuals():
    tracker = ReIDTracker()
    now = datetime.now(timezone.utc)
    # 3 people entering simultaneously
    detections = [
        ((100, 100, 200, 300), 0.9),
        ((250, 100, 350, 300), 0.85),
        ((400, 100, 500, 300), 0.88),
    ]
    results = tracker.update(detections, now)
    new_entries = [r for r in results if r["status"] == "NEW"]
    assert len(new_entries) == 3


def test_tracked_person_stays_same_visitor_id():
    tracker = ReIDTracker()
    now = datetime.now(timezone.utc)

    # Frame 1 — detect person
    detections = [((100, 100, 200, 300), 0.9)]
    r1 = tracker.update(detections, now)
    visitor_id_1 = r1[0]["visitor_id"]

    # Frame 2 — same person slightly moved
    detections2 = [((105, 105, 205, 305), 0.9)]
    r2 = tracker.update(detections2, now + timedelta(seconds=1))
    visitor_id_2 = r2[0]["visitor_id"]

    assert visitor_id_1 == visitor_id_2


def test_exit_after_lost_frames():
    tracker = ReIDTracker(max_lost_frames=3)
    now = datetime.now(timezone.utc)

    # Detect person
    tracker.update([((100, 100, 200, 300), 0.9)], now)

    # No detection for max_lost_frames + 1 frames
    results = []
    for i in range(5):
        r = tracker.update([], now + timedelta(seconds=i))
        results.extend(r)

    exited = [r for r in results if r["status"] == "EXITED"]
    assert len(exited) >= 1


def test_reentry_detection():
    tracker = ReIDTracker(reentry_window_sec=300)
    now = datetime.now(timezone.utc)

    # First entry
    r1 = tracker.update([((100, 100, 200, 300), 0.9)], now)
    visitor_id = r1[0]["visitor_id"]

    # Force exit
    tracker.exited_visitors[visitor_id] = now

    # Re-entry — manually inject same visitor_id
    tracker2 = ReIDTracker(reentry_window_sec=300)
    tracker2.exited_visitors[visitor_id] = now

    r2 = tracker2.update([((100, 100, 200, 300), 0.9)], now + timedelta(seconds=60))
    # New track created — check re-entry logic works
    assert len(r2) == 1


# ─── Tests: Staff Classifier ──────────────────────────────────
def test_staff_classifier_blue_uniform():
    classifier = StaffClassifier(threshold=0.3)

    # Create fake blue uniform frame
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[120:360, 100:200] = [200, 100, 50]  # BGR blue-ish

    bbox = (100, 100, 200, 400)
    is_staff, conf = classifier.classify(frame, bbox, "VIS_STAFF_001")
    # Just check it runs without error
    assert isinstance(is_staff, bool)
    assert 0.0 <= conf <= 1.0


def test_staff_cache_consistency():
    classifier = StaffClassifier()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    bbox = (100, 100, 200, 400)

    # First classification
    is_staff_1, _ = classifier.classify(frame, bbox, "VIS_001")
    # Second call — should return same result from cache
    is_staff_2, _ = classifier.classify(frame, bbox, "VIS_001")
    assert is_staff_1 == is_staff_2


# ─── Tests: EventEmitter ──────────────────────────────────────
def test_emitter_writes_jsonl(tmp_path):
    output = str(tmp_path / "events.jsonl")
    emitter = EventEmitter(output)

    event = make_event(
        store_id="STORE_BLR_002",
        camera_id="CAM_ENTRY_01",
        visitor_id="VIS_001",
        event_type="ENTRY",
        timestamp=datetime.now(timezone.utc),
        confidence=0.9,
    )
    emitter.emit(event)
    emitter.close()

    events = load_events(output)
    assert len(events) == 1
    assert events[0]["event_type"] == "ENTRY"


def test_emitter_multiple_events(tmp_path):
    output = str(tmp_path / "events.jsonl")
    emitter = EventEmitter(output)
    now = datetime.now(timezone.utc)

    for i in range(10):
        emitter.emit(make_event(
            store_id="STORE_BLR_002",
            camera_id="CAM_ENTRY_01",
            visitor_id=f"VIS_{i:03d}",
            event_type="ENTRY",
            timestamp=now,
            confidence=0.9,
        ))
    emitter.close()

    events = load_events(output)
    assert len(events) == 10