"""Focused contract tests for the learned-search inference adapter."""

from __future__ import annotations

import copy
import hashlib
import random

import pytest

torch = pytest.importorskip("torch")

from shengji.engine.round import Round
from shengji.rl.encode import ACT_DIM, OBS_DIM, encode_action, encode_obs
from shengji.train.data import encoder_identity
from shengji.train.model import MODEL_SCHEMA, ValuePriorNet
from shengji.train.search_inference import (
    CHECKPOINT_SCHEMA,
    LEGACY_CHECKPOINT_SCHEMA,
    SearchHeads,
)


def _round(seed: int = 4) -> Round:
    rnd = Round("7", 0, random.Random(seed))
    for _ in range(100):
        rnd.deal_next()
    rnd.finalize_declare()
    rnd.bury(0, list(rnd.hands[0][:8]))
    return rnd


def _arch() -> dict:
    return {
        "obs_dim": OBS_DIM,
        "act_dim": ACT_DIM,
        "trunk": [16, 8],
        "value_hidden": 4,
        "prior_hidden": 5,
        "dropout": 0.0,
        "aux_points": False,
        "aux_search_mean": False,
    }


def _payload(model: ValuePriorNet, *, schema: str = CHECKPOINT_SCHEMA) -> dict:
    return {
        "schema": schema,
        "model_schema": MODEL_SCHEMA,
        "arch": model.arch,
        "model_state": {k: v.detach().cpu() for k, v in model.state_dict().items()},
        "encoder": encoder_identity(),
        "epoch": 7,
        "population": {"schema": "population-test", "counts": {"train": 1}},
    }


@pytest.fixture()
def model() -> ValuePriorNet:
    torch.manual_seed(11)
    return ValuePriorNet(_arch()).eval()


def test_priors_are_global_and_match_direct_forward(model):
    rnd = _round()
    actions = [[rnd.hands[0][i]] for i in range(5)]
    adapter = SearchHeads(model, batch_size=2)
    got = adapter.priors(rnd, 0, actions)
    obs = torch.tensor([encode_obs(rnd, 0)], dtype=torch.float32)
    cand = torch.tensor([[encode_action(a, rnd) for a in actions]], dtype=torch.float32)
    with torch.inference_mode():
        expected = torch.softmax(model(obs, cand, torch.ones((1, 5), dtype=torch.bool)).logits[0], 0)
    assert got == pytest.approx(expected.tolist(), abs=1e-7)
    assert sum(got) == pytest.approx(1.0)
    assert adapter.counters["model_calls"] == 1 + 3
    assert adapter.counters["prior_action_rows"] == 5


def test_prior_encoding_and_tensors_are_bounded_to_chunk(monkeypatch, model):
    import shengji.train.search_inference as search_inference

    rnd = _round()
    actions = [[rnd.hands[0][i]] for i in range(5)]
    encoded = 0
    chunks = []
    original_encode = search_inference.encode_action

    def wrapped_encode(action, round_):
        nonlocal encoded
        encoded += 1
        return original_encode(action, round_)

    class RecordingPrior(torch.nn.Module):
        def __init__(self, wrapped):
            super().__init__()
            self.wrapped = wrapped

        def forward(self, joined):
            nonlocal encoded
            chunks.append(joined.shape[1])
            assert encoded <= 2
            encoded = 0
            return self.wrapped(joined)

    monkeypatch.setattr(search_inference, "encode_action", wrapped_encode)
    model.prior_head = RecordingPrior(model.prior_head)
    SearchHeads(model, batch_size=2).priors(rnd, 0, actions)
    assert chunks == [2, 2, 1]


