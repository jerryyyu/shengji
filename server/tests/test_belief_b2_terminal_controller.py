"""One-shot publication and read-only terminal reconstruction tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

import shengji.rl.belief_b2_terminal_controller as terminal
from shengji.rl.belief_b2_protocol import CAPTURE_WALL_SECOND_CAP
from shengji.rl.belief_b2_result import NS_PER_SECOND
from shengji.rl.belief_b2_execution import (
    REQUIRED_ENVIRONMENT, REQUIRED_EXACT_PATHS, REVIEW_PREFIX,
    B2ExecutionDesignV1, RuntimeProfileV1, SourceBindingV1,
    build_pipeline_admission, expected_review_claim)
from shengji.rl.belief_b2_terminal_controller import (
    BeliefB2TerminalControllerError, run_open_test, verify_terminal)
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_cohort import COHORT_SEEDS
from shengji.rl.belief_evaluation import (reopen_score_pair,
                                           target_count_population)
from shengji.rl.belief_model import new_from_scratch_model
from shengji.rl.belief_ownership import (
    PROBABILITY_SCALE,
    BeliefOwnershipV1,
    ReceiverCountProbabilityV1,
    receiver_sizes,
)
from shengji.rl.belief_synthetic import build_c4_contexts
from shengji.rl.belief_trainer import model_state_sha256


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _design(root) -> B2ExecutionDesignV1:
    paths = (*REQUIRED_EXACT_PATHS,
             "server/shengji/rl/belief_b2_terminal_controller.py")
    bindings = tuple(SourceBindingV1(
        path=path, byte_count=index, sha256=_sha(path))
                     for index, path in enumerate(sorted(paths)))
    runtime = RuntimeProfileV1(
        hostname="test", operating_system="test", machine="x86_64",
        cpu_count=16, memory_bytes=32 << 30,
        boot_identity=_sha("boot"),
        python_executable="/runtime/python",
        python_resolved_executable="/runtime/python",
        python_executable_sha256=_sha("python"), python_version="3.14",
        torch_version="2.9", torch_config_sha256=_sha("torch"),
        numpy_version="2.3", native_path="/runtime/_fast.so",
        native_sha256=_sha("fast"),
        required_environment=REQUIRED_ENVIRONMENT)
    return B2ExecutionDesignV1(
        execution_git="a" * 40, source_bindings=bindings,
        runtime=runtime, evidence_root=str(root))


class _Bytes:
    def __init__(self, label):
        self.label = label

    def canonical_bytes(self):
        return canonical_json_bytes({"label": self.label})


def _authorized(root):
    design = _design(root)
    marker = REVIEW_PREFIX.encode() + canonical_json_bytes(
        expected_review_claim(design))
    admission = build_pipeline_admission(
        design, review_commit="b" * 40, review_marker=marker)
    return design, admission, marker


def _stub_derivation(monkeypatch):
    evidence = SimpleNamespace(inventory=_Bytes("inventory"))
    result = _Bytes("terminal")
    report = {"terminal": {"decision": "SELECT_NONE_NO_CALIBRATION_LIFT"}}
    monkeypatch.setattr(
        terminal, "derive_terminal_evidence",
        lambda _root, _design, _admission: evidence)
    monkeypatch.setattr(
        terminal, "evaluate_b2_terminal", lambda _evidence: result)
    monkeypatch.setattr(
        terminal, "_report_payload",
        lambda _design, _admission, _evidence: report)
    return report


def test_test_open_consumes_slot_before_derivation_failure(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    design, admission, marker = _authorized(root)

    def fail(*_args):
        raise RuntimeError("injected terminal failure")

    monkeypatch.setattr(terminal, "derive_terminal_evidence", fail)
    with pytest.raises(RuntimeError, match="injected"):
        run_open_test(root, design, admission, review_marker=marker)
    partial = root / "terminal.partial"
    assert partial.is_dir()
    assert {path.name for path in partial.iterdir()} == {"attempt.json"}
    with pytest.raises(BeliefB2TerminalControllerError, match="occupied"):
        run_open_test(root, design, admission, review_marker=marker)


def test_terminal_publication_and_reconstruction_are_closed(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    design, admission, marker = _authorized(root)
    expected = _stub_derivation(monkeypatch)
    assert run_open_test(
        root, design, admission, review_marker=marker) == expected
    directory = root / "terminal"
    assert {path.name for path in directory.iterdir()} == {
        "attempt.json", "result.json", "manifest.json"}
    assert verify_terminal(root, design, admission) == expected
    foreign = directory / "foreign.json"
    foreign.write_bytes(b"{}")
    with pytest.raises(
            BeliefB2TerminalControllerError, match="population"):
        verify_terminal(root, design, admission)
    foreign.unlink()
    result = directory / "result.json"
    result.chmod(0o600)
    result.write_bytes(b"{}")
    result.chmod(0o400)
    with pytest.raises(
            BeliefB2TerminalControllerError, match="reconstruction"):
        verify_terminal(root, design, admission)


def test_coordinated_result_and_manifest_rehash_hits_result_guard_exactly(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    design, admission, marker = _authorized(root)
    _stub_derivation(monkeypatch)
    run_open_test(root, design, admission, review_marker=marker)
    directory = root / "terminal"
    result = directory / "result.json"
    manifest = directory / "manifest.json"
    altered = canonical_json_bytes({
        "terminal": {"decision": "COORDINATED-REHASH-WITNESS"}})
    result.chmod(0o600)
    result.write_bytes(altered)
    result.chmod(0o400)
    manifest_row = json.loads(manifest.read_bytes())
    manifest_row["files"]["result.json"] = hashlib.sha256(
        altered).hexdigest()
    manifest.chmod(0o600)
    manifest.write_bytes(canonical_json_bytes(manifest_row))
    manifest.chmod(0o400)
    with pytest.raises(BeliefB2TerminalControllerError) as refusal:
        verify_terminal(root, design, admission)
    assert refusal.value.args == ("terminal result reconstruction drift",)


def test_parallel_resource_windows_use_wall_span_and_enforce_cap(tmp_path):
    design = _design((tmp_path / "evidence").resolve())

    def row(start, finish, *, cpu=0, device=0, size=0):
        return {"resources": {
            "started_monotonic_nanoseconds": start,
            "finished_monotonic_nanoseconds": finish,
            "cpu_nanoseconds": cpu,
            "device_nanoseconds": device,
            "artifact_bytes": size,
            "retry_count": 0,
        }}

    capture = (row(0, 10, cpu=7, size=3),
               row(5, 20, cpu=11, size=5))
    reference = (row(100, 110, cpu=13, size=7),
                 row(102, 118, cpu=17, size=9))
    training = (row(200, 230, device=19, size=11),
                row(205, 240, device=23, size=13))
    receipt = terminal._resources(
        design, capture, reference, training)
    assert receipt.capture_wall_nanoseconds == 20
    assert receipt.capture_cpu_nanoseconds == 18
    assert receipt.capture_artifact_bytes == 8
    assert receipt.reference_wall_nanoseconds == 18
    assert receipt.reference_cpu_nanoseconds == 30
    assert receipt.training_wall_nanoseconds == 40
    assert receipt.training_device_nanoseconds == 42
    assert receipt.within_caps is True

    over_cap = (row(
        0, CAPTURE_WALL_SECOND_CAP * NS_PER_SECOND + 1,
        cpu=1, size=1),)
    refused = terminal._resources(
        design, over_cap, reference, training)
    assert refused.capture_wall_nanoseconds \
        == CAPTURE_WALL_SECOND_CAP * NS_PER_SECOND + 1
    assert refused.within_caps is False


def test_terminal_mechanics_are_measured_from_real_witnesses():
    contexts = build_c4_contexts()
    models = tuple(new_from_scratch_model(seed) for seed in COHORT_SEEDS)
    model_sha256s = tuple(model_state_sha256(model) for model in models)
    measured = terminal._c4_mechanics_witnesses(
        contexts, models, model_sha256s)
    assert measured[:6] == (4, 0, 36, 0, 36, 0)
    assert measured[6] == 108
    assert measured[7] > 0
    assert measured[8:] == (0, 0)

    wrong_rotation = replace(
        contexts[0], rotated_world_0=contexts[0].world_1)
    mutated = terminal._c4_mechanics_witnesses(
        (wrong_rotation, *contexts[1:]), models, model_sha256s)
    assert mutated[2:6] == (36, 9, 36, 0)
    assert mutated[6:] == measured[6:]

    actor, _, _ = reopen_score_pair(contexts[0].world_0)
    members, ensemble = terminal._predict_members(
        models, model_sha256s, actor)
    count, rows, conservation, hard_facts = (
        terminal._validated_prediction_population(
        actor, (*members, ensemble))
    )
    assert count == 9 and rows > 0
    assert (conservation, hard_facts) == (0, 0)
    with pytest.raises(ValueError):
        terminal._validated_prediction_population(
            actor, (replace(ensemble, probabilities=()),))


def test_terminal_mechanics_counts_real_conservation_and_hard_fact_rows():
    context = build_c4_contexts()[0]
    actor, target, _ = reopen_score_pair(context.world_0)
    counts = target_count_population(actor, target)
    valid = BeliefOwnershipV1(
        actor_observation_sha256=actor.sha256(),
        model_schema="terminal-mechanics-count-witness",
        model_sha256="a" * 64,
        behavior_policy_ids=("mc-s0-report-lcb",),
        receiver_sizes=receiver_sizes(actor),
        probabilities=tuple(ReceiverCountProbabilityV1(
            card=card,
            receiver=receiver,
            count_0_ppb=PROBABILITY_SCALE if count == 0 else 0,
            count_1_ppb=PROBABILITY_SCALE if count == 1 else 0,
            count_2_ppb=PROBABILITY_SCALE if count == 2 else 0,
        ) for (card, receiver), count in counts.items()),
    )

    conservation_rows = list(valid.probabilities)
    conservation_index = next(
        index for index, row in enumerate(conservation_rows)
        if counts[(row.card, row.receiver)] == 0)
    row = conservation_rows[conservation_index]
    conservation_rows[conservation_index] = replace(
        row,
        count_0_ppb=PROBABILITY_SCALE - 1,
        count_1_ppb=1,
    )
    conservation_bad = replace(
        valid, probabilities=tuple(conservation_rows))

    hard_fact_rows = list(valid.probabilities)
    unseen = dict(actor.deductions.unseen)
    hard_fact_index = next(
        index for index, current in enumerate(hard_fact_rows)
        if unseen[current.card] == 1
        and counts[(current.card, current.receiver)] == 1)
    row = hard_fact_rows[hard_fact_index]
    hard_fact_rows[hard_fact_index] = replace(
        row,
        count_0_ppb=PROBABILITY_SCALE // 2,
        count_1_ppb=0,
        count_2_ppb=PROBABILITY_SCALE // 2,
    )
    hard_fact_bad = replace(valid, probabilities=tuple(hard_fact_rows))

    measured = terminal._validated_prediction_population(
        actor, (conservation_bad, hard_fact_bad))
    expected_conservation_rows = (
        len(receiver_sizes(actor)) + len(actor.deductions.unseen) - 1)
    assert measured == (
        2,
        2 * len(valid.probabilities),
        expected_conservation_rows,
        1,
    )
