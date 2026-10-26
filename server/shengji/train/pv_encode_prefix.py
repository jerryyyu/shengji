"""Prefix-cached encoding of a served decision's value leaves and prior roots.

``SHENGJI_PV_ENCODE_PREFIX_CACHE=1`` (OFF by default; no name, payload or
decision reads it) routes `PVSearchBot._score_leaves`, `PVSearchBot.scores`
and the ``lgf`` greedy finish's reply plies through this module.  Every tensor
it returns is the reference encoder's tensor byte for byte:

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
  `fused_many` builds a batch of such leaves at once: the prefix planes are
  laid down for the whole batch, each row adds its suffix deltas and its world
  planes (one plane per distinct hand), and the public block is assembled as
  arrays; every entry is a sum of half copies or the fused builder's own
  scalar expression, so the float32 casts see the same doubles.
* Reply policy rows.  The ``lgf`` reply ply's clones extend the root's
  history by identity too; `reply_rows` builds their
  ``flat_input(root_tensors(...))`` rows from `fused_many`, whose static
  tensor is the reference builder's for every state it covers.
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
from collections import Counter, defaultdict
from functools import partial
from operator import is_ as _is

import numpy as np

from ..ai.cwv_policy import CompleteWorldEvaluator
from ..ai.cwv_static_encoding import _v2_static_columns, tensors_from_round_static
from ..engine.cards import Ordering
from ..engine.round import Round, Trick, TrickPlay
from ..rl.encode import CARD_INDEX, N_CARDS, OBS_DIM, RANKS, SUITS, TRUMP
from ..rl.encode_next_actor import next_actor_columns, next_actor_rel
from ..rl.encode_versions import OBS_DIM_BY_VERSION, trick_state
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

    __slots__ = ("tricks", "ordering", "played", "played_total", "physical", "voids", "events",
                 "batched", "native")

    def __init__(self, tricks, ordering, played, played_total, physical, voids, events):
        #: build batches with `fused_many_batched` (the same tensors, less work per row)
        self.batched = False
        #: build batches with `fused_many_native`: None (off) or its kernel arguments
        self.native = None
        self.tricks = tricks
        self.ordering = ordering
        self.played = played
        self.played_total = played_total
        self.physical = physical
        self.voids = voids
        self.events = events

    @classmethod
    def of(cls, rnd, batched=False, native=False):
        """The prefix of ``rnd.history``, or None where the fused builder would
        refuse any state extending it (every leaf then takes the reference).
        ``batched`` routes its batches through `fused_many_batched`;
        ``native`` (with ``batched``) through `fused_many_native`."""
        prefix = cls._of(rnd)
        if prefix is not None and batched:
            prefix.batched = True
            if native:
                prefix.native = _native_arguments(prefix)
        return prefix

    @classmethod
    def _of(cls, rnd):
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


#: the card at each `CARD_INDEX` position
_CARDS = sorted(CARD_INDEX, key=CARD_INDEX.__getitem__)
_UNSEEN = 8 * N_CARDS     # the v1 public unseen plane's offset
_SUIT_ORDER = [*SUITS, TRUMP]


def _trump_indices(ordering):
    return np.asarray([i for i, card in enumerate(_CARDS) if ordering.eff_suit(card) == TRUMP],
                      dtype=np.intp)


def _v2_columns_fast(unseen_trump, rnd, seat):
    """`cwv_static_encoding._v2_static_columns`' 29 columns, given the count
    of trump copies in the fused unseen plane (an int, as the reference's
    ``sum`` over ``unseen.elements()``): the same arithmetic in the same order."""
    o = rnd.ordering
    obs = []
    winner, lead_suit, trick_pts = trick_state(rnd, seat)
    winner_rel = [0.0] * 4
    if winner is not None:
        winner_rel[(winner - seat) % 4] = 1.0
    obs += winner_rel
    obs.append(1.0 if (winner is not None and winner != seat
                       and (winner - seat) % 2 == 0) else 0.0)
    obs.append(min(trick_pts, 80) / 80.0)
    lead_onehot = [0.0] * 5
    if lead_suit is not None:
        lead_onehot[_SUIT_ORDER.index(lead_suit)] = 1.0
    obs += lead_onehot
    played_here = 0 if rnd.trick is None else len(rnd.trick.plays)
    position = [0.0] * 4
    position[min(played_here, 3)] = 1.0
    obs += position
    obs.append(len(rnd.trick.plays[0].cards) / 6.0
               if (rnd.trick is not None and rnd.trick.plays) else 0.0)
    pts_now = min(rnd.attacker_points, 200)
    obs.append(max(-1.0, min(1.0, (pts_now - 80) / 80.0)))
    band = [0.0] * 4
    band[0 if pts_now < 40 else 1 if pts_now < 80 else 2 if pts_now < 120 else 3] = 1.0
    obs += band
    hand = rnd.hands[seat]
    eff = [o.eff_suit(c) for c in hand]
    for name in _SUIT_ORDER:
        obs.append(eff.count(name) / 27.0)
    obs.append(unseen_trump / 27.0)
    counts = Counter(hand)
    obs.append(sum(1 for v in counts.values() if v >= 2) / 13.0)
    obs.append(len(hand) / 27.0)
    return obs


def _checked(rnd, seat):
    """`HistoryPrefix.fused`'s state checks: True when it would read ``rnd``."""
    if (type(rnd) is not Round or type(seat) is not int or not 0 <= seat < 4
            or rnd.phase != "play" or type(rnd.ordering) is not Ordering
            or type(rnd.history) is not list or type(rnd.hands) is not list
            or len(rnd.hands) != 4 or type(rnd.buried) is not list
            or type(rnd.banker) is not int or not 0 <= rnd.banker < 4
            or type(rnd.attacker_points) is not int
            or type(rnd.trump_is_nt) is not bool or rnd.trump_rank not in RANKS
            or type(rnd.trick) is not Trick or type(rnd.trick.plays) is not list
            or len(rnd.trick.plays) > 3):
        return False
    declaration = rnd.declaration
    if declaration is not None:
        if (type(declaration) is not dict
                or type(declaration.get("seat")) is not int
                or not 0 <= declaration["seat"] < 4
                or type(declaration.get("cards")) is not list
                or not declaration["cards"]
                or any(type(card) is not str or card not in CARD_INDEX
                       for card in declaration["cards"])):
            return False
    return True


