#!/usr/bin/env python3
"""Expert labels on fresh self-play of the served bot (the tree's fly.toml SHENGJI_BOT: release 48, or release 49 "Y").
A LABEL producer (a DEV data generator; NOT a strength result) with the search audit probe's game loop, plan, shared draw, FixedWorldsBot,
lift() and record fields.

Supported bases.  The state generator is the base fly.toml serves; "R48" below names it.  On release 49 (R48 plus the singleton
challenger -sc8 and the lead confirmation lcc32) the live seats, the sampler and the served arm are Y as served, its singleton challenger
and lead confirmation included: the served arm's confirmation draws are the shared draw's next 2 x 64 worlds (FixedWorldsBot).  The expert
drops both rules (served_base.EXPERT_DROPS), so on either base it is the same bot under the same name.  On release 48 (no wrapper, no
lead confirmation) none of this applies: the served arm is FixedWorldsBot itself and its confirmation draw is never called.

Four R48 bots play fresh rank-mixed deals (the s61dev r2 plan per deal index) exactly as served -- fly.toml's SHENGJI_BOT and SHENGJI_* env
through the reviewed harness's served_env / variant_factory (exploit_duel_s61.py beside this file) -- under the R48 recipe with lifted
budgets and internal wall deadlines removed (lift(): no play / bury budget, lgfd 0, els 86400, belief prep cap infinite process-wide), so a
loaded host never changes a decision.  At the LABELLED decisions (every lead in tricks 1..LATE_TRICK-1, a lead from LATE_TRICK on with
probability --late-lead-prob, a follow with probability --prob-follow; a decision with one scored action is never labelled) two arms
price the SAME decision on a deep copy with ONE shared 256-world belief draw (R48's sampler, the S58 package):

  expert   a_E   the S61 exploiter BASE at lifted budget (all 256 worlds, K 32, exact 8/8, els 9 s, 2e8 nodes, no lgfd) under a wall cap
                 (--expert-cap-secs): a capped or refused decision is DROPPED and counted, never replaced
  served   a_s   R48 as served on the first 64 worlds of the draw (the recall baseline and the mix row's served pass)

The expert's 32-slot ballot B_E, its 256-world value means Q(a) (levels), R48's prior log-odds l(a) on B_E (the expert runs R48's own
policy head, so its policy_log_odds_admitted IS R48's prior as a 256-world mean) and the rank of a_E in both listings are the row's
target inputs.  The live seat's own record (the action actually played, R48's 8-slot ballot and 64-world means) gives the SELF-TARGET
row of every UNLABELLED multi-action decision, for the 1:1 anti-forgetting mix.

Rows.  Per shard: `probe.jsonl` (a header, one `decision` row per labelled decision with both arm records, one `live` row per unlabelled
decision, one `deal_done` row per deal with its deal_key, one `end` row), and the training rows in the PolicyRows format
`policy_prior.extract` writes for a prefix (`<prefix>.npz` X float16 [n, 833] + Y uint8 [n, 54]; `<prefix>.meta.jsonl` with
ballot / taken / means / deal / deal_key / n_legal / complete / units and the 1b tags): `rows_expert` (Y = a_E, ballot = B_E, means = Q_E)
and `rows_self` (Y = the live seat's selected action, ballot = its 8-slot ballot, means = its 64-world means).  `open_policy_rows(prefix)`
loads either.  The ballot's `taken` is the search's SELECTED action (admitted[selected_index]), so it is always in the ballot; the cards
actually played (a doomed-throw swap may differ) are on the row as `played`, with `swapped`.  Means are value-head LEVELS (units
"value-head-levels"); the trainer builds the completed-Q target from `prior_lo` and `means` at its calibrated T.

Replay capsule (--record-capsule, the HELD-OUT phase).  For every kept labelled decision `capsule.jsonl.gz` holds what the stage-2 recall
read needs to run the REAL served path again at the same root: the canonical engine state (`shengji.luna.game._state_snapshot`, rebuilt by
`_round_from_snapshot`), the deck (the deal key's and the refusal ledger's identity; the kitty is its tail), the hands and the burial in their LIVE order (the
snapshot sorts them; the heuristic anchor reads the hand in its live order, which fixes the ballot's slot 0 and the tie-breaks), the public
failed-throw notice, the served arm's refusal ledger and seed, `first_round`, the served arm's 64 worlds (card indices) and its recorded record
(ballot, means, prior log-odds, selected action, worlds digest).  `replay_capsule(capsule, make)` rebuilds the root, builds a fresh served bot through the registry
(the harness's `variant_factory`, i.e. `pv_registry_entries` / fly.toml's SHENGJI_BOT; the prior through `cwv_prior_admission.load_prior_checked`),
injects the recorded worlds and runs `decide_play`: the recorded ballot, means and pick must come back exactly (the producer test and the
checker's sampled replay prove it).

Recovery.  A shard is written under `shard-NN.partial/` and becomes `shard-NN/` by one atomic rename after its `shard_manifest.json` (the
shard's seed window, plan base, knobs, header pins, this file's and the harness's sha256, every file's sha256, the counts and deal keys) is
written: a completed shard directory is immutable.  `--resume` on an existing output root verifies every completed shard against its
manifest and skips it (a completed shard that does not verify REFUSES: it is never silently recomputed), moves a `.partial` left by a
killed worker to `diag/` (preserved, never deleted) and recomputes only the missing shards; the phase summary is rebuilt atomically
(`summary.json.tmp` -> rename) from the completed shards' manifests, the previous summary kept under `diag/`.  Shards are deterministic
given their window, so a recomputed shard holds the same rows.  Resume is a recovery capability of the files, not authority to retry a run.

The checker (m28lab_check.py) applies the validity guards; this file makes no claim.

Usage (cwd = the tree's server/; SHENGJI_FAST=1; FIND_GAPS_SERVER / FIND_GAPS_PKG / FIND_GAPS_PATH_MAP as the harness):
  python -B scripts/expert_labels/expert_label_probe.py --out DIR --seed0 S --deals N --shards 12 --workers 12 [knobs] [--record-capsule] [--resume]
"""
from __future__ import annotations

