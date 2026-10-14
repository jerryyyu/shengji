"""The pv-search SOFT oracle diagnostics (#707 S17 step 3; `train.pv_soft_oracle`):
``oracle_mix_k`` (``SHENGJI_PV_ORACLE_MIX_K``, token ``orcm<k>``: k of the W
play worlds are the true deal, the rest production's draw) and
``oracle_pin_q`` (``SHENGJI_PV_ORACLE_PIN_Q``, token ``orcq<100 q>``: every
world is production's fill with a seeded fraction q of the hidden copies
pinned to their true holders), both behind #975's harness hook.

Witnesses:
(a) off: release 45's name, digest and payload are unchanged with the flags
unset, empty or ``0``, and a flag-off bot's every decision, record and sampler
state over self-play are those of main's verbatim `_worlds` / `_decide_play`
(`test_cwv_oracle_worlds.MainWorlds`);
(b) names: the tokens, the digest, the env reader's refusals, exclusivity;
(c) serving refuses: constructors and the registry factory without the hook
(before any package is read), the game server at import (a real subprocess);
(d) privacy: unbound, the bot raises `OracleWorldsError`, never a fallback;
(e) k-mix: at every decision exactly the k evenly spaced worlds are the true
deal and the other W - k are production's draw, at W = 64 for k = 1, 4, 16;
(f) q-pin: over many seeded states (refusals, voids, pair and run caps among
them) every world satisfies every constraint, the pinned copies sit with
their true holders, the realised fraction is round(q h) / h, and a failed
fill falls back to production's draw and is counted;
(g) telemetry: the record's ``oracle_*`` fields are scalars and survive the
screen trace (`search_screen.trace_fields`) whole;
(h) harness: the env reader, the build arguments, `make_side` on the real
tiny package, and the description.
"""
import copy
import os
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.mcbot import MCBot
from shengji.ai.memory import Memory
from shengji.ai.registry import REGISTRY, make_bot, register_pv_search_policies
from shengji.api import server as srv
from shengji.train import cwv_shortlist_screen as screen
from shengji.train import pv_search_policy as pv
from shengji.train import pv_soft_oracle as so
from shengji.train.pv_search_policy import RECORD_SCHEMA, OracleWorldsError, PVSearchPolicyError
from shengji.train.search_screen import trace_fields
from test_cwv_oracle_worlds import RELEASE44_PLAY_RULES, MainWorlds, true_deal
from test_pv_admission_rules import names, predict, production_package  # noqa: F401
from test_pv_declare_served_bury import RELEASE45, fly_env
from test_pv_search_serving import SMALL as SERVING_SMALL, _play_state, package  # noqa: F401
from test_pv_small_joker_lead import PointsEvaluator, _fresh_round, _strip

MIX = "SHENGJI_PV_ORACLE_MIX_K"
PIN = "SHENGJI_PV_ORACLE_PIN_Q"
HOOK = screen.oracle_true_deal
#: release 45 (fly.toml) with each soft arm of the S17 step-3 screen
RELEASE45_SOFT = {
    (MIX, "1"): "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-orcm1-rfddca910-bury-hybrid-bwv-147c200f2b6a",
    (MIX, "4"): "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-orcm4-r33285244-bury-hybrid-bwv-a17c1ec22f07",
    (MIX, "16"): "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-orcm16-red6eb981-bury-hybrid-bwv-00e109ae46c2",
    (PIN, "0.5"): "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-orcq50-r9ec4c89f-bury-hybrid-bwv-5d1a0f7132fa",
}
SELF_PLAY_SEEDS = tuple(range(716001, 716004))
#: release 45's play rules are release 44's (release 45 changed only the bury)
PLAY_RULES = RELEASE44_PLAY_RULES
#: production's sampler class attributes (`MCBot.DECLARER_PIN`) for a layout
SAMPLER = MCBot