def fused_many(prefix, positions, seats, version):
    """``[tensor or None]``: for each ``(positions[i], seats[i])`` the static
    route's tensor at ``version`` that ``_widened(version, *prefix.fused(rnd,
    seat), rnd, seat)`` builds, byte for byte, or None where ``fused`` returns
    None.  The prefix planes are laid down once for the batch and each row
    adds only its own suffix (the tricks after the prefix and the current
    trick), its world planes and its seat projection; every value is a sum of
    half copies or the reference's own scalar expression, so the float32
    casts see the same doubles."""
    n = len(positions)
    out = [None] * n
    if version not in VERSIONS or not n:
        return out
    ordering = prefix.ordering
    eff_suit = ordering.eff_suit
    keep = []
    # a hand's half-copy plane, shared by the rows that hold the same cards
    hand_planes, world_planes = {}, []
    played_ix, trick_ix, phys_ix = ([], []), ([], []), ([], [])     # (flat cell, delta)
    voids, events, tails = [], [], []
    for i, (rnd, seat) in enumerate(zip(positions, seats)):
        try:
            if not _checked(rnd, seat):
                continue
            history = rnd.history
            if rnd.ordering is not ordering or len(history) < len(prefix.tricks):
                continue
            if any(history[k] is not trick for k, trick in enumerate(prefix.tricks)):
                continue
            row = len(keep)
            cells = []
            for relative in range(WORLD_RECEIVERS):
                cards = rnd.hands[(seat + relative) % 4] if relative < 4 else rnd.buried
                if type(cards) is not list:
                    raise TypeError
                key = tuple(cards)
                plane = hand_planes.get(key)
                if plane is None:
                    plane = np.zeros(N_CARDS, dtype=np.float64)
                    for card in cards:
                        if type(card) is not str:
                            raise TypeError
                        plane[CARD_INDEX[card]] += 0.5
                    hand_planes[key] = plane
                cells.append(plane)
            played = [defaultdict(float) for _ in range(4)]
            total = defaultdict(float)
            physical = defaultdict(int)
            row_voids = [set(suits) for suits in prefix.voids]
            planes = [defaultdict(float) for _ in range(3)]
            count = prefix.events
            for trick in history[len(prefix.tricks):]:
                if type(trick) is not Trick or type(trick.plays) is not list \
                        or len(trick.plays) != 4:
                    raise TypeError
                got = _traverse(trick, eff_suit, played, total, physical, row_voids, None)
                if got is None:
                    raise TypeError
                count += got
            got = _traverse(rnd.trick, eff_suit, played, total, physical, row_voids, planes)
            if got is None:
                raise TypeError
            count += got
            if not 1 <= count <= HISTORY_MAX_EVENTS:
                continue
            root_is_attacker = rnd.is_attacker(seat)
            tail = [0.0] * 5
            if rnd.trump_is_nt:
                tail[4] = 1.0
            elif rnd.trump_suit in SUITS:
                tail[SUITS.index(rnd.trump_suit)] = 1.0
            rank_onehot = [0.0] * 13
            rank_onehot[RANKS.index(rnd.trump_rank)] = 1.0
            tail += rank_onehot
            banker_rel = [0.0] * 4
            banker_rel[(rnd.banker - seat) % 4] = 1.0
            tail += banker_rel
            tail += [min(rnd.attacker_points, 200) / 200.0,
                     sum(len(hand) for hand in rnd.hands) / 100.0,
                     float(root_is_attacker)]
            for relative in range(4):
                for suit in _SUIT_ORDER:
                    tail.append(float(suit in row_voids[(seat + relative) % 4]))
        except Exception:
            continue
        world_planes.extend(cells)
        # each delta is a sum of half copies: added at once it is the same double
        for who in range(4):
            base = (row * 4 + who) * N_CARDS
            for index, value in played[who].items():
                played_ix[0].append(base + index); played_ix[1].append(value)
        for position in range(3):
            base = (row * 3 + position) * N_CARDS
            for index, value in planes[position].items():
                trick_ix[0].append(base + index); trick_ix[1].append(value)
        base = row * N_CARDS
        for index, value in physical.items():
            phys_ix[0].append(base + index); phys_ix[1].append(value)
        keep.append(i)
        voids.append(row_voids)
        events.append(count)
        tails.append((tail, root_is_attacker))
    if not keep:
        return out
    m = len(keep)
    world = np.stack(world_planes).reshape(m, WORLD_RECEIVERS, N_CARDS)
    played = np.broadcast_to(np.asarray(prefix.played, dtype=np.float64), (m, 4, N_CARDS)).copy()
    if played_ix[0]:
        np.add.at(played.reshape(-1), np.asarray(played_ix[0], np.intp),
                  np.asarray(played_ix[1], np.float64))
    trick_planes = np.zeros((m, 3, N_CARDS), dtype=np.float64)
    if trick_ix[0]:
        np.add.at(trick_planes.reshape(-1), np.asarray(trick_ix[0], np.intp),
                  np.asarray(trick_ix[1], np.float64))
    physical = np.broadcast_to(np.asarray(prefix.physical, dtype=np.int64), (m, N_CARDS)).copy()
    physical += (world * 2).astype(np.int64).sum(axis=1)
    if phys_ix[0]:
        np.add.at(physical.reshape(-1), np.asarray(phys_ix[0], np.intp),
                  np.asarray(phys_ix[1], np.int64))
    complete = (physical == 2).all(axis=1)
    # played_total is the sum of the four played planes (every play adds to both)
    played_total = played.sum(axis=1)
    seats_kept = np.asarray([seats[i] for i in keep], dtype=np.intp)
    rotate = (seats_kept[:, None] + np.arange(4)[None, :]) % 4
    played_rel = played[np.arange(m)[:, None], rotate]
    own = world[:, 0]
    unseen = np.maximum(0.0, 1.0 - played_total - own)
    tail = np.asarray([t for t, _ in tails], dtype=np.float64)
    v1 = np.concatenate([own, played_rel.reshape(m, -1), trick_planes.reshape(m, -1), unseen,
                         tail], axis=1)
    if v1.shape[1] != OBS_DIM:
        return out
    v1 = v1.astype(np.float32)
    world32 = world.astype(np.float32)
    trump = _trump_indices(ordering)
    unseen_trump = (v1[:, _UNSEEN:_UNSEEN + N_CARDS][:, trump] * 2).astype(np.int64).sum(axis=1)
    history = np.zeros((1, HISTORY_EVENT_DIM), dtype=np.float32)
    flag = np.zeros(1, dtype=np.float32)
    for row, i in enumerate(keep):
        if not complete[row]:
            continue
        rnd, seat = positions[i], seats[i]
        attacker = tails[row][1]
        perspective = np.asarray([float(attacker), float(not attacker)], dtype=np.float32)
        if version == 1:
            out[i] = ValueAfterstateTensors(np.concatenate((v1[row], flag)), history,
                                            world32[row], perspective)
            continue
        try:
            columns = _v2_columns_fast(int(unseen_trump[row]), rnd, seat)
            if version == 7:
                columns = [*columns, *next_actor_columns(rnd, seat)]
        except Exception:
            continue
        public = np.concatenate((v1[row], np.asarray(columns, dtype=np.float32), flag))
        out[i] = ValueAfterstateTensorsV2(public, history, world32[row], perspective)
    return out


