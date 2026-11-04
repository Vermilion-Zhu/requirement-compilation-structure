#!/usr/bin/env bash
# ARC-Bench starts the application through this script when it exists.
# It must prepare the app, start it on the injected HOST/PORT, and keep running.
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

# The runner injects PORT (and may inject HOST); defaults keep local runs working.
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-3000}"
echo "[deploy] HOST=${HOST} PORT=${PORT}"

# Skip a full reinstall when the compiler already installed this workspace;
# a missing workspace link means the tree is new or incomplete.
if [ -d node_modules/.bin ] && [ -f node_modules/@arc/backend/package.json ]; then
  echo "[deploy] Workspace dependencies already installed; skipping npm install"
else
  echo "[deploy] Installing frontend and backend workspace dependencies"
  npm install --include=dev --include=optional --no-audit --no-fund
fi

echo "[deploy] Building frontend and backend"
npm run build

echo "[deploy] Starting application"
exec npm run start
