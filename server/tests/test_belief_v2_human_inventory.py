"""Privacy, completeness, and attempted-channel witnesses for V2 H0."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.round import Round, actual_play_after
from shengji.rl.belief_v2_human_inventory import (
    BeliefV2HumanInventoryError,
    build_h0_group_split,
    build_h0_inventory,
    group_split_bytes,
    inventory_bytes,
    validate_h0_group_split,
)


def _event(round_number, kind, **fields):
    return {"round": round_number, "e": kind, **fields}


def _completed_round(*, attempted_complete: bool = False):
    rnd = Round("9", 0, random.Random(731))
    events = [_event(
        1, "round_start", deck=list(rnd.deck), banker=rnd.banker,
        trump_rank=rnd.trump_rank, levels=["9"] * 4,
        players=[
            {"seat": 0, "name": "Alice", "is_bot": False},
            {"seat": 1, "name": "Bot 1", "is_bot": True},
            {"seat": 2, "name": "Bot 2", "is_bot": True},
            {"seat": 3, "name": "Bot 3", "is_bot": True},
        ])]
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    events.append(_event(
        1, "trump", suit=rnd.trump_suit, rank=rnd.trump_rank,
        banker=rnd.banker, declared=False))
    bot = HeuristicBot()
    bury = bot.decide_bury(rnd, rnd.banker)
    rnd.bury(rnd.banker, bury)
    events.append(_event(1, "bury", seat=rnd.banker, cards=bury, bot=False))
    first = True
    while rnd.phase == "play":
        seat = rnd.turn
        cards = bot.decide_play(rnd, seat)
        previous_last = rnd.last_trick
        rnd.play(seat, cards)
        actual = actual_play_after(rnd, seat, previous_last)
        fields = {"seat": seat, "cards": actual, "bot": not first}
        if first and attempted_complete:
            fields["attempted_cards"] = list(actual)
        events.append(_event(1, "play", **fields))
        first = False
    events.append(_event(
        1, "round_end", attacker_points=rnd.attacker_points,
        kitty=list(rnd.buried), kitty_points=rnd.kitty_bonus,
        winner_team="attackers", level_change=1,
        new_levels=["10"] * 4, next_banker=0, game_over=False))
    return events


def _write_snapshot(tmp_path: Path, events):
    source = tmp_path / "PRIVATE_ROOM.jsonl"
    source.write_text("".join(json.dumps(event) + "\n" for event in events))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = tmp_path / "snapshot.sha256"
    manifest.write_text(f"{digest}  {source.name}\n")
    return manifest, source


@pytest.mark.parametrize(("attempted_complete", "channel"), [
    (False, "absent"),
    (True, "complete"),
])
def test_h0_reconstructs_labels_without_publishing_identity_or_rows(
        tmp_path, attempted_complete, channel):
    manifest, source = _write_snapshot(
        tmp_path, _completed_round(attempted_complete=attempted_complete))
    result = build_h0_inventory(
        source_manifest=manifest, source_paths=[source])
    raw = inventory_bytes(result)

    assert result["rounds_seen"] == result["complete_rounds"] == 1
    assert result["incomplete_rounds"] == 0
    assert result["human_play_decisions"] == 1
    assert result["trump_rank_counts"] == {"9": 1}
    assert result["attempted_channel_counts"] == {channel: 1}
    assert result["hidden_ownership_labels_reconstructable_for_complete_rounds"]
    assert result["raw_player_identity_published"] is False
    assert result["model_rows_published"] is False
    assert result["training_authorized"] is False
    assert b"Alice" not in raw and b"PRIVATE_ROOM" not in raw


def test_h0_refuses_source_population_or_byte_drift(tmp_path):
    manifest, source = _write_snapshot(tmp_path, _completed_round())
    extra = tmp_path / "EXTRA.jsonl"
    extra.write_text(source.read_text())
    with pytest.raises(BeliefV2HumanInventoryError, match="population"):
        build_h0_inventory(
            source_manifest=manifest, source_paths=[source, extra])
    source.write_text(source.read_text() + "\n")
    with pytest.raises(BeliefV2HumanInventoryError, match="bytes differ"):
        build_h0_inventory(source_manifest=manifest, source_paths=[source])


def test_h0_refuses_evaluation_only_source_before_publication(tmp_path):
    events = _completed_round()
    events[-1]["training_excluded"] = True
    manifest, source = _write_snapshot(tmp_path, events)
    with pytest.raises(BeliefV2HumanInventoryError, match="evaluation-only"):
        build_h0_inventory(source_manifest=manifest, source_paths=[source])


def _many_group_inventory(tmp_path: Path):
    sources = []
    manifest_rows = []
    for index in range(30):
        source = tmp_path / f"ROOM_{index:02d}.jsonl"
        events = _completed_round(attempted_complete=index % 2 == 0)
        events[0]["source_fixture_nonce"] = index
        source.write_text("".join(
            json.dumps(event) + "\n" for event in events))
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        sources.append(source)
        manifest_rows.append(f"{digest}  {source.name}\n")
    manifest = tmp_path / "snapshot.sha256"
    manifest.write_text("".join(manifest_rows))
    return build_h0_inventory(
        source_manifest=manifest, source_paths=sources)


def test_h0_group_split_is_whole_group_deal_blind_and_exact(tmp_path):
    inventory = _many_group_inventory(tmp_path)
    result = build_h0_group_split(inventory)
    validate_h0_group_split(result, inventory=inventory)
    assert group_split_bytes(result, inventory=inventory).endswith(b"\n")
    assert {split: row["group_count"]
            for split, row in result["splits"].items()} == {
                "train": 24, "calibration": 3, "test": 3}
    populations = [set(row["group_digests"])
                   for row in result["splits"].values()]
    assert not populations[0] & populations[1]
    assert not populations[0] & populations[2]
    assert not populations[1] & populations[2]
    assert sum(row["complete_rounds"]
               for row in result["splits"].values()) == 30
    assert result["selection_inputs"] == ["group_digest"]
    assert result["selection_uses_round_or_decision_counts"] is False
    assert result["selection_uses_labels_or_outcomes"] is False
    assert result["training_authorized"] is False


def test_h0_group_split_refuses_inventory_or_result_drift(tmp_path):
    inventory = _many_group_inventory(tmp_path)
    result = build_h0_group_split(inventory)
    result["splits"]["train"]["group_digests"][0] = "0" * 64
    with pytest.raises(BeliefV2HumanInventoryError,
                       match="split reconstruction"):
        validate_h0_group_split(result, inventory=inventory)

    inventory["groups"][0]["complete_rounds"] += 1
    with pytest.raises(BeliefV2HumanInventoryError,
                       match="group accounting"):
        build_h0_group_split(inventory)
