#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/legal-AI-infraestructure"
INPUT="${ROOT}/backups/benchmark-inputs/prompts-v2-20260812"
OUTPUT_NAME="${OUTPUT_NAME:-benchmark-1000-8192-v2}"
RUN_ID="${RUN_ID:-benchmark1000-8192-v2}"
START_CASE="${START_CASE:-1}"
LIMIT="${LIMIT:-1000}"

cd "${ROOT}"
mkdir -p "backups/benchmark-results/${OUTPUT_NAME}"

PYTHONPATH=apps/api/src python3 backups/rag_benchmark_v2.py \
  --prompts "${INPUT}/prompts" \
  --manifest "${INPUT}/manifest.json" \
  --output "backups/benchmark-results/${OUTPUT_NAME}" \
  --api-base-url http://127.0.0.1:8000 \
  --template-id c4c51e57-0d7c-44ab-9cec-317c698bc253 \
  --case-file-id 5784d3a0-d2d0-4397-8b54-fd1358dbd424 \
  --run-id "${RUN_ID}" \
  --start-case "${START_CASE}" \
  --limit "${LIMIT}" \
  --top-k 8 \
  --minimum-score 0.0 \
  --timeout 600 \
  2>&1 | tee "backups/benchmark-results/${OUTPUT_NAME}/runner.log"
