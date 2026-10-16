"""Policy-head completion of the exact-lead first trick (OFF BY DEFAULT).

``SHENGJI_PV_EXACT_LEAD_POLICY_FIRST=1`` (token ``elp``; requires
``SHENGJI_PV_EXACT_LEAD_ENDGAME=1``; wiring and record keys:
`pv_search_policy.PVSearchBot._exact_lead_decision`).  The S18 exact lead
plays each candidate lead in each sampled world, lets the HEURISTIC complete
the rest of that first trick (`cwv_policy.afterstate(..., finish_trick=True)`)
and solves the remaining tricks by exact partnership minimax.  With this rule
on, the three responses of that first trick are the served POLICY HEAD's
argmax instead; the lead itself and the exact solve after the trick are
unchanged.

Information.  The policy input is world-conditioned: `policy_prior.root_tensors`
encodes the position's public observation from the seat's view
(``encode_obs``), plus a WORLD block holding all four hands and the kitty, and
the served bot averages its log-odds over worlds sampled from ITS OWN view.  A
responder must never be encoded on the leader's sampled world (that would show
it the other hands).  So each responder is encoded on ``view_worlds`` worlds
drawn from its own view of the position -- its hand in that world, the public
history including the lead and earlier responses, the kitty only when it is
the banker -- through production's sampler (`cwv_policy.sample_worlds` with a
`Memory` built for the responder) on a dedicated per-decision `MCBot` stream
(the served sampler's stream never moves); the log-odds are averaged over those
worlds (the served admission's preference) and the argmax over the responder's
COMPLETE legal follow set is played (`leaf_first_trick.best_follow`).  The
responder's refusal ledger is not reconstructed: failed-throw notices do not
constrain its view worlds beyond what the history shows.

Work sharing, exact by construction:

* positions (across worlds and candidates) where the responder holds the same
  INFORMATION STATE -- seat, own hand, the current trick's plays, the position's
  failed-throw notice, and the kitty when it is the banker; the history before
  the trick is the decision root's in every position -- share one view draw and
  one choice (a player decides on its information, never on hidden cards);
* the public block of the input row depends only on that information state, so
  it is encoded once per state (the first view world, by `root_tensors`) and
  each further view world's row replaces only the world block, filled exactly
  as `value_afterstate.tensors_from_round` fills it (tests compare these rows
  byte for byte with full `root_tensors` encodings).

A responder whose legal follow set has exactly one distinct action plays it
without a policy call (the argmax over one action; ``forced``).  A responder
whose view sampling, encoding, predictor call or choice fails plays the
heuristic (``fallbacks``).  One predictor call per response round (three per
lead), batched across all worlds and candidates.  The stage guard runs before
each response round, before each view draw and before each predictor call; an
expiry propagates to the exact-lead `OptionalStage`, which keeps the finalized
baseline decision.
"""
from __future__ import annotations

import itertools

import numpy as np

from ..ai.cwv_policy import afterstate, default_finisher, sample_worlds
from ..ai.mcbot import MCBot
from ..ai.memory import Memory
from ..harvest.legal import iter_follow_actions
from ..rl.value_afterstate import WORLD_RECEIVERS
from .cwv_prior_admission import root_clone
from .leaf_first_trick import best_follow

#: recipe-pinned parameters (enter the recipe digest with the rule on)
LIMITS = dict(view_worlds=8, view="responder-own-view-mcbot-sampler",
              player="policy-argmax-mean-log-odds", share="information-state",
              fallback="heuristic")


def _open_trick(position):
    return position.phase == "play" and position.trick is not None and bool(position.trick.plays)


def information_key(position, seat):
    """What ``seat`` knows at ``position`` beyond the shared decision root."""
    kitty = tuple(sorted(position.buried)) if seat == position.banker else ()
    return (seat, tuple(sorted(position.hands[seat])),
            tuple((play.seat, tuple(play.cards)) for play in position.trick.plays),
            repr(getattr(position, "message", None)), kitty)


def world_block(hands, buried, seat):
    """The input's world block, filled as `value_afterstate.tensors_from_round`."""
    from .policy_prior import CARD_INDEX, N_CARDS
    world = np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32)
    for relative in range(4):
        for card in hands[(seat + relative) % 4]:
            world[relative, CARD_INDEX[card]] += 0.5
    for card in buried:
        world[4, CARD_INDEX[card]] += 0.5
    return world.ravel()


def view_rows(position, seat, worlds, version):
    """One input row per view world: the first fully encoded, the rest with
    its world block substituted (module docstring)."""
    from .policy_prior import flat_input, root_tensors
    hands, buried = worlds[0]
    tensors = root_tensors(root_clone(position, hands, buried), seat, version)
    first = flat_input(tensors, version)
    start = tensors.public.size
    stop = start + tensors.world.size
    rows = [first]
    for hands, buried in worlds[1:]:
        row = first.copy()
        row[start:stop] = world_block(hands, buried, seat)
        rows.append(row)
    return rows


