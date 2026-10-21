"""Prefix-cached encoding of a served decision's value leaves and prior roots.

``SHENGJI_PV_ENCODE_PREFIX_CACHE=1`` (OFF by default; no name, payload or
decision reads it) routes `PVSearchBot._score_leaves` and `PVSearchBot.scores`
through this module.  Every tensor it returns is the reference encoder's
tensor byte for byte:

* Value leaves.  Every leaf of one decision is a clone of the decision root,
  so its ``history`` starts with the root's ``history`` list of complete tricks
  (the same objects).  `HistoryPrefix` runs the fused static builder's
  traversal (`ai.cwv_static_encoding._fused_static_tensors`) over that shared
  prefix ONCE; each leaf then applies its own suffix (its later complete
  tricks and its current trick) and its own seat/hand projection (world
  planes, perspective, the acting seat's hand) exactly as the reference does.
  No ``Memory`` and no whole-leaf state is shared between leaves.  The
  traversal's float updates are half-copy increments, which are exact, and the
  prefix is applied in its original order, so the planes are the reference's.
  A leaf whose history does not extend the prefix by identity, or any state
  the fused builder would refuse, is encoded by the reference encoder.
* Prior roots.  Every root clone of one decision shares the decision's
  history, current trick and acting seat's hand; only the hidden hands and the
  kitty differ, and the public block reads them only through hand lengths.  The
  first world is encoded by the reference (`policy_prior.root_tensors`); a
  later world reuses its public block only when its acting hand and hand
  lengths equal the first world's, and adds its own world planes.

Validation is batched: the per-row ``validate`` calls of the reference are
replaced by one check over the stacked rows that implies every per-row check.
Any exception inside the fast path, a failed batch check or an unsupported
encoder, evaluator or version re-encodes the WHOLE call through the reference,
so a refusal is the reference's refusal, raised at the reference's row.
"""
from __future__ import annotations

import time
from functools import partial

import numpy as np

from ..ai.cwv_policy import CompleteWorldEvaluator
from ..ai.cwv_static_encoding import _v2_static_columns, tensors_from_round_static
from ..engine.cards import Ordering
from ..engine.round import Round, Trick, TrickPlay
from ..rl.encode import CARD_INDEX, N_CARDS, OBS_DIM, RANKS, SUITS, TRUMP
from ..rl.encode_next_actor import next_actor_columns
from ..rl.encode_versions import OBS_DIM_BY_VERSION
from ..rl.public_history import HISTORY_EVENT_DIM, HISTORY_MAX_EVENTS
from ..rl.value_afterstate import (PUBLIC_DIM, WORLD_RECEIVERS, ValueAfterstateTensors,
                                   terminal_distribution)
from ..rl.value_afterstate_v2 import PUBLIC_DIM_BY_VERSION, ValueAfterstateTensorsV2

#: encoder versions whose static value route and root public block this
#: module reproduces; any other version takes the reference path
VERSIONS = (1, 2, 7)
_V2_WIDTHS = frozenset(dim for version, dim in PUBLIC_DIM_BY_VERSION.items() if version >= 2)


def _traverse(trick, eff_suit, played, played_total, physical, voids, trick_planes):
    """The fused builder's per-trick loop: the trick's event count, or None where
    the builder returns None.  Mutates the accumulators exactly as it does."""
    lead_suit = None
    events = 0
    for position, play in enumerate(trick.plays):
        if (type(play) is not TrickPlay or type(play.cards) is not list
                or not play.cards or type(play.seat) is not int
                or not 0 <= play.seat < 4):
            return None
        events += 1
        plane = played[play.seat]
        off_suit = False
        for card in play.cards:
            if type(card) is not str:
                return None
            index = CARD_INDEX[card]
            suit = eff_suit(card)
            if lead_suit is None:
                lead_suit = suit
            if position and suit != lead_suit:
                off_suit = True
            plane[index] += 0.5
            played_total[index] += 0.5
            physical[index] += 1
            if trick_planes is not None:
                trick_planes[position][index] += 0.5
        if off_suit:
            voids[play.seat].add(lead_suit)
    return events


