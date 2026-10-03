"""The recipe of the OPTIONAL paired lookahead tree on the pv-search bot
("PUCT v2", #436); the search itself is `pv_tree_search`.

This module is dependency-free on purpose: `pv_search_policy` imports it for
the recipe field, the name token and the env parsing, while `pv_tree_search`
(which subclasses the served bot) is imported lazily, only when a recipe turns
the tree on.

OFF BY DEFAULT.  ``SHENGJI_PV_TREE_SIMS`` unset (or empty) leaves
``PVSearchConfig.tree`` at ``None``; `recipe_payload` then omits the key, so
every existing recipe digest and registry name is byte-identical, and the
served classes are exactly `PVSearchBot` / `PVSearchBuryBot`.

Env (all under ``SHENGJI_PV_``):

* ``TREE_SIMS=<S>`` -- an integer in [0, 4096]: the lookahead evaluations a
  decision may spend (``0`` = the mechanics only: the decision is the mode-off
  bot's, with the tree telemetry attached);
* ``TREE_EPS`` -- the contender window, in the value head's units (signed
  levels); default 0.05;
* ``TREE_ZMIN`` -- the significance gate on overriding the PV decision
  (default 1.0; ``0`` = plain argmax of the depth-corrected estimate);
* ``TREE_BUDGET_FRACTION`` -- the tree starts only while the decision has used
  at most this fraction of the play serving budget (default 0.5);
* ``TREE_CONT`` -- the continuation a lookahead plays before the value head is
  read (`pv_tree_search`): ``trick`` (default: the policy finishes the current
  trick only), ``trick-next-heuristic`` (then the heuristic leads the next
  trick and the policy follows it), ``policy`` (then the policy leads the
  next trick with its best single-component lead and follows it) or
  ``trick-greedy`` (the current trick only, each reply chosen by one-step value
  greed among the policy's top ``TREE_REPLIES`` follows plus the heuristic's);
* ``TREE_REPLIES`` -- the R of ``trick-greedy`` (an integer in [1, 16], default 4).

The optional knobs are refused unless ``TREE_SIMS`` is set.  Every field of
`PVTreeConfig` enters the recipe digest; the name carries ``-ts<S>`` (plus
``-tcnh`` / ``-tcp`` / ``-tcg`` for a non-default continuation, ``-tr<R>``
for a non-default R, and ``-te<eps>`` / ``-tz<zmin>`` when those differ from
their defaults) after the rule tokens.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

TREE_DEFAULTS = dict(eps=0.05, zmin=1.0, max_contenders=4, cont="trick", reply_candidates=4,
                     budget_fraction=0.5, budget_stop_fraction=0.8)
#: continuation mode -> its name token ("" for the default)
CONT_TOKENS = {"trick": "", "trick-next-heuristic": "-tcnh", "policy": "-tcp",
               "trick-greedy": "-tcg"}
ENV_CONT = "TREE_CONT"
ENV_REPLIES = "TREE_REPLIES"
MAX_SIMS = 4096
ENV_SIMS = "TREE_SIMS"
#: env suffix -> `PVTreeConfig` field, for the optional float knobs
ENV_FLOATS = {"TREE_EPS": "eps", "TREE_ZMIN": "zmin",
              "TREE_BUDGET_FRACTION": "budget_fraction"}


class PVTreeConfigError(ValueError):
    """A tree recipe was refused."""


@dataclass(frozen=True)
class PVTreeConfig:
    """The tree's recipe; every field is digested (`recipe_payload`)."""
    sims: int
    eps: float = TREE_DEFAULTS["eps"]
    zmin: float = TREE_DEFAULTS["zmin"]
    max_contenders: int = TREE_DEFAULTS["max_contenders"]
    #: the continuation mode (module docstring; `CONT_TOKENS`)
    cont: str = TREE_DEFAULTS["cont"]
    #: ``trick-greedy``: the policy's top-R follows are a seat's reply candidates
    reply_candidates: int = TREE_DEFAULTS["reply_candidates"]
    #: the tree starts only while elapsed <= this fraction of the play budget ...
    budget_fraction: float = TREE_DEFAULTS["budget_fraction"]
    #: ... and abandons itself (for the PV decision) once elapsed reaches this one
    budget_stop_fraction: float = TREE_DEFAULTS["budget_stop_fraction"]
    schema: str = "pv-tree-recipe-v3"

    def __post_init__(self):
        if type(self.sims) is not int or not 0 <= self.sims <= MAX_SIMS:
            raise PVTreeConfigError(f"tree sims must be an integer in [0,{MAX_SIMS}]")
        for name in ("eps", "zmin"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise PVTreeConfigError(f"tree {name} must be a finite non-negative number")
            object.__setattr__(self, name, float(value))
        if type(self.max_contenders) is not int or not 2 <= self.max_contenders <= 16:
            raise PVTreeConfigError("tree max_contenders must be an integer in [2,16]")
        if self.cont not in CONT_TOKENS:
            raise PVTreeConfigError(f"tree cont must be one of {sorted(CONT_TOKENS)}")
        if type(self.reply_candidates) is not int or not 1 <= self.reply_candidates <= 16:
            raise PVTreeConfigError("tree reply_candidates must be an integer in [1,16]")
        for name in ("budget_fraction", "budget_stop_fraction"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1:
                raise PVTreeConfigError(f"tree {name} must be in (0,1]")
            object.__setattr__(self, name, float(value))
        if self.budget_stop_fraction < self.budget_fraction:
            raise PVTreeConfigError("tree budget_stop_fraction must be >= budget_fraction")


def tree_token(tree: PVTreeConfig | None) -> str:
    """The name token: ``""`` when off, else ``-ts<S>[-tcnh|-tcp][-te<eps>][-tz<zmin>]``."""
    if tree is None:
        return ""
    if not isinstance(tree, PVTreeConfig):
        raise PVTreeConfigError("tree must be a PVTreeConfig or None")
    token = f"-ts{tree.sims}{CONT_TOKENS[tree.cont]}"
    if tree.reply_candidates != TREE_DEFAULTS["reply_candidates"]:
        token += f"-tr{tree.reply_candidates}"
    if tree.eps != TREE_DEFAULTS["eps"]:
        token += f"-te{tree.eps:g}"
    if tree.zmin != TREE_DEFAULTS["zmin"]:
        token += f"-tz{tree.zmin:g}"
    return token


def tree_env(env, prefix: str = "SHENGJI_PV_") -> PVTreeConfig | None:
    """`PVTreeConfig` from the environment, or None when ``TREE_SIMS`` is unset."""
    raw = env.get(prefix + ENV_SIMS)
    given = {suffix: env.get(prefix + suffix) for suffix in (*ENV_FLOATS, ENV_CONT, ENV_REPLIES)}
    given = {suffix: value for suffix, value in given.items() if value not in (None, "")}
    if raw in (None, ""):
        if given:
            raise PVTreeConfigError(
                f"{prefix}{sorted(given)[0]} is set but {prefix}{ENV_SIMS} is not")
        return None
    if not raw.isdigit():
        raise PVTreeConfigError(f"{prefix}{ENV_SIMS} must be a non-negative integer, not {raw!r}")
    fields = {}
    if ENV_CONT in given:
        fields["cont"] = given.pop(ENV_CONT)
    if ENV_REPLIES in given:
        value = given.pop(ENV_REPLIES)
        if not value.isdigit():
            raise PVTreeConfigError(f"{prefix}{ENV_REPLIES} must be an integer, not {value!r}")
        fields["reply_candidates"] = int(value)
    for suffix, value in given.items():
        try:
            fields[ENV_FLOATS[suffix]] = float(value)
        except ValueError:
            raise PVTreeConfigError(f"{prefix}{suffix} must be a number, not {value!r}") from None
    return PVTreeConfig(sims=int(raw), **fields)
