"""One seat's bot that hands its early leads to a second bot.

`EarlyLeadBot` holds two bots built for the same seat.  ``base`` makes every
decision except a play that opens one of the round's first ``tricks`` tricks;
``early`` makes those.  Declares, the bury and every other attribute read come
from ``base``, so with ``tricks=0`` the wrapper is ``base`` decision for
decision and draw for draw: ``early`` is never consulted and never advances
its own sampler.

Both bots read every public notice (`observe_public`), so each one's refusal
ledger stays event-complete although each decides only some of the plays.
``last_decision_record`` is the record of whichever bot made the latest play
decision, so a harness reading it after `decide_play` sees the deciding
search's own record.
"""
from shengji.train.policy_value_search import leading


def is_early_lead(rnd, tricks: int) -> bool:
    """True when the acting seat opens trick ``len(rnd.history)`` and that
    index is below ``tricks`` (``tricks=5``: leads of tricks 1-5)."""
    return tricks > 0 and leading(rnd) and len(rnd.history) < tricks


class EarlyLeadBot:
    def __init__(self, base, early, tricks: int, *, policy_name: str | None = None):
        if type(tricks) is not int or tricks < 0:
            raise ValueError(f"tricks must be a non-negative int, got {tricks!r}")
        if base is early:
            raise ValueError("base and early must be distinct bots (each owns its sampler)")
        self.base = base
        self.early = early
        self.tricks = tricks
        self.policy_name = policy_name if policy_name is not None else getattr(base, "policy_name", None)
        self.last_decision_record = None
        self.early_decisions = 0
        self.last_routed_early = False

    def __getattr__(self, name):
        if name in ("base", "early"):
            raise AttributeError(name)
        return getattr(self.base, name)

    def decide_play(self, rnd, seat):
        routed = is_early_lead(rnd, self.tricks)
        bot = self.early if routed else self.base
        self.last_routed_early = routed
        try:
            return bot.decide_play(rnd, seat)
        finally:
            self.last_decision_record = getattr(bot, "last_decision_record", None)
            self.early_decisions += int(routed)

    def observe_public(self, rnd) -> None:
        for bot in (self.base, self.early):
            observe = getattr(bot, "observe_public", None)
            if observe is not None:
                observe(rnd)
