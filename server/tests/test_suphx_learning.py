"""Falsification tests for synchronous Suphx policy-gradient mechanics."""
from __future__ import annotations

import random

import pytest


np = pytest.importorskip("numpy")
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
    LOWER_RATE_FACTOR,
    LOWER_RATE_TRANSITION_SCHEMA,
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
    lower_rate_public_schedule,
    new_bundle,
    new_runner,
    resume_runner,
    start_lower_rate_public_segment,
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
            deal_stream_root_seed=ROOT_SEED,
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
    assert "actor digest" in LEARNING_SPEC["causal_deals"]
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
    transition = LEARNING_SPEC["lower_rate_public_transition"]
    assert transition["schema"] == LOWER_RATE_TRANSITION_SCHEMA
    assert transition["learning_rate_factor"] == LOWER_RATE_FACTOR
    assert transition["optimizer"] == "fresh Adam with empty state"
    assert transition["automatic_training"] is False

    schedule = SuphxSchedule(
        segment_id="curriculum", keep_probabilities=(1.0, 0.5, 0.0),
        learning_rate=LEARNING_RATE, deal_stream_root_seed=ROOT_SEED)
    assert algorithm_sha256(schedule) == state_digest(algorithm_spec(schedule))
    for changed in (
        SuphxSchedule(
            "other", schedule.keep_probabilities, LEARNING_RATE, ROOT_SEED),
        SuphxSchedule(
            "curriculum", (1.0, 0.4, 0.0), LEARNING_RATE, ROOT_SEED),
        SuphxSchedule(
            "curriculum", schedule.keep_probabilities, 1e-4, ROOT_SEED),
        SuphxSchedule(
            "curriculum", schedule.keep_probabilities, LEARNING_RATE,
            ROOT_SEED + 1),
    ):
        assert algorithm_sha256(changed) != algorithm_sha256(schedule)


