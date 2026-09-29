"""#663 step 2 (Codex): the policy-isolation arm needs a pv-search bot whose POLICY PRIOR is
one hash-pinned package while the VALUE EVALUATOR stays another, so a policy scorer can be
swapped with production's value, recipe, bury and budgets held fixed.  The served bot binds
one package to both roles; this adds the optional second binding, through the same env,
registry and constructor the screens use, with the prior's identity in the policy name."""
import copy
import random

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import REGISTRY, make_bot, register_pv_search_policies
from shengji.engine.game import Game
from shengji.train import pv_search_policy as pv
from tests.test_pv_search_serving import package  # noqa: F401  (module fixture: one joint package)


def _joint_package(tmp_path_factory, seed, enc_version=2):
    torch = pytest.importorskip("torch")
    from scripts.export_cwv_numpy import export_cwv_numpy
    from shengji.ai.cwv_policy import file_sha256, local_encoder_identity
    from shengji.rl.encode_versions import OBS_DIM_BY_VERSION
    from shengji.rl.value_checkpoint import save_checkpoint
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    d = tmp_path_factory.mktemp(f"pvprior{seed}")
    torch.manual_seed(seed)
    net = ValueNetwork(ValueModelConfig(architecture="mlp", width=32, feedforward_width=64,
                                        public_dim=OBS_DIM_BY_VERSION[enc_version] + 1,
                                        enc_version=enc_version, attention_heads=1,
                                        trunk_block="residual", trunk_layers=2,
                                        search_head=True, policy_head=True))
    net.eval()
    ckpt = d / "joint.pt"
    save_checkpoint(ckpt, net, metadata={"encoder": local_encoder_identity(enc_version),
                                         "sees_hidden_hands": True})
    pkg = d / "joint.npz"
    export_cwv_numpy(ckpt, pkg)
    return str(pkg), file_sha256(pkg)


@pytest.fixture(scope="module")
def other_package(tmp_path_factory):
    """A second joint package with DIFFERENT weights (another seed)."""
    return _joint_package(tmp_path_factory, 23)


def _play_state(seed=625091990):
    rnd = Game(random.Random(seed)).start_round()
    h = HeuristicBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        c = h.decide_declare(rnd, seat)
        if c:
            rnd.declare(seat, c)
    for seat in range(4):
        c = h.decide_declare(rnd, seat, final=True)
        if c:
            rnd.declare(seat, c)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, h.decide_bury(rnd, rnd.banker))
    return rnd


def _registered(monkeypatch, value, prior=None):
    for k in [k for k in REGISTRY if k.startswith("pv-search-")]:
        del REGISTRY[k]
    monkeypatch.setenv("SHENGJI_PV_CKPT", value[0])
    monkeypatch.setenv("SHENGJI_PV_SHA256", value[1])
    monkeypatch.delenv("SHENGJI_PV_PRIOR_CKPT", raising=False)
    monkeypatch.delenv("SHENGJI_PV_PRIOR_SHA256", raising=False)
    if prior is not None:
        monkeypatch.setenv("SHENGJI_PV_PRIOR_CKPT", prior[0])
        monkeypatch.setenv("SHENGJI_PV_PRIOR_SHA256", prior[1])
    monkeypatch.setenv("SHENGJI_PV_WORLDS", "4")
    monkeypatch.setenv("SHENGJI_PV_CANDIDATES", "3")
    monkeypatch.setenv("SHENGJI_PV_CAP", "50")
    names = register_pv_search_policies(**pv.pv_env_recipe())
    assert len(names) == 1
    return names[0]


def test_env_recipe_binds_the_prior_pair_or_neither(package, other_package, monkeypatch):
    monkeypatch.setenv("SHENGJI_PV_CKPT", package[0])
    monkeypatch.setenv("SHENGJI_PV_SHA256", package[1])
    monkeypatch.delenv("SHENGJI_PV_PRIOR_CKPT", raising=False)
    monkeypatch.delenv("SHENGJI_PV_PRIOR_SHA256", raising=False)
    assert "prior_checkpoint" not in pv.pv_env_recipe()
    monkeypatch.setenv("SHENGJI_PV_PRIOR_CKPT", other_package[0])
    with pytest.raises(pv.PVSearchPolicyError, match="go together"):
        pv.pv_env_recipe()
    monkeypatch.setenv("SHENGJI_PV_PRIOR_SHA256", other_package[1][:8])
    with pytest.raises(pv.PVSearchPolicyError, match="full sha256"):
        pv.pv_env_recipe()
    monkeypatch.setenv("SHENGJI_PV_PRIOR_SHA256", other_package[1])
    recipe = pv.pv_env_recipe()
    assert recipe["prior_checkpoint"] == other_package[0] and recipe["prior_sha256"] == other_package[1]


