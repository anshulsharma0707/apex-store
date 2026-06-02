# Apex Store Intelligence

Real-time retail analytics pipeline — from raw CCTV footage to live store metrics.

Built for Apex Retail's physical stores to close the offline analytics gap.

## Note on Sample Data

This repository includes small sample files for testing:

- `data/sample_events.jsonl` (200 schema reference events)
- `data/pos_transactions.csv` (sample POS transactions)
- `data/store_layout.json` (zone definitions, required by pipeline)

Full CCTV video dataset is NOT included per challenge rules.
To run the detection pipeline, place video files in `data/CCTV Footage/`
as described in the "Dataset" section below.

---

## Quick Start (5 Commands)

```bash
# 1. Clone the repo
git clone https://github.com/anshulsharma0707/apex-store.git
cd apex-store

# 2. Copy environment variables
cp .env.example .env

# 3. Start API + PostgreSQL + Redis
docker compose up --build -d

# 4. Seed STORE_BLR_002 sample data (required for acceptance gate)
python -c "
import json, uuid, requests
events = []
with open('data/sample_events.jsonl') as f:
    for line in f:
        line = line.strip()
        if line:
            e = json.loads(line)
            e['store_id'] = 'STORE_BLR_002'
            e['event_id'] = str(uuid.uuid4())
            events.append(e)
for i in range(0, len(events), 100):
    batch = events[i:i+100]
    r = requests.post('http://localhost:8000/events/ingest', json={'events': batch})
    print(f'Batch {i//100+1}:', r.json())
"

# 5. Verify the API
curl http://localhost:8000/stores/STORE_BLR_002/metrics
```

## Optional: Live Dashboard (Bonus)

```bash
python -m streamlit run dashboard/dashboard.py
```

API: http://localhost:8000
Dashboard: http://localhost:8501
API Docs: http://localhost:8000/docs

---

## Dataset

- **Store ID:** STORE_BLR_002 (Brigade Road, Bangalore)
- **Cameras:** CAM 1-5 (Entry, Floor, Billing)
- **POS Data:** pos_transactions.csv

Place dataset files in `data/` directory:
data/
├── CCTV Footage/
│ ├── CAM 1.mp4
│ ├── CAM 2.mp4
│ ├── CAM 3.mp4
│ ├── CAM 4.mp4
│ └── CAM 5.mp4
├── pos_transactions.csv
└── store_layout.json

---

## Running Detection Pipeline

### Process a single clip

```bash
python -m pipeline.detect \
  --video "data/CCTV Footage/CAM 1.mp4" \
  --store-id STORE_BLR_002 \
  --camera-id CAM_1 \
  --layout data/store_layout.json \
  --output data/events/STORE_BLR_002.jsonl \
  --start-time 2026-04-10T10:00:00Z
```

### Process all clips

```bash
bash pipeline/run.sh
```

### Push events to API

```bash
python -c "
from pipeline.emit import load_events, push_events_to_api
events = load_events('data/events/STORE_BLR_002_CAM_1.jsonl')
push_events_to_api(events, api_url='http://localhost:8000')
"
```

---

## API Endpoints

| Method | Endpoint               | Description                      |
| ------ | ---------------------- | -------------------------------- |
| POST   | /events/ingest         | Ingest batch of events (max 500) |
| GET    | /stores/{id}/metrics   | Live store metrics               |
| GET    | /stores/{id}/funnel    | Conversion funnel                |
| GET    | /stores/{id}/heatmap   | Zone heatmap                     |
| GET    | /stores/{id}/anomalies | Active anomalies                 |
| GET    | /health                | System health                    |

Full API docs: http://localhost:8000/docs

---

## Running Tests

```bash
pytest tests/ -v --cov=app --cov-report=term-missing
```

---

## Tech Stack

| Component     | Technology                |
| ------------- | ------------------------- |
| Detection     | YOLOv8 (ultralytics)      |
| Tracking      | Custom IoU + ReID Tracker |
| API Framework | FastAPI                   |
| Database      | PostgreSQL 16             |
| Cache         | Redis 7                   |
| Dashboard     | Streamlit                 |
| Containers    | Docker + Docker Compose   |
| Testing       | pytest                    |
| Logging       | structlog                 |

---

## Store Details

- **Store:** Brigade Road Bangalore
- **Store ID:** STORE_BLR_002
- **Cameras:** 5 cameras (Entry x2, Floor x2, Billing x1)
- **Dataset Date:** 10-04-2026

---

## North Star Metric

**Offline Store Conversion Rate**
Conversion Rate = Visitors who completed a purchase ÷ Total unique visitors
