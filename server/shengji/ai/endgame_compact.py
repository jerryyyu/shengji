"""Compact-state twin of :class:`shengji.ai.endgame.ExactWorldSession`.

Same search, cheaper state.  ``ExactWorldSession`` copies a whole ``Round``
for every child and rebuilds its legal actions, trick resolution and
transposition key from scratch.  :class:`CompactWorldSession` runs the
identical alpha-beta partnership minimax on a compact state, with two
backends:

* ``"compiled"`` -- ``ai/_endgame_fast.pyx``: per-world card-slot bitmasks, a
  C transposition table, and rule facts (decomposition, shape, tractor runs,
  ``decompose_matching``) computed once per card multiset by the engine's own
  functions and shared by every world of a decision.  Selected when the
  engine runs compiled (``SHENGJI_FAST=1``) and the extension is built.
* ``"python"`` -- :class:`_CompactSolver` below, the fallback: tuple states
  and memoized engine calls.

It is a drop-in for ``ExactWorldSession`` in ``train.pv_exact_endgame``; the
reference class stays the oracle (and the solver behind every other caller).

What is preserved exactly, and why
----------------------------------
* **Values, chosen actions, node and cache-hit counts, node-cap refusals.**
  The child order, the alpha-beta window updates, the exact/bound
  transposition tables and the node-cap test are the reference
  ``_ExactSolver.value`` line for line.  The table key is the reference
  ``_state_key`` minus its components that are constant within a session
  (context, which every root is checked against, and phase, always ``"play"``
  at a keyed state), so two states share an entry here iff they share one
  there; a capped search therefore raises at the same node.
* **Engine inputs (python backend).**  Hands are tuples in exactly the order
  the reference's lists have (``list.remove`` drops the first equal card, as
  does :func:`_remove`), plays keep the engine's card order, and every rule
  function receives a fresh ``list`` with the reference's contents.  Memo keys
  are those exact inputs.  The compiled backend keys rule facts by multiset;
  every engine rule it replays is a function of the multiset (``decompose``
  canonicalises its input; the rest count cards or compare levels).
* **``check_budget``**: the python backend calls it at the reference's points
  (every ``value`` call and every root); the compiled backend on every root
  and every 256th search call (``CompactWorldSession`` docstring).

``tests/test_endgame_compact.py`` holds both backends to the reference.

Level mode
----------
``CompactWorldSession(..., level=True)`` answers :meth:`~CompactWorldSession.solve_level`
only: the root's minimax attacker points up to a list of cuts (the steps of
the signed-level objective, :data:`LEVEL_CUTS`).  The compiled backend runs a
separate search for it (``_endgame_fast`` level-mode notes) whose node counts
differ from ``solve``; the python backend solves the root exactly and maps the
value, so both return the same number.  ``solve`` keeps its exact contract and
is untouched by this mode.  ``level_opts`` (compiled only; None = the default
set ``_endgame_fast.LEVEL_DEFAULT``) picks the level search's options, none of
which changes a value; :meth:`~CompactWorldSession.play_key` names the plays
that search treats as one move.
"""

from __future__ import annotations

from ..engine import round as _round
from ..engine.legal import IllegalPlay
from ..engine.cards import Ordering
from ..engine.round import KITTY_MULTIPLIER, Round
from . import endgame as _endgame
from .endgame import (ExactEndgameBudgetExceeded, ExactEndgameRefusal,
                      ExactEndgameResult, _context_key)

try:
    from . import _endgame_fast  # compiled solver; see setup.py
    HAVE_FAST = True
except ImportError:  # not built: the pure-Python solver below
    _endgame_fast = None
    HAVE_FAST = False

#: attacker-point steps of ``teacher_v1.attacker_level_utility`` (0 vs more,
#: then every 40): two point totals in the same interval map to the same level
LEVEL_CUTS = (1,) + tuple(range(40, 4121, 40))


def level_points(points: int, cuts=LEVEL_CUTS) -> int:
    """The highest cut at or below ``points`` (0 below the first cut): two
    totals with the same reduction have the same signed level."""
    reached = [c for c in cuts if c <= points]
    return reached[-1] if reached else 0


_NEG_INF = float('-inf')
_POS_INF = float('inf')


def _remove(hand: tuple, cards) -> tuple:
    """``Round._remove`` on a tuple: drop the first equal card, in order."""
    out = list(hand)
    for c in cards:
        out.remove(c)
    return tuple(out)


