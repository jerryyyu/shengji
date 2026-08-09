"""Falsification tests for the executable, non-launching O0-v2 runner."""
from __future__ import annotations

import copy
import math

import pytest


np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from shengji.rl.exact_resume import (  # noqa: E402
    ReplayRing,
    ResumeProgress,
    ResumeRNGStreams,
    state_digest,
)
from shengji.rl.suphx_actor import publish_initial_actor  # noqa: E402
from shengji.rl.suphx_learning import (  # noqa: E402
    SuphxPolicyGradientUpdate,
    SuphxSchedule,
)
from shengji.rl.suphx_o0_v2_mechanics import (  # noqa: E402
    CrossedCRNSpec,
    LogitMarginSpec,
)
from shengji.rl.suphx_o0_v2_runner import (  # noqa: E402
    ACTOR_SPEC,
    ACTOR_SPEC_SHA256_V2,
    CELL_CONTROL,
    CELL_MARGIN,
    EXPERIMENT,
    LEARNING_RATE,
    RUNNER_SPEC,
    RUNNER_SPEC_SHA256,
    O0V2Algorithm,
    SuphxO0V2Collector,
    SuphxO0V2PolicyGradientUpdate,
    SuphxO0V2RunnerError,
    _legacy_sample,
    new_o0_v2_bundle,
    new_o0_v2_runner,
    validate_o0_v2_sample,
)
from shengji.rl.suphx_policy import new_from_scratch_model  # noqa: E402
from shengji.rl.synchronous_selfplay import (  # noqa: E402
    ActorBatchIdentity,
    LearnerUpdateContext,
    SynchronousActorBatch,
)


def _crn_spec():
    return CrossedCRNSpec(
        root_seed=2_026_080_900,
        training_seed_indices=tuple(range(8)),
    )


@pytest.fixture(scope="module")
def paired_batches(tmp_path_factory):
    torch.use_deterministic_algorithms(True, warn_only=False)
    root = tmp_path_factory.mktemp("o0-v2-runner")
    model = new_from_scratch_model(2_026_081_000)
    actor_ref = publish_initial_actor(model, root / "actor")
    identity = ActorBatchIdentity(
        experiment=EXPERIMENT,
        purpose="actor",
        sequence=0,
        seed=123456,
        actor_ref=actor_ref,
        contract_sha256="a" * 64,
    )
    result = {"model": model, "identity": identity, "root": root}
    for arm in ("oracle", "public"):
        algorithm = O0V2Algorithm(
            _crn_spec(), 0, arm, CELL_CONTROL)
        collector = SuphxO0V2Collector("a" * 64, algorithm)
        result[arm] = {
            "algorithm": algorithm,
            "batch": collector(identity),
            "receipt": collector.key_receipt,
        }
    return result


def test_runner_specs_are_bounded_and_non_authorizing():
    assert ACTOR_SPEC_SHA256_V2 == state_digest(ACTOR_SPEC)
    assert RUNNER_SPEC_SHA256 == state_digest(RUNNER_SPEC)
    assert RUNNER_SPEC["cells"] == [
        {"name": CELL_CONTROL, "margin_controller": False},
        {"name": CELL_MARGIN, "margin_controller": True},
    ]
    assert RUNNER_SPEC["unchanged_recipe"]["iterations_per_endpoint"] == 64
    assert RUNNER_SPEC["unchanged_recipe"]["learning_rate"] == 1e-3
    assert RUNNER_SPEC["experiment_launch_authorized"] is False
    assert RUNNER_SPEC["o1_authorized"] is False
    assert RUNNER_SPEC["strength_claim"] is False
    assert RUNNER_SPEC["production_promotion"] is False


