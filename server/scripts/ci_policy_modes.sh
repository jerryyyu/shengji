#!/usr/bin/env bash
# Policy-head training and search tests, both real engine modes (as ci_cwv_modes.sh).
# Covers value units, exploration tags and composer, soft/listwise targets, policy
# selection metrics, admit-then-select, exact resume and split binding.
#
# Usage: ci_policy_modes.sh [both|pure|compiled]. CI runs one engine per job.
# Each mode runs as two concurrent pytest sessions, one CPU thread each, over
# disjoint halves of the selection: the screen deadline-child and shadow-arm
# modules (dominated by wall-clock child timeouts) and everything else. Every
# session's pipeline failure is preserved and every child is drained.
set -euo pipefail
export SHENGJI_REQUIRE_VOIDS=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1

engine="${1:-both}"
case "$engine" in
    both|pure|compiled) ;;
    *)
        echo "ci_policy_modes.sh: unknown engine '$engine' (want both, pure or compiled)" >&2
        exit 2
        ;;
esac

pids=()
if [ "$engine" != compiled ]; then
    (env -u SHENGJI_FAST uv run python -B -m pytest -q --durations=10 tests/test_policy_*.py tests/test_exact_resume.py tests/test_harvest_trajectory_pv.py tests/test_runij_split_binding.py tests/test_screen_policy_arm.py tests/test_search_policy.py tests/test_split_selector.py 2>&1 |
        sed -u 's/^/[pure 1] /') &
    pids+=($!)
    (env -u SHENGJI_FAST uv run python -B -m pytest -q --durations=10 tests/test_screen_deadline_child.py tests/test_screen_shadow_arm.py 2>&1 |
        sed -u 's/^/[pure 2] /') &
    pids+=($!)
fi
if [ "$engine" != pure ]; then
    (SHENGJI_FAST=1 uv run python -B -m pytest -q --durations=10 tests/test_policy_*.py tests/test_exact_resume.py tests/test_harvest_trajectory_pv.py tests/test_runij_split_binding.py tests/test_screen_policy_arm.py tests/test_search_policy.py tests/test_split_selector.py 2>&1 |
        sed -u 's/^/[compiled 1] /') &
    pids+=($!)
    (SHENGJI_FAST=1 uv run python -B -m pytest -q --durations=10 tests/test_screen_deadline_child.py tests/test_screen_shadow_arm.py 2>&1 |
        sed -u 's/^/[compiled 2] /') &
    pids+=($!)
fi

status=0
for pid in "${pids[@]}"; do
    wait "$pid" || status=1
done
exit "$status"
