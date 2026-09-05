"""The complete-world net at the leaf (``--leaf-model cwv``): the rollout
leaf is the cwv checkpoint's auxiliary points head on the DETERMINIZED CLONE
(the sampled world is the input), in production's units, from the clone's
seat to act.  Every property carries a mutation witness that must go RED."""
from __future__ import annotations

import copy
import hashlib
import random

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import (REGISTRY, VLEAF_LEAF_TRICKS, make_bot, register_vleaf_arms,
                                 vleaf_policy_name)
from shengji.rl.encode import encode_obs
from shengji.rl.value_afterstate import OUTCOME_CLASSES, category_signed_level, tensors_from_round
from shengji.rl.value_model import MLP_INPUT_DIM, ValueModelConfig, ValueNetwork
from shengji.train import leaf_policy as L
from shengji.train import leaf_screen as S
from shengji.train.cwv_data import cwv_encoder_identity
from shengji.train.search_screen import _publish
from shengji.train.train_cwv import AuxPointsHead, save_cwv_checkpoint

from test_vleaf_leaf import (BASE, NO_TRUNCATION, _play_seat0, _tiny, advance, deal,
                             last_trick_state, mid_trick_state, prior_table, true_world)
from test_vleaf_screen import threads


# ------------------------------------------------------------------ fixtures

def mlp(width=8, feedforward=16, seed=31):
    torch.manual_seed(seed)
    config = ValueModelConfig(architecture="mlp", width=width, history_layers=1,
                              attention_heads=1, feedforward_width=feedforward, dropout=0.1,
                              max_history=100)
    model = ValueNetwork(config).eval()
    aux = AuxPointsHead(width).eval()
    return model, aux


def save_cwv(path, model, aux, *, encoder=None, epoch=2):
    save_cwv_checkpoint(path, model, metadata={
        "encoder": encoder or cwv_encoder_identity(), "epoch": epoch,
        "aux_points_head": None if aux is None else aux.payload(),
        "git": {"sha": "test", "dirty": False}})
    return str(path)