def test_algorithm_keeps_margin_factor_separate_and_refuses_recipe_drift():
    spec = _crn_spec()
    control = O0V2Algorithm(spec, 0, "oracle", CELL_CONTROL)
    margin_spec = LogitMarginSpec(target_margin=1.0, coefficient=0.01)
    treatment = O0V2Algorithm(
        spec, 0, "oracle", CELL_MARGIN, margin_spec)
    assert control.as_dict()["margin_spec"] is None
    assert treatment.as_dict()["margin_spec"] == margin_spec.as_dict()
    assert control.sha256 != treatment.sha256
    with pytest.raises(SuphxO0V2RunnerError, match="control"):
        O0V2Algorithm(spec, 0, "oracle", CELL_CONTROL, margin_spec)
    with pytest.raises(SuphxO0V2RunnerError, match="requires"):
        O0V2Algorithm(spec, 0, "oracle", CELL_MARGIN)
    with pytest.raises(SuphxO0V2RunnerError, match="learning rate"):
        O0V2Algorithm(
            spec, 0, "oracle", CELL_CONTROL,
            learning_rate=LEARNING_RATE * 2,
        )


def test_actual_collector_couples_first_public_context_and_endpoint_work(
        paired_batches):
    oracle = paired_batches["oracle"]
    public = paired_batches["public"]
    left = oracle["batch"].samples
    right = public["batch"].samples
    assert left and right
    assert left[0]["game_seed"] == right[0]["game_seed"]
    assert left[0]["public_decision_key"] == right[0]["public_decision_key"]
    assert left[0]["action_draw"] == right[0]["action_draw"]
    assert np.all(left[0]["mask"] == 1.0)
    assert np.all(right[0]["mask"] == 0.0)
    assert oracle["receipt"]["first_public_decision_key"] == \
        public["receipt"]["first_public_decision_key"]
    assert oracle["receipt"]["mechanics_receipt"]["deal_seed"] == \
        public["receipt"]["mechanics_receipt"]["deal_seed"]
    # The policies may fork later.  Every shared prefix decision must still use
    # the same draw; this checks the real actor path, not just the draw helper.
    for left_sample, right_sample in zip(left, right):
        if left_sample["public_decision_key"] != \
                right_sample["public_decision_key"]:
            break
        assert left_sample["action_draw"] == right_sample["action_draw"]
        assert left_sample["public_key_occurrence"] == \
            right_sample["public_key_occurrence"]


def test_sample_provenance_refuses_arm_key_and_algorithm_mutations(
        paired_batches):
    original = paired_batches["oracle"]["batch"].samples[0]
    identity = paired_batches["identity"]
    algorithm = paired_batches["oracle"]["algorithm"]
    validate_o0_v2_sample(original, identity=identity, algorithm=algorithm)
    for field, value in (
        ("arm", "public"),
        ("cell", CELL_MARGIN),
        ("public_decision_key", "0" * 64),
        ("algorithm_sha256", "1" * 64),
        ("crn_root_seed", original["crn_root_seed"] + 1),
    ):
        changed = copy.deepcopy(original)
        changed[field] = value
        with pytest.raises(SuphxO0V2RunnerError):
            validate_o0_v2_sample(
                changed, identity=identity, algorithm=algorithm)


def _update_context(model, optimizer, batch):
    return LearnerUpdateContext(
        learner=model,
        optimizer=optimizer,
        replay=ReplayRing(256),
        rng=ResumeRNGStreams.seeded(77),
        batch=batch,
        progress=ResumeProgress(next_iteration=0, next_batch=0),
    )


def test_control_cell_is_bit_exact_to_the_old_learning_objective(
        paired_batches):
    batch = paired_batches["public"]["batch"]
    algorithm = paired_batches["public"]["algorithm"]
    left = copy.deepcopy(paired_batches["model"])
    right = copy.deepcopy(paired_batches["model"])
    left_optimizer = torch.optim.Adam(left.parameters(), lr=LEARNING_RATE)
    right_optimizer = torch.optim.Adam(right.parameters(), lr=LEARNING_RATE)

    SuphxO0V2PolicyGradientUpdate(algorithm)(
        _update_context(left, left_optimizer, batch))
    legacy_batch = SynchronousActorBatch(
        identity=batch.identity,
        samples=tuple(_legacy_sample(sample) for sample in batch.samples),
    )
    legacy_schedule = SuphxSchedule(
        segment_id="control-equivalence",
        keep_probabilities=(0.0,),
        learning_rate=LEARNING_RATE,
        deal_stream_root_seed=algorithm.crn_spec.root_seed,
    )
    SuphxPolicyGradientUpdate(legacy_schedule)(
        _update_context(right, right_optimizer, legacy_batch))
    assert state_digest(left.state_dict()) == state_digest(right.state_dict())
    assert state_digest(left_optimizer.state_dict()) == \
        state_digest(right_optimizer.state_dict())


