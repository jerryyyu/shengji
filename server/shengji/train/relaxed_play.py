"""Relaxed opponents: a weaker card play for the opposing seats of a casual room.

A relaxed seat is ``RelaxedBot(served, player, ...)``: declaring and burying are the served bot's
(``served``), card play is ``player``'s under one of three play modes:

``search``
    ``player`` is a `PVSearchBot` built with weaker knobs (fewer worlds, fewer candidates, the
    constraint-only world draw in place of the learned belief).  Its search runs as served; with
    ``tau > 0`` the play is then re-drawn among the admitted candidates whose search value is
    within ``delta`` of the best, with probability proportional to ``exp((v - best) / tau)``
    (the "near-best" rule: a play worse than the best by more than ``delta`` is never drawn).
``prior``
    no value search: ``player`` draws its worlds and the policy prior scores every legal play on
    them (the served admission's ranking, the sum of the play's card log-odds averaged over the
    worlds); the top play, or with ``tau > 0`` a softmax draw among plays within ``delta`` of the top.
``search_free``
    no worlds and no search: `search_free_play.SearchFreeBot` (one model forward); the top
    candidate, or with ``tau > 0`` a softmax draw over the candidate head's logits within ``delta``.

A multi-card lead other than the heuristic's own that a single opponent holding the whole unseen
pool could refuse is never drawn by the prior or the softmax (a relaxed bot should not make
throws an attentive player knows to be unsafe).  Every draw uses the bot's own seeded stream, so a
seeded relaxed bot is repeatable.  The partners of a human keep the served bot; nothing here
changes a served decision, a served name or a recipe digest, and nothing imports this module
unless a relaxed level is built.

``LEVELS`` names measured levels that keep the served search size: the env overrides applied when
building ``player`` from the served environment, the play mode and its ``tau`` / ``delta`` (levels
that change the world or candidate count stay in the duel kit).  Legacy levels (``bot``) are whole
older bots (their own declare and bury), built by name through the registry.
"""
from __future__ import annotations

import math
import random
import time
from typing import Any, Mapping, Sequence

import numpy as np

RECORD_SCHEMA = "relaxed-decision-v1"
MODES = ("search", "prior", "search_free")
SEED_SALT = 0x5E1A7ED

#: the measured levels; "env" are SHENGJI_PV_* overrides on the served environment ("" removes a key)
LEVELS: dict[str, dict[str, Any]] = {
    "s136": {"mode": "search_free", "tau": 0.0, "delta": 0.0, "env": {}},
    "nobel": {"mode": "search", "tau": 0.0, "delta": 0.0,
              "env": {"SHENGJI_PV_BELIEF_WORLDS": "0", "SHENGJI_PV_BURY_BELIEF_WORLDS": "0",
                        "SHENGJI_PV_BELIEF_CKPT": "", "SHENGJI_PV_BELIEF_SHA256": ""}},
    "smart": {"bot": "smart"},
    "mclcb": {"bot": "mc-s0-report-lcb"},
}


class RelaxedPlayError(ValueError):
    pass


def near_best(values: Sequence[float], tau: float, delta: float, rng: random.Random,
              allowed: Sequence[bool] | None = None, keep: int | None = None) -> int:
    """The index to play.  ``tau == 0``: ``keep`` if given (the player's own choice), else the
    first maximum.  Otherwise a draw among allowed indices with ``v >= best - delta`` (``delta``
    <= 0 means no cut), weights ``exp((v - best) / tau)``; ``best`` is the allowed maximum."""
    v = [float(x) for x in values]
    if not v or not all(math.isfinite(x) for x in v):
        raise RelaxedPlayError("near_best needs finite values")
    ok = list(allowed) if allowed is not None else [True] * len(v)
    if keep is not None:
        ok[keep] = True
    idx = [i for i in range(len(v)) if ok[i]]
    if not idx:
        raise RelaxedPlayError("no allowed play")
    best = max(v[i] for i in idx)
    if tau <= 0:
        if keep is not None:
            return keep
        return next(i for i in idx if v[i] == best)
    if delta > 0:
        idx = [i for i in idx if v[i] >= best - delta]
    weights = [math.exp((v[i] - best) / tau) for i in idx]
    return rng.choices(idx, weights=weights, k=1)[0]


def _safe_leads(rnd, seat, actions, anchor) -> list[bool]:
    """Per action: False for a multi-card lead (not the anchor) that one opponent holding the
    whole unseen pool could refuse."""
    if rnd.trick.plays:
        return [True] * len(actions)
    from ..ai.memory import Memory
    from ..engine.legal import validate_lead
    anchor_key = tuple(sorted(anchor))
    pool = None
    out = []
    for a in actions:
        if len(a) <= 1 or tuple(sorted(a)) == anchor_key:
            out.append(True)
            continue
        if pool is None:
            pool = list(Memory(rnd, seat, own_kitty=True).unseen.elements())
        _, message = validate_lead(list(a), list(rnd.hands[seat]), [pool, [], []], rnd.ordering)
        out.append(message is None)
    return out


