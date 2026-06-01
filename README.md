# Apex Store Intelligence

Real-time retail analytics pipeline — from raw CCTV footage to live store metrics.

Built for Apex Retail's physical stores to close the offline analytics gap.

---

## Quick Start (5 Commands)

```bash
# 1. Clone the repo
git clone
cd apex-store-intelligence

# 2. Copy environment variables
cp .env.example .env

# 3. Start API + PostgreSQL + Redis
docker compose up --build -d

# 4. Load sample data
python -c "
import requests, csv, uuid
from datetime import datetime, timezone
events = []
with open('data/pos_transactions.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        try:
            date_str = row['order_date'] + ' ' + row['order_time']
            ts = datetime.strptime(date_str, '%d-%m-%Y %H:%M:%S').replace(tzinfo=timezone.utc)
            events.append({'event_id': str(uuid.uuid4()), 'store_id': row['store_id'], 'camera_id': 'CAM_1', 'visitor_id': 'VIS_' + row['order_id'], 'event_type': 'ENTRY', 'timestamp': ts.strftime('%Y-%m-%dT%H:%M:%SZ'), 'zone_id': None, 'dwell_ms': 0, 'is_staff': False, 'confidence': 0.95, 'metadata': {'queue_depth': None, 'sku_zone': None, 'session_seq': 1}})
        except: pass
for i in range(0, len(events), 100):
    r = requests.post('http://localhost:8000/events/ingest', json={'events': events[i:i+100]})
    print(f'Batch {i//100+1}:', r.json()['accepted'], 'accepted')
"

# 5. Open live dashboard
python -m streamlit run dashboard/dashboard.py
```

API: http://localhost:8000
Dashboard: http://localhost:8501
API Docs: http://localhost:8000/docs

---

## Dataset

- **Store ID:** ST1008 (Brigade Road, Bangalore)
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
  --store-id ST1008 \
  --camera-id CAM_1 \
  --layout data/store_layout.json \
  --output data/events/ST1008_CAM_1.jsonl \
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
events = load_events('data/events/ST1008_CAM_1.jsonl')
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
- **Store ID:** ST1008
- **Cameras:** 5 cameras (Entry x2, Floor x2, Billing x1)
- **Dataset Date:** 10-04-2026

---

## North Star Metric

**Offline Store Conversion Rate**
Conversion Rate = Visitors who completed a purchase ÷ Total unique visitors
