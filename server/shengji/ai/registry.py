"""Named bot policies, so the server (and experiments) can swap them out.

Add new policies here and document them in AI_POLICIES.md (repo root) with
their measured win rate. The server picks its bot via the SHENGJI_BOT env
var (default "smart")."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .heuristic import HeuristicBot
from .legacy_b3f8f61 import MCBotPreFix
from .mcbot import MCBot, MCSmartRoll
from .smart import SmartBot


def _smart_variant(name: str, **attrs):
    return type(name, (SmartBot,), attrs)


class MCPreFixNull(MCBotPreFix):
    """Null matched to `mc-prefix`: same pre-fix bot, different RNG stream.

    A null must match the OPPONENT. Using `mc-null` here would compare the
    current bot against a current-bot null while the opponent is the pre-fix
    one, which measures a treatment step rather than the noise floor.
    """

    def __init__(self, seed: int | None = None):
        super().__init__(None if seed is None else seed + 999_983)


class MCStrongNull(MCBot):
    """NULL for the N=60 lane: `mc-strong` with a different RNG stream."""

    N_DETERMINIZATIONS = 30

    def __init__(self, seed: int | None = None):
        super().__init__(None if seed is None else seed + 999_983)


class MCStrongS0EV2Null(MCBot):
    """S0e-v2 null with no cross-cluster overlap in the frozen 148M block."""

    N_DETERMINIZATIONS = 30
    NULL_SEED_OFFSET = 50_000_003

    def __init__(self, seed: int | None = None):
        shifted = None if seed is None else seed + self.NULL_SEED_OFFSET
        super().__init__(shifted)


class MCStrongRLCBC1Null(MCBot):
    """Fresh RLCB-C1 null with no overlap with any matched role stream."""

    N_DETERMINIZATIONS = 30
    NULL_SEED_OFFSET = 60_000_011

    def __init__(self, seed: int | None = None):
        shifted = None if seed is None else seed + self.NULL_SEED_OFFSET
        super().__init__(shifted)


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
    "mc-vstrong": type("MCVStrong", (MCBot,), {"N_DETERMINIZATIONS": 60}),
    # The BOT layer frozen at b3f8f61, before the sampler rewrite: old greedy
    # first-fit world sampler, no pair_cap/run_cap, no canonical hand order.
    # Runs on the CURRENT engine, so today's engine changes are shared by both
    # arms and cancel. Isolates "did the sampler work buy strength".
    "mc-prefix": MCBotPreFix,
    "mc-prefix-null": MCPreFixNull,
    # NULL for the N=60-vs-N=30 lane: identical to mc-strong, different RNG
    # stream. The N=10 `mc-null` cannot serve here — a null must match the
    # OPPONENT, or it measures a dose step instead of the noise floor.
    "mc-strong-null": MCStrongNull,
    "mc-strong-null-s0e-v2": MCStrongS0EV2Null,
    "mc-strong-null-rlcb-c1": MCStrongRLCBC1Null,
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

# S0 v1: one frozen report dose and explicit, separable mechanisms. Production
# `mc-strong` is unchanged. Every report arm spends N*K selection rollouts plus
# exactly 2R paired report rollouts on each contested decision; the uniform-work
# control spends the same N*K+2R total entirely on uniform selection.
# Chosen by the predeclared DEV calibration in s0_override_audit.py: 30/60/120
# retained only 2/3/5 of 12 N=300-positive incumbent overrides under LCB>0;
# 300 was the first dose to retain half with zero N=300-negative supports.
S0_REPORT_WORLDS = 300
REGISTRY.update({
    "mc-s0-report-mean": type("MCS0ReportMean", (MCBot,), {
        "N_DETERMINIZATIONS": 30,
        "REQUIRE_EXACT_WORK": True,
        "REPORT_FOLD_WORLDS": S0_REPORT_WORLDS,
        "REPORT_RULE": "mean",
        "REPORT_MIN_GAIN": 0.0,
    }),
    "mc-s0-report-lcb": type("MCS0ReportLCB", (MCBot,), {
        "N_DETERMINIZATIONS": 30,
        "REQUIRE_EXACT_WORK": True,
        "REPORT_FOLD_WORLDS": S0_REPORT_WORLDS,
        "REPORT_RULE": "lcb",
        "REPORT_MIN_GAIN": 0.0,
    }),
    "mc-s0-adaptive": type("MCS0Adaptive", (MCBot,), {
        "N_DETERMINIZATIONS": 30,
        "REQUIRE_EXACT_WORK": True,
        "ADAPTIVE_ALLOCATION": True,
        "REPORT_FOLD_WORLDS": S0_REPORT_WORLDS,
        "REPORT_RULE": "lcb",
        "REPORT_MIN_GAIN": 0.0,
    }),
    "mc-s0-adaptive-mean": type("MCS0AdaptiveMean", (MCBot,), {
        "N_DETERMINIZATIONS": 30,
        "REQUIRE_EXACT_WORK": True,
        "ADAPTIVE_ALLOCATION": True,
        "REPORT_FOLD_WORLDS": S0_REPORT_WORLDS,
        "REPORT_RULE": "mean",
        "REPORT_MIN_GAIN": 0.0,
    }),
    "mc-s0-random": type("MCS0Random", (MCBot,), {
        "N_DETERMINIZATIONS": 30,
        "REQUIRE_EXACT_WORK": True,
        "ADAPTIVE_ALLOCATION": True,
        "RANDOM_ALLOCATION": True,
        "REPORT_FOLD_WORLDS": S0_REPORT_WORLDS,
        "REPORT_RULE": "lcb",
        "REPORT_MIN_GAIN": 0.0,
    }),
    "mc-s0-random-mean": type("MCS0RandomMean", (MCBot,), {
        "N_DETERMINIZATIONS": 30,
        "REQUIRE_EXACT_WORK": True,
        "ADAPTIVE_ALLOCATION": True,
        "RANDOM_ALLOCATION": True,
        "REPORT_FOLD_WORLDS": S0_REPORT_WORLDS,
        "REPORT_RULE": "mean",
        "REPORT_MIN_GAIN": 0.0,
    }),
    "mc-s0-uniform-work": type("MCS0UniformWork", (MCBot,), {
        "N_DETERMINIZATIONS": 30,
        "REQUIRE_EXACT_WORK": True,
        "EXTRA_SELECTION_WORK": 2 * S0_REPORT_WORLDS,
    }),
})


def _make_policy_null(base_policy: str):
    """Return an exact policy clone whose only treatment is its RNG stream.

    Constructing the named base first avoids copying a hand-maintained subset
    of its search knobs.  That matters for the post-S0 composition screen: its
    null must inherit the terminal champion's report/allocation contract, not
    silently fall back to ordinary N=30 search.
    """
    def make(**kw):
        seed = kw.get("seed")
        shifted = None if seed is None else seed + 999_983
        forwarded = dict(kw)
        forwarded["seed"] = shifted
        return make_bot(base_policy, **forwarded)
    return make


# Champion-matched nulls for the two reachable LCB S0 survivors.  The existing
# `mc-strong-null` remains the SELECT-NONE/current champion control and is not
# changed because it is part of the already-running direct-v11 protocol.
REGISTRY["mc-s0-report-lcb-null"] = _make_policy_null("mc-s0-report-lcb")
REGISTRY["mc-s0-adaptive-null"] = _make_policy_null("mc-s0-adaptive")


def _make_structured_bury_policy(base_policy: str):
    """Enable only the screened S3a structured-bury treatment.

    Construct the exact named terminal S0 policy first so its ordinary-play
    search/report/allocation contract is inherited rather than copied.  The
    MCBot bury path keeps that base policy's literal bury as candidate zero;
    these are the only two behavioural switches changed by this factory.
    """
    def make(**kw):
        bot = make_bot(base_policy, **kw)
        if any(getattr(bot, field, False) for field in
               ("MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME")):
            raise RuntimeError(
                f"S3a base policy {base_policy!r} enables another S3 feature")
        bot.MC_BURY = True
        bot.STRUCTURED_BURY = True
        # Lower-case provenance is deliberately outside the uppercase gameplay
        # contract, just like the S3b base-policy binding below.
        bot.structured_bury_base_policy = base_policy
        return bot
    return make


# The current S0a result leaves exactly these three terminal possibilities:
# SELECT NONE/current, report-LCB, or adaptive-LCB.  Registrations authorize
# experiments only; production remains feature-off.
STRUCTURED_BURY_POLICIES = {
    "mc-strong": "mc-structured-bury",
    "mc-s0-report-lcb": "mc-s0-report-lcb-structured-bury",
    "mc-s0-adaptive": "mc-s0-adaptive-structured-bury",
}
for _base_policy, _treatment_policy in STRUCTURED_BURY_POLICIES.items():
    REGISTRY[_treatment_policy] = _make_structured_bury_policy(_base_policy)


def _make_exact_endgame_policy(base_policy: str):
    """Enable only the bounded S3b continuation on a named search policy.

    The terminal S0 result can leave any of three policies in production.
    Constructing that exact named policy first keeps its ballot, sampling dose,
    report fold and allocation rule intact.  The treatment then changes one
    switch only: heuristic rollouts become exact partnership-minimax once the
    fully determinized world reaches the proved four-card boundary.
    """
    def make(**kw):
        bot = make_bot(base_policy, **kw)
        if any(getattr(bot, field, False) for field in
               ("MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME")):
            raise RuntimeError(
                f"S3b base policy {base_policy!r} enables another S3 feature")
        bot.EXACT_ENDGAME = True
        bot.EXACT_ENDGAME_MAX_CARDS = 4
        bot.EXACT_ENDGAME_MAX_NODES = 250_000
        # Lower-case provenance is deliberately outside the policy's uppercase
        # behavioural contract.  Runners can still prove which terminal policy
        # was cloned without introducing another gameplay knob.
        bot.exact_endgame_base_policy = base_policy
        return bot
    return make


# Reachable terminal-S0 champions, each with exactly one feature-on S3b clone.
# These registrations authorize experiments only; production remains unchanged.
REGISTRY.update({
    "mc-exact-endgame": _make_exact_endgame_policy("mc-strong"),
    "mc-s0-report-lcb-exact-endgame": _make_exact_endgame_policy(
        "mc-s0-report-lcb"),
    "mc-s0-adaptive-exact-endgame": _make_exact_endgame_policy(
        "mc-s0-adaptive"),
})


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
        bot = factory(**kw)
    else:
        bot = factory()
        seed = kw.get("seed")
        if seed is not None and hasattr(bot, "rng"):
            import random as _r
            bot.rng = _r.Random(seed)
    # A class name is not a registry policy identity: several registered arms
    # share one class/factory with different checkpoints or thresholds. Bind
    # the exact name at construction so live decision records can be replayed.
    try:
        bot.policy_name = name
    except (AttributeError, TypeError):
        pass
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
_V11PAIR_NPZ_SHA256 = (
    "cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003"
)


def _make_override_thr(path: str, margin: float):
    def make(**kw):
        from pathlib import Path
        from ..rl.torch_policy import RLOverrideBot
        # Registry identity must not depend on the caller's cwd.  In particular,
        # the revalidation runner hashes server/snapshots_v11pair/ep07.npz, so
        # the policy must load those same absolute bytes even if another cwd
        # happens to contain a lookalike relative path.
        resolved = (Path(__file__).resolve().parents[2] / path).resolve()
        b = RLOverrideBot(str(resolved))
        expected_path = resolved.with_suffix(".npz")
        if (Path(b.checkpoint_path) != expected_path
                or b.checkpoint_sha256 != _V11PAIR_NPZ_SHA256):
            raise RuntimeError(
                "frozen v11pair registry checkpoint identity drift: "
                f"loaded {b.checkpoint_path} {b.checkpoint_sha256}, expected "
                f"{expected_path} {_V11PAIR_NPZ_SHA256}")
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


def _make_v11_anchor(*, random_control: bool = False,
                     search_base_policy: str = "mc-strong"):
    """Frozen v11pair proposal inside one literal MC search contract."""
    def make(**kw):
        from ..rl.torch_policy import (MCV11ProtectedAnchor,
                                       MCV11RandomAnchor)
        cls = MCV11RandomAnchor if random_control else MCV11ProtectedAnchor
        seed = kw.get("seed")
        search_base = make_bot(search_base_policy, seed=seed)
        return cls(
            "snapshots_v11pair/ep07.npz", seed=seed,
            search_base=search_base,
            search_base_policy=search_base_policy,
        )
    return make


# The first learned/search composition that preserves the complete current
# action set and all N=30 common worlds.  The random arm fires on exactly the
# same v11 threshold but protects an arbitrary non-Smart action, separating
# proposal quality from the generic effect of changing candidate 0.
REGISTRY["mc-v11anchor"] = _make_v11_anchor()
REGISTRY["mc-v11anchor-random"] = _make_v11_anchor(random_control=True)
# S0 can terminate with either the report-LCB mechanism or its deterministic
# adaptive allocator.  These variants compose v11 with that exact survivor;
# the original two entries above remain the SELECT-NONE/current-N=30 lane.
for _suffix, _base in (
    ("s0-report-lcb", "mc-s0-report-lcb"),
    ("s0-adaptive", "mc-s0-adaptive"),
):
    REGISTRY[f"mc-v11anchor-{_suffix}"] = _make_v11_anchor(
        search_base_policy=_base)
    REGISTRY[f"mc-v11anchor-{_suffix}-random"] = _make_v11_anchor(
        random_control=True, search_base_policy=_base)


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


# ---------------------------------------------------------------------------
# Value-at-leaf screen arms (DEV; shengji/train/leaf_policy.py).  The arm is
# the production search class with ONE override — its rollout leaf — and its
# strength depends entirely on the points head that evaluates truncated
# leaves, so the checkpoint id is part of the policy name, exactly as
# `_make_vleaf` above insists.  Nothing is registered by default: the arms
# appear only through `register_vleaf_arms` (the screen driver) or when the
# environment names the artifacts, so `scripts/evaluate.py` can drive them by
# name while the default registry stays production-only.
VLEAF_BASE_POLICY = "mc-s0-report-lcb"
VLEAF_LEAF_TRICKS = (0, 1, 2, 4)
#: which net evaluates the truncated leaf: ``public`` = the search head's
#: auxiliary points column on the PUBLIC observation (#226); ``cwv`` = the
#: complete-world value net's auxiliary points head on the determinized
#: clone itself (#229's afterstate tensors: the sampled world IS the input).
VLEAF_LEAF_MODELS = ("public", "cwv")
VLEAF_CHECKPOINT_ENV = "SHENGJI_VLEAF_CKPT"
VLEAF_PRIOR_ENV = "SHENGJI_VLEAF_PRIOR"
VLEAF_ALLOW_LEGACY_ENV = "SHENGJI_VLEAF_ALLOW_LEGACY"
VLEAF_LEAF_MODEL_ENV = "SHENGJI_VLEAF_LEAF_MODEL"


def vleaf_checkpoint_sha256(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError as exc:
        raise RuntimeError(f"value-at-leaf artifact {path} is unreadable: {exc}") from exc
    return h.hexdigest()


def vleaf_policy_name(*, leaf_tricks: int, checkpoint_id: str | None = None,
                      leaf_model: str = "public") -> str:
    """`mc-vleaf-<ckpt8>-t<T>` (public points head), `mc-vleaf-cwv-<ckpt8>-t<T>`
    (complete-world points head) or `mc-vleaf-prior-t<T>` (control)."""
    if type(leaf_tricks) is not int or leaf_tricks not in VLEAF_LEAF_TRICKS:
        raise ValueError(f"leaf_tricks must be one of {VLEAF_LEAF_TRICKS}")
    if leaf_model not in VLEAF_LEAF_MODELS:
        raise ValueError(f"leaf_model must be one of {VLEAF_LEAF_MODELS}")
    if checkpoint_id is None:
        return f"mc-vleaf-prior-t{leaf_tricks}"
    if leaf_model == "cwv":
        return f"mc-vleaf-cwv-{checkpoint_id}-t{leaf_tricks}"
    return f"mc-vleaf-{checkpoint_id}-t{leaf_tricks}"


def _make_vleaf_learned(checkpoint: str, sha256: str, leaf_tricks: int,
                        allow_legacy: bool, leaf_model: str = "public"):
    def make(**kw):
        from ..train.leaf_policy import make_vleaf_bot
        return make_vleaf_bot(checkpoint=checkpoint, leaf_tricks=leaf_tricks,
                              seed=kw.get("seed"), allow_legacy=allow_legacy,
                              expected_sha256=sha256, leaf_model=leaf_model)
    make.vleaf_artifact = (checkpoint, sha256)
    return make


def _make_vleaf_prior(prior: str, sha256: str, leaf_tricks: int):
    def make(**kw):
        from ..train.leaf_policy import make_vleaf_prior_bot
        return make_vleaf_prior_bot(prior=prior, leaf_tricks=leaf_tricks,
                                    seed=kw.get("seed"), expected_sha256=sha256)
    make.vleaf_artifact = (prior, sha256)
    return make


def register_vleaf_arms(*, checkpoint: str | os.PathLike | None = None,
                        prior: str | os.PathLike | None = None,
                        leaf_tricks=VLEAF_LEAF_TRICKS, allow_legacy: bool = False,
                        registry: dict | None = None,
                        leaf_model: str = "public") -> dict[str, str]:
    """Register the screen arms by name; returns ``{name: kind}`` (``learned``
    for the public head, ``cwv`` for the complete-world head, ``prior``).

    Idempotent for the same artifact bytes.  A name already bound to a
    different file refuses: a registry name is a policy identity, and a
    control silently rebound to another prior table would not be the control
    the record names.
    """
    registry = REGISTRY if registry is None else registry
    if leaf_model not in VLEAF_LEAF_MODELS:
        raise ValueError(f"leaf_model must be one of {VLEAF_LEAF_MODELS}")
    names: dict[str, str] = {}
    artifacts = []
    if checkpoint is not None:
        path = str(Path(checkpoint).resolve())
        kind = "cwv" if leaf_model == "cwv" else "learned"
        artifacts.append((kind, path, vleaf_checkpoint_sha256(path)))
    if prior is not None:
        path = str(Path(prior).resolve())
        artifacts.append(("prior", path, vleaf_checkpoint_sha256(path)))
    for t in leaf_tricks:
        for kind, path, sha in artifacts:
            if kind != "prior":
                name = vleaf_policy_name(leaf_tricks=t, checkpoint_id=sha[:8],
                                         leaf_model=leaf_model)
                factory = _make_vleaf_learned(path, sha, t, bool(allow_legacy), leaf_model)
            else:
                name = vleaf_policy_name(leaf_tricks=t)
                factory = _make_vleaf_prior(path, sha, t)
            existing = registry.get(name)
            bound = getattr(existing, "vleaf_artifact", None)
            if existing is not None and bound is None:
                raise RuntimeError(f"{name!r} is already a registered policy")
            if bound is not None and bound[1] != sha:
                raise RuntimeError(
                    f"{name!r} is bound to {bound[0]} ({bound[1][:12]}); refusing "
                    f"to rebind it to {path} ({sha[:12]})")
            if existing is None:
                registry[name] = factory
            names[name] = kind
    return names


if os.environ.get(VLEAF_CHECKPOINT_ENV) or os.environ.get(VLEAF_PRIOR_ENV):
    register_vleaf_arms(
        checkpoint=os.environ.get(VLEAF_CHECKPOINT_ENV) or None,
        prior=os.environ.get(VLEAF_PRIOR_ENV) or None,
        allow_legacy=os.environ.get(VLEAF_ALLOW_LEGACY_ENV) == "1",
        leaf_model=os.environ.get(VLEAF_LEAF_MODEL_ENV) or "public")


def register_cwv_policies(checkpoint: str, worlds, *, finish_trick: bool = True,
                          lcb: float = 0.0, receipt: str | None = None,
                          plies: int | None = None) -> list[str]:
    """Complete-world-value one-ply arms, named by their VALUE checkpoint.

    Same rule as ``_make_vleaf``: the checkpoint is the policy's identity, so
    every name embeds ``<ckpt8>`` (sha256 of the file, first eight hex) and
    the world count -- ``mc-cwv-<ckpt8>-w<W>`` -- and a bare ``mc-cwv`` never
    exists.  ``mc-cwv-prior-<ckpt8>-w<W>`` is the matching NO-LEARNING control: the
    same ballot, sampler and positions with the training receipt's stratified
    prior as the value.  The checkpoint is loaded lazily, once per process,
    and refused when its encoder identity is not the live afterstate encoder.
    ``plies`` (1 or 2) registers the TWO-PLY bot instead -- net-chosen replies
    for the rest of the current trick (1) or one more trick (2) --
    as ``mc-cwv2-<ckpt8>-w<W>[-p2]`` with control ``mc-cwv2-prior-...``.
    Returns the registered names.
    """
    from .cwv_policy import cwv_registry_entries
    entries = cwv_registry_entries(checkpoint, worlds, finish_trick=finish_trick,
                                   lcb=lcb, receipt=receipt, plies=plies)
    REGISTRY.update(entries)
    return sorted(entries)


def scaled_policy_name(base_policy: str, multiplier: float) -> str:
    return f"{base_policy}-x{float(multiplier):g}"


def _make_scaled_policy(base_policy: str, multiplier: float):
    """The named search policy with its selection AND report doses scaled.

    Production's own compute curve is the bar for any learned bot: on fresh
    deals `mc-s0-report-lcb` given 29.7x its rollouts (N=889/R=8890) scored
    +0.215 [+0.125, +0.309] against itself at 1x (2026-09-05), more than the
    value32 leaf probe.  ``N_DETERMINIZATIONS`` and ``REPORT_FOLD_WORLDS``
    scale together, rounded; the ballot, allocation and report rule are the
    base policy's, so the only treatment is the dose.
    """
    if float(multiplier) <= 0:
        raise ValueError("a dose multiplier must be positive")

    def make(**kw):
        factory = REGISTRY[base_policy]
        cls = factory if isinstance(factory, type) else type(make_bot(base_policy))
        if not issubclass(cls, MCBot):
            raise RuntimeError(f"{base_policy!r} is not an MC search policy")
        scaled = type(f"{cls.__name__}x{float(multiplier):g}", (cls,), {
            "N_DETERMINIZATIONS": max(1, round(cls.N_DETERMINIZATIONS * multiplier)),
            "REPORT_FOLD_WORLDS": (round(cls.REPORT_FOLD_WORLDS * multiplier)
                                   if cls.REPORT_FOLD_WORLDS else 0),
        })
        bot = scaled(seed=kw.get("seed"))
        bot.dose_multiplier = float(multiplier)
        bot.dose_base_policy = base_policy
        return bot
    return make


def register_scaled_policies(base_policy: str, multipliers) -> list[str]:
    """Register ``<base>-x<m>`` for every multiplier; return the names."""
    names = []
    for multiplier in multipliers:
        name = scaled_policy_name(base_policy, multiplier)
        REGISTRY[name] = _make_scaled_policy(base_policy, float(multiplier))
        names.append(name)
    return names


# Production's compute curve at the ladder's rungs (N=90/R=900, N=300/R=3000).
register_scaled_policies("mc-s0-report-lcb", (3, 10))


def _register_cwv_from_env() -> None:
    """``SHENGJI_CWV_CKPT`` (+ ``_WORLDS``/``_FINISH_TRICK``/``_LCB``/``_RECEIPT``)
    registers the arms at import so ``scripts/evaluate.py`` can name them."""
    import os
    if not os.environ.get("SHENGJI_CWV_CKPT"):
        return
    from .cwv_policy import env_registry_entries
    REGISTRY.update(env_registry_entries())


_register_cwv_from_env()


def register_cwv_puct_policies(checkpoint: str, simulations, **search) -> list[str]:
    """PUCT-over-sampled-worlds arms, named ``mc-cwvpuct-<ckpt8>-s<S>``.

    Same identity rule as ``register_cwv_policies``: the VALUE checkpoint and
    the simulation budget are in the name; the search parameters (world
    pool, batch, c_puct, prior mode / prior checkpoint, receipt for the
    control) are keyword arguments recorded in every decision and in the
    duel's calibration binding.  ``mc-cwvpuct-prior-<ckpt8>-s<S>`` is the
    matching no-learning control (uniform prior, stratified-prior leaf).
    Returns the registered names.
    """
    from .cwv_puct import cwv_puct_registry_entries
    entries = cwv_puct_registry_entries(checkpoint, simulations, **search)
    REGISTRY.update(entries)
    return sorted(entries)
