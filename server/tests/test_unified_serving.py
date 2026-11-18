"""The unified model's slots as a served registry entry (`train.unified_serving`), off by default.

Three claims, each on release 52's bot built from the repo's ``fly.toml`` on the hash-pinned
release-50 packages (they fail, never skip, under ``SHENGJI_REQUIRE_PV_PACKAGE=1``):

* unset, nothing changes: the registry holds the names it held, the serving module is not imported,
  and a served bot decides the same beside a unified bot in the same process;
* set, the registry bot is the bot the duel adapter built: the served registry entry with the
  shared forward, the value readout and the reply readout installed, decision for decision on the
  ten fixed production positions of `r50_flag_positions`;
* set, the bot acts through the server's own snapshot and commit path, with every slot filled from
  one trunk forward.

The unified package here is a small random one (the claims are about wiring, not strength).  With
``SHENGJI_PV_UNIFIED_PACKAGE_PATH`` and ``SHENGJI_PV_UNIFIED_BELIEF_PACKAGE_PATH`` naming the
screened pair, the same tests also run on it; they skip where it is not provisioned.
"""
import asyncio
import copy
import hashlib
import os
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import r50_flag_positions as P
from test_release46_fly_config import fly_env as production_env
from test_release48_fly_config import apply_to_process
from test_release50_fly_config import (BELIEF_VOLUME_PATH, PRIOR_SHA, PRIOR_VOLUME_PATH, VALUE_SHA,
                                       VALUE_VOLUME_PATH, local_env, release50_packages)  # noqa: F401
from test_release52_fly_config import RELEASE52

#: the screened pair (arm ALL): the unified readout package and the belief package carrying its trunk
UNIFIED_SHA = "97c07be8614ed5c42e47882ff2ad4e68ffb6f174d071f14469f1d0a96f5490af"
UNIFIED_BELIEF_SHA = "1b1fd2deb43b109bd4577af6ffdb98977ad90525de8914c6cbae20e0d5ac77f4"
UNIFIED_VOLUME_PATH = "/data/models/ut-all-97c07be8.npz"
UNIFIED_BELIEF_VOLUME_PATH = "/data/models/ut-all-belief-1b1fd2de.npz"
#: the exploiter's name in the screen's recipe (the duel adapter's), byte for byte
SCREENED = ("pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-rcec-whl-whd-wht-bw-tb-ele-elt-elm-la-"
            "dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-els1600-xf7-xfcompactlevel-r09a10415-bury-"
            "hybrid-bwv-bbw-1b1a47f5dd8b-sc8-ushare97c07be8-uvalue97c07be8-ureply97c07be8")
PAIR_VARS = ("SHENGJI_PV_UNIFIED_PACKAGE_PATH", "SHENGJI_PV_UNIFIED_BELIEF_PACKAGE_PATH")
COUNTERS = ("unified_prior_calls", "unified_shared_hits", "unified_shared_misses", "unified_value_rows",
            "unified_value_other", "unified_reply_rows", "unified_reply_served", "unified_trunk_forwards",
            "unified_trunk_shared")
TRUNK = {"d": 16, "heads": 4, "enc_layers": 1, "xattn_layers": 1, "x_hidden": 16, "card_self_attn": True}
CONFIG = {"trunk": TRUNK, "heads": {"q_hidden": 8, "policy_hidden": 8},
          "readout": {"dp": 8, "dc": 8, "width": 16, "hidden": 32, "blocks": 1}}


def _random_pair(root):
    from shengji.ai import belief_numpy as bn
    from shengji.ai import unified_numpy as un
    from shengji.ai import unified_readout_numpy as rn

    rng = np.random.default_rng(11)

    def weights(shapes):
        return {k: (0.3 * rng.standard_normal(s)).astype(np.float32) for k, s in shapes.items()}
    path = root / "u.npz"
    sha = rn.save_package(path, CONFIG, weights(bn.expected_shapes(TRUNK, **bn.DIMS)),
                          weights(un.head_shapes(CONFIG)), weights(rn.readout_shapes(CONFIG)),
                          {"temperature": 1.1})
    belief = root / "u-belief.npz"
    belief_sha = rn.belief_package(rn.load_unified_readout_numpy(path, sha), belief)
    return {"unified": (str(path), sha), "belief": (str(belief), belief_sha)}