import argparse
import copy
import datetime
import gzip
import hashlib
import json
import math
import os
import platform
import random
import shutil
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import exploit_duel_s61 as duel  # noqa: E402  (served_env runs at import: fly.toml's SHENGJI_* keys enter the process env)

from shengji.ai import belief_numpy as _belief_numpy  # noqa: E402
from shengji.ai.env import observe_committed_play  # noqa: E402
from shengji.engine.cards import points  # noqa: E402
from shengji.engine.combos import decompose  # noqa: E402
from shengji.ai.refusal import Refusal  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.luna.game import _round_from_snapshot, _state_snapshot  # noqa: E402
from shengji.train.data import deal_key as data_deal_key  # noqa: E402
from shengji.train.leaf_screen import _game_factory_for  # noqa: E402
from shengji.train.policy_prior import CARD_INDEX, ENC_VERSION, N_CARDS, cards_to_idx, deal_id, flat_input, input_dim, root_tensors  # noqa: E402
from shengji.train.pv_search_policy import EXACT_LEAD_MAX_SECONDS_RANGE, FALLBACK_SCHEMA, RECORD_SCHEMA, PVSearchBuryBot  # noqa: E402

import served_base  # noqa: E402

PROBE_SCHEMA = "m28lab-v2"
PROBE_REV = "r2"
SHARD_MANIFEST_SCHEMA = "m28lab-shard-manifest-v2"
CAPSULE_SCHEMA = "m28lab-capsule-v3"
PLAN = "r2"
ROWS_UNITS = "value-head-levels"       # the means' units on every training row: R48's value head, levels per round
#: what lift() sets on every R48 instance (module docstring): no serving budgets, no greedy-finish deadline, the exact-lead stage
#: bounded by its node cap alone (the range's maximum seconds), and -- process-wide, below -- no belief preparation cap
LIFTED = {"serving_budget_seconds": None, "bury_serving_budget_seconds": None, "leaf_greedy_deadline_ms": 0,
          "exact_lead_max_seconds": float(EXACT_LEAD_MAX_SECONDS_RANGE[1]), "belief_prep_seconds": "inf"}
#: the belief proposal's preparation cap is a module constant read at every draw; every bot of this process (the expert included)
#: draws without it, and a slow preparation is a slow draw, not a belief fallback
_belief_numpy.PREP_SECONDS = math.inf
#: the per-record `caps` of a lifted bot, and of the expert at its declared caps (its wall cap, lgfd off, els 9 s from EXPERT_ENV)
LIFTED_CAPS = {"serving_budget_seconds": None, "leaf_greedy_deadline_ms": 0, "exact_lead_max_seconds": LIFTED["exact_lead_max_seconds"],
               "belief_prep_seconds": "inf"}
#: the expert's overrides on top of the served base (served_base.EXPERT_ENV); main() adds the removal of the base's EXPERT_DROPS rules
EXPERT_ENV = served_base.EXPERT_ENV
EXPERT_WORLDS = 256
LISTING_CAP = 256    # pv_search_policy records the policy log-odds of the scored set's first 256 entries


def EXPERT_CAPS(cap):
    """The expert's declared caps as its record's `caps`: the wall cap as its serving budget, lgfd off, els from EXPERT_ENV."""
    return {"serving_budget_seconds": float(cap), "leaf_greedy_deadline_ms": 0,
            "exact_lead_max_seconds": float(dict(EXPERT_ENV)["SHENGJI_PV_EXACT_LEAD_MAX_SECONDS"]), "belief_prep_seconds": "inf"}


def worlds_digest(worlds):
    h = hashlib.sha256()
    for hands, buried in worlds:
        h.update(json.dumps([[sorted(x) for x in hands], sorted(buried)]).encode())
    return h.hexdigest()


def det_seed(deal, index):
    return int.from_bytes(hashlib.sha256(f"search-audit|{deal}|{index}".encode()).digest()[:6], "big")


def key(cards):
    return sorted(cards)


class FixedWorldsBot(PVSearchBuryBot):
    """The registered class with its world DRAW replaced by an injected draw: ``_fixed`` = (worlds, attempts, sampling stats)
    from one shared 256-world draw; this bot takes the first ``self.worlds`` of them (64 for the served configuration, all 256
    for the expert), so the served and the expert arms are paired in worlds 0..63.  Everything after the draw -- admission,
    the value pass and its reducer, the selection rules, the exact stages, the record -- is the served code."""

    _fixed = None
    received_digest = None       # sha256 over the worlds this bot actually priced

    def _worlds(self, rnd, seat, check_budget=None):
        if self._fixed is None:
            raise RuntimeError("FixedWorldsBot: no injected draw")
        worlds, attempts, sampling = self._fixed
        if self.refusal_constraints:
            self._refusals.observe(rnd)
        if len(worlds) < self.worlds:
            raise RuntimeError(f"FixedWorldsBot: injected draw holds {len(worlds)} worlds, this bot needs {self.worlds}")
        use = list(worlds[:self.worlds])
        self._last_sampling = dict(sampling)
        self.received_digest = worlds_digest(use)
        return use, attempts

    def confirm_world_count(self):
        """Worlds the lead confirmation's fresh draws take from the injected draw after the base worlds (0 with the rule off)."""
        return self.worlds * self.lead_confirm_rounds if self.lead_confirm else 0

    def _lead_confirm_draw(self, rnd, seat, check_budget):
        """The lead confirmation's fresh draws: the injected draw's next ``lead_confirm_rounds`` blocks of ``self.worlds`` worlds after
        the base worlds, disjoint from them and drawn by the same sampler call, so the paired arms stay on one shared draw."""
        worlds = self._fixed[0] if self._fixed is not None else ()
        need = self.worlds + self.confirm_world_count()
        if len(worlds) < need:
            raise RuntimeError(f"FixedWorldsBot: injected draw holds {len(worlds)} worlds, the lead confirmation needs {need}")
        if check_budget:
            check_budget()
        return list(worlds[self.worlds:need])


_FIXED_WORLDS_CLASSES = {PVSearchBuryBot: FixedWorldsBot}


