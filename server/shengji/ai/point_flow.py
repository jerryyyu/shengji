"""Zero-effect point-flow attribution for completed tricks.

Item 2 of docs/proposals/point-management-census.md: per-rollout counters of
where points went — S4 point-banking telemetry style (schema string, closed
counter-field population, deterministic flag, loud reconciliation) — so every
point mechanism becomes screenable with matched-null discipline.

OBSERVATION ONLY. Nothing here changes any decision, and nothing in
production imports this module: MCBot's default path is untouched. The
opt-in hook is ``classify_trick_point_flow`` (one completed Trick + the
round's Ordering + banker -> one classification) plus the
``PointFlowAccumulator`` a rollout owner may feed; ``round_flow`` is the
one-call convenience for a finished (or partial) round.

Exact attribution semantics — every point card that lands in a completed
trick is attributed by the seat that PLAYED it, relative to the trick's
recorded winner, so the three trick counters partition the trick's points:

- ``winner_teammate_points``:       played by the winner's TEAMMATE (same team, other
                        seat) — the canonical partner feed;
- ``winner_own_points``: carried by the WINNER's own play — points won under
                        one's own power (the S4 bank-at-last move lands
                        here, as does winning with the 10 itself);
- ``losing_team_points``: played by the LOSING team — points surrendered
                        across teams, whether by follow obligation or
                        slough.

``kitty_points`` is the round-end transfer: the MULTIPLIED kitty bonus when
the attackers take the last trick (``Round._resolve_trick``), 0 otherwise —
a defended kitty never transfers. Reconciliation invariants (validated on
every telemetry read): teammate + own + losing == trick_points ==
attacker_captured + defender_captured, attacker + defender teammate ==
winner_teammate_points, and per round attacker_captured + kitty == rnd.attacker_points.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..engine.cards import Ordering, total_points
from ..engine.round import Round, Trick

POINT_FLOW_SCHEMA = "point-flow-telemetry-v2"

POINT_FLOW_COUNTER_FIELDS = (
    "tricks",
    "trick_points",
    "winner_teammate_points",
    "winner_own_points",
    "losing_team_points",
    "kitty_points",
    "attacker_captured",
    "defender_captured",
    "attacker_teammate_points",
    "defender_teammate_points",
)


def empty_point_flow_telemetry() -> dict[str, object]:
    """Canonical zero-dose record (S4 style) for feature-off consumers."""
    return {
        "schema": POINT_FLOW_SCHEMA,
        "deterministic": True,
        **{name: 0 for name in POINT_FLOW_COUNTER_FIELDS},
    }


@dataclass(frozen=True)
class TrickPointFlow:
    """Attribution of one completed trick's points (see module semantics)."""

    winner: int
    winner_is_attacker: bool
    trick_points: int
    winner_teammate_points: int
    winner_own_points: int
    losing_team_points: int


def classify_trick_point_flow(trick: Trick, ordering: Ordering,
                              banker: int) -> TrickPointFlow:
    """Classify one COMPLETED trick. Pure function; mutates nothing.

    Requires an engine-resolved trick: 4 plays, ``winner`` set, and
    ``points`` equal to the recomputed card total — a mismatch raises
    rather than being silently trusted (constructed tricks must therefore
    carry engine-true ``points``).
    """
    if type(banker) is not int or not 0 <= banker < 4:
        raise ValueError(f"banker must be a seat 0..3, got {banker!r}")
    if type(getattr(trick, "winner", None)) is not int or len(trick.plays) != 4:
        raise ValueError("classify_trick_point_flow needs a resolved "
                         "4-play trick with a recorded int winner")
    leader = getattr(trick, "leader", None)
    if type(leader) is not int or not 0 <= leader < 4:
        raise ValueError(f"trick leader must be a seat 0..3, got {leader!r}")
    expected_order = [(leader + k) % 4 for k in range(4)]
    seats = [getattr(tp, "seat", None) for tp in trick.plays]
    if any(type(x) is not int for x in seats) or seats != expected_order:
        raise ValueError(
            f"trick plays must cover seats {expected_order} in engine "
            f"rotation order exactly once each, got {seats!r}")
    if trick.winner not in seats:
        raise ValueError(f"trick winner {trick.winner!r} is not a playing seat")
    teammate = own = losing = 0
    total = 0
    for tp in trick.plays:
        for code in tp.cards:
            try:
                ordering.eff_suit(code)  # validates the code population
            except KeyError:
                raise ValueError(f"unknown card code {code!r}") from None
        pts = total_points(tp.cards)
        total += pts
        if tp.seat == trick.winner:
            own += pts
        elif tp.seat % 2 == trick.winner % 2:
            teammate += pts
        else:
            losing += pts
    if total != trick.points:
        raise AssertionError(
            f"trick.points={trick.points} disagrees with recomputed "
            f"card total {total}; refusing to classify a corrupted trick")
    return TrickPointFlow(
        winner=trick.winner,
        winner_is_attacker=trick.winner % 2 != banker % 2,
        trick_points=total,
        winner_teammate_points=teammate,
        winner_own_points=own,
        losing_team_points=losing,
    )


