"""The unified model's slots as a served registry entry, OFF unless the environment names the package.

``SHENGJI_PV_UNIFIED_CKPT`` + ``SHENGJI_PV_UNIFIED_SHA256`` (both, or neither) name one unified
readout package (``ai.unified_readout_numpy``, NumPy only).  With them set, the registry gains one
more name beside the pv-search names it registers anyway:

    <served name>-ushare<sha8>-uvalue<sha8>-ureply<sha8>

whose factory builds the served bot through the unchanged registry entry and then fills four of its
learned slots from the package (`unified_slots`): the belief proposal and the root prior from one
trunk forward per decision (``ushare``), the value of the decision's own-trick leaves (``uvalue``)
and the greedy finish's reply prior (``ureply``) from the per-world readout on that same forward's
card states.  The search, its rules, budgets, bury and declaration are the served name's.  The
served value package still scores terminal leaves, bury and declaration, and the served prior
package stays bound for the replies the readout does not cover.

The belief package (``SHENGJI_PV_BELIEF_CKPT`` / ``_SHA256``, the served words) must carry the
unified package's trunk: registration loads both, hash-checked, and refuses a pair whose trunk
arrays differ, so a wrong pair fails where the server imports the registry and not at a room's
first decision.

Unset, this module is never imported: the registry holds the names it held, and every bot is built
by the code that built it.  Set, the base names stay registered beside the new one; ``SHENGJI_BOT``
chooses.

Two functions of the served search are wrapped once per process when the first such bot is built
(`activate`): ``pv_tree_search.greedy_reply_ply`` and ``pv_encode_prefix.score_leaves``.  Each
wrapper runs the served function with its own arguments for every bot that does not carry the
readout, so a served bot in the same process decides as it did.

Each play decision's record gains a ``unified`` entry (`RECORD_FIELDS`): the package and how many
root priors, value rows and reply rows of that decision the package filled and how many it left to
the served parts, so a room log shows the slots ran.

The card states a belief proposal keeps for its decision's root prior live on its bot's belief
wrapper. Each server turn snapshot starts with a separate empty cache while sharing immutable
model weights. States are matched to the decision by round object, seat and play count; a
decision that finds none runs the trunk itself with the same result.
"""
from __future__ import annotations

import os

from . import unified_slots as slots
from .pv_search_policy import ENV_PREFIX, PVSearchPolicyError

CKPT_KEY = ENV_PREFIX + "UNIFIED_CKPT"
SHA256_KEY = ENV_PREFIX + "UNIFIED_SHA256"
#: ``1`` serves the readout through its fast path (`unified_slots.leaf_features_fast`, the fused stem,
#: the per-decision row memo): the same model and search, float32 rounding apart, so it enters the name
FAST_KEY = ENV_PREFIX + "UNIFIED_FAST"
FAST_TOKEN = "ufast"
SINGLETON_KEY = ENV_PREFIX + "SINGLETON_CHALLENGER"
_WRAPPED = "unified_serving_wraps"
#: the decision record's account of the slots, per play decision: root priors read from the
#: belief proposal's forward and ones that ran the trunk themselves, the readout's own trunk
#: forwards, value rows it scored and non-terminal value positions of the decision it left to the
#: served evaluator, reply rows it ranked and reply clones it left to the served prior
RECORD_KEY = "unified"
RECORD_FIELDS = {"shared": "unified_shared_hits", "missed": "unified_shared_misses",
                 "trunk": "unified_trunk_forwards", "value_rows": "unified_value_rows",
                 "value_left": "unified_value_other", "reply_rows": "unified_reply_rows",
                 "reply_left": "unified_reply_served"}
#: with `FAST_KEY`: value and reply rows read from the decision's memo instead of a forward
FAST_RECORD_FIELDS = {"value_memo": "unified_value_memo", "reply_memo": "unified_reply_memo"}
_MODELS: dict = {}


def unified_env(environ=None) -> tuple[str, str] | None:
    """``(package path, sha256)`` from the environment, or None when neither key is set."""
    env = os.environ if environ is None else environ
    path, sha = env.get(CKPT_KEY), env.get(SHA256_KEY)
    if not path and not sha:
        return None
    if not path or not sha:
        raise PVSearchPolicyError(f"{CKPT_KEY} and {SHA256_KEY} go together")
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise PVSearchPolicyError(f"{SHA256_KEY} must be the package's full sha256")
    if not str(path).lower().endswith(".npz"):
        raise PVSearchPolicyError("the unified package must be a NumPy package (.npz)")
    return str(path), sha


def load_unified(path: str, sha256: str):
    """The unified readout package, sha-verified, loaded once per process and shared (read-only)
    by every bot that binds it."""
    from ..ai.unified_numpy import UnifiedNumpyError
    from ..ai.unified_readout_numpy import load_unified_readout_numpy
    key = (str(path), sha256)
    if key not in _MODELS:
        try:
            _MODELS[key] = load_unified_readout_numpy(path, sha256)
        except (OSError, KeyError, UnifiedNumpyError) as exc:
            raise PVSearchPolicyError(f"unified package {path}: {exc}") from exc
    return _MODELS[key]


def unified_fast(environ=None) -> bool:
    """`FAST_KEY` as a bool; anything but ``0``/``1``/unset refuses."""
    env = os.environ if environ is None else environ
    raw = env.get(FAST_KEY)
    if raw not in (None, "", "0", "1"):
        raise PVSearchPolicyError(f"{FAST_KEY} must be 0 or 1, not {raw!r}")
    return raw == "1"


