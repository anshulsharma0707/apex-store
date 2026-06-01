# Apex Store Intelligence — System Design

## Overview

I am a full-stack AI engineer with about a year of experience. I have
built APIs and worked with ML models, but this was my first time building
a CV pipeline that goes all the way from raw video to a live API. I had
used YOLO once in a college project, so I was not starting from zero —
but retail CCTV with re-entry, occlusion, and staff detection was new.

My approach was to get something working end-to-end first, then improve
each layer. The north star I kept returning to:

**Conversion Rate = Visitors who purchased ÷ Total unique visitors**

If a design decision did not improve this number or make it more
actionable, I deprioritised it.

---

## Architecture

Raw CCTV Clips
↓
Detection Layer (YOLOv8n + ByteTrack + ReIDTracker)
↓
Structured Events (JSONL)
↓
Intelligence API (FastAPI + PostgreSQL)
↓
Live Dashboard (Streamlit)

---

## Stage 1 — Detection Layer

### YOLOv8n

I went with YOLOv8n because I had used it before and knew the API.
What I did not expect was that ByteTrack is built directly into
ultralytics — that saved me a lot of integration time I would have
spent on a separate tracking library.

One thing I changed mid-build: I was initially filtering out detections
below 0.5 confidence. Then I noticed I was missing people in the billing
area when they were partially behind displays. I stopped dropping them
and started flagging confidence instead. The downstream consumer can
decide what threshold works — the pipeline should not hide uncertainty.

### ReIDTracker

Re-entry was the hardest problem here. My first version just checked
if a visitor_id had been seen before — but that broke when the same
person left and came back. I needed a way to recognise them.

I ended up storing the exit time and last known centroid for every person
who left the frame. When a new detection appears, I check if it is
spatially close to a recent exit within 5 minutes. If yes — REENTRY
event. If no — new ENTRY.

I initially only matched by time window (Claude's suggestion), but
realised that would fail if two different people exited from opposite
ends and re-entered. Adding centroid proximity fixed that case.

### StaffClassifier

My first version was just HSV color matching on the torso — check if
the person is wearing a uniform color. It worked but had false positives
when customers wore similar colors.

I improved it to combine three signals:

- Color match on torso region (40%)
- Number of zones visited — staff moves through everything (30%)
- Average dwell per zone — staff does not linger, customers do (30%)

I looked at using GPT-4V for this — it would be more accurate. But
at roughly $0.01 per image call, it would cost around $18 per store
per day. Not something you can run in production. Multi-signal was
the practical choice.

---

## Stage 2 — Event Stream

I went with JSONL files rather than writing directly to the database
from the pipeline. The main reason: if the API is down when I run
the pipeline, I do not lose data — I just replay the file later.

The `session_seq` field in metadata was something I almost skipped.
Then while debugging a tracking issue, I wished I had it — a jump
from seq 3 to seq 7 tells you exactly where the pipeline broke.
Added it after that.

---

## Stage 3 — Intelligence API

FastAPI because I have used it before and the auto-generated docs
are genuinely useful when testing endpoints manually.

The POS correlation was an interesting problem — there is no customer_id
in the transaction data. I correlate by time window: if a visitor was
in the BILLING zone in the 5 minutes before a transaction, they count
as converted. 5 minutes felt reasonable for a retail checkout.

I got idempotency wrong the first time — I was not deduplicating by
event_id and replaying a batch created duplicates. Fixed it to check
event_id before insert. Tests verify this now.

---

## Stage 4 — Live Dashboard

Built this last, after the API was solid. Streamlit was fast to build
with. The 5-second auto-refresh polls the live API — when new events
come in, the dashboard updates in real time. That was important to me
as proof the pipeline and API are actually connected.

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

## Edge Cases

| Edge Case         | How I Handled It                                         |
| ----------------- | -------------------------------------------------------- |
| Group entry       | YOLO detects individuals — 3 people = 3 ENTRY events     |
| Staff movement    | Multi-signal: color + zone count + dwell time            |
| Re-entry          | Centroid proximity + time window — REENTRY within 5 min  |
| Partial occlusion | Flag confidence, never drop — consumer decides threshold |
| Empty store       | All endpoints return 0.0 not null                        |
| Camera overlap    | visitor_id dedup — same person = one session             |
| Billing queue     | ABANDON emitted if visitor leaves billing with no POS    |
| Zero purchases    | Explicit division by zero handling — returns 0.0         |

---

## Where AI Helped and Where I Disagreed

**ReID approach** — Claude suggested trajectory-based over OSNet.
I agreed, but extended it with centroid proximity which Claude had
not included. Time-window alone would break in edge cases.

**session_seq field** — Claude suggested it. I initially skipped it,
added it after running into a debugging situation where I needed it.
Good suggestion in hindsight.

**confidence in metadata** — Claude suggested this. I kept it
top-level because it is explicitly in the scoring criteria and
needs to be queryable at DB level. JSON fields are not efficiently
indexable in PostgreSQL without extra setup.

**Anomaly thresholds** — Claude suggested 3/8 for queue spike.
I watched the billing clip and saw the queue naturally hits 5-6
during peak. Claude's threshold would have been noisy. I set 5/10.

---

## What I Would Improve With More Time

- Better Re-ID using OSNet for cross-camera tracking
- Staff classifier trained on labeled uniform images
- Redis caching on metrics endpoints for high-traffic stores
- PgBouncer for connection pooling at 40+ store scale
- Prometheus + Grafana for production monitoring
