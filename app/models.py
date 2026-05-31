from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
import uuid


# ─── Event Metadata ───────────────────────────────────────────
class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: int = 0


# ─── Main Event Schema ────────────────────────────────────────
class StoreEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: Literal[
        "ENTRY",
        "EXIT",
        "ZONE_ENTER",
        "ZONE_EXIT",
        "ZONE_DWELL",
        "BILLING_QUEUE_JOIN",
        "BILLING_QUEUE_ABANDON",
        "REENTRY",
    ]
    timestamp: datetime
    zone_id: Optional[str] = None
    dwell_ms: int = 0
    is_staff: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: EventMetadata = Field(default_factory=EventMetadata)


# ─── Ingest Request/Response ──────────────────────────────────
class IngestRequest(BaseModel):
    events: list[StoreEvent]


class IngestResponse(BaseModel):
    accepted: int
    rejected: int
    duplicate: int
    errors: list[dict] = []


# ─── Metrics Response ─────────────────────────────────────────
class ZoneDwell(BaseModel):
    zone_id: str
    avg_dwell_ms: float
    visit_count: int


class MetricsResponse(BaseModel):
    store_id: str
    unique_visitors: int
    conversion_rate: float
    avg_dwell_per_zone: list[ZoneDwell]
    queue_depth: int
    abandonment_rate: float
    window_start: datetime
    window_end: datetime


# ─── Funnel Response ──────────────────────────────────────────
class FunnelStage(BaseModel):
    stage: str
    count: int
    dropoff_pct: float


class FunnelResponse(BaseModel):
    store_id: str
    stages: list[FunnelStage]
    window_start: datetime
    window_end: datetime


# ─── Heatmap Response ─────────────────────────────────────────
class HeatmapZone(BaseModel):
    zone_id: str
    visit_frequency: float
    avg_dwell_ms: float
    normalized_score: float
    data_confidence: bool


class HeatmapResponse(BaseModel):
    store_id: str
    zones: list[HeatmapZone]


# ─── Anomaly Response ─────────────────────────────────────────
class Anomaly(BaseModel):
    anomaly_type: str
    severity: Literal["INFO", "WARN", "CRITICAL"]
    description: str
    suggested_action: str
    detected_at: datetime


class AnomalyResponse(BaseModel):
    store_id: str
    anomalies: list[Anomaly]


# ─── Health Response ──────────────────────────────────────────
class StoreHealth(BaseModel):
    store_id: str
    last_event_timestamp: Optional[datetime]
    status: Literal["OK", "STALE_FEED", "NO_DATA"]


class HealthResponse(BaseModel):
    status: str
    stores: list[StoreHealth]
    checked_at: datetime
    
# ─── Transaction Ingest Request ───────────────────────────────
class TransactionIngestRequest(BaseModel):
    store_id: str
    transaction_id: str
    timestamp: datetime
    basket_value_inr: float