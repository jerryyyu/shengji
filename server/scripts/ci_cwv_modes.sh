#!/usr/bin/env bash
# Both real engine modes must pass. Each owns one CPU thread; run them
# concurrently on the two-core CI host instead of sharing one wall deadline
# sequentially. Preserve per-mode pipeline failures and drain both children.
set -euo pipefail
export SHENGJI_REQUIRE_VOIDS=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1

(env -u SHENGJI_FAST uv run python -B -m pytest -q tests/test_*cwv*.py 2>&1 |
    sed -u 's/^/[pure] /') &
pure_pid=$!
(SHENGJI_FAST=1 uv run python -B -m pytest -q tests/test_*cwv*.py 2>&1 |
    sed -u 's/^/[compiled] /') &
compiled_pid=$!

status=0
wait "$pure_pid" || status=1
wait "$compiled_pid" || status=1
exit "$status"
