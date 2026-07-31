"""Named bot policies, so the server (and experiments) can swap them out.

Add new policies here and document them in AI_POLICIES.md (repo root) with
their measured win rate. The server picks its bot via the SHENGJI_BOT env
var (default "smart")."""

from __future__ import annotations

from .heuristic import HeuristicBot
from .mcbot import MCBot
from .smart import SmartBot


def _smart_variant(name: str, **attrs):
    return type(name, (SmartBot,), attrs)

REGISTRY: dict[str, type] = {
    "heuristic": HeuristicBot,
    "smart": SmartBot,
    "mc": MCBot,  # determinized Monte Carlo; ~50-150ms per decision
    # the pre-throws config (2026-07-31, 66% vs heuristic), for reproducibility:
    "smart-v1": _smart_variant("SmartV1", SAFE_THROWS=False, RESERVE_LAST=False,
                               BURY_VOID=False, DECLARE_MIN=9, DECLARE_FINAL=7),
    # measured-but-rejected variants, kept reproducible:
    "smart-trumpdrain": _smart_variant("SmartTrumpDrain", TRUMP_DRAIN=True),
    "smart-feedtrump": _smart_variant("SmartFeedTrump", FEED_ON_TRUMP=True),
    "smart-anytractor": _smart_variant("SmartAnyTractor", SAFE_TRACTOR_ONLY=False),
    "smart-reserve": _smart_variant("SmartReserve", RESERVE_LAST=True),
}


def make_bot(name: str):
    try:
        return REGISTRY[name]()
    except KeyError:
        raise ValueError(
            f"Unknown bot policy {name!r}. Available: {', '.join(sorted(REGISTRY))}")
