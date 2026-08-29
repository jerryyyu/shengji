import dataclasses
import hashlib

import numpy as np
import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
from shengji.rl.encode import N_CARDS
from shengji.rl.world_afterstate import (
    PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS, WorldAfterstateTensorsV0,
)
from shengji.rl.world_afterstate_v2_inference import PROBABILITY_SCALE
from shengji.rl.world_afterstate_v2_metrics import (
    AUTHORITY, BOOTSTRAP_REPLICATES, WorldAfterstateV2MetricsError,
    build_natural_fit_prior, deal_cluster_bootstrap_interval,
    expected_signed_level_absolute_error_microlevels,
    paired_advantage_absolute_error_improvement_microlevels,
    ranked_probability_score_ppb,
)
from shengji.rl.world_afterstate_v2_training import WorldAfterstateV2TrainingExample


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _row(index, *, source="natural", split="fit", category=100):
    root = f"metric:{index}"
    deal, slot, state = (_sha(root + suffix) for suffix in (":deal", ":slot", ":state"))
    successor = _sha(root + ":successor")
    other = _sha(root + ":other")
    cset = hashlib.sha256(canonical_json_bytes({
        "schema": "world-afterstate-v2-candidate-set-v1",
        "state_sha256": state, "successor_sha256s": [successor, other]})).hexdigest()
    public = np.zeros(PUBLIC_DIM, dtype=np.float32)
    world = np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32)
    return WorldAfterstateV2TrainingExample(
        deal, slot, state, cset, 0, True, successor, _sha(root + ":continuation"),
        0, source, split, "attacker", "early", "lead", "2", "S", "0-39",
        WorldAfterstateTensorsV0(
            public, np.zeros((0, HISTORY_EVENT_DIM), dtype=np.float32), world,
            np.array([1.0, 0.0], dtype=np.float32)), category)


def _one_hot(category):
    result = [0] * 204
    result[category] = PROBABILITY_SCALE
    return tuple(result)


def test_jeffreys_prior_is_natural_fit_only_and_smoothed():
    rows = (_row(0, category=100), _row(1, category=101),
            _row(2, source="pt-sol", category=1), _row(3, split="select", category=2))
    first = build_natural_fit_prior(rows)
    changed = dataclasses.replace(rows[2], signed_level_category=200)
    second = build_natural_fit_prior((*rows[:2], changed, rows[3]))
    assert first.payload() == second.payload()
    assert sum(first.global_probability_ppb) == PROBABILITY_SCALE
    assert all(value > 0 for value in first.global_probability_ppb)
    assert first.probability_ppb("late", "defender", "80+") == first.global_probability_ppb
    with pytest.raises(WorldAfterstateV2MetricsError, match="empty"):
        build_natural_fit_prior((_row(9, source="human"),))


def test_rps_and_absolute_and_paired_error_are_exact():
    assert ranked_probability_score_ppb(_one_hot(7), 7) == 0
    assert ranked_probability_score_ppb(_one_hot(7), 8) > 0
    assert expected_signed_level_absolute_error_microlevels(_one_hot(100), 100) == 0
    assert paired_advantage_absolute_error_improvement_microlevels(
        _one_hot(101), _one_hot(100), 101, 100) == 1_000_000
    split = [0] * 204
    split[100] = PROBABILITY_SCALE // 2
    split[101] = PROBABILITY_SCALE // 2
    assert expected_signed_level_absolute_error_microlevels(
        tuple(split), 101) == 500_000


def test_deal_bootstrap_is_deterministic_clustered_and_fixed_size():
    population = _sha("population")
    values = {_sha(f"deal:{i}"): i for i in range(8)}
    first = deal_cluster_bootstrap_interval(
        values, population_sha256=population, metric_name="rps")
    second = deal_cluster_bootstrap_interval(
        tuple(values.items()), population_sha256=population, metric_name="rps")
    assert first == second
    assert first.replicates == BOOTSTRAP_REPLICATES
    assert first.lower_5th <= first.mean <= first.upper_95th
    with pytest.raises(WorldAfterstateV2MetricsError, match="duplicate"):
        deal_cluster_bootstrap_interval(
            ((next(iter(values)), 1), (next(iter(values)), 2)),
            population_sha256=population, metric_name="rps")


def test_receipts_have_no_authority_and_reject_forgery():
    interval = deal_cluster_bootstrap_interval(
        {_sha("deal"): 1}, population_sha256=_sha("population"), metric_name="x")
    receipt = __import__(
        "shengji.rl.world_afterstate_v2_metrics", fromlist=["MetricReceiptV2"]
    ).MetricReceiptV2("x", _sha("population"), 1, interval)
    receipt.validate()
    assert receipt.payload()["authority"] == AUTHORITY
    forged = dataclasses.replace(receipt, authority={"audit_opening_authorized": True})
    with pytest.raises(WorldAfterstateV2MetricsError, match="receipt"):
        forged.validate()
    prior = build_natural_fit_prior((_row(0),))
    malformed = dataclasses.replace(
        prior,
        strata_probability_ppb=(("early|attacker|not-a-bucket",
                                  prior.global_probability_ppb),))
    with pytest.raises(WorldAfterstateV2MetricsError, match="stratum"):
        malformed.validate()
