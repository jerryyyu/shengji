"""Play-likelihood reweighting of the belief proposal's worlds (``belief_play_reweight``, ``-bpr``).

The served belief draw gives ``worlds`` history-legal worlds from the belief package's marginals.
With the flag on, the draw is ``CANDIDATES`` worlds instead; each candidate is weighted by how
likely the prior makes every play the OTHER seats have made so far if that candidate were the
deal, at ``TAU`` times the log-likelihood, and ``worlds`` of them are resampled in proportion.

The likelihood of one past play by seat ``s`` at ply ``t`` under a candidate: the candidate's
hands with every card played from ``t`` on put back, the public state before ply ``t``
(`rewind`), the prior's card log-odds on that state (`pv_encode_prefix.reply_rows`, the
greedy reply ply's rows), an action's logit the sum of its cards' log-odds, and a softmax over
seat ``s``'s legal plays (a follow: the listed follows; a lead: every non-empty sub-multiset of
one effective-suit group, summed in closed form).  A candidate whose hand could not have made
the play has weight zero.  The actor's own plays carry no information about hidden hands and
are skipped.  A refused throw is scored as the play the engine accepted.

Only public facts enter: the plays on the table and the candidate's own hands.  The true hands
of the round the bot is handed are replaced before any row is built.
"""
from __future__ import annotations

import copy
import math
import time
from collections import Counter

import numpy as np

from ..engine.round import Trick, TrickPlay

#: candidates drawn from the belief proposal before the resample
CANDIDATES = 512
#: multiplier on the summed log-likelihood
TAU = 2.0
IDENTITY = {"schema": "belief-play-reweight-v1", "candidates": CANDIDATES, "tau": TAU,
            "likelihood": "prior-legal-softmax", "resample": "multinomial"}


def past_plays(rnd):
    """Every play made so far as ``(trick index, position, seat, cards)``, in table order."""
    out = []
    tricks = list(rnd.history) + ([rnd.trick] if rnd.trick is not None and rnd.trick.plays else [])
    for k, trick in enumerate(tricks):
        for j, play in enumerate(trick.plays):
            out.append((k, j, int(play.seat), list(play.cards)))
    return out


def rewind(rnd, k: int, j: int):
    """The public state before play ``j`` of trick ``k``: a shallow copy of ``rnd`` whose trick,
    history, turn and points are those of that moment.  Its hands are NOT rewound: every
    consumer substitutes a candidate's (`cwv_prior_admission.root_clone`)."""
    tricks = list(rnd.history) + ([rnd.trick] if rnd.trick is not None else [])
    source = tricks[k]
    past = copy.copy(rnd)
    past.phase = "play"
    past.history = list(rnd.history[:k])
    past.trick = Trick(leader=source.leader,
                       plays=[TrickPlay(p.seat, list(p.cards)) for p in source.plays[:j]])
    past.turn = int(source.plays[j].seat)
    past.last_trick = past.history[-1] if past.history else None
    past.attacker_points = sum(t.points for t in past.history if rnd.is_attacker(t.winner))
    past.kitty_bonus = 0
    past.last_trick_winner = None
    past.message = None
    past.notice = None
    past._notice_plays_left = 0
    return past


def _lse(xs):
    m = max(xs)
    return m + math.log(sum(math.exp(x - m) for x in xs))


def lead_logsumexp(hand, ordering, log_odds):
    """log of the sum, over every legal lead of ``hand`` (each non-empty sub-multiset of one
    effective-suit group), of exp(sum of its cards' log-odds): per group the product over codes
    of ``sum_{k=0..copies} e^{k l}``, minus one for the empty set; groups summed."""
    from ..harvest.legal import _lead_groups
    from .policy_prior import CARD_INDEX
    terms = []
    for _suit, cards in _lead_groups(list(hand), ordering):
        total = 0.0
        for code, copies in Counter(cards).items():
            l = float(log_odds[CARD_INDEX[code]])
            total += _lse([k * l for k in range(copies + 1)])
        # every factor exceeds one, so total > 0
        terms.append(total + math.log1p(-math.exp(-total)) if total > 1e-12
                     else math.log(math.expm1(total)) if total > 0 else -math.inf)
    return _lse(terms)


def _listing_arrays(actions):
    from .policy_prior import CARD_INDEX
    cards = np.fromiter((CARD_INDEX[c] for a in actions for c in a), dtype=np.int64)
    offsets = np.zeros(len(actions) + 1, dtype=np.int64)
    np.cumsum([len(a) for a in actions], out=offsets[1:])
    return cards, offsets


