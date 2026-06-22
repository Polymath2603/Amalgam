#!/bin/bash
set -e
cd "$(dirname "$0")"
echo "=== Slow Test Suite ==="
python3 -m pytest backend/tests/ -v --tb=short -k "add_turn_100 or add_turn_concurrent or uniqueness" 2>&1
echo "Exit code: $?"
