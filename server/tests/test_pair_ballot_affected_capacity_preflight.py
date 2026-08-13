"""Fail-closed tests for the score-free Pair V3 capacity preflight."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import pair_ballot_affected_capacity_preflight as C  # noqa: E402


def _review(path: Path, prefix: str, claim: dict) -> Path:
    path.write_text(prefix + json.dumps(
        claim, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def _runtime() -> dict:
    return {
        "host": "capacity-x86",
        "machine": "x86_64",
        "python": "3.14.4",
        "python_executable": "/usr/bin/python3.14",
        "cpu_count": 16,
        "memory_bytes": 32 * (1 << 30),
        "fast_required": True,
        "strict_voids_required": True,
        "fast_binary_sha256": "f" * 64,
    }


def _states() -> list[dict]:
    rows = []
    for index, (split, band) in enumerate(C.PREFLIGHT_CELLS):
        rows.append({
            "state_id": f"state-{index}",
            "state_sha256": f"{index + 1:064x}",
            "deal_seed": 100 + index,
            "split": split,
            "band": band,
            "role": "defender",
            "search_eligible": True,
            "trick": {"early": 1, "mid": 7, "late": 20}[band],
            "seat": index % 4,
        })
    return rows


def _manifest(rows: list[dict]) -> list[dict]:
    return [{
        "state_id": row["state_id"],
        "state_sha256": row["state_sha256"],
        "deal_seed": row["deal_seed"],
        "split": row["split"],
        "band": row["band"],
        "role": row["role"],
        "lane_index": row["deal_seed"] % C.DESIGN.SHARD_COUNT,
    } for row in rows]


def _packet(rows: list[dict]) -> dict:
    return {
        "git": "a" * 40,
        "internal_sha256": "b" * 64,
        "runtime": _runtime(),
        "preflight": {"states": _manifest(rows)},
    }


def _result() -> dict:
    counters = {
        "sample_attempts": 330,
        "accepted_worlds": 330,
        "failed_worlds": 0,
        "rejected_worlds": 0,
        "impossible_worlds": 0,
    }
    return {
        "current": {"sampler_counters": dict(counters)},
        "retained": {"sampler_counters": dict(counters)},
        "external_report": {
            "sampler": {"counters": {
                **counters, "sample_attempts": 300,
                "accepted_worlds": 300}},
        },
        "candidate_world_work": {
            "current_policy": C.DESIGN.POLICY_WORK_PER_STATE,
            "retained_policy": C.DESIGN.POLICY_WORK_PER_STATE,
            "external_report": 3 * C.EVAL.REPORT_WORLDS,
        },
        "policy_action_changed": True,
        "retained_raw_winner_is_inserted": True,
        "current_raw_winner_was_evicted": False,
    }


def _design() -> dict:
    lane = {"states_by_band": {"early": 56, "mid": 6, "late": 2}}
    return {
        "selection": {
            "states": 1_024,
            "states_by_band": {"early": 896, "mid": 96, "late": 32},
        },
        "schedule": {"lanes": [copy.deepcopy(lane) for _ in range(16)]},
    }


def test_expected_design_marker_uses_corrected_source_digests():
    claim = C.expected_design_review_claim()
    assert claim["identity_membership_sha256"] == \
        "57c835c8785db8c84fff78d19e84dcc7ea1b2ee74ea120065fdf7c75bc276e24"
    assert claim["defender_membership_sha256"] == \
        "8225e5f88b5b3a7d368d9715f9c3e9c5fc1a14df61486204168583e5511de9a4"
    assert claim["selection_sha256"] == \
        "3c9993bc8432d2fc419cfb75c2f766119de3aa4eacdf87dc3c238e1a484b29ab"


def test_design_review_requires_one_raw_exact_marker(tmp_path):
    claim = C.expected_design_review_claim()
    review = _review(tmp_path / "review.md", C.DESIGN_REVIEW_PREFIX, claim)
    assert C.parse_marker(
        review, C.DESIGN_REVIEW_PREFIX, claim,
        label="design review")["claim"] == claim

    review.write_text("    " + review.read_text())
    with pytest.raises(C.CapacityPreflightRefused, match="raw marker"):
        C.parse_marker(review, C.DESIGN_REVIEW_PREFIX, claim,
                       label="design review")

    review.write_text(
        C.DESIGN_REVIEW_PREFIX + json.dumps(claim) + "\n"
        + C.DESIGN_REVIEW_PREFIX + json.dumps(claim) + "\n")
    with pytest.raises(C.CapacityPreflightRefused, match="exactly one"):
        C.parse_marker(review, C.DESIGN_REVIEW_PREFIX, claim,
                       label="design review")


def test_manifest_covers_every_split_band_without_report():
    rows = _states()
    manifest = C.preflight_manifest({
        "states": rows + [{
            **copy.deepcopy(rows[0]), "state_id": "report",
            "state_sha256": "e" * 64, "deal_seed": 999,
            "split": "report",
        }]})
    assert {(row["split"], row["band"]) for row in manifest} \
        == set(C.PREFLIGHT_CELLS)
    assert len({row["deal_seed"] for row in manifest}) == 6
    assert all(row["split"] != "report" for row in manifest)
    assert all(row["role"] == "defender" for row in manifest)


def test_manifest_refuses_attacker_substitution():
    rows = _states()
    rows[0]["role"] = "attacker"
    with pytest.raises(C.CapacityPreflightRefused, match="no distinct defender"):
        C.preflight_manifest({"states": rows})


def test_runtime_requires_x86_capacity_and_strict_compiled_route(monkeypatch):
    monkeypatch.setattr(C.fast, "HAVE_FAST", True)
    monkeypatch.setattr(C.fast, "decompose", object())
    monkeypatch.setattr(C.combos, "decompose", C.fast.decompose)
    assert C.runtime_problems(_runtime()) == []
    for field, value, expected in (
            ("machine", "aarch64", "x86-64"),
            ("cpu_count", 15, "fewer than 16"),
            ("memory_bytes", 29 * (1 << 30), "less than 30"),
            ("strict_voids_required", False, "strict voids"),
            ("fast_binary_sha256", None, "unauthenticated")):
        runtime = _runtime()
        runtime[field] = value
        assert any(expected in problem for problem in C.runtime_problems(runtime))


def test_packet_reconstruction_refuses_authority_and_runtime_mutations(
        tmp_path, monkeypatch):
    review = _review(
        tmp_path / "review.md", C.DESIGN_REVIEW_PREFIX,
        C.expected_design_review_claim())
    rows = _states()
    fake_design = {
        "design_sha256": C.expected_design_review_claim()[
            "design_internal_sha256"],
        "selection": {"states": 1_024, "states_by_band": {
            "early": 896, "mid": 96, "late": 32}},
    }
    monkeypatch.setattr(C, "design_ref", lambda *_args: (
        fake_design, {"path": "design.json", "sha256": "d" * 64,
                      "internal_sha256": fake_design["design_sha256"],
                      "reviewed_git": C.DESIGN_GIT}))
    monkeypatch.setattr(C, "load_population", lambda _path: {"states": rows})
    monkeypatch.setattr(C.fast, "HAVE_FAST", True)
    monkeypatch.setattr(C.fast, "decompose", object())
    monkeypatch.setattr(C.combos, "decompose", C.fast.decompose)
    packet = C.packet_payload(
        expected_git="a" * 40, population_path=tmp_path / "population.json",
        design_path=tmp_path / "design.json",
        design_review_record=review, runtime=_runtime())
    assert packet["authority"] == {
        "one_score_free_preflight_execution_authorized": False,
        "capacity_result_review_authorized": True,
        "scored_packet_design_authorized": False,
        "scored_evaluation_authorized": False,
        "report_access_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    assert C.packet_problems(
        packet, expected_git="a" * 40,
        population_path=tmp_path / "population.json",
        design_path=tmp_path / "design.json",
        design_review_record=review) == []

    for mutate in (
            lambda value: value["authority"].__setitem__(
                "scored_evaluation_authorized", True),
            lambda value: value["population"].__setitem__(
                "report_permitted", True),
            lambda value: value["runtime"].__setitem__("machine", "aarch64"),
            lambda value: value["preflight"].__setitem__("state_count", 5)):
        changed = copy.deepcopy(packet)
        mutate(changed)
        changed["internal_sha256"] = C.digest(
            {key: item for key, item in changed.items()
             if key != "internal_sha256"})
        assert C.packet_problems(
            changed, expected_git="a" * 40,
            population_path=tmp_path / "population.json",
            design_path=tmp_path / "design.json",
            design_review_record=review)


def test_score_free_guard_rejects_nested_outcomes():
    safe = {"score_free": True, "outcomes_published": False,
            "selector_dose": {"policy_action_changes": 2}}
    assert C.score_free_result_problems(safe) == []
    for key in ("estimands", "raw_attacker_points", "attacker_points",
                "level_change", "cards", "records"):
        changed = copy.deepcopy(safe)
        changed["nested"] = {key: []}
        assert C.score_free_result_problems(changed)


def test_measurement_discards_outcomes_and_projects_exact_band_mix(monkeypatch):
    rows = _states()
    monkeypatch.setattr(C, "load_population", lambda _path: {"states": rows})
    monkeypatch.setattr(C.EVAL, "evaluate_state",
                        lambda *_args, **_kwargs: _result())
    monkeypatch.setattr(C.AGG, "_validate_result", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(C.AGG, "_validate_source_binding",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(C.DESIGN, "build_design", lambda _path: _design())
    ticks = iter((0.0, 1.0, 1.0, 3.0, 3.0, 4.0,
                  4.0, 6.0, 6.0, 7.0, 7.0, 9.0))
    result = C.measure_preflight(
        _packet(rows), Path("unused"), clock=lambda: next(ticks))
    assert result["records_discarded"] == 6
    assert result["selector_dose"] == {
        "current_raw_winner_evictions": 0,
        "policy_action_changes": 6,
        "retained_raw_winner_insertions": 6,
    }
    assert result["projection"]["normalized_seconds_per_state_by_band"] == {
        "early": 1.5, "late": 1.5, "mid": 1.5}
    assert result["projection"]["fleet_hours"] == pytest.approx(
        1_024 * 1.5 * 2 / 3_600)
    assert result["projection"]["max_lane_wall_hours"] == pytest.approx(
        64 * 1.5 * 2 / 3_600)
    assert result["criteria"]["all"] is True
    assert result["status"] == "AUTHORIZE_CAPACITY_RESULT_REVIEW"
    assert result["scored_packet_design_authorized"] is False
    assert result["scored_evaluation_authorized"] is False
    assert C.score_free_result_problems(result) == []


def test_measurement_refuses_report_or_incomplete_work(monkeypatch):
    rows = _states()
    rows[0]["split"] = "report"
    monkeypatch.setattr(C, "load_population", lambda _path: {"states": rows})
    with pytest.raises(C.CapacityPreflightRefused, match="identity drift"):
        C.measure_preflight(_packet(_states()), Path("unused"))

    rows = _states()
    bad = _result()
    bad["candidate_world_work"]["current_policy"] -= 1
    monkeypatch.setattr(C, "load_population", lambda _path: {"states": rows})
    monkeypatch.setattr(C.EVAL, "evaluate_state",
                        lambda *_args, **_kwargs: bad)
    monkeypatch.setattr(C.AGG, "_validate_result", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(C.AGG, "_validate_source_binding",
                        lambda *_args, **_kwargs: None)
    ticks = iter((0.0, 1.0))
    with pytest.raises(C.CapacityPreflightRefused, match="exact work drift"):
        C.measure_preflight(
            _packet(rows), Path("unused"), clock=lambda: next(ticks))


def test_packet_review_authorizes_only_one_score_free_preflight():
    claim = C.packet_review_claim(
        expected_git="a" * 40, packet_sha256="b" * 64,
        packet_internal_sha256="c" * 64)
    assert claim["one_score_free_preflight_authorized"] is True
    assert claim["scored_evaluation_authorized"] is False
    assert claim["report_access_authorized"] is False
    assert claim["strength_claim"] is False


def test_missing_packet_review_refuses_before_admission_or_gameplay(
        tmp_path, monkeypatch):
    admission = tmp_path / "admission.json"
    result = tmp_path / "result.json"
    review_copy = tmp_path / "packet-review.md"
    design_review = tmp_path / "design-review.md"
    monkeypatch.setattr(C, "ADMISSION_PATH", admission)
    monkeypatch.setattr(C, "RESULT_PATH", result)
    monkeypatch.setattr(C, "PACKET_REVIEW_PATH", review_copy)
    monkeypatch.setattr(C, "DESIGN_REVIEW_PATH", design_review)
    monkeypatch.setattr(C, "require_exact_clean_git", lambda _git: None)
    packet = _packet(_states())
    monkeypatch.setattr(C, "load_packet", lambda *_args, **_kwargs: packet)
    monkeypatch.setattr(C, "require_qualified_runtime",
                        lambda: packet["runtime"])
    called = False

    def measure(*_args, **_kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(C, "measure_preflight", measure)
    args = SimpleNamespace(
        expected_git="a" * 40, population="population.json",
        design="design.json", packet="packet.json",
        expected_packet_sha256="d" * 64,
        packet_review_record=str(tmp_path / "missing.md"),
        admission=str(admission), out=str(result))
    with pytest.raises(C.CapacityPreflightRefused, match="review is missing"):
        C.run_command(args)
    assert not admission.exists()
    assert called is False


def test_admission_is_consumed_before_measurement(tmp_path, monkeypatch):
    admission = tmp_path / "admission.json"
    result = tmp_path / "result.json"
    review_copy = tmp_path / "packet-review.md"
    design_review = tmp_path / "design-review.md"
    monkeypatch.setattr(C, "ADMISSION_PATH", admission)
    monkeypatch.setattr(C, "RESULT_PATH", result)
    monkeypatch.setattr(C, "PACKET_REVIEW_PATH", review_copy)
    monkeypatch.setattr(C, "DESIGN_REVIEW_PATH", design_review)
    monkeypatch.setattr(C, "require_exact_clean_git", lambda _git: None)
    packet = _packet(_states())
    monkeypatch.setattr(C, "load_packet", lambda *_args, **_kwargs: packet)
    monkeypatch.setattr(C, "require_qualified_runtime",
                        lambda: packet["runtime"])
    claim = C.packet_review_claim(
        expected_git="a" * 40, packet_sha256="d" * 64,
        packet_internal_sha256=packet["internal_sha256"])
    review = _review(tmp_path / "review.md", C.PACKET_REVIEW_PREFIX, claim)

    def fail_after_admission(*_args, **_kwargs):
        assert admission.exists()
        raise C.CapacityPreflightRefused("synthetic worker failure")

    monkeypatch.setattr(C, "measure_preflight", fail_after_admission)
    args = SimpleNamespace(
        expected_git="a" * 40, population="population.json",
        design="design.json", packet="packet.json",
        expected_packet_sha256="d" * 64,
        packet_review_record=str(review), admission=str(admission),
        out=str(result))
    with pytest.raises(C.CapacityPreflightRefused, match="synthetic"):
        C.run_command(args)
    consumed = json.loads(admission.read_bytes())
    assert consumed["one_score_free_preflight_authorized"] is True
    assert consumed["scored_evaluation_authorized"] is False
    assert not result.exists()


def test_module_has_no_full_scored_launcher_surface():
    source = Path(C.__file__).read_text()
    assert "run_shard(" not in source
    assert "defender_combined_summary(" not in source
    assert "REPORT" not in {split for split, _band in C.PREFLIGHT_CELLS}
