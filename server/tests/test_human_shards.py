import hashlib
import json
import random
from pathlib import Path

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.round import Round, actual_play_after
from shengji.rl.human_shards import HumanCorpusError, build_corpus


def _event(round_no, kind, **fields):
    return {"round": round_no, "e": kind, **fields}


def _completed_round(round_no=1):
    rnd = Round("4", 0, random.Random(731))
    events = [_event(
        round_no, "round_start", deck=list(rnd.deck), banker=rnd.banker,
        trump_rank=rnd.trump_rank, levels=["4"] * 4,
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
        round_no, "trump", suit=rnd.trump_suit, rank=rnd.trump_rank,
        banker=rnd.banker, declared=False))

    bot = HeuristicBot()
    bury = bot.decide_bury(rnd, rnd.banker)
    rnd.bury(rnd.banker, bury)
    events.append(_event(
        round_no, "bury", seat=rnd.banker, cards=bury, bot=False))

    first = True
    while rnd.phase == "play":
        seat = rnd.turn
        cards = bot.decide_play(rnd, seat)
        previous_last = rnd.last_trick
        rnd.play(seat, cards)
        played = actual_play_after(rnd, seat, previous_last)
        events.append(_event(
            round_no, "play", seat=seat, cards=played,
            bot=(not first)))
        first = False
    events.append(_event(
        round_no, "round_end", attacker_points=rnd.attacker_points,
        kitty=list(rnd.buried), kitty_points=rnd.kitty_bonus,
        winner_team="attackers", level_change=1,
        new_levels=["5"] * 4, next_banker=0, game_over=False))
    return events


def _write_jsonl(path: Path, events):
    path.write_text("".join(json.dumps(event) + "\n" for event in events))


def _digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_build_corpus_publishes_replayable_play_bury_and_manifest(tmp_path):
    source = tmp_path / "ROOM.jsonl"
    events = _completed_round()
    events.append(_event(
        2, "round_start", deck=events[0]["deck"], banker=0,
        trump_rank="4", levels=["4"] * 4,
        players=events[0]["players"]))
    _write_jsonl(source, events)
    source_manifest = tmp_path / "fly.sha256"
    source_manifest.write_text(f"{_digest(source)}  {source.name}\n")
    out = tmp_path / "human_v8"

    manifest = build_corpus(
        [str(source)], str(out), source_manifest=str(source_manifest),
        run_id="human-v8-test")

    assert out.is_dir()
    assert not (tmp_path / "human_v8.partial").exists()
    assert manifest["schema"] == "human-decision-corpus-v1"
    assert manifest["run_id"] == "human-v8-test"
    assert manifest["training_authorized"] is False
    assert manifest["strength_claim"] is False
    assert manifest["stats"]["play_decisions_accepted"] == 1
    assert manifest["stats"]["bury_decisions_accepted"] == 1
    assert manifest["stats"]["rounds_replayed"] == 1
    assert manifest["rejections"]["round_incomplete"] == 1
    assert manifest["sources"][0]["fly_snapshot_member"] is True

    shard = np.load(out / "shard_00000.npz")
    assert shard["obs"].shape[0] == 1
    assert shard["chosen"].shape == (1,)
    play = json.loads((out / "play_decisions.jsonl").read_text())
    bury = json.loads((out / "bury_decisions.jsonl").read_text())
    assert play["surface"] == "lead"
    assert bury["seat"] == 0
    assert len(bury["chosen"]) == 8
    assert "Alice" not in (out / "manifest.json").read_text()
    assert "Alice" not in (out / "play_decisions.jsonl").read_text()


def test_corrupt_round_is_counted_and_its_pending_decision_is_discarded(tmp_path):
    good = _completed_round(1)
    bad = _completed_round(2)
    first_play = next(event for event in bad if event["e"] == "play")
    first_play["cards"] = ["BJ", "BJ"]
    source = tmp_path / "ROOM.jsonl"
    _write_jsonl(source, good + bad)
    out = tmp_path / "human_v8"

    manifest = build_corpus([str(source)], str(out))

    assert manifest["stats"]["rounds_replayed"] == 1
    assert manifest["stats"]["play_decisions_accepted"] == 1
    assert sum(value for key, value in manifest["rejections"].items()
               if key.startswith("round_play_replay:")) == 1


