#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-18080}"

mkdir -p logs
if [ -f logs/server.pid ]; then
  old_pid="$(cat logs/server.pid)"
  if kill -0 "$old_pid" 2>/dev/null; then
    echo "already running pid=$old_pid port=$PORT"
    exit 0
  fi
fi
nohup ./start.sh > logs/server.log 2>&1 &
echo "$!" > logs/server.pid
echo "started pid=$(cat logs/server.pid) port=$PORT"