@pytest.fixture(scope="module", params=["random", "screened"])
def pair(request, tmp_path_factory):
    """``{"unified": (path, sha256), "belief": (path, sha256)}``: a small random pair, or the
    screened one where its two paths are provisioned."""
    if request.param == "random":
        return _random_pair(tmp_path_factory.mktemp("unified"))
    paths = [os.environ.get(var) for var in PAIR_VARS]
    if not all(paths):
        pytest.skip(f"set {' and '.join(PAIR_VARS)} to run on the screened pair")
    for path, sha in zip(paths, (UNIFIED_SHA, UNIFIED_BELIEF_SHA)):
        actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        assert actual == sha, f"{path} is {actual[:12]}, not the screened {sha[:12]}"
    return {"unified": (paths[0], UNIFIED_SHA), "belief": (paths[1], UNIFIED_BELIEF_SHA)}


@pytest.fixture
def served_functions(monkeypatch):
    """The two served functions the unified bots wrap, restored after the test, the serving
    module's package cache emptied, and the belief proposal's preparation budget lifted with the
    other clocks (`r50_flag_positions.lift`), so every compared decision is a function of the code
    alone and none falls back to the fallback worlds on a slow host."""
    from shengji.ai import belief_numpy as bn
    from shengji.train import pv_encode_prefix, pv_tree_search, unified_serving

    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    monkeypatch.setattr(pv_tree_search, "greedy_reply_ply", pv_tree_search.greedy_reply_ply)
    monkeypatch.setattr(pv_encode_prefix, "score_leaves", pv_encode_prefix.score_leaves)
    monkeypatch.setattr(unified_serving, "_MODELS", {})
    return pv_tree_search.greedy_reply_ply, pv_encode_prefix.score_leaves


def unified_env(packages, pair) -> dict:
    """Release 52's env on the local packages with the four lines a unified release changes: the
    belief pair, the unified pair, and the name the registry derives from them."""
    from shengji.eval.served_config import registry_name

    env = {**local_env(packages, production_env()),
           "SHENGJI_PV_BELIEF_CKPT": pair["belief"][0], "SHENGJI_PV_BELIEF_SHA256": pair["belief"][1],
           "SHENGJI_PV_UNIFIED_CKPT": pair["unified"][0], "SHENGJI_PV_UNIFIED_SHA256": pair["unified"][1]}
    env["SHENGJI_BOT"] = registry_name(env)
    return env


def register(monkeypatch, env):
    """The registry as the server's import leaves it for ``env`` (a scratch copy)."""
    from shengji.ai import registry

    for key in list(os.environ):
        if key.startswith("SHENGJI_PV_"):
            monkeypatch.delenv(key)
    apply_to_process(monkeypatch, env)
    monkeypatch.setattr(registry, "REGISTRY", {k: v for k, v in registry.REGISTRY.items()
                                               if not k.startswith("pv-search-")})
    registry._register_pv_search_from_env()
    return registry


def registry_bot(monkeypatch, env, seed):
    return register(monkeypatch, env).make_bot(env["SHENGJI_BOT"], seed=seed)


