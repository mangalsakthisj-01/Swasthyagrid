#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python -m uvicorn backend.api:app --host 0.0.0.0 --port "${PORT:-8000}"
