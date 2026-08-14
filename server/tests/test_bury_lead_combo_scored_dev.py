"""Fail-closed tests for the reviewed two-fold bury/S6 scorer."""
from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import bury_lead_combo_scored_dev as SCORE  # noqa: E402


class MCS0ReportLCB:
    LEVEL_OBJECTIVE = False
    EXACT_ENDGAME = False

    def __init__(self, seed):
        self.seed = seed
        self._candidates = object()
        self.rollout_policy = SimpleNamespace(mode="baseline")

    @staticmethod
    def _score(points):
        return points


def _candidate(index, *, live=False):
    return SimpleNamespace(
        cards=[f"L{index}", f"L{index}"],
        sources=["live_ballot:test"] if live else ["s6:test"],
        pair_lead=index % 2 == 0,
        structured_throw=index % 3 == 0,
    )


def _ballot(count):
    group0 = SimpleNamespace(
        bury=SimpleNamespace(cards=["B0"], sources=["incumbent"]),
        leads=[_candidate(0, live=True), _candidate(1)],
    )
    group1 = SimpleNamespace(
        bury=SimpleNamespace(cards=["B1"], sources=["expanded"]),
        leads=[_candidate(index) for index in range(2, count)],
    )
    return SimpleNamespace(
        groups=[group0, group1], combo_count=count,
        record=lambda: {"combo_count": count})


def _sampler(prefix):
    return {
        "worlds": 30,
        "attempts": 30,
        "attempt_cap": 600,
        "pre_rng_sha256": "1" * 64,
        "post_rng_sha256": "2" * 64,
        "sampler_before_sha256": "3" * 64,
        "sampler_after_sha256": "4" * 64,
        "sampler_delta": {
            "sample_attempts": 30, "accepted_worlds": 30,
            "failed_worlds": 0, "rejected_worlds": 0,
            "impossible_worlds": 0,
        },
        "world_commitments": [
            SCORE.digest({"fold": prefix, "index": index})
            for index in range(30)
        ],
    }


def _dose(mode):
    if mode == "baseline":
        return {
            "schema": "s6-throw-rollout-dose-v1", "mode": mode,
            "deterministic": True, "actor_visible": True,
            "recursive_mc": False, "exploration_only": True,
            "before": None, "after": None, "delta": None,
        }
    counters = {
        field: (1 if field == "play_calls" else 0)
        for field in SCORE.S6_ROLLOUT_COUNTER_FIELDS
    }
    zero = {field: 0 for field in SCORE.S6_ROLLOUT_COUNTER_FIELDS}
    return {
        "schema": "s6-throw-rollout-dose-v1", "mode": mode,
        "deterministic": True, "actor_visible": True,
        "recursive_mc": False, "exploration_only": True,
        "before": zero, "after": counters, "delta": counters,
    }


@pytest.fixture
def record(monkeypatch):
    seed, count, _, _ = SCORE.DESIGN.SELECTION_ROWS[0]
    ballot = _ballot(count)
    rnd = SimpleNamespace(phase="bury", banker=0)
    monkeypatch.setattr(
        SCORE.POPULATION, "census_state", lambda *args, **kwargs: {
            "state_id": (
                f"{SCORE.DESIGN.POPULATION_ID}:deal:{seed}:banker:0"),
            "source_state_id": f"s3a-bury-pilot-v2:deal:{seed}:banker:0",
            "source_input_sha256": "a" * 64,
            "source_replay_sha256": "b" * 64,
            "combo_count": count,
        })
    monkeypatch.setattr(
        SCORE, "build_bury_lead_combo_ballot",
        lambda *args, **kwargs: ballot)
    monkeypatch.setattr(
        SCORE, "_sample_worlds",
        lambda rnd, seat, *, bot, worlds, attempt_factor: (
            [{"world": index} for index in range(30)],
            _sampler("selection" if bot.seed == SCORE.DESIGN.SELECTION_BASE_SEED
                     else "report")))
    monkeypatch.setattr(
        SCORE, "make_s6_continuation_policy",
        lambda mode, baseline: SimpleNamespace(mode=mode))
    monkeypatch.setattr(SCORE, "_dose", lambda policy, before, *, mode: _dose(mode))

    def rollout(bot, rnd, seat, world, bury, lead, *, continuation_policy):
        index = int(lead[0][1:])
        bonus = {"baseline": 0, "all_boss": 10, "boss_near": 20}[
            continuation_policy.mode]
        actual = list(lead) if index % 3 else [lead[0]]
        attacker_points = 1_000 - index - bonus
        return {
            "banker_value": -float(attacker_points),
            "attacker_points": attacker_points,
            "attempted_lead": list(lead),
            "actual_lead": actual,
            "lead_succeeded": sorted(lead) == sorted(actual),
        }

    value = SCORE.score_state(
        seed, state_builder=lambda *args: (rnd, ["incumbent"], {}),
        bot_factory=lambda champion, seed: MCS0ReportLCB(seed),
        rollout=rollout)
    assert SCORE.record_problems(value, expected_seed=seed) == []
    return value