def test_existing_output_refuses_without_mutation(tmp_path):
    source = tmp_path / "ROOM.jsonl"
    _write_jsonl(source, _completed_round())
    out = tmp_path / "human_v8"
    out.mkdir()
    sentinel = out / "keep"
    sentinel.write_text("unchanged")

    with pytest.raises(HumanCorpusError, match="fresh output required"):
        build_corpus([str(source)], str(out))

    assert sentinel.read_text() == "unchanged"


def test_source_manifest_hash_mismatch_refuses_publication(tmp_path):
    source = tmp_path / "ROOM.jsonl"
    _write_jsonl(source, _completed_round())
    source_manifest = tmp_path / "fly.sha256"
    source_manifest.write_text(f"{'0' * 64}  {source.name}\n")
    out = tmp_path / "human_v8"

    with pytest.raises(HumanCorpusError, match="differs from snapshot"):
        build_corpus(
            [str(source)], str(out), source_manifest=str(source_manifest))

    assert not out.exists()
    assert not (tmp_path / "human_v8.partial").exists()


@pytest.mark.parametrize("tag", [
    {"training_excluded": True},
    {"experiment": {"schema": "human-vs-bot-evaluation-v1"}},
    {"experiment": {"schema": "future-eval-v2", "training_excluded": True}},
])
def test_evaluation_only_round_refuses_entire_publication(tmp_path, tag):
    events = _completed_round()
    events[0].update(tag)
    source = tmp_path / "EVAL.jsonl"
    _write_jsonl(source, events)
    out = tmp_path / "human_v9"

    with pytest.raises(HumanCorpusError, match="evaluation-only round"):
        build_corpus([str(source)], str(out))

    assert not out.exists()
    assert not (tmp_path / "human_v9.partial").exists()


def test_evaluation_tag_on_later_event_also_refuses_publication(tmp_path):
    events = _completed_round()
    events[-1]["training_excluded"] = True
    source = tmp_path / "EVAL.jsonl"
    _write_jsonl(source, events)
    out = tmp_path / "human_v9"

    with pytest.raises(HumanCorpusError, match="evaluation-only round"):
        build_corpus([str(source)], str(out))

    assert not out.exists()


def test_source_manifest_defines_population_and_excludes_legacy_files(tmp_path):
    current = tmp_path / "CURRENT.jsonl"
    legacy = tmp_path / "LEGACY.jsonl"
    _write_jsonl(current, _completed_round(1))
    _write_jsonl(legacy, _completed_round(2))
    source_manifest = tmp_path / "fly.sha256"
    source_manifest.write_text(f"{_digest(current)}  {current.name}\n")
    out = tmp_path / "human_v8"

    manifest = build_corpus(
        [str(tmp_path / "*.jsonl")], str(out),
        source_manifest=str(source_manifest))

    assert manifest["stats"]["source_files"] == 1
    assert manifest["stats"]["non_snapshot_source_files_excluded"] == 1
    assert manifest["non_snapshot_sources_excluded"] == ["LEGACY.jsonl"]
    assert manifest["stats"]["play_decisions_accepted"] == 1


def test_missing_snapshot_member_refuses_before_partial(tmp_path):
    source = tmp_path / "CURRENT.jsonl"
    _write_jsonl(source, _completed_round())
    source_manifest = tmp_path / "fly.sha256"
    source_manifest.write_text(
        f"{_digest(source)}  {source.name}\n{'1' * 64}  MISSING.jsonl\n")
    out = tmp_path / "human_v8"

    with pytest.raises(HumanCorpusError, match="snapshot members missing"):
        build_corpus(
            [str(source)], str(out), source_manifest=str(source_manifest))

    assert not out.exists()
    assert not (tmp_path / "human_v8.partial").exists()
