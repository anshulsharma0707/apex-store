from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import EventDB, TransactionDB
from app.models import AnomalyResponse, Anomaly
from app.metrics import parse_metadata
from datetime import datetime, timezone, timedelta


# Anomaly Detection
def get_store_anomalies(store_id: str, db: Session) -> AnomalyResponse:
    now          = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=24)
    anomalies    = []

    # Customer events only
    base_q = db.query(EventDB).filter(
        EventDB.store_id  == store_id,
        EventDB.is_staff  == False,
        EventDB.timestamp >= window_start,
    )

    # Queue Spike Detection
    latest_queue = (
        base_q
        .filter(EventDB.event_type == "BILLING_QUEUE_JOIN")
        .order_by(EventDB.timestamp.desc())
        .first()
    )

    if latest_queue:
        meta        = parse_metadata(latest_queue.metadata_)
        queue_depth = meta.get("queue_depth", 0) or 0

        if queue_depth >= 10:
            anomalies.append(Anomaly(
                anomaly_type="BILLING_QUEUE_SPIKE",
                severity="CRITICAL",
                description=f"Queue depth is {queue_depth} — critically high.",
                suggested_action="Open additional billing counters immediately.",
                detected_at=now,
            ))
        elif queue_depth >= 5:
            anomalies.append(Anomaly(
                anomaly_type="BILLING_QUEUE_SPIKE",
                severity="WARN",
                description=f"Queue depth is {queue_depth} — above normal.",
                suggested_action="Alert floor staff to assist at billing.",
                detected_at=now,
            ))

    # Conversion Drop Detection
    # Compare current performance with weekly average
    today_start = now - timedelta(hours=24)
    week_start  = now - timedelta(days=7)

    today_visitors = (
        base_q
        .filter(EventDB.event_type == "ENTRY")
        .with_entities(func.count(func.distinct(EventDB.visitor_id)))
        .scalar() or 0
    )

    today_txns = db.query(TransactionDB).filter(
        TransactionDB.store_id  == store_id,
        TransactionDB.timestamp >= today_start,
    ).count()

    week_visitors = (
        db.query(EventDB)
        .filter(
            EventDB.store_id   == store_id,
            EventDB.is_staff   == False,
            EventDB.event_type == "ENTRY",
            EventDB.timestamp  >= week_start,
            EventDB.timestamp  < today_start,
        )
        .with_entities(func.count(func.distinct(EventDB.visitor_id)))
        .scalar() or 0
    )

    week_txns = db.query(TransactionDB).filter(
        TransactionDB.store_id  == store_id,
        TransactionDB.timestamp >= week_start,
        TransactionDB.timestamp < today_start,
    ).count()

    today_conv = today_txns / today_visitors if today_visitors > 0 else 0
    week_conv  = week_txns  / week_visitors  if week_visitors  > 0 else 0

    if week_conv > 0:
        drop_pct = ((week_conv - today_conv) / week_conv) * 100
        if drop_pct >= 30:
            anomalies.append(Anomaly(
                anomaly_type="CONVERSION_DROP",
                severity="CRITICAL",
                description=f"Conversion rate dropped {round(drop_pct, 1)}% vs 7-day average.",
                suggested_action="Review floor layout and staff positioning urgently.",
                detected_at=now,
            ))
        elif drop_pct >= 15:
            anomalies.append(Anomaly(
                anomaly_type="CONVERSION_DROP",
                severity="WARN",
                description=f"Conversion rate dropped {round(drop_pct, 1)}% vs 7-day average.",
                suggested_action="Check if any promotions are running. Review staff coverage.",
                detected_at=now,
            ))

    # Dead Zone Detection
    # Identify inactive zones
    thirty_min_ago = now - timedelta(minutes=30)

    active_zones = (
        base_q
        .filter(
            EventDB.event_type == "ZONE_ENTER",
            EventDB.timestamp  >= thirty_min_ago,
        )
        .with_entities(func.distinct(EventDB.zone_id))
        .all()
    )
    active_zone_ids = {z[0] for z in active_zones if z[0]}

    all_zones = (
        base_q
        .filter(EventDB.event_type == "ZONE_ENTER")
        .with_entities(func.distinct(EventDB.zone_id))
        .all()
    )
    all_zone_ids = {z[0] for z in all_zones if z[0]}

    dead_zones = all_zone_ids - active_zone_ids
    for zone in dead_zones:
        anomalies.append(Anomaly(
            anomaly_type="DEAD_ZONE",
            severity="INFO",
            description=f"Zone '{zone}' has had no visitor activity in the last 30 minutes.",
            suggested_action=f"Check if zone '{zone}' display or signage needs attention.",
            detected_at=now,
        ))

    return AnomalyResponse(
        store_id=store_id,
        anomalies=anomalies,
    )