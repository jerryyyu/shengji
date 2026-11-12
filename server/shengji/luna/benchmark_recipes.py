"""Explicit policy recipes for the Sol panel.

This module only binds recipes and factories.  Its own recipe selection does
not read environment configuration, register policies, or load a neural model
until a returned factory is called.  Importing existing registry modules may
retain their own initialization side effects.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import stat
from typing import Callable, Mapping


_SHAS = {
    "smv3": "491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670",
    "belief": "763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343",
    "soft": "ccade130f34ae61def540441ef997e8d41cef9df96f9683406bbba59ae4ccc75",
    "js_m1": "0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747",
    "m1": "12ce4415a65c479b03d52a08574e14a5909b09435c1d8dddeab1726fbc1d4d4f",
    "prior_v2": "b9ff76c9038630ae80bd396f4565574c549a55e385ffd729c2521905b76f0e6c",
    "w32": "fd6bb4114eb1f2ff049a77989cbd99eb35b949eef944dd72de448ff25b4fabd9",
}
_PV = {"worlds": 64, "candidates": 8, "cap": 4000, "batch_size": 128,
       "serving_budget_seconds": 3.0}
_SHORTLIST = {"alternatives": 4, "selection_worlds": 30,
              "report_worlds": 300, "batch_size": 128,
              "encoding": "mlp-static", "reuse_successors": True}
_IDS = {"smv3-pv", "soft-pv", "js-m1-shortlist", "m1-prior",
        "w32-original", "mc-lcb", "mc-strong", "mc", "smart", "release46-pv"}

# Frozen serving inputs keep recipe selection independent of process env; package
# paths are supplied only after _asset verifies their pinned bytes.
_RELEASE46_ENV = {
    "SHENGJI_PV_CKPT": "",
    "SHENGJI_PV_SHA256": _SHAS["smv3"],
    "SHENGJI_PV_WORLDS": "64",
    "SHENGJI_PV_CANDIDATES": "8",
    "SHENGJI_PV_CAP": "4000",
    "SHENGJI_PV_BATCH_SIZE": "128",
    "SHENGJI_PV_SERVING_BUDGET_SECONDS": "3",
    "SHENGJI_PV_ADMISSION_DIVERSITY": "1",
    "SHENGJI_PV_REFUSAL_CONSTRAINTS": "1",
    "SHENGJI_PV_TIEBREAK_POINTS": "1",
    "SHENGJI_PV_LEAD_ANCHOR": "1",
    "SHENGJI_PV_DOOMED_THROW_RESELECT": "1",
    "SHENGJI_PV_VALUE_DECLARE": "1",
    "SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST": "1",
    "SHENGJI_PV_WORLD_HISTORY_LEGAL": "1",
    "SHENGJI_PV_WORLD_HISTORY_DRAW": "1",
    "SHENGJI_PV_BELIEF_WORLDS": "1",
    "SHENGJI_PV_BELIEF_CKPT": "",
    "SHENGJI_PV_BELIEF_SHA256": _SHAS["belief"],
    "SHENGJI_PV_BELIEF_LOG": "1",
    "SHENGJI_PV_EXACT_LEAD_ENDGAME": "1",
    "SHENGJI_PV_EXACT_DEEP_CARDS": "7",
    "SHENGJI_PV_EXACT_FOLLOW": "1",
    "SHENGJI_PV_EXACT_FOLLOW_SOLVER": "compact-level",
    "SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS": "7",
    "SHENGJI_PV_EXACT_FOLLOW_MAX_NODES": "50000000",
    "SHENGJI_PV_BURY_ARM": "hybrid",
    "SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS": "2",
    "SHENGJI_PV_BURY_WIDE_VALUE": "1",
    "SHENGJI_PV_BURY_WIDE_K": "64",
}


@dataclass(frozen=True)
class PreparedRecipe:
    policy: str
    factory: Callable[..., object]
    identity: dict[str, object]


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset(paths: Mapping[str, str | Path], key: str) -> tuple[str, str]:
    try:
        candidate = Path(paths[key])
    except KeyError as exc:
        raise ValueError(f"missing model asset {key!r}") from exc
    if candidate.is_symlink() or not candidate.exists() or not candidate.is_file():
        raise ValueError(f"model asset {key!r} must be a regular nonsymlink file")
    if not stat.S_ISREG(candidate.stat().st_mode):
        raise ValueError(f"model asset {key!r} must be a regular file")
    actual = _hash(candidate)
    expected = _SHAS[key]
    if actual != expected:
        raise ValueError(f"model asset {key!r} has SHA256 {actual}, expected {expected}")
    return str(candidate.resolve()), expected


def _static(policy: str) -> PreparedRecipe:
    from ..ai.registry import REGISTRY
    factory = REGISTRY.get(policy)
    if factory is None:
        raise ValueError(f"static policy {policy!r} is not registered")

    def make(*, seed=0):
        # SmartBot is deterministic and has no seed constructor argument.
        # Do not catch TypeError: constructor failures must remain failures.
        return factory() if policy == "smart" else factory(seed=seed)

    search = ({"N_DETERMINIZATIONS": 30, "REPORT_FOLD_WORLDS": 300,
               "REPORT_RULE": "lcb", "REPORT_MIN_GAIN": 0.0}
              if policy == "mc-s0-report-lcb" else
              ({"N_DETERMINIZATIONS": 30} if policy == "mc-strong" else
               ({"N_DETERMINIZATIONS": 10} if policy == "mc" else {"kind": "smart"})))
    return PreparedRecipe(policy, make, {"schema": "sol-panel-recipe-v1",
                                         "benchmark_id": {"mc-s0-report-lcb": "mc-lcb"}.get(policy, policy),
                                         "policy": policy, "kind": "static",
                                         "play_only": True, "engine": "current",
                                         "search": search})


def _one_entry(entries):
    if len(entries) != 1:
        raise ValueError(f"recipe registration returned {len(entries)} entries; expected exactly one")
    return next(iter(entries.items()))


def prepare_recipe(policy: str, model_paths: Mapping[str, str | Path], *,
                   js_prior_threshold: int | None = None,
                   js_prior_top: int | None = None) -> PreparedRecipe:
    """Prepare one allowlisted play policy without consulting process env.

    JS-M1 is pinned to the accepted 1,000/256 recipe.  The optional keyword
    arguments are compatibility guards only: differing values are refused.
    """
    if policy not in _IDS:
        raise ValueError(f"unknown benchmark policy {policy!r}")
    if policy == "js-m1-shortlist":
        if ((js_prior_threshold is not None and
             (type(js_prior_threshold) is not int or js_prior_threshold != 1000)) or
                (js_prior_top is not None and
                 (type(js_prior_top) is not int or js_prior_top != 256))):
            raise ValueError("JS-M1 is pinned to prior threshold 1000 and top 256")
    if policy in {"mc-lcb", "mc-strong", "mc", "smart"}:
        return _static({"mc-lcb": "mc-s0-report-lcb", "mc-strong": "mc-strong",
                        "mc": "mc", "smart": "smart"}[policy])

    if policy == "release46-pv":
        path, sha = _asset(model_paths, "smv3")
        belief, belief_sha = _asset(model_paths, "belief")
        from ..train.pv_search_policy import pv_env_recipe, pv_registry_entries

        frozen_env = dict(_RELEASE46_ENV)
        frozen_env.update(SHENGJI_PV_CKPT=path,
                          SHENGJI_PV_SHA256=sha,
                          SHENGJI_PV_BELIEF_CKPT=belief,
                          SHENGJI_PV_BELIEF_SHA256=belief_sha)
        recipe = pv_env_recipe(frozen_env)
        entries = pv_registry_entries(**recipe)
        name, factory = _one_entry(entries)
        identity = {"schema": "sol-panel-recipe-v1", "benchmark_id": policy,
                    "policy": policy, "kind": "pv", "play_only": True,
                    "engine": "current", **recipe}
        if "bury_config" in identity:
            identity["bury_config"] = asdict(identity["bury_config"])
        return PreparedRecipe(name, factory, identity)

    if policy in {"smv3-pv", "soft-pv"}:
        key = "smv3" if policy == "smv3-pv" else "soft"
        path, sha = _asset(model_paths, key)
        from ..train.pv_search_policy import pv_registry_entries
        entries = pv_registry_entries(path, sha256=sha, **_PV)
        name, factory = _one_entry(entries)
        identity = {"schema": "sol-panel-recipe-v1", "benchmark_id": policy,
                    "policy": policy,
                    "kind": "pv", "checkpoint": path, "sha256": sha,
                    "play_only": True, "engine": "current", **_PV}
        return PreparedRecipe(name, factory, identity)

    if policy == "js-m1-shortlist":
        js_prior_threshold, js_prior_top = 1000, 256
        value, value_sha = _asset(model_paths, "js_m1")
        prior, prior_sha = value, value_sha
        prior_kind = "joint-numpy"
    elif policy == "m1-prior":
        value, value_sha = _asset(model_paths, "m1")
        prior, prior_sha = _asset(model_paths, "prior_v2")
        js_prior_threshold, js_prior_top = 1000, 256
        prior_kind = "separate"
    else:
        value, value_sha = _asset(model_paths, "w32")
        prior = prior_sha = None
        prior_kind = "none"
        js_prior_threshold = js_prior_top = None
    from ..train.cwv_shortlist import shortlist_registry_entries
    recipe = dict(_SHORTLIST)
    if prior is not None:
        recipe.update(prior_sha256=prior_sha, prior_threshold=js_prior_threshold,
                      prior_top=js_prior_top)
    entries = shortlist_registry_entries(value, worlds=(32,),
                                         prior_checkpoint=prior, **recipe)
    name, factory = _one_entry(entries)
    identity = {"schema": "sol-panel-recipe-v1", "benchmark_id": policy,
                "policy": policy,
                "kind": "shortlist", "checkpoint": value,
                "sha256": value_sha, "worlds": 32, "play_only": True,
                "engine": "current", **recipe,
                "prior_kind": prior_kind}
    if prior is not None:
        identity.update(prior_checkpoint=prior, prior_sha256=prior_sha)
    return PreparedRecipe(name, factory, identity)


__all__ = ["PreparedRecipe", "prepare_recipe"]
