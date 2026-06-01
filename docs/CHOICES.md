# Apex Store Intelligence — Design Choices

## Decision 1: Detection Model — YOLOv8n

### What I Looked At

| Model | Why I Considered It | Why I Did Not Use It |
|---|---|---|
| YOLOv8n (chosen) | Used it in college, ByteTrack built-in | — |
| YOLOv8m | Better accuracy on occlusion | 3x slower, CPU bottleneck |
| RT-DETR | Best accuracy currently | Too complex to set up in 48hrs |
| MediaPipe | Very fast | Falls apart on crowded scenes |
| DeepSORT | Solid tracker | Needs separate Re-ID model — more moving parts |

### What I Actually Did

I went with YOLOv8n. The honest reason is I had used it before in
college and knew the API. But there was a more practical reason —
ByteTrack is built into ultralytics. I did not need to install or
integrate anything extra to get detection + tracking working together.
In a 48-hour window that matters.

Claude suggested switching to YOLOv8m for better accuracy on the
billing clip occlusion cases. I thought about it and decided it was
the wrong fix. The issue was not the model — it was that I was
silently dropping low-confidence detections. Once I stopped dropping
them and started flagging confidence instead, the billing clip results
improved without needing a heavier model.

If I had GPU and ground truth data showing a real miss rate problem,
I would revisit YOLOv8m or RT-DETR properly.

### Staff Detection

My first version was HSV color matching on the torso — works for
obvious uniform colors, breaks when a customer wears something similar.

I looked at three options:

| Option | What I Liked | What Stopped Me |
|---|---|---|
| Color-only | Simple, already written | Too many false positives |
| GPT-4V per frame | Would be very accurate | ~$18/store/day in API costs |
| Multi-signal (chosen) | No external cost, handles edge cases | Slightly more code |

Claude suggested GPT-4V with a simple yes/no prompt. I actually liked
the idea — it would work well. But $0.01 per image call at production
scale is not something you can justify. I noted it in the code as a
possible premium feature and built the multi-signal approach instead:
color (40%) + zone count (30%) + dwell time (30%).

---

## Decision 2: Event Schema

### Options

**Flat schema** — everything at top level. Simple to query. Problem:
queue_depth would be null on 95% of events, which is confusing for
anyone reading the data.

**Nested metadata JSON (chosen)** — core fields flat, optional fields
in a JSON column. Flexible, no migration needed to add new fields.

**One table per event type** — cleanest from a type safety perspective,
zero nulls. Too many tables and complex JOINs for funnel queries at
this scale.

### What Happened

I started with a flat schema. Claude pointed out the null-on-95%-of-rows
problem with queue_depth. That was a good catch — I moved optional
fields to metadata JSON.

The session_seq field was also Claude's suggestion. My first reaction
was that it was unnecessary overhead. Then I hit a bug where my tracker
was skipping frames and I had no way to know where. Added session_seq
that day. A jump from 3 to 7 in the sequence tells you exactly what
happened.

One place I pushed back: Claude suggested putting confidence inside
metadata too. I kept it top-level. Confidence is explicitly mentioned
in the scoring criteria — it needs to be filterable and queryable at
the database level. Burying it in JSON makes that harder. Knowing
the spec gave me better judgment than Claude on this one.

---

## Decision 3: PostgreSQL over SQLite

### Options

| Option | Good For | Not Good For |
|---|---|---|
| SQLite | Prototypes, single writer | Concurrent writes, production |
| PostgreSQL (chosen) | Production, concurrent streams | Slightly more setup |
| TimescaleDB | Heavy time-series at scale | Overkill here |
| MongoDB | Flexible schema | JOINs for funnel are painful |

### What Happened

Claude recommended SQLite. The argument was reasonable — small dataset,
zero setup overhead, works fine for the tests. For a pure prototype I
would agree.

I overrode it for two reasons.

First, the spec says "production-aware API." Using SQLite directly
contradicts that even if it passes every test.

Second, think about scale: 40 stores × 5 cameras = 200 concurrent
event streams pushing to the same database. SQLite serializes all
writes through a single lock. The first time two cameras try to write
at the same moment, one waits. At 200 streams that becomes a real
problem fast.

With PostgreSQL the answer to "what breaks first at 40 stores?" is
"connection pool exhaustion — add PgBouncer." With SQLite the answer
is "the write lock — rewrite the storage layer." One is an ops fix,
the other is an architecture change. I wanted to be on the right side
of that question.

---

## Decision 4: Redis Caching on Metrics Endpoint

### Options

| Option | Good For | Not Good For |
|---|---|---|
| No caching | Simple, always fresh data | Slow at scale — DB hit every request |
| Redis 30s TTL (chosen) | Fast repeat queries, production-ready | Slight staleness acceptable |
| In-memory cache | Zero infra | Dies on restart, not shared across instances |
| PostgreSQL materialized views | Very fast reads | Complex to refresh, not real-time |

### What Happened

The metrics endpoint was recomputing everything from scratch on every
request — scanning all events, correlating POS transactions, computing
zone averages. At 40 stores with a dashboard polling every 5 seconds,
that is 8 DB queries per second minimum just for metrics.

I added a 30-second Redis cache on the metrics endpoint. First call
hits the database and stores the result. Every subsequent call within
30 seconds returns from Redis directly.

Measured result on the running system:
- First call (DB): 186ms
- Second call (Redis cache): 49ms — 4x faster

I chose 30 seconds as the TTL deliberately. Metrics are not
tick-by-tick data — a 30-second window is acceptable for a retail
dashboard. Queue depth and anomalies are not cached because those
need to be real-time.

One thing I added that Claude did not suggest: graceful degradation.
If Redis is unavailable, `cache_get` and `cache_set` both silently
return None and the API falls back to DB. The service never goes down
because of a cache failure.