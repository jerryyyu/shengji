"""Falsification tests for immutable Suphx actor trajectories."""
from __future__ import annotations

import copy
import math
import random

import pytest


np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from shengji.engine.game import Game  # noqa: E402
from shengji.rl.exact_resume import state_digest  # noqa: E402
from shengji.rl.suphx_actor import (  # noqa: E402
    ACTOR_SOURCE_SHA256S,
    ACTOR_SPEC,
    ACTOR_SPEC_SHA256,
    SuphxActorError,
    SuphxMicroCollector,
    SuphxOrdinaryActor,
    _sample_index,
    actor_batch_bytes,
    load_actor,
    publish_initial_actor,
    validate_sample,
)
from shengji.rl.suphx_micro import EXPERIMENT  # noqa: E402
from shengji.rl.suphx_policy import new_from_scratch_model  # noqa: E402
from shengji.rl.synchronous_selfplay import (  # noqa: E402
    ActorBatchIdentity,
    _runner_contract_sha256,
)


ROOT_SEED = 20260807
ALGORITHM_SHA = "a" * 64


def _identity(tmp_path, *, sequence=0, seed=31337, model_seed=17):
    model = new_from_scratch_model(model_seed)
    actor_ref = publish_initial_actor(model, tmp_path / f"actor-{model_seed}")
    contract = _runner_contract_sha256(
        experiment=EXPERIMENT,
        root_seed=ROOT_SEED,
        algorithm_sha256=ALGORITHM_SHA,
    )
    return ActorBatchIdentity(
        experiment=EXPERIMENT,
        purpose="actor",
        sequence=sequence,
        seed=seed,
        actor_ref=actor_ref,
        contract_sha256=contract,
    )


@pytest.fixture(autouse=True)
def _deterministic_torch_runtime():
    enabled = torch.are_deterministic_algorithms_enabled()
    warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    torch.use_deterministic_algorithms(True, warn_only=False)
    try:
        yield
    finally:
        torch.use_deterministic_algorithms(enabled, warn_only=warn_only)


def test_actor_contract_binds_sources_ballot_sampling_and_direct_reward():
    assert ACTOR_SPEC_SHA256 == state_digest(ACTOR_SPEC)
    assert ACTOR_SPEC["source_sha256s"] == ACTOR_SOURCE_SHA256S
    assert ACTOR_SPEC["ballot"]["ordered_complete_ballot_stored"] is True
    assert ACTOR_SPEC["sampling"]["one_uniform_draw_per_decision"] is True
    assert ACTOR_SPEC["sampling"]["mask_rng_separate_from_action_rng"] is True
    assert ACTOR_SPEC["reward"]["oracle_scalar"] is False
    assert ACTOR_SPEC["controls"]["ordinary_play_fallback"] is False


def test_actor_requires_separate_local_rngs_and_refuses_other_surfaces():
    model = new_from_scratch_model(1)
    shared = random.Random(2)
    with pytest.raises(SuphxActorError, match="separate locals"):
        SuphxOrdinaryActor(
            model, keep_probability=0.5,
            mask_rng=shared, action_rng=shared)
    actor = SuphxOrdinaryActor(
        model, keep_probability=0.5,
        mask_rng=random.Random(3), action_rng=random.Random(4))
    with pytest.raises(SuphxActorError, match="declaration"):
        actor.decide_declare(None, 0)
    with pytest.raises(SuphxActorError, match="burial"):
        actor.decide_bury(None, 0)
    wrong = Game(random.Random(5)).start_round()
    with pytest.raises(SuphxActorError, match="ordinary-play"):
        actor.decide_play(wrong, 0)


def test_categorical_draw_reopens_exact_boundary():
    probabilities = torch.tensor([0.2, 0.3, 0.5], dtype=torch.float32)
    first_edge = float(probabilities[0].item())
    second_edge = first_edge + float(probabilities[1].item())
    assert _sample_index(probabilities, 0.0) == 0
    assert _sample_index(
        probabilities, math.nextafter(first_edge, 0.0)) == 0
    assert _sample_index(probabilities, first_edge) == 1
    assert _sample_index(
        probabilities, math.nextafter(second_edge, 0.0)) == 1
    assert _sample_index(probabilities, second_edge) == 2
    assert _sample_index(probabilities, math.nextafter(1.0, 0.0)) == 2
    with pytest.raises(SuphxActorError, match=r"\[0, 1\)"):
        _sample_index(probabilities, 1.0)


@pytest.mark.parametrize("keep_probability", [0.0, 0.375, 1.0])
def test_real_actor_batch_is_exactly_replayable_and_complete(
        tmp_path, keep_probability):
    identity = _identity(tmp_path, model_seed=int(keep_probability * 8) + 11)
    collector = SuphxMicroCollector(
        identity.contract_sha256, keep_probability)
    python_state = random.getstate()
    numpy_state = np.random.get_state()
    torch_state = torch.get_rng_state().clone()
    first = collector(identity)
    second = collector(identity)
    assert actor_batch_bytes(first) == actor_batch_bytes(second)
    assert random.getstate() == python_state
    assert state_digest(np.random.get_state()) == state_digest(numpy_state)
    assert torch.equal(torch.get_rng_state(), torch_state)
    assert first.samples
    assert {sample["role"] for sample in first.samples} == {0, 1}
    assert {sample["decision_surface"] for sample in first.samples} == {0, 1}
    for sample in first.samples:
        validate_sample(sample, identity=identity)
        assert len(sample["candidate_cards"]) == len(sample["candidates"])
        assert sample["action_cards"] == \
            sample["candidate_cards"][sample["chosen_index"]]
        assert sample["target"] == (-1 if sample["role"] else 1) * \
            sample["attacker_return"]
        if keep_probability == 0.0:
            assert np.count_nonzero(sample["mask"]) == 0
        elif keep_probability == 1.0:
            assert np.count_nonzero(sample["mask"]) == len(sample["mask"])


def test_actor_checkpoint_is_digest_verified(tmp_path):
    identity = _identity(tmp_path)
    loaded = load_actor(identity.actor_ref.path)
    assert state_digest(loaded.state_dict()) == state_digest(
        new_from_scratch_model(17).state_dict())
    with open(identity.actor_ref.path, "ab") as handle:
        handle.write(b"drift")
    with pytest.raises(RuntimeError, match="checkpoint digest drift"):
        from shengji.rl.selfplay_contract import load_verified
        load_verified(identity.actor_ref, load_actor)


@pytest.mark.parametrize("mutation", [
    {"surface": "bury"},
    {"role": True},
    {"chosen_index": -1},
    {"behavior_log_probability": 0.5},
    {"target": 99.0},
    {"actor_sha256": "0" * 64},
])
def test_sample_validation_refuses_contract_action_probability_and_target_drift(
        tmp_path, mutation):
    identity = _identity(tmp_path, model_seed=29)
    batch = SuphxMicroCollector(identity.contract_sha256, 0.5)(identity)
    sample = copy.deepcopy(batch.samples[0])
    sample.update(mutation)
    with pytest.raises(SuphxActorError):
        validate_sample(sample, identity=identity)


def test_collector_refuses_contract_and_round_count_drift(tmp_path):
    identity = _identity(tmp_path)
    with pytest.raises(SuphxActorError, match="round count"):
        SuphxMicroCollector(identity.contract_sha256, 0.5, rounds_per_batch=2)
    collector = SuphxMicroCollector("b" * 64, 0.5)
    with pytest.raises(SuphxActorError, match="identity/contract"):
        collector(identity)