@pytest.mark.parametrize("kwargs", [
    {"segment_id": "", "keep_probabilities": (1.0,),
     "learning_rate": LEARNING_RATE, "deal_stream_root_seed": ROOT_SEED},
    {"segment_id": "bad segment", "keep_probabilities": (1.0,),
     "learning_rate": LEARNING_RATE, "deal_stream_root_seed": ROOT_SEED},
    {"segment_id": "x", "keep_probabilities": (),
     "learning_rate": LEARNING_RATE, "deal_stream_root_seed": ROOT_SEED},
    {"segment_id": "x", "keep_probabilities": (1.1,),
     "learning_rate": LEARNING_RATE, "deal_stream_root_seed": ROOT_SEED},
    {"segment_id": "x", "keep_probabilities": (0.0, 1.0),
     "learning_rate": LEARNING_RATE, "deal_stream_root_seed": ROOT_SEED},
    {"segment_id": "x", "keep_probabilities": (1.0,),
     "learning_rate": 0.0, "deal_stream_root_seed": ROOT_SEED},
    {"segment_id": "x", "keep_probabilities": (1.0,),
     "learning_rate": LEARNING_RATE, "deal_stream_root_seed": -1},
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


def _completed_parent(tmp_path, name="parent"):
    schedule = SuphxSchedule(
        segment_id=f"{name}-curriculum",
        keep_probabilities=(1.0, 0.0),
        learning_rate=LEARNING_RATE,
        deal_stream_root_seed=ROOT_SEED,
    )
    bundle, _, runner, _ = _case(
        tmp_path, name, model_seed=151, rng_seed=157, schedule=schedule)
    for _ in schedule.keep_probabilities:
        _run_and_adopt(runner, schedule)
    checkpoint = runner.save_checkpoint(tmp_path / f"{name}-complete.pt")
    return bundle, runner, schedule, checkpoint


def test_interrupted_resume_matches_across_privilege_boundary(tmp_path):
    schedule = SuphxSchedule(
        segment_id="one-to-zero",
        keep_probabilities=(1.0, 0.0),
        learning_rate=LEARNING_RATE,
        deal_stream_root_seed=ROOT_SEED,
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


def test_lower_rate_public_transition_reopens_parent_and_starts_zero_work(
        tmp_path):
    parent_bundle, parent, parent_schedule, checkpoint = \
        _completed_parent(tmp_path)
    python_state = random.getstate()
    numpy_state = state_digest(np.random.get_state())
    torch_state = torch.get_rng_state().clone()

    started = start_lower_rate_public_segment(
        checkpoint,
        parent_schedule=parent_schedule,
        parent_runner_root_seed=ROOT_SEED,
        child_segment_id="public-low-rate",
        child_iterations=2,
        child_deal_stream_root_seed=ROOT_SEED + 10_000,
        child_runner_root_seed=ROOT_SEED + 20_000,
        child_learner_rng_seed=163,
        child_snapshot_dir=tmp_path / "public-low-rate-candidates",
    )

    assert started.schedule.keep_probabilities == (0.0, 0.0)
    assert started.schedule.learning_rate == \
        parent_schedule.learning_rate * LOWER_RATE_FACTOR
    assert started.runner.progress.next_iteration == 0
    assert started.runner.progress.next_batch == 0
    assert started.runner.actor_ref == parent.actor_ref
    assert not started.bundle.optimizer.state_dict()["state"]
    assert len(started.bundle.replay) == 0
    assert state_digest(started.bundle.learner.state_dict()) == \
        state_digest(parent_bundle.learner.state_dict())
    assert started.transition["schema"] == LOWER_RATE_TRANSITION_SCHEMA
    assert started.transition["parent_checkpoint_ref"] == checkpoint.as_dict()
    assert started.transition["optimizer_reset"] is True
    assert started.transition["replay_reset"] is True
    assert started.transition["games_generated"] == 0
    assert started.transition["training_updates"] == 0
    assert started.transition["automatic_training"] is False
    assert started.transition_sha256 == state_digest(started.transition)
    assert random.getstate() == python_state
    assert state_digest(np.random.get_state()) == numpy_state
    assert torch.equal(torch.get_rng_state(), torch_state)

    captured = []

    def collect(identity):
        batch = SuphxScheduledCollector(
            started.runner.contract_sha256, started.schedule)(identity)
        captured.append(batch)
        return batch

    started.runner.run_iteration(
        collect, SuphxPolicyGradientUpdate(started.schedule))
    assert captured and all(
        sample["keep_probability"] == 0.0
        and sample["deal_stream_root_seed"] ==
        started.schedule.deal_stream_root_seed
        and not np.count_nonzero(sample["mask"])
        for sample in captured[0].samples
    )


def test_lower_rate_public_segment_resumes_exactly_after_transition(tmp_path):
    _, _, parent_schedule, checkpoint = _completed_parent(
        tmp_path, "resume-parent")
    started = start_lower_rate_public_segment(
        checkpoint,
        parent_schedule=parent_schedule,
        parent_runner_root_seed=ROOT_SEED,
        child_segment_id="public-resume",
        child_iterations=2,
        child_deal_stream_root_seed=ROOT_SEED + 30_000,
        child_runner_root_seed=ROOT_SEED + 40_000,
        child_learner_rng_seed=167,
        child_snapshot_dir=tmp_path / "public-resume-live",
    )
    live_collector = _CaptureCollector(SuphxScheduledCollector(
        started.runner.contract_sha256, started.schedule))
    first = _run_and_adopt(
        started.runner, started.schedule, live_collector)
    child_checkpoint = started.runner.save_checkpoint(
        tmp_path / "public-after-one.pt")
    expected = _run_and_adopt(
        started.runner, started.schedule, live_collector)

    restored_bundle = new_bundle(
        model_seed=999,
        learner_rng_seed=999,
        learning_rate=started.schedule.learning_rate,
    )
    restored = resume_runner(
        child_checkpoint,
        bundle=restored_bundle,
        actor_ref=first.candidate_ref,
        candidate_ref=first.candidate_ref,
        snapshot_dir=tmp_path / "public-resume-restored",
        root_seed=ROOT_SEED + 40_000,
        schedule=started.schedule,
    )
    resumed_collector = _CaptureCollector(SuphxScheduledCollector(
        restored.contract_sha256, started.schedule))
    resumed = _run_and_adopt(
        restored, started.schedule, resumed_collector)

    assert live_collector.batches[1] == resumed_collector.batches[0]
    assert resumed.batch == expected.batch
    assert resumed.candidate_ref.sha256 == expected.candidate_ref.sha256
    assert bundle_digest(restored_bundle) == bundle_digest(started.bundle)


def test_lower_rate_transition_refuses_unfinished_unadopted_or_reused_deals(
        tmp_path):
    schedule = SuphxSchedule(
        segment_id="refusal-parent",
        keep_probabilities=(1.0, 0.0),
        learning_rate=LEARNING_RATE,
        deal_stream_root_seed=ROOT_SEED,
    )
    _, _, runner, _ = _case(tmp_path, "refusal", schedule=schedule)
    first = _run_and_adopt(runner, schedule)
    unfinished = runner.save_checkpoint(tmp_path / "unfinished.pt")
    with pytest.raises(SuphxLearningError, match="not exactly exhausted"):
        start_lower_rate_public_segment(
            unfinished,
            parent_schedule=schedule,
            parent_runner_root_seed=ROOT_SEED,
            child_segment_id="refused-unfinished",
            child_iterations=1,
            child_deal_stream_root_seed=ROOT_SEED + 50_000,
            child_runner_root_seed=ROOT_SEED + 60_000,
            child_learner_rng_seed=173,
            child_snapshot_dir=tmp_path / "refused-unfinished",
        )

    runner.run_iteration(
        SuphxScheduledCollector(runner.contract_sha256, schedule),
        SuphxPolicyGradientUpdate(schedule),
    )
    unadopted = runner.save_checkpoint(tmp_path / "unadopted.pt")
    assert runner.actor_ref == first.candidate_ref
    assert runner.actor_ref != runner.candidate_ref
    with pytest.raises(SuphxLearningError, match="was not adopted"):
        start_lower_rate_public_segment(
            unadopted,
            parent_schedule=schedule,
            parent_runner_root_seed=ROOT_SEED,
            child_segment_id="refused-unadopted",
            child_iterations=1,
            child_deal_stream_root_seed=ROOT_SEED + 50_000,
            child_runner_root_seed=ROOT_SEED + 60_000,
            child_learner_rng_seed=173,
            child_snapshot_dir=tmp_path / "refused-unadopted",
        )

    with pytest.raises(SuphxLearningError, match="overlaps"):
        lower_rate_public_schedule(
            schedule,
            segment_id="refused-overlap",
            iterations=1,
            deal_stream_root_seed=schedule.deal_stream_root_seed,
        )
    public_parent = SuphxSchedule(
        segment_id="already-public",
        keep_probabilities=(0.0,),
        learning_rate=LEARNING_RATE,
        deal_stream_root_seed=ROOT_SEED + 1,
    )
    with pytest.raises(SuphxLearningError, match="full privilege to zero"):
        lower_rate_public_schedule(
            public_parent,
            segment_id="refused-public",
            iterations=1,
            deal_stream_root_seed=ROOT_SEED + 2,
        )


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
                identity.contract_sha256, 0.5,
                schedule.deal_stream_root_seed)(identity)
            return batch

    with pytest.raises(SuphxLearningError, match="frozen schedule"):
        runner.run_iteration(
            _ChangedCollector(), SuphxPolicyGradientUpdate(schedule))


def test_update_refuses_actor_independent_deal_stream_drift(tmp_path):
    _, _, runner, schedule = _case(tmp_path)

    class _ChangedDealCollector:
        def __call__(self, identity):
            return SuphxMicroCollector(
                identity.contract_sha256,
                schedule.keep_probability(identity.sequence),
                schedule.deal_stream_root_seed + 1,
            )(identity)

    with pytest.raises(SuphxLearningError, match="deal stream"):
        runner.run_iteration(
            _ChangedDealCollector(), SuphxPolicyGradientUpdate(schedule))


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
        learning_rate=LEARNING_RATE, deal_stream_root_seed=ROOT_SEED)
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
