"""Mutation-focused tests for the frozen Direct-Q learning screen."""
from __future__ import annotations

import copy
import importlib.util
import math
from pathlib import Path

import pytest


np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from shengji.rl import douzero_learning_screen as screen  # noqa: E402
from shengji.rl.douzero_micro import (  # noqa: E402
    ACT_DIM,
    HISTORY_EVENT_DIM,
    ROLE_ATTACKER,
    ROLE_DEFENDER,
    _collate,
    load_actor,
    new_bundle,
    new_from_scratch_model,
    publish_initial_actor,
)
from shengji.rl.encode import OBS_DIM  # noqa: E402
from shengji.rl.exact_resume import state_digest  # noqa: E402
from shengji.rl.selfplay_contract import load_verified  # noqa: E402


@pytest.fixture(autouse=True)
def _strict_deterministic_torch():
    enabled = torch.are_deterministic_algorithms_enabled()
    warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    torch.use_deterministic_algorithms(True, warn_only=False)
    try:
        yield
    finally:
        torch.use_deterministic_algorithms(enabled, warn_only=warn_only)


def _load_launcher():
    path = Path(__file__).resolve().parents[1] / "scripts" \
        / "douzero_micro_learning_screen.py"
    spec = importlib.util.spec_from_file_location(
        "douzero_micro_learning_screen_launcher_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_admits_only_exact_required_environment_before_import():
    launcher = _load_launcher()
    clean = {
        "SHENGJI_FAST": "1",
        "SHENGJI_REQUIRE_VOIDS": "1",
    }
    assert launcher.preimport_environment_problems(clean) == []

    for key in launcher.REFUSED_ENVIRONMENT_KEYS:
        contaminated = dict(clean)
        contaminated[key] = ""
        problems = launcher.preimport_environment_problems(contaminated)
        assert len(problems) == 1
        assert key in problems[0]

    for required in launcher.REQUIRED_ENVIRONMENT:
        missing = dict(clean)
        del missing[required]
        assert any(required in problem for problem in
                   launcher.preimport_environment_problems(missing))
        wrong = dict(clean)
        wrong[required] = "true"
        assert any(required in problem for problem in
                   launcher.preimport_environment_problems(wrong))


def test_screen_contract_binds_dose_ballot_epsilon_and_no_promotion():
    assert screen.SCREEN_SCHEMA == "douzero-micro-learning-screen-v1"
    assert screen.SCREEN_SPEC_SHA256 == state_digest(screen.SCREEN_SPEC)
    assert screen.ITERATIONS == 512
    assert screen.RESUME_BOUNDARY == 256
    assert screen.CHECKPOINT_ITERATIONS == (0, 64, 128, 256, 512)
    assert screen.PROBE_DEALS == 128
    assert screen.REPORT_DEALS == 256
    assert screen.SCREEN_SPEC["report"]["epsilon"] == pytest.approx(0.10)
    assert screen.SCREEN_SPEC["production_promotion"] is False
    assert screen.SCREEN_SPEC["gate"]["greedy_action_change"] == \
        "diagnostic_only"
    assert screen._algorithm_sha256("treatment") != \
        screen._algorithm_sha256("control")

    mutations = (
        (("training", "iterations"), 511),
        (("training", "actor_refresh"), "never"),
        (("probe", "include_throws"), True),
        (("report", "epsilon"), 0.20),
        (("production_promotion",), True),
    )
    for path, value in mutations:
        changed = copy.deepcopy(screen.SCREEN_SPEC)
        cursor = changed
        for key in path[:-1]:
            cursor = cursor[key]
        cursor[path[-1]] = value
        assert state_digest(changed) != screen.SCREEN_SPEC_SHA256


def _set_runtime_environment(monkeypatch):
    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    for key in screen.REFUSED_ENVIRONMENT_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_runtime_refuses_missing_or_unrouted_compiled_engine(monkeypatch):
    from shengji.engine import combos, fast

    _set_runtime_environment(monkeypatch)
    monkeypatch.setattr(fast, "HAVE_FAST", False)
    with pytest.raises(screen.LearningScreenError, match="not active"):
        screen._runtime_identity()

    monkeypatch.setattr(fast, "HAVE_FAST", True)
    monkeypatch.setattr(combos, "decompose", object())
    with pytest.raises(screen.LearningScreenError, match="not active"):
        screen._runtime_identity()


def test_runtime_refuses_flag_by_presence_even_when_empty(monkeypatch):
    _set_runtime_environment(monkeypatch)
    monkeypatch.setenv(screen.REFUSED_ENVIRONMENT_KEYS[0], "")
    with pytest.raises(screen.LearningScreenError,
                       match="must be absent"):
        screen._runtime_identity()


def test_exclusive_artifact_publication_refuses_reuse_and_detects_drift(
        tmp_path):
    target = tmp_path / "artifact.json"
    ref = screen._publish_json(target, {"answer": 42})
    ref.verify()
    with pytest.raises(FileExistsError, match="overwrite"):
        screen._publish_json(target, {"answer": 43})

    with target.open("ab") as handle:
        handle.write(b"drift")
    with pytest.raises(RuntimeError, match="digest drift"):
        ref.verify()


def test_artifact_consumer_refuses_adjacent_partial_marker(tmp_path):
    target = tmp_path / "complete.json"
    ref = screen._publish_json(target, {"answer": 42})
    partial = screen._adjacent_partial(target)
    partial.write_bytes(b"forensic incomplete publication\n")
    with pytest.raises(screen.LearningScreenError,
                       match="incomplete adjacent"):
        screen._load_json(ref)


def test_exact_two_flip_statistics_refuse_duplicate_missing_and_nonfinite():
    rows = [
        {"deal_seed": 10, "flip": 0, "utility": 2.0},
        {"deal_seed": 10, "flip": 1, "utility": 4.0},
        {"deal_seed": 11, "flip": 0, "utility": -1.0},
        {"deal_seed": 11, "flip": 1, "utility": 1.0},
    ]
    assert screen.exact_two_flip_means(
        rows, seed0=10, deals=2, value_field="utility") == {
            10: 3.0, 11: 0.0}

    with pytest.raises(screen.LearningScreenError, match="duplicate/extra"):
        screen.exact_two_flip_means(
            rows + [dict(rows[0])], seed0=10, deals=2,
            value_field="utility")
    with pytest.raises(screen.LearningScreenError, match="coverage"):
        screen.exact_two_flip_means(
            rows[:-1], seed0=10, deals=2, value_field="utility")
    bad = copy.deepcopy(rows)
    bad[0]["utility"] = math.nan
    with pytest.raises(screen.LearningScreenError, match="non-finite"):
        screen.exact_two_flip_means(
            bad, seed0=10, deals=2, value_field="utility")


def test_deal_cluster_summary_uses_cluster_count_and_refuses_bad_inputs():
    summary = screen.paired_summary([1.0, 3.0])
    assert summary["n"] == 2
    assert summary["mean"] == pytest.approx(2.0)
    assert summary["se"] == pytest.approx(1.0)
    assert summary["half95"] == pytest.approx(1.96)
    with pytest.raises(screen.LearningScreenError, match="at least two"):
        screen.paired_summary([1.0])
    with pytest.raises(screen.LearningScreenError, match="non-finite"):
        screen.paired_summary([1.0, math.inf])


def test_learning_gate_uses_lower_bounds_not_favourable_upper_tails():
    variance_bearing = {
        "mean": 0.125, "lcb95": -0.556, "ucb95": 0.806}
    gates, passed, failures = screen.learning_gate_decision(
        pooled_probe={
            "attacker": variance_bearing,
            "defender": variance_bearing,
        },
        seed_probe_means={"0": 0.125, "1": 0.125, "2": 0.125},
        report_effect=variance_bearing,
        report_control={"lcb95": -0.1, "ucb95": 0.1},
        report_seed_effects={"0": 0.125, "1": 0.125, "2": 0.125},
        q_health=True,
    )
    assert passed is False
    assert gates["probe_attacker_mse_lcb_positive"] is False
    assert gates["probe_defender_mse_lcb_positive"] is False
    assert gates["report_treatment_minus_control_lcb_positive"] is False
    assert failures == [
        "probe_attacker_mse_lcb_positive",
        "probe_defender_mse_lcb_positive",
        "report_treatment_minus_control_lcb_positive",
    ]


@pytest.mark.parametrize(("field", "value"), [
    ("segment", 1),
    ("complete", False),
    ("start_iteration", 1),
    ("stop_iteration", 255),
    ("requires_separate_resume", False),
])
def test_resume_boundary_refuses_every_parent_contract_mutation(field, value):
    parent = {
        "segment": 0,
        "complete": True,
        "start_iteration": 0,
        "stop_iteration": 256,
        "requires_separate_resume": True,
    }
    screen._validate_resume_parent(parent)
    parent[field] = value
    with pytest.raises(screen.LearningScreenError,
                       match="separate iteration-256"):
        screen._validate_resume_parent(parent)


def test_full_training_cannot_start_without_matching_preflight(monkeypatch,
                                                                tmp_path):
    marker = screen.LearningScreenError("preflight admission missing")
    sentinel = object()
    monkeypatch.setattr(
        screen, "_require_frozen", lambda root: (sentinel, sentinel, {}))
    monkeypatch.setattr(
        screen, "_initial_payload",
        lambda root, index: (sentinel, {}, sentinel))

    def refuse(root, index, arm):
        assert Path(root) == tmp_path
        assert index == 1
        assert arm == "treatment"
        raise marker

    monkeypatch.setattr(screen, "_require_preflight", refuse)
    with pytest.raises(screen.LearningScreenError,
                       match="preflight admission missing") as caught:
        screen.train_first_segment(tmp_path, 1, "treatment")
    assert caught.value is marker


def test_narrow_ballot_never_widens_probe_or_report(monkeypatch):
    calls = []

    def fake_enumerate(rnd, seat, **kwargs):
        calls.append((rnd, seat, kwargs))
        return [["S2"]]

    marker = object()
    monkeypatch.setattr(screen, "enumerate_actions", fake_enumerate)
    assert screen._narrow_actions(marker, 2) == [["S2"]]
    assert calls == [(marker, 2, {
        "exhaustive_follows": False,
        "include_throws": False,
    })]
    ballot = screen._ballot_identity()
    assert ballot["exhaustive_follows"] is False
    assert ballot["include_throws"] is False


def test_report_rng_is_physical_seat_tied_and_role_mapping_is_exact():
    model = new_from_scratch_model(7)
    first = screen._seat_actor(
        model, domain="report-epsilon", deal_seed=146_000_000, seat=2)
    replay = screen._seat_actor(
        model, domain="report-epsilon", deal_seed=146_000_000, seat=2)
    other_seat = screen._seat_actor(
        model, domain="report-epsilon", deal_seed=146_000_000, seat=3)
    assert first.rng.random() == replay.rng.random()
    assert screen._named_seed(
        screen.SCREEN_SCHEMA, "report-epsilon", 146_000_000, 2) != \
        screen._named_seed(
            screen.SCREEN_SCHEMA, "report-epsilon", 146_000_000, 3)
    assert first.rng.random() != other_seat.rng.random()

    for banker in range(4):
        for team in (0, 1):
            expected = (ROLE_DEFENDER if banker % 2 == team
                        else ROLE_ATTACKER)
            assert screen._candidate_role(
                banker=banker, candidate_team=team) == expected


def test_role_forward_routes_attacker_and_defender_to_their_own_heads():
    """Numerically fails if ``DouZeroRoleQ.forward`` swaps role heads."""
    model = new_from_scratch_model(11)
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        model.attacker.q_head[-1].bias.fill_(1.25)
        model.defender.q_head[-1].bias.fill_(-2.50)
    roles = torch.tensor([ROLE_ATTACKER, ROLE_DEFENDER], dtype=torch.long)
    obs = torch.zeros((2, OBS_DIM), dtype=torch.float32)
    history = torch.zeros((2, 0, HISTORY_EVENT_DIM), dtype=torch.float32)
    lengths = torch.zeros(2, dtype=torch.long)
    actions = torch.zeros((2, ACT_DIM), dtype=torch.float32)
    values = model(roles, obs, history, lengths, actions)
    assert values.tolist() == pytest.approx([1.25, -2.50])


def test_collate_uses_signed_target_not_unsigned_attacker_return():
    """Numerically fails if defender rows collate ``attacker_return``."""
    defender = {
        "role": ROLE_DEFENDER,
        "obs": np.zeros(OBS_DIM, dtype=np.float32),
        "history": np.zeros((1, HISTORY_EVENT_DIM), dtype=np.float32),
        "history_length": 0,
        "action": np.zeros(ACT_DIM, dtype=np.float32),
        "attacker_return": 2.5,
        "target": -2.5,
    }
    *_, targets = _collate([defender])
    assert targets.dtype == torch.float32
    assert targets.tolist() == [-2.5]


def _run_small_arm(tmp_path, arm: str, iterations: int):
    identity = screen._seed_identity(0)
    bundle = new_bundle(
        model_seed=identity["model_seed"],
        learner_rng_seed=identity["learner_rng_seed"],
    )
    initial_state = state_digest(bundle.learner.state_dict())
    actor_ref = publish_initial_actor(
        bundle.learner, tmp_path / arm / "initial-actor")
    runner = screen._new_screen_runner(
        bundle=bundle,
        actor_ref=actor_ref,
        snapshot_dir=tmp_path / arm / "candidates",
        root_seed=identity["runner_root_seed"],
        arm=arm,
    )
    ledger = screen._ExclusiveJsonl(tmp_path / arm / "ledger.jsonl")
    totals = screen._run_iterations(
        runner=runner,
        index=0,
        arm=arm,
        start=0,
        stop=iterations,
        ledger=ledger,
        checkpoint_root=tmp_path / arm / "checkpoints",
        milestones={},
        heartbeat=False,
    )
    rows = screen._load_jsonl(ledger.publish())
    return bundle, actor_ref, initial_state, totals, rows


def test_checkpoint_zero_keeps_distinct_same_state_candidate(tmp_path):
    identity = screen._seed_identity(0)
    bundle = new_bundle(
        model_seed=identity["model_seed"],
        learner_rng_seed=identity["learner_rng_seed"],
    )
    actor_ref = publish_initial_actor(
        bundle.learner, tmp_path / "initial-actor")
    runner = screen._new_screen_runner(
        bundle=bundle,
        actor_ref=actor_ref,
        snapshot_dir=tmp_path / "candidates",
        root_seed=identity["runner_root_seed"],
        arm="treatment",
    )
    milestone = screen._checkpoint_entry(
        runner, tmp_path / "checkpoint-0.pt")
    checkpoint_actor = screen._ref(milestone["actor_ref"])
    checkpoint_candidate = screen._ref(milestone["candidate_ref"])
    assert checkpoint_actor == actor_ref
    assert checkpoint_candidate != actor_ref
    assert screen._model_state_sha256(checkpoint_candidate) == \
        screen._model_state_sha256(actor_ref)


def test_short_real_preflight_segments_and_aggregate_validation(
        monkeypatch, tmp_path):
    """Exercise the real artifact chain at a deliberately tiny test dose."""
    spec_ref = screen._publish_json(tmp_path / "parent-spec.json", {"v": 1})
    runtime_ref = screen._publish_json(
        tmp_path / "parent-runtime.json", {"v": 1})
    monkeypatch.setattr(
        screen, "_require_frozen",
        lambda root: (spec_ref, runtime_ref, {}))
    monkeypatch.setattr(
        screen, "_frozen_refs_only",
        lambda root: (spec_ref, runtime_ref))
    monkeypatch.setattr(screen, "PREFLIGHT_ITERATIONS", 1)
    monkeypatch.setattr(screen, "RESUME_BOUNDARY", 1)
    monkeypatch.setattr(screen, "ITERATIONS", 2)
    monkeypatch.setattr(screen, "CHECKPOINT_ITERATIONS", (0, 1, 2))
    monkeypatch.setattr(screen, "PROBE_DEALS", 2)
    monkeypatch.setattr(screen, "REPORT_DEALS", 2)
    monkeypatch.setattr(
        screen, "SEED_IDENTITIES", (screen.SEED_IDENTITIES[0],))

    root = tmp_path / "screen"
    screen.initialize_seed(root, 0)
    screen.capture_probes(root, 0).verify()
    for arm in screen.ARMS:
        preflight_ref = screen.run_preflight(root, 0, arm)
        preflight_ref.verify()
        preflight = screen._load_json(preflight_ref)
        preflight_rows = screen._load_jsonl(
            screen._ref(preflight["ledger_ref"]))
        assert all(row["score_blind"] is True for row in preflight_rows)
        assert all(not set(screen.SCORE_TELEMETRY_FIELDS)
                   & set(row["update"]) for row in preflight_rows)
        screen.train_first_segment(root, 0, arm).verify()
        screen.train_second_segment(root, 0, arm).verify()
        _, initial, initial_actor = screen._initial_payload(root, 0)
        checkpoints, info = screen._validate_training(
            root, 0, arm, initial_actor,
            str(initial["learner_state_sha256"]))
        assert set(checkpoints) == {"0", "1", "2"}
        assert info["role_counts"]["attacker"] > 0
        assert info["role_counts"]["defender"] > 0
        screen.evaluate_report(root, 0, arm).verify()

    aggregate_ref = screen.aggregate(root)
    aggregate_ref.verify()
    recomputed = screen.verify_aggregate(aggregate_ref)
    assert recomputed["production_promotion"] is False
    assert recomputed["strength_claim"] is False
    assert recomputed["passed_learning_screen"] is all(
        recomputed["gates"].values())
    assert recomputed["failures"] == sorted(
        name for name, value in recomputed["gates"].items() if not value)

    original_resume_identity = screen.exact_resume_boundary_identity

    def tampered_resume(ref):
        identity = original_resume_identity(ref)
        if identity["progress"]["next_iteration"] == 1:
            identity = copy.deepcopy(identity)
            identity["bundle_sha256"] = "0" * 64
        return identity

    monkeypatch.setattr(
        screen, "exact_resume_boundary_identity", tampered_resume)
    with pytest.raises(screen.LearningScreenError,
                       match="resume-boundary mismatch"):
        screen._compute_aggregate(root)
    monkeypatch.setattr(
        screen, "exact_resume_boundary_identity", original_resume_identity)

    original_load_jsonl = screen._load_jsonl

    def tampered_probe(ref):
        rows = original_load_jsonl(ref)
        path = Path(ref.path)
        if path.parent.name == "probes" and path.name == "seed_0.jsonl":
            rows = copy.deepcopy(rows)
            rows[0]["obs"][0] += 0.25
        return rows

    monkeypatch.setattr(screen, "_load_jsonl", tampered_probe)
    with pytest.raises(screen.LearningScreenError,
                       match="probe semantic replay mismatch"):
        screen._compute_aggregate(root)

    def tampered_report(ref):
        rows = original_load_jsonl(ref)
        path = Path(ref.path)
        if path.parent.name == "report" \
                and path.name == "seed_0_treatment.jsonl":
            rows = copy.deepcopy(rows)
            rows[0]["attacker_points"] += 1
            attacker_return = screen.terminal_attacker_return(
                rows[0]["attacker_points"])
            role = (screen.ROLE_ATTACKER
                    if rows[0]["candidate_role"] == "attacker"
                    else screen.ROLE_DEFENDER)
            rows[0]["attacker_return"] = attacker_return
            rows[0]["candidate_signed_return"] = \
                screen.acting_team_return(attacker_return, role)
        return rows

    monkeypatch.setattr(screen, "_load_jsonl", tampered_report)
    with pytest.raises(screen.LearningScreenError,
                       match="REPORT semantic replay mismatch"):
        screen._compute_aggregate(root)


def test_small_training_dose_refreshes_actor_and_no_step_control_is_null(
        tmp_path):
    treatment, initial_ref, initial_state, totals, rows = _run_small_arm(
        tmp_path, "treatment", 2)
    assert totals["iterations"] == 2
    assert len(rows) == 2
    assert rows[0]["batch"]["actor"] == initial_ref.as_dict()
    assert rows[0]["adopted_actor_ref"] == rows[0]["candidate_ref"]
    assert rows[1]["batch"]["actor"] == rows[0]["candidate_ref"]
    assert rows[1]["adopted_actor_ref"] == rows[1]["candidate_ref"]
    assert state_digest(treatment.learner.state_dict()) != initial_state
    assert totals["attacker_samples"] > 0
    assert totals["defender_samples"] > 0
    for row in rows:
        for key in ("loss_before", "loss_after", "gradient_norm",
                    "prediction_min", "prediction_max", "target_min",
                    "target_max"):
            assert math.isfinite(float(row["update"][key]))

    control, _, control_initial, control_totals, control_rows = \
        _run_small_arm(tmp_path, "control", 1)
    assert control_totals["iterations"] == 1
    assert len(control_rows) == 1
    assert state_digest(control.learner.state_dict()) == control_initial
    candidate = screen._ref(control_rows[0]["candidate_ref"])
    candidate_model = load_verified(candidate, load_actor)
    assert state_digest(candidate_model.state_dict()) == control_initial
    assert control_rows[0]["update"]["arm"] == "control"
    assert math.isfinite(control_rows[0]["update"]["loss_before"])