class HistoryPrefix:
    """The fused traversal of one decision root's complete tricks."""

    __slots__ = ("tricks", "ordering", "played", "played_total", "physical", "voids", "events")

    def __init__(self, tricks, ordering, played, played_total, physical, voids, events):
        self.tricks = tricks
        self.ordering = ordering
        self.played = played
        self.played_total = played_total
        self.physical = physical
        self.voids = voids
        self.events = events

    @classmethod
    def of(cls, rnd):
        """The prefix of ``rnd.history``, or None where the fused builder would
        refuse any state extending it (every leaf then takes the reference)."""
        try:
            if type(rnd) is not Round or type(rnd.ordering) is not Ordering \
                    or type(rnd.history) is not list:
                return None
            eff_suit = rnd.ordering.eff_suit
            played = [[0.0] * N_CARDS for _ in range(4)]
            played_total = [0.0] * N_CARDS
            physical = [0] * N_CARDS
            voids = [set() for _ in range(4)]
            events = 0
            tricks = tuple(rnd.history)
            for trick in tricks:
                if type(trick) is not Trick or type(trick.plays) is not list \
                        or len(trick.plays) != 4:
                    return None
                count = _traverse(trick, eff_suit, played, played_total, physical, voids, None)
                if count is None:
                    return None
                events += count
            return cls(tricks, rnd.ordering, played, played_total, physical, voids, events)
        except Exception:
            return None

    def fused(self, rnd, seat):
        """``(public, world, perspective)`` of `_fused_static_tensors(rnd, seat)`
        before its ``validate``, or None where it returns None or ``rnd`` does
        not extend this prefix."""
        try:
            if (type(rnd) is not Round or type(seat) is not int or not 0 <= seat < 4
                    or rnd.phase != "play" or type(rnd.ordering) is not Ordering
                    or type(rnd.history) is not list or type(rnd.hands) is not list
                    or len(rnd.hands) != 4 or type(rnd.buried) is not list
                    or type(rnd.banker) is not int or not 0 <= rnd.banker < 4
                    or type(rnd.attacker_points) is not int
                    or type(rnd.trump_is_nt) is not bool or rnd.trump_rank not in RANKS
                    or type(rnd.trick) is not Trick or type(rnd.trick.plays) is not list
                    or len(rnd.trick.plays) > 3):
                return None
            declaration = rnd.declaration
            if declaration is not None:
                if (type(declaration) is not dict
                        or type(declaration.get("seat")) is not int
                        or not 0 <= declaration["seat"] < 4
                        or type(declaration.get("cards")) is not list
                        or not declaration["cards"]
                        or any(type(card) is not str or card not in CARD_INDEX
                               for card in declaration["cards"])):
                    return None
            history = rnd.history
            prefix = self.tricks
            if rnd.ordering is not self.ordering or len(history) < len(prefix):
                return None
            for index, trick in enumerate(prefix):
                if history[index] is not trick:
                    return None

            physical = list(self.physical)
            world = [[0.0] * N_CARDS for _ in range(WORLD_RECEIVERS)]
            for relative in range(WORLD_RECEIVERS):
                cards = (rnd.hands[(seat + relative) % 4] if relative < 4 else rnd.buried)
                if type(cards) is not list:
                    return None
                plane = world[relative]
                for card in cards:
                    if type(card) is not str:
                        return None
                    index = CARD_INDEX[card]
                    plane[index] += 0.5
                    physical[index] += 1

            eff_suit = rnd.ordering.eff_suit
            played = [list(plane) for plane in self.played]
            played_total = list(self.played_total)
            voids = [set(suits) for suits in self.voids]
            trick_planes = [[0.0] * N_CARDS for _ in range(3)]
            events = self.events
            for trick in history[len(prefix):]:
                if type(trick) is not Trick or type(trick.plays) is not list \
                        or len(trick.plays) != 4:
                    return None
                count = _traverse(trick, eff_suit, played, played_total, physical, voids, None)
                if count is None:
                    return None
                events += count
            count = _traverse(rnd.trick, eff_suit, played, played_total, physical, voids,
                              trick_planes)
            if count is None:
                return None
            events += count
            # every physical count is an int, so this is ``any(n != 2 ...)``
            if not 1 <= events <= HISTORY_MAX_EVENTS or physical.count(2) != N_CARDS:
                return None

            obs = list(world[0])
            for relative in range(4):
                obs.extend(played[(seat + relative) % 4])
            for plane in trick_planes:
                obs.extend(plane)
            obs.extend([max(0.0, 1.0 - seen - own)
                        for seen, own in zip(played_total, world[0])])
            suit_onehot = [0.0] * 5
            if rnd.trump_is_nt:
                suit_onehot[4] = 1.0
            elif rnd.trump_suit in SUITS:
                suit_onehot[SUITS.index(rnd.trump_suit)] = 1.0
            obs.extend(suit_onehot)
            rank_onehot = [0.0] * 13
            rank_onehot[RANKS.index(rnd.trump_rank)] = 1.0
            obs.extend(rank_onehot)
            banker_rel = [0.0] * 4
            banker_rel[(rnd.banker - seat) % 4] = 1.0
            obs.extend(banker_rel)
            root_is_attacker = rnd.is_attacker(seat)
            obs.extend((min(rnd.attacker_points, 200) / 200.0,
                        sum(len(hand) for hand in rnd.hands) / 100.0,
                        float(root_is_attacker)))
            for relative in range(4):
                for suit in [*SUITS, TRUMP]:
                    obs.append(float(suit in voids[(seat + relative) % 4]))
            if len(obs) != OBS_DIM:
                return None
            return (np.asarray([*obs, 0.0], dtype=np.float32),
                    np.asarray(world, dtype=np.float32),
                    np.asarray([float(root_is_attacker), float(not root_is_attacker)],
                               dtype=np.float32))
        except Exception:
            return None