def adapter_bot(monkeypatch, env, pair, seed):
    """The duel adapter's exploiter, step for step: the served registry entry for ``env`` without
    the unified lines, then the three installs on that bot, with the adapter's two module-level
    stand-ins in place for the duration of the caller's patch context."""
    from shengji.ai.unified_readout_numpy import load_unified_readout_numpy
    from shengji.train import pv_encode_prefix, pv_search_policy as pv, pv_tree_search, unified_slots as us

    words = {k: v for k, v in env.items() if "UNIFIED" not in k}
    register(monkeypatch, words)
    recipe = pv.pv_env_recipe(words)
    (name, factory), = pv.singleton_registry_entries(checkpoint=recipe.pop("checkpoint"), **recipe).items()
    monkeypatch.setattr(pv_tree_search, "greedy_reply_ply", us.readout_reply_ply(pv_tree_search.greedy_reply_ply))
    monkeypatch.setattr(pv_encode_prefix, "score_leaves", us.readout_score_leaves(pv_encode_prefix.score_leaves))
    model = load_unified_readout_numpy(*pair["unified"])
    bot = factory(seed=seed)
    assert bot.policy_name == name
    us.install_shared_forward(bot, model)
    us.install_value_readout(bot, model, keep_prefix=True)
    us.install_reply_readout(bot, model, keep_prefix=True)
    return bot


def decide(bot, rnd):
    """`P.decision` plus the slot counters the decision moved; the registry bot's own account of
    them (the record's ``unified`` entry, which the adapter's bot does not write) is checked against
    the counters and taken out, so the two bots' results compare whole."""
    from shengji.train import unified_serving as serving

    before = [getattr(bot, name, 0) for name in COUNTERS]
    out = P.decision(P.lift(bot), rnd)
    assert out["record"]["belief_fallback"] == 0, out["record"].get("belief_fallback_reason")
    out["counters"] = dict(zip(COUNTERS, (getattr(bot, name, 0) - b for name, b in zip(COUNTERS, before))))
    account = out["record"].pop(serving.RECORD_KEY, None)
    if hasattr(bot, "unified_sha256"):
        memo = {name: account.pop(name) for name in serving.FAST_RECORD_FIELDS if name in account}
        assert set(memo) == (set(serving.FAST_RECORD_FIELDS) if bot.unified_fast else set())
        if memo:
            out["memo"] = memo
        assert account == {"package": bot.unified_sha256[:8],
                           **{name: out["counters"][attr] for name, attr in serving.RECORD_FIELDS.items()}}
    else:
        assert account is None
    return out


def test_the_two_keys_go_together_and_pin_a_full_hash():
    from shengji.train import unified_serving as serving
    from shengji.train.pv_search_policy import PVSearchPolicyError

    assert serving.unified_env({}) is None
    assert serving.unified_env({serving.CKPT_KEY: "", serving.SHA256_KEY: ""}) is None
    assert serving.unified_env({serving.CKPT_KEY: "/m/u.npz", serving.SHA256_KEY: UNIFIED_SHA}) == \
        ("/m/u.npz", UNIFIED_SHA)
    for env in ({serving.CKPT_KEY: "/m/u.npz"}, {serving.SHA256_KEY: UNIFIED_SHA},
                {serving.CKPT_KEY: "/m/u.npz", serving.SHA256_KEY: UNIFIED_SHA[:8]},
                {serving.CKPT_KEY: "/m/u.npz", serving.SHA256_KEY: UNIFIED_SHA.upper()},
                {serving.CKPT_KEY: "/m/u.pt", serving.SHA256_KEY: UNIFIED_SHA}):
        with pytest.raises(PVSearchPolicyError):
            serving.unified_env(env)
    assert serving.unified_registry_entries(environ={}, checkpoint="unused", sha256="0" * 64) == {}


def test_the_volume_paths_derive_the_screened_name(monkeypatch):
    """fly.toml with the four unified lines, as written for the volume (hashes stood in for the
    files): the served part of the name is the screen's exploiter's, and the suffix its three
    tokens."""
    from shengji.ai import cwv_policy
    from shengji.train import pv_search_policy as pv
    from shengji.train import unified_serving as serving

    by_path = {VALUE_VOLUME_PATH: VALUE_SHA, PRIOR_VOLUME_PATH: PRIOR_SHA,
               UNIFIED_BELIEF_VOLUME_PATH: UNIFIED_BELIEF_SHA}
    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: by_path[str(path)][:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: by_path[str(path)])
    env = {**production_env(), "SHENGJI_PV_BELIEF_CKPT": UNIFIED_BELIEF_VOLUME_PATH,
           "SHENGJI_PV_BELIEF_SHA256": UNIFIED_BELIEF_SHA}
    assert env["SHENGJI_BOT"] == RELEASE52 and BELIEF_VOLUME_PATH in production_env().values()
    served, = pv.singleton_registry_entries(**pv.pv_env_recipe(env))
    assert serving.unified_name(served, UNIFIED_SHA) == SCREENED
    moved = [t for t in served.split("-") if t not in RELEASE52.split("-")]
    assert moved == ["r09a10415", "1b1a47f5dd8b"]