class _CompactSolver:
    """The reference ``_ExactSolver`` over tuple states (module docstring)."""

    def __init__(self, *, max_hand_cards: int, max_nodes: int,
                 check_budget=None, alpha_beta=False):
        if (isinstance(max_hand_cards, bool)
                or not isinstance(max_hand_cards, int)
                or max_hand_cards < 1):
            raise ValueError("max_hand_cards must be a positive integer")
        if (isinstance(max_nodes, bool) or not isinstance(max_nodes, int)
                or max_nodes < 1):
            raise ValueError("max_nodes must be a positive integer")
        self.max_hand_cards = max_hand_cards
        self.max_nodes = max_nodes
        self.check_budget = check_budget
        self.alpha_beta = alpha_beta
        self.nodes = 0
        self.cache_hits = 0
        self.cache: dict[tuple, int] = {}
        self.bounds: dict[tuple, tuple] = {}
        # per-world rule memos (the session binds one banker/trump/kitty)
        self.ordering = None
        self.banker_parity = 0
        self.kitty_points = 0
        self._sorted: dict[tuple, tuple] = {}
        self._moves: dict[tuple, list] = {}
        self._removed: dict[tuple, tuple] = {}
        self._resolved: dict[tuple, tuple] = {}

    # Round binding.

    def bind(self, rnd: Round) -> None:
        """Bind the rule context from a root of this session's context."""
        self.ordering = rnd.ordering
        self.banker_parity = rnd.banker % 2
        self.kitty_points = _round.total_points(rnd.buried)

    # Memoized rule queries.

    def _srt(self, cards: tuple) -> tuple:
        got = self._sorted.get(cards)
        if got is None:
            got = self._sorted[cards] = tuple(sorted(cards))
        return got

    def _legal(self, hand: tuple, seat: int, hands: tuple, plays: tuple) -> list:
        """``exhaustive_legal_actions`` as ``[(action, played)]``.

        ``played`` is what ``Round.play`` records: the submitted follow, or
        ``validate_lead``'s result for a lead (a failed throw's forced part).
        """
        if plays:
            lead = plays[0][1]
            key = (hand, lead)
        else:
            others = tuple(hands[s] for s in range(4) if s != seat)
            key = (hand, others)
        got = self._moves.get(key)
        if got is not None:
            return got
        if len(hand) > self.max_hand_cards:
            raise ExactEndgameRefusal(
                f"seat {seat} has {len(hand)} cards; completeness cap is "
                f"{self.max_hand_cards}")
        if not hand:
            raise ExactEndgameRefusal("acting seat has an empty hand")
        ordering = self.ordering
        hand_l = list(hand)
        actions: list[tuple] = []
        if not plays:
            other_l = [list(h) for h in others]
            uniform_suit = _endgame.uniform_suit
            validate_lead = _endgame.validate_lead
            for size in range(1, len(hand) + 1):
                for action in _endgame._distinct_multisets(hand_l, size):
                    if uniform_suit(list(action), ordering) is None:
                        continue
                    try:
                        validate_lead(list(action), hand_l, other_l, ordering)
                    except IllegalPlay:
                        continue
                    actions.append(action)
        else:
            if len(lead) > len(hand):
                raise ExactEndgameRefusal(
                    "acting hand is shorter than the current lead")
            validate_follow = _endgame.validate_follow
            lead_l = list(lead)
            for action in _endgame._distinct_multisets(hand_l, len(lead)):
                try:
                    validate_follow(list(action), hand_l, lead_l, ordering)
                except IllegalPlay:
                    continue
                actions.append(action)
        actions.sort(key=lambda a: (len(a), a))
        if not actions:
            raise ExactEndgameRefusal("active state has no enumerated legal action")
        moves = []
        for action in actions:
            if plays:
                # Round.play re-validates the follow (no trusted fast path in
                # an exact clone); it is the same call enumeration just made.
                played = action
            else:
                cards, _msg = _round.validate_lead(
                    list(action), list(hand), [list(h) for h in others], ordering)
                played = tuple(cards)
            moves.append((action, played))
        self._moves[key] = moves
        return moves

    def _resolve(self, plays: tuple) -> tuple:
        """``Round._resolve_trick``: (winning play index, trick points)."""
        cards = tuple(p[1] for p in plays)
        got = self._resolved.get(cards)
        if got is not None:
            return got
        ordering = self.ordering
        lead = list(cards[0])
        inc_suit = _round.uniform_suit(lead, ordering)
        assert inc_suit is not None
        inc_top = _round.decompose(lead, ordering).top_level()
        winner = 0
        for index in range(1, 4):
            played = list(cards[index])
            won, top = _round.beats(played, lead, inc_suit, inc_top, ordering)
            if won:
                winner, inc_top = index, top
                inc_suit = ordering.eff_suit(played[0])
        pts = _round.total_points(c for tp in cards for c in tp)
        got = self._resolved[cards] = (winner, pts)
        return got

    # Search.

    def value(self, hands, turn, points, leader, plays,
              alpha=_NEG_INF, beta=_POS_INF) -> int:
        check_budget = self.check_budget
        if check_budget is not None:
            check_budget()
        if turn is None:
            return points
        srt = self._srt
        key = (turn, points, (srt(hands[0]), srt(hands[1]), srt(hands[2]),
                              srt(hands[3])),
               leader, tuple([(s, srt(c)) for s, c in plays]))
        cache = self.cache
        if key in cache:
            self.cache_hits += 1
            return cache[key]
        lower, upper = self.bounds.get(key, (_NEG_INF, _POS_INF))
        if lower >= beta or upper <= alpha:
            self.cache_hits += 1
            return lower if lower >= beta else upper
        if self.nodes >= self.max_nodes:
            raise ExactEndgameBudgetExceeded(
                f"exact endgame exceeded max_nodes={self.max_nodes}",
                nodes=self.nodes, cache_hits=self.cache_hits)
        self.nodes += 1

        moves = self._legal(hands[turn], turn, hands, plays)
        original_alpha, original_beta = alpha, beta
        maximize = turn % 2 != self.banker_parity
        answer = _NEG_INF if maximize else _POS_INF
        alpha_beta = self.alpha_beta
        child = self._child
        for _action, played in moves:
            value = self.value(*child(hands, turn, points, leader, plays, played),
                               alpha, beta)
            if maximize:
                if value > answer:
                    answer = value
            elif value < answer:
                answer = value
            if alpha_beta:
                if maximize:
                    if answer > alpha:
                        alpha = answer
                elif answer < beta:
                    beta = answer
                if alpha >= beta:
                    break
        if original_alpha < answer < original_beta:
            cache[key] = answer
        elif answer <= original_alpha:
            self.bounds[key] = (lower, min(upper, answer))
        else:
            self.bounds[key] = (max(lower, answer), upper)
        return answer

    def _child(self, hands, turn, points, leader, plays, played):
        """``Round.play(turn, played)`` on the tuple state."""
        rkey = (hands[turn], played)
        hand = self._removed.get(rkey)
        if hand is None:
            hand = self._removed[rkey] = _remove(hands[turn], played)
        hands = hands[:turn] + (hand,) + hands[turn + 1:]
        plays = plays + ((turn, played),)
        if len(plays) < 4:
            return hands, (turn + 1) % 4, points, leader, plays
        index, pts = self._resolve(plays)
        winner = plays[index][0]
        attacker = winner % 2 != self.banker_parity
        if attacker:
            points += pts
        if not (hands[0] or hands[1] or hands[2] or hands[3]):
            if attacker:
                points += (self.kitty_points * KITTY_MULTIPLIER
                           * len(plays[0][1]))
            return hands, None, points, None, ()
        return hands, winner, points, winner, ()


