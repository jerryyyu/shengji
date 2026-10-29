"""The served bot's configuration, read from ``fly.toml``, for every harness that claims it.

A harness that says it measures, teaches from or replays "the served bot" gets the environment
here: the repo's ``fly.toml`` ``[env]`` verbatim (the recipe, the latency switches, the budgets),
with volume paths mapped to local copies and only NAMED overrides on top
(`NAMED_OVERRIDES`).  A harness never writes its own copy of the recipe: a hand-set copy keeps
the recipe of the day it was written while ``fly.toml`` moves on, so a "served" read silently
describes an older bot.  ``tests/test_served_config.py`` fails when a harness's served
environment differs from ``fly.toml`` by anything but a named override.

    python -m shengji.eval.served_config env [--fly-toml PATH] [--map VOLUME=LOCAL ...]
        [--override NAME ...] [--expect-name NAME]
        # prints ``export KEY='VALUE'`` for the whole environment, then SERVED_NAME=...; with
        # --expect-name it refuses (exit 3) unless the derived registry name is exactly NAME
    python -m shengji.eval.served_config check ...same arguments...
        # also builds the bot as the server does and checks its name, budgets and switches

The registry name is derived as the server derives it (`pv_env_recipe` ->
`pv_registry_entries`), so it reads the mapped packages (their hashes enter the name).
"""
from __future__ import annotations

import argparse
import contextlib
import os
import sys
import tomllib
from pathlib import Path
from typing import Iterable, Mapping

FLY_TOML = Path(__file__).resolve().parents[3] / "fly.toml"

#: The only changes a harness may make to the served environment, by name.  A value of ""
#: removes the key.  Each entry says what it is for; a new candidate knob gets an entry here
#: (and nowhere else) before a harness may use it.
NAMED_OVERRIDES: dict[str, dict[str, str]] = {
    # A data teacher searches to completion: no play or bury budget and no greedy-finish
    # deadline, so a slow host never teaches the budget fallback or a wall-clock-dependent leaf.
    "teacher-unbudgeted": {"SHENGJI_PV_SERVING_BUDGET_SECONDS": "",
                           "SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS": "",
                           "SHENGJI_PV_LEAF_GREEDY_DEADLINE": ""},
    # candidate search knobs (off in fly.toml)
    "wla24": {"SHENGJI_PV_WIDE_LEAD_ADMISSION": "1", "SHENGJI_PV_WIDE_LEAD_K": "24"},
    "lcc32": {"SHENGJI_PV_LEAD_CONFIRM": "32"},
    "lgft3": {"SHENGJI_PV_LEAF_GREEDY_TOP": "3"},
}

#: Keys that name where the server writes; a harness replaces them (they enter no bot).
WRITE_KEYS = ("SHENGJI_LOG_DIR", "SHENGJI_DATA_DIR")


class ServedConfigError(ValueError):
    pass


def fly_env(path: str | os.PathLike | None = None) -> dict[str, str]:
    """``fly.toml``'s ``[env]`` as written, every value a string."""
    config = tomllib.loads(Path(path or FLY_TOML).read_text())
    return {str(k): str(v) for k, v in config["env"].items()}


def apply_overrides(env: Mapping[str, str], names: Iterable[str]) -> dict[str, str]:
    """``env`` with the named overrides applied in order; an unknown name refuses."""
    out = dict(env)
    for name in names:
        if name not in NAMED_OVERRIDES:
            raise ServedConfigError(f"unknown override {name!r}; the named overrides are "
                                    f"{sorted(NAMED_OVERRIDES)}")
        for key, value in NAMED_OVERRIDES[name].items():
            if value == "":
                out.pop(key, None)
            else:
                out[key] = value
    return out


def override_keys(names: Iterable[str]) -> set[str]:
    keys: set[str] = set()
    for name in names:
        if name not in NAMED_OVERRIDES:
            raise ServedConfigError(f"unknown override {name!r}")
        keys |= set(NAMED_OVERRIDES[name])
    return keys


def served_env(*, fly_toml: str | os.PathLike | None = None,
               mappings: Mapping[str, str] | None = None,
               overrides: Iterable[str] = (), derive_name: bool = True) -> dict[str, str]:
    """The served environment: ``fly.toml`` with every value equal to a ``mappings`` key
    replaced by its local path, then the named ``overrides``.  With overrides and
    ``derive_name``, ``SHENGJI_BOT`` is re-derived from the overridden recipe (the name
    the server would register), which reads the mapped packages."""
    mappings = dict(mappings or {})
    env = {k: mappings.get(v, v) for k, v in fly_env(fly_toml).items()}
    overrides = tuple(overrides)
    env = apply_overrides(env, overrides)
    if overrides and derive_name:
        env["SHENGJI_BOT"] = registry_name(env)
    return env


def env_diff(env: Mapping[str, str], base: Mapping[str, str]) -> list[str]:
    """The keys whose values differ between ``env`` and ``base`` (absent counts)."""
    return sorted(k for k in set(env) | set(base) if env.get(k) != base.get(k))


def unexplained_diff(env: Mapping[str, str], *, overrides: Iterable[str] = (),
                     mappings: Mapping[str, str] | None = None,
                     fly_toml: str | os.PathLike | None = None) -> list[str]:
    """Keys where ``env`` differs from ``fly.toml`` other than by the named overrides, the
    mapped paths, the re-derived ``SHENGJI_BOT`` (with overrides) and the write paths."""
    overrides = tuple(overrides)
    base = served_env(fly_toml=fly_toml, mappings=mappings, overrides=overrides, derive_name=False)
    allowed = set(WRITE_KEYS) | ({"SHENGJI_BOT"} if overrides else set())
    return [k for k in env_diff(env, base) if k not in allowed]


