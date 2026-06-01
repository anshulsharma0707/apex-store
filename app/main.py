import time
import uuid
import structlog
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from app.database import TransactionDB
from app.models import TransactionIngestRequest

from app.database import get_db, init_db
from app.models import (
    IngestRequest, IngestResponse,
    MetricsResponse, FunnelResponse,
    HeatmapResponse, HeatmapZone,
    AnomalyResponse, HealthResponse,
)
from app.ingestion import ingest_events
from app.metrics import get_store_metrics
from app.funnel import get_store_funnel
from app.anomalies import get_store_anomalies
from app.health import get_health
from app.database import EventDB
from sqlalchemy import func

logger = structlog.get_logger()

# ─── App Init ─────────────────────────────────────────────────
app = FastAPI(
    title="Apex Store Intelligence API",
    description="Real-time retail analytics from CCTV events",
    version="1.0.0",
)


@app.on_event("startup")
def startup():
    init_db()
    logger.info("api_started", version="1.0.0")


# ─── Middleware: Logging ───────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    trace_id = str(uuid.uuid4())
    start = time.time()
    response = await call_next(request)
    latency = round((time.time() - start) * 1000, 2)

    logger.info(
        "request",
        trace_id=trace_id,
        method=request.method,
        endpoint=request.url.path,
        status_code=response.status_code,
        latency_ms=latency,
    )
    return response


# ─── Error Handlers ───────────────────────────────────────────
@app.exception_handler(OperationalError)
async def db_error_handler(request: Request, exc: OperationalError):
    logger.error("database_unavailable", error=str(exc))
    return JSONResponse(
        status_code=503,
        content={
            "error": "DATABASE_UNAVAILABLE",
            "message": "Database is currently unavailable. Please try again.",
        }
    )

@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    logger.error("unhandled_error", error=str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_ERROR",
            "message": "An unexpected error occurred.",
        }
    )


# ─── Routes ───────────────────────────────────────────────────

@app.post("/events/ingest", response_model=IngestResponse)
def ingest(request: IngestRequest, db: Session = Depends(get_db)):
    if len(request.events) > 500:                         
        raise HTTPException(                               
            status_code=422,                               
            detail="Max 500 events per batch allowed",     
        )                                                  
    return ingest_events(request, db)


@app.get("/stores/{store_id}/metrics", response_model=MetricsResponse)
def metrics(store_id: str, db: Session = Depends(get_db)):
    return get_store_metrics(store_id, db)


@app.get("/stores/{store_id}/funnel", response_model=FunnelResponse)
def funnel(store_id: str, db: Session = Depends(get_db)):
    return get_store_funnel(store_id, db)


@app.get("/stores/{store_id}/heatmap", response_model=HeatmapResponse)
def heatmap(store_id: str, db: Session = Depends(get_db)):
    db_zones = (
        db.query(EventDB)
        .filter(
            EventDB.store_id == store_id,
            EventDB.is_staff == False,
            EventDB.event_type == "ZONE_DWELL",
            EventDB.zone_id != None,
        )
        .with_entities(
            EventDB.zone_id,
            func.count(EventDB.event_id).label("freq"),
            func.avg(EventDB.dwell_ms).label("avg_dwell"),
            func.count(func.distinct(EventDB.visitor_id)).label("sessions"),
        )
        .group_by(EventDB.zone_id)
        .all()
    )

    if not db_zones:
        return HeatmapResponse(store_id=store_id, zones=[])

    max_freq = max(z.freq for z in db_zones) or 1

    zones = [
        HeatmapZone(
            zone_id=z.zone_id,
            visit_frequency=z.freq,
            avg_dwell_ms=round(z.avg_dwell or 0, 2),
            normalized_score=round((z.freq / max_freq) * 100, 2),
            data_confidence=z.sessions >= 20,
        )
        for z in db_zones
    ]

    return HeatmapResponse(store_id=store_id, zones=zones)


@app.get("/stores/{store_id}/anomalies", response_model=AnomalyResponse)
def anomalies(store_id: str, db: Session = Depends(get_db)):
    return get_store_anomalies(store_id, db)


@app.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)):
    return get_health(db)

@app.post("/transactions/ingest")
def ingest_transactions(request: TransactionIngestRequest, db: Session = Depends(get_db)):
    from app.database import TransactionDB
    txn = TransactionDB(
        transaction_id=request.transaction_id,
        store_id=request.store_id,
        timestamp=request.timestamp,
        basket_value=request.basket_value_inr,
    )
    db.merge(txn)
    db.commit()
    return {"status": "ok", "transaction_id": request.transaction_id}