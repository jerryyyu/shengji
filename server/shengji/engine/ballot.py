"""Versioned ballot contract — one identity for "which actions were on offer".

The project has two independent candidate generators: `MCBot._candidates()`
and `rl.actions.enumerate_actions()`. Nothing tied them together, so a net
could be trained against one and deployed against the other with no error and
no warning. That is not a hypothetical failure mode — it is the same one three
times:

  * **Elo 798**: play-time enumeration flipped to a wider ballot under a net
    trained on the narrow one.
  * **v10res**: labels collected over `MCBot._candidates()`, inference run over
    `enumerate_actions()`. 11 of 12 decisions enumerated differently. The
    checkpoint looked like a failed idea; it was a mismatch.
  * **v13abs**: high-N labels covered `_candidates()` while `MCValueLeaf`
    maximised over the pinned v1 ballot — one of two misalignments that made
    the run uninformative.

An identity is only worth carrying if it cannot drift from the thing it names.
The first version of this module hand-wrote each spec, which Codex correctly
rejected: a hand-maintained description does not change when the generator
changes, and it captured 4 of the 9 attributes `_candidates()` actually reads.
So identity is now DERIVED, from two things that both really determine the
action set:

  1. the live values of every attribute the generator reads, and
  2. a digest of the generator's own source (plus the same-module helpers it
     calls), so editing the code changes the identity.

Consequence, and it is the intended one: refactoring a generator invalidates
the ballot claim of every checkpoint trained before it. That is correct. If
the code that enumerates actions changed, you no longer have evidence that a
previously-trained net saw the same action set, and a comment-only edit
forcing a re-stamp is a much cheaper failure than another Elo-798.

Policies that do not run a search ballot at all (`smart`, `heuristic`) report
`NO_BALLOT`, never a fabricated MC identity.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class BallotSpec:
    """One configuration of "which legal actions are offered for scoring".

    `config` is a sorted tuple of pairs, not a dict: a frozen dataclass holding
    a mutable dict is not frozen in the way that matters. Mutating one entry
    changed the digest after registration, so a registry key and the object it
    pointed at could disagree.
    """

    name: str
    version: int
    #: which generator implements it — the thing that actually differed
    source: str
    #: every attribute the generator reads, at its live value
    config: tuple[tuple[str, object], ...] = ()
    #: sha256 over the generator's source and its same-module helpers
    source_digest: str = ""
    note: str = ""

    def __post_init__(self):
        if not isinstance(self.config, tuple):
            raise TypeError(
                "config must be an immutable tuple of sorted pairs; a dict "
                "lets a caller change this spec's identity after it has been "
                "recorded (Codex).")

    @property
    def digest(self) -> str:
        """Stable short hash over everything that changes the action set."""
        payload = json.dumps(
            {k: v for k, v in asdict(self).items() if k != "note"},
            sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]

    def __str__(self) -> str:
        return f"{self.name}@v{self.version}[{self.digest}]"

    def explain(self, other: "BallotSpec") -> str:
        """Human-readable reason two ballots differ — for the failure message."""
        if self.source != other.source:
            return f"different generators: {self.source} vs {other.source}"
        if self.source_digest != other.source_digest:
            return (f"same generator, EDITED source "
                    f"({self.source_digest[:8]} vs {other.source_digest[:8]})")
        a, b = dict(self.config), dict(other.config)
        diffs = [f"{k}: {a.get(k, '-')} -> {b.get(k, '-')}"
                 for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
        return "; ".join(diffs) or "no attribute differs (name/version differ)"


class BallotMismatch(RuntimeError):
    """Raised when data labelled under one ballot meets another at play time."""


#: Policies that never enumerate a search ballot. Reporting these as
#: `mc_candidates@v1` made the evaluator manifest authoritatively wrong.
NO_BALLOT = BallotSpec(
    name="none", version=0, source="(no search ballot)",
    note="Policy chooses an action directly; nothing is enumerated or scored.")


# ------------------------------------------------------------ source digests

#: Top-level package whose code counts as "part of the ballot". Callees outside
#: it (stdlib, numpy) are treated as fixed infrastructure.
_PKG = "shengji"


def _module_name_of(obj) -> str:
    """Defining module of a callable, including C extension members.

    Compiled functions from a C extension often carry no usable `__module__`,
    so fall back to finding the loaded module that actually holds this object.
    """
    name = getattr(obj, "__module__", None)
    if name:
        return name
    import sys
    for mod_name, mod in list(sys.modules.items()):
        if mod is not None and getattr(mod, "__dict__", None):
            if any(v is obj for v in mod.__dict__.values()):
                return mod_name
    return ""


def _fingerprint(obj) -> str:
    """Source text if it exists, else the bytes of the compiled artifact.

    The generator calls into `shengji.engine._fast`, a compiled extension.
    Digesting only source would leave the ballot's real implementation — the
    .so that actually decides tractors and legality — outside its identity.
    """
    try:
        return "src:" + inspect.getsource(obj)
    except (OSError, TypeError):
        import sys
        mod = sys.modules.get(_module_name_of(obj))
        path = getattr(mod, "__file__", None)
        if path and os.path.exists(path):
            with open(path, "rb") as fh:
                return (f"bin:{_module_name_of(obj)}:"
                        f"{hashlib.sha256(fh.read()).hexdigest()[:16]}")
        return f"opaque:{_module_name_of(obj)}.{getattr(obj, '__name__', '?')}"


def _project_callees(fn, owner=None) -> list:
    """Direct callees of `fn` that belong to this project.

    Two call shapes, because covering only the first left the identity bound to
    almost nothing that matters. `MCBot._candidates` calls seven helpers as
    `self._lead(...)`, `self._follow(...)` and so on — those methods ARE the
    generator, and an earlier version of this function, which looked only at
    bare names, would not have noticed any of them changing (Codex).
    """
    try:
        tree = ast.parse(inspect.getsource(fn).lstrip())
    except (OSError, SyntaxError, TypeError):
        return []
    out = []
    g = getattr(fn, "__globals__", {})
    bare, methods = set(), set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        if isinstance(n.func, ast.Name):
            bare.add(n.func.id)
        elif (isinstance(n.func, ast.Attribute)
              and isinstance(n.func.value, ast.Name)
              and n.func.value.id == "self"):
            methods.add(n.func.attr)
    # Resolve bare names through the function's own globals — the same lookup a
    # bare-name call performs at runtime. Going via inspect.getmodule() instead
    # returns None whenever the module is not in sys.modules, which silently
    # dropped every helper and made this a no-op its own test could not see.
    for name in sorted(bare):
        obj = g.get(name)
        if obj is None or inspect.isclass(obj):
            continue
        mod = _module_name_of(obj)
        # Same module as the generator, or anywhere in this package. The
        # same-module arm matters for generators that live outside `shengji`
        # (scripts, experiments) whose helpers sit right beside them.
        if mod.split(".")[0] == _PKG or mod == getattr(fn, "__module__", None):
            out.append(obj)
    # Resolve self.<method> against the owning class, walking the MRO so an
    # override in a subclass is the code that actually runs.
    if owner is not None:
        for name in sorted(methods):
            obj = getattr(owner, name, None)
            if inspect.isfunction(obj) or inspect.ismethod(obj):
                out.append(obj)
    return out


def _key(obj) -> tuple:
    return (getattr(obj, "__module__", ""),
            getattr(obj, "__qualname__", getattr(obj, "__name__", repr(obj))))


def source_digest(fn, owner=None, max_depth: int = 3) -> str:
    """Digest binding a ballot's identity to the code that implements it.

    Walks the call graph TRANSITIVELY from the generator, through project
    functions and through `self.<method>` helpers on the owning class, so a
    change to the executable action set moves the identity even when no flag
    changed. Bounded by `max_depth` and a visited set; parts are sorted so the
    digest does not depend on traversal order.

    Compiled callees are folded in by binary digest, deduplicated by module so
    several functions from one .so hash it once.
    """
    parts, seen, seen_bin = [], set(), set()
    stack = [(fn, 0)]
    while stack:
        obj, depth = stack.pop()
        k = _key(obj)
        if k in seen:
            continue
        seen.add(k)
        fp = _fingerprint(obj)
        if fp.startswith("bin:"):
            mod = fp.split(":")[1]
            if mod in seen_bin:
                continue
            seen_bin.add(mod)
        parts.append(fp)
        if depth < max_depth:
            stack += [(c, depth + 1) for c in _project_callees(obj, owner)]
    return hashlib.sha256("".join(sorted(parts)).encode()).hexdigest()[:16]


# ------------------------------------------------------------- MC derivation

#: Every attribute `MCBot._candidates()` reads. Not a curated subset — the
#: test re-derives this from the live source and fails if a new one appears,
#: which is what stops the identity from quietly falling behind the code.
MC_BALLOT_ATTRS = (
    "FOLLOW_MAX_CANDIDATES",
    "LEAD_MAX_CANDIDATES",
    "MAX_CANDIDATES",
    "RETAIN_ALL_LEAD_PAIRS",
    "RISKY_THROWS",
    "TRUMP_BALLOT",
    "V3_LEAD_RANDOM",
    "V3_LEAD_SINGLES",
    "WIDE_FOLLOW_BALLOT",
    "WIDE_LEAD_BALLOT",
)


def mc_ballot(bot) -> BallotSpec:
    """Derive the ballot a live MCBot is configured to enumerate."""
    from ..ai.mcbot import MCBot
    cfg = tuple(sorted((a, getattr(bot, a, None)) for a in MC_BALLOT_ATTRS))
    # owner is the LIVE class, so a subclass that overrides _lead/_follow gets
    # a different identity — which it must, because it generates differently.
    owner = type(bot) if not inspect.isclass(bot) else bot
    return BallotSpec(
        name="mc_candidates", version=1, source="MCBot._candidates",
        config=cfg,
        source_digest=source_digest(MCBot._candidates, owner=owner))


def rl_ballot(exhaustive_follows: bool = False,
              include_throws: bool = False) -> BallotSpec:
    """Derive the ballot `enumerate_actions` produces for these switches.

    These are independent switches, so there are four ballots, not the two
    ("v1"/"v2") the hand-written registry pretended existed.
    """
    from ..rl.actions import enumerate_actions
    cfg = (("exhaustive_follows", bool(exhaustive_follows)),
           ("include_throws", bool(include_throws)))
    return BallotSpec(
        name="rl_actions", version=1, source="rl.actions.enumerate_actions",
        config=cfg, source_digest=source_digest(enumerate_actions))


def policy_ballots(name: str) -> dict:
    """Every ballot STAGE a registered policy uses, keyed by stage.

    Policies are not all single-stage, and reporting one ballot for a
    multi-stage policy is how v13abs was mis-scored. `MCValueLeaf` enumerates
    root candidates with `MCBot._candidates` but asks its NET about leaf
    actions from `enumerate_actions` — the leaf is the stage that binds the
    checkpoint, and reporting only the root hid exactly that (Codex).

    Raises rather than returning "unknown": a manifest that guesses is worse
    than one that refuses, because it reads as authoritative.
    """
    from ..ai.registry import make_bot
    bot = make_bot(name)                    # a construction failure is fatal
    stages = {}
    # `_ballot` is the attribute an override policy keeps its generator on.
    # Dropping it from this lookup made `rl-override-v11pair` report `none@v0`
    # while it was in fact scoring `self._ballot._candidates()`.
    for attr in ("mc", "_ballot", None):
        inner = bot if attr is None else getattr(bot, attr, None)
        if inner is not None and hasattr(inner, "_candidates"):
            stages["root"] = mc_ballot(inner)
            break
    # A net is not synonymous with an RL-enumeration LEAF.  Override, racing
    # and protected-anchor policies score the MC ROOT ballot; reporting them as
    # rl_actions was the provenance version of the v10res mismatch.  Those
    # policies expose the exact generator on `_net_ballot`.  Only policies that
    # really ask their model about rl.actions (RLBot/MCValueLeaf) fall through
    # to the leaf identity.
    model_ballot = getattr(bot, "_net_ballot", None)
    if getattr(bot, "net", None) is not None and model_ballot is not None:
        stages["model"] = mc_ballot(model_ballot)
    elif getattr(bot, "net", None) is not None:
        stages["leaf"] = rl_ballot()
    return stages or {"root": NO_BALLOT}


def ballot_for_policy(name: str) -> BallotSpec:
    """The single ballot that BINDS a policy — its leaf stage if it has one.

    For a multi-stage policy the binding stage is the one a checkpoint is
    trained against, not the root the search happens to enumerate.
    """
    stages = policy_ballots(name)
    return stages.get("model") or stages.get("leaf") or stages["root"]


# ---------------------------------------------------------------- the gate

#: Legacy checkpoints predate provenance. An explicit, loud, per-run opt-out —
#: never a default warning, which is the failure mode this module exists to end.
ESCAPE_HATCH = "SHENGJI_ALLOW_BALLOT_MISMATCH"


def assert_compatible(labelled: BallotSpec, played: BallotSpec,
                      *, context: str = "") -> None:
    """Refuse a train/play pairing whose action sets are not the same contract.

    This is the guard that would have caught Elo-798, v10res and v13abs.
    """
    if labelled.digest == played.digest:
        return
    where = f" [{context}]" if context else ""
    msg = (f"ballot mismatch{where}: labelled under {labelled}, played under "
           f"{played}. Difference: {labelled.explain(played)}. A model may "
           f"only score the ballot it was trained on — widening it at play "
           f"time is the Elo-798 failure. Regenerate labels under the play "
           f"ballot, or pin play to the labelled one.")
    if os.environ.get(ESCAPE_HATCH):
        print(f"\n*** BALLOT MISMATCH ALLOWED BY {ESCAPE_HATCH} ***\n{msg}\n"
              f"*** Results from this run are RESEARCH ONLY and must not be "
              f"used for a strength claim. ***\n", flush=True)
        return
    raise BallotMismatch(msg)


# ------------------------------------------------------- historical records
# What the three failures were, kept as documentation. These are RECORDED
# identities, not live ones: they cannot be re-derived because the code they
# named has since changed. Never compare a live ballot against them.

HISTORICAL = {
    "elo798": "play-time enumeration widened under a net trained narrow",
    "v10res": "labels over MCBot._candidates, inference over enumerate_actions",
    "v13abs": "high-N labels over _candidates, leaf maximised over pinned v1",
}
