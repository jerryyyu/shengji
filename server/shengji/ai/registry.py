"""Named bot policies, so the server (and experiments) can swap them out.

Add new policies here and document them in AI_POLICIES.md (repo root) with
their measured win rate. The server picks its bot via the SHENGJI_BOT env
var (default "smart")."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .heuristic import HeuristicBot
from .mcbot import MCBot, MCSmartRoll
from .smart import SmartBot


def _smart_variant(name: str, **attrs):
    return type(name, (SmartBot,), attrs)


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


def make_bot(name: str, **kw):
    """Build a policy by name, FORWARDING kwargs (notably seed=).

    A wrapper that accepts a seed and drops it (`lambda **k: make_bot("mc")`)
    makes every MC opponent run on OS entropy while the logs claim a seeded,
    reproducible protocol, so callers pass kwargs straight through.
    """
    try:
        factory = REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"Unknown bot policy {name!r}. Available: {', '.join(sorted(REGISTRY))}")
    # Decide by SIGNATURE, never by catching TypeError: a genuine TypeError
    # raised inside a bot's constructor would be swallowed and retried, turning
    # a real bug into another plausible-looking fallback.
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


# ---------------------------------------------------------------------------
# Value-at-leaf screen arms (DEV; shengji/train/leaf_policy.py).  The arm is
# the production search class with ONE override — its rollout leaf — and its
# strength depends entirely on the points head that evaluates truncated
# leaves, so the checkpoint id is part of the policy name.  Nothing is
# registered by default: the arms appear only through `register_vleaf_arms`
# (the screen driver) or when the
# environment names the artifacts, so `scripts/evaluate.py` can drive them by
# name while the default registry stays production-only.
VLEAF_BASE_POLICY = "mc-s0-report-lcb"
VLEAF_LEAF_TRICKS = (0, 1, 2, 4)
#: which net evaluates the truncated leaf: ``public`` = the search head's
#: auxiliary points column on the PUBLIC observation; ``cwv`` = the
#: complete-world value net's auxiliary points head on the determinized
#: clone itself (its afterstate tensors: the sampled world IS the input).
VLEAF_LEAF_MODELS = ("public", "cwv")
#: where the leaf is consulted: ``all`` (every rollout) or ``report`` (only
#: the report fold's paired worlds; selection rollouts are production's).
VLEAF_LEAF_STAGES = ("all", "report")
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


def vleaf_policy_suffix(*, leaf_stage: str = "all") -> str:
    """The variant flag in the policy name: ``""`` for the default (every
    rollout), ``-report`` for the report-fold-only leaf."""
    if leaf_stage not in VLEAF_LEAF_STAGES:
        raise ValueError(f"leaf_stage must be one of {VLEAF_LEAF_STAGES}")
    return "-report" if leaf_stage == "report" else ""


def vleaf_policy_name(*, leaf_tricks: int, checkpoint_id: str | None = None,
                      leaf_model: str = "public", leaf_stage: str = "all") -> str:
    """`mc-vleaf-<ckpt8>-t<T>` (public points head),
    `mc-vleaf-cwv-clamp-<ckpt8>-t<T>` (complete-world points head floored at
    the clone's banked attacker points, ``leaf_policy.POINTS_CLAMP``; the
    unclamped `mc-vleaf-cwv-<ckpt8>-t<T>` is retired, its scores differ) or
    `mc-vleaf-prior-t<T>` (control), plus :func:`vleaf_policy_suffix`
    (``-report``)."""
    if type(leaf_tricks) is not int or leaf_tricks not in VLEAF_LEAF_TRICKS:
        raise ValueError(f"leaf_tricks must be one of {VLEAF_LEAF_TRICKS}")
    if leaf_model not in VLEAF_LEAF_MODELS:
        raise ValueError(f"leaf_model must be one of {VLEAF_LEAF_MODELS}")
    suffix = vleaf_policy_suffix(leaf_stage=leaf_stage)
    if checkpoint_id is None:
        return f"mc-vleaf-prior-t{leaf_tricks}{suffix}"
    if leaf_model == "cwv":
        return f"mc-vleaf-cwv-clamp-{checkpoint_id}-t{leaf_tricks}{suffix}"
    return f"mc-vleaf-{checkpoint_id}-t{leaf_tricks}{suffix}"


def _make_vleaf_learned(checkpoint: str, sha256: str, leaf_tricks: int,
                        allow_legacy: bool, leaf_model: str = "public",
                        leaf_stage: str = "all"):
    def make(**kw):
        from ..train.leaf_policy import make_vleaf_bot
        return make_vleaf_bot(checkpoint=checkpoint, leaf_tricks=leaf_tricks,
                              seed=kw.get("seed"), allow_legacy=allow_legacy,
                              expected_sha256=sha256, leaf_model=leaf_model,
                              leaf_stage=leaf_stage)
    make.vleaf_artifact = (checkpoint, sha256)
    return make


def _make_vleaf_prior(prior: str, sha256: str, leaf_tricks: int, leaf_stage: str = "all"):
    def make(**kw):
        from ..train.leaf_policy import make_vleaf_prior_bot
        return make_vleaf_prior_bot(prior=prior, leaf_tricks=leaf_tricks,
                                    seed=kw.get("seed"), expected_sha256=sha256,
                                    leaf_stage=leaf_stage)
    make.vleaf_artifact = (prior, sha256)
    return make


def register_vleaf_arms(*, checkpoint: str | os.PathLike | None = None,
                        prior: str | os.PathLike | None = None,
                        leaf_tricks=VLEAF_LEAF_TRICKS, allow_legacy: bool = False,
                        registry: dict | None = None,
                        leaf_model: str = "public", leaf_stage: str = "all") -> dict[str, str]:
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
    variant = {"leaf_stage": leaf_stage}
    vleaf_policy_suffix(**variant)     # refuses an unknown stage
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
                                         leaf_model=leaf_model, **variant)
                factory = _make_vleaf_learned(path, sha, t, bool(allow_legacy), leaf_model,
                                              **variant)
            else:
                name = vleaf_policy_name(leaf_tricks=t, **variant)
                factory = _make_vleaf_prior(path, sha, t, **variant)
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

    The checkpoint is the policy's identity, so
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


def _guarded_shortlist_factory(name: str, factory):
    """Wrap a shortlist factory so ``make_bot`` REFUSES anything else.

    The one-ply trap, made unreachable: `register_cwv_policies` looks like the
    way to register the W32 complete-world-value arm, but the bot it registers
    under ``mc-cwv-<ckpt8>-w32`` is ``CWVOnePly_w32`` -- a different design
    that LOSES on the scorecard.  A generator wired to it would run for hours
    producing data from a policy worse than production, with every progress
    counter healthy.  So the type is checked at the registry boundary, on
    whatever the factory returns, and a mismatch raises.
    """
    from ..train.cwv_shortlist import _require_shortlist

    def make(**kw):
        return _require_shortlist(factory(**kw), name)
    return make


def register_cwv_shortlist_policies(checkpoint: str, worlds=(32,),
                                    **recipe) -> list[str]:
    """The DEV shortlist bot (`train.cwv_shortlist.CWVShortlistBot`) as
    registry policies, so ``make_bot`` -- and therefore
    ``harvest/trajectory.py --policy`` -- can reach it.

    Names are ``mc-shortlist-<ckpt8>-w<W>``: distinct by eye from the one-ply
    ``mc-cwv-<ckpt8>-w<W>`` entries of `register_cwv_policies`, which are NOT
    this policy.  The default recipe is the screened one (worlds 32,
    alternatives 4, selection_worlds 30, report_worlds 300, encoding
    mlp-static, reuse_successors on); ``recipe`` overrides it.  Returns the
    registered names.
    """
    from ..train.cwv_shortlist import shortlist_registry_entries

    entries = shortlist_registry_entries(checkpoint, worlds, **recipe)
    guarded = {name: _guarded_shortlist_factory(name, factory)
               for name, factory in entries.items()}
    REGISTRY.update(guarded)
    return sorted(guarded)


def register_cwv_bury_policies(checkpoint: str, worlds=(32,), *, arm,
                               bury_config=None, **play_recipe) -> list[str]:
    """Register named opt-in bury wrappers without replacing play defaults."""
    from ..train.cwv_bury_policy import bury_registry_entries

    entries = bury_registry_entries(checkpoint, worlds, arm=arm,
                                    bury_config=bury_config, **play_recipe)
    REGISTRY.update(entries)
    return sorted(entries)


def scaled_policy_name(base_policy: str, multiplier: float) -> str:
    return f"{base_policy}-x{float(multiplier):g}"


def _make_scaled_policy(base_policy: str, multiplier: float):
    """The named search policy with its selection AND report doses scaled.

    Production's own compute curve is the bar for any learned bot: on fresh
    deals `mc-s0-report-lcb` given 29.7x its rollouts (N=889/R=8890) scored
    +0.215 [+0.125, +0.309] against itself at 1x, more than the
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