def _suit_masks(ordering):
    """``(54, 5)`` float64: column ``k`` marks the cards whose effective suit
    is ``_SUIT_ORDER[k]`` under ``ordering``."""
    masks = np.zeros((N_CARDS, len(_SUIT_ORDER)), dtype=np.float64)
    for index, card in enumerate(_CARDS):
        masks[index, _SUIT_ORDER.index(ordering.eff_suit(card))] = 1.0
    return masks


def _tail_head(rnd, seat):
    """The first 22 v1 tail entries (trump suit, trump rank, banker seat)."""
    head = [0.0] * 5
    if rnd.trump_is_nt:
        head[4] = 1.0
    elif rnd.trump_suit in SUITS:
        head[SUITS.index(rnd.trump_suit)] = 1.0
    rank_onehot = [0.0] * 13
    rank_onehot[RANKS.index(rnd.trump_rank)] = 1.0
    head += rank_onehot
    banker_rel = [0.0] * 4
    banker_rel[(rnd.banker - seat) % 4] = 1.0
    head += banker_rel
    return head


def fused_many_batched(prefix, positions, seats, version):
    """`fused_many`, byte for byte, with less work per row: the five world
    planes are indexed from one array of the distinct hands, the trump, rank
    and banker block of the tail is built once per (trump, banker, seat), and
    the v2 and v7 columns are assembled as arrays.  The hand columns read the
    acting seat's world plane: its effective-suit counts, its pairs (cells at
    1.0) and its length are the integers the reference counts from the hand,
    divided by the same constants, so the float32 casts see the same doubles.
    A row is kept, refused (None) or skipped exactly where `fused_many` keeps,
    refuses or skips it."""
    n = len(positions)
    out = [None] * n
    if version not in VERSIONS or not n:
        return out
    ordering = prefix.ordering
    eff_suit = ordering.eff_suit
    tricks = prefix.tricks
    depth = len(tricks)
    keep = []
    hand_ids, hand_cells = {}, []          # distinct hand -> id; its card indices
    world_ids = []                          # WORLD_RECEIVERS ids per kept row
    heads = {}
    played_ix, trick_ix, phys_ix = ([], []), ([], []), ([], [])     # (flat cell, delta)
    tails, attackers = [], []
    for i, (rnd, seat) in enumerate(zip(positions, seats)):
        try:
            if not _checked(rnd, seat):
                continue
            history = rnd.history
            if rnd.ordering is not ordering or len(history) < depth:
                continue
            # ``map`` stops at the prefix's end: the first ``depth`` tricks by identity
            if not all(map(_is, history, tricks)):
                continue
            row = len(keep)
            ids = []
            for relative in range(WORLD_RECEIVERS):
                cards = rnd.hands[(seat + relative) % 4] if relative < 4 else rnd.buried
                if type(cards) is not list:
                    raise TypeError
                key = tuple(cards)
                hand = hand_ids.get(key)
                if hand is None:
                    cells = []
                    for card in cards:
                        if type(card) is not str:
                            raise TypeError
                        cells.append(CARD_INDEX[card])
                    hand = hand_ids[key] = len(hand_cells)
                    hand_cells.append(cells)
                ids.append(hand)
            played = [defaultdict(float) for _ in range(4)]
            total = defaultdict(float)
            physical = defaultdict(int)
            row_voids = [set(suits) for suits in prefix.voids]
            planes = [defaultdict(float) for _ in range(3)]
            count = prefix.events
            for trick in history[depth:]:
                if type(trick) is not Trick or type(trick.plays) is not list \
                        or len(trick.plays) != 4:
                    raise TypeError
                got = _traverse(trick, eff_suit, played, total, physical, row_voids, None)
                if got is None:
                    raise TypeError
                count += got
            got = _traverse(rnd.trick, eff_suit, played, total, physical, row_voids, planes)
            if got is None:
                raise TypeError
            count += got
            if not 1 <= count <= HISTORY_MAX_EVENTS:
                continue
            root_is_attacker = rnd.is_attacker(seat)
            if type(rnd.trump_suit) is str or rnd.trump_suit is None:
                head_key = (rnd.trump_is_nt, rnd.trump_suit, rnd.trump_rank, rnd.banker, seat)
                head = heads.get(head_key)
                if head is None:
                    head = heads[head_key] = _tail_head(rnd, seat)
            else:
                head = _tail_head(rnd, seat)
            tail = [*head, min(rnd.attacker_points, 200) / 200.0,
                    sum(len(hand) for hand in rnd.hands) / 100.0, float(root_is_attacker)]
            for relative in range(4):
                suits = row_voids[(seat + relative) % 4]
                for suit in _SUIT_ORDER:
                    tail.append(float(suit in suits))
        except Exception:
            continue
        world_ids.append(ids)
        # each delta is a sum of half copies: added at once it is the same double
        for who in range(4):
            base = (row * 4 + who) * N_CARDS
            for index, value in played[who].items():
                played_ix[0].append(base + index); played_ix[1].append(value)
        for position in range(3):
            base = (row * 3 + position) * N_CARDS
            for index, value in planes[position].items():
                trick_ix[0].append(base + index); trick_ix[1].append(value)
        base = row * N_CARDS
        for index, value in physical.items():
            phys_ix[0].append(base + index); phys_ix[1].append(value)
        keep.append(i)
        tails.append(tail)
        attackers.append(root_is_attacker)
    if not keep:
        return out
    m = len(keep)
    # every plane cell is a count of half copies: the reference's sums, exactly
    distinct = np.zeros((len(hand_cells), N_CARDS), dtype=np.float64)
    rows_of = [h for h, cells in enumerate(hand_cells) for _ in cells]
    if rows_of:
        np.add.at(distinct, (np.asarray(rows_of, np.intp),
                             np.asarray([c for cells in hand_cells for c in cells], np.intp)), 0.5)
    world = distinct[np.asarray(world_ids, dtype=np.intp)]          # (m, WORLD_RECEIVERS, 54)
    played = np.broadcast_to(np.asarray(prefix.played, dtype=np.float64), (m, 4, N_CARDS)).copy()
    if played_ix[0]:
        np.add.at(played.reshape(-1), np.asarray(played_ix[0], np.intp),
                  np.asarray(played_ix[1], np.float64))
    trick_planes = np.zeros((m, 3, N_CARDS), dtype=np.float64)
    if trick_ix[0]:
        np.add.at(trick_planes.reshape(-1), np.asarray(trick_ix[0], np.intp),
                  np.asarray(trick_ix[1], np.float64))
    physical = np.broadcast_to(np.asarray(prefix.physical, dtype=np.int64), (m, N_CARDS)).copy()
    physical += (world * 2).astype(np.int64).sum(axis=1)
    if phys_ix[0]:
        np.add.at(physical.reshape(-1), np.asarray(phys_ix[0], np.intp),
                  np.asarray(phys_ix[1], np.int64))
    complete = (physical == 2).all(axis=1)
    played_total = played.sum(axis=1)
    seats_kept = np.asarray([seats[i] for i in keep], dtype=np.intp)
    rotate = (seats_kept[:, None] + np.arange(4)[None, :]) % 4
    played_rel = played[np.arange(m)[:, None], rotate]
    own = world[:, 0]
    unseen = np.maximum(0.0, 1.0 - played_total - own)
    v1 = np.concatenate([own, played_rel.reshape(m, -1), trick_planes.reshape(m, -1), unseen,
                         np.asarray(tails, dtype=np.float64)], axis=1)
    if v1.shape[1] != OBS_DIM:
        return out
    v1 = v1.astype(np.float32)
    world32 = world.astype(np.float32)
    flag = np.zeros((m, 1), dtype=np.float32)
    attacker = np.asarray(attackers, dtype=bool)
    perspective = np.stack([attacker, ~attacker], axis=1).astype(np.float32)
    history = np.zeros((1, HISTORY_EVENT_DIM), dtype=np.float32)
    if version == 1:
        public = np.concatenate((v1, flag), axis=1)
        for row, i in enumerate(keep):
            if complete[row]:
                out[i] = ValueAfterstateTensors(public[row], history, world32[row],
                                                perspective[row])
        return out
    trump = _trump_indices(ordering)
    unseen_trump = (v1[:, _UNSEEN:_UNSEEN + N_CARDS][:, trump] * 2).astype(np.int64).sum(axis=1)
    # the per-row columns (the trick in progress, the score, the next actor);
    # the hand columns follow as arrays
    width = 21 + (4 if version == 7 else 0)
    head_cols = np.zeros((m, width), dtype=np.float64)
    ok = np.zeros(m, dtype=bool)
    for row, i in enumerate(keep):
        if not complete[row]:
            continue
        rnd, seat = positions[i], seats[i]
        try:
            cols = head_cols[row]
            winner, lead_suit, trick_pts = trick_state(rnd, seat)
            if winner is not None:
                cols[(winner - seat) % 4] = 1.0
                if winner != seat and (winner - seat) % 2 == 0:
                    cols[4] = 1.0
            cols[5] = min(trick_pts, 80) / 80.0
            if lead_suit is not None:
                cols[6 + _SUIT_ORDER.index(lead_suit)] = 1.0
            played_here = 0 if rnd.trick is None else len(rnd.trick.plays)
            cols[11 + min(played_here, 3)] = 1.0
            if rnd.trick is not None and rnd.trick.plays:
                cols[15] = len(rnd.trick.plays[0].cards) / 6.0
            pts_now = min(rnd.attacker_points, 200)
            cols[16] = max(-1.0, min(1.0, (pts_now - 80) / 80.0))
            cols[17 + (0 if pts_now < 40 else 1 if pts_now < 80 else 2 if pts_now < 120
                       else 3)] = 1.0
            if version == 7:
                rel = next_actor_rel(rnd, seat)
                if rel is not None:
                    cols[21 + rel] = 1.0
        except Exception:
            head_cols[row] = 0.0
            continue
        ok[row] = True
    copies = own * 2                                     # exact small integers
    suit_counts = copies @ _suit_masks(ordering)
    hand_cols = np.concatenate((suit_counts / 27.0, (unseen_trump / 27.0)[:, None],
                                ((own == 1.0).sum(axis=1) / 13.0)[:, None],
                                (copies.sum(axis=1) / 27.0)[:, None]), axis=1)
    columns = np.concatenate((head_cols[:, :21], hand_cols, head_cols[:, 21:]), axis=1)
    public = np.concatenate((v1, columns.astype(np.float32), flag), axis=1)
    for row, i in enumerate(keep):
        if ok[row]:
            out[i] = ValueAfterstateTensorsV2(public[row], history, world32[row], perspective[row])
    return out