class RelaxedBot:
    """``served`` declares and buries; ``player`` plays under ``mode`` (module docstring).  Every
    public notice reaches both bots."""

    def __init__(self, served, player, *, mode: str, tau: float = 0.0, delta: float = 0.0,
                 seed: int = 0, policy_name: str | None = None):
        if mode not in MODES:
            raise RelaxedPlayError(f"mode must be one of {MODES}")
        if not (tau >= 0 and delta >= 0 and math.isfinite(tau) and math.isfinite(delta)):
            raise RelaxedPlayError("tau and delta are finite and >= 0")
        self.served, self.player = served, player
        self.mode, self.tau, self.delta = mode, float(tau), float(delta)
        self.rng = random.Random((int(seed) * 1_000_003) ^ SEED_SALT)
        self.policy_name = policy_name or (
            f"{getattr(served, 'policy_name', type(served).__name__)}+relaxed:"
            f"{getattr(player, 'policy_name', type(player).__name__)}:{mode}:t{tau:g}:d{delta:g}")
        self.last_decision_record = None
        self.relaxed_decisions = 0
        self.relaxed_redrawn = 0

    def __getattr__(self, name):
        if name in ("served", "player") or name.startswith("__"):
            raise AttributeError(name)
        return getattr(self.served, name)

    def observe_public(self, rnd) -> None:
        observe = getattr(self.served, "observe_public", None)
        if observe is not None:
            observe(rnd)
        if getattr(self.player, "base", None) is self.served:
            # a search-free player wrapping the served bot: its own ledger only, so the
            # served bot reads each notice once
            self.player._ledger.observe(rnd)
            return
        observe = getattr(self.player, "observe_public", None)
        if observe is not None:
            observe(rnd)

    def decide_declare(self, rnd, seat, final=False):
        return self.served.decide_declare(rnd, seat, final=final)

    def decide_bury(self, rnd, seat):
        return self.served.decide_bury(rnd, seat)

    def decide_play(self, rnd, seat):
        started = time.perf_counter()
        self.last_decision_record = None
        if self.mode == "search":
            played, rec = self._search_play(rnd, seat)
        elif self.mode == "prior":
            played, rec = self._prior_play(rnd, seat)
        else:
            played, rec = self._search_free_play(rnd, seat)
        self.relaxed_decisions += 1
        rec = dict(rec, schema=rec.get("schema", RECORD_SCHEMA), policy=self.policy_name,
                   mode=self.mode, played=list(played), seconds=time.perf_counter() - started)
        self.last_decision_record = rec
        return list(played)

    def _search_play(self, rnd, seat):
        played = list(self.player.decide_play(rnd, seat))
        inner = self.player.last_decision_record
        rec = dict(inner) if isinstance(inner, dict) else {}
        rec["relaxed_inner_schema"] = rec.get("schema")
        if self.tau <= 0 or rec.get("schema") != "pv-search-decision-v1":
            rec["relaxed_redrawn"] = False
            return played, rec
        means, admitted = rec.get("value_means") or [], rec.get("admitted") or []
        chosen = rec.get("admitted_indices") or []
        sel = rec.get("selected_index")
        if (len(admitted) < 2 or len(means) != len(admitted) or any(m is None for m in means)
                or sel not in chosen):
            rec["relaxed_redrawn"] = False
            return played, rec
        keep = chosen.index(sel)
        anchor = admitted[0]
        allowed = _safe_leads(rnd, seat, admitted, anchor)
        pick = near_best(means, self.tau, self.delta, self.rng, allowed=allowed)
        rec["relaxed_redrawn"] = pick != keep
        rec["relaxed_pick"] = pick
        if pick != keep:
            self.relaxed_redrawn += 1
            played = list(admitted[pick])
        return played, rec

    def _prior_play(self, rnd, seat):
        from ..ai.heuristic import HeuristicBot
        p = self.player
        anchor = list(HeuristicBot.decide_play(p, rnd, seat))
        try:
            legal = p._legal(rnd, seat, [anchor])
            actions = [list(a) for a in legal.actions]
            worlds, _ = p._worlds(rnd, seat)
            prefs = np.asarray(p.scores(rnd, seat, actions, worlds), np.float64).mean(axis=0)
            allowed = _safe_leads(rnd, seat, actions, anchor)
            if self.tau <= 0:
                idx = [i for i in range(len(actions)) if allowed[i]]
                pick = max(idx, key=lambda i: (prefs[i], -i))
            else:
                pick = near_best(prefs, self.tau, self.delta, self.rng, allowed=allowed)
            top = max(range(len(actions)), key=lambda i: (prefs[i] if allowed[i] else -math.inf, -i))
        except Exception as exc:  # the heuristic's play, as the served budget fallback
            return anchor, {"schema": "relaxed-fallback-v1", "reason": "prior-error",
                            "error_class": type(exc).__name__, "error_message": str(exc)[:200]}
        return actions[pick], {"worlds": len(worlds), "legal": len(actions),
                               "anchor_selected": tuple(sorted(actions[pick])) == tuple(sorted(anchor)),
                               "relaxed_redrawn": pick != top, "top_margin": float(prefs[top] - prefs[pick])}

    def _search_free_play(self, rnd, seat):
        from ..ai.heuristic import HeuristicBot
        from . import search_free_play as SF
        p = self.player
        if not isinstance(p, SF.SearchFreeBot):
            raise RelaxedPlayError("search_free mode plays a SearchFreeBot")
        if self.tau <= 0:
            played = list(p.decide_play(rnd, seat))
            inner = dict(p.last_decision_record or {})
            inner["relaxed_inner_schema"] = inner.get("schema")
            inner.pop("schema", None)
            if inner.get("relaxed_inner_schema") == SF.FALLBACK_SCHEMA:
                inner["schema"] = "relaxed-fallback-v1"
            inner["relaxed_redrawn"] = False
            return played, inner
        anchor = list(HeuristicBot.decide_play(p._heuristic, rnd, seat))
        try:
            refusals = p._ledger.observe(rnd)
            prop, _, logits = p._scored_proposal(rnd, seat, anchor, refusals)
            actions = prop["actions"]
            if len(actions) == 1:
                return actions[0], {"candidates": 1, "relaxed_redrawn": False}
            top = int(np.argmax(logits))
            pick = near_best(logits, self.tau, self.delta, self.rng)
        except Exception as exc:
            return anchor, {"schema": "relaxed-fallback-v1", "reason": "search-free-error",
                            "error_class": type(exc).__name__, "error_message": str(exc)[:200]}
        return actions[pick], {"candidates": len(actions), "relaxed_redrawn": pick != top,
                               "top_margin": float(logits[top] - logits[pick]),
                               "anchor_selected": pick == 0}


