"""Synthetic contract tests for the generic report-LCB performance A/B."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import report_lcb_perf_ab as harness


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _design(tmp_path: Path) -> dict:
    sources = {
        "server/shengji/ai/mcbot.py": "1" * 64,
        "server/shengji/engine/round.py": "2" * 64,
    }
    identity = {
        "repo": str(tmp_path / "base"),
        "git": "a" * 40,
        "source_sha256s": sources,
        "native": {
            "path": "server/shengji/engine/_fast.test.so",
            "sha256": "3" * 64,
        },
    }
    head = copy.deepcopy(identity)
    head["repo"] = str(tmp_path / "head")
    head["git"] = "b" * 40
    head["source_sha256s"] = {
        key: ("4" * 64 if key.endswith("round.py") else value)
        for key, value in sources.items()
    }
    return {
        "schema": harness.DESIGN_SCHEMA,
        "claim_boundary": copy.deepcopy(harness.CLAIM_BOUNDARY),
        "experiment": {
            "id": "synthetic-report-lcb-perf-ab-v1",
            "policy": harness.POLICY,
            "n_determinizations": 30,
            "report_fold_worlds": 300,
            "seeds": [101, 103, 107, 109],
            "orders": [
                "base_head", "head_base", "head_base", "base_head"],
            "capture_excluded_fields":
                list(harness.CAPTURE_EXCLUDED_FIELDS),
            "normalization_removed_fields":
                list(harness.NORMALIZED_BALLOT_FIELDS),
            "retention": {
                "statistic": "aggregate_wall_reduction_percent",
                "minimum_percent": 3.0,
            },
        },
        "evidence_root": str(tmp_path / "evidence"),
        "python": {
            "executable": "/opt/example/python",
            "resolved": "/opt/example/python3.14",
            "version": "3.14.4",
            "sha256": "5" * 64,
        },
        "harness": {
            "path": "/opt/example/report_lcb_perf_ab.py",
            "sha256": "6" * 64,
        },
        "base": identity,
        "head": head,
    }


def _sampler(offset: int = 0) -> dict[str, int]:
    return {
        "sample_attempts": offset,
        "accepted_worlds": offset,
        "failed_worlds": 0,
        "rejected_worlds": 0,
        "impossible_worlds": 0,
    }


def _snapshot(*, rng: int = 7, sampler: int = 0, rollouts: int = 0,
              searches: int = 0) -> dict:
    return {
        "rng_state": [3, [rng, rng + 1], None],
        "sampler": _sampler(sampler),
        "rollouts": rollouts,
        "search_calls": searches,
        "short_search_decisions": 0,
        "zero_world_decisions": 0,
        "bury_search_calls": 0,
        "bury_rollouts": 0,
        "bury_short_searches": 0,
    }


def _searched_decision(*, ballot_suffix: str = "base") -> dict:
    before = _snapshot(rng=11, sampler=4)
    after = _snapshot(rng=12, sampler=334, rollouts=660, searches=1)
    return {
        "action": ["H4"],
        "before": before,
        "after": after,
        "record": {
            "policy": harness.POLICY,
            "n_determinizations": 30,
            "report_worlds_requested": 300,
            "played": ["H4"],
            "candidates": [["H3"], ["H4"]],
            "worlds": 30,
            "n_by_candidate": [30, 30],
            "rng_state": copy.deepcopy(before["rng_state"]),
            "sampler_counters": {
                "before": copy.deepcopy(before["sampler"]),
                "after": copy.deepcopy(after["sampler"]),
                "delta": {
                    key: after["sampler"][key] - before["sampler"][key]
                    for key in harness.SAMPLER_KEYS
                },
            },
            "report_fold": {"complete": True, "worlds": 300},
            "work": {
                "selection_budget": 60,
                "selection_rollouts": 60,
                "report_budget": 600,
                "report_rollouts": 600,
                "total_budget": 660,
                "total_rollouts": 660,
                "complete": True,
            },
            "ballot": {
                "digest": f"digest-{ballot_suffix}",
                "display": f"display-{ballot_suffix}",
                "source_digest": f"source-{ballot_suffix}",
                "candidates": [["H3"], ["H4"]],
            },
        },
    }


def _arm(*, ballot_suffix: str = "base") -> dict:
    forced = _snapshot(rng=5)
    searched = _searched_decision(ballot_suffix=ballot_suffix)
    return {
        "schema": harness.ARM_SCHEMA,
        "seed": 101,
        "policy": harness.POLICY,
        "trump_rank": "2",
        "banker": 0,
        "attacker_points": 80,
        "winner_team": "attackers",
        "level_change": 1,
        "history": [[0, ["S5", "S5"]], [1, ["H4"]]],
        "decision_records": [
            [{
                "action": ["S5", "S5"],
                "record": None,
                "before": copy.deepcopy(forced),
                "after": copy.deepcopy(forced),
            }],
            [searched],
            [],
            [],
        ],
        "final_bots": [
            copy.deepcopy(forced), copy.deepcopy(searched["after"]),
            _snapshot(rng=21), _snapshot(rng=31),
        ],
    }


def test_design_requires_balanced_fresh_batch_and_exact_identities(tmp_path):
    design = _design(tmp_path)
    assert harness.design_problems(design) == []

    unbalanced = copy.deepcopy(design)
    unbalanced["experiment"]["orders"] = ["base_head"] * 4
    assert "execution order is not exactly balanced" in \
        harness.design_problems(unbalanced)

    retryable = copy.deepcopy(design)
    retryable["claim_boundary"]["one_batch_no_retry_or_tuning"] = False
    assert "claim boundary drift" in harness.design_problems(retryable)

    source_gap = copy.deepcopy(design)
    source_gap["head"]["source_sha256s"].pop(
        "server/shengji/engine/round.py")
    assert "base/head source path sets differ" in \
        harness.design_problems(source_gap)

    native_gap = copy.deepcopy(design)
    native_gap["head"]["native"]["sha256"] = "not-a-sha"
    assert any("head native SHA" in problem
               for problem in harness.design_problems(native_gap))


def test_forced_no_search_is_valid_counted_and_disclosed(tmp_path):
    summary = harness.validate_arm_semantics(
        _arm(), _design(tmp_path), 101)
    assert summary == {
        "history_plays": 2,
        "searched_decisions": 1,
        "forced_no_search_decisions": 1,
        "engine_adjusted_plays": 0,
        "searched_decisions_by_seat": [0, 1, 0, 0],
        "forced_no_search_decisions_by_seat": [1, 0, 0, 0],
        "engine_adjusted_plays_by_seat": [0, 0, 0, 0],
    }


@pytest.mark.parametrize("field", [
    "rng_state", "sampler", "rollouts", "search_calls",
])
def test_forced_no_search_must_leave_rng_sampler_and_work_unchanged(
        tmp_path, field):
    arm = _arm()
    after = arm["decision_records"][0][0]["after"]
    if field == "rng_state":
        after[field][1][0] += 1
    elif field == "sampler":
        after[field]["sample_attempts"] += 1
    else:
        after[field] += 1
    with pytest.raises(
            harness.HarnessRefused, match="forced/no-search play changed"):
        harness.validate_arm_semantics(arm, _design(tmp_path), 101)


@pytest.mark.parametrize(("mutation", "message"), [
    (lambda record: record.__setitem__("n_determinizations", 29),
     "not N=30"),
    (lambda record: record.__setitem__("report_worlds_requested", 299),
     "not R=300"),
    (lambda record: record["work"].__setitem__("total_rollouts", 659),
     "work is not exact"),
    (lambda record: record["rng_state"][1].__setitem__(0, 999),
     "pre-search RNG state drift"),
    (lambda record: record["sampler_counters"]["delta"].__setitem__(
        "accepted_worlds", 329),
     "sampler accounting drift"),
])
def test_searched_decisions_require_exact_n30_r300_work_rng_and_sampler(
        tmp_path, mutation, message):
    arm = _arm()
    mutation(arm["decision_records"][1][0]["record"])
    with pytest.raises(harness.HarnessRefused, match=message):
        harness.validate_arm_semantics(arm, _design(tmp_path), 101)


def test_engine_adjusted_throw_keeps_action_and_history_as_distinct_evidence(
        tmp_path):
    arm = _arm()
    arm["decision_records"][0][0]["action"] = ["S5", "S5", "S6", "S6"]
    summary = harness.validate_arm_semantics(arm, _design(tmp_path), 101)
    assert summary["engine_adjusted_plays"] == 1
    assert summary["engine_adjusted_plays_by_seat"] == [1, 0, 0, 0]


def test_changed_attempted_action_cannot_normalize_away(tmp_path):
    base, head = _arm(ballot_suffix="base"), _arm(ballot_suffix="head")
    head["decision_records"][0][0]["action"] = ["S6", "S6"]
    base_bytes, _ = harness.normalize_arm(base)
    head_bytes, _ = harness.normalize_arm(head)
    assert head_bytes != base_bytes


def test_only_code_derived_ballot_fields_are_normalized(tmp_path):
    base, head = _arm(ballot_suffix="base"), _arm(ballot_suffix="head")
    harness.validate_arm_semantics(base, _design(tmp_path), 101)
    harness.validate_arm_semantics(head, _design(tmp_path), 101)
    base_bytes, base_removed = harness.normalize_arm(base)
    head_bytes, head_removed = harness.normalize_arm(head)
    assert base_removed == head_removed == {
        "digest": 1, "display": 1, "source_digest": 1}
    assert base_bytes == head_bytes

    head["decision_records"][1][0]["record"]["ballot"]["candidates"] = [
        ["H3"], ["H5"]]
    changed, _ = harness.normalize_arm(head)
    assert changed != base_bytes


def test_immutable_design_is_required_before_a_batch(tmp_path):
    path = tmp_path / "design.json"
    path.write_bytes(harness.canonical(_design(tmp_path)))
    with pytest.raises(harness.HarnessRefused, match="non-writable"):
        harness._require_immutable_design(path)
    path.chmod(0o444)
    assert harness._require_immutable_design(path) == path.read_bytes()


def test_json_reader_refuses_duplicate_keys_and_nonfinite_values():
    with pytest.raises(harness.HarnessRefused, match="duplicate JSON key"):
        harness.load_json_bytes(b'{"a":1,"a":2}')
    with pytest.raises(harness.HarnessRefused, match="non-finite"):
        harness.load_json_bytes(b'{"a":NaN}')


def test_arm_semantic_schema_refuses_foreign_outcome_or_authority_fields(
        tmp_path):
    for field, value in (
            ("utility", 1.0), ("production_deployment", True),
            ("execution_authorized", True)):
        arm = _arm()
        arm[field] = value
        with pytest.raises(harness.HarnessRefused, match="field set drift"):
            harness.validate_arm_semantics(arm, _design(tmp_path), 101)

    arm = _arm()
    arm["decision_records"][1][0]["foreign_outcome"] = 99
    with pytest.raises(harness.HarnessRefused, match="wrapper field set drift"):
        harness.validate_arm_semantics(arm, _design(tmp_path), 101)


def test_actual_identity_binds_git_sources_and_native_binary(tmp_path):
    repo = tmp_path / "repo"
    source = repo / "server/shengji/engine/round.py"
    native = repo / "server/shengji/engine/_fast.test.so"
    source.parent.mkdir(parents=True)
    source.write_text("ROUND = 1\n")
    native.write_bytes(b"synthetic-native")
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "add", "."], check=True)
    subprocess.run([
        "git", "-C", repo, "-c", "user.name=Test",
        "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture",
    ], check=True)
    git = subprocess.check_output(
        ["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
    expected = {
        "repo": str(repo),
        "git": git,
        "source_sha256s": {
            "server/shengji/engine/round.py": _sha(source.read_bytes()),
        },
        "native": {
            "path": "server/shengji/engine/_fast.test.so",
            "sha256": _sha(native.read_bytes()),
        },
    }
    assert harness._actual_identity("fixture", expected) == {
        key: expected[key] for key in ("git", "source_sha256s", "native")}

    source.write_text("ROUND = 2\n")
    with pytest.raises(harness.HarnessRefused, match="worktree is dirty"):
        harness._actual_identity("fixture", expected)


def test_exclusive_writes_make_a_consumed_path_non_retryable(tmp_path):
    path = tmp_path / "one-shot.json"
    harness._exclusive_write(path, b"first")
    assert path.read_bytes() == b"first"
    assert path.stat().st_mode & 0o222 == 0
    with pytest.raises(FileExistsError):
        harness._exclusive_write(path, b"retry")


def test_internal_arm_cli_routes_all_bound_arguments(monkeypatch, tmp_path):
    called = []
    design = tmp_path / "design.json"
    raw = tmp_path / "raw.json"
    monkeypatch.setattr(
        sys, "argv",
        ["report_lcb_perf_ab.py", "run-arm", str(design), "head", "101",
         str(raw)])
    monkeypatch.setattr(
        harness, "_run_arm",
        lambda *args: called.append(args))
    harness.main()
    assert called == [(design.resolve(), "head", 101, raw.resolve())]


def test_batch_refuses_before_any_namespace_without_external_design_binding(
        monkeypatch, tmp_path):
    design = _design(tmp_path)
    path = tmp_path / "design.json"
    path.write_bytes(harness.canonical(design))
    path.chmod(0o444)
    monkeypatch.setattr(harness, "_require_runtime", lambda *_args: None)
    monkeypatch.delenv("PERF_AB_EXTERNAL_DESIGN_SHA256", raising=False)
    monkeypatch.delenv("PERF_AB_REVIEW_RECORD_SHA256", raising=False)
    with pytest.raises(harness.HarnessRefused, match="external design"):
        harness._run_batch(path)
    assert not Path(design["evidence_root"]).exists()


def test_batch_also_requires_a_review_record_binding_before_identity_or_write(
        monkeypatch, tmp_path):
    design = _design(tmp_path)
    path = tmp_path / "design.json"
    payload = harness.canonical(design)
    path.write_bytes(payload)
    path.chmod(0o444)
    monkeypatch.setattr(harness, "_require_runtime", lambda *_args: None)
    monkeypatch.setenv(
        "PERF_AB_EXTERNAL_DESIGN_SHA256", harness.sha256_bytes(payload))
    monkeypatch.delenv("PERF_AB_REVIEW_RECORD_SHA256", raising=False)
    with pytest.raises(harness.HarnessRefused, match="review-record"):
        harness._run_batch(path)
    assert not Path(design["evidence_root"]).exists()