def _native_arguments(prefix):
    """The prefix as `_pv_fast.encode_static_batch`'s arguments, or None
    (no compiled module, or an ordering whose suits the kernel cannot number):
    the batches then take `fused_many_batched`."""
    from .pv_native import _pv_fast
    if _pv_fast is None:
        return None
    try:
        ordering = prefix.ordering
        suits = [ordering.eff_suit(card) for card in _CARDS]
        if any(suit not in _SUIT_ORDER for suit in suits):
            return None
        voids = np.zeros(4, dtype=np.uint32)
        for seat, held in enumerate(prefix.voids):
            for k, suit in enumerate(_SUIT_ORDER):
                if suit in held:
                    voids[seat] |= np.uint32(1 << k)
        return (np.ascontiguousarray(prefix.played, dtype=np.float64),
                np.ascontiguousarray(prefix.physical, dtype=np.int_), voids,
                np.asarray([_SUIT_ORDER.index(suit) for suit in suits], dtype=np.int8),
                np.asarray([suit == TRUMP for suit in suits], dtype=np.uint8),
                {suit: k for k, suit in enumerate(_SUIT_ORDER)})
    except Exception:
        return None


def native_arrays(prefix, positions, seats, version):
    """``(public, world, perspective)``: the stacked fields of the rows
    `fused_many_batched` builds when it keeps every row, built by the compiled
    `_pv_fast.encode_static_batch`; None where the kernel declines (a row the
    batched builder would skip or refuse, any kernel error) or ``prefix`` has
    no native arguments."""
    arguments = prefix.native
    if arguments is None or version not in VERSIONS or not len(positions):
        return None
    from .pv_native import _pv_fast
    played, physical, voids, suit_of, is_trump, suit_index = arguments
    try:
        return _pv_fast.encode_static_batch(
            prefix.tricks, prefix.ordering, played, physical, voids, prefix.events,
            list(positions), list(seats), version, CARD_INDEX, suit_of, is_trump,
            (Round, Trick, TrickPlay, Ordering), _checked, trick_state, SUITS, RANKS, suit_index,
            HISTORY_MAX_EVENTS)
    except Exception:
        return None


