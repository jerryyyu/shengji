"""Fixture-backed tests for the point-census tooling: manifest binding,
classification, legality filtering, determinism, and no implicit writes."""
from __future__ import annotations

import copy
import json
import os
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parent
SCRIPTS = SERVER / "scripts/point_census"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SERVER))

import common  # noqa: E402
import e2_e3_search_objective as objective  # noqa: E402
import p1_p2_rollout_probes as probes  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.cards import Ordering, points  # noqa: E402
from shengji.engine.round import Round, Trick, TrickPlay  # noqa: E402


def _synthetic_log(path: Path, seed: int = 5) -> None:
    """Write one engine-generated round in the server log format.

    Seat 0 is the human; the other seats are bots."""
    rnd = Round("2", 0, random.Random(seed))
    deck = list(rnd.deck)
    # Mirror replay_log.rebuild_round exactly so the fixture replays
    # byte-for-byte through the same reconstruction path.
    rnd.hands = [[], [], [], []]
    rnd._deal_pos = 0
    rnd.phase = "deal"
    rnd.kitty = deck[100:]
    actors = [make_bot("smart") for _ in range(4)]
    events = [{"e": "round_start", "round": 1, "banker": 0, "trump_rank": "2",
               "deck": deck,
               "players": [{"seat": s, "name": f"P{s}"} for s in range(4)]}]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        choice = actors[seat].decide_declare(rnd, seat)
        if choice:
            rnd.declare(seat, choice)
            events.append({"e": "declare", "round": 1, "seat": seat,
                           "cards": list(choice), "bot": seat != 0})
    for seat in range(4):
        choice = actors[seat].decide_declare(rnd, seat, final=True)
        if choice:
            rnd.declare(seat, choice)
            events.append({"e": "declare", "round": 1, "seat": seat,
                           "cards": list(choice), "bot": seat != 0})
    rnd.finalize_declare()
    events.append({"e": "trump", "round": 1, "banker": rnd.banker})
    bury = list(actors[rnd.banker].decide_bury(rnd, rnd.banker))
    rnd.bury(rnd.banker, bury)
    events.append({"e": "bury", "round": 1, "cards": bury})
    while rnd.phase == "play":
        seat = rnd.turn
        cards = actors[seat].decide_play(rnd, seat)
        events.append({"e": "play", "round": 1, "seat": seat,
                       "cards": list(cards), "bot": seat != 0})
        rnd.play(seat, list(cards))
        if rnd.last_trick is not None and (rnd.trick is None
                                           or not rnd.trick.plays):
            trick = rnd.last_trick
            events.append({
                "e": "trick", "round": 1,
                "winner": trick.winner,
                "points": sum(points(c) for tp in trick.plays
                              for c in tp.cards),
                "plays": [{"seat": tp.seat, "cards": list(tp.cards)}
                          for tp in trick.plays]})
    path.write_text("".join(json.dumps(e) + "\n" for e in events))


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    logs = tmp_path_factory.mktemp("logs")
    _synthetic_log(logs / "FIXT.jsonl")
    manifest = common.build_manifest(str(logs))
    mpath = logs.parent / "manifest.json"
    mpath.write_bytes(common.canonical(manifest))
    return logs, mpath, common.sha256_file(mpath)


def _new_corpus(tmp_path: Path, seed: int = 5):
    logs = tmp_path / "logs"
    logs.mkdir()
    _synthetic_log(logs / "FIXT.jsonl", seed=seed)
    mpath = tmp_path / "manifest.json"
    mpath.write_bytes(common.canonical(common.build_manifest(str(logs))))
    return logs, mpath


def _load(corpus):
    logs, mpath, expected = corpus
    return common.load_validated_manifest(
        str(mpath), str(logs), expected)


def _write_manifest(path: Path, value: dict) -> str:
    path.write_bytes(common.canonical(value))
    return common.sha256_file(path)


