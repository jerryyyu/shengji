"""S112 offline DEV: score base / B1a / importance-sampled teacher worlds against the true deal.

Imports the shengji tree (the read-only worktree) for every sampler, encoder, legal listing and the
soft oracle's layout/agreement; nothing here re-implements a sampler.
"""
from __future__ import annotations

import hashlib
import math
import os
import random
import sys
import time
import tomllib
from collections import Counter
from pathlib import Path

WT = Path("/Users/jerryyu/Projects/shengji-wt/claude-pl1-r51")
ROOT = Path("/Users/jerryyu/shengji-archive/2026-11-06-s113-belief-teacher-b1a")
MODELS = ROOT / "models"
PKG_SHA = {
    "g3a-e04-f4f4127e.npz": "f4f4127ec0c8821b4aa07f7d651a4258c696f97a874707da2c78ad26c0c9b9fd",
    "p0-ft1-1fa201b2.npz": "1fa201b288e78b3072979f55030aae44711ee214b50a14e155d0bbe11b6bb1bf",
    "b1a-028131a0.npz": "028131a03de0c69b5164cdd0f65369950340f58fe226f75d6d877aeda2ca8fc8",
}
# bceil's arm C strip (arms/words.sh EXC, the non-package words): empty value removes the key
EXC_STRIP = ("SHENGJI_PV_BELIEF_CKPT", "SHENGJI_PV_BELIEF_SHA256", "SHENGJI_PV_BURY_BELIEF_WORLDS",
             "SHENGJI_PV_EXACT_LEAD_ENDGAME", "SHENGJI_PV_DOOMED_THROW_RESELECT_EXACT_GUARD",
             "SHENGJI_PV_EXACT_DEEP_CARDS", "SHENGJI_PV_WORLD_HISTORY_LEGAL", "SHENGJI_PV_WORLD_HISTORY_DRAW",
             "SHENGJI_PV_BELIEF_WORLDS")
WORLDS = 64


def served_env() -> dict:
    """fly.toml's [env] SHENGJI_PV_* / SHENGJI_FAST / SHENGJI_BOT with /data/models mapped to MODELS
    (scripts/y_trajectory.recipe_environment's selection)."""
    env = tomllib.loads((WT / "fly.toml").read_text())["env"]
    sel = {k: str(v) for k, v in env.items()
           if k.startswith("SHENGJI_PV_") or k in ("SHENGJI_FAST", "SHENGJI_REQUIRE_VOIDS", "SHENGJI_BOT")}
    for k, v in list(sel.items()):
        if k.endswith("_CKPT"):
            sel[k] = str(MODELS / Path(v).name)
    assert sel["SHENGJI_PV_LEAD_CONFIRM"] == "0" and sel["SHENGJI_PV_WORLDS"] == "64"
    return sel


def setup_process():
    for k in list(os.environ):
        if k.startswith("SHENGJI_"):
            del os.environ[k]
    os.environ.update(served_env())
    for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[k] = "1"
    if str(WT / "server") not in sys.path:
        sys.path.insert(0, str(WT / "server"))


def verify_packages():
    out = {}
    for name, sha in PKG_SHA.items():
        got = hashlib.sha256((MODELS / name).read_bytes()).hexdigest()
        if got != sha or not sha.startswith(name.rsplit("-", 1)[1].split(".")[0]):
            raise SystemExit(f"package {name}: sha {got} != {sha}")
        out[name] = got
    return out


