import cv2
import json
import argparse
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta
from ultralytics import YOLO

from pipeline.tracker import ReIDTracker
from pipeline.staff_classifier import StaffClassifier
from pipeline.emit import EventEmitter, make_event


# Zone utilities
def load_store_layout(layout_path: str) -> dict:
    with open(layout_path, "r") as f:
        return json.load(f)


def get_zone_for_centroid(cx: float, cy: float, zones: list) -> str | None:
    for zone in zones:
        x1 = zone.get("x1", 0)
        y1 = zone.get("y1", 0)
        x2 = zone.get("x2", 9999)
        y2 = zone.get("y2", 9999)
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            return zone["zone_id"]
    return None


# Direction detection
def get_direction(trajectory: list, frame_height: int) -> str | None:
    if len(trajectory) < 5:
        return None
    start_y = trajectory[0][1]
    end_y   = trajectory[-1][1]
    delta   = end_y - start_y
    if delta > frame_height * 0.1:
        return "ENTRY"
    elif delta < -frame_height * 0.1:
        return "EXIT"
    return None


# Billing queue helpers
def get_billing_queue_depth(zone_dwell_tracker: dict) -> int:
    return len([
        v for v in zone_dwell_tracker
        if zone_dwell_tracker[v]["zone"] == "BILLING"
    ])