def served(worlds=4, seed=17, budget=None, evaluator=None, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=worlds, candidates=8,
                               cap=4000, batch_size=128, serving_budget_seconds=budget, **rules)
    return pv.PVSearchBot(predict, evaluator=evaluator or PointsEvaluator(), version=2,
                          config=config, checkpoint="/dev/null", seed=seed)


def hooked(**kw):
    bot = served(**kw)
    bot.bind_oracle_deal(HOOK)
    return bot


def capture_scored(bot):
    log = []
    orig = bot._score_leaves

    def _score_leaves(rnd_, seat_, actions, worlds, *a, **kw):
        log.append([(list(map(list, hands)), list(buried)) for hands, buried in worlds])
        return orig(rnd_, seat_, actions, worlds, *a, **kw)
    bot._score_leaves = _score_leaves
    return log


# ------------------------------------------------------------ (a) off: identity

def test_release45_name_digest_and_payload_unchanged_when_off(production_package):
    env = fly_env()
    assert names(env) == [RELEASE45]
    for raw in ("", "0"):
        assert names({**env, MIX: raw}) == [RELEASE45]
        assert names({**env, PIN: raw}) == [RELEASE45]
    recipe = pv.pv_env_recipe(env)
    assert "oracle_mix_k" not in recipe and "oracle_pin_q" not in recipe
    config = pv.PVSearchConfig(checkpoint_sha256=recipe["sha256"], worlds=64, candidates=8,
                               cap=4000, batch_size=128, serving_budget_seconds=3.0,
                               value_declare=True, **PLAY_RULES)
    assert pv.recipe_digest(config) == "add86676"
    payload = pv.recipe_payload(config)
    assert not any(key.startswith("oracle") for key in payload)
    assert pv.PVSearchBot.oracle_mix_k == 0 and pv.PVSearchBot.oracle_pin_q == 0.0
    bot = served()
    assert "oracle_mix_k" not in vars(bot) and "oracle_pin_q" not in vars(bot)
    assert bot._soft_oracle is None and bot._soft_oracle_record() == {}


@pytest.mark.parametrize("budget", [None, 3.0], ids=["unbudgeted", "budgeted"])
def test_off_is_mains_decision_over_self_play(budget):
    decisions = 0
    for seed in SELF_PLAY_SEEDS:
        rnd = _fresh_round(seed)
        kw = dict(worlds=4, budget=budget, **PLAY_RULES)
        off = [served(seed=100 + s, **kw) for s in range(4)]
        main = [MainWorlds(predict, evaluator=PointsEvaluator(), version=2, config=off[s].config,
                           checkpoint="/dev/null", seed=100 + s) for s in range(4)]
        while rnd.phase == "play":
            seat = rnd.turn
            a = off[seat].decide_play(copy.deepcopy(rnd), seat)
            b = main[seat].decide_play(copy.deepcopy(rnd), seat)
            assert a == b
            rec = off[seat].last_decision_record
            assert _strip(rec) == _strip(main[seat].last_decision_record)
            assert rec["schema"] == RECORD_SCHEMA and not any(k.startswith("oracle") for k in rec)
            assert off[seat].sampler.rng.getstate() == main[seat].sampler.rng.getstate()
            decisions += 1
            rnd.play(seat, a)
    assert decisions >= 75


# ------------------------------------------------------------ (b) names

