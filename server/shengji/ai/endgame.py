"""Exact perfect-information solving for bounded Shengji endgames.

This is the inner solver for the S3b experiment, not a production policy.
An MC policy may eventually call it *inside each determinized world* and then
average the resulting values across worlds.  Calling it once on the real room
state would leak hidden hands, so this module deliberately accepts only a
complete :class:`Round` and makes no policy/registry decision by itself.

The completeness boundary is small and executable: every remaining hand must
contain at most ``max_hand_cards`` (four by default).  At that size all
distinct physical-card multisets can be enumerated.  Leads include every
non-empty same-effective-suit subset, including attempted throws; follows
include every subset of the required size and are filtered by the engine's
real legality function.  The engine itself resolves failed throws.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from itertools import combinations

from ..engine.legal import IllegalPlay, uniform_suit, validate_follow, validate_lead
from ..engine.round import Round, Trick, TrickPlay


class ExactEndgameRefusal(RuntimeError):
    """The state is outside the solver's proved completeness boundary."""


class ExactEndgameBudgetExceeded(ExactEndgameRefusal):
    """The exact search exceeded its predeclared nonterminal expansion cap."""

    def __init__(self, message: str, *, nodes: int, cache_hits: int):
        super().__init__(message)
        self.nodes = nodes
        self.cache_hits = cache_hits


@dataclass(frozen=True)
class ExactEndgameResult:
    """Exact attacker-point value and the acting seat's optimal root action."""

    attacker_points: int
    action: tuple[str, ...]
    nodes: int
    cache_hits: int


def _distinct_multisets(hand: list[str], size: int):
    """Yield sorted code-multisets once despite physical duplicate cards."""
    seen: set[tuple[str, ...]] = set()
    for indices in combinations(range(len(hand)), size):
        key = tuple(sorted(hand[i] for i in indices))
        if key not in seen:
            seen.add(key)
            yield key


def exhaustive_legal_actions(
        rnd: Round, seat: int, *, max_hand_cards: int = 4) -> list[list[str]]:
    """Enumerate every legal submitted action inside the bounded endgame.

    Failed throws remain actions: ``Round.play`` converts the attempted throw
    to its forced component using the other three determinized hands.  Returning
    only the forced component here would change the player's available choice.
    """
    if rnd.phase != "play" or rnd.trick is None or rnd.ordering is None:
        raise ExactEndgameRefusal("exact endgame requires an active play phase")
    if rnd.turn != seat:
        raise ExactEndgameRefusal(
            f"seat {seat} is not the acting seat {rnd.turn}")
    hand = list(rnd.hands[seat])
    if len(hand) > max_hand_cards:
        raise ExactEndgameRefusal(
            f"seat {seat} has {len(hand)} cards; completeness cap is "
            f"{max_hand_cards}")
    if not hand:
        raise ExactEndgameRefusal("acting seat has an empty hand")

    actions: list[tuple[str, ...]] = []
    if not rnd.trick.plays:
        other_hands = [rnd.hands[s] for s in range(4) if s != seat]
        for size in range(1, len(hand) + 1):
            for key in _distinct_multisets(hand, size):
                action = list(key)
                if uniform_suit(action, rnd.ordering) is None:
                    continue
                try:
                    # Validation establishes legality; retain the submitted
                    # action rather than validate_lead's failed-throw result.
                    validate_lead(action, hand, other_hands, rnd.ordering)
                except IllegalPlay:
                    continue
                actions.append(key)
    else:
        lead = rnd.trick.plays[0].cards
        if len(lead) > len(hand):
            raise ExactEndgameRefusal(
                "acting hand is shorter than the current lead")
        for key in _distinct_multisets(hand, len(lead)):
            try:
                validate_follow(list(key), hand, lead, rnd.ordering)
            except IllegalPlay:
                continue
            actions.append(key)

    actions.sort(key=lambda a: (len(a), a))
    if not actions:
        raise ExactEndgameRefusal("active state has no enumerated legal action")
    return [list(a) for a in actions]


def _clone_for_play(rnd: Round) -> Round:
    """Copy exactly the mutable state touched by ``Round.play``.

    Sharing ``Ordering`` is intentional: its decomposition cache is a pure
    memo keyed by card multiset and can be shared across search branches.
    Deep-copying it at every node would copy an ever-growing cache and make
    the bounded solver needlessly quadratic in memory.
    """
    clone: Round = copy.copy(rnd)
    clone.hands = [list(h) for h in rnd.hands]
    clone.buried = list(rnd.buried)
    clone.history = list(rnd.history)
    clone.trick = (None if rnd.trick is None else Trick(
        leader=rnd.trick.leader,
        plays=[TrickPlay(p.seat, list(p.cards)) for p in rnd.trick.plays],
        winner=rnd.trick.winner,
        points=rnd.trick.points))
    clone.message = None
    # A clone inherited from an MC rollout may carry the trusted fast-path.
    # Exact action enumeration is exhaustive, but the engine must still check
    # every submitted follow so this module never relies on that provenance.
    clone._trusted_rollout = False
    return clone


def _context_key(rnd: Round):
    """Immutable rule/kitty context that changes terminal values or teams."""
    return (
        rnd.banker,
        rnd.trump_rank,
        rnd.trump_suit,
        bool(rnd.trump_is_nt),
        tuple(sorted(rnd.buried)),
    )


def _state_key(rnd: Round):
    trick = rnd.trick
    return (
        _context_key(rnd),
        rnd.phase,
        rnd.turn,
        int(rnd.attacker_points),
        tuple(tuple(sorted(h)) for h in rnd.hands),
        None if trick is None else trick.leader,
        () if trick is None else tuple(
            (p.seat, tuple(sorted(p.cards))) for p in trick.plays),
    )


