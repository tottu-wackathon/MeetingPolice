#!/usr/bin/env bash
set -euo pipefail

echo "=== Step 1: git pull origin testing ==="
git pull --rebase origin new

echo "=== Step 2: start frontend ==="
./scripts/start_frontend.sh

echo "=== Step 3: start backend ==="
./scripts/start_backend.sh
