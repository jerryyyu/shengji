"""Falsification tests for synchronous Suphx policy-gradient mechanics."""
from __future__ import annotations

import pytest


pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from shengji.rl.exact_resume import state_digest  # noqa: E402
from shengji.rl.suphx_actor import (  # noqa: E402
    SuphxMicroCollector,
    actor_batch_bytes,
    publish_initial_actor,
)
from shengji.rl.suphx_learning import (  # noqa: E402
    ENTROPY_CONTROLLER_STEP,
    GRADIENT_NORM_CAP,
    LEARNING_SOURCE_SHA256S,
    LEARNING_SPEC,
    LEARNING_SPEC_SHA256,
    MAX_ENTROPY_ALPHA,
    REPLAY_CAPACITY,
    TARGET_ENTROPY_FRACTION,
    VALUE_COEFFICIENT,
    SuphxLearningError,
    SuphxPolicyGradientUpdate,
    SuphxSchedule,
    SuphxScheduledCollector,
    algorithm_sha256,
    algorithm_spec,
    bundle_digest,
    contract_digest,
    new_bundle,
    new_runner,
    resume_runner,
)
ROOT_SEED = 20260807
LEARNING_RATE = 1e-3


@pytest.fixture(autouse=True)
def _deterministic_torch_runtime():
    enabled = torch.are_deterministic_algorithms_enabled()
    warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    torch.use_deterministic_algorithms(True, warn_only=False)
    try:
        yield
    finally:
        torch.use_deterministic_algorithms(enabled, warn_only=warn_only)


def _case(tmp_path, name="case", *, model_seed=11, rng_seed=13,
          actor_ref=None, schedule=None):
    if schedule is None:
        schedule = SuphxSchedule(
            segment_id="test-segment",
            keep_probabilities=(1.0, 0.0),
            learning_rate=LEARNING_RATE,
        )
    bundle = new_bundle(
        model_seed=model_seed,
        learner_rng_seed=rng_seed,
        learning_rate=schedule.learning_rate,
    )
    if actor_ref is None:
        actor_ref = publish_initial_actor(
            bundle.learner, tmp_path / f"{name}-actor")
    runner = new_runner(
        bundle=bundle,
        actor_ref=actor_ref,
        snapshot_dir=tmp_path / f"{name}-candidates",
        root_seed=ROOT_SEED,
        schedule=schedule,
    )
    return bundle, actor_ref, runner, schedule


def test_learning_contract_and_schedule_bind_every_material_choice():
    assert LEARNING_SPEC_SHA256 == contract_digest(LEARNING_SPEC)
    assert LEARNING_SPEC["source_sha256s"] == LEARNING_SOURCE_SHA256S
    assert LEARNING_SPEC["objective"]["value_coefficient"] == \
        VALUE_COEFFICIENT
    assert LEARNING_SPEC["objective"][
        "target_entropy_fraction_of_log_ballot"] == TARGET_ENTROPY_FRACTION
    assert LEARNING_SPEC["objective"]["entropy_controller_step"] == \
        ENTROPY_CONTROLLER_STEP
    assert LEARNING_SPEC["objective"]["max_entropy_alpha"] == \
        MAX_ENTROPY_ALPHA
    assert LEARNING_SPEC["optimizer"]["gradient_norm_cap"] == \
        GRADIENT_NORM_CAP
    assert LEARNING_SPEC["replay"]["capacity"] == REPLAY_CAPACITY
    assert LEARNING_SPEC["replay"]["older_samples_used_for_update"] is False

    schedule = SuphxSchedule(
        segment_id="curriculum", keep_probabilities=(1.0, 0.5, 0.0),
        learning_rate=LEARNING_RATE)
    assert algorithm_sha256(schedule) == state_digest(algorithm_spec(schedule))
    for changed in (
        SuphxSchedule("other", schedule.keep_probabilities, LEARNING_RATE),
        SuphxSchedule("curriculum", (1.0, 0.4, 0.0), LEARNING_RATE),
        SuphxSchedule("curriculum", schedule.keep_probabilities, 1e-4),
    ):
        assert algorithm_sha256(changed) != algorithm_sha256(schedule)


@pytest.mark.parametrize("kwargs", [
    {"segment_id": "", "keep_probabilities": (1.0,),
     "learning_rate": LEARNING_RATE},
    {"segment_id": "bad segment", "keep_probabilities": (1.0,),
     "learning_rate": LEARNING_RATE},
    {"segment_id": "x", "keep_probabilities": (),
     "learning_rate": LEARNING_RATE},
    {"segment_id": "x", "keep_probabilities": (1.1,),
     "learning_rate": LEARNING_RATE},
    {"segment_id": "x", "keep_probabilities": (1.0,),
     "learning_rate": 0.0},
])
def test_schedule_refuses_invalid_identity_probability_and_rate(kwargs):
    with pytest.raises(SuphxLearningError):
        SuphxSchedule(**kwargs)


