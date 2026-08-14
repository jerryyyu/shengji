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

- ``fed_points``:       played by the winner's TEAMMATE (same team, other
                        seat) — the canonical partner feed;
- ``contested_points``: carried by the WINNER's own play — points won under
                        one's own power (the S4 bank-at-last move lands
                        here, as does winning with the 10 itself);
- ``discarded_points``: played by the LOSING team — points surrendered
                        across teams, whether by follow obligation or
                        slough.

``kitty_points`` is the round-end transfer: the MULTIPLIED kitty bonus when
the attackers take the last trick (``Round._resolve_trick``), 0 otherwise —
a defended kitty never transfers. Reconciliation invariants (validated on
every telemetry read): fed + contested + discarded == trick_points ==
attacker_captured + defender_captured, attacker_fed + defender_fed ==
fed_points, and per round attacker_captured + kitty == rnd.attacker_points.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..engine.cards import Ordering, total_points
from ..engine.round import Round, Trick

POINT_FLOW_SCHEMA = "point-flow-telemetry-v1"

POINT_FLOW_COUNTER_FIELDS = (
    "tricks",
    "trick_points",
    "fed_points",
    "contested_points",
    "discarded_points",
    "kitty_points",
    "attacker_captured",
    "defender_captured",
    "attacker_fed",
    "defender_fed",
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
    fed_points: int
    contested_points: int
    discarded_points: int


def classify_trick_point_flow(trick: Trick, ordering: Ordering,
                              banker: int) -> TrickPointFlow:
    """Classify one COMPLETED trick. Pure function; mutates nothing.

    Requires an engine-resolved trick: 4 plays, ``winner`` set, and
    ``points`` equal to the recomputed card total — a mismatch raises
    rather than being silently trusted (constructed tricks must therefore
    carry engine-true ``points``).
    """
    if not isinstance(banker, int) or not 0 <= banker < 4:
        raise ValueError(f"banker must be a seat 0..3, got {banker!r}")
    if trick.winner is None or len(trick.plays) != 4:
        raise ValueError("classify_trick_point_flow needs a resolved "
                         "4-play trick with a recorded winner")
    fed = contested = discarded = 0
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
            contested += pts
        elif tp.seat % 2 == trick.winner % 2:
            fed += pts
        else:
            discarded += pts
    if total != trick.points:
        raise AssertionError(
            f"trick.points={trick.points} disagrees with recomputed "
            f"card total {total}; refusing to classify a corrupted trick")
    return TrickPointFlow(
        winner=trick.winner,
        winner_is_attacker=trick.winner % 2 != banker % 2,
        trick_points=total,
        fed_points=fed,
        contested_points=contested,
        discarded_points=discarded,
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
        t["fed_points"] += flow.fed_points
        t["contested_points"] += flow.contested_points
        t["discarded_points"] += flow.discarded_points
        side = "attacker" if flow.winner_is_attacker else "defender"
        t[f"{side}_captured"] += flow.trick_points
        t[f"{side}_fed"] += flow.fed_points
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
        attacker_captured = 0
        for trick in rnd.history:
            flow = self.add_trick(trick, rnd.ordering, rnd.banker)
            if flow.winner_is_attacker:
                attacker_captured += flow.trick_points
        kitty = 0
        if rnd.phase == "round_end":
            kitty = rnd.kitty_bonus
            self.add_kitty_transfer(kitty)
        if attacker_captured + kitty != rnd.attacker_points:
            raise AssertionError(
                f"round attribution {attacker_captured}+{kitty} disagrees "
                f"with engine attacker_points {rnd.attacker_points}")

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
        if counters["fed_points"] + counters["contested_points"] \
                + counters["discarded_points"] != counters["trick_points"]:
            raise AssertionError("point-flow trick partition does not reconcile")
        if counters["attacker_captured"] + counters["defender_captured"] \
                != counters["trick_points"]:
            raise AssertionError("point-flow capture split does not reconcile")
        if counters["attacker_fed"] + counters["defender_fed"] \
                != counters["fed_points"]:
            raise AssertionError("point-flow fed split does not reconcile")


def round_flow(rnd: Round) -> dict[str, object]:
    """One-call opt-in hook: telemetry for a single (possibly partial) round."""
    acc = PointFlowAccumulator()
    acc.accumulate_round(rnd)
    return acc.telemetry()