def fixed_worlds_class(cls):
    """The FixedWorldsBot form of a served class: FixedWorldsBot itself for the plain search, else a subclass placing the injected draw
    ahead of ``cls`` in the MRO, so every rule ``cls`` adds (the singleton challenger's admission) stays in force."""
    if not (isinstance(cls, type) and issubclass(cls, PVSearchBuryBot)):
        raise TypeError(f"not a PVSearchBuryBot class: {cls!r}")
    if cls not in _FIXED_WORLDS_CLASSES:
        _FIXED_WORLDS_CLASSES[cls] = type("FixedWorlds" + cls.__name__, (FixedWorldsBot, cls), {"__module__": __name__})
    return _FIXED_WORLDS_CLASSES[cls]


def lift(bot):
    """The R48 recipe under lifted budgets with internal wall deadlines removed (module docstring, LIFTED)."""
    bot.serving_budget_seconds = LIFTED["serving_budget_seconds"]
    bot.bury_serving_budget_seconds = LIFTED["bury_serving_budget_seconds"]
    bot.leaf_greedy_deadline_ms = LIFTED["leaf_greedy_deadline_ms"]
    bot.exact_lead_max_seconds = LIFTED["exact_lead_max_seconds"]
    return bot


def caps(bot):
    """The wall-time caps a bot runs under, as the probe set them: the per-row witness of the lifted (or the expert's declared) policy."""
    return {"serving_budget_seconds": bot.serving_budget_seconds, "leaf_greedy_deadline_ms": int(bot.leaf_greedy_deadline_ms),
            "exact_lead_max_seconds": float(bot.exact_lead_max_seconds), "belief_prep_seconds": "inf" if _belief_numpy.PREP_SECONDS == math.inf else _belief_numpy.PREP_SECONDS}


#: record fields of the served lead rules (the singleton challenger's admission, the lead confirmation), copied when the record has them
SERVED_RULE_FIELDS = ("singleton_challenger_applied", "singleton_probe_margin", "lead_confirm_status", "lead_confirm_applied",
                      "lead_confirm_worlds", "lead_confirm_abandon_reason")


def rec_fields(rec, bot):
    """The decision-record fields the checker guards and reports (a search record or a fallback record), and the bot's caps.
    The deadline fields are the record's own names at 0c1e9965: present only when the rule is on and the stage ran."""
    rec = rec or {}
    out = {"schema": rec.get("schema"), "worlds": rec.get("worlds"), "belief_fallback": rec.get("belief_fallback"),
           "belief_error": rec.get("belief_error"), "seconds": rec.get("seconds", rec.get("elapsed_seconds")), "caps": caps(bot)}
    if rec.get("schema") == FALLBACK_SCHEMA:
        out.update(reason=rec.get("reason"), error_class=rec.get("error_class"), error_stage=rec.get("error_stage"))
    else:
        out.update(admitted_n=len(rec.get("admitted") or []), selected_index=rec.get("selected_index"),
                   exact_deep_cards=rec.get("exact_deep_cards"), exact_lead_status=rec.get("exact_lead_status"),
                   exact_lead_changed=rec.get("exact_lead_changed"), exact_lead_abandon_reason=rec.get("exact_lead_abandon_reason"),
                   exact_follow_attempted=rec.get("exact_follow_attempted"), exact_follow_applied=rec.get("exact_follow_applied"),
                   exact_follow_abandoned=rec.get("exact_follow_abandoned"),
                   lgf_deadline_fired=rec.get("leaf_greedy_deadline_fired"), lgf_deadline_cut_leaves=rec.get("leaf_greedy_deadline_cut_leaves"),
                   tiebreak_abandoned=rec.get("tiebreak_abandoned"), reselect_abandoned=rec.get("doomed_throw_reselect_abandoned"))
        # the served lead rules' witnesses, on the records of a bot that runs them (a plain R48 record carries none of these keys)
        out.update({k: rec[k] for k in SERVED_RULE_FIELDS if k in rec})
    return out


def action_type(cards, rnd):
    """single / pair / tractor (one component) or throw (several components, a mixed-suit follow included)."""
    if len(cards) == 1:
        return "single"
    comps = decompose(list(cards), rnd.ordering).components
    return comps[0].kind if len(comps) == 1 else "throw"


def selected_action(rec):
    """The search's SELECTED ballot action (admitted[admitted_indices.index(selected_index)]) or None on a record without a usable
    ballot (a fallback, a single candidate priced by nobody, a selection outside the ballot)."""
    adm, idx, sel, means = rec.get("admitted") or [], rec.get("admitted_indices") or [], rec.get("selected_index"), rec.get("value_means") or []
    if rec.get("schema") != RECORD_SCHEMA or len(adm) < 2 or len(adm) != len(idx) or len(means) != len(adm) or sel not in idx \
            or any(m is None or not math.isfinite(float(m)) for m in means):
        return None
    return key(adm[idx.index(sel)])


def listing_rank(listing, i):
    """The rank (0 = top) of scored-set entry ``i`` in a policy log-odds listing, or None when the listing does not reach it."""
    if listing is None or i is None or not 0 <= i < len(listing):
        return None
    return int(sum(1 for v in listing if v > listing[i]))


def arm_record(rec, bot, rnd):
    out = rec_fields(rec, bot)
    sel = selected_action(rec)
    out.update(cards=sel, played=key(rec["played"]) if rec.get("played") is not None else None, swapped=(sel is not None and key(rec["played"]) != sel),
               admitted=[key(a) for a in rec.get("admitted") or []], admitted_indices=rec.get("admitted_indices"),
               value_means=rec.get("value_means"), policy_log_odds_admitted=rec.get("policy_log_odds_admitted"),
               n_actions=rec.get("actions"), legal_count=rec.get("legal_count"), legal_complete=rec.get("legal_complete"),
               action_type=action_type(sel, rnd) if sel is not None else None)
    return out


