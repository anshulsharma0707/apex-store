from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models import StoreEvent, IngestRequest, IngestResponse
from app.database import EventDB
import structlog

logger = structlog.get_logger()


# ─── Ingest Events ────────────────────────────────────────────
def ingest_events(request: IngestRequest, db: Session) -> IngestResponse:
    accepted = 0
    rejected = 0
    duplicate = 0
    errors = []

    for event in request.events:
        try:
            # Validate confidence
            if event.confidence < 0.0 or event.confidence > 1.0:
                rejected += 1
                errors.append({
                    "event_id": event.event_id,
                    "reason": "Invalid confidence value"
                })
                continue

            # Check duplicate by event_id (idempotent)
            existing = db.query(EventDB).filter(
                EventDB.event_id == event.event_id
            ).first()

            if existing:
                duplicate += 1
                continue

            # Save to DB
            db_event = EventDB(
                event_id   = event.event_id,
                store_id   = event.store_id,
                camera_id  = event.camera_id,
                visitor_id = event.visitor_id,
                event_type = event.event_type,
                timestamp  = event.timestamp,
                zone_id    = event.zone_id,
                dwell_ms   = event.dwell_ms,
                is_staff   = event.is_staff,
                confidence = event.confidence,
                metadata_  = event.metadata.model_dump(),
            )

            db.add(db_event)
            db.commit()
            accepted += 1

            logger.info(
                "event_ingested",
                event_id=event.event_id,
                store_id=event.store_id,
                event_type=event.event_type,
            )

        except IntegrityError:
            db.rollback()
            duplicate += 1

        except Exception as e:
            db.rollback()
            rejected += 1
            errors.append({
                "event_id": event.event_id,
                "reason": str(e)
            })
            logger.error(
                "event_ingest_failed",
                event_id=event.event_id,
                error=str(e)
            )

    return IngestResponse(
        accepted=accepted,
        rejected=rejected,
        duplicate=duplicate,
        errors=errors,
    )