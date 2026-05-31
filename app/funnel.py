from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import EventDB, TransactionDB
from app.models import FunnelResponse, FunnelStage
from datetime import datetime, timezone, timedelta


# ─── Get Conversion Funnel ────────────────────────────────────
def get_store_funnel(store_id: str, db: Session) -> FunnelResponse:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=365)

    # Base query — exclude staff
    base_q = db.query(EventDB).filter(
        EventDB.store_id == store_id,
        EventDB.is_staff == False,
        EventDB.timestamp >= window_start,
    )

    # ── Stage 1: Unique Visitors (ENTRY) ──────────────────────
    entry_visitors = (
        base_q
        .filter(EventDB.event_type == "ENTRY")
        .with_entities(func.distinct(EventDB.visitor_id))
        .all()
    )
    entry_visitors = set(v[0] for v in entry_visitors)
    entry_count = len(entry_visitors)

    # ── Stage 2: Zone Visit ───────────────────────────────────
    zone_visitors = (
        base_q
        .filter(EventDB.event_type.in_(["ZONE_ENTER", "ZONE_DWELL"]))
        .with_entities(func.distinct(EventDB.visitor_id))
        .all()
    )
    zone_visitors = set(v[0] for v in zone_visitors)
    # Only count visitors who also entered
    zone_visitors = zone_visitors & entry_visitors
    zone_count = len(zone_visitors)

    # ── Stage 3: Billing Queue ────────────────────────────────
    billing_visitors = (
        base_q
        .filter(
            EventDB.event_type.in_([
                "BILLING_QUEUE_JOIN",
                "ZONE_ENTER"
            ]),
            EventDB.zone_id.in_(["BILLING", "BILLING_COUNTER"]),
        )
        .with_entities(func.distinct(EventDB.visitor_id))
        .all()
    )
    billing_visitors = set(v[0] for v in billing_visitors)
    billing_visitors = billing_visitors & entry_visitors
    billing_count = len(billing_visitors)

    # ── Stage 4: Purchase ─────────────────────────────────────
    transactions = db.query(TransactionDB).filter(
        TransactionDB.store_id == store_id,
        TransactionDB.timestamp >= window_start,
    ).all()

    purchased_visitors = set()
    for txn in transactions:
        billing_window_start = txn.timestamp - timedelta(minutes=60)
        billing_v = (
            base_q
            .filter(
                EventDB.zone_id.in_(["BILLING", "BILLING_COUNTER"]),
                EventDB.timestamp >= billing_window_start,
                EventDB.timestamp <= txn.timestamp,
            )
            .with_entities(EventDB.visitor_id)
            .all()
        )
        for v in billing_v:
            purchased_visitors.add(v.visitor_id)

    purchased_visitors = purchased_visitors & entry_visitors
    purchase_count = len(purchased_visitors)

    # ── Calculate Dropoff % ───────────────────────────────────
    def dropoff(current: int, previous: int) -> float:
        if previous == 0:
            return 0.0
        return round((1 - current / previous) * 100, 2)

    stages = [
        FunnelStage(
            stage="Entry",
            count=entry_count,
            dropoff_pct=0.0,
        ),
        FunnelStage(
            stage="Zone Visit",
            count=zone_count,
            dropoff_pct=dropoff(zone_count, entry_count),
        ),
        FunnelStage(
            stage="Billing Queue",
            count=billing_count,
            dropoff_pct=dropoff(billing_count, zone_count),
        ),
        FunnelStage(
            stage="Purchase",
            count=purchase_count,
            dropoff_pct=dropoff(purchase_count, billing_count),
        ),
    ]

    return FunnelResponse(
        store_id=store_id,
        stages=stages,
        window_start=window_start,
        window_end=now,
    )