def training_row(rnd, seat, cards, ballot, means, prior_lo, tags):
    """One PolicyRows row: X the true-world root tensors from the mover's seat (encoder v2), Y the 54-card multi-hot of ``cards``,
    the meta the loader reads (ballot / taken as card indices, means, deal, deal_key, n_legal, complete, units) plus the 1b tags."""
    x = flat_input(root_tensors(rnd, seat))
    y = np.zeros(N_CARDS, np.uint8)
    for i in cards_to_idx(cards):
        y[i] = 1
    meta = {"ballot": [cards_to_idx(a) for a in ballot], "taken": cards_to_idx(cards), "means": [float(m) for m in means],
            "prior_lo": [float(v) for v in prior_lo], "deal": deal_id(rnd), "deal_key": data_deal_key(list(rnd.deck)),
            "units": ROWS_UNITS, "seat": seat, "trick_no": len(rnd.history), "lead": rnd.trick is not None and not rnd.trick.plays,
            "is_attacker": bool(rnd.is_attacker(seat)), "is_banker": seat == rnd.banker, "hand_size": len(rnd.hands[seat])}
    meta.update(tags)
    return x, y, meta


CARDS = sorted(CARD_INDEX, key=CARD_INDEX.get)      # index -> card string


def world_indices(worlds):
    """The served arm's worlds as card indices: [[hands x4], buried] per world."""
    return [[[cards_to_idx(sorted(h)) for h in hands], cards_to_idx(sorted(buried))] for hands, buried in worlds]


def worlds_from_indices(idx):
    """The inverse of world_indices: [(hands, buried)] with card strings, each hand and the burial sorted."""
    return [([sorted(CARDS[i] for i in h) for h in hands], sorted(CARDS[i] for i in buried)) for hands, buried in idx]


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def capsule_of(rnd, seat, D, worlds64, served, deal, index, dkey, first_round, served_seed, confirm_worlds=()):
    """The replay capsule of one kept labelled decision (module docstring): the canonical root state, the deck, the public notice, the
    served arm's refusal ledger and seed, its 64 worlds and its recorded record; with the served lead confirmation on, also the worlds its
    fresh draws took (``confirm_worlds``, absent otherwise)."""
    cap = {"schema": CAPSULE_SCHEMA, "deal": deal, "index": index, "seat": seat, "deal_key": dkey, "first_round": bool(first_round),
            "snapshot": _state_snapshot(rnd), "deck": cards_to_idx(list(rnd.deck)), "notice": copy.deepcopy(getattr(rnd, "notice", None)),
            # the snapshot sorts every hand; the heuristic anchor (slot 0 of the ballot, hence the ballot order and the tie-breaks) reads the hand in
            # its live order, so the live order is kept beside it (same multiset, asserted on replay)
            "hands_order": [cards_to_idx(list(h)) for h in rnd.hands], "buried_order": cards_to_idx(list(rnd.buried)),
            "refusals": [[r.seat, list(r.attempted), list(r.forced), r.trick_index] for r in D._refusals.refusals], "served_seed": served_seed,
            "worlds": world_indices(worlds64),
            "served": {k: served[k] for k in ("admitted", "admitted_indices", "cards", "played", "value_means", "policy_log_odds_admitted", "selected_index", "n_actions", "legal_count", "worlds", "schema")},
            "worlds_digest": D.received_digest}
    if D.lead_confirm:
        cap["confirm_worlds"] = world_indices(confirm_worlds)
    return cap


def round_from_capsule(cap):
    """The pre-decision Round of a capsule: the luna snapshot rebuilt, then the context the snapshot does not carry (deck, kitty, first_round,
    the public notice)."""
    rnd = _round_from_snapshot(cap["snapshot"])
    hands = [[CARDS[i] for i in h] for h in cap["hands_order"]]
    buried = [CARDS[i] for i in cap["buried_order"]]
    if [sorted(h) for h in hands] != [list(h) for h in rnd.hands] or sorted(buried) != list(rnd.buried):
        raise ValueError("capsule: hands_order / buried_order are not the snapshot's multisets")
    rnd.hands, rnd.buried = hands, buried
    rnd.deck = [CARDS[i] for i in cap["deck"]]
    rnd.kitty = list(rnd.deck[-len(rnd.buried):]) if rnd.buried else list(rnd.deck[100:])
    rnd.first_round = bool(cap["first_round"])
    rnd.notice = copy.deepcopy(cap["notice"])
    return rnd


def replay_capsule(cap, make):
    """Re-run the SERVED path on a capsule: a fresh bot from the registry factory `make(seed)` (the harness's variant_factory: the R48 recipe,
    the numpy prior through cwv_prior_admission.load_prior_checked, the served admission / value pass / reducer / rules), lifted exactly as
    the lane's bots, its ledger seeded with the capsule's refusals, the capsule's 64 worlds injected.  Returns the comparison with the
    recorded served record: ballot, means, prior log-odds, selected action and worlds digest must all be exactly equal."""
    rnd = round_from_capsule(cap)
    before = json.dumps(_state_snapshot(rnd), sort_keys=True)
    bot = lift(make(cap["served_seed"]))
    bot.__class__ = fixed_worlds_class(type(bot))
    bot._refusals.key = tuple(rnd.deck)
    bot._refusals.refusals = [Refusal(int(a), tuple(b), tuple(c), int(d)) for a, b, c, d in cap["refusals"]]
    worlds = worlds_from_indices(cap["worlds"])
    if bool(bot.lead_confirm) != ("confirm_worlds" in cap):
        raise ValueError("capsule: confirm_worlds present iff the served bot runs the lead confirmation")
    bot._fixed = (worlds + worlds_from_indices(cap.get("confirm_worlds", [])), 0, {})
    cards = bot.decide_play(rnd, cap["seat"])
    rec = bot.last_decision_record or {}
    got = dict(admitted=[key(a) for a in rec.get("admitted") or []], value_means=rec.get("value_means"), policy_log_odds_admitted=rec.get("policy_log_odds_admitted"),
               cards=selected_action(rec), played=key(cards), selected_index=rec.get("selected_index"), n_actions=rec.get("actions"), worlds=rec.get("worlds"), schema=rec.get("schema"))
    want = cap["served"]
    same = {k: got[k] == want[k] for k in ("admitted", "value_means", "policy_log_odds_admitted", "cards", "played", "selected_index", "n_actions", "worlds", "schema")}
    same["worlds_digest"] = bot.received_digest == cap["worlds_digest"] == worlds_digest(worlds[:bot.worlds])
    same["state_unchanged"] = json.dumps(_state_snapshot(rnd), sort_keys=True) == before
    return dict(ok=all(same.values()), same=same, got=got, caps=caps(bot))


