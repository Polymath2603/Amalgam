#!/bin/bash
set -e
cd "$(dirname "$0")"
echo "=== Fast Test Suite ==="
python3 -m pytest backend/tests/ -q --tb=short -k "not add_turn_100 and not add_turn_concurrent and not uniqueness" 2>&1
echo "Exit code: $?"
