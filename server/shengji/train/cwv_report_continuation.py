"""DEV-only net continuation for CWV shortlist report finalists.

The root search remains :class:`CWVShortlistBot`: its exhaustive legal
shortlist, uniform/learned root scoring, and production MC selection are not
changed.  Only the independent report fold uses the lockstep implementation
from :mod:`net_rollout`, with a net for the configured number of tricks and
the normal heuristic rollout thereafter.
"""
from __future__ import annotations

from .cwv_shortlist import CWVShortlistBot
from .net_rollout import MCNetRolloutSearch, _fresh_counts


class _BallotOnlyEvaluator:
    """Satisfy ``MCNetRolloutSearch`` construction for the ballot helper.

    The helper only calls ``_candidates`` and the tractor-lock branch.  A
    refusing evaluator makes that boundary explicit; ballot construction must
    never silently become a second learned search.
    """

    def score_many(self, positions, seats):
        raise AssertionError("literal inner ballot must not invoke a model")


class CWVReportContinuationBot(CWVShortlistBot):
    """CWV W32 shortlist with learned continuation in the report fold only."""

    REPORT_CONTINUATION_RECORD_SCHEMA = "cwv-report-continuation-v1"
    NET_STAGE = "report"
    # The root shortlist deliberately disables production's tractor shortcut.
    TRACTOR_LOCK = False

    # Borrow the frozen production report/world arithmetic and lockstep
    # implementation.  The lockstep wrapper below only supplies its separate
    # continuation evaluator and restores the root evaluator afterwards.
    _report_fold_gap = MCNetRolloutSearch._report_fold_gap
    _report_rng = staticmethod(MCNetRolloutSearch._report_rng)
    _net_horizon = MCNetRolloutSearch._net_horizon
    _net_perspective = staticmethod(MCNetRolloutSearch._net_perspective)

    def __init__(self, root_evaluator, *, continuation_evaluator=None,
                 seed=0, config=None, reuse_successors=False,
                 guidance="learned", tricks=1):
        if guidance not in {"learned", "prior", "heuristic"}:
            raise ValueError("guidance must be one of 'learned', 'prior', 'heuristic'")
        if type(tricks) is not int or tricks < 0:
            raise ValueError("tricks must be a non-negative integer")
        if guidance == "prior" and (
                continuation_evaluator is None or
                continuation_evaluator is root_evaluator):
            raise ValueError(
                "prior guidance requires continuation_evaluator separate from root_evaluator")

        # Root construction and validation stay entirely in CWVShortlistBot.
        super().__init__(root_evaluator, seed=seed, config=config,
                         reuse_successors=reuse_successors)
        self.root_evaluator = root_evaluator
        self.guidance = guidance
        self.continuation_evaluator = (
            root_evaluator if continuation_evaluator is None
            else continuation_evaluator)
        # Heuristic is a named no-net control, regardless of the supplied K.
        self.NET_TRICKS = 0 if guidance == "heuristic" else tricks

        if self.NET_TRICKS and not callable(
                getattr(self.continuation_evaluator, "score_many", None)):
            raise ValueError(
                "learned/prior continuation requires evaluator.score_many(positions, seats)")

        # This helper is intentionally a distinct MCNetRolloutSearch object:
        # its MCBot ballot is literal production (including tractor lock),
        # while this bot's root ballot remains exhaustive CWV shortlist.
        self._literal_ballot_helper = MCNetRolloutSearch(
            _BallotOnlyEvaluator(), seed=seed)

        # MCNetRolloutSearch is mixed in by borrowed methods, rather than by
        # inheritance, so initialize the bookkeeping those methods consume.
        self.netroll_counts = _fresh_counts()
        self.netroll_sim_secs = 0.0
        self.netroll_net_secs = 0.0
        self._decision_counts = _fresh_counts()
        self._decision_secs = {"sim": 0.0, "net": 0.0}
        self.last_net_trace = None
        self.last_lockstep = None

    def _net_ballot(self, clone, seat):
        """Use a literal production ballot for inner movers.

        Calling the borrowed method on ``self`` would dispatch to this class's
        exhaustive ``CWVShortlistBot._candidates`` and recurse through every
        inner world.  The separate helper retains the original tractor lock
        and MCBot candidate source.
        """
        return MCNetRolloutSearch._net_ballot(
            self._literal_ballot_helper, clone, seat)

    def _lockstep_values(self, rnd, seat, worlds, candidates, *, stage,
                         sessions=None):
        """Run the borrowed lockstep against only the continuation evaluator."""
        original = self.evaluator
        self.evaluator = self.continuation_evaluator
        try:
            return MCNetRolloutSearch._lockstep_values(
                self, rnd, seat, worlds, candidates, stage=stage,
                sessions=sessions)
        finally:
            self.evaluator = original

    def decide_play(self, rnd, seat):
        # A decision's report counters are separate from cumulative worker
        # accounting in ``netroll_counts``.
        self._decision_counts = _fresh_counts()
        self._decision_secs = {"sim": 0.0, "net": 0.0}
        self.last_net_trace = None
        self.last_lockstep = None
        played = super().decide_play(rnd, seat)
        record = self.last_decision_record
        if record is not None:
            continuation = {
                "schema": self.REPORT_CONTINUATION_RECORD_SCHEMA,
                "guidance": self.guidance,
                "tricks": self.NET_TRICKS,
                "stage": "report",
                "inner_ballot": "production",
                "terminal": "heuristic",
                "counts": dict(self._decision_counts),
                "sim_wall_secs": self._decision_secs["sim"],
                "net_wall_secs": self._decision_secs["net"],
                "decision_wall_secs": record.get("search_secs"),
            }
            record["cwv_report_continuation"] = continuation
        return played


__all__ = ["CWVReportContinuationBot"]