def test_unset_the_registry_and_the_served_bot_are_untouched(release50_packages):
    """A fresh process with fly.toml's env: no unified name, the serving modules never imported,
    the served functions unwrapped, and no instance override on the served bot."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("SHENGJI_PV_")}
    # the release-28 rollback keys name a package this test does not provision
    env.update({k: v for k, v in local_env(release50_packages, production_env()).items()
                if not k.startswith("SHENGJI_CWV_")})
    env.pop("SHENGJI_LOG_DIR", None)
    if os.environ.get("SHENGJI_FAST") != "1":
        env.pop("SHENGJI_FAST", None)
    code = (
        "import os, sys\n"
        "if os.environ.get('SHENGJI_FAST') == '1':\n"
        "    from shengji.engine import fast\n"
        "    assert fast.activate()\n"
        "from shengji.ai import registry\n"
        "from shengji.train import pv_encode_prefix, pv_tree_search\n"
        "names = [n for n in registry.REGISTRY if n.startswith('pv-search-')]\n"
        "assert os.environ['SHENGJI_BOT'] in names and not [n for n in names if 'ushare' in n], names\n"
        "bot = registry.make_bot(os.environ['SHENGJI_BOT'], seed=1)\n"
        "loaded = [m for m in sys.modules if m.startswith('shengji.') and 'unified' in m]\n"
        "assert not loaded, loaded\n"
        "assert pv_tree_search.greedy_reply_ply.__module__ == 'shengji.train.pv_tree_search'\n"
        "assert pv_encode_prefix.score_leaves.__module__ == 'shengji.train.pv_encode_prefix'\n"
        "assert not {'scores', '_search', '_belief_worlds'} & set(vars(bot)), sorted(vars(bot))\n"
        "assert type(bot.belief_model).__name__ == 'BeliefNumpy'\n"
        "print('UNTOUCHED', bot.policy_name)\n")
    done = subprocess.run([sys.executable, "-B", "-c", code], env=env, capture_output=True, text=True,
                          cwd=Path(__file__).resolve().parents[1], timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip() == f"UNTOUCHED {RELEASE52}"


def test_set_the_registry_gains_one_name_beside_the_served_ones(release50_packages, pair, monkeypatch,
                                                              served_functions):
    from shengji.train import unified_serving as serving

    env = unified_env(release50_packages, pair)
    without = {k: v for k, v in env.items() if "UNIFIED" not in k}
    before = {n for n in register(monkeypatch, without).REGISTRY if n.startswith("pv-search-")}
    after = {n for n in register(monkeypatch, env).REGISTRY if n.startswith("pv-search-")}
    sha8 = pair["unified"][1][:8]
    served, = [n for n in before if n.endswith("-sc8")]
    assert after - before == {env["SHENGJI_BOT"]} == {f"{served}-ushare{sha8}-uvalue{sha8}-ureply{sha8}"}
    assert before <= after and not serving.active()
    if pair["unified"][1] == UNIFIED_SHA:
        assert env["SHENGJI_BOT"] == SCREENED
    bot = registry_bot(monkeypatch, env, seed=3)
    assert bot.policy_name == env["SHENGJI_BOT"] and serving.active()
    assert bot.unified_sha256 == pair["unified"][1]
    assert bot.model_ids("play")["belief"] == pair["belief"][1][:8]
    assert bot.encode_prefix_cache is True and bot.leaf_greedy_finish is True


def test_a_belief_package_with_another_trunk_refuses_at_registration(release50_packages, pair, monkeypatch,
                                                                    served_functions):
    from shengji.train.pv_search_policy import PVSearchPolicyError

    env = {**local_env(release50_packages, production_env()),
           "SHENGJI_PV_UNIFIED_CKPT": pair["unified"][0], "SHENGJI_PV_UNIFIED_SHA256": pair["unified"][1]}
    with pytest.raises(PVSearchPolicyError, match="trunk"):
        register(monkeypatch, env)
    wrong = {**unified_env(release50_packages, pair), "SHENGJI_PV_UNIFIED_SHA256": "0" * 64}
    with pytest.raises(PVSearchPolicyError, match="sha256"):
        register(monkeypatch, wrong)
    off = {**unified_env(release50_packages, pair), "SHENGJI_PV_LEAF_GREEDY_FINISH": "0",
           "SHENGJI_PV_LEAF_GREEDY_FINISH_EXACT_SKIP": "0", "SHENGJI_PV_LEAF_GREEDY_DEADLINE": ""}
    off.pop("SHENGJI_PV_LEAF_GREEDY_DEADLINE")
    with pytest.raises(PVSearchPolicyError, match="LEAF_GREEDY_FINISH"):
        register(monkeypatch, off)


def test_the_registry_bot_decides_as_the_duel_adapters_bot(release50_packages, pair, monkeypatch,
                                                          served_functions):
    """Ten fixed production positions: the played cards, the base worlds, the decision record and
    the slot counters of the registry's unified bot equal the adapter-built bot's exactly."""
    env = unified_env(release50_packages, pair)
    want = {}
    with monkeypatch.context() as patch:
        for position in P.POSITIONS:
            bot = adapter_bot(patch, env, pair, P.SEED)
            assert bot.policy_name == env["SHENGJI_BOT"]
            want[position] = decide(bot, P.replay(*position))
    totals = dict.fromkeys(COUNTERS, 0)
    for position in P.POSITIONS:
        got = decide(registry_bot(monkeypatch, env, P.SEED), P.replay(*position))
        assert got == want[position], P.label(*position)
        assert got["record"]["policy"] == env["SHENGJI_BOT"]
        assert got["counters"]["unified_shared_hits"] == 1 == got["counters"]["unified_prior_calls"]
        for name in COUNTERS:
            totals[name] += got["counters"][name]
    assert totals["unified_value_rows"] > 0 and totals["unified_reply_rows"] > 0
    assert totals["unified_trunk_shared"] > 0
    for name in ("unified_shared_misses", "unified_value_other", "unified_reply_served",
                 "unified_trunk_forwards"):
        assert totals[name] == 0, name


def test_a_served_bot_decides_the_same_beside_a_unified_bot(release50_packages, pair, monkeypatch,
                                                           served_functions):
    """The wrappers a unified bot puts in front of the two served functions pass a served bot
    through: its decisions before and after they are in place are equal."""
    from shengji.train import unified_serving as serving

    positions = (("ADKY3", 9, 0), ("SDUS2", 8, 0), ("SDUS2", 14, 1))
    served_env = local_env(release50_packages, production_env())

    def served(position):
        bot = registry_bot(monkeypatch, served_env, P.SEED)
        assert bot.policy_name == RELEASE52 and "scores" not in vars(bot)
        out = P.decision(P.lift(bot), P.replay(*position))
        assert out["record"]["belief_fallback"] == 0, out["record"].get("belief_fallback_reason")
        return out
    before = {position: served(position) for position in positions}
    assert not serving.active()
    env = unified_env(release50_packages, pair)
    unified = registry_bot(monkeypatch, env, P.SEED)
    assert serving.active()
    assert decide(unified, P.replay(*positions[0]))["counters"]["unified_value_rows"] > 0
    for position in positions:
        assert served(position) == before[position], P.label(*position)


def test_the_unified_bot_acts_through_the_server_path(release50_packages, pair, tmp_path, monkeypatch,
                                                     served_functions):
    """Two consecutive bot turns through ``_paced_bot_step`` / ``_commit_bot_turn`` (each searches a
    deep copy of the room's bot, which then becomes the room's bot): both complete on the unified
    slots from one trunk forward, and play what a bot outside the server plays."""
    from shengji.ai import belief_numpy as bn
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from shengji.train import pv_search_policy as pv
    from test_pv_search_serving import _play_state

    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    env = unified_env(release50_packages, pair)
    name = env["SHENGJI_BOT"]
    rnd = _play_state()
    assert not rnd.trick.plays
    outside = P.lift(registry_bot(monkeypatch, env, seed=7))
    expected = []
    twin = copy.deepcopy(rnd)
    for _ in range(2):
        cards = outside.decide_play(twin, twin.turn)
        expected.append(sorted(cards))
        twin.play(twin.turn, list(cards))
    bot = P.lift(registry_bot(monkeypatch, env, seed=7))

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="UNIF", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        turns = []
        for _ in range(2):
            seat = rnd.turn
            prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
            assert prepared is not None
            searched = prepared.decision.snapshot.bot_copy
            assert searched is not bot and searched.policy_name == name
            before = {c: getattr(room.bot, c) for c in COUNTERS}
            turns.append((copy.deepcopy(searched.last_decision_record), sorted(prepared.decision.cards),
                          {c: getattr(searched, c) - before[c] for c in COUNTERS}))
            assert srv._commit_bot_turn(room, prepared)
            assert room.bot is searched
        return turns

    for (record, cards, counters), want in zip(asyncio.run(scenario()), expected):
        assert record["schema"] == pv.RECORD_SCHEMA and record["work_complete"]
        assert record["policy"] == name and record["belief_fallback"] == 0
        assert record["unified"] == {"package": pair["unified"][1][:8], "shared": 1, "missed": 0, "trunk": 0,
                                     "value_rows": counters["unified_value_rows"], "value_left": 0,
                                     "reply_rows": counters["unified_reply_rows"], "reply_left": 0}
        assert cards == want
        assert counters["unified_shared_hits"] == 1 and counters["unified_shared_misses"] == 0
        assert counters["unified_trunk_shared"] == 1 and counters["unified_trunk_forwards"] == 0
        assert counters["unified_value_rows"] > 0 and counters["unified_value_other"] == 0
        assert counters["unified_reply_rows"] > 0 and counters["unified_reply_served"] == 0


def test_discarded_server_snapshot_keeps_other_decision_caches_isolated(
        release50_packages, pair, tmp_path, monkeypatch, served_functions):
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from test_pv_search_serving import _play_state

    bot = P.lift(registry_bot(monkeypatch, unified_env(release50_packages, pair), seed=7))
    game = Game(random.Random(0))
    game.round = _play_state()
    room = srv.Room(code="COPY", game=game, bot=bot,
                    seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
    first = srv._snapshot_bot_turn(room, game.round.turn, "bot")
    second = srv._snapshot_bot_turn(room, game.round.turn, "bot")
    assert first is not None and second is not None
    result = srv._compute_bot_turn(first)
    assert result.cards
    # A speculative decision is discarded without committing its bot to the room.
    assert first.bot_copy.belief_model.shared
    assert copy.deepcopy(first.bot_copy).belief_model.shared == {}
    assert room.bot.belief_model.shared == {}
    assert second.bot_copy.belief_model.shared == {}
    for snapshot in (first, second):
        copied = snapshot.bot_copy
        assert copied.belief_model is not room.bot.belief_model
        assert copied.belief_model.w is room.bot.belief_model.w
        assert copied.belief_model.unified is copied.unified_prior_model is bot.unified_prior_model
        assert copied.evaluator.unified_bot is copied
    record = first.bot_copy.last_decision_record
    assert record["unified"]["shared"] == 1
    assert record["unified"]["missed"] == record["unified"]["trunk"] == 0


def fast_env(env) -> dict:
    """``env`` with the fast readout switched on and the name the registry derives for it."""
    from shengji.eval.served_config import registry_name
    from shengji.train import unified_serving as serving

    out = {**env, serving.FAST_KEY: "1"}
    out["SHENGJI_BOT"] = registry_name(out)
    return out


def test_the_fast_readout_switch_is_0_or_1_and_enters_the_name():
    from shengji.train import unified_serving as serving
    from shengji.train.pv_search_policy import PVSearchPolicyError

    assert serving.unified_fast({}) is False
    assert serving.unified_fast({serving.FAST_KEY: ""}) is False
    assert serving.unified_fast({serving.FAST_KEY: "0"}) is False
    assert serving.unified_fast({serving.FAST_KEY: "1"}) is True
    for raw in ("2", "true", " 1"):
        with pytest.raises(PVSearchPolicyError):
            serving.unified_fast({serving.FAST_KEY: raw})
    assert serving.unified_name("s", UNIFIED_SHA) == "s-ushare97c07be8-uvalue97c07be8-ureply97c07be8"
    assert serving.unified_name("s", UNIFIED_SHA, fast=True) == serving.unified_name("s", UNIFIED_SHA) + "-ufast"


def test_the_fused_stem_is_the_readout_stem(tmp_path):
    """`fused_stem` folds the pooled card states and the context into the stem: the value
    distribution and the reply log-odds equal `leaf_hidden`'s up to float32 rounding."""
    from shengji.ai import unified_readout_numpy as rn

    pair = _random_pair(tmp_path)
    model = rn.load_unified_readout_numpy(*pair["unified"])
    rng = np.random.default_rng(5)
    q = rng.standard_normal((54, TRUNK["d"])).astype(np.float32)
    g = np.abs(rng.standard_normal(TRUNK["x_hidden"])).astype(np.float32)
    cache = model.decision_cache(q, g)
    fused = model.fused_stem(cache)
    n = 37
    planes = ((rng.random((n, 9, 54)) < 0.2) * rng.integers(1, 3, (n, 9, 54))).astype(np.float32)
    scalars = rng.random((n, 12)).astype(np.float32)
    flat = planes.reshape(n, -1)
    np.testing.assert_allclose(model.leaf_value_probs_fused(fused, flat, scalars),
                               model.leaf_value_probs(cache, planes, scalars), rtol=0, atol=1e-6)
    np.testing.assert_allclose(model.leaf_reply_logits_fused(fused, flat, scalars),
                               model.leaf_reply_logits(cache, planes, scalars), rtol=0, atol=1e-4)
    assert model.leaf_reply_logits_fused(fused, flat[:0], scalars[:0]).shape == (0, 54)