def test_one_iteration_updates_policy_value_entropy_and_exact_candidate(tmp_path):
    bundle, _, runner, schedule = _case(tmp_path)
    before = state_digest(bundle.learner.state_dict())
    alphas_before = {
        key: float(head.entropy_alpha.item())
        for key, head in bundle.learner.surfaces.items()}
    receipt = runner.run_iteration(
        SuphxScheduledCollector(runner.contract_sha256, schedule),
        SuphxPolicyGradientUpdate(schedule),
    )
    assert receipt.progress.next_iteration == 1
    assert receipt.samples_added == len(bundle.replay)
    assert state_digest(bundle.learner.state_dict()) != before
    assert bundle.optimizer.state_dict()["state"]
    receipt.candidate_ref.verify()
    alphas_after = {
        key: float(head.entropy_alpha.item())
        for key, head in bundle.learner.surfaces.items()}
    assert any(alphas_after[key] != alphas_before[key]
               for key in alphas_before)
    assert all(0.0 <= value <= MAX_ENTROPY_ALPHA
               for value in alphas_after.values())


class _CaptureCollector:
    def __init__(self, inner):
        self.inner = inner
        self.batches = []

    def __call__(self, identity):
        batch = self.inner(identity)
        self.batches.append(actor_batch_bytes(batch))
        return batch


def _run_and_adopt(runner, schedule, collector=None):
    if collector is None:
        collector = SuphxScheduledCollector(runner.contract_sha256, schedule)
    receipt = runner.run_iteration(
        collector, SuphxPolicyGradientUpdate(schedule))
    adopted = runner.adopt_current_candidate_as_actor()
    assert adopted == receipt.candidate_ref
    return receipt


def test_interrupted_resume_matches_across_privilege_boundary(tmp_path):
    schedule = SuphxSchedule(
        segment_id="one-to-zero",
        keep_probabilities=(1.0, 0.0),
        learning_rate=LEARNING_RATE,
    )
    live_bundle, _, live, _ = _case(
        tmp_path, "live", model_seed=101, rng_seed=23, schedule=schedule)
    live_collector = _CaptureCollector(
        SuphxScheduledCollector(live.contract_sha256, schedule))
    first = _run_and_adopt(live, schedule, live_collector)
    checkpoint = live.save_checkpoint(tmp_path / "after-one.pt")
    expected = _run_and_adopt(live, schedule, live_collector)

    restored_bundle = new_bundle(
        model_seed=999, learner_rng_seed=999,
        learning_rate=schedule.learning_rate)
    restored = resume_runner(
        checkpoint,
        bundle=restored_bundle,
        actor_ref=first.candidate_ref,
        candidate_ref=first.candidate_ref,
        snapshot_dir=tmp_path / "restored-candidates",
        root_seed=ROOT_SEED,
        schedule=schedule,
    )
    resumed_collector = _CaptureCollector(
        SuphxScheduledCollector(restored.contract_sha256, schedule))
    resumed = _run_and_adopt(restored, schedule, resumed_collector)

    assert live_collector.batches[1] == resumed_collector.batches[0]
    assert resumed.batch == expected.batch
    assert resumed.candidate_ref.path != expected.candidate_ref.path
    assert resumed.candidate_ref.sha256 == expected.candidate_ref.sha256
    assert bundle_digest(restored_bundle) == bundle_digest(live_bundle)


def test_stale_learner_refuses_behavior_probability_and_poisons_runner(tmp_path):
    bundle, _, runner, schedule = _case(tmp_path)
    with torch.no_grad():
        next(bundle.learner.parameters()).add_(0.25)
    with pytest.raises(SuphxLearningError, match="immutable behavior actor"):
        runner.run_iteration(
            SuphxScheduledCollector(runner.contract_sha256, schedule),
            SuphxPolicyGradientUpdate(schedule),
        )
    with pytest.raises(Exception, match="poisoned"):
        runner.next_batch_identity()


def test_update_refuses_sample_schedule_drift(tmp_path):
    bundle, _, runner, schedule = _case(tmp_path)

    class _ChangedCollector:
        def __call__(self, identity):
            batch = SuphxMicroCollector(
                identity.contract_sha256, 0.5)(identity)
            return batch

    with pytest.raises(SuphxLearningError, match="frozen schedule"):
        runner.run_iteration(
            _ChangedCollector(), SuphxPolicyGradientUpdate(schedule))


def test_schedule_exhaustion_refuses_third_batch(tmp_path):
    _, _, runner, schedule = _case(tmp_path)
    _run_and_adopt(runner, schedule)
    _run_and_adopt(runner, schedule)
    with pytest.raises(SuphxLearningError, match="outside"):
        SuphxScheduledCollector(runner.contract_sha256, schedule)(
            runner.next_batch_identity())


def test_resume_refuses_schedule_drift(tmp_path):
    bundle, _, runner, schedule = _case(tmp_path)
    receipt = _run_and_adopt(runner, schedule)
    checkpoint = runner.save_checkpoint(tmp_path / "resume.pt")
    changed = SuphxSchedule(
        segment_id="changed", keep_probabilities=(1.0, 0.0),
        learning_rate=LEARNING_RATE)
    restored_bundle = new_bundle(
        model_seed=999, learner_rng_seed=999,
        learning_rate=changed.learning_rate)
    with pytest.raises(RuntimeError, match="contract"):
        resume_runner(
            checkpoint,
            bundle=restored_bundle,
            actor_ref=receipt.candidate_ref,
            candidate_ref=receipt.candidate_ref,
            snapshot_dir=tmp_path / "case-candidates",
            root_seed=ROOT_SEED,
            schedule=changed,
        )
