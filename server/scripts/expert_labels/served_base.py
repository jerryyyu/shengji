"""The served state generator of the expert-label producer and the variants derived from it.

The producer and its duel harness take the served bot from ``fly.toml`` (``SHENGJI_BOT`` and the
``SHENGJI_*`` environment) and derive variants from it by ``SHENGJI_PV_*`` overrides.  This module
holds the parts of that derivation that carry an invariant, free of import-time side effects so
they can be tested against any base environment:

* A served name is ``<play name>-bury-<bury tokens>-<12-hex digest>`` optionally followed by one
  registered wrapper token (``WRAPPERS``).  Any other tail is refused: an unparsed name is never
  matched by a heuristic.
* A variant is built from the base environment with the overrides applied, through the registry
  path the server uses (``pv_env_recipe`` -> ``pv_registry_entries``, or
  ``singleton_registry_entries`` when the variant's own environment turns the singleton challenger
  on).  Before any variant is derived, the base environment must register the base name itself,
  so a ``SHENGJI_BOT`` that is not the bot its environment builds is refused.
* The expert is the base search deepened by ``EXPERT_ENV``.  The base's served lead rules that the
  expert does not run (``EXPERT_DROPS``) are removed explicitly, so on every supported base the
  expert is the same bot and its derived name is the same name.
"""
from __future__ import annotations

import re

#: the expert's overrides on the served base: all 256 worlds, K 32, the exact stages at 8 cards
#: with 2e8 nodes and a 9 s exact-lead cap, and no greedy-finish deadline (its wall cap is the
#: producer's per-decision cap).  The belief stays the base's, so the shared draw is the served draw.
EXPERT_ENV = (("SHENGJI_PV_CANDIDATES", "32"), ("SHENGJI_PV_EXACT_DEEP_CARDS", "8"), ("SHENGJI_PV_EXACT_DEEP_MAX_NODES", "200000000"),
              ("SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS", "8"), ("SHENGJI_PV_EXACT_FOLLOW_MAX_NODES", "200000000"),
              ("SHENGJI_PV_EXACT_LEAD_MAX_SECONDS", "9.0"), ("SHENGJI_PV_LEAF_GREEDY_DEADLINE", ""), ("SHENGJI_PV_WORLDS", "256"))

#: served lead rules the expert never runs, removed whenever the base sets them:
#: the lead confirmation (lcc<k>) screens a policy pool beyond an 8-slot ballot and the registry
#: refuses it unless k exceeds the candidates, so it cannot exist at the expert's K 32; the
#: singleton challenger (sc8) replaces the last slot of an 8-slot ballot and is a served-width rule.
EXPERT_DROPS = ("SHENGJI_PV_LEAD_CONFIRM", "SHENGJI_PV_SINGLETON_CHALLENGER")

SINGLETON_ENV = "SHENGJI_PV_SINGLETON_CHALLENGER"
#: registered wrapper tokens that follow the bury digest, and the environment flag that registers each
WRAPPERS = {"sc8": SINGLETON_ENV}
_DIGEST = re.compile(r"[0-9a-f]{12}")


class ServedNameError(ValueError):
    """A served name outside the registered grammar, or a base its environment does not build."""


def parse_served_name(name: str) -> tuple[tuple[str, ...], str, str | None]:
    """``(bury tokens, bury digest, wrapper or None)`` of a served name; refuses any other shape."""
    parts = name.split("-bury-")
    if len(parts) != 2 or not parts[0]:
        raise ServedNameError(f"{name!r}: not a <play>-bury-<arm>-<digest> name")
    toks = parts[1].split("-")
    wrapper = None
    if toks and toks[-1] in WRAPPERS:
        wrapper = toks.pop()
    if len(toks) < 2 or not _DIGEST.fullmatch(toks[-1]):
        raise ServedNameError(f"{name!r}: the bury part does not end in a 12-hex digest"
                              f" (optionally followed by one of {sorted(WRAPPERS)})")
    if any(_DIGEST.fullmatch(t) for t in toks[:-1]):
        raise ServedNameError(f"{name!r}: more than one digest in the bury part")
    return tuple(toks[:-1]), toks[-1], wrapper


def apply_overrides(env: dict, overrides) -> dict:
    """``env`` with ``SHENGJI_PV_*`` overrides applied; an empty value removes the key."""
    out = dict(env)
    for k, v in overrides:
        if v == "":
            out.pop(k, None)
        else:
            out[k] = v
    return out


def _wrapper_on(env: dict) -> str | None:
    on = [w for w, flag in WRAPPERS.items() if env.get(flag, "0") == "1"]
    bad = [flag for flag in WRAPPERS.values() if env.get(flag, "0") not in ("", "0", "1")]
    if bad:
        raise ServedNameError(f"{bad} must be 0 or 1")
    return on[0] if on else None


def registry_entries(env: dict) -> dict:
    """The registry entries ``env`` builds, as the server registers them: the plain search and,
    with the singleton challenger on, its ``-sc8`` wrapper instead."""
    from shengji.train.pv_search_policy import pv_env_recipe, pv_registry_entries, singleton_registry_entries
    recipe = pv_env_recipe(env)
    if _wrapper_on(env) == "sc8":
        return singleton_registry_entries(**recipe)
    return pv_registry_entries(recipe.pop("checkpoint"), **recipe)


def check_base(base_name: str, env: dict) -> None:
    """Refuse a base name its own environment does not register."""
    parse_served_name(base_name)
    names = list(registry_entries(env))
    if base_name not in names:
        raise ServedNameError(f"base {base_name!r} is not the bot its environment builds ({names})")


def match_variant(base_name: str, env: dict, entries) -> str:
    """The one entry of a variant's registry ``entries`` that is the base's bury arm with the wrapper
    the variant's own environment registers.  Refuses zero or several matches."""
    tokens, _, _ = parse_served_name(base_name)
    want = _wrapper_on(env)
    names = []
    for n in entries:
        try:
            t, _, w = parse_served_name(n)
        except ServedNameError:
            continue
        if t == tokens and w == want:
            names.append(n)
    if len(names) != 1:
        raise ServedNameError(f"no single variant of {base_name!r} among {list(entries)}: {names}")
    return names[0]


def derive_variant(base_name: str, env: dict, overrides) -> tuple[str, object]:
    """``(name, factory)`` of the base with ``overrides``: the base is checked against ``env``, then the
    variant is registered from ``env`` with the overrides applied and matched to the base's bury arm."""
    check_base(base_name, env)
    venv = apply_overrides(env, overrides)
    entries = registry_entries(venv)
    name = match_variant(base_name, venv, entries)
    return name, entries[name]


def expert_env(base_env: dict) -> tuple:
    """The expert's overrides on ``base_env``: ``EXPERT_ENV`` plus the removal of every ``EXPERT_DROPS``
    rule the base sets (sorted by key, the producer's binding form)."""
    out = dict(EXPERT_ENV)
    for k in EXPERT_DROPS:
        if base_env.get(k) not in (None, "", "0"):
            out[k] = ""
    return tuple(sorted(out.items()))


def served_class(name: str):
    """The bot class a served name builds: the singleton challenger's for an ``-sc8`` name, else the search's."""
    from shengji.train.pv_search_policy import PVSearchBuryBot
    _, _, wrapper = parse_served_name(name)
    if wrapper == "sc8":
        from shengji.eval.singleton_challenger import SingletonChallengerBuryBot
        return SingletonChallengerBuryBot
    return PVSearchBuryBot