def test_manifest_roundtrip_and_tamper_refusal(corpus):
    logs, mpath, expected = corpus
    manifest, ordered, actual = _load(corpus)
    assert [item.name for item in ordered] == ["FIXT.jsonl"]
    assert actual == expected
    assert manifest["totals"]["rounds"] == 1
    log = logs / "FIXT.jsonl"
    original = log.read_bytes()
    log.write_bytes(original + b"\n")
    with pytest.raises(SystemExit, match="drift"):
        common.load_validated_manifest(str(mpath), str(logs), expected)
    log.write_bytes(original)


@pytest.mark.parametrize("mutation", [
    "root-extra", "allowed-use", "bool-count", "totals", "duplicate-name",
    "traversal",
])
def test_manifest_rehashed_schema_mutations_refuse(tmp_path, mutation):
    logs, mpath = _new_corpus(tmp_path)
    value = json.loads(mpath.read_bytes())
    if mutation == "root-extra":
        value["authority"] = True
    elif mutation == "allowed-use":
        value["allowed_use"].append("strength-selection")
    elif mutation == "bool-count":
        value["files"][0]["plays"] = True
    elif mutation == "totals":
        value["totals"]["plays"] += 1
    elif mutation == "duplicate-name":
        value["files"].append(copy.deepcopy(value["files"][0]))
    elif mutation == "traversal":
        value["files"][0]["name"] = "../FIXT.jsonl"
    expected = _write_manifest(mpath, value)
    with pytest.raises(SystemExit, match="REFUSED"):
        common.load_validated_manifest(str(mpath), str(logs), expected)


def test_manifest_duplicate_and_nonfinite_json_refuse_with_matching_hash(
        tmp_path):
    logs, mpath = _new_corpus(tmp_path)
    raw = mpath.read_bytes()
    duplicate = raw.replace(
        b'{"allowed_use":',
        b'{"schema":"point-census-input-manifest-v1","allowed_use":', 1)
    mpath.write_bytes(duplicate)
    with pytest.raises(SystemExit, match="strict JSON"):
        common.load_validated_manifest(
            str(mpath), str(logs), common.sha256_file(mpath))
    value = common.build_manifest(str(logs))
    value["totals"]["plays"] = float("nan")
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"))
           + "\n").encode()
    mpath.write_bytes(raw)
    with pytest.raises(SystemExit, match="strict JSON"):
        common.load_validated_manifest(
            str(mpath), str(logs), common.sha256_file(mpath))


def test_manifest_population_and_link_mutations_refuse(tmp_path):
    logs, mpath = _new_corpus(tmp_path)
    expected = common.sha256_file(mpath)
    (logs / "UNTRACKED.jsonl").write_bytes((logs / "FIXT.jsonl").read_bytes())
    with pytest.raises(SystemExit, match="population drift"):
        common.load_validated_manifest(str(mpath), str(logs), expected)
    (logs / "UNTRACKED.jsonl").unlink()
    target = logs / "FIXT.jsonl"
    hard = logs / "HARD.jsonl"
    os.link(target, hard)
    with pytest.raises(SystemExit, match="contains a link"):
        common.load_validated_manifest(str(mpath), str(logs), expected)


def test_manifest_and_input_symlinks_refuse(tmp_path):
    logs, mpath = _new_corpus(tmp_path)
    expected = common.sha256_file(mpath)
    manifest_link = tmp_path / "manifest-link.json"
    manifest_link.symlink_to(mpath)
    with pytest.raises(SystemExit, match="stable input|regular/unlinked"):
        common.load_validated_manifest(
            str(manifest_link), str(logs), expected)
    log = logs / "FIXT.jsonl"
    elsewhere = tmp_path / "elsewhere.jsonl"
    log.rename(elsewhere)
    log.symlink_to(elsewhere)
    with pytest.raises(SystemExit, match="contains a link"):
        common.load_validated_manifest(str(mpath), str(logs), expected)


def test_iter_decisions_yields_only_the_human_seat(corpus):
    _, ordered, _ = _load(corpus)
    rows = list(common.iter_decisions(ordered))
    assert rows, "fixture round produced no human decisions"
    assert {seat for _, _, _, _, seat, _ in rows} == {0}


