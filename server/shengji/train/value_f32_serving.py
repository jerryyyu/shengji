"""The served pv-search bot with its complete-world networks forwarded in float32, OFF by default.

``SHENGJI_PV_VALUE_F32=1`` adds, beside every pv-search name the environment registers, a twin

    <name>-vf32

whose factory builds that name's bot and then gives it float32 views (`CWVNumpyMLP.as_float32`) of
the two complete-world packages it holds: the value package behind ``bot.evaluator`` (terminal
leaves, bury, declaration, and every value row the unified readout leaves to it) and the prior
package behind ``bot.predict`` (the root prior and the replies the readout leaves to it).  The
weights are the packages' own float32 arrays; only the forward's rounding changes, so the switch
enters the name.  The unified and belief packages already forward in float32 and are unchanged.

Unset (or ``0``), nothing is registered and no bot is touched: every name builds the bot it built.
The base names stay registered beside the twins; ``SHENGJI_BOT`` chooses.
"""
from __future__ import annotations

import os

from .pv_search_policy import ENV_PREFIX, PVSearchPolicyError

FLAG_KEY = ENV_PREFIX + "VALUE_F32"
TOKEN = "vf32"
SUFFIX = "-" + TOKEN


def value_f32(environ=None) -> bool:
    """`FLAG_KEY` as a bool; anything but ``0``/``1``/unset refuses."""
    env = os.environ if environ is None else environ
    raw = env.get(FLAG_KEY)
    if raw not in (None, "", "0", "1"):
        raise PVSearchPolicyError(f"{FLAG_KEY} must be 0 or 1, not {raw!r}")
    return raw == "1"


def _f32_view(model, where):
    from ..ai.cwv_numpy import CWVNumpyError, CWVNumpyMLP
    if not isinstance(model, CWVNumpyMLP):
        raise PVSearchPolicyError(f"{where} is a {type(model).__name__}, not a complete-world NumPy package")
    try:
        return model if model.compute_f32 else model.as_float32()
    except CWVNumpyError as exc:
        raise PVSearchPolicyError(f"{where}: {exc}") from exc


def install(bot):
    """Give ``bot`` float32 views of its value and prior packages and the `TOKEN` suffix; returns
    ``bot``.  The views are this bot's own attributes; the shared package objects are unchanged."""
    evaluator = getattr(bot, "evaluator", None)
    predict = getattr(bot, "predict", None)
    if evaluator is None or predict is None or not hasattr(predict, "_prior_net"):
        raise PVSearchPolicyError(f"{FLAG_KEY} needs a pv-search bot with a NumPy evaluator and prior")
    evaluator.model = _f32_view(evaluator.model, "the value package")
    predict._prior_net = _f32_view(predict._prior_net, "the prior package")
    bot.value_f32 = True
    bot.policy_name = f"{bot.policy_name}{SUFFIX}"
    return bot


def value_f32_registry_entries(entries: dict, environ=None) -> dict:
    """``{name + SUFFIX: factory}`` for each pv-search entry of ``entries`` when `FLAG_KEY` is on,
    else ``{}``."""
    if not value_f32(environ):
        return {}

    def twin(make, served):
        def build(**kw):
            bot = make(**kw)
            if getattr(bot, "policy_name", None) != served:
                raise PVSearchPolicyError(f"the registry built {getattr(bot, 'policy_name', None)!r}, "
                                          f"expected {served!r}")
            return install(bot)
        return build
    return {name + SUFFIX: twin(make, name) for name, make in entries.items()
            if name.startswith("pv-search-") and not name.endswith(SUFFIX)}
