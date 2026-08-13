"""Synthetic contract tests for the generic report-LCB performance A/B."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import stat
import subprocess
import sys
from types import ModuleType

import pytest

from scripts import report_lcb_perf_ab as harness
from scripts import validate_report_lcb_perf_bundle as validator


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _design(tmp_path: Path) -> dict:
    sources = {
        "server/shengji/ai/mcbot.py": "1" * 64,
        "server/shengji/engine/round.py": "2" * 64,
    }
    identity = {
        "repo": str(tmp_path / "base"),
        "git": harness.BASE_GIT,
        "source_sha256s": sources,
        "native": {
            "path": "server/shengji/engine/_fast.test.so",
            "sha256": "3" * 64,
        },
    }
    head = copy.deepcopy(identity)
    head["repo"] = str(tmp_path / "head")
    head["git"] = harness.HEAD_GIT
    head["source_sha256s"] = {
        key: ("4" * 64 if key.endswith("round.py") else value)
        for key, value in sources.items()
    }
    return {
        "schema": harness.DESIGN_SCHEMA,
        "claim_boundary": copy.deepcopy(harness.CLAIM_BOUNDARY),
        "experiment": {
            "id": harness.EXPERIMENT_ID,
            "policy": harness.POLICY,
            "n_determinizations": 30,
            "report_fold_worlds": 300,
            "seeds": list(harness.PAIR_SEEDS),
            "orders": list(harness.PAIR_ORDERS),
            "capture_excluded_fields":
                list(harness.CAPTURE_EXCLUDED_FIELDS),
            "normalization_removed_fields":
                list(harness.NORMALIZED_BALLOT_FIELDS),
            "retention": copy.deepcopy(harness.RETENTION_CONTRACT),
        },
        "evidence_root": str(tmp_path / "evidence"),
        "python": {
            "executable": "/opt/example/python",
            "resolved": "/opt/example/python3.14",
            "version": "3.14.4",
            "sha256": "5" * 64,
            "implementation": "CPython",
            "cache_tag": "cpython-314",
            "soabi": "cpython-314-test",
            "platform": "Synthetic-1",
            "machine": "x86_64",
        },
        "harness": {
            "path": "/opt/example/report_lcb_perf_ab.py",
            "sha256": "6" * 64,
        },
        "validator": {
            "path": "/opt/example/validate_report_lcb_perf_bundle.py",
            "sha256": "7" * 64,
        },
        "execution": {
            "child_environment": copy.deepcopy(
                harness.FIXED_CHILD_ENVIRONMENT),
            "host_profile": {
                "path": "/etc/report-lcb-perf/host-profile.json",
                "sha256": "8" * 64,
            },
            "systemd_unit": {
                "path": "/etc/systemd/system/report-lcb-perf.service",
                "sha256": "9" * 64,
            },
            "timer": "time.perf_counter_ns",
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
    before = _snapshot(rng=11)
    after = _snapshot(rng=12, sampler=330, rollouts=660, searches=1)
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
            "report_fold": {
                "complete": True, "worlds": 300,
                "attempts": 300, "rejected": 0,
            },
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


def _arm(*, ballot_suffix: str = "base", seed: int = 101) -> dict:
    forced = _snapshot(rng=5)
    searched = _searched_decision(ballot_suffix=ballot_suffix)
    return {
        "schema": harness.ARM_SCHEMA,
        "seed": seed,
        "policy": harness.POLICY,
        "trump_rank": "2",
        "banker": 0,
        "attacker_points": 80,
        "winner_team": "attackers",
        "level_change": 1,
        "history": [[0, ["S5", "S5"]], [1, ["H4"]]],
        "game_rng_state": [3, [101, 102], None],
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
    # These are the two review-sensitive constants that the first source audit
    # found were only transitively frozen into a later host design.  Pin them
    # directly so a weakened threshold or broadened normalization cannot keep
    # the tooling suite green before design review.
    assert harness.MINIMUM_AGGREGATE_REDUCTION_PERCENT == 3.0
    assert harness.NORMALIZED_BALLOT_FIELDS == (
        "decision_records[*].record.ballot.digest",
        "decision_records[*].record.ballot.display",
        "decision_records[*].record.ballot.source_digest",
    )
    assert harness.HEAD_GIT == \
        "a91eb2716917bcc3c431d9f6841efd02f4fc8b00"
    assert harness.EXPERIMENT_ID == \
        "report-lcb-perf-accepted-stack-pr90-v5-bytecode-repair"
    assert harness.PAIR_SEEDS == (
        3241160913, 309165843, 623399655,
        1506812366, 1286062863, 2808674107,
    )
    assert set(harness.PAIR_SEEDS).isdisjoint({
        3368250205, 194578860, 2724771798,
        2228922925, 1533007193, 1686527578,
        2552710799, 3117477128, 1009088913,
        3804486078, 4075261754, 2363873674,
        1325809612, 3286110, 1702447446,
        2457851339, 3102784513, 3313536938,
    })

    design = _design(tmp_path)
    assert harness.design_problems(design) == []

    unbalanced = copy.deepcopy(design)
    unbalanced["experiment"]["orders"] = ["base_head"] * 6
    assert "execution order is not the preregistered alternation" in \
        harness.design_problems(unbalanced)

    short = copy.deepcopy(design)
    short["experiment"]["seeds"] = list(harness.PAIR_SEEDS[:4])
    assert "seeds are not the six preregistered fresh pairs" in \
        harness.design_problems(short)

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


def test_systemd_invocation_binding_uses_real_unit_to_id_symlink(tmp_path):
    units = tmp_path / "units"
    units.mkdir()
    unit = Path("/etc/systemd/system/report-lcb-perf-ab-pr89-v3.service")
    invocation_id = "a" * 32
    live = units / f"invocation:{unit.name}"
    live.symlink_to(invocation_id)

    harness._require_systemd_invocation(
        unit, invocation_id, units_dir=units)

    live.unlink()
    # This is the inverse mapping used by the spent v2r1 implementation.  It
    # does not match systemd's /run/systemd/units contract and must refuse.
    (units / f"invocation:{invocation_id}").symlink_to(unit.name)
    with pytest.raises(harness.HarnessRefused, match="binding is not live"):
        harness._require_systemd_invocation(
            unit, invocation_id, units_dir=units)

    (units / f"invocation:{unit.name}").symlink_to("b" * 32)
    with pytest.raises(harness.HarnessRefused, match="binding is not live"):
        harness._require_systemd_invocation(
            unit, invocation_id, units_dir=units)

    with pytest.raises(harness.HarnessRefused, match="identity is malformed"):
        harness._require_systemd_invocation(
            unit, "not-an-invocation", units_dir=units)


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
        after[field]["failed_worlds"] += 1
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


def test_searched_engine_adjusted_throw_binds_attempt_and_engine_history(
        tmp_path):
    arm = _arm()
    decision = arm["decision_records"][1][0]
    attempted = ["H4", "H4", "H5"]
    decision["action"] = attempted
    decision["record"]["played"] = attempted
    decision["record"]["candidates"][1] = attempted
    decision["record"]["ballot"]["candidates"][1] = attempted
    # The engine accepted only H4; the complete attempted and actual objects
    # stay distinct and are both compared across A/B arms.
    assert arm["history"][1][1] == ["H4"]
    summary = harness.validate_arm_semantics(
        arm, _design(tmp_path), 101)
    assert summary["searched_decisions"] == 1
    assert summary["engine_adjusted_plays"] == 1
    assert summary["engine_adjusted_plays_by_seat"] == [0, 1, 0, 0]

    decision["record"]["played"] = ["H4"]
    with pytest.raises(harness.HarnessRefused, match="record/attempt drift"):
        harness.validate_arm_semantics(arm, _design(tmp_path), 101)


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
    setup = repo / "server/setup.py"
    pyproject = repo / "server/pyproject.toml"
    lock = repo / "server/uv.lock"
    native = repo / "server/shengji/engine/_fast.test.so"
    source.parent.mkdir(parents=True)
    source.write_text("ROUND = 1\n")
    setup.write_text("# synthetic build source\n")
    pyproject.write_text("[build-system]\nrequires = []\n")
    lock.write_text("version = 1\n")
    native.write_bytes(b"synthetic-native")
    (repo / ".gitignore").write_text("*.so\n")
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run([
        "git", "-C", repo, "add", ".gitignore",
        "server/shengji/engine/round.py", "server/setup.py",
        "server/pyproject.toml", "server/uv.lock",
    ], check=True)
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
            "server/setup.py": _sha(setup.read_bytes()),
            "server/pyproject.toml": _sha(pyproject.read_bytes()),
            "server/uv.lock": _sha(lock.read_bytes()),
        },
        "native": {
            "path": "server/shengji/engine/_fast.test.so",
            "sha256": _sha(native.read_bytes()),
        },
    }
    assert harness._actual_identity("fixture", expected) == {
        key: expected[key] for key in ("git", "source_sha256s", "native")}

    incomplete = copy.deepcopy(expected)
    incomplete["source_sha256s"].pop("server/setup.py")
    with pytest.raises(
            harness.HarnessRefused,
            match="tracked source manifest is incomplete"):
        harness._actual_identity("fixture", incomplete)

    source.write_text("ROUND = 2\n")
    with pytest.raises(harness.HarnessRefused, match="worktree is dirty"):
        harness._actual_identity("fixture", expected)


def test_prearm_staging_archives_portable_actual_identity(tmp_path):
    """Regression for the spent V3 KeyError before the first benchmark arm."""

    repo = tmp_path / "repo"
    source = repo / "server/shengji/engine/round.py"
    native = repo / "server/shengji/engine/_fast.test.so"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"ROUND = 1\n")
    native.write_bytes(b"synthetic-native")
    expected = {
        "repo": str(repo),
        "git": "a" * 40,
        "source_sha256s": {
            "server/shengji/engine/round.py": _sha(source.read_bytes()),
        },
        "native": {
            "path": "server/shengji/engine/_fast.test.so",
            "sha256": _sha(native.read_bytes()),
        },
    }
    # This is the portable value returned by _actual_identity: no repo key.
    actual = {key: expected[key]
              for key in ("git", "source_sha256s", "native")}
    root = tmp_path / "evidence"
    root.mkdir()

    harness._stage_arm_identity(root, "base", expected, actual)

    assert harness.load_json_bytes(
        (root / "base.identity.json").read_bytes()) == actual
    validator._validate_source_archive(
        root / "base.source.tar", actual["source_sha256s"])
    assert (root / "base.native.bin").read_bytes() == native.read_bytes()
    assert all(not path.stat().st_mode & 0o222 for path in root.iterdir())


def test_imported_shengji_modules_must_resolve_inside_bound_repo(
        monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    package = repo / "server/shengji"
    package.mkdir(parents=True)
    origin = package / "__init__.py"
    origin.write_text("")
    for name in tuple(sys.modules):
        if name == "shengji" or name.startswith("shengji."):
            monkeypatch.delitem(sys.modules, name)
    module = ModuleType("shengji")
    module.__file__ = str(origin)
    monkeypatch.setitem(sys.modules, "shengji", module)
    harness._require_import_origins(repo)

    module.__file__ = str(tmp_path / "foreign/shengji/__init__.py")
    with pytest.raises(harness.HarnessRefused, match="escaped bound repo"):
        harness._require_import_origins(repo)


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


def test_isolated_arm_flags_prevent_bytecode_despite_ignored_environment(
        tmp_path):
    assert harness.ISOLATED_CHILD_FLAGS == ("-I", "-B", "-P")
    package = tmp_path / "bound_runtime"
    package.mkdir()
    (package / "__init__.py").write_text("VALUE = 7\n")
    program = (
        "import pathlib,sys;"
        f"sys.path.insert(0,{str(tmp_path)!r});"
        "import bound_runtime;"
        "print(int(sys.flags.ignore_environment),"
        "int(sys.dont_write_bytecode),bound_runtime.VALUE)"
    )
    environment = dict(harness.FIXED_CHILD_ENVIRONMENT)
    completed = subprocess.run(
        [sys.executable, *harness.ISOLATED_CHILD_FLAGS, "-c", program],
        env=environment, check=True, capture_output=True, text=True)
    assert completed.stdout.strip() == "1 1 7"
    assert not (package / "__pycache__").exists()


def test_batch_arm_command_uses_the_bytecode_safe_isolation_flags(tmp_path):
    script = tmp_path / "harness.py"
    design = tmp_path / "design.json"
    raw = tmp_path / "arm.raw.json"
    command = harness._isolated_arm_command(
        "/usr/bin/python3.14", script, design, "base", 123, raw)
    assert command[:5] == [
        "/usr/bin/python3.14", "-I", "-B", "-P", "-c"]
    assert command[-5:] == [
        "run-arm", str(design), "base", "123", str(raw)]


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


def _timing_rows(reductions, bases=None):
    bases = bases or [100_000_000_000] * 6
    return [{
        "seed": seed,
        "order": order,
        "base": {"elapsed_ns": base},
        "head": {"elapsed_ns": round(base * (1.0 - reduction / 100.0))},
    } for seed, order, base, reduction in zip(
        harness.PAIR_SEEDS, harness.PAIR_ORDERS, bases, reductions,
        strict=True)]


@pytest.mark.parametrize(("reductions", "aggregate_pass", "lcb_pass"), [
    ([4, 4.5, 5, 5.5, 6, 6.5], True, True),
    ([2.75, 2.85, 2.95, 3.05, 3.15, 3.25], True, True),
    ([-0.58, -0.58, -0.58, 6.58, 6.58, 6.58], True, False),
])
def test_paired_student_t_gate_catches_point_estimate_and_ddof_traps(
        reductions, aggregate_pass, lcb_pass):
    rows = _timing_rows(reductions)
    paired = harness.paired_statistics(rows)
    aggregate = 100.0 * (
        sum(row["base"]["elapsed_ns"] for row in rows)
        - sum(row["head"]["elapsed_ns"] for row in rows)
    ) / sum(row["base"]["elapsed_ns"] for row in rows)
    assert (aggregate >= 3.0) is aggregate_pass
    assert (paired["one_sided_95_lcb_percent"] > 0) is lcb_pass


def test_aggregate_weighting_gate_is_distinct_from_paired_lcb():
    rows = _timing_rows(
        [2, 10, 10, 10, 10, 10],
        [1_000_000_000_000] + [10_000_000_000] * 5)
    paired = harness.paired_statistics(rows)
    aggregate = 100.0 * (
        sum(row["base"]["elapsed_ns"] for row in rows)
        - sum(row["head"]["elapsed_ns"] for row in rows)
    ) / sum(row["base"]["elapsed_ns"] for row in rows)
    assert aggregate == pytest.approx(2.380952380952381)
    assert paired["one_sided_95_lcb_percent"] > 0


@pytest.mark.parametrize("counter", [
    "short_search_decisions", "zero_world_decisions", "bury_short_searches",
])
def test_absolute_short_and_zero_world_counters_refuse_even_without_delta(
        tmp_path, counter):
    arm = _arm()
    decision = arm["decision_records"][1][0]
    decision["before"][counter] = 1
    decision["after"][counter] = 1
    arm["final_bots"][1][counter] = 1
    with pytest.raises(harness.HarnessRefused, match="short or zero-world"):
        harness.validate_arm_semantics(arm, _design(tmp_path), 101)


def test_searched_sampler_requires_exact_330_accepted_worlds(tmp_path):
    arm = _arm()
    decision = arm["decision_records"][1][0]
    decision["after"]["sampler"]["accepted_worlds"] -= 1
    decision["after"]["sampler"]["sample_attempts"] -= 1
    decision["record"]["sampler_counters"]["after"] = copy.deepcopy(
        decision["after"]["sampler"])
    decision["record"]["sampler_counters"]["delta"][
        "accepted_worlds"] -= 1
    decision["record"]["sampler_counters"]["delta"][
        "sample_attempts"] -= 1
    arm["final_bots"][1] = copy.deepcopy(decision["after"])
    with pytest.raises(harness.HarnessRefused, match="sampler dose"):
        harness.validate_arm_semantics(arm, _design(tmp_path), 101)


def test_snapshot_chain_and_final_snapshot_are_bound(tmp_path):
    arm = _arm()
    first = arm["decision_records"][0][0]
    second = copy.deepcopy(first)
    second["before"]["rng_state"][1][0] += 1
    second["after"] = copy.deepcopy(second["before"])
    arm["decision_records"][0].append(second)
    arm["history"].append([0, copy.deepcopy(second["action"])])
    arm["final_bots"][0] = copy.deepcopy(second["after"])
    with pytest.raises(harness.HarnessRefused, match="snapshot chain"):
        harness.validate_arm_semantics(arm, _design(tmp_path), 101)


def test_actual_imported_native_must_equal_named_path_and_hash(tmp_path):
    repo = tmp_path / "repo"
    native = repo / "server/shengji/engine/_fast.test.so"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"native")
    fast = ModuleType("fast")
    fast._fast = ModuleType("_fast")
    fast._fast.__file__ = str(native)
    expected = {
        "path": "server/shengji/engine/_fast.test.so",
        "sha256": _sha(native.read_bytes()),
    }
    harness._require_actual_native(repo, expected, fast)
    fast._fast.__file__ = str(repo / "server/shengji/engine/shadow.so")
    with pytest.raises(harness.HarnessRefused, match="native extension"):
        harness._require_actual_native(repo, expected, fast)


@pytest.mark.parametrize("extra", ["shadow.pyc", "shadow.so"])
def test_runtime_tree_refuses_ignored_bytecode_and_unbound_loadables(
        tmp_path, extra):
    repo = tmp_path / "repo"
    package = repo / "server/shengji"
    package.mkdir(parents=True)
    native = package / "_fast.so"
    native.write_bytes(b"native")
    (package / extra).write_bytes(b"shadow")
    with pytest.raises(harness.HarnessRefused, match="ignored|unbound"):
        harness._require_runtime_tree(repo, "server/shengji/_fast.so")


@pytest.mark.parametrize("extra", ["dataclasses.py", "dataclasses.pyc",
                                    "dataclasses.so"])
def test_runtime_tree_refuses_top_level_import_shadows(tmp_path, extra):
    repo = tmp_path / "repo"
    package = repo / "server/shengji"
    package.mkdir(parents=True)
    native = package / "_fast.so"
    native.write_bytes(b"native")
    (repo / "server" / extra).write_bytes(b"shadow")
    with pytest.raises(harness.HarnessRefused, match="top-level import shadow"):
        harness._require_runtime_tree(repo, "server/shengji/_fast.so")


@pytest.mark.parametrize("package_init", [
    "__init__.py", "__init__.pyc", "__init__.cpython-314-test.so",
])
def test_runtime_tree_refuses_top_level_package_shadows(
        tmp_path, package_init):
    repo = tmp_path / "repo"
    package = repo / "server/shengji"
    package.mkdir(parents=True)
    native = package / "_fast.so"
    native.write_bytes(b"native")
    shadow = repo / "server/dataclasses"
    shadow.mkdir()
    (shadow / package_init).write_bytes(b"shadow")
    with pytest.raises(harness.HarnessRefused, match="package shadow"):
        harness._require_runtime_tree(repo, "server/shengji/_fast.so")


def test_offline_validator_refuses_duplicate_json_and_mutable_bundle(tmp_path):
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"a":1,"a":2}')
    with pytest.raises(validator.BundleRefused, match="duplicate JSON key"):
        validator.load_json(duplicate)
    with pytest.raises(validator.BundleRefused, match="immutable root-owned"):
        validator._require_bundle_directory(tmp_path)


def test_offline_source_archive_recomputes_complete_path_hash_closure(tmp_path):
    archive = tmp_path / "source.tar"
    source_map = {
        "server/shengji/__init__.py": _sha(b"init\n"),
        "server/uv.lock": _sha(b"lock\n"),
    }
    import io
    import tarfile
    with tarfile.open(archive, "w") as bundle:
        for name, payload in (
                ("server/shengji/__init__.py", b"init\n"),
                ("server/uv.lock", b"lock\n")):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            bundle.addfile(info, io.BytesIO(payload))
    validator._validate_source_archive(archive, source_map)
    source_map.pop("server/uv.lock")
    with pytest.raises(validator.BundleRefused, match="closure drift"):
        validator._validate_source_archive(archive, source_map)


def test_offline_expected_population_is_exact_six_pairs():
    paths = validator._expected_paths(harness)
    assert len([path for path in paths if path.endswith(".raw.json")]) == 12
    assert len([path for path in paths
                if path.endswith(".normalized.json")]) == 12
    assert len([path for path in paths if path.endswith(".stdout.jsonl")]) == 12
    assert len([path for path in paths if path.endswith(".stderr.log")]) == 12
    assert "result.json" in paths
    assert "execution.json" in paths


def test_offline_validator_reopens_raw_bundle_and_refuses_extra_or_mutated(
        monkeypatch, tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    harness_source = Path(harness.__file__).read_bytes()
    validator_source = Path(validator.__file__).read_bytes()
    source_payloads = {
        "server/shengji/ai/mcbot.py": b"synthetic mcbot\n",
        "server/uv.lock": b"synthetic lock\n",
    }
    design = _design(root)
    design["evidence_root"] = str(root)
    design["harness"] = {
        "path": str(root / "harness.py"),
        "sha256": _sha(harness_source),
    }
    design["validator"] = {
        "path": str(root / "validator.py"),
        "sha256": _sha(validator_source),
    }
    design["python"]["sha256"] = _sha(b"synthetic python")
    design["execution"]["systemd_unit"]["sha256"] = \
        _sha(b"synthetic unit")
    design["execution"]["host_profile"]["sha256"] = \
        _sha(b"synthetic profile")
    for label, native_payload in (
            ("base", b"base native"), ("head", b"head native")):
        design[label]["source_sha256s"] = {
            path: _sha(payload) for path, payload in source_payloads.items()}
        design[label]["native"]["sha256"] = _sha(native_payload)
    harness.require_design(design)
    design_payload = harness.canonical(design)
    design_sha = _sha(design_payload)
    review = {
        "schema": harness.REVIEW_SCHEMA,
        "design_sha256": design_sha,
        "verdict": "PASS",
        "reviewer": "synthetic-reviewer",
        "summary": "synthetic exact-design PASS",
    }
    review_payload = harness.canonical(review)
    review_sha = _sha(review_payload)

    def put(name, payload):
        path = root / name
        path.write_bytes(payload)
        path.chmod(0o444)
        return path

    put("design.json", design_payload)
    put("review.json", review_payload)
    put("harness.py", harness_source)
    put("validator.py", validator_source)
    put("systemd.unit", b"synthetic unit")
    put("host-profile.json", b"synthetic profile")
    put("python.bin", b"synthetic python")
    identities = {}
    for label, native_payload in (
            ("base", b"base native"), ("head", b"head native")):
        identity = {
            key: design[label][key]
            for key in ("git", "source_sha256s", "native")}
        identities[label] = identity
        put(f"{label}.identity.json", harness.canonical(identity))
        archive = root / f"{label}.source.tar"
        import io
        import tarfile
        with tarfile.open(archive, "w") as bundle:
            for name, payload in source_payloads.items():
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                bundle.addfile(info, io.BytesIO(payload))
        archive.chmod(0o444)
        put(f"{label}.native.bin", native_payload)

    rows = []
    for index, (seed, order) in enumerate(zip(
            harness.PAIR_SEEDS, harness.PAIR_ORDERS, strict=True)):
        row = {"seed": seed, "order": order}
        normalized = {}
        for label in ("base", "head"):
            arm = _arm(ballot_suffix=label, seed=seed)
            raw = harness.canonical(arm)
            validation = harness.validate_arm_semantics(arm, design, seed)
            normalized_bytes, removals = harness.normalize_arm(arm)
            elapsed = (100_000_000_000 + index * 1_000_000
                       if label == "base" else
                       95_000_000_000 + index * 1_000_000)
            summary = {
                "elapsed_ns": elapsed,
                "semantic_bytes": len(raw),
                "semantic_sha256": _sha(raw),
                **validation,
            }
            stem = f"seed-{seed}.{label}"
            stdout = harness.canonical(summary) + b"\n"
            put(f"{stem}.raw.json", raw)
            put(f"{stem}.normalized.json", normalized_bytes)
            put(f"{stem}.stdout.jsonl", stdout)
            put(f"{stem}.stderr.log", b"")
            normalized[label] = normalized_bytes
            row[label] = {
                "elapsed_ns": elapsed,
                "raw_semantic_sha256": _sha(raw),
                "raw_semantic_bytes": len(raw),
                "normalized_semantic_sha256": _sha(normalized_bytes),
                "normalized_semantic_bytes": len(normalized_bytes),
                "normalization_removals": removals,
                "stdout_sha256": _sha(stdout),
                "stderr_sha256": _sha(b""),
                **validation,
            }
        assert normalized["base"] == normalized["head"]
        row["normalized_semantics_exact"] = True
        rows.append(row)

    invocation_id = "synthetic-invocation"
    execution = {
        "schema": harness.EXECUTION_SCHEMA,
        "design_sha256": design_sha,
        "review_record_sha256": review_sha,
        "review_record_source_path": "/root/review.json",
        "systemd_invocation_id": invocation_id,
        "boot_id": "synthetic-boot",
        "started_unix_ns": 1,
        "finished_arms_unix_ns": 2,
        "arms_completed": 12,
        "arm_sequence": [{
            "sequence_index": index,
            "seed": seed,
            "label": label,
            "started_monotonic_ns": index * 2 + 1,
            "finished_monotonic_ns": index * 2 + 2,
            "returncode": 0,
        } for index, (seed, label) in enumerate([
            (seed, label)
            for seed, order in zip(
                harness.PAIR_SEEDS, harness.PAIR_ORDERS, strict=True)
            for label in order.split("_")
        ])],
        "child_environment": {
            **harness.FIXED_CHILD_ENVIRONMENT,
            "INVOCATION_ID": invocation_id,
            "SHENGJI_FAST": "1",
            "SHENGJI_REQUIRE_VOIDS": "1",
            "PERF_AB_DESIGN_SHA256": design_sha,
            "PERF_EXPERIMENT_ID": harness.EXPERIMENT_ID,
        },
        "systemd_unit_sha256":
            design["execution"]["systemd_unit"]["sha256"],
        "host_profile_sha256":
            design["execution"]["host_profile"]["sha256"],
    }
    execution_payload = harness.canonical(execution)
    put("execution.json", execution_payload)
    result = harness.build_result(
        design, design_sha, review_sha, invocation_id,
        _sha(execution_payload), identities, rows)
    put("result.json", harness.canonical(result))

    def synthetic_metadata(path):
        status = path.stat()
        return {
            "path": path.name,
            "sha256": validator.sha256_file(path),
            "bytes": status.st_size,
            "mode": stat.S_IMODE(status.st_mode),
            "uid": status.st_uid,
            "gid": status.st_gid,
            "nlink": status.st_nlink,
        }

    monkeypatch.setattr(validator, "_regular_metadata", synthetic_metadata)
    monkeypatch.setattr(validator, "_require_bundle_directory", lambda _root: None)
    artifacts = [
        synthetic_metadata(root / name)
        for name in sorted(validator._expected_paths(harness))]
    manifest = {
        "schema": harness.BUNDLE_SCHEMA,
        "design_sha256": design_sha,
        "review_record_sha256": review_sha,
        "systemd_invocation_id": invocation_id,
        "artifacts": artifacts,
    }
    manifest_path = put("manifest.json", harness.canonical(manifest))
    manifest_sha = validator.sha256_file(manifest_path)
    verified = validator.validate_bundle(root, design_sha, manifest_sha)
    assert verified["status"] == "VERIFIED"
    assert verified["decision"] == "retain"

    extra = put("unmanifested.txt", b"extra")
    with pytest.raises(validator.BundleRefused, match="path closure drift"):
        validator.validate_bundle(root, design_sha, manifest_sha)
    extra.unlink()
    raw = root / f"seed-{harness.PAIR_SEEDS[0]}.head.raw.json"
    raw.chmod(0o644)
    raw.write_bytes(raw.read_bytes() + b" ")
    raw.chmod(0o444)
    with pytest.raises(validator.BundleRefused, match="metadata/hash closure"):
        validator.validate_bundle(root, design_sha, manifest_sha)