def _root_state(rnd: Round):
    """The tuple state of a root ``Round`` (hands in the engine's list order)."""
    trick = rnd.trick
    return (tuple(tuple(h) for h in rnd.hands), rnd.turn,
            int(rnd.attacker_points), trick.leader,
            tuple((p.seat, tuple(p.cards)) for p in trick.plays))


def _solve_state(state, solver: _CompactSolver) -> tuple[int, tuple]:
    """The reference ``endgame._solve_root`` on a tuple root state."""
    hands, turn, points, leader, plays = state
    moves = solver._legal(hands[turn], turn, hands, plays)
    scored: list[tuple[tuple[str, ...], int]] = []
    for action, played in moves:
        child = solver._child(hands, turn, points, leader, plays, played)
        scored.append((action, solver.value(*child)))
    choose = max if turn % 2 != solver.banker_parity else min
    best_value = choose(value for _, value in scored)
    best_action = next(action for action, value in scored
                       if value == best_value)
    return best_value, best_action


def _compiled_engine_active() -> bool:
    from ..engine import fast
    return bool(fast._saved)


def default_backend() -> str:
    """``"compiled"`` exactly when the engine runs compiled (``SHENGJI_FAST=1``
    activated ``engine.fast``) and ``_endgame_fast`` is built; else
    ``"python"``.  Both backends return identical results."""
    return "compiled" if HAVE_FAST and _compiled_engine_active() else "python"