def _register_cwv_shortlist_from_env() -> None:
    """``SHENGJI_CWV_SHORTLIST_CKPT`` (+ the ``_WORLDS``/``_ALTERNATIVES``/
    ``_SELECTION_WORLDS``/``_REPORT_WORLDS``/``_BATCH_SIZE``/``_ENCODING``/
    ``_REUSE_SUCCESSORS`` knobs, plus the opt-in ``SHENGJI_CWV_PRIOR_CKPT`` /
    ``_SHA256`` / ``_THRESHOLD`` / ``_TOP`` prior group) registers
    ``mc-shortlist-<ckpt8>-w<W>-r<recipe8>[-prior-<sha8>]`` at import, so a
    spawned trajectory worker resolves the same name the parent did
    (`train.cwv_shortlist.shortlist_env_recipe`)."""
    import os
    import sys
    if not os.environ.get("SHENGJI_CWV_SHORTLIST_CKPT"):
        return
    module = sys.modules.get("shengji.train.cwv_shortlist")
    if module is not None and not hasattr(module, "shortlist_env_recipe"):
        # That module is PARTWAY through its own import: it reached its
        # ``from ..ai.registry import REGISTRY`` line, which is what is running
        # us now, so its own definitions do not exist yet.  Registering here
        # would raise ImportError.  It calls this function again from its
        # module bottom, where the symbol does exist, so do nothing.
        return
    from ..train.cwv_shortlist import shortlist_env_recipe
    checkpoint, worlds, recipe = shortlist_env_recipe()
    register_cwv_shortlist_policies(checkpoint, worlds, **recipe)