def test_tokens_digest_and_env_reader(production_package):
    env = fly_env()
    play = RELEASE45[:RELEASE45.index("-radd86676")]
    for k in (1, 4, 16):
        name, = names({**env, MIX: str(k)})
        assert name.startswith(f"{play}-orcm{k}-r") and "-bury-hybrid-bwv-" in name
        assert pv.pv_env_recipe({**env, MIX: str(k)})["oracle_mix_k"] == k
    name, = names({**env, PIN: "0.5"})
    assert name.startswith(f"{play}-orcq50-r")
    assert pv.pv_env_recipe({**env, PIN: "0.5"})["oracle_pin_q"] == 0.5
    for (flag, raw), name in RELEASE45_SOFT.items():
        assert names({**env, flag: raw}) == [name]
    base = dict(checkpoint_sha256="f" * 64, worlds=64)
    off = pv.PVSearchConfig(**base)
    digests = {pv.recipe_digest(off)}
    for kw in (dict(oracle_mix_k=1), dict(oracle_mix_k=4), dict(oracle_mix_k=16),
               dict(oracle_pin_q=0.5), dict(oracle_pin_q=0.25), dict(oracle_worlds=True)):
        digests.add(pv.recipe_digest(pv.PVSearchConfig(**base, **kw)))
    assert len(digests) == 7
    payload = pv.recipe_payload(pv.PVSearchConfig(**base, oracle_mix_k=16))
    assert payload["oracle_mix_k"] == 16 and payload["oracle_worlds_information"] == "true-deal-mix"
    assert "oracle_pin_q" not in payload
    payload = pv.recipe_payload(pv.PVSearchConfig(**base, oracle_pin_q=0.5))
    assert payload["oracle_pin_q"] == 0.5 and payload["oracle_pin_fill"] == so.PIN_FILL
    assert payload["oracle_worlds_information"] == "true-holder-pin" and "oracle_mix_k" not in payload
    for bad in ("x", "-1", "1.5"):
        with pytest.raises(PVSearchPolicyError, match=MIX):
            pv.pv_env_recipe({**env, MIX: bad})
    for bad in ("x", "1", "1.5", "0.555", "-0.5"):
        with pytest.raises(PVSearchPolicyError, match=PIN):
            pv.pv_env_recipe({**env, PIN: bad})
    with pytest.raises(PVSearchPolicyError, match="worlds - 1"):
        names({**env, MIX: "64"})


def test_exclusive_with_each_other_the_oracle_and_the_adaptive_rules():
    for kw in (dict(oracle_mix_k=4, oracle_pin_q=0.5), dict(oracle_mix_k=4, oracle_worlds=True),
               dict(oracle_pin_q=0.5, oracle_worlds=True),
               dict(oracle_mix_k=4, adaptive_worlds=True),
               dict(oracle_pin_q=0.5, adaptive_worlds_leads=True)):
        with pytest.raises(PVSearchPolicyError, match="exclusive"):
            pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, **kw))
        with pytest.raises(PVSearchPolicyError, match="exclusive"):
            served(worlds=8, **kw)
    for kw in (dict(oracle_mix_k=4), dict(oracle_mix_k=True), dict(oracle_pin_q="0.5"),
               dict(oracle_pin_q=1.0)):
        with pytest.raises(PVSearchPolicyError):
            served(worlds=4, **kw)


# ------------------------------------------------------------ (c) serving refuses

def test_constructors_refuse_without_the_hook_before_any_package_is_read(tmp_path):
    missing = str(tmp_path / "absent.npz")
    for kw in (dict(oracle_mix_k=4), dict(oracle_pin_q=0.5)):
        with pytest.raises(PVSearchPolicyError, match="never served"):
            pv.make_pv_search_bot(missing, sha256="f" * 64, **kw)
    assert not os.path.exists(missing)
    with pytest.raises(PVSearchPolicyError, match="rule off"):
        pv.make_pv_search_bot(missing, sha256="f" * 64, oracle_deal=HOOK)


@pytest.mark.parametrize("flag,raw", [(MIX, "16"), (PIN, "0.5")])
def test_registry_factory_refuses_the_servers_build(production_package, flag, raw):
    (name, factory), = pv.pv_registry_entries(**pv.pv_env_recipe({**fly_env(), flag: raw})).items()
    assert "-orc" in name
    with pytest.raises(PVSearchPolicyError, match="never served"):
        factory(seed=0)