def fused_many_native(prefix, positions, seats, version):
    """`fused_many_batched`, byte for byte: the rows of `native_arrays`, or
    `fused_many_batched`'s own where it declines."""
    built = native_arrays(prefix, positions, seats, version)
    if built is None:
        return fused_many_batched(prefix, positions, seats, version)
    public, world, perspective = built
    history = np.zeros((1, HISTORY_EVENT_DIM), dtype=np.float32)
    kind = ValueAfterstateTensors if version == 1 else ValueAfterstateTensorsV2
    return [kind(public[row], history, world[row], perspective[row])
            for row in range(len(positions))]


class StackedRows:
    """The model rows of a batch held as its stacked ``(public, world,
    perspective)`` arrays: what ``np.stack`` over the rows' fields gives, for
    the evaluator's stacked forward (`NumpyCompleteWorldEvaluator.probabilities_stacked`)."""

    __slots__ = ("arrays",)

    def __init__(self, public, world, perspective):
        self.arrays = (public, world, perspective)

    def __len__(self):
        return self.arrays[0].shape[0]


def _stacked_evaluator(evaluator) -> bool:
    """The served NumPy evaluator, whose ``probabilities`` stacks each chunk's
    fields and runs `probabilities_stacked`'s forward on them."""
    from ..ai.cwv_numpy_evaluator import NumpyCompleteWorldEvaluator
    return type(evaluator) is NumpyCompleteWorldEvaluator


