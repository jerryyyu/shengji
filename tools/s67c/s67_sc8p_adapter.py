#!/usr/bin/env python3
"""s67c adapter: the reviewed S61 duel harness (exploit_duel_s61.py, b15d292f, beside this file, NOT modified) with the exploiter side
built as the pair / tractor challenger (server/shengji/eval/pair_challenger.py at 8a50fe8a, branch claude/s67-pair-challenger: the singleton
challenger's fixed-width lead probe with the omitted pool widened to every one-component pair or tractor; throws stay out; research
identity '-sc8p').  = s66_sc8_adapter.py (80e0e7f8, the s66dev / s66b adapter) with the candidate, the sentinel value, the suffix, the row key
and the probe entry changed; the harness replacement mechanism is the same.

The harness builds every bot from fly.toml's SHENGJI_* env through the production registry (its variant_factory: make_bot(SHENGJI_BOT) for
no override, pv_registry_entries for SHENGJI_PV_* overrides).  No env flag constructs the challenger: pair_candidate_from_env(environ, seed)
is a function, not a registry entry.  So this adapter imports the harness as a module and REPLACES two of its module-level functions before
main() runs; every other harness function (play_mirror, run, the resume binding, the summaries, the row form) runs unchanged, and the
child processes (spawn) re-import this file as __mp_main__, so the replacements hold in every worker.

  1. variant_factory(overrides): when the overrides carry the sentinel S66_EXPLOITER=sc8p, the (name, factory) pair is the candidate:
       - the environment is the process env (fly.toml's SHENGJI_* keys, placed there by the harness's served_env, with the package paths
         mapped) plus the OTHER overrides, applied exactly as the harness applies them (an empty value removes the key);
       - with other overrides present (a time-scaled bench only), the baseline name is re-derived as the harness's variant_factory does
         (pv_env_recipe -> pv_registry_entries, the one entry with the served recipe's bury tail) and written to SHENGJI_BOT of that
         environment, since the candidate loader refuses a SHENGJI_BOT that is not the recipe's own name; the lane passes the sentinel ALONE,
         so there the environment's SHENGJI_BOT is fly.toml's and the name is fly.toml's SHENGJI_BOT + '-sc8p';
       - the factory is pair_candidate_from_env(env, seed=seed): the production package loader, the bury consumer (PairChallengerBuryBot for
         a bury_arm recipe), the latency switches and the belief log flag bound from that environment, policy_name = name + '-sc8p';
       - each built bot's decide_play is wrapped so the per-decision probe fields of its decision record are collected (below).
     Any other overrides (none, or SHENGJI_PV_* only) go to the harness's own variant_factory unchanged: the defender is built exactly
     as in s63dev / s64dev / s65dev / s66dev / s66b.
  2. play_mirror(...): the harness's play_mirror, then the collected probe fields are attached to the row under the key 'sc8p':
       {'ex': [[lead, applied, evaluations, probe_worlds, margin, chosen, added_kind, pool, played_kind] per exploiter decide_play, in
        the round's order]}
     lead: the decision led the trick (leading(rnd) before the call); applied: singleton_challenger_applied from the decision record (None
     on a fallback record, which carries no admission fields); evaluations / probe_worlds / margin: singleton_probe_evaluations /
     singleton_probe_worlds / singleton_probe_margin when the probe ran (a lead with more than 7 cards in the largest hand, at least two
     admitted slots and a non-empty omitted pool), else None; chosen: applied and the played cards equal the admitted candidate
     (singleton_challenger_added), else False (None when applied is None); added_kind: challenger_added_kind ('single' / 'pair' /
     'tractor') when applied, else None; pool: challenger_pool as [singles, pairs, tractors] when the admission classified the omitted pool
     (a lead at max hand > 7 with at least two admitted slots; the probe runs only when the sum is positive), else None; played_kind: the
     kind of the played lead by the candidate's own classifier (pair_challenger.lead_kind on the round's ordering: 'single' / 'pair' /
     'tractor' / 'throw'), None on a follow.  The harness's dhist / dsecs for the side are untouched; the reader reconciles the two lists
     by position.
  3. _source_binding(...): the harness's binding plus this adapter's sha256, the candidate module's (pair_challenger.py of the tree on
     sys.path) and its base class module's (singleton_challenger.py), so a resumed run refuses a changed adapter or candidate as it refuses
     a changed producer.

Everything else is the harness: usage, arguments, the resume binding, the output rows.  Run it exactly as the harness is run, with this file
in place of exploit_duel_s61.py:
  SHENGJI_FAST=1 FIND_GAPS_SERVER=<tree>/server FIND_GAPS_PKG=<smv3out> FIND_GAPS_PATH_MAP=... python -B s67_sc8p_adapter.py --arm identity \
      --seed0 S --deals N --workers W --round-plan r2 --exploiter-env S66_EXPLOITER=sc8p --out OUT.jsonl
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
SENTINEL = ("S66_EXPLOITER", "sc8p")
SUFFIX = "-sc8p"
KINDS = ("single", "pair", "tractor")

sys.path.insert(0, str(HERE.parent))
_spec = importlib.util.spec_from_file_location("exploit_duel_s61", HERE.with_name("exploit_duel_s61.py"))
D = importlib.util.module_from_spec(_spec)
sys.modules["exploit_duel_s61"] = D
_spec.loader.exec_module(D)          # sets fly.toml's env (served_env), puts the tree's server on sys.path, imports the engine

from shengji.eval import pair_challenger as PC  # noqa: E402  (the tree's module, on the harness's sys.path)
from shengji.eval import singleton_challenger as SC  # noqa: E402  (its base: the probe, the loader, the env binding)
from shengji.train.policy_value_search import leading  # noqa: E402

CANDIDATE_PATH = Path(PC.__file__).resolve()
BASE_PATH = Path(SC.__file__).resolve()
_PROBES: list = []                   # per worker process: the exploiter side's probe fields of the mirror being played
_orig_variant_factory = D.variant_factory
_orig_play_mirror = D.play_mirror
_orig_source_binding = D._source_binding
_CANDIDATES: dict = {}


def _sorted_cards(cards):
    return sorted(cards) if isinstance(cards, (list, tuple)) else None


def _pool(rec):
    pool = rec.get("challenger_pool")
    if not isinstance(pool, dict):
        return None
    return [int(pool.get(k, 0)) for k in KINDS]


def _probe_fields(rec, lead, played, played_kind):
    """[lead, applied, evaluations, probe_worlds, margin, chosen, added_kind, pool, played_kind] from one decision record."""
    if not isinstance(rec, dict) or "singleton_challenger_applied" not in rec:
        return [bool(lead), None, None, None, None, None, None, None, played_kind]
    applied = rec.get("singleton_challenger_applied")
    chosen = bool(applied) and _sorted_cards(rec.get("singleton_challenger_added")) == _sorted_cards(played)
    return [bool(lead), applied, rec.get("singleton_probe_evaluations"), rec.get("singleton_probe_worlds"),
            rec.get("singleton_probe_margin"), chosen, rec.get("challenger_added_kind"), _pool(rec), played_kind]


def _wrap_decide_play(bot):
    orig = bot.decide_play

    def decide_play(rnd, seat):
        lead = leading(rnd)
        cards = orig(rnd, seat)
        played_kind = PC.lead_kind(list(cards), rnd.ordering) if lead else None
        _PROBES.append(_probe_fields(getattr(bot, "last_decision_record", None), lead, cards, played_kind))
        return cards
    bot.decide_play = decide_play
    return bot


def _baseline_name(env):
    """The harness's own derivation (variant_factory) of the recipe's registry name for an overridden environment."""
    from shengji.train.pv_search_policy import pv_env_recipe, pv_registry_entries
    recipe = pv_env_recipe(env)
    entries = pv_registry_entries(recipe.pop("checkpoint"), **recipe)
    tail = D.R45.split("-bury-")[1].split("-")[:-1]
    names = [n for n in entries if n.split("-bury-")[-1].split("-")[:-1] == tail]
    if len(names) != 1:
        raise SystemExit(f"s67 adapter: ambiguous baseline names {names}")
    return names[0]


def variant_factory(overrides: tuple):
    if SENTINEL not in tuple(overrides):
        return _orig_variant_factory(overrides)
    key = tuple(overrides)
    if key not in _CANDIDATES:
        rest = tuple(o for o in key if o != SENTINEL)
        env = dict(os.environ)
        for k, v in rest:
            if v == "":
                env.pop(k, None)
            else:
                env[k] = v
        if rest:
            env["SHENGJI_BOT"] = _baseline_name(env)
        name = env["SHENGJI_BOT"] + SUFFIX

        def make(seed, _env=env, _name=name):
            bot = PC.pair_candidate_from_env(_env, seed=seed)
            if bot.policy_name != _name:
                raise SystemExit(f"s67 adapter: pair_candidate_from_env named {bot.policy_name!r}, expected {_name!r}")
            return _wrap_decide_play(bot)
        _CANDIDATES[key] = (name, make)
    return _CANDIDATES[key]


def play_mirror(arm, deal_seed, mirror, keep_history, defender_env=(), exploiter_env=(), plan_entry=("first", "2", None)):
    _PROBES.clear()
    rec = _orig_play_mirror(arm, deal_seed, mirror, keep_history, defender_env, exploiter_env, plan_entry)
    rec["sc8p"] = {"ex": [list(p) for p in _PROBES]}
    _PROBES.clear()
    return rec


def _source_binding(denv=(), eenv=()):
    source = _orig_source_binding(denv, eenv)
    source[HERE.name] = D._sha256(HERE)
    source["pair_challenger.py"] = D._sha256(CANDIDATE_PATH)
    source["singleton_challenger.py"] = D._sha256(BASE_PATH)
    return source


D.variant_factory = variant_factory
D.play_mirror = play_mirror
D._source_binding = _source_binding

if __name__ == "__main__":
    D.main()
