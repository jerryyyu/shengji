#!/usr/bin/env bash
# Policy-head training and search tests, both real engine modes (as ci_cwv_modes.sh).
# Covers value units, exploration tags and composer, soft/listwise targets, policy
# selection metrics, admit-then-select, exact resume and split binding.
set -euo pipefail
export SHENGJI_REQUIRE_VOIDS=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1

(env -u SHENGJI_FAST uv run python -B -m pytest -q --durations=10 tests/test_policy_*.py tests/test_exact_resume.py tests/test_runij_split_binding.py tests/test_screen_policy_arm.py tests/test_screen_deadline_child.py tests/test_search_policy.py tests/test_split_selector.py 2>&1 |
    sed -u 's/^/[pure] /') &
pure_pid=$!
(SHENGJI_FAST=1 uv run python -B -m pytest -q --durations=10 tests/test_policy_*.py tests/test_exact_resume.py tests/test_runij_split_binding.py tests/test_screen_policy_arm.py tests/test_screen_deadline_child.py tests/test_search_policy.py tests/test_split_selector.py 2>&1 |
    sed -u 's/^/[compiled] /') &
compiled_pid=$!

status=0
wait "$pure_pid" || status=1
wait "$compiled_pid" || status=1
exit "$status"
