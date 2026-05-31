#!/bin/bash
set -e

DATA_DIR="./data/CCTV Footage"
LAYOUT="./data/store_layout.json"
OUTPUT_DIR="./data/events"
API_URL="http://localhost:8000"
MODEL="yolov8n.pt"

mkdir -p "$OUTPUT_DIR"

echo "🚀 Apex Store Intelligence Pipeline"

python -m pipeline.detect --video "$DATA_DIR/CAM 1.mp4" --store-id ST1008 --camera-id CAM_1 --layout "$LAYOUT" --output "$OUTPUT_DIR/ST1008_CAM_1.jsonl" --start-time "2026-04-10T10:00:00Z" --model "$MODEL"

python -m pipeline.detect --video "$DATA_DIR/CAM 2.mp4" --store-id ST1008 --camera-id CAM_2 --layout "$LAYOUT" --output "$OUTPUT_DIR/ST1008_CAM_2.jsonl" --start-time "2026-04-10T10:00:00Z" --model "$MODEL"

python -m pipeline.detect --video "$DATA_DIR/CAM 3.mp4" --store-id ST1008 --camera-id CAM_3 --layout "$LAYOUT" --output "$OUTPUT_DIR/ST1008_CAM_3.jsonl" --start-time "2026-04-10T10:00:00Z" --model "$MODEL"

python -m pipeline.detect --video "$DATA_DIR/CAM 4.mp4" --store-id ST1008 --camera-id CAM_4 --layout "$LAYOUT" --output "$OUTPUT_DIR/ST1008_CAM_4.jsonl" --start-time "2026-04-10T10:00:00Z" --model "$MODEL"

python -m pipeline.detect --video "$DATA_DIR/CAM 5.mp4" --store-id ST1008 --camera-id CAM_5 --layout "$LAYOUT" --output "$OUTPUT_DIR/ST1008_CAM_5.jsonl" --start-time "2026-04-10T10:00:00Z" --model "$MODEL"

echo "✅ All clips processed!"

for JSONL in "$OUTPUT_DIR"/*.jsonl; do
    python -c "
from pipeline.emit import load_events, push_events_to_api
events = load_events('$JSONL')
push_events_to_api(events, api_url='$API_URL')
"
done

echo "🎉 Pipeline complete!"