def label(bots, rnd, seat, deal, index, live_cards, live_rec, live_bot):
    S, D, E = bots
    t0 = time.perf_counter()
    snap = copy.deepcopy(rnd)
    secs = {}
    # the shared draw: 256 worlds from the served sampler (R48's recipe, its own stream); the served arm takes 0..63
    t = time.perf_counter()
    S.worlds = E.worlds
    worlds, attempts = S._worlds(snap, seat)
    sampling = dict(S._last_sampling)
    secs["draw"] = time.perf_counter() - t
    if len(worlds) < D.worlds + D.confirm_world_count():
        raise RuntimeError(f"shared draw of {len(worlds)} worlds is narrower than the served arm's {D.worlds} + {D.confirm_world_count()}")
    for b in (D, E):
        b._fixed = (worlds, attempts, sampling)
    # expert
    t = time.perf_counter()
    e_cards = E.decide_play(snap, seat)
    secs["expert"] = time.perf_counter() - t
    e_rec = E.last_decision_record or {}
    expert = arm_record(e_rec, E, snap)
    e_dropped = e_rec.get("schema") != RECORD_SCHEMA or expert["cards"] is None
    expert.update(dropped=e_dropped, drop_reason=None if not e_dropped else (e_rec.get("reason") or ("no-ballot" if e_rec.get("schema") == RECORD_SCHEMA else "no-record")))
    # served
    t = time.perf_counter()
    s_cards = D.decide_play(snap, seat)
    secs["served"] = time.perf_counter() - t
    s_rec = D.last_decision_record or {}
    served = arm_record(s_rec, D, snap)
    # the admission tags of a_E: in R48's served ballot; its rank in R48's 64-world prior listing (the served record's, aligned by scored-set
    # index when both arms enumerated the same set) and in the 256-world listing (the expert's own)
    tags = {"expert_in_r48_ballot": None, "expert_pref_rank_r48": None, "expert_lo_r48": None, "expert_pref_rank_256": None,
            "listing_aligned": None, "rank_exact": None}
    if not e_dropped and served["schema"] == RECORD_SCHEMA:
        sel_i = e_rec["selected_index"]
        aligned = bool(s_rec.get("actions") == e_rec.get("actions") and s_rec.get("legal_count") == e_rec.get("legal_count"))
        s_listing = s_rec.get("policy_log_odds_listing") or []
        tags.update(expert_in_r48_ballot=tuple(expert["cards"]) in {tuple(a) for a in served["admitted"]},
                    expert_pref_rank_r48=listing_rank(s_listing, sel_i) if aligned else None,
                    expert_lo_r48=float(s_listing[sel_i]) if aligned and 0 <= sel_i < len(s_listing) else None,
                    expert_pref_rank_256=listing_rank(e_rec.get("policy_log_odds_listing"), sel_i),
                    listing_aligned=aligned, rank_exact=bool(e_rec.get("actions") is not None and e_rec["actions"] <= LISTING_CAP))
    secs["total"] = time.perf_counter() - t0
    plays = len(snap.trick.plays) if snap.trick is not None else 0
    live = rec_fields(live_rec, live_bot)
    live.update(cards=key(live_cards))
    row = {
        "row": "decision", "deal": deal, "index": index, "seat": seat,
        "lead": plays == 0, "pos_in_trick": plays, "trick_no": len(snap.history),
        "hand_size": len(snap.hands[seat]), "max_hand": max(len(h) for h in snap.hands),
        "is_attacker": bool(snap.is_attacker(seat)), "is_banker": seat == snap.banker,
        "legal_count": s_rec.get("legal_count"), "legal_complete": s_rec.get("legal_complete"), "n_actions": s_rec.get("actions"),
        "expert": expert, "served": served, "live": live, **tags,
        # the pairing witness: the served bot priced exactly the expert's first `D.worlds` worlds (64 in the lane configuration)
        "worlds_digest": {"served": D.received_digest, "expert": E.received_digest, "expert_prefix": worlds_digest(worlds[:D.worlds])},
        "draw_attempts": attempts, "secs": secs,
    }
    train = None
    if not e_dropped:
        train = training_row(snap, seat, expert["cards"], expert["admitted"], expert["value_means"], expert["policy_log_odds_admitted"],
                             {"source": "expert", "index": index, "label_kind": "lead" if plays == 0 else "follow", "action_type": expert["action_type"],
                              "expert_secs": secs["expert"], "expert_swapped": expert["swapped"], "expert_played": cards_to_idx(expert["played"]),
                              "served_ballot": [cards_to_idx(a) for a in served["admitted"]], "served_means": served["value_means"],
                              "served_prior_lo": served["policy_log_odds_admitted"], "served_taken": cards_to_idx(served["cards"]) if served["cards"] else None,
                              "served_schema": served["schema"], "live_taken": cards_to_idx(live["cards"]), **tags})
    return row, train, worlds[:D.worlds], worlds[D.worlds:D.worlds + D.confirm_world_count()], served


def note_declare(bot, drecs):
    rec = getattr(bot, "last_declare_record", None)
    if isinstance(rec, dict):
        drecs.append([rec.get("schema"), rec.get("fallback_reason"), rec.get("evaluated"), rec.get("worlds"),
                      rec.get("worlds_completed"), rec.get("seconds")])