def test_margin_cell_is_the_only_learning_delta_and_stays_finite(
        paired_batches):
    batch = paired_batches["oracle"]["batch"]
    control_algorithm = paired_batches["oracle"]["algorithm"]
    margin_algorithm = O0V2Algorithm(
        _crn_spec(), 0, "oracle", CELL_MARGIN,
        LogitMarginSpec(target_margin=1.0, coefficient=0.01),
    )
    # Rebind only the algorithm provenance; the behavior tensors and draws are
    # otherwise identical, making the objective term the sole update delta.
    margin_samples = []
    for sample in batch.samples:
        changed = copy.deepcopy(sample)
        changed["cell"] = CELL_MARGIN
        changed["algorithm_sha256"] = margin_algorithm.sha256
        margin_samples.append(changed)
    margin_batch = SynchronousActorBatch(
        identity=batch.identity, samples=tuple(margin_samples))

    control_model = copy.deepcopy(paired_batches["model"])
    margin_model = copy.deepcopy(paired_batches["model"])
    control_optimizer = torch.optim.Adam(
        control_model.parameters(), lr=LEARNING_RATE)
    margin_optimizer = torch.optim.Adam(
        margin_model.parameters(), lr=LEARNING_RATE)
    control_update = SuphxO0V2PolicyGradientUpdate(control_algorithm)
    margin_update = SuphxO0V2PolicyGradientUpdate(margin_algorithm)
    control_update(_update_context(
        control_model, control_optimizer, batch))
    margin_update(_update_context(
        margin_model, margin_optimizer, margin_batch))
    assert state_digest(control_model.state_dict()) != \
        state_digest(margin_model.state_dict())
    assert margin_update.margin_summary
    assert all(
        cell["decisions"] > 0
        and math.isfinite(cell["mean_top_two_margin"])
        for cell in margin_update.margin_summary.values()
    )
    assert all(
        bool(torch.all(torch.isfinite(value)))
        for value in margin_model.state_dict().values()
    )


def test_one_real_synchronous_iteration_publishes_keyed_work_only(tmp_path):
    torch.use_deterministic_algorithms(True, warn_only=False)
    algorithm = O0V2Algorithm(
        _crn_spec(), 1, "public", CELL_CONTROL)
    bundle = new_o0_v2_bundle(
        model_seed=2_026_081_001,
        learner_rng_seed=2_026_082_001,
    )
    initial = publish_initial_actor(bundle.learner, tmp_path / "initial")
    runner = new_o0_v2_runner(
        bundle=bundle,
        actor_ref=initial,
        snapshot_dir=tmp_path / "candidates",
        root_seed=2_026_083_001,
        algorithm=algorithm,
    )
    collector = SuphxO0V2Collector(runner.contract_sha256, algorithm)
    update = SuphxO0V2PolicyGradientUpdate(algorithm)
    receipt = runner.run_iteration(collector, update)
    adopted = runner.adopt_current_candidate_as_actor()
    assert receipt.progress.next_iteration == 1
    assert receipt.samples_added == collector.key_receipt["decision_count"]
    assert adopted == receipt.candidate_ref
    assert collector.key_receipt["outcomes"] is None
    assert collector.key_receipt["strength_scores"] is None
    assert collector.key_receipt["strength_claim"] is False
    assert collector.key_receipt["production_promotion"] is False