class PointFlowAccumulator:
    """Sums TrickPointFlow classifications across tricks/rounds/rollouts.

    Deterministic pure-integer bookkeeping: no RNG, no engine writes. One
    accumulator may span many rollout worlds; per-round reconciliation
    against ``rnd.attacker_points`` happens inside ``accumulate_round`` with
    round-local sums, so cross-round accumulation stays valid.
    """

    def __init__(self) -> None:
        self._totals: Counter[str] = Counter(
            {name: 0 for name in POINT_FLOW_COUNTER_FIELDS})

    # ------------------------------------------------------------------ feed
    def add_trick(self, trick: Trick, ordering: Ordering,
                  banker: int) -> TrickPointFlow:
        flow = classify_trick_point_flow(trick, ordering, banker)
        t = self._totals
        t["tricks"] += 1
        t["trick_points"] += flow.trick_points
        t["winner_teammate_points"] += flow.winner_teammate_points
        t["winner_own_points"] += flow.winner_own_points
        t["losing_team_points"] += flow.losing_team_points
        side = "attacker" if flow.winner_is_attacker else "defender"
        t[f"{side}_captured"] += flow.trick_points
        t[f"{side}_teammate_points"] += flow.winner_teammate_points
        return flow

    def add_kitty_transfer(self, bonus_points: int) -> None:
        """Record the round-end MULTIPLIED kitty bonus (0 when defended)."""
        if isinstance(bonus_points, bool) or not isinstance(bonus_points, int) \
                or bonus_points < 0:
            raise ValueError(f"kitty bonus must be a non-negative int, "
                             f"got {bonus_points!r}")
        self._totals["kitty_points"] += bonus_points

    def accumulate_round(self, rnd: Round) -> None:
        """Classify every resolved trick of ``rnd`` (open trick excluded).

        At ``round_end`` also records the kitty transfer. Reconciles this
        round's attribution against the engine's own tally and raises on any
        mismatch instead of accumulating a wrong number.
        """
        if rnd.ordering is None or rnd.banker is None:
            raise ValueError("accumulate_round needs a finalized round")
        # Stage into a ROUND-LOCAL accumulator first: a refused round must
        # leave this reusable accumulator byte-identical (review finding 1).
        staged = PointFlowAccumulator()
        attacker_captured = 0
        for trick in rnd.history:
            flow = staged.add_trick(trick, rnd.ordering, rnd.banker)
            if flow.winner_is_attacker:
                attacker_captured += flow.trick_points
        kitty = 0
        if rnd.phase == "round_end":
            kitty = rnd.kitty_bonus
            staged.add_kitty_transfer(kitty)
        if attacker_captured + kitty != rnd.attacker_points:
            raise AssertionError(
                f"round attribution {attacker_captured}+{kitty} disagrees "
                f"with engine attacker_points {rnd.attacker_points}")
        self._totals.update(staged._totals)

    # ----------------------------------------------------------------- report
    def snapshot(self) -> dict[str, int]:
        return {name: int(self._totals[name])
                for name in POINT_FLOW_COUNTER_FIELDS}

    def telemetry(self) -> dict[str, object]:
        counters = self.snapshot()
        self._validate(counters)
        return {
            "schema": POINT_FLOW_SCHEMA,
            "deterministic": True,
            **counters,
        }

    @staticmethod
    def _validate(counters: dict[str, int]) -> None:
        if set(counters) != set(POINT_FLOW_COUNTER_FIELDS):
            raise AssertionError("point-flow counter field population drift")
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0
               for v in counters.values()):
            raise AssertionError("point-flow counters must be non-negative ints")
        if counters["winner_teammate_points"] + counters["winner_own_points"] \
                + counters["losing_team_points"] != counters["trick_points"]:
            raise AssertionError("point-flow trick partition does not reconcile")
        if counters["attacker_captured"] + counters["defender_captured"] \
                != counters["trick_points"]:
            raise AssertionError("point-flow capture split does not reconcile")
        if counters["attacker_teammate_points"] + counters["defender_teammate_points"] \
                != counters["winner_teammate_points"]:
            raise AssertionError("point-flow teammate split does not reconcile")


def round_flow(rnd: Round) -> dict[str, object]:
    """One-call opt-in hook: telemetry for a single (possibly partial) round."""
    acc = PointFlowAccumulator()
    acc.accumulate_round(rnd)
    return acc.telemetry()