def play_deal(cfg, deal, gidx, fh, rows_e, rows_s, cfh):
    kind, rank, fixed = duel.round_plan(PLAN, gidx)
    dn, dmake = duel.variant_factory(cfg["served_env"])
    en, emake = duel.variant_factory(cfg["expert_env"])
    pol = [lift(dmake(duel.seat_seed(deal, s))) for s in range(4)]
    S = lift(dmake(det_seed(deal, -1)))
    served_seed = det_seed(deal, -3)
    D = lift(dmake(served_seed))
    served_cls = served_base.served_class(dn)
    D.__class__ = fixed_worlds_class(type(D))
    E = emake(det_seed(deal, -5))
    E.__class__ = fixed_worlds_class(type(E))
    E.serving_budget_seconds = cfg["expert_cap_secs"]
    E.bury_serving_budget_seconds = None
    # the classes the names build: the live seats and the sampler are the served class, the served arm its FixedWorlds form, the expert the
    # plain search's (its EXPERT_DROPS leave no wrapper)
    assert all(type(b) is served_cls for b in pol + [S]), [type(b).__name__ for b in pol + [S]]
    assert type(D) is fixed_worlds_class(served_cls) and type(E) is FixedWorldsBot, (type(D).__name__, type(E).__name__)
    for b in pol + [S, D]:   # the lifted policy, witnessed before the deal is played
        assert caps(b) == LIFTED_CAPS and b.bury_serving_budget_seconds is None, caps(b)
    assert caps(E) == EXPERT_CAPS(cfg["expert_cap_secs"]), caps(E)
    bots = (S, D, E)
    game = Game(random.Random(deal)) if kind == "first" else _game_factory_for(rank, fixed)(random.Random(deal))
    rnd = game.start_round()
    assert rnd.trump_rank == rank and bool(rnd.first_round) == (kind == "first") and (fixed is None or rnd.banker == fixed), \
        (kind, rank, fixed, rnd.trump_rank, rnd.first_round, rnd.banker)
    dkey = data_deal_key(list(rnd.deck))
    drecs = []
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = pol[seat].decide_declare(rnd, seat)
        note_declare(pol[seat], drecs)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = pol[seat].decide_declare(rnd, seat, final=True)
        note_declare(pol[seat], drecs)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    banker = rnd.banker
    buried = pol[banker].decide_bury(rnd, banker)
    brec = getattr(pol[banker], "last_bury_record", None)
    brec = brec if isinstance(brec, dict) else {}
    bury_rec = [brec.get("schema"), brec.get("fallback_reason"), brec.get("candidate_count"), brec.get("model_worlds")]
    rnd.bury(banker, buried)
    pick = random.Random(det_seed(deal, -2))
    index, labelled, dropped, n_self, skipped_single, self_skipped = 0, [], 0, 0, 0, 0
    while rnd.phase == "play":
        seat = rnd.turn
        lead = rnd.trick is not None and not rnd.trick.plays
        trick_no = len(rnd.history)
        if lead:
            want = trick_no < cfg["late_trick"] or pick.random() < cfg["late_lead_prob"]
        else:
            want = pick.random() < cfg["prob_follow"]
        t0 = time.perf_counter()
        cards = pol[seat].decide_play(rnd, seat)
        live_secs = time.perf_counter() - t0
        rec = pol[seat].last_decision_record or {}
        single = rec.get("schema") == RECORD_SCHEMA and (rec.get("actions") or 0) < 2
        if want and not single:
            before = (json.dumps(rnd.hands), len(rnd.history), len(rnd.trick.plays) if rnd.trick is not None else 0)
            row, train, w64, wconfirm, served = label(bots, rnd, seat, deal, index, cards, rec, pol[seat])
            assert before == (json.dumps(rnd.hands), len(rnd.history), len(rnd.trick.plays) if rnd.trick is not None else 0)
            row["live_secs"] = live_secs
            fh.write(json.dumps(row) + "\n")
            labelled.append(index)
            dropped += int(row["expert"]["dropped"])
            if train is not None:
                rows_e.append(train)
                if cfh is not None:
                    cfh.write((json.dumps(capsule_of(rnd, seat, D, w64, served, deal, index, dkey, kind == "first", served_seed, wconfirm)) + "\n").encode())
        else:
            live = rec_fields(rec, pol[seat])
            sel = selected_action(rec) if not single else None
            live.update(row="live", deal=deal, index=index, seat=seat, lead=lead, trick_no=trick_no, live_secs=live_secs,
                        skipped_single=bool(want and single), cards=key(cards), self_row=sel is not None)
            fh.write(json.dumps(live) + "\n")
            if sel is not None:
                x, y, meta = training_row(rnd, seat, sel, [key(a) for a in rec["admitted"]], rec["value_means"], rec["policy_log_odds_admitted"],
                                          {"source": "self", "index": index, "label_kind": "lead" if lead else "follow", "action_type": action_type(sel, rnd),
                                           "swapped": key(cards) != sel, "played": cards_to_idx(cards)})
                rows_s.append((x, y, meta))
                n_self += 1
            elif not single and rec.get("schema") == RECORD_SCHEMA:
                self_skipped += 1
        rnd.play(seat, cards)
        observe_committed_play(rnd, pol + [S, D, E])
        index += 1
    result = game.finish_round()
    fh.write(json.dumps({
        "row": "deal_done", "deal": deal, "deal_key": dkey, "plan_index": gidx, "round_kind": kind, "trump_rank": rnd.trump_rank, "planned_banker": fixed,
        "banker": banker, "decisions": index, "labelled": labelled, "expert_dropped": dropped, "self_rows": n_self, "self_skipped": self_skipped,
        "attacker_points": int(result.attacker_points), "kitty_points": int(sum(points(c) for c in rnd.buried)),
        "kitty_bonus": int(result.kitty_points), "last_trick_winner": rnd.last_trick_winner,
        "winner_team": int(result.winner_team), "level_change": int(result.level_change),
        "declare_recs": {"live": drecs}, "bury_rec": {"live": bury_rec}}) + "\n")
    fh.flush()
    return dict(decisions=index, labelled=len(labelled), expert_dropped=dropped, self_rows=n_self, deal_key=dkey)


def write_rows(prefix, rows):
    """The PolicyRows pair for a prefix (``<prefix>.npz`` + ``<prefix>.meta.jsonl``), fresh files; nothing when there is no row."""
    if not rows:
        return 0
    X = np.stack([r[0] for r in rows]).astype(np.float16)
    Y = np.stack([r[1] for r in rows]).astype(np.uint8)
    assert X.shape == (len(rows), input_dim(ENC_VERSION)) and Y.shape == (len(rows), N_CARDS), (X.shape, Y.shape)
    with open(prefix + ".npz", "xb") as fh:
        np.savez_compressed(fh, X=X, Y=Y)
    with open(prefix + ".meta.jsonl", "x") as fh:
        for r in rows:
            fh.write(json.dumps(r[2]) + "\n")
    return len(rows)