def level_spec(level: str) -> Mapping[str, Any]:
    try:
        return LEVELS[level]
    except KeyError:
        raise RelaxedPlayError(f"unknown relaxed level {level!r}; known: {sorted(LEVELS)}") from None


# ------------------------------------------------------------------ the casual level

#: the level a casual room's Bots "Standard" serves: the S136 search-free scorer's card
#: play with a near-best softmax (tau 1.0, delta 4.0 logits), the served declare and bury
CASUAL_PACKAGE = "sf-s136-516617b8.npz"
CASUAL_SHA256 = "516617b893689a931977068a1a536735afdb1edff0979f6f2360588291a8d184"
CASUAL_TAU = 1.0
CASUAL_DELTA = 4.0
_CASUAL_MODELS: dict = {}


def casual_suffix(sha256: str = CASUAL_SHA256, tau: float = CASUAL_TAU, delta: float = CASUAL_DELTA) -> str:
    """The token a casual relaxed bot appends to the served name, so its policy never equals it."""
    return f"relax-sf{sha256[:8]}-t{tau:g}-d{delta:g}"


def casual_model(path, sha256: str = CASUAL_SHA256):
    """The search-free model at ``path``, sha256-checked, loaded once per process (read-only)."""
    key = (str(path), sha256)
    if key not in _CASUAL_MODELS:
        from . import search_free_play as SF
        _CASUAL_MODELS[key] = SF.load_package(path, sha256=sha256)
    return _CASUAL_MODELS[key]


def build_casual(served, path, *, seed: int, sha256: str = CASUAL_SHA256,
                 tau: float = CASUAL_TAU, delta: float = CASUAL_DELTA) -> RelaxedBot:
    """``served`` declares and buries; the search-free scorer plays with near-best noise."""
    from . import search_free_play as SF
    player = SF.SearchFreeBot(served, casual_model(path, sha256))
    name = f"{getattr(served, 'policy_name', type(served).__name__)}-{casual_suffix(sha256, tau, delta)}"
    return RelaxedBot(served, player, mode="search_free", tau=tau, delta=delta, seed=seed, policy_name=name)


#: the Beginner level: the casual level's package, declare and bury, with wider card-play noise
#: (tau 3.0 within delta 8.0 logits). Its team loses 0.58 levels/round to a Standard team on
#: paired seat-swapped rank-mixed deals; every play still comes from the scorer's legal proposals.
BEGINNER_TAU = 3.0
BEGINNER_DELTA = 8.0


def build_beginner(served, path, *, seed: int, sha256: str = CASUAL_SHA256) -> RelaxedBot:
    """``build_casual`` at the Beginner noise (``BEGINNER_TAU``, ``BEGINNER_DELTA``)."""
    return build_casual(served, path, seed=seed, sha256=sha256, tau=BEGINNER_TAU, delta=BEGINNER_DELTA)