def test_the_name_carries_the_prior_identity_only_when_one_is_bound(package, other_package, monkeypatch):
    plain = _registered(monkeypatch, package)
    with_prior = _registered(monkeypatch, package, other_package)
    assert plain.startswith(f"pv-search-{package[1][:8]}-w4-k3-")
    assert with_prior.startswith(f"pv-search-{package[1][:8]}-prior-{other_package[1][:8]}-w4-k3-")
    assert plain != with_prior
    # the same recipe digest: the prior changes the identity, not the recipe
    assert plain.rsplit("-r", 1)[1] == with_prior.rsplit("-r", 1)[1]


def test_the_bot_prices_with_the_value_package_and_admits_with_the_prior(package, other_package, monkeypatch):
    name = _registered(monkeypatch, package, other_package)
    bot = make_bot(name, seed=3)
    assert type(bot) is pv.PVSearchBot
    assert bot.checkpoint == package[0]
    assert bot.prior_checkpoint == other_package[0] and bot.prior_sha256 == other_package[1]
    # the prior predict object is the OTHER package; the evaluator is the value package
    assert bot.predict.path == other_package[0] and bot.predict.sha256 == other_package[1]
    # and the policy scores are the other package's, not the value package's own head
    rnd = _play_state()
    seat = rnd.turn
    legal = bot._legal(rnd, seat, [HeuristicBot().decide_play(copy.deepcopy(rnd), seat)])
    worlds, _ = bot._worlds(rnd, seat, None)
    own = pv.NumpyPriorPredict(package[0], package[1])
    mixed = bot.scores(rnd, seat, list(legal.actions), worlds).mean(axis=0)
    bot_own = make_bot(_registered(monkeypatch, package), seed=3)
    plain = bot_own.scores(rnd, seat, list(legal.actions), worlds).mean(axis=0)
    assert not np.allclose(mixed, plain), "the separate prior did not change the admission scores"


def test_binding_the_value_package_as_its_own_prior_is_the_served_bot(package, monkeypatch):
    """A prior package identical in bytes to the value package must decide exactly as the
    one-package bot: the second binding adds nothing but a name."""
    import shutil
    from shengji.ai.cwv_policy import file_sha256
    copy_path = str(pytest.importorskip("pathlib").Path(package[0]).with_name("same.npz"))
    shutil.copyfile(package[0], copy_path)
    assert file_sha256(copy_path) == package[1]
    plain = make_bot(_registered(monkeypatch, package), seed=5)
    twin = make_bot(_registered(monkeypatch, package, (copy_path, package[1])), seed=5)
    rnd = _play_state()
    seat = rnd.turn
    assert plain.decide_play(copy.deepcopy(rnd), seat) == twin.decide_play(copy.deepcopy(rnd), seat)


def test_a_mismatched_or_half_bound_prior_refuses(package, other_package, tmp_path):
    with pytest.raises(pv.PVSearchPolicyError, match="BOTH prior_checkpoint and prior_sha256"):
        pv.make_pv_search_bot(package[0], sha256=package[1], prior_checkpoint=other_package[0])
    with pytest.raises(pv.PVSearchPolicyError, match="prior package SHA256 mismatch"):
        pv.make_pv_search_bot(package[0], sha256=package[1], prior_checkpoint=other_package[0],
                              prior_sha256="0" * 64)
    with pytest.raises(pv.PVSearchPolicyError, match="prior package on disk"):
        pv.pv_registry_entries(package[0], sha256=package[1], prior_checkpoint=other_package[0],
                               prior_sha256="0" * 64)


def test_a_prior_of_another_encoder_version_refuses(package, other_package, tmp_path_factory, monkeypatch):
    """The served package loader accepts only the served encoding, so a v1 or v5 prior is
    refused at load before the version guard runs (fail closed either way).  The guard
    itself is driven with a prior that loads but reports another version."""
    from shengji.ai.cwv_numpy import CWVNumpyError
    for seed, version in ((31, 1), (37, 5)):
        pkg = _joint_package(tmp_path_factory, seed, enc_version=version)
        with pytest.raises((pv.PVSearchPolicyError, CWVNumpyError, ValueError)):   # the loader's own refusals
            pv.make_pv_search_bot(package[0], sha256=package[1], prior_checkpoint=pkg[0], prior_sha256=pkg[1])
    real = pv.NumpyPriorPredict

    class OtherVersion(real):
        def __init__(self, path, sha256):
            super().__init__(path, sha256)
            if path == other_package[0]:
                self.version = 5
    monkeypatch.setattr(pv, "NumpyPriorPredict", OtherVersion)
    with pytest.raises(pv.PVSearchPolicyError, match="must agree"):
        pv.make_pv_search_bot(package[0], sha256=package[1], prior_checkpoint=other_package[0],
                              prior_sha256=other_package[1])