class Bots:
    """The served R51 bot (B1a worlds, the prior) and bceil's arm C bot (base worlds)."""

    def __init__(self, seed=0):
        from shengji.ai import registry
        from shengji.train.pv_search_policy import pv_env_recipe, singleton_registry_entries
        name = os.environ["SHENGJI_BOT"]
        if name not in registry.REGISTRY:
            raise SystemExit(f"served name drift: {name}")
        self.r51 = registry.make_bot(name, seed=seed)
        env = dict(os.environ)
        for k in EXC_STRIP:
            env.pop(k, None)
        recipe = pv_env_recipe(env)
        entries = singleton_registry_entries(checkpoint=recipe.pop("checkpoint"), **recipe)
        names = sorted(n for n in entries if n.endswith("-sc8"))
        self.c_name = names[0]
        self.c = entries[self.c_name](seed=seed)
        c, r = self.c, self.r51
        assert r.belief_worlds and r.world_history_legal and r.refusal_constraints and r.worlds == WORLDS
        assert not c.belief_worlds and not c.world_history_legal and c.refusal_constraints and c.worlds == WORLDS
        assert not c._oracle_on() and not r._oracle_on()

        # bceil's q-pin arms P / Q / R (C + SHENGJI_PV_ORACLE_PIN_Q), bound to the screen harness's true-deal hook
        from shengji.train.cwv_shortlist_screen import oracle_true_deal
        self.qpin = {}
        for q in ("0.25", "0.5", "0.75"):
            envq = dict(env)
            envq["SHENGJI_PV_ORACLE_PIN_Q"] = q
            rq = pv_env_recipe(envq)
            eq = singleton_registry_entries(checkpoint=rq.pop("checkpoint"), **rq)
            nq = sorted(n for n in eq if n.endswith("-sc8"))[0]
            bot = eq[nq](seed=seed, oracle_deal=oracle_true_deal)
            assert abs(bot.oracle_pin_q - float(q)) < 1e-12 and not bot.belief_worlds
            self.qpin[q] = bot

    def all(self):
        return [self.r51, self.c, *self.qpin.values()]

    def reseed(self, seed):
        self.r51.sampler.rng = random.Random(f"s112|r51|{seed}")
        self.c.sampler.rng = random.Random(f"s112|base|{seed}")
        for q, bot in self.qpin.items():
            bot.sampler.rng = random.Random(f"s112|qpin{q}|{seed}")


def replay_round(rec, attempts=None, observers=(), states=None):
    """The decision state of ``rec`` through `harvest.rebuild.round_from_setup`, replaying each past play;
    a failed throw (``attempts[str(t)]``, the record's submitted action at ply t) is replayed as attempted so
    the engine downgrades it and posts its public notice, and every observer (a bot's refusal ledger) reads
    the round after each play, as the served bot's ledger does. ``states``, when a list, receives
    (t, seat, chosen cards, deep copy of the state before play t)."""
    import copy
    from shengji.harvest.rebuild import round_from_setup
    attempts = attempts or {}
    rnd = round_from_setup(rec["deck"], rec["setup"])
    for ob in observers:
        ob.observe(rnd)
    for t, play in enumerate(rec["plays_prefix"]):
        seat = int(play["seat"])
        chosen = list(attempts.get(str(t), play["cards"]))
        if states is not None:
            states.append((t, seat, chosen, copy.deepcopy(rnd)))
        before = len(rnd.history)
        rnd.play(seat, chosen)
        got = (rnd.history[before].plays if len(rnd.history) > before else rnd.trick.plays)[-1] \
            if (len(rnd.history) > before or rnd.trick.plays) else None
        if got is None or got.seat != seat or sorted(got.cards) != sorted(play["cards"]):
            raise ValueError(f"replay drift at play {t}")
        for ob in observers:
            ob.observe(rnd)
    if rnd.turn != rec["seat"]:
        raise ValueError("turn mismatch")
    return rnd


def point_round(rec, attempts=None, bots=None):
    observers = []
    if bots is not None:
        for bot in bots.all():
            bot._refusals.key = None          # a fresh ledger for this point
            observers.append(bot._refusals)
    return replay_round(rec, attempts, observers)


def layout_for(bots, rnd, seat):
    from shengji.ai.memory import Memory
    from shengji.train import pv_soft_oracle as SOFT
    mem = Memory(rnd, seat, own_kitty=getattr(bots.c.sampler, "BANKER_KITTY", True))
    return SOFT.hidden_layout(bots.c.sampler, rnd, seat, mem, rnd.hands, rnd.buried)


def world_acc(layout, worlds, weights=None):
    """Per-point acc: mean over worlds (optionally weighted) of matched hidden copies / hidden."""
    from shengji.train import pv_soft_oracle as SOFT
    if not layout.hidden:
        return None
    vals = [SOFT.agreement(layout, h, b)[0] / layout.hidden for h, b in worlds]
    if weights is None:
        return sum(vals) / len(vals)
    return sum(w * v for w, v in zip(weights, vals)) / sum(weights)


def draw(bot, rnd, seat, n):
    old = bot.worlds
    bot.worlds = n
    try:
        worlds, _ = bot._worlds(rnd, seat)
    finally:
        bot.worlds = old
    return [([list(h) for h in hands], sorted(b)) for hands, b in worlds]


