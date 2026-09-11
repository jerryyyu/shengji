import copy
from collections import Counter

import numpy as np
import pytest

from shengji.ai.cwv_policy import CompleteWorldEvaluator, local_encoder_identity
from shengji.ai.cwv_static_encoding import tensors_from_round_static
from shengji.ai.memory import Memory
from shengji.engine.cards import TRUMP
from shengji.rl.encode_versions import encode_obs, encoder_version_for
from shengji.rl.encode_hand_control import hand_control_columns
from shengji.rl.value_afterstate_v2 import tensors_from_round
from shengji.rl.value_model import ValueModelConfig, ValueNetwork
from shengji.train.cwv_data import cwv_encoder_identity
from tests.test_cwv_static_encoding import _state_after


def test_v3_boss_features_match_memory_queries_not_hidden_world():
    rnd = _state_after(43, 12)
    for seat in range(4):
        mem = Memory(rnd,seat,own_kitty=False)
        values = hand_control_columns(rnd,seat,mem.unseen)
        counts = Counter(rnd.hands[seat])
        for group in (0,1):
            cards = [c for c in counts if int(rnd.ordering.eff_suit(c)==TRUMP)==group]
            assert values[group] == sum(counts[c] for c in cards if mem.is_boss(c))/25
            assert values[2+group] == sum(1 for c in cards if counts[c]>=2 and mem.pair_is_boss(c))/12
        twin = copy.deepcopy(rnd)
        hidden = [s for s in range(4) if s != seat]
        twin.hands[hidden[0]][0], twin.buried[0] = twin.buried[0], twin.hands[hidden[0]][0]
        assert encode_obs(rnd,seat,version=3) == encode_obs(twin,seat,version=3)


def test_v3_feature_values_tractor_and_pair_boss_positive_controls():
    rnd = _state_after(43,0)
    # Fixed NT ordering: ordinary hearts at consecutive levels, trump jokers.
    from shengji.engine.cards import Ordering
    rnd.ordering = Ordering(None,'2')
    rnd.hands[0] = ['H8','H8','H9','H9','BJ','BJ']
    v = hand_control_columns(rnd,0,Counter({'HA':1,'LJ':2}))
    assert v == [0.,2/25,2/12,1/12,2/12,0.,1/6,0.]
    blocked = hand_control_columns(rnd,0,Counter({'HA':2,'LJ':2}))
    assert blocked[2] == 0 and blocked[4] == 2/12


@pytest.mark.parametrize('plies',[1,4,35,70,100])
def test_v3_reference_static_and_v2_prefix_bytes(plies):
    rnd = _state_after(41,plies)
    for seat in range(4):
        ref = tensors_from_round(rnd,seat,version=3)
        fast = tensors_from_round_static(rnd,seat,version=3)
        old = tensors_from_round(rnd,seat,version=2)
        assert ref.public.shape == (569,)
        assert ref.public[:560].tobytes() == old.public[:-1].tobytes()
        assert ref.public[-1] == old.public[-1]
        for name in ('public','world','perspective'):
            assert getattr(ref,name).tobytes() == getattr(fast,name).tobytes()
        assert encoder_version_for(568) == 3


def test_v3_real_model_reference_static_scores_and_input_width():
    import torch
    torch.set_num_threads(1)
    torch.manual_seed(13)
    model = ValueNetwork(ValueModelConfig(architecture='mlp',width=16,
                         feedforward_width=32,public_dim=569,enc_version=3))
    ref = CompleteWorldEvaluator(None,model=model,encoding='reference')
    fast = CompleteWorldEvaluator(None,model=model,encoding='mlp-static')
    states = [_state_after(41,p) for p in (1,4,35,70)]
    assert np.array_equal(ref.score(states,0),fast.score(states,0))


def test_empty_history_retains_reference_refusal_and_v3_packing_is_exact():
    from shengji.rl.value_afterstate import ValueAfterstateError
    from shengji.train.data import obs_layout_for
    rnd = _state_after(41,0)
    for encoder in (tensors_from_round, tensors_from_round_static):
        with pytest.raises(ValueAfterstateError,match='^history tensor length drift$'):
            encoder(rnd,0,version=3)
    x = np.asarray([encode_obs(rnd,s,version=3) for s in range(4)],dtype=np.float32)
    layout = obs_layout_for(3)
    packed = layout.pack(x)
    assert layout.unpack(packed['bits'],packed['u8'],packed['f32']).tobytes()==x.tobytes()