def test_memo_rows_computes_each_new_key_once():
    from shengji.train import unified_slots as us

    calls = []

    def compute(rows):
        calls.append(list(rows))
        return [f"r{i}" for i in rows]
    memo = {}
    assert us.memo_rows(memo, [b"a", b"b", b"a"], compute) == (["r0", "r1", "r0"], 1)
    assert us.memo_rows(memo, [b"b", b"c", b"c"], compute) == (["r1", "r1", "r1"], 2)
    assert us.memo_rows(memo, [], compute) == ([], 0)
    assert calls == [[0, 1], [1]]


def test_the_fast_readout_decides_as_the_readout(release50_packages, pair, monkeypatch, served_functions):
    """Ten fixed production positions: with the fast readout the registry bot plays the cards the
    readout plays, on the same worlds and admitted candidates, with candidate values within float32
    rounding; every leaf's fast features are `leaf_features_batch`'s, and equal rows share a memo key."""
    from shengji.train import unified_slots as us

    env = unified_env(release50_packages, pair)
    fast = fast_env(env)
    assert fast["SHENGJI_BOT"] == env["SHENGJI_BOT"] + "-ufast"
    checked = [0, 0]
    features = us.leaf_features_fast

    def checked_features(frame, leaves):
        mine, planes, scalars, keys = features(frame, leaves)
        want_mine, want_planes, want_scalars = us.leaf_features_batch(frame, leaves)
        assert mine == want_mine
        assert np.array_equal(planes, want_planes.reshape(len(mine), -1)) and planes.dtype == np.float32
        assert np.array_equal(scalars, want_scalars)
        rows = {}
        for key, p, sc in zip(keys, planes, scalars):
            row = p.tobytes() + sc.tobytes()
            assert rows.setdefault(key, row) == row
        checked[0] += len(mine)
        checked[1] += len(mine) - len(set(keys))
        return mine, planes, scalars, keys
    monkeypatch.setattr(us, "leaf_features_fast", checked_features)
    memo = {"value_memo": 0, "reply_memo": 0}
    for position in P.POSITIONS:
        want = decide(registry_bot(monkeypatch, env, P.SEED), P.replay(*position))
        bot = registry_bot(monkeypatch, fast, P.SEED)
        assert bot.policy_name == fast["SHENGJI_BOT"] and bot.unified_fast
        got = decide(bot, P.replay(*position))
        assert got["cards"] == want["cards"], P.label(*position)
        assert got["worlds"] == want["worlds"], P.label(*position)
        assert got["counters"] == want["counters"], P.label(*position)
        g, w = got["record"], want["record"]
        assert g["policy"] == fast["SHENGJI_BOT"] and w["policy"] == env["SHENGJI_BOT"]
        assert g["admitted_indices"] == w["admitted_indices"] and g["selected_index"] == w["selected_index"]
        np.testing.assert_allclose(np.asarray(g["value_means"], float), np.asarray(w["value_means"], float),
                                   rtol=0, atol=1e-4, err_msg=P.label(*position))
        for name in memo:
            memo[name] += got["memo"][name]
    assert checked[0] > 0
    assert memo["value_memo"] > 0


