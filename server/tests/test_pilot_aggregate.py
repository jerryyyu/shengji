"""The aggregator is an experiment gate, not a formatting script."""
from __future__ import annotations

import pytest

from scripts import pilot_aggregate as agg

ARMS = ["current", "v3", "random_fill", "quota", "mc_more_full_work",
        "full_universe"]


def _record(name, seed, *, quota=1.0, random_fill=3.0,
            full=0.5, mc_more=2.5):
    keys = [[[[1, ["S3"]]], []], [[[1, ["S4"]]], []]]
    regrets = {arm: 2.0 for arm in ARMS}
    regrets.update(quota=quota, random_fill=random_fill,
                   full_universe=full, mc_more_full_work=mc_more)
    fold = {"requested": 2, "accepted": 2, "attempts": 2, "rejected": 0,
            "short": 0, "collision_within": 0, "collision_cross": 0}
    digest = agg.stable_digest(keys)
    return {
        "state": name, "deal_seed": seed, "report_world_keys": keys,
        "report_world_digest": digest,
        "reference_returns": [2.0, 2.0], "reference_raw_points": [80, 80],
        "reference_brackets": [0, 0],
        "fold_stats": {name: dict(fold) for name in ("proposal", "oracle", "report")},
        "sampler_counter_deltas": {name: 0 for name in agg.SAMPLER_COUNTERS},
        "arms": {arm: {
            "regret": regrets[arm], "matched_oracle": False, "work": 168,
            "report_world_digest": digest, "n_report_worlds": 2,
            "arm_returns": [0.0, 0.0], "arm_raw_points": [40, 40],
            "arm_brackets": [-1, -1],
        } for arm in ARMS},
    }


def _run(records):
    return {
        "schema": agg.RUN_SCHEMA, "git": "abc", "ballot": "b@v1[x]",
        "experiment_id": "exp", "states_sha256": "states",
        "required_arms": list(ARMS), "shard_count": 1, "shard_index": 0,
        "experiment_n_states": len(records), "n_states": len(records),
        "budget": 14, "work_target": 168, "band": .05,
        "report_worlds": 2, "oracle_worlds": 2,
        "full_proposal_worlds": 2, "salt": "pilot", "tree_dirty": False,
        "complete": True, "work_violations": [], "replay_errors": 0,
        "protocol_failures": [],
        "sampler_counter_totals": {name: 0 for name in agg.SAMPLER_COUNTERS},
        "records": records,
    }


def test_sign_and_primary_and_attribution_contrasts_are_the_named_estimands():
    records = [_record("a", 1), _record("b", 2)]
    got, _ = agg.validate_runs([_run(records)])
    primary = agg.paired(got, *agg.PRIMARY)
    attribution = agg.paired(got, *agg.ATTRIBUTION)
    assert primary == pytest.approx((2.0, 0.0, 2))
    assert attribution == pytest.approx((2.0, 0.0, 2))
    assert primary[2] == 2, "worlds must not inflate the two deal clusters"


@pytest.mark.parametrize("mutate,needle", [
    (lambda run: run.update(tree_dirty=True), "dirty tree"),
    (lambda run: run["work_violations"].append(["x"]), "work-band"),
    (lambda run: run.update(replay_errors=1), "replay errors"),
    (lambda run: run["protocol_failures"].append("x"), "protocol failures"),
    (lambda run: run["sampler_counter_totals"].update(rejected_worlds=1),
     "sampler counter"),
])
def test_failed_runner_invariants_are_refused(mutate, needle):
    run = _run([_record("a", 1), _record("b", 2)])
    mutate(run)
    with pytest.raises(agg.ProtocolError, match=needle):
        agg.validate_runs([run])


def test_missing_state_arm_and_reference_brackets_are_refused():
    run = _run([_record("a", 1), _record("b", 2)])
    run["n_states"] = 3
    del run["records"][0]["arms"]["quota"]
    del run["records"][1]["reference_brackets"]
    with pytest.raises(agg.ProtocolError) as exc:
        agg.validate_runs([run])
    message = str(exc.value)
    assert "records != n_states" in message
    assert "required arms" in message
    assert "reference_brackets" in message


def test_different_report_world_identity_is_refused():
    run = _run([_record("a", 1), _record("b", 2)])
    run["records"][0]["arms"]["quota"]["report_world_digest"] = "other"
    with pytest.raises(agg.ProtocolError, match="different report worlds"):
        agg.validate_runs([run])


def test_duplicate_state_or_deal_is_refused():
    records = [_record("same", 1), _record("same", 1)]
    with pytest.raises(agg.ProtocolError) as exc:
        agg.validate_runs([_run(records)])
    assert "duplicate state" in str(exc.value)
    assert "more than one state from a deal" in str(exc.value)


@pytest.mark.parametrize("field,value", [
    ("schema", "other"), ("git", "def"), ("ballot", "other"),
])
def test_mixed_schema_git_or_ballot_across_shards_is_refused(field, value):
    a = _run([_record("a", 1)])
    b = _run([_record("b", 2)])
    for run, index in ((a, 0), (b, 1)):
        run.update(shard_count=2, shard_index=index, experiment_n_states=2,
                   n_states=1)
    b[field] = value
    with pytest.raises(agg.ProtocolError, match=f"mixed {field}|wrong schema"):
        agg.validate_runs([a, b])


def test_missing_shard_is_refused():
    run = _run([_record("a", 1)])
    run.update(shard_count=2, shard_index=0, experiment_n_states=2)
    with pytest.raises(agg.ProtocolError, match="shards"):
        agg.validate_runs([run])