def _register_cwv_bury_from_env() -> None:
    """Explicit opt-in, including fresh spawned trajectory worker processes."""
    import os
    import sys
    if not os.environ.get("SHENGJI_CWV_BURY_ARM"):
        return
    module = sys.modules.get("shengji.train.cwv_bury_policy")
    if module is not None and not hasattr(module, "bury_env_recipe"):
        return
    from ..train.cwv_bury_policy import bury_env_recipe
    checkpoint, worlds, recipe, arm, config, budget = bury_env_recipe()
    register_cwv_bury_policies(checkpoint, worlds, arm=arm,
                              bury_config=config, serving_budget_seconds=budget, **recipe)


def register_pv_search_policies(checkpoint: str, *, sha256: str, **recipe) -> list[str]:
    """The production wrapper for the policy/value search (`train.pv_search_policy`)
    as a registry policy: ``pv-search-<ckpt8>-w<W>-k<K>-r<recipe8>``.  The factory
    is type-guarded at the registry boundary, as the shortlist is."""
    from ..train.pv_search_policy import pv_registry_entries

    entries = pv_registry_entries(checkpoint, sha256=sha256, **recipe)
    REGISTRY.update(entries)
    return sorted(entries)


def _register_pv_search_from_env() -> None:
    """``SHENGJI_PV_CKPT`` + ``SHENGJI_PV_SHA256`` (+ the ``_WORLDS`` / ``_CANDIDATES`` /
    ``_CAP`` / ``_BATCH_SIZE`` / ``_SEED`` / ``_SERVING_BUDGET_SECONDS`` knobs) register
    the pv-search policy at import, so a spawned worker resolves the same name
    the parent did (`train.pv_search_policy.pv_env_recipe`)."""
    import os
    import sys
    if not os.environ.get("SHENGJI_PV_CKPT"):
        return
    module = sys.modules.get("shengji.train.pv_search_policy")
    if module is not None and not hasattr(module, "pv_env_recipe"):
        return
    from ..train.pv_search_policy import pv_env_recipe
    recipe = pv_env_recipe()
    checkpoint = recipe.pop("checkpoint")
    register_pv_search_policies(checkpoint, **recipe)
    raw = os.environ.get("SHENGJI_PV_SINGLETON_CHALLENGER", "0")
    if raw not in ("", "0", "1"):
        raise ValueError("SHENGJI_PV_SINGLETON_CHALLENGER must be 0 or 1")
    if raw == "1":
        from ..train.pv_search_policy import singleton_registry_entries
        REGISTRY.update(singleton_registry_entries(checkpoint=checkpoint, **recipe))