def test_v3_identity_binds_feature_sources_and_keeps_v1_v2_old_closure(monkeypatch):
    from shengji.train import cwv_data
    before = {v:cwv_encoder_identity(v) for v in (1,2,3)}
    for v in before:
        assert before[v]['implementation_sha256'] == local_encoder_identity(v)['implementation_sha256']
    assert 'encode_hand_control' not in before[2]['source_sha256s']
    assert 'encode_hand_control' in before[3]['source_sha256s']
    real = cwv_data.sha256_file
    monkeypatch.setattr(cwv_data,'sha256_file',lambda path:
        'f'*64 if path.name=='encode_hand_control.py' else real(path))
    assert cwv_encoder_identity(1) == before[1]
    assert cwv_encoder_identity(2) == before[2]
    assert cwv_encoder_identity(3)['implementation_sha256'] != before[3]['implementation_sha256']


def test_v3_public_cache_identity_rejects_stale_feature_source(monkeypatch):
    from shengji.rl import encoder_identity as identity
    from shengji.train import data
    before = {v: data.encoder_identity(v) for v in (1, 2, 3)}
    keys = {v: data.encoder_cache_key(v) for v in before}
    meta = {"schema": data.CACHE_SCHEMA, "packing": data.packing_for(3),
            "encoder": before[3]}
    assert data.check_meta(meta, path="test-v3-cache", version=3) == meta
    real = identity.sha256_file
    monkeypatch.setattr(identity, "sha256_file", lambda path:
        "f" * 64 if path.name == "encode_hand_control.py" else real(path))
    for v in (1, 2):
        assert data.encoder_identity(v) == before[v]
        assert data.encoder_cache_key(v) == keys[v]
    assert data.encoder_cache_key(3) != keys[3]
    with pytest.raises(data.TrainDataError, match="^test-v3-cache: cache built by another encoder$"):
        data.check_meta(meta, path="test-v3-cache", version=3)


def test_v3_exported_static_evaluator_matches_reference(tmp_path):
    from shengji.ai.cwv_policy import shared_evaluator
    from tests.test_cwv_numpy import _actual_export
    package, model = _actual_export(tmp_path, version=3)
    ref = CompleteWorldEvaluator(None, model=model, encoding="reference")
    fast = shared_evaluator(str(package), encoding="mlp-static", threads=1)
    states = [_state_after(41, p) for p in (1, 4, 35, 70)]
    np.testing.assert_allclose(ref.score(states, 0), fast.score(states, 0),
                               atol=1e-5, rtol=1e-5)


def test_v3_public_checkpoint_consumers_bind_version_and_source(tmp_path, monkeypatch):
    import torch
    from shengji.rl import encoder_identity as identity
    from shengji.train import cwv_eval, data, train_v0
    from shengji.train.model import ValuePriorNet
    from shengji.train.search_inference import SearchHeads
    config = train_v0.build_config(data=["unopened"], hidden=8, encoder_version=3)
    path = tmp_path / "public.pt"
    train_v0.save_checkpoint(path, ValuePriorNet(config["arch"]), config=config,
        epoch=1, selection={}, baselines={}, calibration=None, split={}, population={})
    assert SearchHeads.from_checkpoint(path).enc_version == 3
    assert cwv_eval.public_head_version(cwv_eval.load_public_head(str(path))[0]) == 3
    payload = torch.load(path, weights_only=True)
    payload["encoder"] = data.encoder_identity(2)
    wrong = tmp_path / "wrong-version.pt"
    torch.save(payload, wrong)
    for loader, error in ((SearchHeads.from_checkpoint, ValueError),
                          (cwv_eval.load_public_head, cwv_eval.EvalError)):
        with pytest.raises(error, match="encoder version differs from its input width"):
            loader(wrong)
    real = identity.sha256_file
    monkeypatch.setattr(identity, "sha256_file", lambda p:
        "f" * 64 if p.name == "encode_hand_control.py" else real(p))
    with pytest.raises(ValueError, match="^checkpoint encoder differs from the current encoder$"):
        SearchHeads.from_checkpoint(path)
    with pytest.raises(cwv_eval.EvalError, match="public head encoder .* differs from this build"):
        cwv_eval.load_public_head(str(path))