def test_values_are_direct_signed_outputs_and_hidden_twin_is_ignored(model):
    rnd = _round()
    twin = copy.deepcopy(rnd)
    # Exchange ownership between two hidden seats, and exchange a hidden
    # burial card with a hidden hand card.  The actor is seat 1 (non-banker),
    # so neither change is public information.
    twin.hands[2][0], twin.hands[3][0] = twin.hands[3][0], twin.hands[2][0]
    twin.buried[0], twin.hands[2][1] = twin.hands[2][1], twin.buried[0]
    assert sorted(sum(twin.hands, []) + twin.buried) == sorted(sum(rnd.hands, []) + rnd.buried)
    adapter = SearchHeads(model, batch_size=2)
    got = adapter.values([(rnd, 1), (twin, 1), (rnd, 0)])
    with torch.inference_mode():
        obs = torch.tensor([encode_obs(rnd, 1), encode_obs(twin, 1), encode_obs(rnd, 0)])
        expected = model.value_head(model.trunk(obs))[:, 0]
    assert got == pytest.approx(expected.tolist(), abs=1e-7)
    assert got[0] == pytest.approx(got[1], abs=1e-7)
    action = [[rnd.hands[1][0]], [rnd.hands[1][1]]]
    assert adapter.priors(rnd, 1, action) == pytest.approx(
        adapter.priors(twin, 1, action), abs=1e-7)
    visible_twin = copy.deepcopy(rnd)
    visible_twin.hands[1][0], visible_twin.hands[2][0] = (
        visible_twin.hands[2][0], visible_twin.hands[1][0])
    assert encode_obs(visible_twin, 1) != encode_obs(rnd, 1)
    assert adapter.counters["value_rows"] == 3


def test_values_accept_continuation_rounds_with_turn_as_actor(model):
    rnd = _round()
    rnd.turn = 2
    adapter = SearchHeads(model)
    assert len(adapter.values([rnd])) == 1


def test_inputs_and_validation_are_strict(model):
    rnd = _round()
    actions = [[rnd.hands[0][0]], [rnd.hands[0][1]]]
    before = copy.deepcopy(actions)
    adapter = SearchHeads(model, batch_size=1)
    adapter.priors(rnd, 0, actions)
    assert actions == before
    with pytest.raises(ValueError):
        adapter.priors(rnd, 0, [])
    with pytest.raises(ValueError):
        adapter.values([])
    with pytest.raises(ValueError):
        adapter.values([(rnd, 4)])
    with pytest.raises(ValueError):
        SearchHeads(model, batch_size=0)


def test_nonfinite_and_wrong_head_shapes_are_refused(model):
    rnd = _round()
    action = [[rnd.hands[0][0]]]

    class BadPrior(torch.nn.Module):
        def forward(self, joined):
            return torch.full((*joined.shape[:-1], 1), float("nan"))

    model.prior_head = BadPrior()
    with pytest.raises(ValueError, match="non-finite"):
        SearchHeads(model).priors(rnd, 0, action)

    class BadTrunk(torch.nn.Module):
        def forward(self, obs):
            return torch.zeros((obs.shape[0], 3))

    model.trunk = BadTrunk()
    with pytest.raises(ValueError, match="trunk"):
        SearchHeads(model).values([(rnd, 0)])


def test_v3_checkpoint_metadata_and_fail_closed_legacy(tmp_path, model):
    path = tmp_path / "v3.pt"
    torch.save(_payload(model), path)
    adapter = SearchHeads.from_checkpoint(path, batch_size=2)
    assert adapter.metadata["checkpoint_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert adapter.metadata["epoch"] == 7
    assert adapter.metadata["population_available"] is True
    legacy = tmp_path / "v2.pt"
    torch.save(_payload(model, schema=LEGACY_CHECKPOINT_SCHEMA), legacy)
    with pytest.raises(ValueError, match="allow_legacy"):
        SearchHeads.from_checkpoint(legacy)
    old = SearchHeads.from_checkpoint(legacy, allow_legacy=True)
    assert old.metadata["legacy"] is True
    assert old.metadata["population_available"] is False
    assert old.metadata["held_out_claim"] is False
    assert adapter.metadata["held_out_claim"] is False


@pytest.mark.parametrize("field", ["model_schema", "encoder", "arch"])
def test_checkpoint_identity_and_architecture_refused(tmp_path, model, field):
    payload = _payload(model)
    if field == "model_schema":
        payload[field] = "forged"
    elif field == "encoder":
        payload[field] = {**payload[field], "implementation_sha256": "forged"}
    else:
        payload[field] = {**payload[field], "obs_dim": OBS_DIM + 1}
    path = tmp_path / f"bad-{field}.pt"
    torch.save(payload, path)
    with pytest.raises(ValueError):
        SearchHeads.from_checkpoint(path)