def _widened(version, public, world, perspective, rnd, seat):
    """The static route's tensor for a fused base: `tensors_from_round_static`'s
    v1 return, or `_widen_v2_static` / `_widen_v7_static` without ``validate``."""
    base = ValueAfterstateTensors(public, np.zeros((1, HISTORY_EVENT_DIM), dtype=np.float32),
                                  world, perspective)
    if version == 1:
        return base
    columns = _v2_static_columns(base, rnd, seat)
    if version == 7:
        columns = [*columns, *next_actor_columns(rnd, seat)]
    obs_dim = OBS_DIM_BY_VERSION[1]
    extra = np.asarray(columns, dtype=np.float32)
    widened = np.concatenate((base.public[:obs_dim], extra, base.public[obs_dim:]))
    return ValueAfterstateTensorsV2(widened, base.history, base.world, base.perspective)


def _valid_batch(rows, version) -> bool:
    """One check over the fast rows that implies the reference's per-row
    ``validate`` of the fused base (v1) and of its widening (v2 and later)."""
    if not rows:
        return True
    try:
        public = np.stack([row.public for row in rows])
        world = np.stack([row.world for row in rows])
        perspective = np.stack([row.perspective for row in rows])
    except ValueError:      # rows of different shapes
        return False
    widths = PUBLIC_DIM if version == 1 else None
    if public.dtype != np.float32 or world.dtype != np.float32 \
            or perspective.dtype != np.float32:
        return False
    if public.ndim != 2 or (public.shape[1] != widths if widths is not None
                            else public.shape[1] not in _V2_WIDTHS):
        return False
    if world.shape[1:] != (WORLD_RECEIVERS, N_CARDS) or perspective.shape[1:] != (2,):
        return False
    return bool(np.isfinite(public).all()
                and ((world == 0.0) | (world == 0.5) | (world == 1.0)).all()
                and ((perspective == 0.0) | (perspective == 1.0)).all()
                and (perspective.sum(axis=1) == 1.0).all())


def static_version(encoder):
    """The encoder version of the served static value route, or None for any
    other encoder (a diagnostic override, the reference builder)."""
    if encoder is tensors_from_round_static:
        return 1
    if (isinstance(encoder, partial) and encoder.func is tensors_from_round_static
            and not encoder.args and set(encoder.keywords) == {"version"}
            and encoder.keywords["version"] in VERSIONS):
        return encoder.keywords["version"]
    return None


def _plain_evaluator(evaluator) -> bool:
    cls = type(evaluator)
    return (isinstance(evaluator, CompleteWorldEvaluator)
            and cls.score is CompleteWorldEvaluator.score
            and cls.score_many is CompleteWorldEvaluator.score_many)