def _builder(prefix):
    """The batch builder ``prefix`` selects."""
    if prefix.native is not None:
        return fused_many_native
    return fused_many_batched if prefix.batched else fused_many


def reply_rows(clones, seat, version, prefix):
    """The greedy reply ply's policy rows, ``flat_input(root_tensors(clone,
    seat, version), version)`` for each clone, byte for byte: built by
    `fused_many` on ``prefix`` (the decision root's), the reference for any
    row it does not cover; one batched check stands for the reference's
    per-row ``validate``, and any failure re-encodes the whole call by the
    reference."""
    from .policy_prior import flat_input, root_tensors

    def reference():
        return [flat_input(root_tensors(clone, seat, version), version) for clone in clones]

    if prefix is None or version not in VERSIONS or not clones:
        return reference()
    try:
        build = _builder(prefix)
        if prefix.native is not None:
            built = native_arrays(prefix, clones, [seat] * len(clones), version)
            if built is not None and _valid_stacked(*built, version):
                from .policy_prior import input_dim
                public, world, perspective = built
                # flat_input of each row: its fields concatenated, as float32
                flat = np.concatenate((public, world.reshape(len(clones), -1), perspective),
                                      axis=1).astype(np.float32)
                if flat.shape[1] == input_dim(version):
                    return list(flat)
            # the kernel declined: the batched builder's rows
            build = fused_many_batched
        fast = build(prefix, clones, [seat] * len(clones), version)
        built = [t for t in fast if t is not None]
        if not _valid_batch(built, version):
            return reference()
        return [flat_input(t, version) if t is not None
                else flat_input(root_tensors(clone, seat, version), version)
                for t, clone in zip(fast, clones)]
    except Exception:
        return reference()


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
    return _valid_stacked(public, world, perspective, version)


