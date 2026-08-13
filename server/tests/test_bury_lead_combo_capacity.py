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

GIT = "1" * 40


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
    row = _row()
    return {
        "population_id": P.POPULATION_ID,
        "census_states": P.POPULATION_STATES,
        "shape_rich_states": 32,
        "hash_uniform_anchor_states": 32,
        "selected_states": 64,
        "selection_sha256": "a" * 64,
        "selection_rows_sha256": "b" * 64,
        "widest_state_sha256": C._digest(row),
    }


def _runtime() -> dict:
    return {
        "git": GIT,
        "tree_dirty": False,
        "python": C.EXPECTED_PYTHON,
        "fast_binary_sha256": "a" * 64,
        "population_source_sha256": "b" * 64,
        "scorer_source_sha256": "c" * 64,
        "continuation_source_sha256": "d" * 64,
        "journal_source_sha256": "e" * 64,
        "controller_source_sha256": "f" * 64,
    }


def _dose(mode: str) -> dict:
    before = {name: 0 for name in C.CONTINUATION.S6_ROLLOUT_COUNTER_FIELDS}
    counters = dict(before)
    if mode != "baseline":
        counters["play_calls"] = 1
    return {
        "schema": "s6-throw-rollout-dose-v1",
        "mode": mode,
        "deterministic": True,
        "actor_visible": True,
        "recursive_mc": False,
        "exploration_only": True,
        "before": None if mode == "baseline" else before,
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
            "bot_class": "MCS0ReportLCB",
            "baseline_rollout_policy_class": "HeuristicBot",
            "continuation_mode": mode,
            "continuation_policy_class": (
                "HeuristicBot" if mode == "baseline"
                else "S6ThrowRolloutPolicy"),
            "continuation_actor_visible": True,
            "recursive_mc_continuation": False,
            "level_objective": False,
            "exact_endgame": False,
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


def test_widest_state_uses_lexical_state_id_tie_break(monkeypatch):
    first = _row(1, 9)
    second = _row(2, 9)
    assert first["state_id"] < second["state_id"]
    materialized = {
        "selection": {
            "shape_rich": 32,
            "hash_uniform_anchor": 32,
            "total": 64,
            "rows": [second, first],
            "rows_sha256": "c" * 64,
        },
    }
    monkeypatch.setattr(P, "POPULATION_STATES", 2)
    monkeypatch.setattr(P, "census_state", lambda seed: {"seed": seed})
    monkeypatch.setattr(P, "select_dev_states", lambda _rows: materialized)
    monkeypatch.setattr(P, "selection_problems", lambda _value: [])
    _, row = C._selection()
    assert row == first


class _Bot:
    def __init__(self, *, hidden=False):
        self.rng = random.Random(7)
        self.hidden = hidden

    def _sample_hands(self, _rnd, _seat, _memory):
        buried = ["H5"] if self.hidden else []
        return ([list("AA"), list("BB"), list("CC"), list("DD")], buried)


def _measured(monkeypatch, mode: str, *, mutate=None, hidden=False, banker=0):
    bot = _Bot(hidden=hidden)
    monkeypatch.setattr(P, "build_bury_state", lambda *_: (
        SimpleNamespace(banker=banker, phase="bury"), [], {}))
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
    lambda raw: raw["scoring_contract"].__setitem__("exact_endgame", True),
    lambda raw: raw["scoring_contract"].__setitem__(
        "continuation_policy_class", "RecursiveMCBot"),
    lambda raw: raw["sampler_counters"]["delta"].__setitem__(
        "impossible_worlds", 1),
])
def test_measurement_refuses_recursive_hidden_incomplete_or_open_schema(
        monkeypatch, mutate):
    with pytest.raises(C.CapacityRefused):
        _measured(monkeypatch, "boss_near", mutate=mutate)


def test_measurement_refuses_hidden_kitty(monkeypatch):
    with pytest.raises(C.CapacityRefused, match="hidden kitty"):
        _measured(monkeypatch, "baseline", hidden=True)


def test_measurement_requires_nonbaseline_execution_and_exact_banker(
        monkeypatch):
    def zero_dose(raw):
        for snapshot in ("after", "delta"):
            raw["continuation_dose"][snapshot]["play_calls"] = 0

    with pytest.raises(C.CapacityRefused, match="did not execute"):
        _measured(monkeypatch, "all_boss", mutate=zero_dose)
    with pytest.raises(C.CapacityRefused, match="banker differs"):
        _measured(monkeypatch, "boss_near", banker=1)


def test_result_requires_same_state_ballot_rng_and_sampled_world():
    assert C.result_problems(_result()) == []
    for field, replacement in (
            ("state_id", "different"),
            ("ballot_sha256", "0" * 64),
            ("pre_rng_sha256", "1" * 64),
            ("post_rng_sha256", "6" * 64),
            ("sampled_world_commitment", "2" * 64)):
        value = _result()
        value["arms"][2][field] = replacement
        material = dict(value)
        material.pop("internal_sha256")
        value["internal_sha256"] = C._digest(material)
        assert any("common-world" in item
                   for item in C.result_problems(value)), field