def past_states(rec, attempts=None):
    """[(t, seat_t, chosen cards_t, rnd_t)] for every past card play (the attempted throw for a failed one;
    rnd_t = the state just before play t)."""
    out = []
    replay_round(rec, attempts, (), out)
    return out


def _listing_arrays(actions):
    import numpy as np
    from shengji.train.policy_prior import CARD_INDEX
    cards = np.fromiter((CARD_INDEX[c] for a in actions for c in a), dtype=np.int64)
    offsets = np.zeros(len(actions) + 1, dtype=np.int64)
    np.cumsum([len(a) for a in actions], out=offsets[1:])
    return cards, offsets


def lead_logsumexp(hand, ordering, lg):
    """log sum over EVERY legal lead (each non-empty sub-multiset of one effective-suit group of the hand,
    `harvest.legal.count_lead_actions`'s set) of exp(sum of its cards' log-odds), in closed form:
    per group prod_code(sum_{k=0..count} e^{k l_code}) - 1 (the empty set), groups summed."""
    from shengji.harvest.legal import _lead_groups
    from shengji.train.policy_prior import CARD_INDEX
    terms = []
    for _suit, cards in _lead_groups(list(hand), ordering):
        cnt = Counter(cards)
        logs = []
        for code, c in cnt.items():
            l = float(lg[CARD_INDEX[code]])
            logs.append(_lse([k * l for k in range(c + 1)]))
        tot = sum(logs)                      # log prod
        terms.append(tot + math.log1p(-math.exp(-tot)) if tot > 1e-12 else _log_expm1_small(tot, logs))
    return _lse(terms)


def _lse(xs):
    m = max(xs)
    return m + math.log(sum(math.exp(x - m) for x in xs))


def _log_expm1_small(tot, logs):
    # log(exp(tot) - 1) for tot near 0 or negative: tot is a log of a product of factors each >= 1, so tot >= 0;
    # tot == 0 only if every factor is 1, impossible (a factor is 1 + e^l + ...) -- guard anyway
    return math.log(math.expm1(tot)) if tot > 0 else -math.inf


def teacher_loglik(bots, rec, rnd, seat, cands, states=None, cap=None, timing=None, attempts=None):
    """Per candidate world: sum over past card plays t by seats != seat of
    log softmax_{legal plays of that seat at t}(prior card-logit sums)[played action], the prior being the
    served release 51 prior (p0-ft1-1fa201b2, `PVSearchBot.predict`, rows from `pv_encode_prefix.reply_rows`
    = `flat_input(root_tensors(root_clone(rnd_t, world_t)))`), action logit = sum of its cards' log-odds
    (`PVSearchBot.scores`), legal set = `harvest.legal.enumerate_legal` capped at the served cap (the
    native follow listing where the compiled module is present; same actions), the played action forced in.
    -inf when the played action is illegal under the candidate's hypothesized hand at t."""
    import numpy as np
    from shengji.harvest import legal as HL
    from shengji.train import pv_native
    from shengji.train.cwv_prior_admission import root_clone
    from shengji.train.pv_encode_prefix import HistoryPrefix, reply_rows
    from shengji.train.policy_prior import CARD_INDEX
    r = bots.r51
    cap = r.cap if cap is None else cap
    states = past_states(rec, attempts) if states is None else states
    prefix = rec["plays_prefix"]
    n = len(cands)
    ll = np.zeros(n, dtype=np.float64)
    plays_from = [[Counter() for _ in range(4)] for _ in range(len(prefix) + 1)]
    for t in range(len(prefix) - 1, -1, -1):
        plays_from[t] = [Counter(c) for c in plays_from[t + 1]]
        plays_from[t][int(prefix[t]["seat"])].update(prefix[t]["cards"])
    nlegal = 0
    tm = timing if timing is not None else Counter()
    for t, s, cards, rnd_t in states:
        if s == seat:
            continue
        t0 = time.perf_counter()
        add = [list(plays_from[t][q].elements()) for q in range(4)]
        alive = [i for i in range(n) if np.isfinite(ll[i])]
        clones = []
        for i in alive:
            hands, buried = cands[i]
            clones.append(root_clone(rnd_t, [list(hands[q]) + add[q] for q in range(4)], buried))
        played = tuple(sorted(cards))
        pidx = [CARD_INDEX[c] for c in played]
        ok = [HL.is_legal(c, s, list(played)) for c in clones]
        keep = [k for k, good in enumerate(ok) if good]
        for k, good in enumerate(ok):
            if not good:
                ll[alive[k]] = -math.inf
        t1 = time.perf_counter(); tm["clone_legal"] += t1 - t0
        if not keep:
            continue
        clones = [clones[k] for k in keep]
        idx = [alive[k] for k in keep]
        pre = HistoryPrefix.of(rnd_t, batched=r.encode_batch_fast, native=r.encode_native)
        rows = reply_rows(clones, s, r.version, pre)
        logits = np.asarray(r.predict(np.stack(rows).astype(np.float32)), dtype=np.float64)
        t2 = time.perf_counter(); tm["encode_predict"] += t2 - t1
        lead = rnd_t.trick.plays[0].cards if rnd_t.trick is not None and rnd_t.trick.plays else None
        cache = {}
        for j, clone in enumerate(clones):
            hand = clone.hands[s]
            lg = logits[j]
            if lead is None:
                lse = lead_logsumexp(hand, clone.ordering, lg)
                nlegal += 1
            else:
                key = tuple(sorted(hand))
                got = cache.get(key)
                if got is None:
                    listing = pv_native.follow_listing(list(hand), list(lead), clone.ordering, None)
                    if listing is None:
                        got = _listing_arrays(HL.enumerate_legal(clone, s, cap=None).actions)
                    else:
                        got = (np.asarray(listing[0], dtype=np.int64), np.asarray(listing[1], dtype=np.int64))
                    cache[key] = got
                cidx, off = got
                nlegal += len(off) - 1
                sums = np.add.reduceat(lg[cidx], off[:-1])
                m = sums.max()
                lse = m + math.log(np.exp(sums - m).sum())
            ll[idx[j]] += lg[pidx].sum() - lse
        tm["listing_softmax"] += time.perf_counter() - t2
    return ll, nlegal