def play_loglik(bot, rnd, seat, candidates, check_budget=None):
    """``(len(candidates),)`` float64: each candidate world's summed log-likelihood of the plays
    made so far by the seats other than ``seat``; ``-inf`` where a play was not legal for the
    candidate's hand."""
    from ..harvest import legal as HL
    from . import pv_native
    from .cwv_prior_admission import root_clone
    from .policy_prior import CARD_INDEX
    from .pv_encode_prefix import HistoryPrefix, reply_rows
    plays = past_plays(rnd)
    n = len(candidates)
    ll = np.zeros(n, dtype=np.float64)
    # cards each seat has played from ply t on: a candidate's hand at ply t is its hand now plus these
    later = [[Counter() for _ in range(4)] for _ in range(len(plays) + 1)]
    for t in range(len(plays) - 1, -1, -1):
        later[t] = [Counter(c) for c in later[t + 1]]
        later[t][plays[t][2]].update(plays[t][3])
    for t, (k, j, s, cards) in enumerate(plays):
        if s == seat:
            continue
        if check_budget is not None:
            check_budget()
        alive = np.flatnonzero(np.isfinite(ll))
        if not len(alive):
            break
        past = rewind(rnd, k, j)
        add = [list(later[t][q].elements()) for q in range(4)]
        clones = [root_clone(past, [list(candidates[i][0][q]) + add[q] for q in range(4)],
                             candidates[i][1]) for i in alive]
        played = sorted(cards)
        ok = np.fromiter((HL.is_legal(c, s, played) for c in clones), dtype=bool, count=len(clones))
        ll[alive[~ok]] = -math.inf
        if not ok.any():
            continue
        clones = [c for c, good in zip(clones, ok) if good]
        index = alive[ok]
        prefix = HistoryPrefix.of(past, batched=bot.encode_batch_fast, native=bot.encode_native)
        rows = reply_rows(clones, s, bot.version, prefix)
        logits = np.asarray(bot.predict(np.stack(rows).astype(np.float32)), dtype=np.float64)
        pidx = [CARD_INDEX[c] for c in played]
        lead = past.trick.plays[0].cards if past.trick.plays else None
        cache = {}
        for row, clone in enumerate(clones):
            lg = logits[row]
            hand = clone.hands[s]
            if lead is None:
                lse = lead_logsumexp(hand, clone.ordering, lg)
            else:
                key = tuple(sorted(hand))
                got = cache.get(key)
                if got is None:
                    listing = pv_native.follow_listing(list(hand), list(lead), clone.ordering, None)
                    if listing is None:
                        got = _listing_arrays(HL.enumerate_legal(clone, s, cap=None).actions)
                    else:
                        got = (np.asarray(listing[0], dtype=np.int64),
                               np.asarray(listing[1], dtype=np.int64))
                    cache[key] = got
                cidx, off = got
                sums = np.add.reduceat(lg[cidx], off[:-1])
                m = sums.max()
                lse = m + math.log(np.exp(sums - m).sum())
            ll[index[row]] += lg[pidx].sum() - lse
    return ll


def ess(logw) -> float:
    logw = np.asarray(logw, dtype=np.float64)
    fin = np.isfinite(logw)
    if not fin.any():
        return 0.0
    w = np.exp(logw[fin] - logw[fin].max())
    return float(w.sum() ** 2 / (w ** 2).sum())


def resample(bot, rnd, seat, candidates, count: int, seed: int, check_budget=None):
    """``count`` of ``candidates`` drawn with replacement in proportion to
    ``exp(TAU * play_loglik)``, seeded by ``seed``; ``(worlds, stats)``.  When no candidate has
    a finite likelihood the first ``count`` candidates are returned as drawn and the record
    says so."""
    t0 = time.perf_counter()
    ll = play_loglik(bot, rnd, seat, candidates, check_budget)
    logw = TAU * ll
    fin = np.isfinite(logw)
    stats = {"play_reweight_candidates": len(candidates), "play_reweight_alive": int(fin.sum()),
             "play_reweight_ess": round(ess(logw), 3), "play_reweight_degenerate": 0}
    if not fin.any():
        picked = list(range(count))
        stats["play_reweight_degenerate"] = 1
    else:
        w = np.where(fin, np.exp(np.where(fin, logw, 0.0) - logw[fin].max()), 0.0)
        rng = np.random.default_rng(int(seed))
        picked = [int(i) for i in rng.choice(len(w), size=count, replace=True, p=w / w.sum())]
    stats["play_reweight_distinct"] = len(set(picked))
    stats["play_reweight_ms"] = round(1e3 * (time.perf_counter() - t0), 3)
    return [candidates[i] for i in picked], stats