def test_served_trajectory_capture_preserves_unified_decisions_and_labels(
        release50_packages, pair, monkeypatch, served_functions):
    """Capture wraps the registry bot without changing its search or losing training labels."""
    import json
    from collections import Counter
    from shengji.harvest import trajectory as tr

    env = unified_env(release50_packages, pair)
    registry = register(monkeypatch, env)
    config = tr.build_config(policy=env["SHENGJI_BOT"], seed0=0,
                             explore_rate=0, explore_k=0, round_mix="sampled",
                             capture_served_budget=True)
    assert config["served_budgets"]["play_seconds"] == 3
    assert config["served_budgets"]["bury_seconds"] == 2
    assert config["served_runtime"]["SHENGJI_PV_UNIFIED_SHA256"] == pair["unified"][1]
    assert config["served_runtime"]["SHENGJI_PV_BELIEF_SHA256"] == pair["belief"][1]
    for position in P.POSITIONS:
        expected = decide(registry.make_bot(env["SHENGJI_BOT"], seed=P.SEED), P.replay(*position))
        captured = tr.make_trajectory_bot(config, seed=P.SEED, explore_rng=random.Random(17))
        rnd = P.replay(*position)
        actual = decide(captured, rnd)
        assert actual == expected, P.label(*position)
        fields = tr._play_fields({}, config["run_id"], 0, 0, rnd, rnd.turn, [],
                                 captured.last_decision_record["played"], captured, 256, Counter())
        saved = json.loads(json.dumps(fields))
        record = captured.last_decision_record
        assert saved["allocation"]["serving_decision"] == record
        assert saved["action_values"]["means"] == record["value_means"]
        assert saved["action_values"]["policy_log_odds"] == record["policy_log_odds_admitted"]
        assert saved["ballot"][saved["allocation"]["played_index"]] == saved["action"]
        assert saved["allocation"]["serving_decision"]["unified"]["shared"] == 1
        assert saved["allocation"]["serving_decision"]["unified"]["missed"] == 0
