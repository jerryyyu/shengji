"""Boundaries for the telemetry-only bury/S6 capacity diagnostic."""
from __future__ import annotations

import copy
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import bury_lead_combo_capacity as C  # noqa: E402
import bury_lead_combo_population as P  # noqa: E402


def _row(offset: int = 0, combos: int = 3) -> dict:
    seed = P.DEAL_SEED0 + offset
    return {
        "state_id": f"{P.POPULATION_ID}:deal:{seed}:banker:{offset % 4}",
        "source_state_id":
            f"s3a-bury-pilot-v2:deal:{seed}:banker:{offset % 4}",
        "deal_seed": seed,
        "selection_group": "shape_rich",
        "selection_reason": "combo_count",
        "combo_count": combos,
    }


def _selection_summary() -> dict:
    return {
        "population_id": P.POPULATION_ID,
        "census_states": P.POPULATION_STATES,
        "shape_rich_states": 32,
        "hash_uniform_anchor_states": 32,
        "selected_states": 64,
        "selection_sha256": "a" * 64,
        "selection_rows_sha256": "b" * 64,
    }


def _runtime() -> dict:
    return {
        "git": "1" * 40,
        "tree_dirty": False,
        "python": "3.14.4",
        "fast_binary_sha256": "a" * 64,
        "population_source_sha256": "b" * 64,
        "scorer_source_sha256": "c" * 64,
        "continuation_source_sha256": "d" * 64,
        "journal_source_sha256": "e" * 64,
        "controller_source_sha256": "f" * 64,
    }


def _dose(mode: str) -> dict:
    counters = {name: 0 for name in C.CONTINUATION.S6_ROLLOUT_COUNTER_FIELDS}
    return {
        "schema": "s6-throw-rollout-dose-v1",
        "mode": mode,
        "deterministic": True,
        "actor_visible": True,
        "recursive_mc": False,
        "exploration_only": True,
        "before": None if mode == "baseline" else dict(counters),
        "after": None if mode == "baseline" else dict(counters),
        "delta": None if mode == "baseline" else dict(counters),
    }


def _work(count: int = 3) -> dict:
    return {
        "worlds_requested": 1,
        "worlds_used": 1,
        "attempts": 1,
        "attempt_cap": C.ATTEMPT_FACTOR,
        "candidate_rollouts": count,
        "requested_candidate_rollouts": count,
        "candidate_rollout_cap": count,
        "common_worlds": True,
        "complete": True,
    }


def _raw(mode: str, count: int = 3) -> dict:
    return {
        "schema": C.EXPLORE.SCHEMA,
        "status": "COMPLETE_EXPLORATION",
        "candidate_count": count,
        "scoring_contract": {
            "bot_class": "Bot",
            "baseline_rollout_policy_class": "HeuristicBot",
            "continuation_mode": mode,
            "continuation_policy_class": "HeuristicBot",
            "continuation_actor_visible": True,
            "recursive_mc_continuation": False,
            "level_objective": True,
            "exact_endgame": True,
            "perspective": "banker_value_is_negative_attacker_objective",
        },
        "continuation_dose": _dose(mode),
        "ballot": {"private candidates discarded": True},
        "rng_state": [3, [1, 2, 3], None],
        "work": _work(count),
        "sampler_counters": {
            "before": {},
            "after": {},
            "delta": {
                "sample_attempts": 1,
                "accepted_worlds": 1,
                "failed_worlds": 0,
                "rejected_worlds": 0,
                "impossible_worlds": 0,
            },
        },
    }


def _arm(mode: str, *, world: str = "9" * 64, count: int = 3) -> dict:
    return {
        "mode": mode,
        "state_id": _row(combos=count)["state_id"],
        "deal_seed": _row(combos=count)["deal_seed"],
        "candidate_count": count,
        "ballot_sha256": "3" * 64,
        "pre_rng_sha256": "4" * 64,
        "post_rng_sha256": "5" * 64,
        "sampled_world_commitment": world,
        "elapsed_seconds": 2.0,
        "work": _work(count),
        "sampler_delta": _raw(mode, count)["sampler_counters"]["delta"],
        "continuation_dose": _dose(mode),
        "raw_candidate_values_discarded": count,
    }