@pytest.mark.parametrize("flag,raw", [(MIX, "16"), (PIN, "0.5")])
def test_game_server_refuses_the_flags_at_import(flag, raw):
    for off in (None, "", "0"):
        srv._refuse_pv_diagnostics({} if off is None else {flag: off})
    with pytest.raises(RuntimeError, match="never served"):
        srv._refuse_pv_diagnostics({flag: raw})
    env = {**os.environ, flag: raw}
    env.pop("SHENGJI_PV_CKPT", None)
    proc = subprocess.run([sys.executable, "-B", "-c", "import shengji.api.server"],
                          cwd=str(Path(__file__).parents[1]), env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode != 0
    assert flag in proc.stderr and "never served" in proc.stderr


# ------------------------------------------------------------ (d) privacy

@pytest.mark.parametrize("kw", [dict(oracle_mix_k=2), dict(oracle_pin_q=0.5)], ids=["mix", "pin"])
@pytest.mark.parametrize("budget", [None, 3.0], ids=["unbudgeted", "budgeted"])
def test_unbound_soft_oracle_refuses_and_never_falls_back(kw, budget):
    bot = served(budget=budget, **kw)
    rnd = _fresh_round(SELF_PLAY_SEEDS[0])
    before = bot.sampler.rng.getstate()
    with pytest.raises(OracleWorldsError, match="no harness hook"):
        bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    assert bot.last_decision_record is None and bot.sampler.rng.getstate() == before
    # a hook whose deal breaks the contract fails closed too
    bot.bind_oracle_deal(lambda r, s: (true_deal(r)[0][:3], true_deal(r)[1]))
    with pytest.raises(OracleWorldsError):
        bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    assert bot.last_decision_record is None


# ------------------------------------------------------------ (e) k-mix

@pytest.mark.parametrize("k", [1, 4, 16])
def test_k_mix_scores_exactly_k_true_worlds_among_production_draws(k):
    worlds = 64
    decisions = 0
    rnd = _fresh_round(SELF_PLAY_SEEDS[k % len(SELF_PLAY_SEEDS)])
    bots, logs, draws = [], [], []
    for s in range(4):
        bot = hooked(worlds=worlds, seed=100 + s, oracle_mix_k=k, **PLAY_RULES)
        logs.append(capture_scored(bot))
        drawn = []
        orig = bot._production_draw

        def _production_draw(*a, _orig=orig, _drawn=drawn, **kw):
            got = _orig(*a, **kw)
            _drawn.append([(list(map(list, h)), list(b)) for h, b in got[0]])
            return got
        bot._production_draw = _production_draw
        bots.append(bot)
        draws.append(drawn)
    positions = so.mix_positions(k, worlds)
    assert len(positions) == k and positions[0] == 0
    while rnd.phase == "play":
        seat = rnd.turn
        n_scored, n_drawn = len(logs[seat]), len(draws[seat])
        played = bots[seat].decide_play(copy.deepcopy(rnd), seat)
        rec = bots[seat].last_decision_record
        assert rec["schema"] == RECORD_SCHEMA and rec["worlds"] == worlds
        scored, = logs[seat][n_scored:]
        drawn, = draws[seat][n_drawn:]
        truth = list(true_deal(rnd))
        assert len(scored) == worlds and len(drawn) == worlds - k
        assert all(list(scored[i]) == truth for i in positions)
        assert [w for i, w in enumerate(scored) if i not in positions] == drawn
        true_count = sum(list(w) == truth for w in scored)
        assert true_count >= k and rec["oracle_true_worlds"] == true_count
        assert rec["oracle_mix_k"] == k and rec["oracle_pinned_copies"] == 0
        assert rec["oracle_pin_fallback_worlds"] == 0
        assert 0.0 <= rec["oracle_card_agreement"] <= 1.0
        decisions += 1
        rnd.play(seat, played)
    assert decisions >= 25


# ------------------------------------------------------------ (f) q-pin

def _states(seeds, throw=0.0):
    """Every play-phase state of heuristic self-play rounds.  With ``throw``,
    that fraction of leads instead attempts the leader's whole holding of one
    suit of three or more cards (the engine refuses most: failed-throw
    notices, so the refusal constraints are exercised)."""
    h = HeuristicBot()
    for seed in seeds:
        rnd = _fresh_round(seed)
        rng = random.Random(seed)
        while rnd.phase == "play":
            yield seed, rnd
            seat = rnd.turn
            play = None
            if throw and (rnd.trick is None or not rnd.trick.plays) and rng.random() < throw:
                by_suit = {}
                for card in rnd.hands[seat]:
                    by_suit.setdefault(rnd.ordering.eff_suit(card), []).append(card)
                long = sorted(u for u, cards in by_suit.items() if len(cards) >= 3)
                if long:
                    play = by_suit[rng.choice(long)]
            rnd.play(seat, play if play is not None else h.decide_play(rnd, seat))


def _violations_of_truth(rnd, seat, refusals):
    """The true deal through the validator, with production's public pins
    (declared cards and the unplayed cards of each refused throw)."""
    from shengji.ai.refusal import pin_unplayed_attempt
    hands, buried = true_deal(rnd)
    mem = Memory(rnd, seat, own_kitty=True)
    for refusal in refusals:
        pin_unplayed_attempt(mem, rnd, refusal, seat)
    layout = so.hidden_layout(SAMPLER, rnd, seat, mem, hands, buried)
    return so.world_violations(rnd, seat, mem, layout, hands, buried, refusals), mem, layout


def test_q_pin_worlds_respect_every_constraint_over_many_seeded_states():
    q, worlds = 0.5, 8
    seeds = range(717001, 717041)
    bots = {}
    coverage = Counter()
    checked = 0
    for seed, rnd in _states(seeds, throw=0.15):
        seat = rnd.turn
        bot = bots.get((seed, seat))
        if bot is None:
            bot = bots[(seed, seat)] = hooked(worlds=worlds, seed=seed * 4 + seat,
                                              oracle_pin_q=q, refusal_event_complete=True,
                                              **PLAY_RULES)
        for other in range(4):
            if (seed, other) in bots:
                bots[(seed, other)].observe_public(rnd)
        worlds_out, _attempts = bot._worlds(rnd, seat)
        rec = bot._soft_oracle
        refusals = bot._refusals.observe(rnd)
        bad, mem, layout = _violations_of_truth(rnd, seat, refusals)
        assert bad == []                                   # the truth is valid (a sound validator)
        hidden = layout.hidden
        want = so.pin_count(q, hidden)
        assert rec["oracle_hidden_copies"] == hidden
        assert rec["oracle_pinned_copies"] == want * (worlds - rec["oracle_pin_fallback_worlds"])
        if hidden:
            assert rec["oracle_pin_fraction"] == pytest.approx(
                want * (worlds - rec["oracle_pin_fallback_worlds"]) / (hidden * worlds))
        fallback_at = set(bot._soft_oracle_drawn_at)
        assert len(fallback_at) == rec["oracle_pin_fallback_worlds"]
        for index, (hands, buried) in enumerate(worlds_out):
            if index in fallback_at:
                # production's own draw (its refusal-aware sampler, which itself
                # falls back to a plain draw at its attempt cap): voids only
                kinds = {v[0] for v in so.world_violations(rnd, seat, mem, layout, hands,
                                                           buried, refusals)}
                assert "void" not in kinds
                continue
            assert so.world_violations(rnd, seat, mem, layout, hands, buried, refusals) == []
            matched, _ = so.agreement(layout, hands, buried)
            assert matched >= want
        coverage["states"] += 1
        coverage["refusal_states"] += bool(refusals)
        coverage["void_states"] += any(mem.voids[s] for s in range(4) if s != seat)
        coverage["pair_cap_states"] += any(
            mem.pair_cap[s] for s in range(4) if s != seat)
        coverage["run_cap_states"] += any(
            mem.run_cap[s] for s in range(4) if s != seat)
        coverage["fallback_worlds"] += rec["oracle_pin_fallback_worlds"]
        coverage["rejections"] += rec["oracle_pin_rejections"]
        checked += len(worlds_out)
    print(f"\nq-pin coverage: {dict(coverage)} worlds={checked}")
    assert coverage["states"] >= 400 and coverage["void_states"] >= 100
    assert coverage["pair_cap_states"] >= 20 and coverage["refusal_states"] >= 100
    assert coverage["run_cap_states"] >= 1
    # fallbacks are rare, not routine: the fill works on real states
    assert coverage["fallback_worlds"] <= 0.01 * checked


def test_q_pin_pinned_copies_sit_with_their_true_holders():
    q = 0.5
    rnd = _fresh_round(SELF_PLAY_SEEDS[1])
    seat = rnd.turn
    hands, buried = true_deal(rnd)
    bot = hooked(worlds=4, oracle_pin_q=q, **PLAY_RULES)
    mem = Memory(rnd, seat, own_kitty=True)
    layout = so.hidden_layout(bot.sampler, rnd, seat, mem, hands, buried)
    want = so.pin_count(q, layout.hidden)
    for trial in range(30):
        rng = random.Random(trial)
        pins = [layout.truth[i] for i in sorted(rng.sample(range(layout.hidden), want))]
        got = so.pinned_fill(bot.sampler, rnd, mem, layout, pins)
        assert got is not None
        world, kitty = got
        for receiver, cards in _by_receiver(pins).items():
            held = Counter(kitty) if receiver == "kitty" else Counter(world[receiver])
            assert not (cards - held)
        complete = bot.sampler._complete_determinized_hands(rnd, seat, world, buried=kitty)
        assert so.world_violations(rnd, seat, mem, layout, complete, kitty) == []
    # q = 0 pins nothing; pinning everything reproduces the truth
    full = so.pinned_fill(bot.sampler, rnd, mem, layout, list(layout.truth))
    complete = bot.sampler._complete_determinized_hands(rnd, seat, full[0], buried=full[1])
    assert so.agreement(layout, complete, full[1]) == (layout.hidden, True)


def _by_receiver(pins):
    out = {}
    for card, receiver in pins:
        out.setdefault(receiver, Counter())[card] += 1
    return out


def test_validator_catches_each_broken_constraint():
    """`world_violations` is not vacuous: a void, a pair cap, a public pin and
    a known kitty broken on purpose are each reported."""
    found = Counter()
    for seed, rnd in _states(range(717001, 717011)):
        seat = rnd.turn
        bad, mem, layout = _violations_of_truth(rnd, seat, ())
        assert bad == []
        hands, buried = true_deal(rnd)
        o = rnd.ordering
        for s in layout.others:
            for u in mem.voids[s]:
                # swap one card of the void suit held by another seat into s
                donor = next(((t, c) for t in layout.others if t != s for c in hands[t]
                              if o.eff_suit(c) == u), None)
                if donor is None or not hands[s]:
                    continue
                t, c = donor
                broken = [list(h) for h in hands]
                d = broken[s].pop()
                broken[s].append(c)
                broken[t].remove(c)
                broken[t].append(d)
                kinds = {v[0] for v in so.world_violations(rnd, seat, mem, layout, broken, buried)}
                assert "void" in kinds
                found["void"] += 1
                break
            if layout.pre[s]:
                broken = [list(h) for h in hands]
                code = layout.pre[s][0]
                t, other = next((t, c) for t in layout.others if t != s
                                for c in broken[t] if c != code)
                broken[s].remove(code)
                broken[t].remove(other)
                broken[s].append(other)
                broken[t].append(code)
                kinds = {v[0] for v in so.world_violations(rnd, seat, mem, layout, broken, buried)}
                assert "public_pin" in kinds
                found["public_pin"] += 1
        s = layout.others[0]
        if not layout.kitty_slots and hands[s] and buried:
            broken_kitty = [hands[s][0]] + list(buried[1:])
            kinds = {v[0] for v in so.world_violations(rnd, seat, mem, layout, hands, broken_kitty)}
            assert "known_kitty" in kinds
            found["known_kitty"] += 1
    assert found["void"] >= 20 and found["known_kitty"] >= 5
    # a pair cap of 0 against a hand holding a pair
    rnd = _fresh_round(SELF_PLAY_SEEDS[0])
    seat = rnd.turn
    hands, buried = true_deal(rnd)
    mem = Memory(rnd, seat, own_kitty=True)
    layout = so.hidden_layout(SAMPLER, rnd, seat, mem, hands, buried)
    for s in layout.others:
        pair = next((c for c, n in Counter(hands[s]).items() if n >= 2), None)
        if pair is not None:
            u = rnd.ordering.eff_suit(pair)
            mem.max_pairs = lambda seat_, suit, _s=s, _u=u: 0 if (seat_, suit) == (_s, _u) else None
            kinds = {v[0] for v in so.world_violations(rnd, seat, mem, layout, hands, buried)}
            assert "pair_cap" in kinds
            break
    else:
        pytest.fail("no pair in the fixture deal")


@pytest.mark.parametrize("budget", [None, 3.0], ids=["unbudgeted", "budgeted"])
def test_q_pin_failed_fill_falls_back_to_production_and_is_counted(monkeypatch, budget):
    rnd = _fresh_round(SELF_PLAY_SEEDS[2])
    seat = rnd.turn
    bot = hooked(worlds=8, budget=budget, oracle_pin_q=0.5, **PLAY_RULES)
    monkeypatch.setattr(so, "pinned_fill", lambda *a, **k: None)
    bot.decide_play(copy.deepcopy(rnd), seat)
    rec = bot.last_decision_record
    assert rec["schema"] == RECORD_SCHEMA and rec["worlds"] == 8
    assert rec["oracle_pin_fallback_worlds"] == 8 and rec["oracle_pinned_copies"] == 0
    assert rec["oracle_pin_fills"] == 8 * so.PIN_FILL_ATTEMPTS
    assert rec["oracle_pin_fraction"] == 0.0
    # a constraint rejection is retried, then counted the same way
    monkeypatch.undo()
    calls = Counter()
    real = so.world_violations

    def reject_first(*a, **k):
        calls["n"] += 1
        return [("void", 0, "X")] if calls["n"] % 2 else real(*a, **k)
    monkeypatch.setattr(so, "world_violations", reject_first)
    bot2 = hooked(worlds=8, budget=budget, oracle_pin_q=0.5, **PLAY_RULES)
    bot2.decide_play(copy.deepcopy(rnd), seat)
    rec = bot2.last_decision_record
    assert rec["oracle_pin_rejections"] >= 8 and rec["oracle_pin_fallback_worlds"] == 0


def test_q_pin_self_play_is_seeded_and_records_the_realised_fraction():
    def run():
        out = []
        rnd = _fresh_round(SELF_PLAY_SEEDS[0])
        bots = [hooked(worlds=16, seed=100 + s, oracle_pin_q=0.5, **PLAY_RULES) for s in range(4)]
        while rnd.phase == "play":
            seat = rnd.turn
            played = bots[seat].decide_play(copy.deepcopy(rnd), seat)
            rec = bots[seat].last_decision_record
            hidden = rec["oracle_hidden_copies"]
            if hidden:
                assert rec["oracle_pin_fraction"] == pytest.approx(
                    so.pin_count(0.5, hidden) * (16 - rec["oracle_pin_fallback_worlds"])
                    / (16 * hidden))
                assert abs(rec["oracle_pin_fraction"] - 0.5) <= 0.5 / hidden + 1e-9 \
                    or rec["oracle_pin_fallback_worlds"]
            out.append((played, _strip(rec)))
            rnd.play(seat, played)
        return out
    first = run()
    assert first == run() and len(first) >= 25


# ------------------------------------------------------------ (g) telemetry

def test_telemetry_is_scalar_and_survives_the_screen_trace():
    rnd = _fresh_round(SELF_PLAY_SEEDS[0])
    for kw in (dict(oracle_mix_k=2), dict(oracle_pin_q=0.5)):
        bot = hooked(**kw, **PLAY_RULES)
        bot.decide_play(copy.deepcopy(rnd), rnd.turn)
        rec = bot.last_decision_record
        soft = {k: v for k, v in rec.items() if k.startswith("oracle_")}
        assert set(soft) == {"oracle_mix_k", "oracle_pin_q", "oracle_hidden_copies",
                             "oracle_true_worlds", "oracle_card_agreement",
                             "oracle_pinned_copies", "oracle_pin_fraction",
                             "oracle_pin_fallback_worlds", "oracle_pin_fills",
                             "oracle_pin_rejections"}
        assert all(isinstance(v, (int, float)) for v in soft.values())
        trace = trace_fields(rec, skip=("played",))
        assert {k: trace[k] for k in soft} == soft


# ------------------------------------------------------------ (h) the harness

def test_harness_reads_the_soft_flags():
    assert screen.oracle_soft_requested({}) == {}
    for raw in ("", "0"):
        assert screen.oracle_soft_requested({MIX: raw, PIN: raw}) == {}
    assert screen.oracle_soft_requested({MIX: "16"}) == {"oracle_mix_k": 16}
    assert screen.oracle_soft_requested({PIN: "0.5"}) == {"oracle_pin_q": 0.5}
    for env in ({MIX: "x"}, {PIN: "1.0"}):
        with pytest.raises(ValueError):
            screen.oracle_soft_requested(env)
    assert screen._arm_policy_kwargs({"oracle_mix_k": 4}) == {"oracle_deal": HOOK}
    assert screen._arm_policy_kwargs({"oracle_pin_q": 0.5}) == {"oracle_deal": HOOK}
    assert screen._arm_policy_kwargs({"oracle_mix_k": 0}) == {}
    identity = {"bot_class": "PVSearchBuryBot"}
    for key, value, words in (("oracle_mix_k", 16, "16 of the worlds"),
                              ("oracle_pin_q", 0.5, "0.5 of the hidden copies")):
        text = screen._arm_description({"arm": "policy", "arm_policy": "x",
                                        "arm_policy_identity": identity, key: value})
        assert text.startswith("DIAGNOSTIC") and words in text and "never served" in text


@pytest.fixture
def soft_registered(package):
    path, sha = package
    mix = register_pv_search_policies(path, sha256=sha, oracle_mix_k=1, **SERVING_SMALL)
    pin = register_pv_search_policies(path, sha256=sha, oracle_pin_q=0.5, **SERVING_SMALL)
    try:
        yield mix[0], pin[0]
    finally:
        for name in mix + pin:
            REGISTRY.pop(name, None)


def test_make_side_builds_the_soft_arms_with_the_hook(soft_registered):
    for name, key, value in zip(soft_registered, ("oracle_mix_k", "oracle_pin_q"), (1, 0.5)):
        assert ("-orcm1-" if key == "oracle_mix_k" else "-orcq50-") in name
        with pytest.raises(PVSearchPolicyError, match="never served"):
            make_bot(name, seed=5)
        config = {"arm": "policy", "arm_policy": name, key: value}
        probe = make_bot(name, seed=0, **screen._arm_policy_kwargs(config))
        config["arm_policy_identity"] = screen._policy_identity(probe)
        assert config["arm_policy_identity"]["config"][key] == value
        bot = screen.make_side(config, "arm", 3)
        assert bot._oracle_deal is HOOK and getattr(bot, key) == value
        rnd = _play_state()
        bot.decide_play(copy.deepcopy(rnd), rnd.turn)
        rec = bot.last_decision_record
        assert rec["schema"] == RECORD_SCHEMA and rec["worlds"] == SERVING_SMALL["worlds"]
        assert rec[key] == value
        with pytest.raises(PVSearchPolicyError, match="never served"):
            screen.make_side({**config, key: 0}, "arm", 3)
