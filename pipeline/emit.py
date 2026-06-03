import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Event creation helpers
def make_event(
    store_id: str,
    camera_id: str,
    visitor_id: str,
    event_type: str,
    timestamp: datetime,
    zone_id: Optional[str] = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    confidence: float = 1.0,
    queue_depth: Optional[int] = None,
    sku_zone: Optional[str] = None,
    session_seq: int = 0,
) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": store_id,
        "camera_id": camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": is_staff,
        "confidence": round(confidence, 4),
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone": sku_zone,
            "session_seq": session_seq,
        }
    }


# Event writer
class EventEmitter:
    def __init__(self, output_path: str):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.output_path, "a", encoding="utf-8")
        self.count = 0

    def emit(self, event: dict):
        self._file.write(json.dumps(event) + "\n")
        self._file.flush()
        self.count += 1

    def close(self):
        self._file.close()
        print(f"✅ Emitted {self.count} events → {self.output_path}")


# Load events from a JSONL file
def load_events(path: str) -> list[dict]:
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


# Send events to the ingestion API
def push_events_to_api(
    events: list[dict],
    api_url: str = "http://localhost:8000",
    batch_size: int = 100,
):
    import requests

    total = len(events)
    accepted = 0
    rejected = 0

    for i in range(0, total, batch_size):
        batch = events[i:i + batch_size]
        try:
            resp = requests.post(
                f"{api_url}/events/ingest",
                json={"events": batch},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                accepted += data.get("accepted", 0)
                rejected += data.get("rejected", 0)
                print(f"Batch {i//batch_size + 1}: ✅ {data['accepted']} accepted, "
                      f"❌ {data['rejected']} rejected, "
                      f"🔁 {data['duplicate']} duplicate")
            else:
                print(f"Batch {i//batch_size + 1}: ❌ HTTP {resp.status_code}")
        except Exception as e:
            print(f"Batch {i//batch_size + 1}: ❌ Error — {e}")

    print(f"\n✅ Done — {accepted} accepted, {rejected} rejected out of {total} total")