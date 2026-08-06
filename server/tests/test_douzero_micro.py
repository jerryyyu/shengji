"""Falsification tests for the bounded DouZero-style microbaseline."""
from __future__ import annotations

import copy
import random
from types import SimpleNamespace

import pytest


np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from shengji.engine.round import Trick, TrickPlay  # noqa: E402
from shengji.rl.douzero_micro import (  # noqa: E402
    ACT_DIM,
    ALGORITHM_SHA256,
    ALGORITHM_SOURCE_SHA256S,
    ALGORITHM_SPEC,
    BALLOT_SCHEMA,
    DouZeroMicroCollector,
    DouZeroMicroError,
    DouZeroMicroUpdate,
    EPSILON,
    EXPERIMENT,
    HISTORY_EVENT_DIM,
    HISTORY_SCHEMA,
    NETWORK_SCHEMA,
    OPPONENT_SCHEMA,
    REPLAY_CAPACITY,
    REWARD_SCHEMA,
    ROLE_ATTACKER,
    ROLE_DEFENDER,
    SAMPLE_SCHEMA,
    UPDATE_BATCH_SIZE,
    UnsupportedDecisionSurface,
    OrdinaryPlayActor,
    acting_team_return,
    actor_batch_bytes,
    bundle_digest,
    contract_digest,
    encode_public_history,
    load_actor,
    new_bundle,
    new_from_scratch_model,
    new_runner,
    publish_initial_actor,
    resume_runner,
    terminal_attacker_return,
    validate_sample,
)
from shengji.rl.encode import (CARD_INDEX, ENCODER_IMPLEMENTATION_SHA256,
                               ENCODER_SOURCE_SHA256S, OBS_DIM)  # noqa: E402
from shengji.rl.exact_resume import state_digest  # noqa: E402
from shengji.rl.selfplay_contract import CheckpointRef, load_verified  # noqa: E402


ROOT_SEED = 20260806


@pytest.fixture(autouse=True)
def _deterministic_torch_runtime():
    enabled = torch.are_deterministic_algorithms_enabled()
    warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    torch.use_deterministic_algorithms(True, warn_only=False)
    try:
        yield
    finally:
        torch.use_deterministic_algorithms(enabled, warn_only=warn_only)


def _runner_case(tmp_path, name="case", *, model_seed=11, rng_seed=13,
                 actor_ref=None):
    bundle = new_bundle(model_seed=model_seed, learner_rng_seed=rng_seed)
    if actor_ref is None:
        actor_ref = publish_initial_actor(
            bundle.learner, tmp_path / f"{name}-actor")
    runner = new_runner(
        bundle=bundle,
        actor_ref=actor_ref,
        snapshot_dir=tmp_path / f"{name}-candidates",
        root_seed=ROOT_SEED,
    )
    return bundle, actor_ref, runner