def unified_name(served_name: str, sha256: str, fast: bool = False) -> str:
    sha8 = sha256[:8]
    return (f"{served_name}-{slots.SHARED_TOKEN}{sha8}-{slots.VALUE_TOKEN}{sha8}"
            f"-{slots.REPLY_TOKEN}{sha8}" + (f"-{FAST_TOKEN}" if fast else ""))


def activate() -> None:
    """Put the readout's two dispatchers in front of the served functions, once per process."""
    from . import pv_encode_prefix, pv_tree_search
    for module, attr, wrap in ((pv_tree_search, "greedy_reply_ply", slots.readout_reply_ply),
                               (pv_encode_prefix, "score_leaves", slots.readout_score_leaves)):
        served = getattr(module, attr)
        if getattr(served, _WRAPPED, None) is None:
            wrapped = wrap(served)
            setattr(wrapped, _WRAPPED, served)
            setattr(module, attr, wrapped)


def active() -> bool:
    from . import pv_encode_prefix, pv_tree_search
    return (getattr(pv_tree_search.greedy_reply_ply, _WRAPPED, None) is not None
            and getattr(pv_encode_prefix.score_leaves, _WRAPPED, None) is not None)


def _decide_play(self, rnd, seat):
    """The bot's own ``decide_play``; its decision record gains `RECORD_KEY` (`RECORD_FIELDS`)."""
    fields = {**RECORD_FIELDS, **FAST_RECORD_FIELDS} if self.unified_fast else RECORD_FIELDS
    before = [getattr(self, attr) for attr in fields.values()]
    cards = type(self).decide_play(self, rnd, seat)
    record = getattr(self, "last_decision_record", None)
    if isinstance(record, dict):
        record[RECORD_KEY] = {"package": self.unified_sha256[:8],
                              **{name: getattr(self, attr) - was
                                 for (name, attr), was in zip(fields.items(), before)}}
    return cards


def install(bot, model, fast: bool = False):
    """Fill ``bot``'s belief, root-prior, value and reply slots from ``model`` (``fast``: through the
    readout's fast path, `FAST_KEY`); returns ``bot``."""
    import types
    activate()
    try:
        slots.install_shared_forward(bot, model)
        slots.install_value_readout(bot, model, keep_prefix=True)
        slots.install_reply_readout(bot, model, keep_prefix=True)
    except slots.UnifiedSlotError as exc:
        raise PVSearchPolicyError(f"unified slots: {exc}") from exc
    bot.unified_sha256 = model.package_sha256
    bot.unified_fast = bool(fast)
    if fast:
        bot.policy_name = f"{bot.policy_name}-{FAST_TOKEN}"
    bot.decide_play = types.MethodType(_decide_play, bot)
    # A replacement deadline worker builds these assets and binds these methods
    # to its own instance. RNG, search counters and receipts cross the checkpoint.
    bot._screen_factory_fields = frozenset((
        "belief_model", "unified_prior_model", "unified_value_model", "unified_reply_model",
        "_belief_worlds", "scores", "_search", "decide_play",
    ))
    return bot


def unified_registry_entries(*, environ=None, **recipe) -> dict:
    """``{name: factory}`` for the environment's unified package over ``recipe`` (the keyword
    arguments `pv_env_recipe` returns), or ``{}`` when the environment names none.  The base entry
    is the one the registry serves for the same environment: the singleton challenger's when
    ``SHENGJI_PV_SINGLETON_CHALLENGER=1``, else the plain pv-search entry."""
    from .pv_search_policy import _load_belief, pv_registry_entries, singleton_registry_entries
    env = os.environ if environ is None else environ
    pinned = unified_env(env)
    if pinned is None:
        return {}
    path, sha256 = pinned
    if not recipe.get("belief_worlds") or not recipe.get("belief_checkpoint"):
        raise PVSearchPolicyError(f"{CKPT_KEY} needs the belief proposal on a belief package carrying "
                                  f"its trunk ({ENV_PREFIX}BELIEF_WORLDS=1, {ENV_PREFIX}BELIEF_CKPT)")
    if not recipe.get("leaf_greedy_finish"):
        raise PVSearchPolicyError(f"{CKPT_KEY} needs the greedy-finished leaf "
                                  f"({ENV_PREFIX}LEAF_GREEDY_FINISH=1): the reply slot is its shortlist")
    fast = unified_fast(env)
    raw = env.get(SINGLETON_KEY, "0")
    if raw not in ("", "0", "1"):
        raise PVSearchPolicyError(f"{SINGLETON_KEY} must be 0 or 1")
    base = (singleton_registry_entries if raw == "1" else pv_registry_entries)(**recipe)
    model = load_unified(path, sha256)
    try:
        slots.shared_trunk_belief(_load_belief(recipe["belief_checkpoint"], recipe["belief_sha256"]), model)
    except slots.UnifiedSlotError as exc:
        raise PVSearchPolicyError(f"unified slots: {exc}") from exc

    def named(make, served, name):
        def build(**kw):
            bot = make(**kw)
            if getattr(bot, "policy_name", None) != served:
                raise PVSearchPolicyError(f"the registry built {getattr(bot, 'policy_name', None)!r}, "
                                          f"expected {served!r}")
            install(bot, model, fast)
            if bot.policy_name != name:
                raise PVSearchPolicyError(f"built {bot.policy_name!r}, expected {name!r}")
            return bot
        return build
    return {unified_name(served, sha256, fast): named(make, served, unified_name(served, sha256, fast))
            for served, make in base.items()}