def test_result_requires_common_sampler_attempts_and_widest_row_binding():
    value = _result()
    value["arms"][1]["work"]["attempts"] = 2
    value["arms"][1]["sampler_delta"].update({
        "sample_attempts": 2,
        "failed_worlds": 1,
    })
    material = dict(value)
    material.pop("internal_sha256")
    value["internal_sha256"] = C._digest(material)
    problems = C.result_problems(value)
    assert "common-world work" in problems
    assert "common-world sampler_delta" in problems

    value = _result()
    state = value["capacity_state"]
    banker = (int(str(state["state_id"]).rsplit(":", 1)[-1]) + 1) % 4
    state["state_id"] = (
        f"{P.POPULATION_ID}:deal:{state['deal_seed']}:banker:{banker}")
    state["source_state_id"] = (
        f"s3a-bury-pilot-v2:deal:{state['deal_seed']}:banker:{banker}")
    for arm in value["arms"]:
        arm["state_id"] = state["state_id"]
    material = dict(value)
    material.pop("internal_sha256")
    value["internal_sha256"] = C._digest(material)
    assert "selection fields" in C.result_problems(value)


def test_result_refuses_balanced_negative_timing_and_nonzero_prior_dose():
    value = _result()
    value["arms"][0]["elapsed_seconds"] = -1.0
    value["arms"][1]["elapsed_seconds"] = 3.0
    value["total_arm_seconds"] = 4.0
    before = value["arms"][1]["continuation_dose"]["before"]
    after = value["arms"][1]["continuation_dose"]["after"]
    for key in before:
        before[key] = 5
        after[key] = 5
    material = dict(value)
    material.pop("internal_sha256")
    value["internal_sha256"] = C._digest(material)
    assert "baseline arm contract" in C.result_problems(value)
    assert "all_boss arm contract" in C.result_problems(value)


def test_runtime_requires_exact_exploration_head_and_python(monkeypatch):
    monkeypatch.setattr(C.JOURNAL, "strict_runtime", lambda: _runtime())
    monkeypatch.setattr(C, "_sha256", lambda _path: "f" * 64)
    assert C._runtime(GIT)["git"] == GIT
    bad = _runtime()
    bad["git"] = "0" * 40
    monkeypatch.setattr(C.JOURNAL, "strict_runtime", lambda: bad)
    with pytest.raises(C.CapacityRefused, match="runtime identity"):
        C._runtime(GIT)
    with pytest.raises(C.CapacityRefused, match="full lowercase"):
        C._runtime("main")
    assert "runtime fields" in C.result_problems(
        _result(), expected_git="0" * 40)
    bad = _runtime()
    bad["python"] = "3.15.0"
    monkeypatch.setattr(C.JOURNAL, "strict_runtime", lambda: bad)
    with pytest.raises(C.CapacityRefused, match="runtime identity"):
        C._runtime(GIT)


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


@pytest.mark.parametrize(("field", "replacement"), [
    ("selection_reason", "attacker_points=225"),
    ("selection_reason", "uniform_anchor"),
    ("source_state_id", "sealed/REPORT/outcome.json"),
    ("selection_group", "hash_uniform_anchor"),
    ("selection_group", "report_selected"),
])
def test_capacity_row_refuses_outcome_or_report_aliases(field, replacement):
    value = _result()
    value["capacity_state"][field] = replacement
    material = dict(value)
    material.pop("internal_sha256")
    value["internal_sha256"] = C._digest(material)
    assert "capacity state" in C.result_problems(value)


def test_capacity_row_accepts_each_exact_group_reason_pair():
    shape = _row()
    assert C._row_problems(shape) == []
    anchor = _row(1)
    anchor.update({
        "selection_group": "hash_uniform_anchor",
        "selection_reason": "uniform_anchor",
    })
    assert C._row_problems(anchor) == []


def test_atomic_output_refuses_overwrite_and_invalid_build(tmp_path):
    output = tmp_path / "capacity.json"
    result = _result()
    assert C.run(output, GIT, build=lambda: result) == result
    assert json.loads(output.read_bytes()) == result
    with pytest.raises(C.CapacityRefused, match="overwrite"):
        C.run(output, GIT, build=lambda: result)
    bad = copy.deepcopy(result)
    bad["strength_claim"] = True
    bad_output = tmp_path / "bad.json"
    with pytest.raises(C.CapacityRefused):
        C.run(bad_output, GIT, build=lambda: bad)
    assert not bad_output.exists()


def test_concurrent_writer_created_during_build_is_preserved(tmp_path):
    output = tmp_path / "capacity.json"

    def racing_build():
        output.write_text("rival\n")
        return _result()

    with pytest.raises(C.CapacityRefused, match="overwrite"):
        C.run(output, GIT, build=racing_build)
    assert output.read_text() == "rival\n"
