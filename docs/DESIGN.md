# Apex Store Intelligence — System Design

## Overview

Apex Store Intelligence is a complete end-to-end pipeline that transforms
raw CCTV footage into actionable retail analytics. The system processes
video clips from physical stores, detects and tracks customers, emits
structured behavioural events, and exposes a real-time REST API for
store intelligence queries.

---

## Architecture

### Stage 1 — Detection Layer

The detection pipeline is built around three components:

- **YOLOv8n** — Object detection model. Detects all persons in each frame.
  Chosen for its balance of speed and accuracy at 1080p/15fps.
- **ReIDTracker** — Custom bounding-box trajectory tracker. Assigns a
  stable `visitor_id` across frames using IoU matching and centroid
  distance. Handles occlusion by maintaining lost track buffers.
- **StaffClassifier** — HSV color-based uniform detector. Classifies
  torso region of each detected person against known uniform color
  profiles. Results are cached per `visitor_id` for consistency.

### Stage 2 — Event Stream

Events are emitted as JSONL (one JSON object per line). This format was
chosen for its simplicity, replay-ability, and compatibility with both
batch and streaming ingestion patterns. Each event conforms to the
required schema with full metadata.

### Stage 3 — Intelligence API

Built with FastAPI for performance and automatic OpenAPI documentation.
PostgreSQL stores all events and POS transactions. Real-time metrics are
computed directly from database queries — no stale cache.

Key design decisions:

- **Idempotent ingestion** — events are deduplicated by `event_id`
- **Staff exclusion** — all metric queries filter `is_staff=False`
- **Session-based funnel** — funnel counts unique `visitor_id` per stage
- **POS correlation** — conversion computed via 5-minute billing window

### Stage 4 — Live Dashboard

Streamlit dashboard polls the API every 5 seconds and renders live
metrics, funnel, zone dwell chart, anomalies, and system health.

---

## Database Schema

### events table

| Column     | Type        | Description                        |
| ---------- | ----------- | ---------------------------------- |
| event_id   | VARCHAR PK  | UUID — globally unique             |
| store_id   | VARCHAR     | Store identifier                   |
| camera_id  | VARCHAR     | Camera source                      |
| visitor_id | VARCHAR     | Re-ID token                        |
| event_type | VARCHAR     | ENTRY / EXIT / ZONE_ENTER etc      |
| timestamp  | TIMESTAMPTZ | UTC event time                     |
| zone_id    | VARCHAR     | Zone name (nullable)               |
| dwell_ms   | INTEGER     | Dwell duration                     |
| is_staff   | BOOLEAN     | Staff flag                         |
| confidence | FLOAT       | Detection confidence               |
| metadata\_ | JSON        | Queue depth, sku_zone, session_seq |

### pos_transactions table

| Column         | Type        | Description            |
| -------------- | ----------- | ---------------------- |
| transaction_id | VARCHAR PK  | POS transaction ID     |
| store_id       | VARCHAR     | Store identifier       |
| timestamp      | TIMESTAMPTZ | Transaction time       |
| basket_value   | FLOAT       | Transaction amount INR |

---

## Edge Case Handling

| Edge Case         | Our Approach                                                                           |
| ----------------- | -------------------------------------------------------------------------------------- |
| Group entry       | YOLO detects individuals — each gets separate track and ENTRY event                    |
| Staff movement    | HSV uniform classifier marks is_staff=True — excluded from all metrics                 |
| Re-entry          | ReIDTracker maintains exited_visitors dict — same visitor within 5 min = REENTRY event |
| Partial occlusion | Low confidence detections flagged but not dropped — confidence field preserved         |
| Empty store       | All metric endpoints handle zero-visitor case — return 0.0 not null                    |
| Camera overlap    | visitor_id based deduplication — same person from two cameras gets one session         |
| Billing queue     | queue_depth tracked in metadata — BILLING_QUEUE_ABANDON emitted if no POS follows      |

---

## AI-Assisted Decisions

### 1. ReID Strategy — Trajectory vs Deep Learning

I consulted Claude to evaluate whether to use a deep learning Re-ID
model (OSNet/torchreid) or a trajectory-based approach. Claude suggested
that for a 48-hour challenge with realistic CCTV footage, a trajectory
approach using IoU + centroid distance would be more reliable to
implement correctly than a deep learning Re-ID model that requires
careful calibration. I agreed — the trajectory approach is
interpretable, debuggable, and sufficient for the edge cases in the
dataset. I would switch to OSNet for a production deployment with
multiple camera angles requiring cross-camera Re-ID.

### 2. Event Schema Design

Claude suggested adding a `session_seq` field to the metadata to track
the ordinal position of each event within a visitor session. I initially
overlooked this but agreed it adds value for debugging session integrity
and detecting broken tracking sequences.

### 3. Anomaly Severity Thresholds

I asked Claude what conversion drop thresholds would be meaningful for
retail analytics. Claude suggested 15% drop = WARN and 30% drop =
CRITICAL based on typical retail benchmarks. I agreed with this
framing but adjusted the queue spike thresholds based on the billing
area clip specifications (5 = WARN, 10 = CRITICAL) rather than
accepting Claude's initial suggestion of 3/8.

---

## Production Considerations

- All endpoints return structured errors — no raw stack traces
- Health endpoint detects STALE_FEED if no events for 10 minutes
- Docker Compose runs API + PostgreSQL + Redis as a single unit
- Structured JSON logging with trace_id on every request
- Test coverage >70% with edge case fixtures
