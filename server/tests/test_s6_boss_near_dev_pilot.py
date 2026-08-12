"""Contracts for the reusable S6 boss/near DEV pilot."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_boss_near_dev_pilot as PILOT  # noqa: E402


RESULT = Path(__file__).with_name("data") / \
    "s6_boss_near_dev_pilot.v1.json"


def test_policy_contract_keeps_live_root_ballot_and_names_gate():
    contract = PILOT.policy_contract()
    assert len(set(contract["root_ballot_digests"].values())) == 1
    assert contract["full_source_ballot_preserved"] is True
    assert contract["second_search_gate"] == "boss_near_first"
    assert contract["candidate_zero"] == "literal live champion action"


def test_factories_are_explicit_and_unregistered():
    treatment = PILOT.make_arm("treatment", 7)
    null = PILOT.make_arm("matched_null", 7)
    champion = PILOT.make_arm("champion", 7)
    assert treatment.s6_throw_mode == "treatment"
    assert null.s6_throw_mode == "matched_null"
    assert treatment.s6_throw_search_gate == null.s6_throw_search_gate \
        == "boss_near_first"
    assert not hasattr(champion, "s6_throw_search_gate")
    with pytest.raises(PILOT.PilotRefused, match="unknown"):
        PILOT.make_arm("mystery", 7)


def test_exclusive_writer_refuses_overwrite(tmp_path):
    target = tmp_path / "dev.json"
    PILOT.write_exclusive(target, {"schema": PILOT.SCHEMA})
    with pytest.raises(PILOT.PilotRefused, match="overwrite"):
        PILOT.write_exclusive(target, {"schema": PILOT.SCHEMA})


@pytest.mark.parametrize("clusters", [0, -1, PILOT.MAX_CLUSTERS + 1])
def test_payload_refuses_out_of_bound_cluster_count(clusters):
    with pytest.raises(PILOT.PilotRefused, match="cluster count"):
        PILOT.build_payload(
            {}, expected_git="a" * 40, clusters=clusters, workers=1,
            elapsed_seconds=1.0)


@pytest.mark.parametrize("workers", [0, -1, PILOT.MAX_WORKERS + 1])
def test_payload_refuses_out_of_bound_worker_count(workers):
    with pytest.raises(PILOT.PilotRefused, match="worker count"):
        PILOT.build_payload(
            {}, expected_git="a" * 40, clusters=1, workers=workers,
            elapsed_seconds=1.0)


def test_frozen_dev_pilot_recomputes_and_remains_exploratory():
    raw = RESULT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "ad3eae32911780d90f251210a65342da0091f51b77b4e53415003111197b8b8e")
    payload = json.loads(raw)
    internal = payload.pop("internal_sha256")
    assert PILOT.stable_digest(payload) == internal == (
        "0ff32e97ee73db8a68168812176947bb3b553e76c4e73accb3ba37dcd904cf43")
    assert payload["git"] == "ac9d7048fadb0ae171b4bb0e9f1b37c0aa0a745f"
    assert payload["tree_dirty"] is False
    assert payload["runtime"]["fast_binary_sha256"] == (
        "e08d05295bdce8f36f9b5fa2bb414b68b1ea7cb6316da4a943b4325987769f30")
    # Recompute repository-owned source pins without requiring the native
    # extension to be installed in the checkout that audits this artifact.
    # The exact Air binary remains authenticated by its frozen digest above.
    paths = {
        "pilot": PILOT.SCRIPT,
        "duel_core": PILOT.SERVER / "scripts/s6_throw_duel.py",
        "gate": PILOT.SERVER / "shengji/ai/throw_search_gate.py",
        "policy": PILOT.SERVER / "shengji/ai/throw_policy.py",
        "source": PILOT.SERVER / "shengji/ai/throw_sourcing.py",
        "evaluation": PILOT.SERVER / "shengji/evaluation.py",
        "registry": PILOT.SERVER / "shengji/ai/registry.py",
        "mcbot": PILOT.SERVER / "shengji/ai/mcbot.py",
        "memory": PILOT.SERVER / "shengji/ai/memory.py",
        "env": PILOT.SERVER / "shengji/ai/env.py",
        "game": PILOT.SERVER / "shengji/engine/game.py",
        "round": PILOT.SERVER / "shengji/engine/round.py",
    }
    assert {name: PILOT.sha256(path) for name, path in paths.items()} == {
        name: digest for name, digest in payload["source_sha256s"].items()
        if name != "fast_binary"
    }

    records = payload["records"]
    assert all(len(records[label]) == 64 for label in PILOT.LABEL_ORDER)
    for label in PILOT.LABEL_ORDER:
        assert len({(row["seed"], row["flip"])
                    for row in records[label]}) == 64
        assert all(not PILOT.record_problems(
            row, expected_label=label, expected_seed=row["seed"],
            expected_flip=row["flip"]) for row in records[label])
    rebuilt = PILOT.BASE.build_aggregate(
        PILOT._normalized(records), expected_clusters=32)
    assert rebuilt["stats"] == payload["descriptive"]["stats"]
    assert rebuilt["telemetry"] == payload["descriptive"]["telemetry"]
    assert rebuilt["criteria"][
        "matched_null_champion_exact_outcomes"] is True

    champion = {(row["seed"], row["flip"]): row
                for row in records["champion"]}
    cluster_diffs = Counter()
    override_diffs = []
    for row in records["treatment"]:
        key = (row["seed"], row["flip"])
        diff = row["level_utility"] - champion[key]["level_utility"]
        cluster_diffs[row["seed"]] += diff
        if row["arm"]["s6_throw"]["treatment_overrides"]:
            override_diffs.append(diff)
    assert Counter(cluster_diffs.values()) == {0: 31, -2: 1}
    assert Counter(override_diffs) == {0: 11, -2: 1}
    assert payload["descriptive"]["stats"]["treatment_champion"] == {
        "a": "treatment", "b": "champion", "clusters": 32,
        "half_width95": 0.1225, "lcb95": -0.185,
        "mean": -0.0625, "ucb95": 0.06,
    }
    assert payload["exploration_only"] is True
    assert payload["confirmatory_claim"] is False
    assert payload["screen_execution_authorized"] is False
    assert payload["strength_claim"] is False
    assert payload["production_promotion"] is False
    assert payload["production_deployment"] is False