def q_eff(acc_m, acc_base):
    return (acc_m - acc_base) / (1.0 - acc_base)


def ess(logw):
    import numpy as np
    logw = np.asarray(logw, dtype=np.float64)
    fin = np.isfinite(logw)
    if not fin.any():
        return 0.0
    w = np.exp(logw[fin] - logw[fin].max())
    return float(w.sum() ** 2 / (w ** 2).sum())


def resample(logw, k, rng):
    """k indices drawn with replacement in proportion to exp(logw) (multinomial)."""
    import numpy as np
    logw = np.asarray(logw, dtype=np.float64)
    fin = np.isfinite(logw)
    if not fin.any():
        raise ValueError("every candidate has zero likelihood")
    w = np.where(fin, np.exp(np.where(fin, logw, 0.0) - logw[fin].max()), 0.0)
    p = w / w.sum()
    return [int(i) for i in rng.choice(len(p), size=k, replace=True, p=p)]


def public_violations(rnd, seat, layout, hands, buried, bots, refusals=()):
    """Every public-information constraint a world (four hands + kitty) breaks: the soft oracle's
    `world_violations` (sizes, voids, pair/run caps, declarer pins, known kitty) plus card conservation
    against the played cards and the acting seat's own hand, and the declared trump cards' holder."""
    from shengji.ai.memory import Memory, iter_known
    from shengji.engine.cards import make_deck
    from shengji.train import pv_soft_oracle as SOFT
    mem = Memory(rnd, seat, own_kitty=getattr(bots.c.sampler, "BANKER_KITTY", True))
    out = list(SOFT.world_violations(rnd, seat, mem, layout, hands, buried, refusals))
    if Counter(hands[seat]) != Counter(rnd.hands[seat]):
        out.append(("own_hand", seat, None))
    played = Counter()
    for trick in rnd.history:
        for p in trick.plays:
            played.update(p.cards)
    if rnd.trick is not None:
        for p in rnd.trick.plays:
            played.update(p.cards)
    total = Counter()
    for h in hands:
        total.update(h)
    total.update(buried)
    total.update(played)
    if total != Counter(make_deck()):
        out.append(("conservation", None, None))
    for s in range(4):
        if s == seat:
            continue
        for c in hands[s]:
            if rnd.ordering.eff_suit(c) in mem.voids[s]:
                out.append(("void_direct", s, c))
    for code, (dseat, ncopies) in iter_known(mem):
        if dseat != seat and Counter(hands[dseat])[code] < min(ncopies, len(rnd.hands[dseat])):
            out.append(("declared", dseat, code))
    return out
