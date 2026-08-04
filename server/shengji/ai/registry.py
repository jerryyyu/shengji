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


class MCNull(MCBot):
    """NULL CONTROL: identical to `mc` in every way except its random draws.

    Same ballot, same N, same flags — only the RNG stream differs. Any effect
    it shows against `mc` is therefore pure sampling noise, which makes it the
    right control for "does more search help": if the null clears the same bar
    the arm did, the bar is measuring the harness rather than the treatment.

    This exists because the first dose rerun used `mc-strong` as its control.
    The evaluator's control means "an arm that should NOT work", and passing it
    a stronger treatment voided all six shards for a reason that was the setup,
    not the data.
    """

    def __init__(self, seed: int | None = None):
        super().__init__(None if seed is None else seed + 999_983)

REGISTRY: dict[str, type] = {
    "heuristic": HeuristicBot,
    "smart": SmartBot,
    "mc": MCBot,  # determinized Monte Carlo; ~30ms/decision (N=10 worlds)
    "mc-strong": type("MCStrong", (MCBot,), {"N_DETERMINIZATIONS": 30}),
    "mc-lite": type("MCLite", (MCBot,), {"N_DETERMINIZATIONS": 5}),
    "mc-null": MCNull,  # null control: same policy, different RNG stream
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


def make_bot(name: str, **kw):
    """Build a policy by name, FORWARDING kwargs (notably seed=).

    make_bot used to take no kwargs, so every duel script wrapped it as
    `lambda **k: make_bot("mc")` — which accepts a seed and silently drops it.
    `_seeded()` then never hit its TypeError fallback, and every MC opponent
    ran on OS entropy while the logs claimed a seeded, reproducible protocol
    (Codex, 2026-08-04). This is the SAME defect as the unseeded-anchor
    incident, reintroduced one layer up at the call site.
    """
    try:
        factory = REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"Unknown bot policy {name!r}. Available: {', '.join(sorted(REGISTRY))}")
    # Decide by SIGNATURE, never by catching TypeError: a genuine TypeError
    # raised inside a bot's constructor would be swallowed and retried, turning
    # a real bug into another plausible-looking fallback — the exact pattern
    # that has cost us three days this week (Codex, 2026-08-04).
    import inspect
    try:
        params = inspect.signature(factory).parameters
    except (TypeError, ValueError):        # builtins without introspection
        params = {}
    takes_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD
                       for p in params.values()) or "seed" in params
    if takes_kwargs:
        return factory(**kw)
    bot = factory()
    seed = kw.get("seed")
    if seed is not None and hasattr(bot, "rng"):
        import random as _r
        bot.rng = _r.Random(seed)
    return bot


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
# Absolute action-Q head trained on 240-world `Q^H(s,a)` labels. The v7w arm is
# the same architecture/wrapper, but the comparison does NOT isolate label
# quality: v13's MCBot-candidate/early-state training distribution differs from
# the pinned-v1/post-four-trick distribution used by MCValueLeaf.
REGISTRY["mc-vleaf-v13abs"] = _make_vleaf("ckpt_v13abs.pt")
REGISTRY["mc-vleaf-v8a-ep03"] = _make_vleaf("snapshots_v8a/ep03.pt")
# CAVEAT (Jerry's question, 2026-08-04): v11pair was trained with a PAIRWISE
# objective — only differences within a decision are constrained, so the value
# head's absolute level is free to drift per state. vleaf compares leaves
# ACROSS states, so this head may be uncalibrated for exactly the use the
# hybrid puts it to. Worth measuring; the prediction is that it underperforms.
# QUARANTINED (Codex, 2026-08-04): a pairwise head has no identified
# cross-state scale, so using it as a leaf evaluator is implementation-invalid.
# The measured 32.5% is a consequence of that, not evidence about learned
# leaves. Left unregistered so it cannot be duelled again by accident.
# REGISTRY["mc-vleaf-v11pair"] = _make_vleaf("snapshots_v11pair/ep07.pt")


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
# MARGIN 0 = trust the net's argmax over the MC ballot. The 0.02 bar was
# fitted on the teacher's own biased estimates; refitted against the N=240
# reference the best bar is ZERO, and held-out regret drops 2.870 -> 2.152,
# below deployed mc's 2.803 (2026-08-04).
def _make_race(ckpt: str, keep: int):
    def f(**kw):
        from ..rl.torch_policy import MCPriorRace
        b = MCPriorRace(ckpt, seed=kw.get("seed"))
        b.KEEP = keep
        return b
    return f


# Net as a root prior; same rollout budget, concentrated on fewer candidates.
def _make_randrace(keep: int):
    def f(**kw):
        from ..rl.torch_policy import MCRandomRace
        b = MCRandomRace("snapshots_v11pair/ep07.pt", seed=kw.get("seed"))
        b.KEEP = keep
        return b
    return f


# THE CONTROL for the racing result: same pruning size and budget, no net.
def _make_v3(random_fill: bool):
    def f(**kw):
        from ..ai.mcbot import MCBot as _MC
        b = _MC(seed=kw.get("seed"))
        b.V3_LEAD_SINGLES = True
        b.V3_LEAD_RANDOM = random_fill
        return b
    return f


# Ballot V3, lead layer: one single per DISTINCT effective level instead of
# only top + lowest-non-point per suit. Recovers 51 of 93 missed human leads.
REGISTRY["mc-v3lead"] = _make_v3(False)
REGISTRY["mc-v3lead-rand"] = _make_v3(True)   # the control
REGISTRY["mc-randrace4"] = _make_randrace(4)
REGISTRY["mc-race3-v11pair"] = _make_race("snapshots_v11pair/ep07.pt", 3)
REGISTRY["mc-race4-v11pair"] = _make_race("snapshots_v11pair/ep07.pt", 4)
# Codex's bounded hypothesis from the full-corpus threshold diagnostic: fit on
# even deal seeds, reported on odd, margin 0.005 cut stored all-state regret
# from 1.261 (at the deployed 0.02) to 1.142 raw points/decision. That is
# offline, early-state, fixed-ballot evidence — it justifies an ONLINE test,
# not a promotion.
REGISTRY["rl-override-v11pair-m005"] = _make_override_thr(
    "snapshots_v11pair/ep07.pt", 0.005)
REGISTRY["rl-override-v11pair-m0"] = _make_override_thr(
    "snapshots_v11pair/ep07.pt", 0.0)
REGISTRY["rl-override-v11pair"] = _make_override_thr(
    "snapshots_v11pair/ep07.pt", 0.02)
def _make_gate(path: str, gate: float):
    def f(**kw):
        from ..rl.torch_policy import MCGatedOverride
        b = MCGatedOverride(path)
        b.GATE = gate
        b._seed = kw.get("seed")
        return b
    return f


# Cheap net as a stakes DETECTOR: SmartBot on low-stakes decisions, full MC
# search on the ~12% the net flags. Gate fitted on a disjoint holdout half.
REGISTRY["mc-gate-v11pair"] = _make_gate("snapshots_v11pair/ep07.pt", 0.02)
REGISTRY["rl-override-v10res"] = _make_override("snapshots_v10res/ep09.pt")