def test_algorithm_contract_binds_every_required_choice():
    assert ALGORITHM_SHA256 == contract_digest(ALGORITHM_SPEC)
    assert ALGORITHM_SPEC["decision_surface"] == "ordinary_play_only"
    assert ALGORITHM_SPEC["implementation_source_sha256s"] == \
        ALGORITHM_SOURCE_SHA256S
    assert set(ALGORITHM_SOURCE_SHA256S) == {
        "douzero_micro", "actions", "encode", "memory", "smart_controls",
        "round_driver", "cards", "combos", "game", "round",
    }
    observation = ALGORITHM_SPEC["encoder"]["observation"]
    assert observation["schema"] == \
        "rl-observation-v1-public-no-private-kitty"
    assert observation["layout_version"] == 1
    assert observation["dimension"] == OBS_DIM
    assert observation["implementation_sha256"] == \
        ENCODER_IMPLEMENTATION_SHA256
    assert observation["source_sha256s"] == ENCODER_SOURCE_SHA256S
    assert ALGORITHM_SPEC["encoder"]["history"] == HISTORY_SCHEMA
    assert ALGORITHM_SPEC["action_ballot"]["schema"] == BALLOT_SCHEMA
    assert ALGORITHM_SPEC["reward"]["schema"] == REWARD_SCHEMA
    assert ALGORITHM_SPEC["reward"]["oracle_baseline"] is False
    assert ALGORITHM_SPEC["reward"]["warm_start"] is False
    assert ALGORITHM_SPEC["network"]["schema"] == NETWORK_SCHEMA
    assert ALGORITHM_SPEC["network"]["roles"] == ["attacker", "defender"]
    assert ALGORITHM_SPEC["network"]["separate_role_parameters"] is True
    assert ALGORITHM_SPEC["update"]["batch_size"] == UPDATE_BATCH_SIZE
    assert ALGORITHM_SPEC["update"]["replay_capacity"] == REPLAY_CAPACITY
    assert ALGORITHM_SPEC["exploration"]["epsilon"] == EPSILON
    assert ALGORITHM_SPEC["opponent_and_controls"]["schema"] == OPPONENT_SCHEMA
    assert ALGORITHM_SPEC["opponent_and_controls"]["ordinary_fallback"] is False

    for path, value in (
        (("encoder", "history"), "different-history"),
        (("action_ballot", "schema"), "different-ballot"),
        (("reward", "schema"), "different-reward"),
        (("network", "roles"), ["one-network"]),
        (("update", "loss"), "different-loss"),
        (("update", "replay_capacity"), REPLAY_CAPACITY + 1),
        (("exploration", "epsilon"), 0.2),
        (("opponent_and_controls", "ordinary_play"), "different-opponent"),
    ):
        changed = copy.deepcopy(ALGORITHM_SPEC)
        changed[path[0]][path[1]] = value
        assert contract_digest(changed) != ALGORITHM_SHA256

    changed = copy.deepcopy(ALGORITHM_SPEC)
    changed["encoder"]["observation"]["implementation_sha256"] = "0" * 64
    assert contract_digest(changed) != ALGORITHM_SHA256
    changed = copy.deepcopy(ALGORITHM_SPEC)
    changed["implementation_source_sha256s"]["actions"] = "0" * 64
    assert contract_digest(changed) != ALGORITHM_SHA256


def test_direct_terminal_return_is_role_antisymmetric_without_residual():
    assert terminal_attacker_return(0) == -3.5
    assert terminal_attacker_return(1) == -2.5
    assert terminal_attacker_return(40) == -1.5
    assert terminal_attacker_return(80) == 0.5
    assert terminal_attacker_return(120) == 1.5
    assert terminal_attacker_return(200) == 3.5
    for attacker_return in (-3.5, -1.5, 0.5, 2.5, 3.5):
        attacker = acting_team_return(attacker_return, ROLE_ATTACKER)
        defender = acting_team_return(attacker_return, ROLE_DEFENDER)
        assert attacker == attacker_return
        assert defender == -attacker
    with pytest.raises(DouZeroMicroError, match="unsupported role"):
        acting_team_return(1.0, 7)


def test_history_encoder_preserves_public_order_seat_and_trick_position():
    first = Trick(
        leader=2,
        plays=[
            TrickPlay(2, ["SA"]),
            TrickPlay(3, ["S2"]),
            TrickPlay(0, ["S3"]),
            TrickPlay(1, ["S4"]),
        ],
        winner=2,
    )
    current = Trick(
        leader=2,
        plays=[TrickPlay(2, ["H5", "H5"]), TrickPlay(3, ["H6", "H6"])],
    )
    rnd = SimpleNamespace(history=[first], trick=current)
    encoded = encode_public_history(rnd, seat=3)
    assert encoded.shape == (6, HISTORY_EVENT_DIM)
    assert encoded.dtype == np.float32
    assert encoded[0, CARD_INDEX["SA"]] == 0.5
    assert encoded[1, CARD_INDEX["S2"]] == 0.5
    seat_offset = len(CARD_INDEX)
    assert encoded[0, seat_offset + 3] == 1.0  # seat 2 relative to actor 3
    assert encoded[1, seat_offset + 0] == 1.0
    trick_position_offset = seat_offset + 4
    assert encoded[0, trick_position_offset + 0] == 1.0
    assert encoded[1, trick_position_offset + 1] == 1.0
    assert encoded[4, CARD_INDEX["H5"]] == 1.0
    reversed_round = SimpleNamespace(history=[], trick=Trick(
        leader=3, plays=list(reversed(current.plays))))
    reversed_rows = encode_public_history(reversed_round, seat=3)
    assert not np.array_equal(encoded[4:], reversed_rows)


