import json
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from app.database import EventDB, TransactionDB
from app.models import MetricsResponse, ZoneDwell
from app.cache import cache_get, cache_set
from datetime import datetime, timezone, timedelta


# Helper Function
def parse_metadata(metadata_) -> dict:
    if not metadata_:
        return {}
    if isinstance(metadata_, dict):
        return metadata_
    if isinstance(metadata_, str):
        try:
            return json.loads(metadata_)
        except Exception:
            return {}
    return {}


# Store Metrics
def get_store_metrics(store_id: str, db: Session) -> MetricsResponse:
    # Check Cache
    cache_key = f"metrics:{store_id}"
    cached = cache_get(cache_key)
    if cached:
        return MetricsResponse(**cached)

    now          = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=24)

    # Base query for customer events
    base_q = db.query(EventDB).filter(
        EventDB.store_id  == store_id,
        EventDB.is_staff  == False,
        EventDB.timestamp >= window_start,
    )

    # Unique Visitors
    unique_visitors = (
        base_q
        .filter(EventDB.event_type == "ENTRY")
        .with_entities(func.count(func.distinct(EventDB.visitor_id)))
        .scalar() or 0
    )

    # Conversion Rate
    transactions = db.query(TransactionDB).filter(
        TransactionDB.store_id  == store_id,
        TransactionDB.timestamp >= window_start,
    ).all()

    converted_visitors = set()
    for txn in transactions:
        billing_window_start = txn.timestamp - timedelta(minutes=5)
        billing_visitors = (
            base_q
            .filter(
                EventDB.zone_id.in_(["BILLING", "BILLING_COUNTER"]),
                EventDB.timestamp >= billing_window_start,
                EventDB.timestamp <= txn.timestamp,
            )
            .with_entities(EventDB.visitor_id)
            .all()
        )
        for v in billing_visitors:
            converted_visitors.add(v.visitor_id)

    conversion_rate = (
        round(len(converted_visitors) / unique_visitors, 4)
        if unique_visitors > 0 else 0.0
    )

    # Average Dwell Time Per Zone
    zone_dwells = (
        base_q
        .filter(
            EventDB.event_type == "ZONE_DWELL",
            EventDB.zone_id    != None,
        )
        .with_entities(
            EventDB.zone_id,
            func.avg(EventDB.dwell_ms).label("avg_dwell"),
            func.count(EventDB.event_id).label("visit_count"),
        )
        .group_by(EventDB.zone_id)
        .all()
    )

    avg_dwell_per_zone = [
        ZoneDwell(
            zone_id=z.zone_id,
            avg_dwell_ms=round(z.avg_dwell or 0, 2),
            visit_count=z.visit_count,
        )
        for z in zone_dwells
    ]

    # Queue Depth
    latest_queue = (
        base_q
        .filter(EventDB.event_type == "BILLING_QUEUE_JOIN")
        .order_by(EventDB.timestamp.desc())
        .first()
    )

    queue_depth = 0
    if latest_queue:
        meta = parse_metadata(latest_queue.metadata_)
        queue_depth = meta.get("queue_depth", 0) or 0

    # Queue Abandonment Rate
    total_queue_joins = (
        base_q
        .filter(EventDB.event_type == "BILLING_QUEUE_JOIN")
        .count()
    )
    total_abandons = (
        base_q
        .filter(EventDB.event_type == "BILLING_QUEUE_ABANDON")
        .count()
    )
    abandonment_rate = (
        round(total_abandons / total_queue_joins, 4)
        if total_queue_joins > 0 else 0.0
    )

    result = MetricsResponse(
        store_id=store_id,
        unique_visitors=unique_visitors,
        conversion_rate=conversion_rate,
        avg_dwell_per_zone=avg_dwell_per_zone,
        queue_depth=queue_depth,
        abandonment_rate=abandonment_rate,
        window_start=window_start,
        window_end=now,
    )

    # Store Result In Cache
    cache_set(cache_key, result.model_dump())

    return result