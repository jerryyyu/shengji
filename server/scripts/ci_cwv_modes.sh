#!/usr/bin/env bash
# Both real engine modes must pass. Each owns one CPU thread; run them
# concurrently on the two-core CI host instead of sharing one wall deadline
# sequentially. Preserve per-mode pipeline failures and drain both children.
#
# Usage: ci_cwv_modes.sh [all|1|2]. Shard 1 runs exactly the SHARD1 modules,
# shard 2 every other selected module, so the two shards partition the
# selection and a new module lands in shard 2. Both shards keep the literal
# selection below and deselect the other shard's modules; a deselect that
# fails to match runs a module twice, never zero times.
set -euo pipefail
export SHENGJI_REQUIRE_VOIDS=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1

shard="${1:-all}"
# Balanced by measured per-file time in both engine modes.
SHARD1=(
    tests/test_cwv_archive_read.py
    tests/test_cwv_bury_belief_worlds.py
    tests/test_cwv_bury_boundaries.py
    tests/test_cwv_bury_diagnostic.py
    tests/test_cwv_bury_kitty_charge.py
    tests/test_cwv_bury_screen.py
    tests/test_cwv_bury_serving.py
    tests/test_cwv_bury_trajectory.py
    tests/test_cwv_bury_two_stage.py
    tests/test_cwv_bury_wide_value.py
    tests/test_cwv_candidate_batching.py
    tests/test_cwv_corpus_fixture_reuse.py
    tests/test_cwv_corrected_capped.py
    tests/test_cwv_corrected_rollout.py
    tests/test_cwv_deep8_warmstart_contract.py
    tests/test_cwv_double_shortlist_cost.py
    tests/test_cwv_duel.py
    tests/test_cwv_encoder_compat.py
    tests/test_cwv_init_deeper.py
    tests/test_cwv_leaf_policy_first_trick.py
    tests/test_cwv_loader_timing.py
    tests/test_cwv_numpy_evaluator.py
    tests/test_cwv_numpy_grid.py
    tests/test_cwv_oracle_soft.py
    tests/test_cwv_oracle_worlds.py
    tests/test_cwv_prior_registry.py
    tests/test_cwv_public_head_batching.py
    tests/test_cwv_public_history_serving.py
    tests/test_cwv_receipt_cache_index.py
    tests/test_cwv_residual_diagnostic.py
    tests/test_cwv_room_experiments.py
    tests/test_cwv_screen_fixed_banker.py
    tests/test_cwv_served_rank.py
    tests/test_cwv_serving_gate.py
    tests/test_cwv_serving_smoke.py
    tests/test_cwv_shortlist.py
    tests/test_cwv_shortlist_collection_identity.py
    tests/test_cwv_shortlist_cost.py
    tests/test_cwv_shortlist_recipe_identity.py
    tests/test_cwv_shortlist_scheduling.py
    tests/test_cwv_shortlist_screen.py
    tests/test_cwv_smoke_release45_bury.py
    tests/test_cwv_static_encoding.py
    tests/test_cwv_static_public.py
    tests/test_cwv_successor_reuse.py
    tests/test_cwv_train_policy_head.py
    tests/test_cwv_train_stage_timing.py
    tests/test_cwv_train_throughput.py
    tests/test_cwv_train_value_distill.py
    tests/test_cwv_twoply.py
    tests/test_cwv_v2_unseen.py
    tests/test_cwv_window_contract.py
    tests/test_vleaf_cwv.py
)

if [ "$shard" = 1 ] || [ "$shard" = 2 ]; then
    for module in "${SHARD1[@]}"; do
        if [ ! -f "$module" ]; then
            echo "ci_cwv_modes.sh: shard 1 lists missing module $module" >&2
            exit 2
        fi
    done
fi

deselect=()
case "$shard" in
    all) ;;
    1)
        for module in tests/test_*cwv*.py tests/test_encoder_bytes_golden.py; do
            case " ${SHARD1[*]} " in
                *" $module "*) ;;
                *) deselect+=(--deselect "$module::") ;;
            esac
        done
        ;;
    2)
        for module in "${SHARD1[@]}"; do
            deselect+=(--deselect "$module::")
        done
        ;;
    *)
        echo "ci_cwv_modes.sh: unknown shard '$shard' (want all, 1 or 2)" >&2
        exit 2
        ;;
esac

(env -u SHENGJI_FAST uv run python -B -m pytest -q --durations=20 tests/test_*cwv*.py tests/test_encoder_bytes_golden.py ${deselect[@]+"${deselect[@]}"} 2>&1 |
    sed -u 's/^/[pure] /') &
pure_pid=$!
(SHENGJI_FAST=1 uv run python -B -m pytest -q --durations=20 tests/test_*cwv*.py tests/test_encoder_bytes_golden.py ${deselect[@]+"${deselect[@]}"} 2>&1 |
    sed -u 's/^/[compiled] /') &
compiled_pid=$!

status=0
wait "$pure_pid" || status=1
wait "$compiled_pid" || status=1
exit "$status"
