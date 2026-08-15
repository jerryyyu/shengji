"""Closed BELIEF-V1 B2 corpus-population manifest tests."""

from __future__ import annotations

import hashlib
import random
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.rl.belief_b2_protocol import (
    B2_ROUND_COUNT,
    b2_round_seeds,
    capture_lane,
    champion_policy_seeds,
)
from shengji.rl.belief_capture import (
    _capture_with_policies,
    captured_round_artifacts,
)
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_corpus import split_for_round_seed
from shengji.rl.belief_population import (
    BeliefPopulationError,
    BeliefPopulationV1,
    PopulationRoundV1,
    population_round_from_artifacts,
    validate_population,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _synthetic_population():
    rows = []
    for seed in b2_round_seeds():
        manifest = _hash(f"manifest|{seed}")
        transcript = _hash(f"transcript|{seed}")
        actor = _hash(f"actor|{seed}")
        target = _hash(f"target|{seed}")
        bundle = hashlib.sha256(canonical_json_bytes({
            "schema": "belief-v1-b2-corpus-round-binding-v1",
            "round_seed": seed,
            "capture_manifest_sha256": manifest,
            "public_transcript_sha256": transcript,
            "actor_stream_sha256": actor,
            "privileged_target_stream_sha256": target,
        })).hexdigest()
        rows.append(PopulationRoundV1(
            round_seed=seed,
            lane=capture_lane(seed),
            split=split_for_round_seed(seed),
            policy_seeds=champion_policy_seeds(seed),
            decision_count=72 + seed % 9,
            capture_manifest_sha256=manifest,
            public_transcript_sha256=transcript,
            actor_stream_sha256=actor,
            privileged_target_stream_sha256=target,
            round_bundle_sha256=bundle,
        ))
    return BeliefPopulationV1(rounds=tuple(rows))


def test_full_population_envelope_is_exact_closed_and_outcome_free():
    population = _synthetic_population()
    validate_population(population)
    payload = population.to_dict()
    assert payload["round_count"] == B2_ROUND_COUNT
    assert payload["decision_count"] == sum(
        row.decision_count for row in population.rounds)
    assert payload["contains_round_outcome"] is False
    assert payload["privileged_targets_are_runtime_inputs"] is False
    assert all(payload[key] is False for key in payload
               if key.endswith("_authorized"))
    assert b'"winner"' not in population.canonical_bytes()
    assert b'"attacker_points"' not in population.canonical_bytes()


def test_one_real_round_bundle_reopens_and_binds_all_streams():
    seed = b2_round_seeds()[0]
    policies = [HeuristicBot() for _ in range(4)]
    captured = _capture_with_policies(
        seed, "mc-s0-report-lcb", champion_policy_seeds(seed), policies)
    artifacts = captured_round_artifacts(captured)
    row = population_round_from_artifacts(artifacts)
    assert row.round_seed == seed
    assert row.decision_count == len(captured.pairs)
    assert row.capture_manifest_sha256 == hashlib.sha256(
        artifacts.manifest_bytes).hexdigest()
    assert row.public_transcript_sha256 == hashlib.sha256(
        artifacts.transcript_bytes).hexdigest()
    changed_targets = (artifacts.target_rows[0] + b" ",
                       *artifacts.target_rows[1:])
    with pytest.raises(BeliefPopulationError, match="capture bundle refused"):
        population_round_from_artifacts(replace(
            artifacts, target_rows=changed_targets))


def test_population_refuses_drop_reorder_lane_split_hash_and_authority_drift():
    population = _synthetic_population()
    with pytest.raises(BeliefPopulationError, match="schema/count"):
        validate_population(replace(population, rounds=population.rounds[:-1]))
    swapped = (population.rounds[1], population.rounds[0],
               *population.rounds[2:])
    with pytest.raises(BeliefPopulationError, match="seed sequence"):
        validate_population(replace(population, rounds=swapped))
    for changed, message in (
        (replace(population.rounds[0], lane=1), "identity/work"),
        (replace(population.rounds[0], split="test"), "split"),
        (replace(population.rounds[0], decision_count=True), "identity/work"),
        (replace(population.rounds[0], round_bundle_sha256="0" * 64),
         "bundle hash"),
    ):
        with pytest.raises(BeliefPopulationError, match=message):
            validate_population(replace(
                population, rounds=(changed, *population.rounds[1:])))
