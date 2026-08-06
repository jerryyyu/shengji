"""Falsification tests for the synchronous learner resume boundary."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pytest


np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from shengji.rl.exact_resume import (  # noqa: E402
    ReplayRing,
    ResumeContractError,
    ResumeProgress,
    ResumeRollbackError,
    ResumeRNGStreams,
    load_exact_resume,
    save_exact_resume,
    state_digest,
)
from shengji.rl.selfplay_contract import CheckpointRef  # noqa: E402


EXPERIMENT = "s2-resume-falsification-v1"
CONTRACT_SHA256 = hashlib.sha256(b"synchronous learner contract").hexdigest()


@pytest.fixture(autouse=True)
def _deterministic_torch_runtime():
    enabled = torch.are_deterministic_algorithms_enabled()
    warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    torch.use_deterministic_algorithms(True, warn_only=False)
    try:
        yield
    finally:
        torch.use_deterministic_algorithms(enabled, warn_only=warn_only)


@dataclass
class _LearnerBundle:
    learner: object
    optimizer: object
    replay: ReplayRing
    rng: ResumeRNGStreams


def _new_bundle(*, rng_seed: int = 123) -> _LearnerBundle:
    learner = torch.nn.Sequential(
        torch.nn.Linear(2, 3),
        torch.nn.Tanh(),
        torch.nn.Linear(3, 1),
    )
    with torch.no_grad():
        offset = 0
        for parameter in learner.parameters():
            values = torch.arange(
                offset, offset + parameter.numel(), dtype=parameter.dtype)
            parameter.copy_(values.reshape_as(parameter).mul_(0.01).sub_(0.08))
            offset += parameter.numel()
    optimizer = torch.optim.Adam(learner.parameters(), lr=0.007)
    replay = ReplayRing(4)
    # Six inserts force a wrapped ring before the first update.  Exact resume
    # must preserve physical placement as well as chronological sample order.
    for index in range(6):
        replay.append({
            "x": np.asarray([index / 10, (index + 1) / 7], dtype=np.float32),
            "target": np.float32((index - 2) / 5),
            "origin": ("seed", index),
        })
    return _LearnerBundle(
        learner=learner,
        optimizer=optimizer,
        replay=replay,
        rng=ResumeRNGStreams.seeded(rng_seed),
    )


def _learner_step(bundle: _LearnerBundle,
                  progress: ResumeProgress) -> ResumeProgress:
    logical = bundle.replay.logical_items()
    sample_index = int(bundle.rng.numpy.integers(0, len(logical)))
    sample = logical[sample_index]
    python_jitter = bundle.rng.python.uniform(-0.03, 0.03)
    torch_jitter = torch.rand((), generator=bundle.rng.torch).mul(0.04)

    features = torch.from_numpy(sample["x"])
    target = torch.as_tensor(sample["target"]) + torch_jitter
    target = target + python_jitter + progress.next_batch * 1e-4
    prediction = bundle.learner(features).squeeze()
    loss = (prediction - target).square()
    bundle.optimizer.zero_grad()
    loss.backward()
    bundle.optimizer.step()
    bundle.optimizer.zero_grad(set_to_none=True)

    new_x = np.asarray([
        bundle.rng.numpy.normal(),
        bundle.rng.python.random(),
    ], dtype=np.float32)
    new_target = np.float32(
        torch.rand((), generator=bundle.rng.torch).item())
    bundle.replay.append({
        "x": new_x,
        "target": new_target,
        "origin": (progress.next_iteration, progress.next_batch),
    })
    return ResumeProgress(
        next_iteration=progress.next_iteration + 1,
        next_batch=progress.next_batch + 2,
    )


def _run_until(bundle: _LearnerBundle, progress: ResumeProgress,
               stop_iteration: int) -> ResumeProgress:
    while progress.next_iteration < stop_iteration:
        progress = _learner_step(bundle, progress)
    return progress


def _artifact_refs(tmp_path):
    actor = tmp_path / "actor.pt"
    candidate = tmp_path / "candidate.pt"
    actor.write_bytes(b"immutable actor generation 17")
    candidate.write_bytes(b"immutable learner candidate 23")
    return CheckpointRef.capture(actor), CheckpointRef.capture(candidate)


def _save_case(tmp_path):
    actor_ref, candidate_ref = _artifact_refs(tmp_path)
    bundle = _new_bundle()
    progress = _run_until(bundle, ResumeProgress(0, 11), 2)
    resume_ref = save_exact_resume(
        tmp_path / "resume.pt",
        learner=bundle.learner,
        optimizer=bundle.optimizer,
        replay=bundle.replay,
        rng=bundle.rng,
        progress=progress,
        actor_ref=actor_ref,
        candidate_ref=candidate_ref,
        experiment=EXPERIMENT,
        contract_sha256=CONTRACT_SHA256,
    )
    return resume_ref, actor_ref, candidate_ref, progress


def _load_case(resume_ref, actor_ref, candidate_ref, *,
               contract_sha256=CONTRACT_SHA256,
               replay_capacity=4):
    bundle = _new_bundle(rng_seed=999)
    if replay_capacity != 4:
        bundle.replay = ReplayRing(replay_capacity)
    receipt = load_exact_resume(
        resume_ref,
        learner=bundle.learner,
        optimizer=bundle.optimizer,
        replay=bundle.replay,
        rng=bundle.rng,
        expected_actor_ref=actor_ref,
        expected_candidate_ref=candidate_ref,
        expected_experiment=EXPERIMENT,
        expected_contract_sha256=contract_sha256,
    )
    return bundle, receipt


def _rewrite_payload(source_ref, target, mutate):
    payload = torch.load(
        source_ref.path, map_location="cpu", weights_only=False)
    mutate(payload)
    torch.save(payload, target)
    return CheckpointRef.capture(target)


def _bundle_digests(bundle: _LearnerBundle):
    return {
        "learner": state_digest(bundle.learner.state_dict()),
        "optimizer": state_digest(bundle.optimizer.state_dict()),
        "replay": state_digest(bundle.replay.state_dict()),
        "rng": state_digest(bundle.rng.state_dict()),
    }


def _load_into(bundle, resume_ref, actor_ref, candidate_ref):
    return load_exact_resume(
        resume_ref,
        learner=bundle.learner,
        optimizer=bundle.optimizer,
        replay=bundle.replay,
        rng=bundle.rng,
        expected_actor_ref=actor_ref,
        expected_candidate_ref=candidate_ref,
        expected_experiment=EXPERIMENT,
        expected_contract_sha256=CONTRACT_SHA256,
    )


def test_interrupted_resume_exactly_matches_uninterrupted_next_state(tmp_path):
    actor_ref, candidate_ref = _artifact_refs(tmp_path)
    initial = ResumeProgress(next_iteration=0, next_batch=11)

    uninterrupted = _new_bundle()
    uninterrupted_progress = _run_until(uninterrupted, initial, 8)

    interrupted = _new_bundle()
    boundary = _run_until(interrupted, initial, 3)
    resume_ref = save_exact_resume(
        tmp_path / "exact.pt",
        learner=interrupted.learner,
        optimizer=interrupted.optimizer,
        replay=interrupted.replay,
        rng=interrupted.rng,
        progress=boundary,
        actor_ref=actor_ref,
        candidate_ref=candidate_ref,
        experiment=EXPERIMENT,
        contract_sha256=CONTRACT_SHA256,
    )

    resumed, receipt = _load_case(
        resume_ref, actor_ref, candidate_ref)
    assert receipt.progress == boundary
    assert receipt.actor_ref == actor_ref
    assert receipt.candidate_ref == candidate_ref
    resumed_progress = _run_until(resumed, receipt.progress, 8)

    assert resumed_progress == uninterrupted_progress
    for uninterrupted_value, resumed_value in zip(
            uninterrupted.learner.state_dict().values(),
            resumed.learner.state_dict().values(), strict=True):
        assert torch.equal(uninterrupted_value, resumed_value)
    assert state_digest(uninterrupted.optimizer.state_dict()) == \
        state_digest(resumed.optimizer.state_dict())
    assert state_digest(uninterrupted.replay.state_dict()) == \
        state_digest(resumed.replay.state_dict())
    assert state_digest(uninterrupted.replay.logical_items()) == \
        state_digest(resumed.replay.logical_items())
    assert uninterrupted.replay.cursor == resumed.replay.cursor
    assert state_digest(uninterrupted.rng.state_dict()) == \
        state_digest(resumed.rng.state_dict())

    # The first values after the tested run also match, proving that resume did
    # not merely recreate the final parameters while leaving RNGs one draw off.
    assert uninterrupted.rng.python.random() == resumed.rng.python.random()
    assert uninterrupted.rng.numpy.integers(0, 2**31) == \
        resumed.rng.numpy.integers(0, 2**31)
    assert torch.equal(
        torch.rand((3,), generator=uninterrupted.rng.torch),
        torch.rand((3,), generator=resumed.rng.torch),
    )


def test_resume_refuses_missing_and_stale_semantic_fields(tmp_path):
    resume_ref, actor_ref, candidate_ref, _ = _save_case(tmp_path)
    missing = _rewrite_payload(
        resume_ref, tmp_path / "missing.pt", lambda value: value.pop("rng"))
    with pytest.raises(ResumeContractError, match="fields mismatch"):
        _load_case(missing, actor_ref, candidate_ref)

    def make_progress_stale(value):
        value["progress"]["next_batch"] += 1

    stale = _rewrite_payload(
        resume_ref, tmp_path / "stale.pt", make_progress_stale)
    with pytest.raises(ResumeContractError,
                       match="progress component digest mismatch"):
        _load_case(stale, actor_ref, candidate_ref)


def test_resume_refuses_outer_byte_drift(tmp_path):
    resume_ref, actor_ref, candidate_ref, _ = _save_case(tmp_path)
    resume_path = tmp_path / "resume.pt"
    resume_path.write_bytes(resume_path.read_bytes() + b"corruption")
    with pytest.raises(RuntimeError, match="checkpoint digest drift"):
        _load_case(resume_ref, actor_ref, candidate_ref)


def test_resume_refuses_wrong_contract_and_artifact_identity(tmp_path):
    resume_ref, actor_ref, candidate_ref, _ = _save_case(tmp_path)
    wrong_contract = hashlib.sha256(b"different contract").hexdigest()
    with pytest.raises(ResumeContractError, match="contract digest mismatch"):
        _load_case(
            resume_ref, actor_ref, candidate_ref,
            contract_sha256=wrong_contract)

    other_actor = tmp_path / "other_actor.pt"
    other_actor.write_bytes(b"different immutable actor")
    with pytest.raises(ResumeContractError,
                       match="actor artifact identity mismatch"):
        _load_case(
            resume_ref, CheckpointRef.capture(other_actor), candidate_ref)

    other_candidate = tmp_path / "other_candidate.pt"
    other_candidate.write_bytes(b"different immutable candidate")
    with pytest.raises(ResumeContractError,
                       match="candidate artifact identity mismatch"):
        _load_case(
            resume_ref, actor_ref, CheckpointRef.capture(other_candidate))


def test_resume_refuses_mutated_bound_artifact_bytes(tmp_path):
    resume_ref, actor_ref, candidate_ref, _ = _save_case(tmp_path)
    actor_path = tmp_path / "actor.pt"
    actor_path.write_bytes(b"mutated actor bytes")
    with pytest.raises(RuntimeError, match="checkpoint digest drift"):
        _load_case(resume_ref, actor_ref, candidate_ref)


def test_resume_refuses_pending_work_and_replay_capacity_drift(tmp_path):
    actor_ref, candidate_ref = _artifact_refs(tmp_path)
    bundle = _new_bundle()
    with pytest.raises(ResumeContractError, match="quiescent boundary"):
        save_exact_resume(
            tmp_path / "pending.pt",
            learner=bundle.learner,
            optimizer=bundle.optimizer,
            replay=bundle.replay,
            rng=bundle.rng,
            progress=ResumeProgress(0, 11),
            actor_ref=actor_ref,
            candidate_ref=candidate_ref,
            experiment=EXPERIMENT,
            contract_sha256=CONTRACT_SHA256,
            pending_jobs=1,
        )

    resume_ref = save_exact_resume(
        tmp_path / "capacity.pt",
        learner=bundle.learner,
        optimizer=bundle.optimizer,
        replay=bundle.replay,
        rng=bundle.rng,
        progress=ResumeProgress(0, 11),
        actor_ref=actor_ref,
        candidate_ref=candidate_ref,
        experiment=EXPERIMENT,
        contract_sha256=CONTRACT_SHA256,
    )
    with pytest.raises(ResumeContractError, match="replay capacity mismatch"):
        _load_case(
            resume_ref, actor_ref, candidate_ref, replay_capacity=5)


def test_resume_refuses_nondeterministic_or_drifted_runtime(tmp_path):
    actor_ref, candidate_ref = _artifact_refs(tmp_path)
    bundle = _new_bundle()
    torch.use_deterministic_algorithms(False)
    with pytest.raises(ResumeContractError,
                       match="requires Torch deterministic algorithms"):
        save_exact_resume(
            tmp_path / "nondeterministic.pt",
            learner=bundle.learner,
            optimizer=bundle.optimizer,
            replay=bundle.replay,
            rng=bundle.rng,
            progress=ResumeProgress(0, 11),
            actor_ref=actor_ref,
            candidate_ref=candidate_ref,
            experiment=EXPERIMENT,
            contract_sha256=CONTRACT_SHA256,
        )
    torch.use_deterministic_algorithms(True, warn_only=False)

    resume_ref = save_exact_resume(
        tmp_path / "runtime.pt",
        learner=bundle.learner,
        optimizer=bundle.optimizer,
        replay=bundle.replay,
        rng=bundle.rng,
        progress=ResumeProgress(0, 11),
        actor_ref=actor_ref,
        candidate_ref=candidate_ref,
        experiment=EXPERIMENT,
        contract_sha256=CONTRACT_SHA256,
    )

    def drift_python_version(payload):
        payload["runtime"]["python"]["version"] = "0.0-stale"
        payload["component_sha256"]["execution"] = state_digest({
            "runtime": payload["runtime"],
            "learner_schema": payload["learner_schema"],
        })

    drifted = _rewrite_payload(
        resume_ref, tmp_path / "runtime_drift.pt", drift_python_version)
    with pytest.raises(ResumeContractError,
                       match="numerical runtime identity mismatch"):
        _load_case(drifted, actor_ref, candidate_ref)


def test_resume_refuses_learner_schema_and_optimizer_topology_drift(tmp_path):
    resume_ref, actor_ref, candidate_ref, _ = _save_case(tmp_path)

    wrong_shape = _new_bundle(rng_seed=999)
    wrong_shape.learner = torch.nn.Sequential(
        torch.nn.Linear(2, 4),
        torch.nn.Tanh(),
        torch.nn.Linear(4, 1),
    )
    wrong_shape.optimizer = torch.optim.Adam(
        wrong_shape.learner.parameters(), lr=0.007)
    with pytest.raises(ResumeContractError,
                       match="learner or optimizer schema mismatch"):
        _load_into(wrong_shape, resume_ref, actor_ref, candidate_ref)

    wrong_topology = _new_bundle(rng_seed=999)
    wrong_topology.optimizer = torch.optim.Adam(
        reversed(list(wrong_topology.learner.parameters())), lr=0.007)
    with pytest.raises(ResumeContractError,
                       match="learner or optimizer schema mismatch"):
        _load_into(wrong_topology, resume_ref, actor_ref, candidate_ref)

    wrong_mode = _new_bundle(rng_seed=999)
    wrong_mode.learner.eval()
    with pytest.raises(ResumeContractError,
                       match="learner or optimizer schema mismatch"):
        _load_into(wrong_mode, resume_ref, actor_ref, candidate_ref)


def test_resume_refuses_mid_update_gradient_state(tmp_path):
    actor_ref, candidate_ref = _artifact_refs(tmp_path)
    bundle = _new_bundle()
    parameter = next(bundle.learner.parameters())
    parameter.grad = torch.ones_like(parameter)
    with pytest.raises(ResumeContractError, match="gradient-free"):
        save_exact_resume(
            tmp_path / "mid_update.pt",
            learner=bundle.learner,
            optimizer=bundle.optimizer,
            replay=bundle.replay,
            rng=bundle.rng,
            progress=ResumeProgress(0, 11),
            actor_ref=actor_ref,
            candidate_ref=candidate_ref,
            experiment=EXPERIMENT,
            contract_sha256=CONTRACT_SHA256,
        )


def test_late_restore_failure_rolls_back_every_mutable_component(tmp_path):
    resume_ref, actor_ref, candidate_ref, _ = _save_case(tmp_path)
    bundle = _new_bundle(rng_seed=999)
    before = _bundle_digests(bundle)
    real_load_rng = bundle.rng.load_state_dict
    calls = 0

    def fail_first_rng_restore(state):
        nonlocal calls
        calls += 1
        real_load_rng(state)
        if calls == 1:
            raise RuntimeError("injected late RNG restore failure")

    bundle.rng.load_state_dict = fail_first_rng_restore
    with pytest.raises(ResumeContractError,
                       match="original state restored"):
        _load_into(bundle, resume_ref, actor_ref, candidate_ref)
    assert calls == 2
    assert _bundle_digests(bundle) == before


def test_rollback_failure_requires_process_termination(tmp_path):
    resume_ref, actor_ref, candidate_ref, _ = _save_case(tmp_path)
    bundle = _new_bundle(rng_seed=999)
    real_load_rng = bundle.rng.load_state_dict

    def always_fail_rng_restore(state):
        real_load_rng(state)
        raise RuntimeError("injected RNG restore and rollback failure")

    bundle.rng.load_state_dict = always_fail_rng_restore
    with pytest.raises(ResumeRollbackError, match="caller must terminate"):
        _load_into(bundle, resume_ref, actor_ref, candidate_ref)
