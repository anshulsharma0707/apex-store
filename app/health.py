from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import EventDB
from app.models import HealthResponse, StoreHealth
from datetime import datetime, timezone, timedelta


# ─── Health Check ─────────────────────────────────────────────
def get_health(db: Session) -> HealthResponse:
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(minutes=10)

    # Get all unique store IDs
    stores = (
        db.query(func.distinct(EventDB.store_id))
        .all()
    )
    store_ids = [s[0] for s in stores]

    store_healths = []

    for store_id in store_ids:
        # Get last event timestamp for this store
        last_event = (
            db.query(EventDB)
            .filter(EventDB.store_id == store_id)
            .order_by(EventDB.timestamp.desc())
            .first()
        )

        if not last_event:
            status = "NO_DATA"
            last_ts = None
        elif last_event.timestamp < stale_threshold:
            status = "STALE_FEED"
            last_ts = last_event.timestamp
        else:
            status = "OK"
            last_ts = last_event.timestamp

        store_healths.append(StoreHealth(
            store_id=store_id,
            last_event_timestamp=last_ts,
            status=status,
        ))

    # Overall status
    statuses = [s.status for s in store_healths]
    if "STALE_FEED" in statuses:
        overall = "DEGRADED"
    elif "NO_DATA" in statuses:
        overall = "NO_DATA"
    else:
        overall = "OK"

    return HealthResponse(
        status=overall,
        stores=store_healths,
        checked_at=now,
    )