def registry_name(env: Mapping[str, str]) -> str:
    """The pv-search registry name the server registers for ``env`` (one recipe)."""
    from ..train.pv_search_policy import pv_env_recipe, pv_registry_entries
    recipe = pv_env_recipe(dict(env))
    names = list(pv_registry_entries(recipe.pop("checkpoint"), **recipe))
    if len(names) != 1:
        raise ServedConfigError(f"the env registers {len(names)} pv-search names, not one: {names}")
    return names[0]


@contextlib.contextmanager
def process_env(env: Mapping[str, str]):
    """``env`` exported into ``os.environ`` for the duration, then restored.

    The server process boots with fly.toml's ``[env]`` in its environment, and some switches
    are read where the bot is built rather than from the recipe (the pv-search latency
    switches and the belief log flag enter no name).  Build-time keys the env leaves out are
    cleared, so an ambient shell value cannot build a different bot under the same name."""
    from ..train.pv_search_policy import BELIEF_LOG_ENV, LATENCY_SWITCH_ENV
    scoped = set(env) | set(LATENCY_SWITCH_ENV.values()) | {BELIEF_LOG_ENV}
    saved = {key: os.environ.get(key) for key in scoped}
    for key in scoped - set(env):
        os.environ.pop(key, None)
    os.environ.update({key: str(value) for key, value in env.items()})
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def build_served_bot(env: Mapping[str, str], *, seed: int = 13, expected_name: str | None = None):
    """``(name, bot)``: register exactly what the server registers from ``env`` and build
    ``SHENGJI_BOT``, with ``env`` in the process environment while the bot is built.
    ``expected_name``: refuse unless ``SHENGJI_BOT`` is exactly that name."""
    env = dict(env)
    name = env.get("SHENGJI_BOT", "")
    if expected_name is not None and name != expected_name:
        raise ServedConfigError(f"SHENGJI_BOT {name!r} is not the expected {expected_name!r}")
    with process_env(env):
        from ..ai import registry
        from ..train.cwv_bury_policy import bury_env_recipe
        from ..train.cwv_shortlist import shortlist_env_recipe
        registered = set()
        parsed = bury_env_recipe(env)
        if parsed is not None:
            checkpoint, worlds, recipe, arm, config, budget = parsed
            registered.update(registry.register_cwv_bury_policies(
                checkpoint, worlds, arm=arm, bury_config=config,
                serving_budget_seconds=budget, **recipe))
        play = shortlist_env_recipe(env)
        if play is not None:
            registered.update(registry.register_cwv_shortlist_policies(play[0], play[1], **play[2]))
        if env.get("SHENGJI_PV_CKPT"):
            from ..train.pv_search_policy import pv_env_recipe
            recipe = pv_env_recipe(env)
            registered.update(registry.register_pv_search_policies(recipe.pop("checkpoint"), **recipe))
        if name not in registered:
            raise ServedConfigError(f"SHENGJI_BOT {name!r} is not registered by this env: "
                                    "the server would not boot with it")
        return name, registry.make_bot(name, seed=seed)


def _shell_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def _parse(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=("env", "check"))
    p.add_argument("--fly-toml", default=str(FLY_TOML))
    p.add_argument("--map", action="append", default=[], metavar="VOLUME=LOCAL")
    p.add_argument("--override", action="append", default=[], choices=sorted(NAMED_OVERRIDES))
    p.add_argument("--expect-name")
    p.add_argument("--seed", type=int, default=0)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse(argv)
    mappings = dict(item.split("=", 1) for item in args.map)
    try:
        env = served_env(fly_toml=args.fly_toml, mappings=mappings, overrides=args.override)
        name = registry_name(env)
        if name != env["SHENGJI_BOT"]:
            raise ServedConfigError(f"fly.toml's SHENGJI_BOT {env['SHENGJI_BOT']!r} is not the "
                                    f"name its recipe registers ({name!r})")
        if args.expect_name is not None and name != args.expect_name:
            raise ServedConfigError(f"the served name is {name!r}, not the expected {args.expect_name!r}")
        if args.command == "check":
            built, bot = build_served_bot(env, seed=args.seed, expected_name=args.expect_name)
            budgets = (getattr(bot, "serving_budget_seconds", None),
                       getattr(bot, "bury_serving_budget_seconds", None))
            if "teacher-unbudgeted" in args.override and budgets != (None, None):
                raise ServedConfigError(f"a teacher must be unbudgeted; the bot has {budgets}")
            from ..train.pv_search_policy import LATENCY_SWITCH_ENV, latency_switches
            want = latency_switches(env)
            have = {attr: bool(getattr(bot, attr, False)) for attr in LATENCY_SWITCH_ENV}
            if have != want:
                raise ServedConfigError(f"the built bot's latency switches {have} are not the env's {want}")
            print(f"# built {built} -> {type(bot).__name__}; budgets {budgets}", file=sys.stderr)
    except (ServedConfigError, OSError, ValueError) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    if args.command == "env":
        # Clear optional recipe keys in the consuming shell before applying the snapshot.
        print("for _shengji_key in $(env | sed -n "
              "'s/^\\(SHENGJI_PV_[A-Za-z0-9_]*\\)=.*/\\1/p'); do")
        print('    unset "$_shengji_key"')
        print("done")
        print("unset _shengji_key")
        # the write paths name the server's volume; the caller sets its own
        for key in sorted(k for k in env if k not in WRITE_KEYS):
            print(f"export {key}={_shell_quote(env[key])}")
    print(f"SERVED_NAME={_shell_quote(name)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
