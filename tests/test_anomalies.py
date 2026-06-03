

import pytest
import uuid
from fastapi.testclient import TestClient
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import Base, get_db, EventDB, TransactionDB

# Test Database Setup
TEST_DB_URL = "sqlite:///./test_anomalies.db"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False}
)
TestSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=test_engine
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
STORE = "STORE_BLR_002"


# Helpers
def insert_event(db, visitor_id, event_type, zone_id=None,
                 is_staff=False, metadata=None, ts=None):
    event = EventDB(
        event_id   = str(uuid.uuid4()),
        store_id   = STORE,
        camera_id  = "CAM_ENTRY_01",
        visitor_id = visitor_id,
        event_type = event_type,
        timestamp  = ts or datetime.now(timezone.utc),
        zone_id    = zone_id,
        dwell_ms   = 0,
        is_staff   = is_staff,
        confidence = 0.9,
        metadata_  = metadata or {},
    )
    db.add(event)
    db.commit()


def insert_transaction(db, ts=None):
    txn = TransactionDB(
        transaction_id = str(uuid.uuid4()),
        store_id       = STORE,
        timestamp      = ts or datetime.now(timezone.utc),
        basket_value   = 1000.0,
    )
    db.add(txn)
    db.commit()


# Test Cases
def test_no_anomalies_empty_store():
    resp = client.get(f"/stores/{STORE}/anomalies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["anomalies"] == []


def test_queue_spike_warn():
    db = TestSessionLocal()
    insert_event(db, "VIS_001", "BILLING_QUEUE_JOIN",
                 metadata={"queue_depth": 6})
    db.close()

    resp = client.get(f"/stores/{STORE}/anomalies")
    assert resp.status_code == 200
    anomalies = resp.json()["anomalies"]
    queue_anomaly = next(
        (a for a in anomalies if a["anomaly_type"] == "BILLING_QUEUE_SPIKE"), None
    )
    assert queue_anomaly is not None
    assert queue_anomaly["severity"] == "WARN"


def test_queue_spike_critical():
    db = TestSessionLocal()
    insert_event(db, "VIS_001", "BILLING_QUEUE_JOIN",
                 metadata={"queue_depth": 12})
    db.close()

    resp = client.get(f"/stores/{STORE}/anomalies")
    anomalies = resp.json()["anomalies"]
    queue_anomaly = next(
        (a for a in anomalies if a["anomaly_type"] == "BILLING_QUEUE_SPIKE"), None
    )
    assert queue_anomaly is not None
    assert queue_anomaly["severity"] == "CRITICAL"


def test_dead_zone_detection():
    db = TestSessionLocal()
    # Zone visited yesterday but not in last 30 min
    old_ts = datetime.now(timezone.utc) - timedelta(hours=2)
    insert_event(db, "VIS_001", "ZONE_ENTER",
                 zone_id="SKINCARE", ts=old_ts)
    db.close()

    resp = client.get(f"/stores/{STORE}/anomalies")
    anomalies = resp.json()["anomalies"]
    dead_zone = next(
        (a for a in anomalies if a["anomaly_type"] == "DEAD_ZONE"), None
    )
    assert dead_zone is not None
    assert dead_zone["severity"] == "INFO"
    assert "SKINCARE" in dead_zone["description"]


def test_conversion_drop_warn():
    db = TestSessionLocal()
    now = datetime.now(timezone.utc)

    # Last 7 days — good conversion (10 visitors, 5 purchases)
    for i in range(10):
        ts = now - timedelta(days=3)
        insert_event(db, f"VIS_OLD_{i}", "ENTRY", ts=ts)
    for i in range(5):
        ts = now - timedelta(days=3)
        insert_transaction(db, ts=ts)

    # Today — bad conversion (10 visitors, 1 purchase)
    for i in range(10):
        insert_event(db, f"VIS_NEW_{i}", "ENTRY")
    insert_transaction(db)
    db.close()

    resp = client.get(f"/stores/{STORE}/anomalies")
    anomalies = resp.json()["anomalies"]
    conv_drop = next(
        (a for a in anomalies if a["anomaly_type"] == "CONVERSION_DROP"), None
    )
    assert conv_drop is not None
    assert conv_drop["severity"] in ["WARN", "CRITICAL"]


def test_anomaly_has_suggested_action():
    db = TestSessionLocal()
    insert_event(db, "VIS_001", "BILLING_QUEUE_JOIN",
                 metadata={"queue_depth": 15})
    db.close()

    resp = client.get(f"/stores/{STORE}/anomalies")
    anomalies = resp.json()["anomalies"]
    for a in anomalies:
        assert "suggested_action" in a
        assert len(a["suggested_action"]) > 0