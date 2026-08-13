# Point-management census scripts

Read-only, manifest-pinned exploration tooling behind
`docs/proposals/point-management-census.md`. Every script validates the
frozen ordered manifest (content SHAs) before reading any input, iterates in
manifest order, derives seeds from stable decision identity, and emits
exactly one canonical JSON document on stdout — no files are written. No
script launches jobs or carries review/run authority.

Run from the repo root:

    uv run --project server python -B server/scripts/point_census/manifest.py check
    uv run --project server python -B server/scripts/point_census/e1_census.py
    uv run --project server python -B server/scripts/point_census/e5_feed_ground_truth.py
    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 uv run --project server \
        python -B server/scripts/point_census/p1_p2_rollout_probes.py
    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 uv run --frozen --project server \
        python -B server/scripts/point_census/e2_e3_search_objective.py

Rebuild the manifest only when the log population intentionally changes
(`manifest.py build --logs-dir logs > server/scripts/point_census/manifest.json`);
the committed manifest is the frozen population of record. Tests:
`server/tests/test_point_census.py` (fixtures cover tamper refusal,
classification, legality filtering, determinism, no implicit writes).
