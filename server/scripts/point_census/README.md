# Point-management census scripts

Read-only, manifest-pinned exploration tooling behind
`docs/proposals/point-management-census.md`. Every script validates the
frozen ordered manifest (content SHAs) before reading any input, iterates in
manifest order, derives seeds from stable decision identity, and emits
exactly one canonical JSON document on stdout — no files are written. No
script launches jobs or carries review/run authority.

The human corpus is private and intentionally absent from a fresh checkout.
The committed manifest is its complete ordered hash boundary: external and
internal SHA-256
`8d6cc27f20f8b8953447b8c4f89ba81cccf1bf53bc66521438633a747106aeeb`.
Point `POINT_CENSUS_LOGS` at an authorized local copy. A fresh checkout can
run the synthetic tests, but cannot reproduce human-data aggregates without
those private bytes.

Run from the repo root:

    POINT_CENSUS_LOGS=/path/to/private/logs
    POINT_CENSUS_MANIFEST_SHA=8d6cc27f20f8b8953447b8c4f89ba81cccf1bf53bc66521438633a747106aeeb
    uv run --project server python -B server/scripts/point_census/manifest.py check \
        --logs-dir "$POINT_CENSUS_LOGS" --expected-manifest-sha256 "$POINT_CENSUS_MANIFEST_SHA"
    uv run --project server python -B server/scripts/point_census/e1_census.py \
        --logs-dir "$POINT_CENSUS_LOGS" --expected-manifest-sha256 "$POINT_CENSUS_MANIFEST_SHA"
    uv run --project server python -B server/scripts/point_census/e5_feed_ground_truth.py \
        --logs-dir "$POINT_CENSUS_LOGS" --expected-manifest-sha256 "$POINT_CENSUS_MANIFEST_SHA"
    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 uv run --project server \
        python -B server/scripts/point_census/p1_p2_rollout_probes.py \
        --logs-dir "$POINT_CENSUS_LOGS" --expected-manifest-sha256 "$POINT_CENSUS_MANIFEST_SHA"
    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 uv run --frozen --project server \
        python -B server/scripts/point_census/e2_e3_search_objective.py \
        --logs-dir "$POINT_CENSUS_LOGS" --expected-manifest-sha256 "$POINT_CENSUS_MANIFEST_SHA"

Rebuild the manifest only when the log population intentionally changes
(`manifest.py build --logs-dir logs > server/scripts/point_census/manifest.json`);
the committed manifest is the frozen population of record. Rebuilding it
changes the population identity and requires a new review. Tests:
`server/tests/test_point_census.py` (23 tests cover closed-schema and
population tamper refusal, symlink/hardlink and stable-byte boundaries,
classification, rollout legality, objective-arm world/work binding, every
headline CLI route, deterministic output, clean source/runtime receipts, and
no implicit writes).