# Main processing pipeline
def process_clip(
    video_path: str,
    store_id: str,
    camera_id: str,
    layout_path: str,
    output_path: str,
    clip_start_time: datetime,
    model_path: str = "yolov8n.pt",
    confidence_threshold: float = 0.5,
    seen_visitors: set = None,  # Initialize shared visitor tracking
):
    print(f"\n🎬 Processing: {video_path}")
    print(f"   Store: {store_id} | Camera: {camera_id}")

    # Cross-camera deduplication
    if seen_visitors is None:
        seen_visitors = set()

    # Initialize models and helpers
    model     = YOLO(model_path)
    tracker   = ReIDTracker()
    staff_clf = StaffClassifier()
    emitter   = EventEmitter(output_path)

    # Load store configuration
    layout = load_store_layout(layout_path)
    zones  = layout.get("zones", [])

    # Open input video
    cap          = cv2.VideoCapture(video_path)
    fps          = cap.get(cv2.CAP_PROP_FPS) or 15.0
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    frame_idx                    = 0
    zone_dwell_tracker: dict[str, dict] = {}
    billing_queue_visitors: set         = set()
    visitor_billing_entry_time: dict    = {}

    print(f"   FPS: {fps} | Processing frames...")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        offset_sec = frame_idx / fps
        now        = clip_start_time + timedelta(seconds=offset_sec)

        # Run object detection
        results    = model(frame, classes=[0], verbose=False)
        detections = []

        for result in results:
            for box in result.boxes:
                conf = float(box.conf[0])
                bbox = tuple(box.xyxy[0].tolist())
                detections.append((bbox, conf))

        # Update tracker state
        tracks = tracker.update(detections, now)

        for t in tracks:
            visitor_id = t["visitor_id"]
            bbox       = t["bbox"]
            conf       = t["confidence"]
            status     = t["status"]
            seq        = t["session_seq"]
            
            # Classify staff members
            is_staff, _ = staff_clf.classify(frame, bbox, visitor_id)
            tracker.set_staff(int(t["track_id"]), is_staff)

            # Resolve visitor zone
            cx, cy  = t["centroid"]
            zone_id = get_zone_for_centroid(cx, cy, zones)

            # Generate events

            # New visitor entry
            if status == "NEW":
                if visitor_id not in seen_visitors:
                    seen_visitors.add(visitor_id)
                    emitter.emit(make_event(
                        store_id=store_id,
                        camera_id=camera_id,
                        visitor_id=visitor_id,
                        event_type="ENTRY",
                        timestamp=now,
                        is_staff=is_staff,
                        confidence=conf,
                        session_seq=seq,
                    ))

            # Re-entry event
            elif status == "REENTRY":
                emitter.emit(make_event(
                    store_id=store_id,
                    camera_id=camera_id,
                    visitor_id=visitor_id,
                    event_type="REENTRY",
                    timestamp=now,
                    is_staff=is_staff,
                    confidence=conf,
                    session_seq=seq,
                ))

            # EXIT
            elif status == "EXITED":
                track_obj = tracker.lost_tracks.get(t["track_id"])
                if track_obj:
                    direction = get_direction(track_obj.trajectory, frame_height)
                    if direction == "EXIT" or direction is None:
                        emitter.emit(make_event(
                            store_id=store_id,
                            camera_id=camera_id,
                            visitor_id=visitor_id,
                            event_type="EXIT",
                            timestamp=now,
                            is_staff=is_staff,
                            confidence=conf,
                            session_seq=seq,
                        ))

                # Check for queue abandonment
                if visitor_id in billing_queue_visitors:
                    billing_queue_visitors.discard(visitor_id)
                    visitor_billing_entry_time.pop(visitor_id, None)
                    emitter.emit(make_event(
                        store_id=store_id,
                        camera_id=camera_id,
                        visitor_id=visitor_id,
                        event_type="BILLING_QUEUE_ABANDON",
                        timestamp=now,
                        zone_id="BILLING",
                        is_staff=is_staff,
                        confidence=conf,
                        session_seq=seq,
                        queue_depth=get_billing_queue_depth(zone_dwell_tracker),
                    ))

                zone_dwell_tracker.pop(visitor_id, None)
                seen_visitors.discard(visitor_id)  # Remove visitor from active tracking
                continue

            # Zone-related events
            if zone_id and status == "TRACKED":
                prev = zone_dwell_tracker.get(visitor_id)

                # Entered a new zone
                if not prev or prev["zone"] != zone_id:
                    if prev:
                        emitter.emit(make_event(
                            store_id=store_id,
                            camera_id=camera_id,
                            visitor_id=visitor_id,
                            event_type="ZONE_EXIT",
                            timestamp=now,
                            zone_id=prev["zone"],
                            is_staff=is_staff,
                            confidence=conf,
                            session_seq=seq,
                        ))

                    emitter.emit(make_event(
                        store_id=store_id,
                        camera_id=camera_id,
                        visitor_id=visitor_id,
                        event_type="ZONE_ENTER",
                        timestamp=now,
                        zone_id=zone_id,
                        is_staff=is_staff,
                        confidence=conf,
                        session_seq=seq,
                    ))
                    zone_dwell_tracker[visitor_id] = {
                        "zone": zone_id,
                        "enter_time": now,
                        "last_dwell_emit": now,
                    }

                    # Queue join handling
                    if zone_id == "BILLING" and not is_staff:
                        queue_depth = get_billing_queue_depth(zone_dwell_tracker)
                        if queue_depth > 0:
                            billing_queue_visitors.add(visitor_id)
                            visitor_billing_entry_time[visitor_id] = now
                            emitter.emit(make_event(
                                store_id=store_id,
                                camera_id=camera_id,
                                visitor_id=visitor_id,
                                event_type="BILLING_QUEUE_JOIN",
                                timestamp=now,
                                zone_id="BILLING",
                                is_staff=is_staff,
                                confidence=conf,
                                session_seq=seq,
                                queue_depth=get_billing_queue_depth(zone_dwell_tracker),
                            ))

                # Emit dwell updates at 30-second intervals
                else:
                    last_emit = prev["last_dwell_emit"]
                    dwell_ms  = int((now - prev["enter_time"]).total_seconds() * 1000)
                    if (now - last_emit).total_seconds() >= 30:
                        emitter.emit(make_event(
                            store_id=store_id,
                            camera_id=camera_id,
                            visitor_id=visitor_id,
                            event_type="ZONE_DWELL",
                            timestamp=now,
                            zone_id=zone_id,
                            dwell_ms=dwell_ms,
                            is_staff=is_staff,
                            confidence=conf,
                            session_seq=seq,
                        ))
                        zone_dwell_tracker[visitor_id]["last_dwell_emit"] = now

        frame_idx += 1

        if frame_idx % 500 == 0:
            print(f"   Frame {frame_idx} | Events: {emitter.count}")

    cap.release()
    emitter.close()
    print(f"✅ Done: {video_path} | Total events: {emitter.count}")


# Command-line entry point
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apex Store Detection Pipeline")
    parser.add_argument("--video",      required=True, help="Path to video clip")
    parser.add_argument("--store-id",   required=True, help="Store ID")
    parser.add_argument("--camera-id",  required=True, help="Camera ID")
    parser.add_argument("--layout",     required=True, help="Path to store_layout.json")
    parser.add_argument("--output",     required=True, help="Output JSONL path")
    parser.add_argument("--start-time", required=True, help="Clip start time ISO-8601")
    parser.add_argument("--model",      default="yolov8n.pt", help="YOLO model path")
    parser.add_argument("--confidence", default=0.5, type=float)
    args = parser.parse_args()

    start_time = datetime.fromisoformat(args.start_time.replace("Z", "+00:00"))

    process_clip(
        video_path=args.video,
        store_id=args.store_id,
        camera_id=args.camera_id,
        layout_path=args.layout,
        output_path=args.output,
        clip_start_time=start_time,
        model_path=args.model,
        confidence_threshold=args.confidence,
    )