class _ExactSolver:
    def __init__(self, *, max_hand_cards: int, max_nodes: int):
        if (isinstance(max_hand_cards, bool)
                or not isinstance(max_hand_cards, int)
                or max_hand_cards < 1):
            raise ValueError("max_hand_cards must be a positive integer")
        if (isinstance(max_nodes, bool) or not isinstance(max_nodes, int)
                or max_nodes < 1):
            raise ValueError("max_nodes must be a positive integer")
        self.max_hand_cards = max_hand_cards
        self.max_nodes = max_nodes
        self.nodes = 0
        self.cache_hits = 0
        self.cache: dict[tuple, int] = {}

    def value(self, rnd: Round) -> int:
        if rnd.phase == "round_end":
            return int(rnd.attacker_points)
        if rnd.phase != "play" or rnd.turn is None:
            raise ExactEndgameRefusal(
                f"cannot solve phase={rnd.phase!r}, turn={rnd.turn!r}")
        key = _state_key(rnd)
        if key in self.cache:
            self.cache_hits += 1
            return self.cache[key]
        if self.nodes >= self.max_nodes:
            raise ExactEndgameBudgetExceeded(
                f"exact endgame exceeded max_nodes={self.max_nodes}",
                nodes=self.nodes, cache_hits=self.cache_hits)
        self.nodes += 1

        seat = rnd.turn
        actions = exhaustive_legal_actions(
            rnd, seat, max_hand_cards=self.max_hand_cards)
        values = []
        for action in actions:
            child = _clone_for_play(rnd)
            child.play(seat, action)
            values.append(self.value(child))
        answer = max(values) if rnd.is_attacker(seat) else min(values)
        self.cache[key] = answer
        return answer


def _solve_root(rnd: Round, solver: _ExactSolver) -> ExactEndgameResult:
    """Score one root with an existing context-bound transposition table."""
    seat = rnd.turn
    assert seat is not None
    actions = exhaustive_legal_actions(
        rnd, seat, max_hand_cards=solver.max_hand_cards)
    scored: list[tuple[tuple[str, ...], int]] = []
    for action in actions:
        child = _clone_for_play(rnd)
        child.play(seat, action)
        scored.append((tuple(action), solver.value(child)))
    choose = max if rnd.is_attacker(seat) else min
    best_value = choose(value for _, value in scored)
    best_action = next(action for action, value in scored
                       if value == best_value)
    return ExactEndgameResult(
        attacker_points=best_value,
        action=best_action,
        nodes=solver.nodes,
        cache_hits=solver.cache_hits,
    )


class ExactWorldSession:
    """One exact cache shared only within one accepted determinized world.

    Candidate rollouts from the same world often converge on identical late
    frontiers.  This session reuses those values while refusing a different
    banker/trump/kitty context.  Callers must create a new session for every
    sampled world; structured-bury candidates also need separate sessions
    because each candidate changes the buried cards.
    """

    def __init__(self, rnd: Round, *, max_hand_cards: int = 4,
                 max_nodes: int = 250_000):
        self.context = _context_key(rnd)
        self.solver = _ExactSolver(
            max_hand_cards=max_hand_cards, max_nodes=max_nodes)
        self.frontiers = 0

    @property
    def nodes(self) -> int:
        return self.solver.nodes

    @property
    def cache_hits(self) -> int:
        return self.solver.cache_hits

    def solve(self, rnd: Round) -> ExactEndgameResult:
        if _context_key(rnd) != self.context:
            raise ExactEndgameRefusal(
                "exact session context differs in banker/trump/buried cards")
        if rnd.phase != "play" or rnd.turn is None:
            raise ExactEndgameRefusal("root must be an active play decision")
        largest = max((len(h) for h in rnd.hands), default=0)
        if largest > self.solver.max_hand_cards:
            raise ExactEndgameRefusal(
                f"largest hand has {largest} cards; completeness cap is "
                f"{self.solver.max_hand_cards}")
        before_nodes = self.solver.nodes
        before_hits = self.solver.cache_hits
        self.frontiers += 1
        try:
            result = _solve_root(rnd, self.solver)
        except ExactEndgameBudgetExceeded as exc:
            exc.nodes = self.solver.nodes - before_nodes
            exc.cache_hits = self.solver.cache_hits - before_hits
            raise
        return ExactEndgameResult(
            attacker_points=result.attacker_points,
            action=result.action,
            nodes=self.solver.nodes - before_nodes,
            cache_hits=self.solver.cache_hits - before_hits,
        )


def solve_exact_endgame(
        rnd: Round, *, max_hand_cards: int = 4,
        max_nodes: int = 250_000) -> ExactEndgameResult:
    """Solve a fully determinized bounded endgame by partnership minimax.

    Attackers maximize final attacker points; the banker's team minimizes them.
    The input's game semantics are not mutated (the shared ``Ordering`` may
    warm its pure decomposition cache). A returned result is exact for the
    engine's current house rules; an over-cap state or exhausted work budget
    raises a refusal instead of silently falling back under an "exact" label.

    ``nodes`` counts newly expanded uncached nonterminal child states. The
    public root dispatch and terminal leaves are deliberately not counted, so
    this is a bounded expansion contract rather than total CPU work.
    """
    if rnd.phase != "play" or rnd.turn is None:
        raise ExactEndgameRefusal("root must be an active play decision")
    largest = max((len(h) for h in rnd.hands), default=0)
    if largest > max_hand_cards:
        raise ExactEndgameRefusal(
            f"largest hand has {largest} cards; completeness cap is "
            f"{max_hand_cards}")

    session = ExactWorldSession(
        rnd, max_hand_cards=max_hand_cards, max_nodes=max_nodes)
    return session.solve(rnd)