SOURCE_SHA256 = file_sha256(os.path.realpath(__file__))
HARNESS_SHA256 = file_sha256(os.path.join(HERE, "exploit_duel_s61.py"))
SERVED_BASE_SHA256 = file_sha256(os.path.join(HERE, "served_base.py"))
KNOBS = ("late_trick", "late_lead_prob", "prob_follow", "expert_cap_secs", "record_capsule", "served_env", "expert_env")


def utc_stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def header_row(cfg, shard, seed0, deals):
    dn, dmake = duel.variant_factory(cfg["served_env"])
    en, emake = duel.variant_factory(cfg["expert_env"])
    return {"row": "header", "schema": PROBE_SCHEMA, "probe_rev": PROBE_REV, "lifted": LIFTED, "shard": shard, "seed0": seed0, "deals": deals, "plan": PLAN,
            "served_name": dn, "expert_name": en, "served_env": [list(x) for x in cfg["served_env"]],
            "expert_env": [list(x) for x in cfg["expert_env"]], "served_worlds": dmake(0).worlds, "expert_worlds": emake(0).worlds,
            "expert_cap_secs": cfg["expert_cap_secs"], "late_trick": cfg["late_trick"], "late_lead_prob": cfg["late_lead_prob"],
            "prob_follow": cfg["prob_follow"], "record_capsule": cfg["record_capsule"], "rows_units": ROWS_UNITS,
            "enc_version": int(ENC_VERSION), "input_dim": input_dim(ENC_VERSION), "source_sha256": SOURCE_SHA256, "harness_sha256": HARNESS_SHA256, "served_base_sha256": SERVED_BASE_SHA256,
            "pv_sha256": os.environ.get("SHENGJI_PV_SHA256"), "belief_sha256": os.environ.get("SHENGJI_PV_BELIEF_SHA256"),
            "fly_toml_sha256": duel._sha256(duel.REPO / "fly.toml"), "python": platform.python_version(),
            "numpy": np.__version__, "fast": os.environ.get("SHENGJI_FAST")}


def shard_binding(cfg, shard, seed0, deals):
    """What a completed shard must have been produced from: its window, plan base, knobs and the producing sources."""
    return {"shard": shard, "seed0": seed0, "deals": deals, "plan_base": cfg["plan_base"], "plan": PLAN, "schema": PROBE_SCHEMA, "probe_rev": PROBE_REV,
            "knobs": {k: ([list(x) for x in cfg[k]] if k in ("served_env", "expert_env") else cfg[k]) for k in KNOBS},
            "source_sha256": SOURCE_SHA256, "harness_sha256": HARNESS_SHA256, "served_base_sha256": SERVED_BASE_SHA256}


def verify_completed_shard(final, cfg, shard, seed0, deals):
    """A completed shard directory against its manifest: the binding equal to this task's, every listed file present with its sha256 and no
    other file.  Returns the manifest, or raises SystemExit REFUSING (a completed shard is never silently recomputed)."""
    mp = os.path.join(final, "shard_manifest.json")
    if not os.path.isfile(mp):
        raise SystemExit(f"REFUSING: {final} exists without shard_manifest.json (not a completed shard; a .partial is the recoverable form)")
    m = json.load(open(mp))
    if m.get("schema") != SHARD_MANIFEST_SCHEMA or m.get("binding") != shard_binding(cfg, shard, seed0, deals):
        raise SystemExit(f"REFUSING: {final} was produced from another binding (window / plan / knobs / sources) than this run's")
    present = sorted(n for n in os.listdir(final) if n != "shard_manifest.json")
    if present != sorted(m["files"]):
        raise SystemExit(f"REFUSING: {final} holds {present}, its manifest lists {sorted(m['files'])}")
    bad = [n for n, sha in m["files"].items() if file_sha256(os.path.join(final, n)) != sha]
    if bad:
        raise SystemExit(f"REFUSING: {final}: {bad} differ from the shard manifest")
    return m