class CompactWorldSession:
    """``ExactWorldSession`` on a compact state (module docstring).

    ``backend``: ``"compiled"`` (``_endgame_fast``), ``"python"``
    (:class:`_CompactSolver`) or None for :func:`default_backend`.

    The compiled backend calls ``check_budget`` on every ``budget_every``-th
    search call rather than on every call (every root still checks first, as
    the reference does); an expired deadline is seen at most that many calls
    later.  Its masks hold at most ``_endgame_fast.MAX_HAND`` physical cards
    per seat (three copies of a code).  A root beyond that -- impossible for
    the leaves of one sampled world, which only lose cards -- switches the
    session to the Python backend by replaying the roots already solved, which
    rebuilds the same table and counters, so results stay identical.
    """

    def __init__(self, rnd: Round, *, max_hand_cards: int = 4,
                 max_nodes: int = 250_000, check_budget=None, alpha_beta=False,
                 backend: str | None = None, budget_every: int = 256,
                 level: bool = False, level_opts: int | None = None):
        self.context = _context_key(rnd)
        # the reference argument checks, whichever backend runs
        _CompactSolver(max_hand_cards=max_hand_cards, max_nodes=max_nodes)
        if backend is None:
            backend = default_backend()
        if backend not in ("compiled", "python"):
            raise ValueError(f"unknown exact backend {backend!r}")
        if backend == "compiled" and not HAVE_FAST:
            raise ValueError("compiled exact backend is not built")
        if (isinstance(budget_every, bool) or not isinstance(budget_every, int)
                or budget_every < 1):
            raise ValueError("budget_every must be a positive integer")
        if backend == "compiled" and max_hand_cards > _endgame_fast.MAX_HAND:
            backend = "python"
        self.backend = backend
        self.max_hand_cards = max_hand_cards
        self.max_nodes = max_nodes
        self.check_budget = check_budget
        self.alpha_beta = alpha_beta
        self.budget_every = budget_every
        self.level = bool(level)
        self.level_opts = level_opts
        self.frontiers = 0
        self.solver = None
        self._root = None          # the first root: binds the rule context
        self._history = []         # compiled roots solved, for a replay
        self._replayable = True

    @property
    def nodes(self) -> int:
        return 0 if self.solver is None else self.solver.nodes

    @property
    def cache_hits(self) -> int:
        return 0 if self.solver is None else self.solver.cache_hits

    def _python_solver(self) -> _CompactSolver:
        solver = _CompactSolver(
            max_hand_cards=self.max_hand_cards, max_nodes=self.max_nodes,
            check_budget=self.check_budget, alpha_beta=self.alpha_beta)
        solver.bind(self._root)
        return solver

    def _bind(self, rnd: Round) -> None:
        if rnd.ordering is None:
            raise ExactEndgameRefusal(
                "exact endgame requires an active play phase")
        self._root = rnd
        if self.backend == "compiled" and type(rnd.ordering) is not Ordering:
            self.backend = "python"     # the compiled tables rebuild an Ordering
        if self.backend == "python":
            self.solver = self._python_solver()
        else:
            self.solver = _endgame_fast.FastWorld(
                rnd.ordering, rnd.banker, list(rnd.buried),
                max_nodes=self.max_nodes,
                check_budget=self.check_budget, alpha_beta=self.alpha_beta,
                budget_every=self.budget_every,
                exc_type=ExactEndgameRefusal,
                budget_exc_type=ExactEndgameBudgetExceeded,
                **({'level': True, 'level_opts': self.level_opts} if self.level else {}))

    def _to_python(self) -> None:
        """Rebuild this session's table on the Python backend (class doc)."""
        if not self._replayable:
            raise ExactEndgameRefusal(
                "compact exact session cannot hold this root after a refused solve")
        compiled = self.solver
        solver = self._python_solver()
        for state in self._history:
            _solve_state(state, solver)
        if (solver.nodes, solver.cache_hits) != (compiled.nodes, compiled.cache_hits):
            raise AssertionError("compact exact replay diverged from the compiled solver")
        self.solver = solver
        self.backend = "python"
        self._history = []

    def _check_root(self, rnd: Round) -> None:
        if self.check_budget is not None:
            self.check_budget()
        if _context_key(rnd) != self.context:
            raise ExactEndgameRefusal(
                "exact session context differs in banker/trump/buried cards")
        if rnd.phase != "play" or rnd.turn is None:
            raise ExactEndgameRefusal("root must be an active play decision")
        largest = max((len(h) for h in rnd.hands), default=0)
        if largest > self.max_hand_cards:
            raise ExactEndgameRefusal(
                f"largest hand has {largest} cards; completeness cap is "
                f"{self.max_hand_cards}")
        if rnd.trick is None or rnd.ordering is None:
            raise ExactEndgameRefusal("exact endgame requires an active play phase")
        if self.solver is None:
            self._bind(rnd)

    def solve_level(self, rnd: Round, cuts=LEVEL_CUTS) -> int:
        """The root's minimax attacker points reduced by :func:`level_points`
        to the lowest total of their interval between ``cuts`` -- or the
        root's own points when no cut above them is reached (module docstring,
        level mode).  Node-cap refusals raise as in :meth:`solve`."""
        if not self.level:
            raise ExactEndgameRefusal("solve_level needs a level-mode session")
        self._check_root(rnd)
        self.frontiers += 1
        before_nodes = self.solver.nodes
        before_hits = self.solver.cache_hits
        try:
            if self.backend == "compiled":
                try:
                    return self.solver.solve_level(rnd, cuts)
                except _endgame_fast.SlotCapacityExceeded:
                    # level tables need no replay: a fresh python solver
                    # answers the same intervals
                    self.backend = "python"
                    self.solver = self._python_solver()
            points, _action = _solve_state(_root_state(rnd), self.solver)
        except ExactEndgameBudgetExceeded as exc:
            exc.nodes = self.solver.nodes - before_nodes
            exc.cache_hits = self.solver.cache_hits - before_hits
            raise
        root = int(rnd.attacker_points)
        reduced = level_points(points, cuts)
        return reduced if reduced > root else root

    def play_key(self, rnd: Round, cards):
        """On a compiled level session: a key equal for two plays of the acting
        seat at ``rnd`` when the level search treats them as interchangeable
        (``_endgame_fast`` ``play_key``), so their children have equal values;
        None on the python backend (no such reduction there)."""
        if not self.level:
            raise ExactEndgameRefusal("play_key needs a level-mode session")
        self._check_root(rnd)
        if self.backend != "compiled":
            return None
        try:
            return self.solver.play_key(rnd, list(cards))
        except _endgame_fast.SlotCapacityExceeded:
            return None

    def solve_points(self, rnd: Round) -> int:
        """The root's exact minimax attacker points on a level-mode session
        (the compiled level search with a full window; python: ``solve``'s)."""
        if not self.level:
            raise ExactEndgameRefusal("solve_points needs a level-mode session")
        self._check_root(rnd)
        self.frontiers += 1
        if self.backend == "compiled":
            try:
                return self.solver.solve_points(rnd)
            except _endgame_fast.SlotCapacityExceeded:
                self.backend = "python"
                self.solver = self._python_solver()
        return _solve_state(_root_state(rnd), self.solver)[0]

    def solve(self, rnd: Round) -> ExactEndgameResult:
        if self.level:
            raise ExactEndgameRefusal("a level-mode session answers solve_level only")
        if self.check_budget is not None:
            self.check_budget()
        if _context_key(rnd) != self.context:
            raise ExactEndgameRefusal(
                "exact session context differs in banker/trump/buried cards")
        if rnd.phase != "play" or rnd.turn is None:
            raise ExactEndgameRefusal("root must be an active play decision")
        largest = max((len(h) for h in rnd.hands), default=0)
        if largest > self.max_hand_cards:
            raise ExactEndgameRefusal(
                f"largest hand has {largest} cards; completeness cap is "
                f"{self.max_hand_cards}")
        if rnd.trick is None or rnd.ordering is None:
            raise ExactEndgameRefusal("exact endgame requires an active play phase")
        if self.solver is None:
            self._bind(rnd)
        state = _root_state(rnd)
        before_nodes = self.solver.nodes
        before_hits = self.solver.cache_hits
        self.frontiers += 1
        try:
            if self.backend == "compiled":
                try:
                    points, action = self.solver.solve(rnd)
                    self._history.append(state)
                except _endgame_fast.SlotCapacityExceeded:
                    self._to_python()
            if self.backend == "python":
                points, action = _solve_state(state, self.solver)
        except ExactEndgameBudgetExceeded as exc:
            self._replayable = False
            exc.nodes = self.solver.nodes - before_nodes
            exc.cache_hits = self.solver.cache_hits - before_hits
            raise
        except BaseException:
            self._replayable = False
            raise
        return ExactEndgameResult(
            attacker_points=points,
            action=action,
            nodes=self.solver.nodes - before_nodes,
            cache_hits=self.solver.cache_hits - before_hits,
        )