def test_legal_point_filter_and_boss_classification(corpus):
    _, ordered, _ = _load(corpus)
    checked = 0
    for _, _, _, rnd, seat, _ in common.iter_decisions(ordered):
        is_lead, winning, partner, _, to_act = common.trick_context(rnd, seat)
        if is_lead or winning is None:
            continue
        for action in common.legal_point_actions(rnd, seat):
            assert sum(points(c) for c in action) > 0
        cls, literal = common.classify_boss(
            rnd, seat, winning[0], winning[1], winning[2], to_act)
        assert cls in ("literal", "inferred_strict", "inferred_loose",
                       "open", "complex")
        assert literal == (cls == "literal")
        checked += 1
    assert checked > 0


def test_decision_key_is_stable_and_order_free():
    a = common.decision_key("m" * 64, "A.jsonl", 1, 3)
    assert a == common.decision_key("m" * 64, "A.jsonl", 1, 3)
    assert a != common.decision_key("m" * 64, "A.jsonl", 1, 4)


def _follow_state(hand: list[str]) -> Round:
    rnd = Round("2", 0, random.Random(9))
    rnd.phase = "play"
    rnd.banker = 0
    rnd.trump_suit = "S"
    rnd.ordering = Ordering("S", "2")
    rnd.hands = [[], [], list(hand), []]
    rnd.trick = Trick(
        leader=0,
        plays=[TrickPlay(0, ["H8"]), TrickPlay(1, ["H3"])],
    )
    rnd.turn = 2
    return rnd


def test_rollout_feed_denominator_requires_engine_legal_point_action():
    tallies = {key: Counter() for key in probes.TABLE_KEYS}
    bot = probes.CountingHeuristic(tallies)
    off_suit_only = _follow_state(["H4", "C5"])
    assert common.legal_point_actions(off_suit_only, 2) == []
    assert bot._follow(off_suit_only, 2) == ["H4"]
    assert sum(row["n"] for row in tallies.values()) == 0

    legal_point = _follow_state(["H5", "C3"])
    assert common.legal_point_actions(legal_point, 2) == [["H5"]]
    assert bot._follow(legal_point, 2) == ["H5"]
    assert sum(row["n"] for row in tallies.values()) == 1
    assert sum(row["fed"] for row in tallies.values()) == 1


def _binding_fixture():
    return {
        "action": ["H3"],
        "binding": {
            "before": {"rng": "a", "sampler": {"accepted_worlds": 0},
                       "counters": {"rollouts": 0}},
            "after": {"rng": "b", "sampler": {"accepted_worlds": 60},
                      "counters": {"rollouts": 330}},
            "counter_delta": {"rollouts": 330},
            "sampler_delta": {"accepted_worlds": 60},
            "record": {"work": {"total_rollouts": 330},
                       "n_by_candidate": [30, 30],
                       "report_work": {"worlds": 30}},
            "world_commitment_count": 60,
            "world_commitments_sha256": "c" * 64,
        },
    }


@pytest.mark.parametrize("mutation", [
    "post-rng", "world-order", "sampler-delta", "record-work",
    "candidate-work",
])
def test_objective_binding_drift_refuses(mutation):
    base = _binding_fixture()
    level = copy.deepcopy(base)
    level["action"] = ["D4"]  # objective actions may legitimately differ
    assert objective.require_same_binding(base, level) == \
        common.sha256_bytes(common.canonical(base["binding"]))
    if mutation == "post-rng":
        level["binding"]["after"]["rng"] = "changed"
    elif mutation == "world-order":
        level["binding"]["world_commitments_sha256"] = "d" * 64
    elif mutation == "sampler-delta":
        level["binding"]["sampler_delta"]["accepted_worlds"] = 59
    elif mutation == "record-work":
        level["binding"]["record"]["work"]["total_rollouts"] = 329
    elif mutation == "candidate-work":
        level["binding"]["record"]["n_by_candidate"] = [29, 31]
    with pytest.raises(SystemExit, match="RNG/world/work binding"):
        objective.require_same_binding(base, level)


