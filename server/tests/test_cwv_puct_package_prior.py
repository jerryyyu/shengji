"""Witnesses for the PUCT bot's joint-package policy prior and finish-trick
leaf boundary (#436 step 1).

Torch-free: the package is a tiny synthetic joint ``.npz`` built here with
``cwv_numpy.expected_arrays`` (random weights, the v2 schema, a policy head),
loaded by the same ``load_prior_checked`` the served prior admission uses.

Every witness carries its discriminator: the parity test checks against the
admission's own ``_prior_scores`` and shows a temperature or perspective
mutant differs; the sha test shows one flipped hex digit refuses; the leaf
test shows the scored position moved only within the trick and that the
default path scores the leaves themselves, unchanged.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from shengji.ai import cwv_puct
from shengji.ai.cwv_numpy import PACKAGE_SCHEMA_V2, CWVNumpyConfig, expected_arrays
from shengji.ai.cwv_policy import CWVError, file_sha256, finish_current_trick, sample_worlds
from shengji.ai.cwv_puct import (
    CWVPuctBot,
    JointPackagePriorHead,
    action_key,
    cwv_puct_registry_entries,
    leaf_boundary,
    leaf_copy,
    leaf_identity,
    prior_identity,
    puct_control_name,
    puct_policy_name,
    value_prior,
    world_clone,
)
from shengji.ai.mcbot import MCBot
from shengji.ai.memory import Memory
from shengji.train.cwv_prior_admission import CWVPriorAdmissionBot, load_prior_checked
from game_state_helpers import state_after as _state_after


def _load_script(name: str):
    path = Path(__file__).parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------- the package

def _write_joint_package(path: Path, seed: int) -> str:
    """A tiny plain-trunk joint package (value + 54-card policy head) with
    random weights; returns its sha256."""
    from shengji.ai.cwv_policy import local_encoder_identity
    cfg = CWVNumpyConfig(architecture="mlp", width=8, feedforward_width=16, public_dim=561,
                         enc_version=2, trunk_block="plain", trunk_layers=2, policy_head=True)
    rng = np.random.default_rng(seed)
    weights = {k: (rng.standard_normal(shape) * 0.2).astype(np.float32)
               for k, shape in expected_arrays(cfg).items()}
    payload = {"schema": PACKAGE_SCHEMA_V2,
               "config": {"architecture": "mlp", "width": 8, "feedforward_width": 16,
                          "public_dim": 561, "enc_version": 2, "trunk_block": "plain",
                          "trunk_layers": 2, "policy_head": True},
               "original_checkpoint_sha256": "0" * 64,
               "metadata": {"exported_value_head": "outcome",
                            "encoder": local_encoder_identity(2), "sees_hidden_hands": True}}
    np.savez_compressed(path, metadata=np.asarray(json.dumps(payload, sort_keys=True)), **weights)
    return file_sha256(path)


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    path = tmp_path_factory.mktemp("puctpkg") / "tiny-joint.npz"
    return str(path), _write_joint_package(path, 3)


@pytest.fixture(scope="module")
def other_package(tmp_path_factory):
    path = tmp_path_factory.mktemp("puctpkg2") / "other-joint.npz"
    return str(path), _write_joint_package(path, 23)


# --------------------------------------------------------------- fixtures

def _contested_state(seed: int = 5, start: int = 4, *, min_candidates: int = 3):
    bot = MCBot(seed=0)
    for plies in range(start, 110):
        rnd = _state_after(seed, plies)
        if rnd.phase != "play":
            break
        if len(bot._candidates(rnd, rnd.turn)) >= min_candidates:
            return rnd
    raise AssertionError("no contested state found")


class _StubEvaluator:
    backend = "stub"
    checkpoint_sha256 = None
    ckpt8 = None

    def __init__(self, rule=lambda p, s: 0.0):
        self.rule = rule
        self.batches = []
        self.forward_calls = 0

    def identity(self):
        return {"kind": "stub"}

    def score(self, positions, root_seat):
        self.batches.append((list(positions), root_seat))
        self.forward_calls += 1
        return np.asarray([self.rule(p, root_seat) for p in positions], dtype=np.float64)


def _bot(evaluator, **attrs) -> CWVPuctBot:
    head = attrs.pop("prior_head", None)
    cls = type("Probe", (CWVPuctBot,), {"CWV_WORLD_POOL": 4, "CWV_BATCH": 4,
                                        "CWV_SIMULATIONS": 24, "CWV_TRACE": True, **attrs})
    return cls(seed=7, evaluator=evaluator, prior_head=head)


def _capture_worlds(bot):
    captured = {}
    original = bot.sample_worlds

    def sample(rnd, seat, n, *, mem=None):
        worlds, attempts = original(rnd, seat, n, mem=mem)
        captured["worlds"] = [([list(h) for h in hands], list(buried)) for hands, buried in worlds]
        return worlds, attempts
    bot.sample_worlds = sample
    return captured


def _admission_scorer(path: str, sha: str):
    """The served admission's scoring object: `_prior_scores` bound to the
    checked prior triple, exactly as `CWVPriorAdmissionBot.__init__` binds it."""
    kind, net, payload = load_prior_checked(path, sha)
    scorer = type("Admission", (), {})()
    scorer._prior_kind, scorer._prior_net, scorer._prior_payload = kind, net, payload
    from shengji.train.cwv_prior_admission import prior_encoder_version
    scorer._prior_version = prior_encoder_version(kind, net, payload)
    scorer._prior_log_odds = CWVPriorAdmissionBot._prior_log_odds.__get__(scorer)
    scorer._prior_scores = CWVPriorAdmissionBot._prior_scores.__get__(scorer)
    return scorer


# --------------------------- (a) root prior == softmax of _prior_scores

def test_root_prior_is_the_softmax_of_the_admissions_prior_scores(package):
    path, sha = package
    T = 0.7
    head = JointPackagePriorHead(path, sha, temperature=T)
    assert head.identity()["prior_kind"] == "joint-numpy" and head.ckpt8 == sha[:8]
    rnd = _contested_state(5)
    seat = rnd.turn
    bot = _bot(_StubEvaluator(), CWV_PRIOR="package", CWV_PRIOR_TEMPERATURE=T, prior_head=head)
    captured = _capture_worlds(bot)
    bot.decide_play(copy.deepcopy(rnd), seat)
    rec = bot.last_decision_record
    assert rec["search"]["prior"] == "package" and rec["search"]["prior_temperature"] == T
    assert rec["search"]["prior_head"]["checkpoint_sha256"] == sha
    ballot = [list(c) for c in rec["candidates"]]
    worlds = captured["worlds"]
    # the served admission's own scores on the same root, worlds and ballot
    scores = _admission_scorer(path, sha)._prior_scores(rnd, seat, ballot, worlds)
    assert scores.shape == (len(worlds), len(ballot))
    want = value_prior(scores.mean(axis=0), T)
    assert len(set(np.round(want, 12))) > 1                       # the prior discriminates
    assert rec["root_prior"] == want.tolist()                     # bitwise: one code path
    # MUTANTS: the temperature ignored, or a single world instead of the pool mean
    assert rec["root_prior"] != pytest.approx(value_prior(scores.mean(axis=0), 1.0).tolist(), abs=1e-9)
    assert rec["root_prior"] != pytest.approx(value_prior(scores[0], T).tolist(), abs=1e-9)
    # the adapter never encodes the true hidden hands
    with pytest.raises(CWVError):
        head.probabilities(rnd, seat, ballot)

    # below the root: a node's prior in ITS world is the one-world score softmax
    hands, buried = worlds[0]
    clone = world_clone(rnd, hands, buried)
    clone.play(seat, ballot[0])
    opp = clone.turn
    node = cwv_puct.Node((action_key(ballot[0]),), 1)
    requests: list = []
    bot._expand(node, clone, requests)
    assert len(requests) == 1
    bot._serve_prior_requests(requests)
    world_ballot = bot._ballot(clone, opp)
    one_world = _admission_scorer(path, sha)._prior_scores(
        clone, opp, [list(a) for a in world_ballot], [(clone.hands, clone.buried)])
    assert [node.prior[a] for a in world_ballot] == pytest.approx(
        value_prior(one_world[0], T).tolist(), abs=1e-9)
    # the pure helper: an empty ballot or no worlds refuses
    with pytest.raises(CWVError):
        head.scores(rnd, seat, [], worlds)
    with pytest.raises(CWVError):
        head.scores(rnd, seat, ballot, [])


def test_batched_node_priors_equal_their_single_request_values(package):
    path, sha = package
    head = JointPackagePriorHead(path, sha)
    rnd = _contested_state(6)
    seat = rnd.turn
    mc = MCBot(seed=11)
    worlds, _ = sample_worlds(mc, rnd, seat, 3, mem=Memory(rnd, seat, own_kitty=True))
    rows = []
    for hands, buried in worlds:
        clone = world_clone(rnd, hands, buried)
        rows.append(head.encode(clone, clone.turn, [list(c) for c in mc._candidates(clone, clone.turn)]))
    batched = head.batch_from_encoded(rows)
    assert len(batched) == len(rows)
    for row, probs in zip(rows, batched):
        single = head.batch_from_encoded([row])[0]
        assert probs == pytest.approx(single.tolist(), abs=1e-9)
        assert probs.sum() == pytest.approx(1.0) and len(probs) == len(row[1])
    assert head.batch_from_encoded([]) == []


# ------------------------------------------------- (b) sha mismatch refuses

def test_a_sha_mismatch_or_a_headless_kind_refuses(package, tmp_path):
    path, sha = package
    flipped = ("0" if sha[0] != "0" else "1") + sha[1:]
    with pytest.raises(CWVError, match="refused"):
        JointPackagePriorHead(path, flipped)
    with pytest.raises(CWVError):
        JointPackagePriorHead(path, sha[:8])                   # not a full pin
    with pytest.raises(CWVError):
        JointPackagePriorHead(path, sha, temperature=0.0)
    with pytest.raises(CWVError):
        cwv_puct.make_cwv_puct_bot(path, simulations=4, prior="package",
                                   prior_checkpoint=path, prior_sha256=flipped)
    with pytest.raises(CWVError):
        cwv_puct.make_cwv_puct_bot(path, simulations=4, prior="package",
                                   prior_checkpoint=path)      # no pin at all
    # a package prior needs the hooks: a head without root_probabilities is refused
    class NoRoot:
        def encode(self, *a): ...
        def batch_from_encoded(self, *a): ...
    with pytest.raises(CWVError):
        _bot(_StubEvaluator(), CWV_PRIOR="package", prior_head=NoRoot())
    with pytest.raises(CWVError):
        _bot(_StubEvaluator(), CWV_PRIOR="package")


# ------------------------- (c) the finish-trick boundary and the default

def _within_the_trick(leaf, boundary) -> bool:
    """``boundary`` is ``leaf`` with at most the current trick finished: the
    same plays before it, and either the trick resolved (one more history
    entry, an empty new trick or the round over) or nothing changed."""
    before = len(leaf.history)
    if boundary.history[:before] != leaf.history[:before]:
        return False
    if not leaf.trick.plays or leaf.phase != "play":
        return len(boundary.history) == before and boundary.trick.plays == leaf.trick.plays
    if len(boundary.history) != before + 1:
        return False
    resolved = boundary.history[before]
    if [tuple(p.cards) for p in resolved.plays[:len(leaf.trick.plays)]] != \
            [tuple(p.cards) for p in leaf.trick.plays]:
        return False
    return boundary.phase == "round_end" or not boundary.trick.plays


def test_finish_trick_scores_the_boundary_and_moves_only_within_the_trick():
    rnd = _contested_state(5)
    seat = rnd.turn
    stub = _StubEvaluator(lambda p, s: 0.25)
    bot = _bot(stub, CWV_LEAF_FINISH_TRICK=True)
    bot.decide_play(copy.deepcopy(rnd), seat)
    rec = bot.last_decision_record
    assert rec["search"]["leaf_finish_trick"] is True and "leaf" not in rec["search"]
    scored = [p for batch, _s in stub.batches for p in batch]
    assert len(scored) == 24 == len(bot.last_trace)
    moved = 0
    for entry, position in zip(bot.last_trace, scored):
        leaf, boundary = entry["leaf"], entry["boundary"]
        assert position is boundary and boundary is not leaf
        assert _within_the_trick(leaf, boundary), (len(leaf.trick.plays), len(boundary.history))
        # the leaf itself stays as reached
        assert leaf.trick is not None
        # production's own helper produces the same boundary
        want = leaf_copy(leaf)
        finish_current_trick(want)
        assert want.history == boundary.history and want.hands == boundary.hands
        assert want.attacker_points == boundary.attacker_points
        moved += len(boundary.history) != len(leaf.history)
    assert moved > 0                                               # the boundary differs
    # MUTANT: a boundary that plays past the trick is caught by the witness
    leaf = bot.last_trace[0]["leaf"]
    too_far = leaf_boundary(leaf)
    from shengji.ai.heuristic import HeuristicBot
    if too_far.phase == "play":
        too_far.play(too_far.turn, HeuristicBot().decide_play(too_far, too_far.turn))
        assert not _within_the_trick(leaf, too_far)


def test_default_path_scores_the_leaves_themselves_and_is_unchanged():
    rnd = _contested_state(5)
    seat = rnd.turn
    rule = lambda p, s: float(len(p.history) % 3) - 1.0           # noqa: E731
    default = _bot(_StubEvaluator(rule))
    explicit = _bot(_StubEvaluator(rule), CWV_LEAF_FINISH_TRICK=False)
    assert default.CWV_LEAF_FINISH_TRICK is False
    default.decide_play(copy.deepcopy(rnd), seat)
    explicit.decide_play(copy.deepcopy(rnd), seat)
    for bot in (default, explicit):
        scored = [p for batch, _s in bot.evaluator.batches for p in batch]
        assert all(p is t["leaf"] for p, t in zip(scored, bot.last_trace))
        assert all("boundary" not in t for t in bot.last_trace)
        # the v1 identity: no leaf keys at all
        assert "leaf_finish_trick" not in bot.last_decision_record["search"]
    strip = lambda r: {k: v for k, v in r.items() if k not in ("work", "search_secs")}   # noqa: E731
    assert strip(default.last_decision_record) == strip(explicit.last_decision_record)
    assert [t["value"] for t in default.last_trace] == [t["value"] for t in explicit.last_trace]
    assert [t["path"] for t in default.last_trace] == [t["path"] for t in explicit.last_trace]
    # fixed-seed determinism of the default path across two fresh bots
    again = _bot(_StubEvaluator(rule))
    again.decide_play(copy.deepcopy(rnd), seat)
    assert strip(again.last_decision_record) == strip(default.last_decision_record)
    # the boundary CHANGES the values a history-sensitive stub returns
    finished = _bot(_StubEvaluator(rule), CWV_LEAF_FINISH_TRICK=True)
    finished.decide_play(copy.deepcopy(rnd), seat)
    assert [t["value"] for t in finished.last_trace] != [t["value"] for t in default.last_trace]
    # a playout leaf already plays through the trick: the flag is refused there
    with pytest.raises(CWVError):
        _bot(_StubEvaluator(), CWV_LEAF="playout", CWV_LEAF_FINISH_TRICK=True)
    assert leaf_identity("net", 1) == {} and leaf_identity("net", 1, True) == {"leaf_finish_trick": True}
    with pytest.raises(CWVError):
        leaf_identity("playout", 1, True)


# --------------------------------------------- (d) registry name round-trip

def test_registry_names_round_trip_the_package_prior_and_the_boundary(package, other_package):
    path, sha = package
    other, other_sha = other_package
    ckpt8 = sha[:8]
    assert puct_policy_name(ckpt8, 64, prior="package") == f"mc-cwvpuct-{ckpt8}-s64-pprior"
    assert puct_policy_name(ckpt8, 64, prior="package", prior_temperature=0.5,
                            leaf_finish_trick=True) == f"mc-cwvpuct-{ckpt8}-s64-pprior-T0.5-ftl"
    assert puct_policy_name(ckpt8, 64, leaf_finish_trick=True) == f"mc-cwvpuct-{ckpt8}-s64-ftl"
    assert puct_policy_name(ckpt8, 64, prior="package", prior8="abcd1234") \
        == f"mc-cwvpuct-{ckpt8}-prior-abcd1234-s64-pprior"
    assert puct_control_name(ckpt8, 64, prior="package", leaf_finish_trick=True, prior8="abcd1234") \
        == f"mc-cwvpuct-prior-{ckpt8}-s64-ftl"
    assert prior_identity("package", 1.0) == {"prior_temperature": 1.0}
    # one package in both roles: no -prior- part
    entries = cwv_puct_registry_entries(path, [64], prior="package", prior_checkpoint=path,
                                        prior_sha256=sha, leaf_finish_trick=True)
    assert set(entries) == {f"mc-cwvpuct-{ckpt8}-s64-pprior-ftl", f"mc-cwvpuct-prior-{ckpt8}-s64-ftl"}
    bot = entries[f"mc-cwvpuct-{ckpt8}-s64-pprior-ftl"](seed=3)
    assert bot.CWV_PRIOR == "package" and bot.CWV_LEAF_FINISH_TRICK is True
    assert bot.CWV_SIMULATIONS == 64 and bot.prior_head.package_sha256 == sha
    assert bot.cwv_ckpt8 == ckpt8 and bot.search_identity()["prior_head"]["ckpt8"] == ckpt8
    # a prior package other than the value package names itself
    split = cwv_puct_registry_entries(path, [64], prior="package", prior_checkpoint=other,
                                      prior_sha256=other_sha)
    assert f"mc-cwvpuct-{ckpt8}-prior-{other_sha[:8]}-s64-pprior" in split
    with pytest.raises(CWVError):
        cwv_puct_registry_entries(path, [64], prior="package", prior_checkpoint=path)
    with pytest.raises(CWVError):
        cwv_puct_registry_entries(path, [64], leaf="playout", leaf_finish_trick=True)
    # the registry helper takes the same keywords
    from shengji.ai.registry import REGISTRY, register_cwv_puct_policies
    names = register_cwv_puct_policies(path, [32], prior="package", prior_checkpoint=path,
                                       prior_sha256=sha)
    try:
        assert names == sorted([f"mc-cwvpuct-{ckpt8}-s32-pprior", f"mc-cwvpuct-prior-{ckpt8}-s32"])
    finally:
        for name in names:
            REGISTRY.pop(name, None)
    # the duel's binding and CLI carry both keys
    duel = _load_script("cwv_duel")
    args = duel.build_parser().parse_args(
        ["calibrate", "--checkpoint", path, "--out", "c.json", "--tree",
         "--prior", "package", "--prior-checkpoint", path, "--prior-sha256", sha,
         "--leaf-finish-trick"])
    binding = duel.search_from_args(args)
    assert binding["prior"] == "package" and binding["prior_checkpoint_sha256"] == sha
    assert binding["prior_temperature"] == 1.0 and binding["leaf_finish_trick"] is True
    assert duel.arm_name(args, ckpt8, 64) == f"mc-cwvpuct-{ckpt8}-s64-pprior-ftl"
    assert duel.control_arm_name(args, ckpt8, 64) == f"mc-cwvpuct-prior-{ckpt8}-s64-ftl"
    assert duel.arm_name(args, "deadbeef", 64) == f"mc-cwvpuct-deadbeef-prior-{ckpt8}-s64-pprior-ftl"
    plain = duel.build_parser().parse_args(
        ["calibrate", "--checkpoint", path, "--out", "c.json", "--tree"])
    assert "leaf_finish_trick" not in duel.search_from_args(plain)
    assert duel.arm_name(plain, ckpt8, 64) == f"mc-cwvpuct-{ckpt8}-s64"
    missing = duel.build_parser().parse_args(
        ["calibrate", "--checkpoint", path, "--out", "c.json", "--tree",
         "--prior", "package", "--prior-checkpoint", path])
    with pytest.raises(duel.CalibrationMismatch):
        duel.search_from_args(missing)


def test_the_package_prior_runs_end_to_end_on_the_packages_own_value_head(package):
    """The #436 arm shape: one package prices the leaf AND the ballot."""
    path, sha = package
    bot = cwv_puct.make_cwv_puct_bot(path, simulations=8, prior="package", prior_checkpoint=path,
                                     prior_sha256=sha, leaf_finish_trick=True, world_pool=2, batch=4,
                                     seed=5)
    rnd = _contested_state(5)
    move = bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    rec = bot.last_decision_record
    assert move in [list(c) for c in rec["candidates"]]
    assert rec["work"]["simulations"] == 8 and rec["evaluator"]["ckpt8"] == sha[:8]
    assert rec["search"]["prior_head"]["kind"] == "joint_package_policy_head"
    assert sum(rec["root_prior"]) == pytest.approx(1.0)
