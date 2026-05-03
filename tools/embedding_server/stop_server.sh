#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ -f logs/server.pid ]; then
  pid="$(cat logs/server.pid)"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 60); do
      if ! kill -0 "$pid" 2>/dev/null; then
        rm -f logs/server.pid
        echo "stopped pid=$pid"
        exit 0
      fi
      sleep 1
    done
    kill -9 "$pid" 2>/dev/null || true
    rm -f logs/server.pid
    echo "force stopped pid=$pid"
    exit 0
  fi
fi

pkill -f "uvicorn app:app" 2>/dev/null || true
rm -f logs/server.pid
echo "not running"