def test_from_scratch_model_is_named_rng_only_and_role_separated():
    python_state = random.getstate()
    numpy_state = np.random.get_state()
    torch_state = torch.get_rng_state().clone()
    first = new_from_scratch_model(71)
    assert random.getstate() == python_state
    assert state_digest(np.random.get_state()) == state_digest(numpy_state)
    assert torch.equal(torch.get_rng_state(), torch_state)

    torch.manual_seed(999)
    second = new_from_scratch_model(71)
    torch.set_rng_state(torch_state)
    assert state_digest(first.state_dict()) == state_digest(second.state_dict())
    attacker_parameters = {id(value) for value in first.attacker.parameters()}
    defender_parameters = {id(value) for value in first.defender.parameters()}
    assert attacker_parameters.isdisjoint(defender_parameters)

    obs = np.zeros(OBS_DIM, dtype=np.float32)
    actions = np.zeros((2, ACT_DIM), dtype=np.float32)
    actions[1, 0] = 1.0
    history = np.zeros((2, HISTORY_EVENT_DIM), dtype=np.float32)
    history[0, 0] = 0.5
    history[1, 1] = 0.5
    attacker_scores = first.score_candidates(
        role=ROLE_ATTACKER, obs=obs, history=history, actions=actions)
    defender_scores = first.score_candidates(
        role=ROLE_DEFENDER, obs=obs, history=history, actions=actions)
    reversed_scores = first.score_candidates(
        role=ROLE_ATTACKER, obs=obs, history=history[::-1].copy(),
        actions=actions)
    assert attacker_scores[0] != attacker_scores[1]
    assert not torch.equal(attacker_scores, defender_scores)
    assert not torch.equal(attacker_scores, reversed_scores)


def test_q_actor_refuses_every_unsupported_surface():
    actor = OrdinaryPlayActor(new_from_scratch_model(3), random.Random(4))
    with pytest.raises(UnsupportedDecisionSurface, match="declaration"):
        actor.decide_declare(None, 0)
    with pytest.raises(UnsupportedDecisionSurface, match="burial"):
        actor.decide_bury(None, 0)
    wrong_phase = SimpleNamespace(
        phase="bury", turn=0, trick=None, ordering=None)
    with pytest.raises(UnsupportedDecisionSurface, match="ordinary-play"):
        actor.decide_play(wrong_phase, 0)


def test_actor_ref_is_loaded_with_digest_verification(tmp_path):
    model = new_from_scratch_model(5)
    actor_ref = publish_initial_actor(model, tmp_path / "actor")
    loaded = load_verified(actor_ref, load_actor)
    assert state_digest(loaded.state_dict()) == state_digest(model.state_dict())
    actor_path = actor_ref.path
    with open(actor_path, "ab") as handle:
        handle.write(b"drift")
    with pytest.raises(RuntimeError, match="checkpoint digest drift"):
        load_verified(actor_ref, load_actor)


def test_real_actor_batch_is_replayable_direct_and_ordinary_only(tmp_path):
    _, _, runner = _runner_case(tmp_path)
    identity = runner.next_batch_identity()
    collector = DouZeroMicroCollector(runner.contract_sha256)
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
    assert {sample["role"] for sample in first.samples} == {
        ROLE_ATTACKER, ROLE_DEFENDER}
    assert any(sample["history_length"] > 0 for sample in first.samples)
    assert any(sample["history_length"] == 0 for sample in first.samples)
    attacker_returns = {sample["attacker_return"] for sample in first.samples}
    assert len(attacker_returns) == 1
    for sample in first.samples:
        validate_sample(sample, identity=identity)
        assert sample["schema"] == SAMPLE_SCHEMA
        assert sample["surface"] == "ordinary_play"
        assert sample["target"] == acting_team_return(
            sample["attacker_return"], sample["role"])
        assert "oracle" not in sample and "baseline" not in sample


@pytest.mark.parametrize("mutation", [
    {"surface": "bury"},
    {"role": 9},
    {"target": 123.0},
    {"actor_sha256": "0" * 64},
])
def test_sample_contract_refuses_surface_role_target_and_actor_drift(
        tmp_path, mutation):
    _, _, runner = _runner_case(tmp_path)
    identity = runner.next_batch_identity()
    batch = DouZeroMicroCollector(runner.contract_sha256)(identity)
    sample = copy.deepcopy(batch.samples[0])
    sample.update(mutation)
    with pytest.raises((DouZeroMicroError, UnsupportedDecisionSurface)):
        validate_sample(sample, identity=identity)