def _valid_stacked(public, world, perspective, version) -> bool:
    """`_valid_batch`'s check on the rows' stacked fields."""
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


def encode_leaves(evaluator, positions, root_seat, prefix, batched=True):
    """``(values, rows, pending, fast)`` for `score_leaves`: the terminal values
    filled in ``values``, the model rows in position order with their indices,
    and how many rows the prefix built; None when the call must take the
    reference path whole (an unsupported evaluator, encoder or seat, any
    exception, a failed batch check).  The prefix rows are built by
    `fused_many`; ``batched=False`` builds each by `HistoryPrefix.fused`
    instead (the same tensors; the tests' oracle)."""
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
        live = [index for index, rnd in enumerate(positions) if rnd.phase != "round_end"]
        build = _builder(prefix)
        if batched and live and prefix.native is not None and _stacked_evaluator(evaluator):
            stacked = native_arrays(prefix, [positions[index] for index in live],
                                    [root_seat] * len(live), version)
            if stacked is not None and _valid_stacked(*stacked, version):
                for index, rnd in enumerate(positions):
                    if rnd.phase == "round_end":
                        values[index] = float(
                            terminal_distribution(rnd, root_seat) @ evaluator.support)
                return values, StackedRows(*stacked), live, len(live)
            if stacked is None:
                # the kernel declined: the batched builder's rows
                build = fused_many_batched
        built = build(prefix, [positions[index] for index in live], [root_seat] * len(live),
                      version) if batched else None
        built = dict(zip(live, built)) if built is not None else None
        for index, rnd in enumerate(positions):
            if rnd.phase == "round_end":
                values[index] = float(
                    terminal_distribution(rnd, root_seat) @ evaluator.support)
                continue
            if built is not None:
                row = built[index]
            else:
                parts = prefix.fused(rnd, root_seat)
                row = None if parts is None else _widened(version, *parts, rnd, root_seat)
            if row is None:
                rows.append(reference(rnd, root_seat))
            else:
                rows.append(row)
                fast.append(row)
            pending.append(index)
        if not _valid_batch(fast, version):
            return None
    except Exception:
        return None
    return values, rows, pending, len(fast)


def score_leaves(evaluator, positions, root_seat, prefix, batched=True):
    """``evaluator.score(positions, root_seat)``, its leaves encoded on ``prefix``.

    The terminal rows, the row order, the forward pass and the evaluator's
    counters are `CompleteWorldEvaluator.score_many`'s.
    """
    wall0, cpu0 = time.perf_counter(), time.process_time()
    n = len(positions)
    encoded = encode_leaves(evaluator, positions, root_seat, prefix, batched) if n else None
    if encoded is None:
        return evaluator.score(positions, root_seat)
    values, rows, pending, _ = encoded
    if type(rows) is StackedRows:
        values[pending] = evaluator.probabilities_stacked(*rows.arrays) @ evaluator.support
    elif rows:
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


__all__ = ["VERSIONS", "HistoryPrefix", "encode_leaves", "fused_many", "fused_many_batched",
           "fused_many_native", "native_arrays", "prior_rows", "reply_rows", "score_leaves", "static_version"]