class ExactLeadPolicyFirst:
    """Builds every (world, candidate) leaf of one exact-lead pass in a batch.

    ``predict``/``version``: the bot's policy prior and encoder version;
    ``seed``: the per-decision view-sampler seed; ``check_budget``: the stage
    guard.  Counters (`counters`): ``policy_plays``, ``forced``,
    ``fallbacks`` (positions), ``views`` (information states drawn),
    ``view_worlds_drawn``, ``batches`` (predictor calls).
    """

    def __init__(self, predict, version: int, *, seed, check_budget=None,
                 view_worlds: int = LIMITS["view_worlds"]):
        if type(view_worlds) is not int or view_worlds < 1:
            raise ValueError("view_worlds must be a positive int")
        self.predict = predict
        self.version = int(version)
        self.check_budget = check_budget
        self.view_worlds = view_worlds
        self.sampler = MCBot(seed=seed)
        self.fallback = default_finisher()
        self.policy_plays = self.forced = self.fallbacks = 0
        self.views = self.view_worlds_drawn = self.batches = 0
        self._leaves = None

    def counters(self) -> dict:
        return dict(exact_lead_policy_plays=self.policy_plays,
                    exact_lead_policy_forced=self.forced,
                    exact_lead_policy_fallbacks=self.fallbacks,
                    exact_lead_policy_views=self.views,
                    exact_lead_policy_view_worlds=self.view_worlds_drawn,
                    exact_lead_policy_batches=self.batches)

    def _guard(self):
        if self.check_budget is not None:
            self.check_budget()

    def leaf_fn(self, rnd, seat, actions, worlds):
        """`pv_exact_endgame.exact_lead_means`'s ``leaf_fn``: on its first call
        (after that function validated the worlds) every leaf is built in one
        batch; each call returns its precomputed (world, candidate) leaf."""
        keys = [tuple(action) for action in actions]

        def leaf(world_root, leaf_seat, hands, buried, action, world_index):
            if leaf_seat != seat:
                raise ValueError("exact-lead policy leaf asked for another seat")
            if self._leaves is None:
                self._leaves = self.build(rnd, seat, actions, worlds)
            return self._leaves[world_index][keys.index(tuple(action))]
        return leaf

    def build(self, rnd, seat, actions, worlds):
        """``leaves[w][k]``: candidate ``k`` led in world ``w`` (the clone and
        lead of `PolicyValueBot._leaf`), its first trick completed here."""
        leaves = [[afterstate(root_clone(rnd, hands, buried), seat, hands, buried, list(action))
                   for action in actions] for hands, buried in worlds]
        self.complete([leaf for row in leaves for leaf in row])
        return leaves

    @staticmethod
    def _forced(position, seat):
        options = list(itertools.islice(iter_follow_actions(
            list(position.hands[seat]), list(position.trick.plays[0].cards),
            position.ordering), 2))
        return list(options[0]) if len(options) == 1 else None

    def _view(self, position, seat):
        """The responder's own-view rows, or None on any failure."""
        try:
            mem = Memory(position, seat, own_kitty=getattr(self.sampler, "BANKER_KITTY", True))
            worlds, _ = sample_worlds(self.sampler, position, seat, self.view_worlds, mem=mem)
            if not worlds:
                return None
            rows = view_rows(position, seat, worlds, self.version)
        except Exception:
            return None
        self.views += 1
        self.view_worlds_drawn += len(rows)
        return rows

    def _log_odds(self, rows):
        from .policy_prior import N_CARDS
        try:
            out = np.asarray(self.predict(np.stack(rows).astype(np.float32)), dtype=np.float64)
        except Exception:
            return None
        if out.shape != (len(rows), N_CARDS) or not np.isfinite(out).all():
            return None
        return out

    def complete(self, positions):
        """Complete the open first trick at every position (mutates them)."""
        from .policy_prior import CARD_INDEX
        while True:
            open_positions = [p for p in positions if _open_trick(p)]
            if not open_positions:
                break
            self._guard()
            plays, groups, rows = [], {}, []
            for position in open_positions:
                seat = position.turn
                forced = self._forced(position, seat)
                if forced is not None:
                    plays.append((position, seat, forced))
                    continue
                key = information_key(position, seat)
                if key not in groups:
                    self._guard()
                    view = self._view(position, seat)
                    span = None
                    if view is not None:
                        span = slice(len(rows), len(rows) + len(view))
                        rows.extend(view)
                    groups[key] = [position, span, []]
                groups[key][2].append(position)
            self._guard()   # no predictor call starts past the deadline
            log_odds = self._log_odds(rows) if rows else None
            if log_odds is not None:
                self.batches += 1
            choices = {}
            for key, (first, span, _members) in groups.items():
                action = None
                if span is not None and log_odds is not None:
                    try:
                        action = best_follow(first.hands[key[0]], first.trick.plays[0].cards,
                                             first.ordering, log_odds[span].mean(axis=0),
                                             CARD_INDEX)
                    except Exception:
                        action = None
                choices[key] = action
            for position, seat, forced in plays:
                self.forced += 1
                position.play(seat, list(forced))
            for key, (_first, _span, members) in groups.items():
                for position in members:
                    seat = key[0]
                    action = choices[key]
                    if action is None:
                        self.fallbacks += 1
                        action = self.fallback.decide_play(position, seat)
                    else:
                        self.policy_plays += 1
                    position.play(seat, list(action))
        self._guard()


__all__ = ["LIMITS", "ExactLeadPolicyFirst", "information_key", "view_rows", "world_block"]
