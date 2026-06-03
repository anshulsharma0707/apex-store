from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models import StoreEvent, IngestRequest, IngestResponse
from app.database import EventDB
import structlog

logger = structlog.get_logger()


# Event Ingestion Logic
def ingest_events(request: IngestRequest, db: Session) -> IngestResponse:
    accepted = 0
    rejected = 0
    duplicate = 0
    errors = []

    for event in request.events:
        try:
            # Check confidence score range
            if event.confidence < 0.0 or event.confidence > 1.0:
                rejected += 1
                errors.append({
                    "event_id": event.event_id,
                    "reason": "Invalid confidence value"
                })
                continue

            # Skip if event already exists
            existing = db.query(EventDB).filter(
                EventDB.event_id == event.event_id
            ).first()

            if existing:
                duplicate += 1
                continue

            # Save event using a nested transaction
            with db.begin_nested():
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

            accepted += 1
            logger.info(
                "event_ingested",
                event_id=event.event_id,
                store_id=event.store_id,
                event_type=event.event_type,
            )

        except IntegrityError:
            duplicate += 1

        except Exception as e:
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

    db.commit()  # Commit all valid events
    return IngestResponse(
        accepted=accepted,
        rejected=rejected,
        duplicate=duplicate,
        errors=errors,
    )