def encode_leaves(evaluator, positions, root_seat, prefix):
    """``(values, rows, pending, fast)`` for `score_leaves`: the terminal values
    filled in ``values``, the model rows in position order with their indices,
    and how many rows the prefix built; None when the call must take the
    reference path whole (an unsupported evaluator, encoder or seat, any
    exception, a failed batch check)."""
    if prefix is None or not _plain_evaluator(evaluator) or type(root_seat) is not int \
            or not 0 <= root_seat < 4:
        return None
    version = static_version(evaluator.encoder)
    if version is None:
        return None
    reference = evaluator.encoder
    try:
        values = np.empty(len(positions), dtype=np.float64)
        rows, pending, fast = [], [], []
        for index, rnd in enumerate(positions):
            if rnd.phase == "round_end":
                values[index] = float(
                    terminal_distribution(rnd, root_seat) @ evaluator.support)
                continue
            parts = prefix.fused(rnd, root_seat)
            if parts is None:
                rows.append(reference(rnd, root_seat))
            else:
                row = _widened(version, *parts, rnd, root_seat)
                rows.append(row)
                fast.append(row)
            pending.append(index)
        if not _valid_batch(fast, version):
            return None
    except Exception:
        return None
    return values, rows, pending, len(fast)


def score_leaves(evaluator, positions, root_seat, prefix):
    """``evaluator.score(positions, root_seat)``, its leaves encoded on ``prefix``.

    The terminal rows, the row order, the forward pass and the evaluator's
    counters are `CompleteWorldEvaluator.score_many`'s.
    """
    wall0, cpu0 = time.perf_counter(), time.process_time()
    n = len(positions)
    encoded = encode_leaves(evaluator, positions, root_seat, prefix) if n else None
    if encoded is None:
        return evaluator.score(positions, root_seat)
    values, rows, pending, _ = encoded
    if rows:
        values[pending] = evaluator.probabilities(rows) @ evaluator.support
    evaluator.calls += 1
    evaluator.positions += n
    evaluator.model_rows += len(rows)
    evaluator.terminal_rows += n - len(rows)
    evaluator.wall_secs += time.perf_counter() - wall0
    evaluator.cpu_secs += time.process_time() - cpu0
    return values


def prior_rows(rnd, seat, worlds, version):
    """`PVSearchBot.scores`' prior input, ``(len(worlds), input_dim(version))``
    float32: one ``flat_input(root_tensors(root_clone(...)))`` row per world."""
    # lazy: policy_prior -> harvest.rebuild -> registry is a cycle at import time
    from .cwv_prior_admission import root_clone
    from .policy_prior import flat_input, root_tensors

    def reference():
        return np.stack([flat_input(root_tensors(root_clone(rnd, hands, buried), seat, version),
                                    version)
                         for hands, buried in worlds]).astype(np.float32)

    if version not in VERSIONS or type(seat) is not int or not 0 <= seat < 4 \
            or len(worlds) < 2:
        return reference()
    try:
        hands0, buried0 = worlds[0]
        first = root_tensors(root_clone(rnd, hands0, buried0), seat, version)
        rows = [flat_input(first, version)]
        own = list(hands0[seat])
        lengths = [len(list(hand)) for hand in hands0]
        public = first.public.ravel()
        perspective = first.perspective.ravel()
        planes = []
        for hands, buried in worlds[1:]:
            hands = [list(hand) for hand in hands]
            if len(hands) != 4 or hands[seat] != own or [len(h) for h in hands] != lengths:
                return reference()
            world = [[0.0] * N_CARDS for _ in range(WORLD_RECEIVERS)]
            for relative in range(4):
                plane = world[relative]
                for card in hands[(seat + relative) % 4]:
                    plane[CARD_INDEX[card]] += 0.5
            for card in list(buried):
                world[4][CARD_INDEX[card]] += 0.5
            planes.append(np.asarray(world, dtype=np.float32))
        stacked = np.stack(planes)
        if not bool(((stacked == 0.0) | (stacked == 0.5) | (stacked == 1.0)).all()):
            return reference()
        for plane in planes:
            rows.append(np.concatenate([public, plane.ravel(), perspective]).astype(np.float32))
        x = np.stack(rows).astype(np.float32)
        if x.shape != (len(worlds), rows[0].shape[0]):
            return reference()
        return x
    except Exception:
        return reference()


__all__ = ["VERSIONS", "HistoryPrefix", "encode_leaves", "prior_rows", "score_leaves",
           "static_version"]
