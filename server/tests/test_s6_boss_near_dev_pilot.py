"""Contracts for the reusable S6 boss/near DEV pilot."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_boss_near_dev_pilot as PILOT  # noqa: E402


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
