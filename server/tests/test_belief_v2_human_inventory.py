"""Privacy, completeness, and attempted-channel witnesses for V2 H0."""

from __future__ import annotations

import copy
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
    verify_h0_inventory,
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


@pytest.mark.parametrize("mutation", [
    lambda result: result.__setitem__("foreign_field", False),
    lambda result: result.__setitem__("raw_player_identity_published", True),
    lambda result: result.__setitem__("model_rows_published", True),
    lambda result: result.__setitem__("training_authorized", True),
    lambda result: result.__setitem__("test_open_authorized", True),
    lambda result: result.__setitem__("strength_claim_authorized", True),
])
def test_h0_verifier_refuses_foreign_fields_and_every_authority(
        tmp_path, mutation):
    manifest, source = _write_snapshot(tmp_path, _completed_round())
    result = build_h0_inventory(
        source_manifest=manifest, source_paths=[source])
    mutation(result)
    with pytest.raises(BeliefV2HumanInventoryError,
                       match="inventory identity drift"):
        verify_h0_inventory(result)


def _many_group_inventory(tmp_path: Path, *, shared_first_two=False):
    sources = []
    manifest_rows = []
    for index in range(30):
        source = tmp_path / f"ROOM_{index:02d}.jsonl"
        events = _completed_round(attempted_complete=index % 2 == 0)
        events[0]["players"][0]["name"] = (
            "Shared Human" if shared_first_two and index < 2
            else f"Human {index:02d}")
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
    assert result["selection_inputs"] == [
        "component_digest", "eligible_decision_count"]
    assert result["selection_target_decision_fractions"] == {
        "train": {"numerator": 8, "denominator": 10},
        "calibration": {"numerator": 1, "denominator": 10},
        "test": {"numerator": 1, "denominator": 10},
    }
    assert result["selection_uses_round_counts"] is False
    assert result["selection_uses_decision_count_magnitudes"] is True
    assert result[
        "selection_requires_nonempty_eligible_decisions_per_split"] is True
    assert result["selection_uses_labels_or_outcomes"] is False
    assert result["training_authorized"] is False


def test_h0_cross_file_player_component_never_crosses_splits(tmp_path):
    inventory = _many_group_inventory(tmp_path, shared_first_two=True)
    shared = [row for row in inventory["components"]
              if len(row["group_digests"]) == 2]
    assert len(shared) == 1
    merged_groups = shared[0]["group_digests"]
    result = build_h0_group_split(inventory)
    memberships = [split for split, row in result["splits"].items()
                   if set(merged_groups) & set(row["group_digests"])]
    assert len(memberships) == 1
    assert set(merged_groups).issubset(
        result["splits"][memberships[0]]["group_digests"])

    forged = copy.deepcopy(result)
    source_split = memberships[0]
    target_split = next(split for split in forged["splits"]
                        if split != source_split)
    forged["splits"][source_split]["group_digests"].remove(
        merged_groups[0])
    forged["splits"][target_split]["group_digests"].append(
        merged_groups[0])
    forged["splits"][target_split]["group_digests"].sort()
    with pytest.raises(BeliefV2HumanInventoryError,
                       match="split reconstruction"):
        validate_h0_group_split(forged, inventory=inventory)


def test_h0_component_split_balances_decisions_and_keeps_nonempty_rows(
        tmp_path):
    sources = []
    manifest_rows = []
    component_sizes = (15, 4, 2, 2, 1, 1, 1, 1, 1, 1, 1)
    index = 0
    for component, size in enumerate(component_sizes):
        for _ in range(size):
            source = tmp_path / f"ROOM_{index:02d}.jsonl"
            events = _completed_round()
            events[0]["players"][0]["name"] = f"Human {component:02d}"
            events[0]["source_fixture_nonce"] = index
            if size == 1 and component != 4:
                for event in events:
                    if event.get("e") == "play":
                        event["bot"] = True
            source.write_text("".join(
                json.dumps(event) + "\n" for event in events))
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            sources.append(source)
            manifest_rows.append(f"{digest}  {source.name}\n")
            index += 1
    manifest = tmp_path / "snapshot.sha256"
    manifest.write_text("".join(manifest_rows))
    inventory = build_h0_inventory(
        source_manifest=manifest, source_paths=sources)
    result = build_h0_group_split(inventory)

    assert sorted(len(row["group_digests"])
                  for row in inventory["components"]) \
        == [1, 1, 1, 1, 1, 1, 1, 2, 2, 4, 15]
    assert sum(row["group_count"]
               for row in result["splits"].values()) == 30
    assert all(row["human_play_decisions"] > 0
               for row in result["splits"].values())
    component_membership = {}
    for split, split_row in result["splits"].items():
        for group in split_row["group_digests"]:
            component = next(row["component_digest"]
                             for row in inventory["groups"]
                             if row["group_digest"] == group)
            component_membership.setdefault(component, set()).add(split)
    assert all(len(values) == 1 for values in component_membership.values())
    assert result["zero_decision_component_destination"] == "train"

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
