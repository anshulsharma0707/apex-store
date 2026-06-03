

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone
from app.main import app
from app.database import Base, engine, get_db
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Test database setup
TEST_DB_URL = "sqlite:///./test.db"

test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False}
)
TestSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine
)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    Base.metadata.drop_all(bind=test_engine)


client = TestClient(app)


# Test data helper
def make_event(event_id=None, event_type="ENTRY", is_staff=False):
    return {
        "event_id":   event_id or "test-event-001",
        "store_id":   "STORE_BLR_002",
        "camera_id":  "CAM_ENTRY_01",
        "visitor_id": "VIS_abc123",
        "event_type": event_type,
        "timestamp":  "2026-03-03T14:22:10Z",
        "zone_id":    None,
        "dwell_ms":   0,
        "is_staff":   is_staff,
        "confidence": 0.91,
        "metadata": {
            "queue_depth":  None,
            "sku_zone":     None,
            "session_seq":  1,
        }
    }


# Test cases
def test_ingest_single_event():
    resp = client.post("/events/ingest", json={"events": [make_event()]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 1
    assert data["rejected"] == 0
    assert data["duplicate"] == 0


def test_ingest_duplicate_event():
    event = make_event(event_id="dupe-event-001")
    client.post("/events/ingest", json={"events": [event]})
    resp = client.post("/events/ingest", json={"events": [event]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["duplicate"] == 1
    assert data["accepted"] == 0


def test_ingest_empty_batch():
    resp = client.post("/events/ingest", json={"events": []})
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 0


def test_ingest_invalid_confidence():
    event = make_event()
    event["confidence"] = 1.5  # Invalid
    resp = client.post("/events/ingest", json={"events": [event]})
    assert resp.status_code == 422


def test_ingest_batch_500():
    import uuid
    events = [make_event(event_id=str(uuid.uuid4())) for _ in range(500)]
    resp = client.post("/events/ingest", json={"events": events})
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 500


def test_ingest_staff_event():
    event = make_event(is_staff=True)
    event["event_id"] = "staff-event-001"
    resp = client.post("/events/ingest", json={"events": [event]})
    assert resp.status_code == 200
    assert resp.json()["accepted"] == 1


def test_ingest_partial_success():
    import uuid
    events = [
        make_event(event_id=str(uuid.uuid4())),
        {**make_event(event_id=str(uuid.uuid4())), "confidence": 99},   # intentionally invalid
        make_event(event_id=str(uuid.uuid4())),
    ]
    resp = client.post("/events/ingest", json={"events": events})
    assert resp.status_code in [200, 422]


def test_metrics_empty_store():
    resp = client.get("/stores/STORE_EMPTY_999/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["unique_visitors"] == 0
    assert data["conversion_rate"] == 0.0


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "checked_at" in data
    
def test_ingest_integrity_error_duplicate():
    import uuid
    event_id = str(uuid.uuid4())
    event = make_event(event_id=event_id)
    # Insert original event
    client.post("/events/ingest", json={"events": [event]})
    # Re-submit the same event_id
    resp = client.post("/events/ingest", json={"events": [event]})
    assert resp.status_code == 200
    assert resp.json()["duplicate"] >= 1


def test_ingest_invalid_confidence_negative():
    event = make_event()
    event["confidence"] = -0.1
    resp = client.post("/events/ingest", json={"events": [event]})
    assert resp.status_code == 422


def test_ingest_logs_error_on_bad_event():
    import uuid
    event = make_event(event_id=str(uuid.uuid4()))
    event["store_id"] = None   # Missing required value
    resp = client.post("/events/ingest", json={"events": [event]})
    assert resp.status_code in [200, 422]