def _rehash(value):
    material = dict(value)
    material.pop("internal_sha256", None)
    value["internal_sha256"] = SCORE.digest(material)
    return value


def test_score_state_freezes_nested_slots_and_common_report_worlds(record):
    count = record["candidate_count"]
    assert record["selection"]["selected_indices"] == {
        "incumbent_live": 0,
        "incumbent_widened": 1,
        "expanded": count - 1,
    }
    commitments = [
        record["report"]["modes"][mode]["world_commitments"]
        for mode in SCORE.MODES
    ]
    assert commitments[0] == commitments[1] == commitments[2]
    assert record["work"]["selection_candidate_rollouts"] == count * 30
    assert record["work"]["report_candidate_rollouts_per_mode"] == 90
    assert record["work"]["total_candidate_rollouts"] == count * 30 + 270


def test_producer_record_round_trip_exposes_only_canonical_mode_order(record):
    raw = SCORE.canonical(record)
    reparsed = json.loads(raw)
    seed = record["deal_seed"]
    assert list(record["report"]["modes"]) == list(SCORE.MODES)
    assert list(reparsed["report"]["modes"]) == sorted(SCORE.MODES)
    assert SCORE.record_problems(reparsed, expected_seed=seed) == [
        "report fold contract drift"]

    validation = dict(reparsed)
    report = dict(reparsed["report"])
    modes = reparsed["report"]["modes"]
    report["modes"] = {mode: modes[mode] for mode in SCORE.MODES}
    validation["report"] = report
    assert SCORE.canonical(validation) == raw
    assert SCORE.record_problems(validation, expected_seed=seed) == []


def test_lowest_index_wins_an_exact_tie():
    assert SCORE._winner([5, 2, 7], [0.0] * 8) == 2


@pytest.mark.parametrize("mutate, expected", [
    (lambda value: (
        value["selection"]["selected_indices"].update(expanded=0),
        value["selection"]["selected_candidates"].update(
            expanded=copy.deepcopy(
                value["selection"]["candidate_metadata"][0]))),
     "winner/menu"),
    (lambda value: value["selection"]["candidate_metadata"][0].update(
        live_lead=False), "winner/menu"),
    (lambda value: value["selection"]["sampler"]["sampler_delta"].update(
        impossible_worlds=1), "sampler"),
    (lambda value: value["report"]["modes"]["all_boss"][
        "world_commitments"].__setitem__(0, "f" * 64), "common-world"),
    (lambda value: value["report"]["modes"]["boss_near"]["continuation_dose"][
        "delta"].update(play_calls=0), "continuation-dose"),
    (lambda value: value["report"]["modes"]["baseline"]["rows"][0][
        "slot_outcomes"][0].update(lead_succeeded=True), "outcome"),
    (lambda value: value["work"].update(total_candidate_rollouts=1),
     "exact work"),
    (lambda value: value.update(execution_authorized=True), "field population"),
])
def test_rehashed_record_mutations_refuse(record, mutate, expected):
    forged = copy.deepcopy(record)
    mutate(forged)
    _rehash(forged)
    assert any(expected in problem for problem in SCORE.record_problems(
        forged, expected_seed=record["deal_seed"]))


def test_scorer_has_no_cli_writer_or_process_surface():
    source = Path(SCORE.__file__).read_text()
    tree = ast.parse(source)
    imports = {
        alias.name for node in ast.walk(tree)
        if isinstance(node, ast.Import) for alias in node.names
    }
    assert not imports.intersection({"argparse", "os", "subprocess"})
    assert "__main__" not in source
    assert ".write" not in source


def test_record_validator_refuses_malformed_values_without_raising(record):
    paths = []

    def walk(value, path=()):
        if isinstance(value, dict):
            for key, child in value.items():
                if key != "internal_sha256":
                    paths.append(path + (key,))
                    walk(child, path + (key,))
        elif isinstance(value, list):
            for index, child in enumerate(value[:2]):
                paths.append(path + (index,))
                walk(child, path + (index,))

    def replace(value, path, replacement):
        cursor = value
        for step in path[:-1]:
            cursor = cursor[step]
        cursor[path[-1]] = replacement

    def locate(value, path):
        for step in path:
            value = value[step]
        return value

    walk(record)
    for path in paths:
        for replacement in (None, True, 0, "x", {}, []):
            if locate(record, path) == replacement:
                continue
            forged = copy.deepcopy(record)
            replace(forged, path, replacement)
            _rehash(forged)
            problems = SCORE.record_problems(
                forged, expected_seed=record["deal_seed"])
            if ("slot_outcomes" in path
                    and path[-1] in {"banker_value", "attacker_points"}):
                # Outcome values are authenticated by immutable bytes and a
                # later replaying reviewer, not inferred by the schema check.
                continue
            assert problems, f"undetected malformed path={path!r} value={replacement!r}"