def test_source_receipt_refuses_dirty_or_drifted_source(monkeypatch):
    real_git = common._git

    def dirty_git(*args):
        if args and args[0] == "status":
            return " M server/scripts/point_census/common.py\n"
        return real_git(*args)

    monkeypatch.setattr(common, "_git", dirty_git)
    with pytest.raises(SystemExit, match="tracked source tree is dirty"):
        common._source_receipt(SCRIPTS / "e1_census.py")

    def clean_git(*args):
        if args and args[0] == "status":
            return ""
        return real_git(*args)

    monkeypatch.setattr(common, "_git", clean_git)
    real_stable = common.stable_bytes

    def forged_bytes(path):
        if path == REPO / common.SOURCE_PATHS[0]:
            return b"forged source\n"
        return real_stable(path)

    monkeypatch.setattr(common, "stable_bytes", forged_bytes)
    with pytest.raises(SystemExit, match="source/Git drift"):
        common._source_receipt(SCRIPTS / "e1_census.py")


def _run_script(script: str, corpus, run_dir: Path, *extra: str,
                env_extra: dict[str, str] | None = None):
    logs, mpath, expected = corpus
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SERVER)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if env_extra:
        env.update(env_extra)
    command = [sys.executable, "-B", str(SCRIPTS / script)]
    if script == "manifest.py":
        command.append("check")
    command.extend([
        "--logs-dir", str(logs), "--manifest", str(mpath),
        "--expected-manifest-sha256", expected,
        *extra,
    ])
    return subprocess.run(
        command, cwd=run_dir, env=env, capture_output=True)


def test_all_headline_routes_stdout_only_and_receipt_bound(corpus, tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cases = [
        ("manifest.py", (), "VALID"),
        ("e1_census.py", (), "point-census-e1-v2"),
        ("e5_feed_ground_truth.py", (), "point-census-e5-v2"),
        ("p1_p2_rollout_probes.py", ("--rollout-states", "0"),
         "point-census-p1p2-v2"),
        ("e2_e3_search_objective.py", ("--cap-per-class", "0"),
         "point-census-e2e3-v2"),
    ]
    outputs = {}
    for script, extra, schema in cases:
        before = set(run_dir.iterdir())
        completed = _run_script(script, corpus, run_dir, *extra)
        assert completed.returncode == 0, (script, completed.stderr[-800:])
        assert set(run_dir.iterdir()) == before, f"{script} wrote files"
        value = json.loads(completed.stdout)
        outputs[script] = completed.stdout
        if script == "manifest.py":
            assert value["status"] == schema
            continue
        assert value["schema"] == schema
        receipt = value["receipt"]
        assert receipt["manifest_sha256"] == corpus[2]
        assert receipt["manifest_internal_sha256"] == corpus[2]
        assert receipt["tracked_tree_clean"] is True
        assert receipt["source_git"] == subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
            text=True, capture_output=True).stdout.strip()
        assert receipt["tool_path"].endswith(script)
        assert set(receipt["source_sha256s"]) == set(common.SOURCE_PATHS)
    assert json.loads(outputs["e1_census.py"])["decisions"] > 0
    assert json.loads(outputs["p1_p2_rollout_probes.py"])[
        "p1_rollout_states"] == 0
    assert all(not row for row in json.loads(
        outputs["e2_e3_search_objective.py"])["classes"].values())


def test_e1_output_is_deterministic(corpus, tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    first = _run_script("e1_census.py", corpus, run_dir)
    second = _run_script("e1_census.py", corpus, run_dir)
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout


def test_route_refuses_invalid_runtime_flag(corpus, tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    completed = _run_script(
        "e1_census.py", corpus, run_dir,
        env_extra={"SHENGJI_FAST": "sometimes"})
    assert completed.returncode != 0
    assert b"unsupported runtime flag value" in completed.stderr
