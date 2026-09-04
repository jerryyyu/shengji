"""Ballot-gap report, manifest writer and CLI plumbing."""
import json
import os

import pytest

from shengji.harvest import ballot_gap, cli, manifest
from shengji.harvest.common import LUNA0_ROOT, LUNA_ROOTS, SOL0_ROOT, InputRegistry


def test_aggregate_fractions():
    decisions = [
        {"phase": "lead", "rank": "2", "mode": "S", "contested": True, "off_ballot": True},
        {"phase": "lead", "rank": "2", "mode": "S", "contested": True, "off_ballot": False},
        {"phase": "follow", "rank": "A", "mode": "NT", "contested": False, "off_ballot": False},
    ]
    agg = ballot_gap.aggregate(decisions)
    assert agg["overall"] == {"decisions": 3, "contested": 2, "off_ballot": 1,
                              "off_ballot_fraction": 0.5}
    assert agg["by_phase"]["lead"]["off_ballot_fraction"] == 0.5
    assert agg["by_phase"]["follow"]["off_ballot_fraction"] is None
    assert agg["by_phase"]["bury"]["decisions"] == 0
    assert set(agg["by_rank_mode"]) == {"2|S", "A|NT"}


def test_teacher_sources_load():
    if not (all(r.is_dir() for r in LUNA_ROOTS) and SOL0_ROOT.is_dir() and LUNA0_ROOT.is_dir()):
        pytest.skip("teacher evidence roots not present")
    registry = InputRegistry()
    luna = list(ballot_gap.luna_rpc_decisions(registry))
    sol0 = list(ballot_gap.transcript_decisions(SOL0_ROOT, registry))
    luna0 = list(ballot_gap.transcript_decisions(LUNA0_ROOT, registry))
    print(f"ballot-gap decisions: luna-rpc={len(luna)} sol0={len(sol0)} luna0={len(luna0)}")
    assert len(luna) == 4808
    assert len(sol0) > 1000 and len(luna0) > 1000
    for d in luna + sol0 + luna0:
        assert d["phase"] in ("lead", "follow")
    assert all(d["contested"] for d in sol0 + luna0)


def test_cli_end_to_end_small(tmp_path):
    out = tmp_path / "out"
    assert cli.main(["room-log", "--out", str(out), "--limit", "3"]) == 0
    assert cli.main(["highn", "--out", str(out), "--limit", "5"]) == 0
    assert cli.main(["manifest", str(out)]) == 0
    m = json.loads((out / "manifest.json").read_text())
    assert set(m["sources"]) == {"room-log", "highn"}
    assert m["sources"]["room-log"]["counts"]["rounds"] == 3
    assert m["sources"]["highn"]["counts"]["decisions"] == 5
    for name, info in m["outputs"].items():
        assert len(info["sha256"]) == 64
        assert (out / name).is_file()
    assert m["sources"]["room-log"]["inputs"] and all(
        len(row["sha256"]) == 64 for row in m["sources"]["room-log"]["inputs"])
    assert m["encoder"] is None
    lines = (out / "room-log.jsonl").read_text().splitlines()
    assert len(lines) == m["sources"]["room-log"]["counts"]["decisions"] + 3
    assert not (out / "room-log.private.jsonl").exists()


def test_write_source_private_mode(tmp_path):
    from shengji.harvest.common import ExtractResult
    from shengji.harvest.schema import finalize_record
    rec = finalize_record({
        "source": "pt1", "source_ref": "g", "policy": "p", "round_seed": 1,
        "setup": {"trump_rank": "2", "banker": 0, "declarations": [],
                  "declaration": None, "trump_suit": "S", "trump_is_nt": False,
                  "buried": None},
        "plays_prefix": [], "seat": 0, "ply": 0, "trick": 0, "role": "banker-team",
        "legal_actions": [["S2"]], "legal_actions_complete": True,
        "legal_actions_count": 1, "action": ["S2"],
        "hidden_hands": {"hands_by_seat": [[], [], [], []], "buried": []},
    })
    result = ExtractResult("pt1", public=[rec], private=[rec], counts={"decisions": 1})
    manifest.write_source(tmp_path, result, cap=1)
    mode = os.stat(tmp_path / "pt1.private.jsonl").st_mode & 0o777
    assert mode == 0o600
    m = manifest.build_manifest(tmp_path)
    assert m["outputs"]["pt1.private.jsonl"]["private"] is True
