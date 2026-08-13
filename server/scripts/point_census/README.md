# Point-management census scripts

Read-only exploration tooling behind `docs/proposals/point-management-census.md`.
Replays logged human games (`logs/*.jsonl`) and compares human decisions with
the heuristic and production MC policies. No script here launches jobs,
mutates state outside its own stdout, or carries any review/run authority.

Run from the repo root:

    uv run --project server python -B server/scripts/point_census/e1_census.py
    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 uv run --project server \
        python -B server/scripts/point_census/e2_e3_search_objective.py
    uv run --project server python -B server/scripts/point_census/e5_feed_ground_truth.py
    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 uv run --project server \
        python -B server/scripts/point_census/p1_p2_rollout_probes.py

E1 and E5 are pure-python (seconds). E2/E3 and P1/P2 run production MC
decisions (~0.5 s each compiled; a few minutes total).
