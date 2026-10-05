"""Explicit policy recipes for the Sol panel.

This module only binds recipes and factories.  Its own recipe selection does
not read environment configuration, register policies, or load a neural model
until a returned factory is called.  Importing existing registry modules may
retain their own initialization side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import stat
from typing import Callable, Mapping


_SHAS = {
    "smv3": "491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670",
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
        "w32-original", "mc-lcb", "mc-strong", "mc", "smart"}


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
