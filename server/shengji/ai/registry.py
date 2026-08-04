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
    # Generational snapshots, named <policy>-<yyyymmdd> = the live head
    # on that date; bare names are always the current head. (Flags-only
    # reconstruction — shared engine/Memory fixes are NOT ablated):
    # pre-overnight-adoptions smart (before CONTROL_LEADS/TEMPO_GUARD/
    # LATE_TRUMP_PAIRS/VOID_DUMP, night of 2026-08-01):
    "smart-20260801": _smart_variant("Smart20260801", CONTROL_LEADS=False,
                                 TEMPO_GUARD=False, LATE_TRUMP_PAIRS=False,
                                 VOID_DUMP=False),
    # start-of-day mc (2026-08-02 morning, pre-WIDE_LEAD_BALLOT):
    "mc-20260802am": type("MC20260802am", (MCBot,), {"WIDE_LEAD_BALLOT": False}),
    # pre-overnight mc (narrow ballot + pre-adoption smart layer):
    "mc-20260801": type("MC20260801", (MCBot,), {"WIDE_LEAD_BALLOT": False,
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


def _make_vleaf(ckpt: str):
    """Value-leaf hybrid, named by its VALUE-HEAD checkpoint.

    The hybrid's strength depends entirely on which net evaluates the
    truncated-rollout leaves, so the checkpoint is part of the policy's
    identity — never register or report a bare "mc-vleaf" (2026-08-03:
    the pool headline was un-reproducible because the value head wasn't
    named in the result).
    """
    def f():
        from ..rl.torch_policy import MCValueLeaf
        return MCValueLeaf(ckpt=ckpt)
    return f


# Value-leaf hybrids, one entry per value head. Elo pool 2026-08-03:
# mc-vleaf-v7w-ep02 = 1163 (mc 1110, smart 1089, rl-v7w 1060, heuristic 1000)
REGISTRY["mc-vleaf-v7w-ep02"] = _make_vleaf("snapshots_v7w/ep02.pt")
REGISTRY["mc-vleaf-v8a-ep03"] = _make_vleaf("snapshots_v8a/ep03.pt")


def _make_override(ckpt: str):
    def f():
        from ..rl.torch_policy import RLOverrideBot
        return RLOverrideBot(ckpt=ckpt)
    return f


# Residual-distillation override policies (learned override of SmartBot)
# ep09 is the checkpoint the battery actually evaluated; the alias pointed at
# ep05, so anyone playing this bot got a DIFFERENT net than the one measured
# (Codex 2026-08-03). Kept registered only for the offline residual
# post-mortem — this arm is a near no-op, not a candidate for play.
def _make_override_thr(path: str, margin: float):
    def make(**kw):
        from ..rl.torch_policy import RLOverrideBot
        b = RLOverrideBot(path)
        b.MARGIN = margin          # fitted on a DISJOINT half of the holdout
        return b
    return make


# threshold 0.02 was fitted on half A of the holdout and reported on half B
# (regret 1.943 vs 2.103 for always-candidate-0), so it is not post-hoc.
REGISTRY["rl-override-v11pair"] = _make_override_thr(
    "snapshots_v11pair/ep07.pt", 0.02)
REGISTRY["rl-override-v10res"] = _make_override("snapshots_v10res/ep09.pt")
