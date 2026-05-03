#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ -f logs/server.pid ]; then
  pid="$(cat logs/server.pid)"
  if kill -0 "$pid" 2>/dev/null; then
    echo "running pid=$pid"
    exit 0
  fi
fi

echo "stopped"