def register_exploit_policies(checkpoint: str, *, sha256: str, **recipe) -> list[str]:
    """The exploitability probe's attacker (`train.exploit_policy`) as a registry
    policy: ``<pv-search name>-exploit-<recipe12>``.  It is a DIAGNOSTIC, never a
    served arm; it is here so the existing screen harness can run it with no new
    instrument."""
    from ..train.exploit_policy import exploit_registry_entries

    entries = exploit_registry_entries(checkpoint, sha256=sha256, **recipe)
    REGISTRY.update(entries)
    return sorted(entries)


def _register_exploit_from_env() -> None:
    """``SHENGJI_EXPLOIT_FLOOR`` (+ ``_TEMPERATURE`` / ``_SCOPE``) on top of the
    ``SHENGJI_PV_*`` recipe registers the exploiter arm at import.

    WITHOUT ``SHENGJI_EXPLOIT_FLOOR`` THIS DOES NOTHING, which is the point: the
    probe is inert in every process that has not deliberately asked for it, so
    no served path can reach it by accident.
    """
    import os
    import sys
    if not os.environ.get("SHENGJI_EXPLOIT_FLOOR") or not os.environ.get("SHENGJI_PV_CKPT"):
        return
    module = sys.modules.get("shengji.train.exploit_policy")
    if module is not None and not hasattr(module, "exploit_env_recipe"):
        return
    from ..train.exploit_policy import exploit_env_recipe
    from ..train.pv_search_policy import pv_env_recipe
    recipe = pv_env_recipe()
    recipe.update(exploit_env_recipe())
    register_exploit_policies(recipe.pop("checkpoint"), **recipe)


def _register_netroll_from_env() -> None:
    """``SHENGJI_NETROLL_CKPT`` (+ ``_TRICKS``/``_STAGES``/``_RECEIPT``) registers
    the net-rollout arms (``mc-netroll-<ckpt8>-k<K>[-all]`` and their
    ``mc-netroll-prior-...`` controls; ``train.net_rollout``) at import."""
    import os
    if not os.environ.get("SHENGJI_NETROLL_CKPT"):
        return
    from ..train.net_rollout import register_netroll_from_env
    register_netroll_from_env()


_register_netroll_from_env()
_register_cwv_shortlist_from_env()
_register_pv_search_from_env()
_register_exploit_from_env()
_register_cwv_bury_from_env()
