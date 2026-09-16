"""#425 served as ONE file: a v2 NumPy package carries the joint net's policy head, reproduces
the Torch head over the trunk features without Torch, and the prior admission loads that same
package as the prior (kind ``joint-numpy``) with an admitted pool identical to the Torch joint prior.

Witnesses: parity of ``policy_log_odds`` with ``policy_logits(features_flat(x))``; a headless
package refuses the call; a package that drops a policy array is schema drift; the admission's
pools match the Torch joint kind on a real wide decision; Torch stays out of the served process.
"""
import hashlib
import json
import subprocess
import sys

import numpy as np
import pytest

from shengji.ai.cwv_numpy import CWVNumpyError, PACKAGE_SCHEMA_V2, load_cwv_numpy


@pytest.fixture(scope="module")
def joint(tmp_path_factory):
    torch = pytest.importorskip("torch")
    from scripts.export_cwv_numpy import export_cwv_numpy
    from shengji.ai.cwv_policy import local_encoder_identity
    from shengji.rl.value_checkpoint import save_checkpoint
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    d = tmp_path_factory.mktemp("joint")
    torch.manual_seed(11)
    net = ValueNetwork(ValueModelConfig(architecture="mlp", width=32, feedforward_width=64, public_dim=561,
                                        enc_version=2, attention_heads=1, trunk_block="residual",
                                        trunk_layers=2, search_head=True, policy_head=True))
    net.eval()
    ckpt = d / "joint.pt"
    save_checkpoint(ckpt, net, metadata={"encoder": local_encoder_identity(2), "sees_hidden_hands": True})
    pkg = d / "joint.npz"
    export_cwv_numpy(ckpt, pkg)
    headless = ValueNetwork(ValueModelConfig(architecture="mlp", width=32, feedforward_width=64, public_dim=561,
                                             enc_version=2, attention_heads=1, trunk_block="residual",
                                             trunk_layers=2, search_head=True))
    headless.eval()
    hckpt = d / "headless.pt"
    save_checkpoint(hckpt, headless, metadata={"encoder": local_encoder_identity(2), "sees_hidden_hands": True})
    hpkg = d / "headless.npz"
    export_cwv_numpy(hckpt, hpkg)
    return net, str(ckpt), str(pkg), str(hpkg)


def test_joint_package_reproduces_the_torch_policy_head_and_value_softmax(joint):
    torch = pytest.importorskip("torch")
    net, ckpt, pkg, hpkg = joint
    model = load_cwv_numpy(pkg)
    assert model.policy_head is True
    meta = json.loads(str(np.load(pkg)["metadata"].item()))
    assert meta["schema"] == PACKAGE_SCHEMA_V2 and meta["config"]["policy_head"] is True
    rng = np.random.default_rng(5)
    public = rng.standard_normal((9, 561)).astype(np.float32)
    world = (rng.integers(0, 3, (9, 5, 54)) * 0.5).astype(np.float32)
    persp = np.eye(2, dtype=np.float32)[rng.integers(0, 2, 9)]
    flat = np.concatenate((public, world.reshape(9, -1), persp), axis=1)
    with torch.no_grad():
        want = net.policy_logits(net.features_flat(torch.from_numpy(flat))).numpy()
        want_p = torch.softmax(net.head_logits(net.features(torch.from_numpy(public), torch.from_numpy(world),
                                                            torch.from_numpy(persp)), "outcome"), 1).numpy()
    np.testing.assert_allclose(model.policy_log_odds(flat), want, rtol=2e-5, atol=2e-6)
    np.testing.assert_allclose(model.probabilities(public, world, persp), want_p, rtol=2e-5, atol=2e-6)
    # a headless package refuses the policy call; the joint package refuses shape drift
    with pytest.raises(CWVNumpyError, match="no policy head"):
        load_cwv_numpy(hpkg).policy_log_odds(flat)
    with pytest.raises(CWVNumpyError, match="shape drift"):
        model.policy_log_odds(flat[:, :-1])


def test_a_joint_package_missing_a_policy_array_is_schema_drift(joint, tmp_path):
    _, _, pkg, _ = joint
    z = dict(np.load(pkg))
    bad = {k: v for k, v in z.items() if k != "policy_bias"}
    np.savez_compressed(tmp_path / "bad.npz", **bad)
    with pytest.raises(CWVNumpyError, match="schema drift"):
        load_cwv_numpy(tmp_path / "bad.npz")
    # a package claiming a policy head must be v2
    meta = json.loads(str(z["metadata"].item())); meta["schema"] = "shengji-cwv-numpy-mlp-v1"
    z2 = dict(z); z2["metadata"] = np.asarray(json.dumps(meta, sort_keys=True))
    np.savez_compressed(tmp_path / "v1claim.npz", **z2)
    with pytest.raises(CWVNumpyError):
        load_cwv_numpy(tmp_path / "v1claim.npz")


def test_admission_loads_the_joint_package_as_the_prior_with_the_torch_pool(joint):
    """The served single-file design: the same .npz is the value package AND the prior."""
    from shengji.train.cwv_prior_admission import (CWVPriorAdmissionBot, CWVPriorAdmissionConfig,
                                                    load_prior_checked)
    from shengji.train.cwv_shortlist import CWVShortlistConfig
    from test_cwv_prior_admission import Values, play_state
    net, ckpt, pkg, hpkg = joint
    sha = lambda p: hashlib.file_digest(open(p, "rb"), "sha256").hexdigest()
    kind, model, payload = load_prior_checked(pkg, sha(pkg))
    assert kind == "joint-numpy" and payload is None and model.policy_head
    with pytest.raises(ValueError, match="neither"):
        load_prior_checked(hpkg, sha(hpkg))
    # The Torch reference: the same net as the trainer's "joint" kind (the cache is primed
    # directly because this hand-saved checkpoint carries no trainer metadata; the kind's
    # log-odds path is unchanged: policy_logits over features_flat).
    from shengji.train import cwv_prior_admission as adm
    adm._PRIORS[(ckpt, sha(ckpt))] = ("joint", net, None)
    rnd = play_state(); seat = rnd.turn
    pools = []
    for ck in (pkg, ckpt):
        bot = CWVPriorAdmissionBot(Values(), seed=13, config=CWVShortlistConfig(worlds=2),
                                   prior=CWVPriorAdmissionConfig(checkpoint=ck, checkpoint_sha256=sha(ck),
                                                                 threshold=1, top=8))
        selected = bot._candidates(rnd, seat)
        adm = bot.last_shortlist["prior_admission"]
        pools.append((sorted(map(tuple, selected)), adm["union_size"], adm["pool_action_count"], adm["prior_kind"]))
    assert pools[0][:3] == pools[1][:3], pools
    assert pools[0][3] == "joint-numpy" and pools[1][3] == "joint"


def test_served_process_loads_the_joint_prior_without_torch(joint):
    _, _, pkg, _ = joint
    code = f"""
import sys
class Block:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'torch' or fullname.startswith('torch.'):
            raise RuntimeError('torch import blocked')
sys.meta_path.insert(0, Block())
import hashlib, numpy as np
from shengji.train.cwv_prior_admission import load_prior_checked
sha = hashlib.file_digest(open({pkg!r}, 'rb'), 'sha256').hexdigest()
kind, model, _ = load_prior_checked({pkg!r}, sha)
out = model.policy_log_odds(np.zeros((2, 561 + 5 * 54 + 2), dtype=np.float32))
print(kind, out.shape)
"""
    run = subprocess.run([sys.executable, "-P", "-B", "-c", code], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[-800:]
    assert run.stdout.strip() == "joint-numpy (2, 54)"