def shard_main(args):
    cfg, shard, seed0, deals, final = args
    root = os.path.dirname(final)
    partial = final + ".partial"
    if os.path.isdir(final):
        m = verify_completed_shard(final, cfg, shard, seed0, deals)
        return dict(m["counts"], shard=shard, seed0=seed0, deals=deals, skipped=True, secs=0.0, manifest_sha256=file_sha256(os.path.join(final, "shard_manifest.json")))
    if os.path.exists(partial):   # a worker died inside this shard: keep its partial files for diagnosis, recompute from the window
        kept = os.path.join(root, "diag", f"{os.path.basename(partial)}.{utc_stamp()}.{os.getpid()}")
        os.makedirs(os.path.dirname(kept), exist_ok=True)
        shutil.move(partial, kept)
    os.makedirs(partial)
    path = os.path.join(partial, "probe.jsonl")
    started = time.perf_counter()
    tot = dict(decisions=0, labelled=0, expert_dropped=0, self_rows=0)
    rows_e, rows_s, dkeys = [], [], []
    cfh = gzip.open(os.path.join(partial, "capsule.jsonl.gz"), "xb") if cfg["record_capsule"] else None
    with open(path, "x") as fh:
        fh.write(json.dumps(header_row(cfg, shard, seed0, deals)) + "\n")
        for dd in range(deals):
            deal = seed0 + dd
            r = play_deal(cfg, deal, cfg["plan_base"] + dd, fh, rows_e, rows_s, cfh)
            for k in tot:
                tot[k] += r[k]
            dkeys.append(r["deal_key"])
        if cfh is not None:
            cfh.close()
        n_e = write_rows(os.path.join(partial, "rows_expert"), rows_e)
        n_s = write_rows(os.path.join(partial, "rows_self"), rows_s)
        assert n_e == tot["labelled"] - tot["expert_dropped"] and n_s == tot["self_rows"], (n_e, n_s, tot)
        fh.write(json.dumps({"row": "end", "shard": shard, "deals": deals, **tot, "rows_expert": n_e, "rows_self": n_s, "secs": time.perf_counter() - started}) + "\n")
    counts = dict(tot, rows_expert=n_e, rows_self=n_s)
    files = {n: file_sha256(os.path.join(partial, n)) for n in sorted(os.listdir(partial))}
    manifest = {"schema": SHARD_MANIFEST_SCHEMA, "binding": shard_binding(cfg, shard, seed0, deals), "files": files, "counts": counts,
                "deal_keys": dkeys, "completed_at": utc_stamp(), "secs": time.perf_counter() - started}
    with open(os.path.join(partial, "shard_manifest.json"), "x") as fh:
        json.dump(manifest, fh, sort_keys=True)
        fh.write("\n")
    os.replace(partial, final)     # the completion: one atomic rename; the shard directory is immutable from here on
    return dict(counts, shard=shard, seed0=seed0, deals=deals, skipped=False, secs=time.perf_counter() - started, manifest_sha256=file_sha256(os.path.join(final, "shard_manifest.json")))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="output root (fresh: every shard's files are created exclusively)")
    ap.add_argument("--seed0", type=int, required=True)
    ap.add_argument("--deals", type=int, required=True, help="deals in all, split evenly over --shards")
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--late-trick", type=int, default=12, help="leads in tricks before this index (0-based) are always labelled")
    ap.add_argument("--late-lead-prob", type=float, default=1.0 / 3.0, help="label probability of a lead from --late-trick on")
    ap.add_argument("--prob-follow", type=float, default=0.07, help="label probability of a follow")
    ap.add_argument("--expert-cap-secs", type=float, default=60.0)
    ap.add_argument("--record-capsule", action="store_true", help="write the replay capsule of every kept labelled decision (HELD-OUT)")
    ap.add_argument("--resume", action="store_true", help="reopen an existing output root: verify and skip completed shards, recompute the rest, rebuild the summary")
    ap.add_argument("--served-env", action="append", default=[], help="TEST ONLY: SHENGJI_PV_X=V override for the served configuration")
    ap.add_argument("--expert-env", action="append", default=[], help="TEST ONLY: SHENGJI_PV_X=V override added to the expert's")
    a = ap.parse_args(argv)
    if a.deals % a.shards:
        raise SystemExit("REFUSING: --deals must divide evenly over --shards")
    per = a.deals // a.shards
    expert_env = dict(served_base.expert_env(os.environ))      # EXPERT_ENV, and the base's EXPERT_DROPS rules removed
    expert_env.update(dict(duel._parse_env(a.expert_env)))      # a TEST override replaces the expert's own value for that key
    cfg = dict(served_env=duel._parse_env(a.served_env), expert_env=tuple(sorted(expert_env.items())),
               late_trick=a.late_trick, late_lead_prob=a.late_lead_prob, prob_follow=a.prob_follow,
               expert_cap_secs=a.expert_cap_secs, record_capsule=bool(a.record_capsule))
    os.makedirs(a.out, exist_ok=True)
    summary = os.path.join(a.out, "summary.json")
    present = sorted(n for n in os.listdir(a.out) if n == "summary.json" or n == "diag" or n.startswith("shard-"))
    if present and not a.resume:
        raise SystemExit(f"REFUSING: {a.out} already holds {present[:3]}{'...' if len(present) > 3 else ''} (fresh runs only; pass --resume to reopen the output root)")
    if a.resume and os.path.exists(summary):
        kept = os.path.join(a.out, "diag", f"summary.json.{utc_stamp()}.{os.getpid()}")
        os.makedirs(os.path.dirname(kept), exist_ok=True)
        shutil.move(summary, kept)
    tasks = [(dict(cfg, plan_base=i * per), i, a.seed0 + i * per, per, os.path.join(a.out, f"shard-{i:02d}")) for i in range(a.shards)]
    t0 = time.time()
    if a.workers <= 1 or a.shards == 1:
        results = [shard_main(t) for t in tasks]
    else:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(min(a.workers, a.shards), maxtasksperchild=1) as pool:
            results = list(pool.imap_unordered(shard_main, tasks))
    results.sort(key=lambda r: r["shard"])
    if len(results) != a.shards or [r["shard"] for r in results] != list(range(a.shards)):
        raise SystemExit("REFUSING: not every shard returned")
    dn, _ = duel.variant_factory(cfg["served_env"])
    en, _ = duel.variant_factory(cfg["expert_env"])
    tot = {k: sum(r[k] for r in results) for k in ("decisions", "labelled", "expert_dropped", "self_rows", "rows_expert", "rows_self")}
    for r in results:    # every completed shard, skipped or recomputed, verifies against its manifest before the summary names it
        verify_completed_shard(os.path.join(a.out, f"shard-{r['shard']:02d}"), dict(cfg, plan_base=r["shard"] * per), r["shard"], r["seed0"], r["deals"])
    tmp = summary + ".tmp"
    with open(tmp, "w") as fh:
        json.dump({"schema": PROBE_SCHEMA + "-summary", "seed0": a.seed0, "deals": a.deals, "shards": a.shards, "workers": a.workers,
                   "served_name": dn, "expert_name": en, "served_env": [list(x) for x in cfg["served_env"]],
                   "expert_env": [list(x) for x in cfg["expert_env"]], "expert_cap_secs": a.expert_cap_secs,
                   "late_trick": a.late_trick, "late_lead_prob": a.late_lead_prob, "prob_follow": a.prob_follow, "record_capsule": bool(a.record_capsule),
                   "rows_units": ROWS_UNITS, "enc_version": int(ENC_VERSION), "input_dim": input_dim(ENC_VERSION),
                   "source_sha256": SOURCE_SHA256, "harness_sha256": HARNESS_SHA256, "served_base_sha256": SERVED_BASE_SHA256, "resumed": bool(a.resume), "shards_skipped": sum(1 for r in results if r["skipped"]),
                   **tot, "wall_secs": time.time() - t0, "shards_detail": results}, fh, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, summary)
    print(f"DONE deals {a.deals} decisions {tot['decisions']} labelled {tot['labelled']} expert_dropped {tot['expert_dropped']} "
          f"rows_expert {tot['rows_expert']} rows_self {tot['rows_self']} shards_skipped {sum(1 for r in results if r['skipped'])} wall {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