@pytest.fixture(scope="module")
def cwv(tmp_path_factory):
    root = tmp_path_factory.mktemp("cwv-leaf")
    model, aux = mlp()
    path = save_cwv(root / "cwv.pt", model, aux)
    return {"path": path, "model": model, "aux": aux,
            "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest()}


@pytest.fixture(scope="module")
def headless_cwv(tmp_path_factory):
    model, _aux = mlp(seed=32)
    return save_cwv(tmp_path_factory.mktemp("cwv-headless") / "headless.pt", model, None)


def torch_aux_points(model, aux, clone, seat) -> float:
    """The reference: torch's own trunk + aux head on the afterstate tensors."""
    t = tensors_from_round(clone, seat)
    with torch.inference_mode():
        features = model.features(torch.from_numpy(t.public[None]),
                                  torch.from_numpy(t.world[None]),
                                  torch.from_numpy(t.perspective[None]))
        return float(aux(features)[0]) * L.POINTS_SCALE


def torch_level(model, clone, seat) -> float:
    """The signed-level head's expectation: what the leaf must NOT return."""
    t = tensors_from_round(clone, seat)
    support = torch.tensor([category_signed_level(i) for i in range(OUTCOME_CLASSES)])
    with torch.inference_mode():
        logits = model.head(model.features(torch.from_numpy(t.public[None]),
                                           torch.from_numpy(t.world[None]),
                                           torch.from_numpy(t.perspective[None])))
        return float(torch.softmax(logits, dim=1)[0] @ support)


def clone_at_horizon(rnd, seat, candidate, tricks):
    clone = copy.deepcopy(rnd)
    clone.play(seat, list(candidate))
    policy = HeuristicBot()
    while len(clone.history) < len(rnd.history) + tricks:
        clone.play(clone.turn, policy.decide_play(clone, clone.turn))
    return clone


# -------------------------- 1. aux points in production units; terminal exact

def test_cwv_leaf_returns_the_aux_points_head_and_terminal_leaves_stay_exact(cwv):
    head = L.CompleteWorldPointsHead.from_checkpoint(cwv["path"])
    assert head.metadata["checkpoint_sha256"] == cwv["sha256"]
    leaf = L.CompleteWorldPointsLeaf(head)
    rnd, seat = mid_trick_state(4_242)
    sampled, buried = true_world(rnd, seat)
    arm = L.MCValueLeafSearch(leaf, seed=1, leaf_tricks=1)
    candidate = make_bot(BASE)._candidates(rnd, seat)[0]
    got = arm._rollout(rnd, seat, sampled, buried, list(candidate))
    clone = clone_at_horizon(rnd, seat, candidate, 1)
    expected = torch_aux_points(cwv["model"], cwv["aux"], clone, clone.turn)
    assert got == pytest.approx(expected, abs=1e-4)
    assert got != pytest.approx(torch_level(cwv["model"], clone, clone.turn), abs=1e-4)
    assert arm.leaf_counts["predicted_leaves"] == 1 and head.calls == 1
    assert leaf.encode_secs > 0 and leaf.forward_secs > 0
    assert arm.policy_name == f"{BASE}+vleaf-cwv-t1"
    # A leaf that reaches round end is production's exact points, never the head.
    rnd, seat = last_trick_state(4_242)
    sampled, buried = true_world(rnd, seat)
    prod = make_bot(BASE, seed=1)
    arm = L.MCValueLeafSearch(leaf, seed=1, leaf_tricks=1)
    candidate = prod._candidates(rnd, seat)[0]
    exact = prod._rollout(rnd, seat, sampled, buried, list(candidate))
    assert arm._rollout(rnd, seat, sampled, buried, list(candidate)) == exact
    assert head.calls == 1
    assert arm.leaf_counts["terminal_leaves"] == 1 and arm.leaf_counts["predicted_leaves"] == 0


def test_witness_level_head_at_the_leaf_is_caught(monkeypatch, cwv):
    """Mutant: the leaf returns the signed-level head's expectation."""
    model = cwv["model"]
    monkeypatch.setattr(L.CompleteWorldPointsLeaf, "final_attacker_points",
                        lambda self, clone, seat: torch_level(model, clone, seat))
    head = L.CompleteWorldPointsHead.from_checkpoint(cwv["path"])
    rnd, seat = mid_trick_state(4_242)
    sampled, buried = true_world(rnd, seat)
    arm = L.MCValueLeafSearch(L.CompleteWorldPointsLeaf(head), seed=1, leaf_tricks=1)
    candidate = make_bot(BASE)._candidates(rnd, seat)[0]
    got = arm._rollout(rnd, seat, sampled, buried, list(candidate))
    clone = clone_at_horizon(rnd, seat, candidate, 1)
    assert got != pytest.approx(torch_aux_points(model, cwv["aux"], clone, clone.turn), abs=1e-4)


# --------------------------------- 2. the tensors come from the sampled world

def swapped_hidden_hands(clone, seat):
    """The same public state with two non-acting seats' hands exchanged."""
    other = copy.deepcopy(clone)
    a, b = (seat + 1) % 4, (seat + 3) % 4
    other.hands[a], other.hands[b] = clone.hands[b], clone.hands[a]
    return other


def test_leaf_value_depends_on_the_clones_hidden_hands(cwv):
    leaf = L.CompleteWorldPointsLeaf(L.CompleteWorldPointsHead.from_checkpoint(cwv["path"]))
    rnd, seat = mid_trick_state(4_242)
    clone = clone_at_horizon(rnd, seat, make_bot(BASE)._candidates(rnd, seat)[0], 1)
    acting = clone.turn
    other = swapped_hidden_hands(clone, acting)
    # The public observation of the acting seat is byte-identical ...
    assert np.array_equal(encode_obs(clone, acting), encode_obs(other, acting))
    assert np.array_equal(tensors_from_round(clone, acting).public,
                          tensors_from_round(other, acting).public)
    # ... and the world tensor, hence the leaf, is not.
    assert not np.array_equal(tensors_from_round(clone, acting).world,
                              tensors_from_round(other, acting).world)
    assert leaf.final_attacker_points(clone, acting) != pytest.approx(
        leaf.final_attacker_points(other, acting), abs=1e-6)


def test_witness_public_encoder_at_the_leaf_is_caught(monkeypatch, cwv):
    """Mutant: the leaf inputs are the public observation with an empty world."""
    def public_only(clone, seat):
        t = tensors_from_round(clone, seat)
        return np.concatenate((t.public, np.zeros_like(t.world).reshape(-1), t.perspective))

    monkeypatch.setattr(L, "cwv_leaf_inputs", public_only)
    leaf = L.CompleteWorldPointsLeaf(L.CompleteWorldPointsHead.from_checkpoint(cwv["path"]))
    rnd, seat = mid_trick_state(4_242)
    clone = clone_at_horizon(rnd, seat, make_bot(BASE)._candidates(rnd, seat)[0], 1)
    other = swapped_hidden_hands(clone, clone.turn)
    assert leaf.final_attacker_points(clone, clone.turn) == pytest.approx(
        leaf.final_attacker_points(other, clone.turn), abs=1e-9)


# ------------------------------------- 2b. the fast input row is the reference

def states_across_the_round():
    out = []
    for seed in (4_242, 4_243, 4_244):
        for tricks in (0, 3, 7, 11, 15):
            rnd = deal(seed)
            # at least one play made: the reference needs a public-history event,
            # and a leaf always follows the candidate's play
            seat = advance(rnd, lambda r, t=tricks: len(r.history) >= t
                           and len(r.trick.plays) == 1 + t % 3)
            out.append((rnd, seat))
    return out


def test_fast_leaf_inputs_are_tensors_from_round_byte_for_byte():
    assert L.MLP_INPUT_DIM == MLP_INPUT_DIM
    seen = 0
    for rnd, seat in states_across_the_round():
        for root in range(4):
            fast = L.cwv_leaf_inputs(rnd, root)
            assert fast.dtype == np.float32 and fast.shape == (MLP_INPUT_DIM,)
            assert np.array_equal(fast, L.cwv_reference_inputs(rnd, root))
            seen += 1
    assert seen == 60


def test_witness_dropped_burial_row_breaks_the_reference_equality(monkeypatch):
    original = L.cwv_leaf_inputs

    def without_burial(clone, seat):
        saved = clone.buried
        clone.buried = []
        try:
            return original(clone, seat)
        finally:
            clone.buried = saved

    monkeypatch.setattr(L, "cwv_leaf_inputs", without_burial)
    rnd, seat = mid_trick_state(4_242)
    assert not np.array_equal(L.cwv_leaf_inputs(rnd, seat), L.cwv_reference_inputs(rnd, seat))


# ------------------------------------------------------------ 3. numpy == torch

def random_rows(n=256, seed=6):
    g = torch.Generator().manual_seed(seed)
    public = torch.rand(n, MLP_INPUT_DIM - 5 * 54 - 2, generator=g)
    world = torch.randint(0, 3, (n, 5, 54), generator=g).float() / 2.0
    perspective = torch.zeros(n, 2)
    perspective[:, 0] = 1.0
    perspective[n // 2:, 0], perspective[n // 2:, 1] = 0.0, 1.0
    return public, world, perspective


def test_numpy_export_matches_torch_at_production_width():
    model, aux = mlp(width=256, feedforward=512, seed=8)
    head = L.CompleteWorldPointsHead.from_model(model, aux)
    public, world, perspective = random_rows()
    with torch.inference_mode():
        expected = aux(model.features(public, world, perspective)).numpy()
    rows = np.concatenate((public.numpy(), world.reshape(256, -1).numpy(), perspective.numpy()),
                          axis=1)
    got = head.forward(rows)
    assert got.shape == (256, 1)
    assert np.abs(got[:, 0] - expected).max() < 1e-5
    assert head.final_attacker_points(rows[3]) == pytest.approx(float(expected[3]) * 100.0,
                                                                abs=1e-3)


def test_witness_dropped_bias_breaks_numpy_torch_parity(monkeypatch):
    original = L.CompleteWorldPointsHead.__init__

    def dropped(self, hidden, output, **kw):
        w, _ = hidden[0]
        original(self, [(w, np.zeros(w.shape[0]))] + list(hidden[1:]), output, **kw)

    monkeypatch.setattr(L.CompleteWorldPointsHead, "__init__", dropped)
    model, aux = mlp(width=256, feedforward=512, seed=8)
    head = L.CompleteWorldPointsHead.from_model(model, aux)
    public, world, perspective = random_rows()
    with torch.inference_mode():
        expected = aux(model.features(public, world, perspective)).numpy()
    rows = np.concatenate((public.numpy(), world.reshape(256, -1).numpy(), perspective.numpy()),
                          axis=1)
    assert np.abs(head.forward(rows)[:, 0] - expected).max() > 1e-5


# ------------------------------------------------------------------ 4. refusals

def test_refuses_a_headless_checkpoint_and_a_foreign_encoder(tmp_path, cwv, headless_cwv):
    with pytest.raises(L.LeafError, match="no points head"):
        L.CompleteWorldPointsHead.from_checkpoint(headless_cwv)
    with pytest.raises(L.LeafError, match="no points head"):
        L.load_leaf_head(headless_cwv, leaf_model="cwv")
    with pytest.raises(L.LeafError, match="no points head"):
        L.CompleteWorldPointsHead.from_model(cwv["model"], None)
    with pytest.raises(L.LeafError, match="no points head"):   # the CLI prints REFUSING
        S.build_config(arm="learned", leaf_tricks=1, seed0=1, clusters=1, arm_select_worlds=1,
                       checkpoint=headless_cwv, leaf_model="cwv")
    forged = save_cwv(tmp_path / "forged.pt", cwv["model"], cwv["aux"],
                      encoder={**cwv_encoder_identity(), "implementation_sha256": "forged"})
    with pytest.raises(L.LeafError, match="encoder"):
        L.CompleteWorldPointsHead.from_checkpoint(forged)
    # The public loader refuses a cwv checkpoint and vice versa: the two
    # formats are not interchangeable behind one flag.
    with pytest.raises(ValueError):
        L.load_leaf_head(cwv["path"], leaf_model="public")
    with pytest.raises(L.LeafError, match="leaf_model"):
        L.load_leaf_head(cwv["path"], leaf_model="other")


def test_witness_removed_points_head_guards_accept_a_headless_checkpoint(monkeypatch, headless_cwv):
    """Mutant: both guards gone and a fresh (untrained) aux head stands in."""
    monkeypatch.setattr(L, "require_cwv_points_head", lambda metadata, **kw: None)
    original = L.CompleteWorldPointsHead.from_model.__func__

    def helpful(cls, model, aux_head, **kw):
        return original(cls, model, aux_head or AuxPointsHead(model.config.width), **kw)

    monkeypatch.setattr(L.CompleteWorldPointsHead, "from_model", classmethod(helpful))
    assert isinstance(L.CompleteWorldPointsHead.from_checkpoint(headless_cwv),
                      L.CompleteWorldPointsHead)


def test_witness_loader_bypassing_identity_check_accepts_a_forged_encoder(monkeypatch, tmp_path,
                                                                         cwv):
    def raw_loader(path):
        from shengji.rl.value_checkpoint import load_checkpoint
        model, metadata = load_checkpoint(path, map_location="cpu")
        return L.CompleteWorldPointsHead.from_model(
            model, AuxPointsHead.from_payload(metadata["aux_points_head"]))

    monkeypatch.setattr(L.CompleteWorldPointsHead, "from_checkpoint", staticmethod(raw_loader))
    forged = save_cwv(tmp_path / "forged.pt", cwv["model"], cwv["aux"],
                      encoder={**cwv_encoder_identity(), "implementation_sha256": "forged"})
    assert isinstance(L.CompleteWorldPointsHead.from_checkpoint(forged), L.CompleteWorldPointsHead)


def calibration_for(cwv, *, leaf_model, prior_path, **overrides):
    cal = {"schema": S.CALIBRATION_SCHEMA, "outcomes_read": False,
           "chosen_arm_select_worlds": 7, "checkpoint_sha256": cwv["sha256"], "leaf_tricks": 1,
           "baseline_policy": S.VLEAF_BASE_POLICY, "baseline_select_worlds": 1,
           "report_worlds": 30, "trump_ranks": ["2"], "within_band": True, "within_grid": True,
           "file_sha256": "x", "seed0": 1, "clusters": 1}
    if leaf_model is not None:
        cal["leaf_model"] = leaf_model
    cal.update(overrides)
    return cal


@pytest.fixture()
def prior_path(tmp_path):
    path = tmp_path / "prior_points.json"
    _publish(path, prior_table().to_dict())
    return str(path)


def test_run_refuses_a_calibration_made_for_the_other_leaf_model(monkeypatch, cwv, prior_path):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    kw = dict(leaf_tricks=1, seed0=1, clusters=1, arm_select_worlds=7, checkpoint=cwv["path"],
              prior=prior_path, baseline_select_worlds=1, report_worlds=30, trump_ranks=("2",))
    ok = S.build_config(arm="learned", leaf_model="cwv",
                        calibration=calibration_for(cwv, leaf_model="cwv", prior_path=prior_path),
                        **kw)
    assert ok["calibration"]["leaf_model"] == "cwv" and ok["leaf_model"] == "cwv"
    assert ok["arm_policy"] == f"mc-vleaf-cwv-{cwv['sha256'][:8]}-t1"
    for arm in ("learned", "prior"):
        with pytest.raises(S.ScreenError, match="leaf-model public"):
            S.build_config(arm=arm, leaf_model="cwv",
                           calibration=calibration_for(cwv, leaf_model="public",
                                                       prior_path=prior_path), **kw)
        # A calibration from before the field existed was made with the public head.
        with pytest.raises(S.ScreenError, match="leaf-model public"):
            S.build_config(arm=arm, leaf_model="cwv",
                           calibration=calibration_for(cwv, leaf_model=None,
                                                       prior_path=prior_path), **kw)
    with pytest.raises(S.ScreenError, match="leaf-model cwv"):
        S.build_config(arm="prior", leaf_model="public",
                       calibration=calibration_for(cwv, leaf_model="cwv", prior_path=prior_path),
                       **kw)


def test_witness_removed_leaf_model_binding_accepts_the_other_calibration(monkeypatch, cwv,
                                                                          prior_path):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "require_matching_leaf_model", lambda calibration, leaf_model: None)
    config = S.build_config(
        arm="learned", leaf_model="cwv", leaf_tricks=1, seed0=1, clusters=1, arm_select_worlds=7,
        checkpoint=cwv["path"], prior=prior_path, baseline_select_worlds=1, report_worlds=30,
        trump_ranks=("2",),
        calibration=calibration_for(cwv, leaf_model="public", prior_path=prior_path))
    assert config["calibration"]["leaf_model"] == "public"


# ------------------------------- 5. T beyond the round: production, byte for byte

def test_cwv_leaf_is_production_when_nothing_is_truncated(cwv):
    seed = 4_243
    head = L.CompleteWorldPointsHead.from_checkpoint(cwv["path"])
    prod = _tiny(make_bot(BASE, seed=seed))
    arm = _tiny(L.MCValueLeafSearch(L.CompleteWorldPointsLeaf(head), seed=seed,
                                    leaf_tricks=NO_TRUNCATION))
    assert _play_seat0(arm, seed, twin=prod) > 5
    assert arm.rollouts == prod.rollouts > 0
    assert head.calls == 0 and arm.leaf_secs == 0.0
    assert arm.leaf_counts["predicted_leaves"] == 0


# ----------------------------------------------------- registry and the screen

def test_registry_names_embed_cwv_and_the_checkpoint_id(cwv):
    registry = {BASE: REGISTRY[BASE]}
    names = register_vleaf_arms(checkpoint=cwv["path"], leaf_model="cwv", registry=registry)
    assert names == {f"mc-vleaf-cwv-{cwv['sha256'][:8]}-t{t}": "cwv" for t in VLEAF_LEAF_TRICKS}
    assert vleaf_policy_name(leaf_tricks=1, checkpoint_id="abcd1234", leaf_model="cwv") \
        == "mc-vleaf-cwv-abcd1234-t1"
    assert vleaf_policy_name(leaf_tricks=1, checkpoint_id="abcd1234") == "mc-vleaf-abcd1234-t1"
    assert vleaf_policy_name(leaf_tricks=1, leaf_model="cwv") == "mc-vleaf-prior-t1"
    with pytest.raises(ValueError, match="leaf_model"):
        vleaf_policy_name(leaf_tricks=1, checkpoint_id="abcd1234", leaf_model="seq")
    for name in names:
        bot = registry[name](seed=5)
        assert isinstance(bot, L.MCValueLeafSearch) and bot.leaf.kind == "cwv"
        assert bot.leaf.head.metadata["checkpoint_sha256"] == cwv["sha256"]
        assert bot.LEAF_TRICKS == int(name.rsplit("-t", 1)[1])
        assert bot.rng.getstate() == random.Random(5).getstate()
    record = L.leaf_record(registry[next(iter(names))](seed=5))
    assert record["leaf"]["leaf_model"] == "cwv" and record["leaf"]["held_out_claim"] is False


def test_real_cluster_with_the_cwv_leaf_counts_nn_calls(monkeypatch, tmp_path, cwv, prior_path):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    config = S.build_config(arm="learned", leaf_model="cwv", leaf_tricks=1, seed0=431, clusters=1,
                            arm_select_worlds=1, checkpoint=cwv["path"], prior=prior_path,
                            baseline_select_worlds=1, report_worlds=30, bootstrap_replicates=100,
                            trump_ranks=("2",))
    assert config["arm_policy"] == f"mc-vleaf-cwv-{cwv['sha256'][:8]}-t1"
    assert config["model_metadata"]["sees_hidden_hands"] is True
    summary = S.run_arm(config, output=tmp_path / "cwv", workers=1, log=lambda s: None,
                        executor_factory=threads)
    assert summary["leaf_model"] == "cwv" and summary["arm_policy"] == config["arm_policy"]
    assert "complete-world" in summary["arm_description"]
    arm = summary["leaf_counters"]["arm"]
    assert arm["nn_calls"] == arm["predicted_leaves"] > 0 and arm["prior_lookups"] == 0
    assert arm["leaf_encode_secs"] > 0 and arm["leaf_forward_secs"] > 0
    assert arm["leaf_encode_secs"] + arm["leaf_forward_secs"] <= arm["leaf_secs"]
    assert summary["per_leaf_usecs"]["arm"] > 0 and summary["per_leaf_usecs"]["baseline"] is None
    assert summary["equal_work_strength_claim"] is False
    rows = S.cpu_rows([{"records": summary_records(tmp_path / "cwv")}])
    ratio = S.cpu_ratio(rows)
    assert ratio["per_leaf_usecs"]["arm"] == pytest.approx(summary["per_leaf_usecs"]["arm"])
    assert ratio["leaf_encode_secs"]["arm"] > 0


def summary_records(output):
    import json
    return json.loads((output / "cluster-00000.json").read_text())["records"]