def _result() -> dict:
    arms = [_arm(mode) for mode in C.MODES]
    value = {
        "schema": C.SCHEMA,
        "runtime": _runtime(),
        "selection": _selection_summary(),
        "capacity_state": _row(),
        "arms": arms,
        "capacity_complete": True,
        "candidate_rollouts": 9,
        "total_arm_seconds": 6.0,
        "telemetry_only": True,
        "opened_reusable_dev": True,
        "source_outcomes_read": False,
        "outcomes_published": False,
        "confirmatory_inference": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    value["internal_sha256"] = C._digest(value)
    return value


def test_module_has_no_executable_review_or_authority_protocol():
    source = Path(C.__file__).read_text()
    assert "reviewer-attestation" not in source
    assert "PASS_OR_HOLD" not in source
    assert "execution_authorized" not in source
    assert not hasattr(C, "review_request_claim")
    assert not hasattr(C, "reviewer_attestation_claim")


def test_census_is_full_selection_is_32_plus_32_and_widest_wins(monkeypatch):
    seen = []
    rows = [_row(index, index + 1) for index in range(4)]
    materialized = {
        "selection": {
            "shape_rich": 32,
            "hash_uniform_anchor": 32,
            "total": 64,
            "rows": [rows[1], rows[3], rows[2]],
            "rows_sha256": "c" * 64,
        },
    }
    monkeypatch.setattr(P, "POPULATION_STATES", 4)
    monkeypatch.setattr(
        P, "census_state", lambda seed: seen.append(seed) or {"seed": seed})
    monkeypatch.setattr(P, "select_dev_states", lambda _rows: materialized)
    monkeypatch.setattr(P, "selection_problems", lambda _value: [])
    summary, row = C._selection()
    assert seen == [P.DEAL_SEED0 + index for index in range(4)]
    assert summary["shape_rich_states"] == 32
    assert summary["hash_uniform_anchor_states"] == 32
    assert row == rows[3]


class _Bot:
    def __init__(self, *, hidden=False):
        self.rng = random.Random(7)
        self.hidden = hidden

    def _sample_hands(self, _rnd, _seat, _memory):
        buried = ["H5"] if self.hidden else []
        return ([list("AA"), list("BB"), list("CC"), list("DD")], buried)


def _measured(monkeypatch, mode: str, *, mutate=None, hidden=False):
    bot = _Bot(hidden=hidden)
    monkeypatch.setattr(P, "build_bury_state", lambda *_: (
        SimpleNamespace(banker=0, phase="bury"), [], {}))
    monkeypatch.setattr(P, "make_bot", lambda *_args, **_kwargs: bot)
    monkeypatch.setattr(C.JOURNAL, "state_rng_seed", lambda *_: 7)

    def scorer(_rnd, _seat, *, bot, **_kwargs):
        bot._sample_hands(None, None, None)
        raw = _raw(mode)
        if mutate:
            mutate(raw)
        return raw

    ticks = iter((1.0, 3.0))
    return C._measure(
        mode, _row(), scorer=scorer, clock=lambda: next(ticks))


def test_measurement_retains_only_telemetry_and_commitment(monkeypatch):
    arm = _measured(monkeypatch, "all_boss")
    assert set(arm) == C.ARM_FIELDS
    assert arm["elapsed_seconds"] == 2.0
    assert arm["raw_candidate_values_discarded"] == 3
    serialized = json.dumps(arm)
    for forbidden in C.FORBIDDEN_KEYS:
        assert f'"{forbidden}"' not in serialized


@pytest.mark.parametrize("mutate", [
    lambda raw: raw["scoring_contract"].__setitem__(
        "recursive_mc_continuation", True),
    lambda raw: raw["scoring_contract"].__setitem__(
        "continuation_actor_visible", False),
    lambda raw: raw["work"].__setitem__("worlds_used", 0),
    lambda raw: raw["work"].__setitem__("winner_points", 80),
    lambda raw: raw["continuation_dose"].__setitem__("utility", 1.0),
])
def test_measurement_refuses_recursive_hidden_incomplete_or_open_schema(
        monkeypatch, mutate):
    with pytest.raises(C.CapacityRefused):
        _measured(monkeypatch, "boss_near", mutate=mutate)


def test_measurement_refuses_hidden_kitty(monkeypatch):
    with pytest.raises(C.CapacityRefused, match="hidden kitty"):
        _measured(monkeypatch, "baseline", hidden=True)


def test_result_requires_same_state_ballot_rng_and_sampled_world():
    assert C.result_problems(_result()) == []
    for field, replacement in (
            ("state_id", "different"),
            ("ballot_sha256", "0" * 64),
            ("pre_rng_sha256", "1" * 64),
            ("sampled_world_commitment", "2" * 64)):
        value = _result()
        value["arms"][2][field] = replacement
        material = dict(value)
        material.pop("internal_sha256")
        value["internal_sha256"] = C._digest(material)
        assert any("common-world" in item
                   for item in C.result_problems(value)), field


def test_closed_output_and_authority_boundary_refuse_rehashed_mutations():
    value = _result()
    value["production_deployment"] = True
    value["arms"][0]["attacker_points"] = 80
    value["arms"][1]["work"]["winner"] = 1
    material = dict(value)
    material.pop("internal_sha256")
    value["internal_sha256"] = C._digest(material)
    problems = C.result_problems(value)
    assert "authority boundary" in problems
    assert any("forbidden field" in problem for problem in problems)
    assert "arm fields" in problems


def test_atomic_output_refuses_overwrite_and_invalid_build(tmp_path):
    output = tmp_path / "capacity.json"
    result = _result()
    assert C.run(output, build=lambda: result) == result
    assert json.loads(output.read_bytes()) == result
    with pytest.raises(C.CapacityRefused, match="overwrite"):
        C.run(output, build=lambda: result)
    bad = copy.deepcopy(result)
    bad["strength_claim"] = True
    bad_output = tmp_path / "bad.json"
    with pytest.raises(C.CapacityRefused):
        C.run(bad_output, build=lambda: bad)
    assert not bad_output.exists()
