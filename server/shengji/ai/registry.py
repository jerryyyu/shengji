"""Named bot policies, so the server (and experiments) can swap them out.

Add new policies here and document them in AI_POLICIES.md (repo root) with
their measured win rate. The server picks its bot via the SHENGJI_BOT env
var (default "smart")."""

from __future__ import annotations

from .heuristic import HeuristicBot
from .mcbot import MCBot, MCSmartRoll
from .smart import SmartBot


def _smart_variant(name: str, **attrs):
    return type(name, (SmartBot,), attrs)

REGISTRY: dict[str, type] = {
    "heuristic": HeuristicBot,
    "smart": SmartBot,
    "mc": MCBot,  # determinized Monte Carlo; ~30ms/decision (N=10 worlds)
    "mc-strong": type("MCStrong", (MCBot,), {"N_DETERMINIZATIONS": 30}),
    "mc-lite": type("MCLite", (MCBot,), {"N_DETERMINIZATIONS": 5}),
    "mc-argmax": type("MCArgmax", (MCBot,), {"MARGIN": 0.0}),
    "mc-smartroll": MCSmartRoll,  # SmartBot rollouts, ~5x slower/decision
    # the pre-throws config (2026-07-31, 66% vs heuristic), for reproducibility:
    "smart-v1": _smart_variant("SmartV1", SAFE_THROWS=False, RESERVE_LAST=False,
                               BURY_VOID=False, DECLARE_MIN=9, DECLARE_FINAL=7,
                               ENDGAME_CONTROL=False, BURY_TRUMP_GATE=False),
    # v2 = throws-era config without the research-derived endgame/bury rules:
    "smart-v2": _smart_variant("SmartV2", ENDGAME_CONTROL=False,
                               BURY_TRUMP_GATE=False),
    # generational snapshots for longitudinal tracking (flags-only
    # reconstruction — shared engine/Memory fixes are NOT ablated):
    # pre-overnight-adoptions smart (before CONTROL_LEADS/TEMPO_GUARD/
    # LATE_TRUMP_PAIRS/VOID_DUMP, night of 2026-08-01):
    "smart-0801": _smart_variant("Smart0801", CONTROL_LEADS=False,
                                 TEMPO_GUARD=False, LATE_TRUMP_PAIRS=False,
                                 VOID_DUMP=False),
    # start-of-day mc (2026-08-02 morning, pre-WIDE_LEAD_BALLOT):
    "mc-0802am": type("MC0802am", (MCBot,), {"WIDE_LEAD_BALLOT": False}),
    # pre-overnight mc (narrow ballot + pre-adoption smart layer):
    "mc-0801": type("MC0801", (MCBot,), {"WIDE_LEAD_BALLOT": False,
                                         "CONTROL_LEADS": False,
                                         "TEMPO_GUARD": False,
                                         "LATE_TRUMP_PAIRS": False,
                                         "VOID_DUMP": False}),
    # measured-but-rejected variants, kept reproducible:
    "smart-trumpdrain": _smart_variant("SmartTrumpDrain", TRUMP_DRAIN=True),
    "smart-feedtrump": _smart_variant("SmartFeedTrump", FEED_ON_TRUMP=True),
    "smart-anytractor": _smart_variant("SmartAnyTractor", SAFE_TRACTOR_ONLY=False),
    "smart-reserve": _smart_variant("SmartReserve", RESERVE_LAST=True),
}


def _make_rl():
    from ..rl.torch_policy import RLBot  # lazy: needs torch + a checkpoint
    return RLBot()


def _make_mc_v5roll():
    """MCBot with the distilled net as rollout policy (the 55%-vs-mc
    hybrid). Needs torch + the checkpoint (SHENGJI_V5_CKPT, default
    ckpt_distill_full.pt in the server cwd). ~2-3s per decision."""
    import os
    from ..rl.torch_policy import RLBot
    from .mcbot import MCBot

    class MCv5Roll(MCBot):
        def __init__(self, seed=None):
            super().__init__(seed)
            self.rollout_policy = RLBot(
                ckpt=os.environ.get("SHENGJI_V5_CKPT", "ckpt_distill_full.pt"))

    return MCv5Roll()


REGISTRY["rl"] = _make_rl
REGISTRY["mc-v5roll"] = _make_mc_v5roll


def make_bot(name: str):
    try:
        return REGISTRY[name]()
    except KeyError:
        raise ValueError(
            f"Unknown bot policy {name!r}. Available: {', '.join(sorted(REGISTRY))}")
