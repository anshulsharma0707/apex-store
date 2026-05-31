# Apex Store Intelligence — Design Choices

## Decision 1: Detection Model — YOLOv8n

### Options Considered

| Model     | Pros                                           | Cons                                       |
| --------- | ---------------------------------------------- | ------------------------------------------ |
| YOLOv8n   | Fast, accurate, easy setup, built-in ByteTrack | Smaller model — less accurate on occlusion |
| YOLOv8m   | Better accuracy                                | 3x slower — too slow for 1080p/15fps       |
| RT-DETR   | State of art accuracy                          | Complex setup, high GPU memory             |
| MediaPipe | Lightweight                                    | Poor accuracy on crowds                    |

### What AI Suggested

I asked Claude to compare detection models for retail CCTV at 1080p/15fps
on a CPU-constrained environment. Claude recommended YOLOv8n as the
starting point for the following reasons:

- Pre-trained on COCO dataset which includes person class (class 0)
- Built-in ByteTrack integration via `ultralytics` library
- Best speed/accuracy tradeoff for real-time retail use
- Active community — well documented edge cases

Claude also suggested considering RT-DETR for higher accuracy on
partially occluded persons but noted the setup complexity was not
justified for a 48-hour challenge.

Claude suggested dropping detections below 0.4 confidence threshold. I disagreed — I flag them with confidence field instead of dropping, because silent drops are worse than uncertain data in a retail analytics context

### What I Chose and Why

**YOLOv8n** — I agreed with Claude's reasoning. The key factor was
ByteTrack being built into the `ultralytics` library, which removed
the need to integrate a separate tracking library. For partial
occlusion cases in the billing clip, I handle degraded confidence
by flagging rather than dropping low-confidence detections —
this is more honest than suppressing uncertain results.

If I were productionising this, I would evaluate YOLOv8m or RT-DETR
on a representative held-out clip and make the model configurable
via environment variable.

---

## Decision 2: Event Schema Design

### Options Considered

**Option A — Flat schema**
All fields at top level. Simple to query but rigid — adding new
metadata fields requires schema migration.

**Option B — Nested metadata (chosen)**
Core fields flat, optional/extensible fields in `metadata` JSON.
More flexible — queue_depth, sku_zone, session_seq can evolve
without breaking existing consumers.

**Option C — Event sourcing with separate payload per event type**
Maximum type safety but complex — each event type has its own
Pydantic model. Overkill for a 48-hour challenge.

### What AI Suggested

Claude suggested Option B with a specific recommendation: keep
`queue_depth` in metadata rather than as a top-level field because
it is only populated for `BILLING_QUEUE_JOIN` events. Putting it
at the top level would mean it is `null` on 95% of events, which
is misleading. I agreed with this reasoning.

Claude also suggested adding `session_seq` as an ordinal counter
per visitor session. I had not included this initially — after
thinking about it, I agreed it is useful for debugging broken
tracking sequences and verifying session integrity.

### What I Chose and Why

**Option B** — nested metadata. The `metadata` JSON field gives us
flexibility to add new fields (e.g. `face_direction`, `cart_detected`)
without a database migration. The core query fields (store_id,
visitor_id, event_type, timestamp, zone_id) are top-level for
efficient indexing. I overrode Claude's suggestion to put
`confidence` inside metadata — I kept it top-level because every
event has a confidence value and it is used in scoring criteria.

---

## Decision 3: API Storage Engine

### Options Considered

| Option              | Pros                                            | Cons                                       |
| ------------------- | ----------------------------------------------- | ------------------------------------------ |
| SQLite              | Zero setup, simple                              | Not production-grade, no concurrent writes |
| PostgreSQL (chosen) | Production-grade, concurrent, good time queries | Requires Docker service                    |
| TimescaleDB         | Optimised for time-series                       | Complex setup, overkill                    |
| MongoDB             | Flexible schema                                 | Harder to query with JOINs for funnel      |

### What AI Suggested

Claude initially suggested SQLite for simplicity given the 48-hour
window. The reasoning was: SQLite has zero infrastructure overhead,
the dataset is small (5 stores × 3 cameras × 20 min), and the
scoring harness would work fine with it.

### What I Chose and Why

**PostgreSQL** — I overrode Claude's SQLite suggestion for the
following reasons:

1. The problem statement explicitly says "production-aware API"
2. The acceptance gate requires `docker compose up` — PostgreSQL
   fits naturally into the compose stack
3. Concurrent writes from multiple camera feeds would hit SQLite's
   write lock immediately in a real deployment
4. The funnel and metrics queries use window functions and GROUP BY
   that PostgreSQL handles more efficiently than SQLite

The tradeoff is added complexity in the Docker setup, but this is
minimal with the provided `docker-compose.yml`. I added health
checks on the PostgreSQL container so the API waits for the database
to be ready before starting.

For a true production deployment at 40 stores, I would evaluate
TimescaleDB for its time-series compression and continuous aggregates,
which would make the metrics queries significantly faster.
