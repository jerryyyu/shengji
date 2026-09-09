"""Small, engine-backed witnesses for the train-only horizon importer."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from shengji.engine.round import Round
from shengji.harvest import legal, rebuild
from shengji.harvest.schema import finalize_record, record_sha256
from scripts import cwv_decision_panel as panel

POLICY = "mc-shortlist-3cd27716-w32-r55d379a3"

def _record(seed: int, ref: str, *, policy: str = POLICY,
            outcome: dict | None = None) -> dict:
    rnd = Round("2", 0, random.Random(seed))
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    rnd.bury(0, rnd.hands[0][:8])
    listed = legal.enumerate_legal(rnd, rnd.turn, cap=1)
    return finalize_record({
        "source": "trajectory", "source_ref": ref, "policy": policy,
        "round_seed": seed, "deck": list(rnd.deck),
        "setup": rebuild.setup_from_round(rnd), "plays_prefix": [],
        "seat": rnd.turn, "ply": 0, "trick": 0, "role": "banker-team",
        "legal_actions": listed.actions, "legal_actions_complete": False,
        "legal_actions_count": listed.count, "action": listed.actions[0],
        "outcome": outcome,
    })


def _store(tmp_path: Path, rows: list[dict]) -> tuple[Path, dict[str, str]]:
    source = tmp_path / "trajectory.jsonl"
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    assignment = {panel._record_deal_key(row): "train" for row in rows}
    return source, assignment


def test_reconstructs_one_state_per_mirrored_deal(tmp_path):
    first = _record(21, "deal:21:mirror:0", policy=POLICY)
    mirror = dict(first, source_ref="deal:21:mirror:1")
    mirror["record_sha256"] = record_sha256(mirror)
    source, assignment = _store(tmp_path, [first, mirror])
    out = tmp_path / "panel.json"
    result = panel.build_panel(source, assignment, out,
                               policy=POLICY, max_deals=1, seed=7)
    assert len(result["entries"]) == 1
    entry = result["entries"][0]
    assert entry["provenance"]["split"] == "fit"
    assert entry["snapshot"]["phase"] == "play"
    assert json.loads(out.read_text())["schema"] == panel.PANEL_SCHEMA


def test_heldout_rows_are_not_rebuilt(tmp_path, monkeypatch):
    train = _record(31, "train", policy=POLICY)
    heldout = _record(32, "validation", policy=POLICY)
    source, assignment = _store(tmp_path, [train, heldout])
    assignment[panel._record_deal_key(heldout)] = "val"
    original = panel.rebuild.state_for_record
    calls = []

    def observe(row):
        calls.append(row["source_ref"])
        return original(row)

    monkeypatch.setattr(panel.rebuild, "state_for_record", observe)
    panel.build_panel(source, assignment, tmp_path / "panel.json",
                      policy=POLICY, max_deals=1)
    assert calls == ["train"]


def test_outcome_changes_do_not_change_identity(tmp_path):
    row = _record(41, "stable", policy=POLICY, outcome={"attacker_points": 0,
                                          "winner_team": 0,
                                          "signed_level_utility": 3})
    source, assignment = _store(tmp_path, [row])
    one = panel.build_panel(source, assignment, tmp_path / "one.json",
                            policy=POLICY, max_deals=1)
    changed = dict(row, outcome={"attacker_points": 200, "winner_team": 1,
                                 "signed_level_utility": -3})
    changed["record_sha256"] = record_sha256(changed)
    source.write_text(json.dumps(changed) + "\n")
    two = panel.build_panel(source, assignment, tmp_path / "two.json",
                            policy=POLICY, max_deals=1)
    assert one["entries"][0]["id"] == two["entries"][0]["id"]


def test_policy_mismatch_refused(tmp_path):
    row = _record(51, "wrong", policy="wrong-policy")
    source, assignment = _store(tmp_path, [row])
    with pytest.raises(panel.PanelError, match="policy"):
        panel.build_panel(source, assignment, tmp_path / "panel.json",
                          policy=POLICY, max_deals=1)


def test_cutoff_listing_does_not_disqualify_exhaustive_width(tmp_path):
    row = _record(61, "cutoff", policy=POLICY)
    source, assignment = _store(tmp_path, [row])
    result = panel.build_panel(source, assignment, tmp_path / "panel.json",
                               policy=POLICY, max_deals=1)
    assert result["entries"][0]["snapshot"]["phase"] == "play"
    assert row["legal_actions_count"] >= 6 and len(row["legal_actions"]) == 1


def test_assignment_superset_is_reported_as_unused(tmp_path):
    row = _record(66, "subset", policy=POLICY)
    source, assignment = _store(tmp_path, [row])
    assignment["deck:" + "f" * 64] = "train"
    result = panel.build_panel(source, assignment, tmp_path / "panel.json",
                               policy=POLICY, max_deals=1)
    assert result["census"]["unused_assignment_deals"] == 1


def test_stops_reconstructing_after_requested_population(tmp_path, monkeypatch):
    rows = [_record(67, "first", policy=POLICY),
            _record(68, "second", policy=POLICY)]
    source, assignment = _store(tmp_path, rows)
    calls = []
    original = panel.rebuild.state_for_record

    def observe(row):
        calls.append(row["source_ref"])
        return original(row)

    monkeypatch.setattr(panel.rebuild, "state_for_record", observe)
    # Force a known deal order so the witness is independent of hash output.
    monkeypatch.setattr(panel, "_deal_priority",
                        lambda _seed, key: "0" if key == panel._record_deal_key(rows[0]) else "1")
    panel.build_panel(source, assignment, tmp_path / "panel.json",
                      policy=POLICY, max_deals=1)
    assert len(calls) == 1


def test_source_hash_drift_refused_after_discovery(tmp_path, monkeypatch):
    row = _record(71, "drift", policy=POLICY)
    source, assignment = _store(tmp_path, [row])
    discovered = panel.data.discover_store(source)
    source.write_text(source.read_text() + "\n")
    monkeypatch.setattr(panel.data, "discover_store", lambda _path: discovered)
    with pytest.raises(panel.PanelError, match="source hash drift"):
        panel.build_panel(source, assignment, tmp_path / "panel.json",
                          policy=POLICY, max_deals=1)


def test_selected_record_hash_is_checked_not_only_copied(tmp_path):
    row = _record(71, "drift", policy=POLICY)
    row["record_sha256"] = "0" * 64
    source, assignment = _store(tmp_path, [row])
    with pytest.raises(panel.PanelError, match="selected record hash drift"):
        panel.build_panel(source, assignment, tmp_path / "panel.json",
                          policy=POLICY, max_deals=1)