def test_one_serial_batch_inserts_replay_and_updates_one_candidate(tmp_path):
    bundle, _, runner = _runner_case(tmp_path)
    before = state_digest(bundle.learner.state_dict())
    collector = DouZeroMicroCollector(runner.contract_sha256)
    receipt = runner.run_iteration(collector, DouZeroMicroUpdate())
    assert receipt.progress.next_iteration == 1
    assert receipt.progress.next_batch == 1
    assert receipt.samples_added == len(bundle.replay)
    assert 0 < len(bundle.replay) <= REPLAY_CAPACITY
    assert state_digest(bundle.learner.state_dict()) != before
    assert bundle.optimizer.state_dict()["state"]
    receipt.candidate_ref.verify()


class _CaptureCollector:
    def __init__(self, inner):
        self.inner = inner
        self.wire_batches = []
        self.action_choices = []

    def __call__(self, identity):
        batch = self.inner(identity)
        self.wire_batches.append(actor_batch_bytes(batch))
        self.action_choices.append(tuple(
            sample["action_cards"] for sample in batch.samples))
        return batch


def test_interrupted_resume_matches_batch_bytes_candidate_and_all_state(tmp_path):
    actor_source = new_bundle(model_seed=101, learner_rng_seed=17)
    actor_ref = publish_initial_actor(
        actor_source.learner, tmp_path / "shared-actor")

    uninterrupted_bundle, _, uninterrupted = _runner_case(
        tmp_path, "uninterrupted", model_seed=101, rng_seed=23,
        actor_ref=actor_ref)
    uninterrupted_collector = _CaptureCollector(
        DouZeroMicroCollector(uninterrupted.contract_sha256))
    uninterrupted_receipts = [
        uninterrupted.run_iteration(
            uninterrupted_collector, DouZeroMicroUpdate())
        for _ in range(2)
    ]

    interrupted_bundle, _, interrupted = _runner_case(
        tmp_path, "interrupted", model_seed=101, rng_seed=23,
        actor_ref=actor_ref)
    interrupted_collector = _CaptureCollector(
        DouZeroMicroCollector(interrupted.contract_sha256))
    first_interrupted = interrupted.run_iteration(
        interrupted_collector, DouZeroMicroUpdate())
    checkpoint_ref = interrupted.save_checkpoint(
        tmp_path / "after-one.pt")

    restored_bundle = new_bundle(model_seed=999, learner_rng_seed=999)
    restored = resume_runner(
        checkpoint_ref,
        bundle=restored_bundle,
        actor_ref=actor_ref,
        candidate_ref=first_interrupted.candidate_ref,
        snapshot_dir=tmp_path / "interrupted-candidates",
        root_seed=ROOT_SEED,
    )
    resumed_collector = _CaptureCollector(
        DouZeroMicroCollector(restored.contract_sha256))
    resumed_receipt = restored.run_iteration(
        resumed_collector, DouZeroMicroUpdate())

    assert uninterrupted_collector.wire_batches[0] == \
        interrupted_collector.wire_batches[0]
    assert uninterrupted_collector.wire_batches[1] == \
        resumed_collector.wire_batches[0]
    assert uninterrupted_collector.action_choices[0] == \
        interrupted_collector.action_choices[0]
    assert uninterrupted_collector.action_choices[1] == \
        resumed_collector.action_choices[0]
    assert resumed_receipt.batch == uninterrupted_receipts[1].batch
    assert resumed_receipt.candidate_ref.sha256 == \
        uninterrupted_receipts[1].candidate_ref.sha256
    assert bundle_digest(restored_bundle) == bundle_digest(uninterrupted_bundle)
    assert restored.progress == uninterrupted.progress


def test_collector_refuses_wrong_runner_contract_before_loading_actor(tmp_path):
    _, _, runner = _runner_case(tmp_path)
    identity = runner.next_batch_identity()
    collector = DouZeroMicroCollector("0" * 64)
    with pytest.raises(DouZeroMicroError, match="runner contract mismatch"):
        collector(identity)


def test_fixed_contract_rejects_silent_scale_changes():
    with pytest.raises(DouZeroMicroError, match="round count is fixed"):
        DouZeroMicroCollector(ALGORITHM_SHA256, rounds_per_batch=2)
    with pytest.raises(DouZeroMicroError, match="batch size is fixed"):
        DouZeroMicroUpdate(batch_size=UPDATE_BATCH_SIZE + 1)
    with pytest.raises(DouZeroMicroError, match="replay capacity is fixed"):
        new_bundle(
            model_seed=1, learner_rng_seed=2,
            replay_capacity=REPLAY_CAPACITY + 1)
    assert EXPERIMENT == "douzero-micro-ordinary-play-v1"
