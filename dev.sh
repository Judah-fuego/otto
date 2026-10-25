#!/usr/bin/env bash
# API on :8000, web console on :3000. Ctrl-C stops both.
# OTTO_ALERTS=mock ./dev.sh pins the scripted demo alerts.
set -euo pipefail
cd "$(dirname "$0")"

[ -d web/node_modules ] || (cd web && npm install)

.venv/bin/uvicorn app.server:app --port 8000 --reload --reload-dir app --reload-dir voyage &
API=$!
trap 'kill $API 2>/dev/null' EXIT

cd web && npm run dev
