"""Falsification tests for the frozen, non-admitted O0-v2 Air packet."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from shengji.rl.selfplay_contract import CheckpointRef  # noqa: E402
from shengji.rl.suphx_actor import publish_initial_actor  # noqa: E402
from shengji.rl.suphx_o0_v2_screen import (  # noqa: E402
    CELL_CONTROL,
    CELL_MARGIN,
    CELLS,
    CRN_SPEC,
    EVAL_DEALS,
    EVAL_SEED0,
    EXPECTED_HOST,
    EXPECTED_PYTHON,
    FAMILY_ALPHA_MAX,
    ITERATIONS,
    MARGIN_SPEC,
    ONE_SIDED_ALPHA_EACH,
    PACKET_REVIEW_MARKER,
    PACKET_REVIEW_SCHEMA,
    RUN_ID,
    SEED_IDENTITIES,
    SuphxO0V2ScreenError,
    _algorithm,
    _cell_criteria,
    _comparison_round,
    _deal_collision_proof,
    _exact_two_flip_means,
    _packet_review_claim,
    _require_admission,
    _spec_payload,
    _student_t_summary,
    _terminal_verdict,
    admit_packet,
    freeze_packet,
    verify_packet,
)
from shengji.rl.suphx_policy import new_from_scratch_model  # noqa: E402
from shengji.rl import suphx_o0_v2_screen as screen  # noqa: E402


_LAUNCHER_PATH = Path(__file__).resolve().parents[1] \
    / "scripts" / "suphx_o0_v2_screen.py"
_LAUNCHER_SPEC = importlib.util.spec_from_file_location(
    "suphx_o0_v2_screen_launcher_test", _LAUNCHER_PATH)
assert _LAUNCHER_SPEC is not None and _LAUNCHER_SPEC.loader is not None
launcher = importlib.util.module_from_spec(_LAUNCHER_SPEC)
_LAUNCHER_SPEC.loader.exec_module(launcher)


def _runtime():
    return {
        "git": "a" * 40,
        "material_tree_clean": True,
        "host": EXPECTED_HOST,
        "machine": "arm64",
        "python": EXPECTED_PYTHON,
        "python_executable": "/test/python3.14",
        "numpy": np.__version__,
        "torch": torch.__version__,
        "device": "cpu",
        "cpu_count": 10,
        "torch_num_threads": 1,
        "torch_num_interop_threads": 1,
        "fast_engine": True,
        "require_voids": True,
    }


@pytest.fixture
def frozen_packet(tmp_path, monkeypatch):
    root = tmp_path / "packet"
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}\n")
    preflight_ref = CheckpointRef.capture(preflight)
    monkeypatch.setattr(screen, "EXPECTED_RUN_ROOT", root)
    monkeypatch.setattr(screen, "runtime_identity", _runtime)
    monkeypatch.setattr(
        screen, "source_identity",
        lambda: {"schema": "test-sources", "files": {"x": "b" * 64}},
    )
    monkeypatch.setattr(screen, "_preflight_ref", lambda: preflight_ref)
    ref = freeze_packet(root)
    return root, ref


def test_population_and_gate_contract_are_fresh_and_factorial():
    assert len(SEED_IDENTITIES) == 8
    assert {value["index"] for value in SEED_IDENTITIES} == set(range(8))
    for field in ("model_seed", "learner_rng_seed", "runner_root_seed"):
        assert len({value[field] for value in SEED_IDENTITIES}) == 8
    proof = _deal_collision_proof()
    assert proof["training_deals_total"] == 8 * ITERATIONS
    assert proof["unique_training_deals"] == 8 * ITERATIONS
    assert proof["evaluation_deals"] == list(
        range(EVAL_SEED0, EVAL_SEED0 + EVAL_DEALS))
    assert proof["training_evaluation_collisions"] == 0
    assert proof["training_sequential_namespace_collisions"] == 0

    spec = _spec_payload()
    assert spec["cells"] == [
        {"name": CELL_CONTROL, "shared_public_crn": True,
         "margin_spec": None},
        {"name": CELL_MARGIN, "shared_public_crn": True,
         "margin_spec": MARGIN_SPEC.as_dict()},
    ]
    assert spec["inference"]["training_seed_count"] == 8
    assert spec["inference"]["one_sided_alpha_each"] == \
        ONE_SIDED_ALPHA_EACH
    assert spec["inference"]["two_cell_family_alpha_max"] == FAMILY_ALPHA_MAX
    assert spec["inference"][
        "cell_verdicts_are_predeclared_without_best_cell_selection"] is True
    assert spec["authority"]["packet_review_required_before_training"] is True
    assert spec["authority"]["o1_training"] is False
    assert spec["authority"]["strength"] is False
    assert spec["authority"]["production"] is False
    replay = spec["evaluation"]["semantic_replay"]
    assert replay == {
        "post_publication_endpoint_replay": True,
        "gate_compute_replay": True,
        "gate_internal_verify_replay": True,
        "independent_verify_gate_replay_required": True,
        "passes_after_generation": 4,
        "rounds_per_pass": 12_288,
        "total_evaluation_executions": 61_440,
    }


def test_preimport_launcher_pins_threads_and_refuses_sampler_flags():
    clean = dict(launcher.REQUIRED_ENVIRONMENT)
    assert launcher.preimport_environment_problems(clean) == []
    for name in launcher.REQUIRED_ENVIRONMENT:
        missing = dict(clean)
        missing.pop(name)
        assert launcher.preimport_environment_problems(missing)
    contaminated = dict(clean)
    contaminated["SHENGJI_WEIGHTED_SPLITS"] = ""
    problems = launcher.preimport_environment_problems(contaminated)
    assert any("must be absent" in problem for problem in problems)


def test_control_and_margin_algorithms_differ_only_by_named_cell_factor():
    control = _algorithm(3, CELL_CONTROL, "oracle").as_dict()
    margin = _algorithm(3, CELL_MARGIN, "oracle").as_dict()
    assert control["crn_spec"] == margin["crn_spec"] == CRN_SPEC.as_dict()
    assert control["training_seed_index"] == margin["training_seed_index"] == 3
    assert control["arm"] == margin["arm"] == "oracle"
    assert control["learning_rate"] == margin["learning_rate"] == 1e-3
    assert control["iterations"] == margin["iterations"] == 64
    assert control["cell"] == CELL_CONTROL
    assert margin["cell"] == CELL_MARGIN
    assert control["margin_spec"] is None
    assert margin["margin_spec"] == MARGIN_SPEC.as_dict()


def test_freeze_publishes_exact_non_authorizing_packet(frozen_packet):
    root, ref = frozen_packet
    packet = verify_packet(ref)
    assert ref == CheckpointRef.capture(root / "launch_packet.json")
    assert packet["runtime"] == _runtime()
    assert packet["preflight_ref"] == screen._preflight_ref().as_dict()
    assert packet["review_required"] is True
    assert packet["training_authorized"] is False
    assert packet["o1_authorized"] is False
    assert packet["strength_claim"] is False
    assert packet["production_promotion"] is False
    assert len(packet["initial_manifest_refs"]) == 8
    assert not (root / "review_admission.json").exists()
    assert not (root / "gate.json").exists()
    with pytest.raises(SuphxO0V2ScreenError, match="absent or empty"):
        freeze_packet(root)


def _review_bytes(packet_ref, **updates):
    claim = {
        "schema": PACKET_REVIEW_SCHEMA,
        "git": "a" * 40,
        "run_id": RUN_ID,
        "packet_sha256": packet_ref.sha256,
        "host": EXPECTED_HOST,
        "python": EXPECTED_PYTHON,
        "independent_review": True,
        "training_authorized": True,
        "o1_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "verdict": "PASS",
    }
    claim.update(updates)
    return (PACKET_REVIEW_MARKER + json.dumps(
        claim, sort_keys=True, separators=(",", ":")) + "\n").encode()


def test_admission_requires_one_exact_independent_review_marker(
        frozen_packet, tmp_path):
    root, packet_ref = frozen_packet
    review = tmp_path / "immutable-review.txt"
    review.write_bytes(_review_bytes(packet_ref))
    review_ref = CheckpointRef.capture(review)
    admission_ref = admit_packet(
        packet_ref,
        expected_packet_sha256=packet_ref.sha256,
        review_record=review,
        expected_review_sha256=review_ref.sha256,
    )
    reopened_packet, reopened_admission, admission = _require_admission(root)
    assert reopened_packet == packet_ref
    assert reopened_admission == admission_ref
    assert admission["training_authorized"] is True
    assert admission["o1_authorized"] is False
    assert admission["strength_claim"] is False
    assert admission["production_promotion"] is False
    # Later mutation/removal of the source review cannot invalidate the copied
    # immutable admission record.
    review.unlink()
    _require_admission(root)


@pytest.mark.parametrize("mutation", [
    {"git": "b" * 40},
    {"packet_sha256": "0" * 64},
    {"host": "wrong"},
    {"python": "3.13.0"},
    {"independent_review": False},
    {"training_authorized": False},
    {"o1_authorized": True},
    {"strength_claim": True},
    {"production_promotion": True},
    {"verdict": "HOLD"},
])
def test_review_marker_authority_mutations_refuse(frozen_packet, mutation):
    _, packet_ref = frozen_packet
    with pytest.raises(SuphxO0V2ScreenError):
        _packet_review_claim(_review_bytes(packet_ref, **mutation), packet_ref)


def test_seed_clustered_summary_and_terminal_verdict_are_predeclared():
    summary = _student_t_summary([1.0] * 8)
    assert summary == {
        "n": 8,
        "mean": 1.0,
        "se": 0.0,
        "one_sided_alpha": 0.025,
        "df": 7,
        "critical_value": 2.3646242515927844,
        "lcb": 1.0,
    }
    assert _terminal_verdict(CELLS) == "ADVANCE_BOTH"
    assert _terminal_verdict([CELL_CONTROL]) == "ADVANCE_CRN_CONTROL"
    assert _terminal_verdict([CELL_MARGIN]) == "ADVANCE_CRN_PLUS_MARGIN"
    assert _terminal_verdict([]) == "SELECT_NONE"
    with pytest.raises(SuphxO0V2ScreenError):
        _terminal_verdict(["future"])


def test_every_named_cell_gate_is_nonvacuous():
    means = {
        str(index): {
            "oracle_minus_public": 1.0,
            "oracle_minus_initial": 1.0,
            "same_model_null": 0.0,
        }
        for index in range(8)
    }
    baseline = _cell_criteria(
        cell=CELL_CONTROL,
        primary={"lcb": 0.5},
        seed_means=means,
        coupling={"passed": True},
        null_exact=True,
    )
    assert all(baseline.values())

    mutations = []
    changed = copy.deepcopy(means)
    changed["0"]["oracle_minus_public"] = 0.0
    mutations.append({"seed_means": changed})
    changed = copy.deepcopy(means)
    changed["0"]["oracle_minus_initial"] = 0.0
    mutations.append({"seed_means": changed})
    mutations.extend([
        {"primary": {"lcb": 0.0}},
        {"coupling": {"passed": False}},
        {"null_exact": False},
    ])
    for mutation in mutations:
        kwargs = {
            "cell": CELL_CONTROL,
            "primary": {"lcb": 0.5},
            "seed_means": means,
            "coupling": {"passed": True},
            "null_exact": True,
        }
        kwargs.update(mutation)
        criteria = _cell_criteria(**kwargs)
        assert not all(criteria.values())


def test_same_model_two_flip_evaluation_null_is_exact(tmp_path, monkeypatch):
    torch.use_deterministic_algorithms(True, warn_only=False)
    model = new_from_scratch_model(161_000_001)
    ref = publish_initial_actor(model, tmp_path / "actor")
    rows = [
        _comparison_round(
            comparison="same_model_null",
            index=0,
            cell=CELL_CONTROL,
            deal_seed=EVAL_SEED0,
            flip=flip,
            candidate_model=model,
            reference_model=model,
            candidate_ref=ref,
            reference_ref=ref,
            candidate_gamma=1.0,
            reference_gamma=1.0,
        )
        for flip in (0, 1)
    ]
    assert rows[0]["attacker_points"] == rows[1]["attacker_points"]
    assert rows[0]["candidate_signed_return"] == \
        -rows[1]["candidate_signed_return"]
    monkeypatch.setattr(screen, "EVAL_DEALS", 1)
    means = _exact_two_flip_means(rows)
    assert means == {EVAL_SEED0: 0.0}


def test_packet_refuses_unknown_cell_and_seed():
    with pytest.raises(SuphxO0V2ScreenError):
        _algorithm(8, CELL_CONTROL, "oracle")
    with pytest.raises(SuphxO0V2ScreenError):
        _algorithm(0, "future", "oracle")


def _write_json(path: Path, payload) -> CheckpointRef:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return CheckpointRef.capture(path)


def _write_jsonl(path: Path, rows) -> CheckpointRef:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows), encoding="utf-8")
    return CheckpointRef.capture(path)


def test_evaluation_loader_replays_models_and_refuses_self_consistent_outcome(
        tmp_path, monkeypatch):
    root = tmp_path / "semantic-replay"
    root.mkdir()
    monkeypatch.setattr(screen, "EXPECTED_RUN_ROOT", root)
    monkeypatch.setattr(screen, "EVAL_DEALS", 1)

    model = new_from_scratch_model(161_000_001)
    actor_ref = publish_initial_actor(model, root / "actor")
    packet_ref = _write_json(root / "packet.json", {"kind": "packet"})
    admission_ref = _write_json(
        root / "admission.json", {"kind": "admission"})
    initial_manifest_ref = _write_json(
        root / "initial.json", {"kind": "initial"})
    oracle_training_ref = _write_json(
        root / "oracle-training.json", {"kind": "oracle"})
    public_training_ref = _write_json(
        root / "public-training.json", {"kind": "public"})

    definitions = {
        "oracle_minus_public": (actor_ref, actor_ref, 1.0, 0.0),
        "oracle_minus_initial": (actor_ref, actor_ref, 1.0, 1.0),
        "same_model_null": (actor_ref, actor_ref, 1.0, 1.0),
    }
    rows = []
    for comparison, (
            candidate_ref, reference_ref, candidate_gamma,
            reference_gamma) in definitions.items():
        for flip in (0, 1):
            rows.append(_comparison_round(
                comparison=comparison,
                index=0,
                cell=CELL_CONTROL,
                deal_seed=EVAL_SEED0,
                flip=flip,
                candidate_model=model,
                reference_model=model,
                candidate_ref=candidate_ref,
                reference_ref=reference_ref,
                candidate_gamma=candidate_gamma,
                reference_gamma=reference_gamma,
            ))
    rows_path = root / "eval" / CELL_CONTROL / "seed_0.jsonl"
    rows_ref = _write_jsonl(rows_path, rows)
    manifest = {
        "schema": screen.EVAL_SCHEMA,
        "screen_schema": screen.SCREEN_SCHEMA,
        "run_id": RUN_ID,
        "packet_ref": packet_ref.as_dict(),
        "admission_ref": admission_ref.as_dict(),
        "initial_manifest_ref": initial_manifest_ref.as_dict(),
        "oracle_training_ref": oracle_training_ref.as_dict(),
        "public_training_ref": public_training_ref.as_dict(),
        "seed_index": 0,
        "cell": CELL_CONTROL,
        "model_refs": {
            "initial": actor_ref.as_dict(),
            "oracle": actor_ref.as_dict(),
            "public": actor_ref.as_dict(),
        },
        "comparisons": list(screen.COMPARISONS),
        "deal_seed0": EVAL_SEED0,
        "deals": 1,
        "flips": [0, 1],
        "rounds": 6,
        "comparison_rounds": {
            name: 2 for name in screen.COMPARISONS},
        "rows_ref": rows_ref.as_dict(),
        "complete": True,
        "o1_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    manifest_path = root / "eval" / CELL_CONTROL / "seed_0.json"
    _write_json(manifest_path, manifest)

    monkeypatch.setattr(
        screen, "_require_admission",
        lambda _root: (packet_ref, admission_ref, {}))
    monkeypatch.setattr(
        screen, "_verify_initial",
        lambda _root, _index: (initial_manifest_ref, actor_ref, {}))
    monkeypatch.setattr(
        screen, "_load_training",
        lambda _root, _index, _cell, arm: (
            oracle_training_ref if arm == "oracle" else public_training_ref,
            actor_ref, {}, []))

    _, comparisons, _ = screen._load_evaluation(root, 0, CELL_CONTROL)
    assert set(comparisons) == set(screen.COMPARISONS)

    changed = copy.deepcopy(rows)
    row = changed[0]
    row["attacker_points"] += 40
    role = screen._candidate_role(row["banker"], row["candidate_team"])
    attacker_return = screen.clipped_attacker_bracket_return(
        row["attacker_points"])
    signed = screen.acting_team_return(attacker_return, role)
    row["attacker_bracket_return"] = attacker_return
    row["candidate_signed_return"] = signed
    row["candidate_won"] = int(signed > 0.0)
    manifest["rows_ref"] = _write_jsonl(rows_path, changed).as_dict()
    _write_json(manifest_path, manifest)
    with pytest.raises(SuphxO0V2ScreenError, match="semantic replay"):
        screen._load_evaluation(root, 0, CELL_CONTROL)


def test_run_and_independent_gate_verification_reenter_evaluation_loader(
        tmp_path, monkeypatch):
    root = tmp_path / "gate-replay"
    root.mkdir()
    monkeypatch.setattr(screen, "EXPECTED_RUN_ROOT", root)
    placeholder = _write_json(root / "input.json", {"kind": "input"})
    monkeypatch.setattr(
        screen, "_require_admission",
        lambda _root: (placeholder, placeholder, {}))
    monkeypatch.setattr(
        screen, "_load_training",
        lambda *_args: (placeholder, placeholder, {}, []))
    monkeypatch.setattr(
        screen, "cross_arm_coupling_gate",
        lambda *_args: {"passed": True})
    calls = []

    def load_evaluation(_root, index, cell):
        calls.append((index, cell))
        return placeholder, {
            "oracle_minus_public": {EVAL_SEED0: 1.0},
            "oracle_minus_initial": {EVAL_SEED0: 1.0},
            "same_model_null": {EVAL_SEED0: 0.0},
        }, {}

    monkeypatch.setattr(screen, "_load_evaluation", load_evaluation)
    gate_ref = screen.run_gate(root)
    # Gate computation and its mandatory internal verification each traverse
    # every seed/cell evaluation through the no-toggle replay loader.
    assert len(calls) == 2 * len(CELLS) * len(SEED_IDENTITIES)
    payload = screen.verify_gate(gate_ref)
    assert len(calls) == 3 * len(CELLS) * len(SEED_IDENTITIES)
    assert payload["semantic_replay_contract"] \
        == screen._semantic_replay_contract()
    assert payload["verdict"] == "ADVANCE_BOTH"
