"""The OPTIONAL second stage of the wide value-only bury (``SHENGJI_PV_BURY_TWO_STAGE``,
bury-name token ``bts`` after ``bwv``/``bwv2``; #707 S15).  OFF BY DEFAULT.

Release 45's chooser (`bury_wide_value`, ``bwv`` at K=64) ranks up to 64
candidate buries by the value head's mean over the arm's 32 model worlds, on a
leaf whose first trick the heuristic plays, and buries the argmax.  v77 found
that widening the set further gains nothing, so the open question is the
SCORING: the argmax of 64 noisy means over 32 shared worlds is biased upwards
(the winner's curse) and the one-trick leaf is shallow.

With the flag on the chooser keeps stage 1 exactly (the same candidates, the
same worlds, the same means, the same argmax) and then:

1. takes the stage-1 top ``top`` candidates (rank order, the stage-1 argmax
   first; `TOP_DEFAULT`);
2. draws ``worlds`` FRESH banker-view worlds on a stream of its own (a new
   ``mc-s0-report-lcb`` helper on the ``two-stage`` seed: the stage-1 worlds
   and every RNG the bot owns are untouched), so the stage-2 means carry no
   stage-1 selection bias;
3. scores every top candidate on EVERY one of those worlds (common random
   numbers: the same worlds, and a deterministic continuation, for each
   candidate, so the differences between candidates are paired): the
   post-bury position is played forward ``tricks`` whole tricks by the POLICY
   HEAD (the served package's prior, the argmax at every seat over its
   complete legal set: `leaf_first_trick.PolicyFirstTrick`, the heuristic
   for a seat the policy cannot play) and the value head scores the result
   from the banker's seat.  A position whose round ENDS inside those tricks
   (the policy's throws can empty the hands early; ``tricks`` = 25 is a full
   playout) is valued by its outcome instead, in the value head's units
   (`rl.value_afterstate.category_signed_level` of the banker's signed-level
   category, as `cwv_bury.rollout_bury_values` maps a rollout);
4. keeps the stage-1 argmax unless the best stage-2 mean beats ITS stage-2
   mean by more than ``margin`` (signed levels; the value declaration's test,
   ``best - incumbent > margin``, default 0.0) AND by more than ``z`` standard
   errors of their paired difference over the common worlds (default 1.0; 0
   disables it).  A tie keeps the higher stage-1 rank.  The second condition
   is there because the measured stage-2 differences among the top four are
   mostly within noise (the PR's measurement: at ``tricks`` = 2 the best
   beats the stage-1 argmax on 23 of 40 roots, by more than one paired
   standard error on 13, by more than two on 2).

How this differs from the hybrid bury that release 45 replaced
(`cwv_bury_policy.CWVBuryMixin`, arm ``hybrid``): the hybrid shortlisted from
the structured BALLOT only (19-32 candidates), by the value mean, then let MC
ROLLOUTS of the HEURISTIC continuation (the full round, scored in raw attacker
points through ``mc-s0-report-lcb``'s objective, a 5-point incumbent margin)
decide among the value top-4 and the HEURISTIC incumbent.  Here the shortlist
comes from the wide set (64 candidates: the ballot plus the incumbent's
swaps), the incumbent of the second stage is the VALUE argmax, not the
heuristic bury, and the second stage is the value head again on deeper
positions played by the served POLICY head, over fresh common worlds -- the
same units as stage 1, so the margin means the same thing in both.

Budget.  Stage 2 is optional work with its own deadline and a HARD fallback to
the stage-1 argmax (never to the heuristic incumbent: stage 1 is complete by
then).  It begins only after stage 1's last ``check_budget`` passed, and it
never calls the bury's ``check_budget``: its own check (before every world
draw, before and after every policy batch, before and after every value batch)
raises at ``min(stage-2 start + seconds, bury start + bury budget - reserve)``
(``seconds``: `SECONDS_DEFAULT`; ``reserve``: `RESERVE_SECONDS`).  An expiry,
or any error in stage 2, keeps the stage-1 argmax and records why; a partial
stage 2 is discarded (all or nothing).

Record: the ``cwv-bury-policy-v1`` record of `bury_wide_value` with
``picked_index`` (and ``wide_value.chosen_index`` / ``chosen_is_incumbent``)
the FINAL choice, plus ``two_stage``: ``config`` (the six parameters),
``stage1_index``,
``top`` (candidate indices, stage-1 order), ``means`` (stage-2, aligned with
``top``; None when stage 2 did not complete), ``paired_se`` (telemetry: the
standard error of each one's paired difference from the stage-1 argmax over
the common worlds), ``chosen_index``, ``switched``,
``completed``, ``fallback`` (None / ``"budget"`` / ``"error"``),
``error_class``, ``seconds``, ``deadline_seconds``, ``world_attempts``,
``positions``, ``terminal_positions``, ``policy_plays``, ``policy_fallbacks``.

Off (the default) nothing here is called: `bury_wide_value` checks the bot's
``bury_two_stage`` (class default None) and its record, name and decisions are
release 45's.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass

import numpy as np

from ..ai.registry import make_bot
from .cwv_bury import (_checked_batch_size, _post_bury_validated, _require_bury_round,
                       _validated_world_hands, _world_parts)
from .cwv_bury_policy import BuryPolicyError, _seed, _worlds
from .leaf_first_trick import PolicyFirstTrick
from ..rl.value_afterstate import category_signed_level, signed_level_category

#: the bury-name token, after the wide chooser's (``...-bury-<arm>-bwv-bts-<12 hex>``)
TOKEN = "bts"
#: the key the decision record carries the stage's telemetry under
RECORD_KEY = "two_stage"
#: the stage's identity inside the ``cwv-bury-recipe-v1`` digest
CHOOSER = "value-top-n-rescored-on-common-fresh-worlds-policy-tricks-then-value"
#: the defaults (module docstring; the latency they cost: the PR's measurement)
TOP_DEFAULT = 4
WORLDS_DEFAULT = 32
TRICKS_DEFAULT = 2
MARGIN_DEFAULT = 0.0
Z_DEFAULT = 1.0
SECONDS_DEFAULT = 1.0
#: the bounds a configuration may ask for
TOP_MAX = 16
WORLDS_MAX = 256
TRICKS_MAX = 25
Z_MAX = 10.0
SECONDS_MAX = 10.0
#: the part of the bury budget stage 2 always leaves unused
RESERVE_SECONDS = 0.25
#: the seed label of the stage's world helper (`cwv_bury_policy._seed`)
SEED_LABEL = "two-stage"


@dataclass(frozen=True)
class TwoStageConfig:
    """The stage's parameters (module docstring)."""

    top: int = TOP_DEFAULT
    worlds: int = WORLDS_DEFAULT
    tricks: int = TRICKS_DEFAULT
    margin: float = MARGIN_DEFAULT
    z: float = Z_DEFAULT
    seconds: float = SECONDS_DEFAULT

    def __post_init__(self):
        for name, low, high in (("top", 2, TOP_MAX), ("worlds", 1, WORLDS_MAX),
                                ("tricks", 1, TRICKS_MAX)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise BuryPolicyError(f"two-stage {name} must be an int in [{low}, {high}]")
        if (type(self.margin) not in (int, float) or isinstance(self.margin, bool)
                or not math.isfinite(self.margin) or self.margin < 0):
            raise BuryPolicyError("two-stage margin must be a finite number >= 0")
        if (type(self.z) not in (int, float) or isinstance(self.z, bool)
                or not math.isfinite(self.z) or not 0 <= self.z <= Z_MAX):
            raise BuryPolicyError(f"two-stage z must be a number in [0, {Z_MAX}]")
        if (type(self.seconds) not in (int, float) or isinstance(self.seconds, bool)
                or not math.isfinite(self.seconds) or not 0 < self.seconds <= SECONDS_MAX):
            raise BuryPolicyError(f"two-stage seconds must be a number in (0, {SECONDS_MAX}]")
        # canonical floats, so the identity digest does not depend on 0 vs 0.0
        object.__setattr__(self, "margin", float(self.margin))
        object.__setattr__(self, "z", float(self.z))
        object.__setattr__(self, "seconds", float(self.seconds))

    def identity(self) -> dict:
        return {"chooser": CHOOSER, **asdict(self)}


class StageTwoExpired(BuryPolicyError):
    """The stage's own deadline passed (it never reaches the bury's fallback)."""


def stage_two_deadline(config: TwoStageConfig, *, started: float, stage_started: float,
                       budget) -> float:
    """``min(stage start + seconds, bury start + budget - reserve)`` (no budget:
    the first term alone)."""
    deadline = stage_started + config.seconds
    if budget is not None:
        deadline = min(deadline, started + float(budget) - RESERVE_SECONDS)
    return deadline


def terminal_value(position) -> float:
    """A finished round's outcome in the value head's units, from the banker's
    team (`cwv_bury.rollout_bury_values`' mapping)."""
    return category_signed_level(signed_level_category(int(position.attacker_points), False))


def score_common_worlds(rnd, candidates, worlds, evaluator, player, tricks: int,
                        check=None, counts=None) -> np.ndarray:
    """Values ``[world, candidate]`` of every candidate on every world (the
    same worlds for each: common random numbers), each position played
    ``tricks`` whole tricks by ``player`` (`PolicyFirstTrick.play_first_tricks`,
    one trick a call, batched) before ``evaluator`` scores it from the
    banker's seat; a position whose round ended is valued by `terminal_value`
    and plays no further.  World-major batches of at most
    ``evaluator.max_batch``; ``check`` runs before every world and around
    every value batch (the player runs its own before and after every policy
    batch).  ``counts["terminal"]`` (when given) counts the ended positions."""
    banker = _require_bury_round(rnd)
    candidates = tuple(tuple(candidate) for candidate in candidates)
    worlds = tuple(_world_parts(world) for world in worlds)
    if not candidates or not worlds:
        raise BuryPolicyError("two-stage scoring needs at least one candidate and world")
    max_batch = _checked_batch_size(evaluator)
    values = np.empty((len(worlds), len(candidates)), dtype=np.float64)
    positions, slots = [], []

    def flush():
        if not positions:
            return
        for _ in range(tricks):
            live = [position for position in positions if position.phase == "play"]
            if not live:
                break
            player.play_first_tricks(live)
        live = [k for k, position in enumerate(positions) if position.phase == "play"]
        for k, position in enumerate(positions):
            if position.phase != "play":
                values[slots[k]] = terminal_value(position)
                if counts is not None:
                    counts["terminal"] = counts.get("terminal", 0) + 1
        if live:
            if check is not None:
                check()
            scored = np.asarray(evaluator.score([positions[k] for k in live], banker),
                                dtype=np.float64)
            if check is not None:
                check()
            if scored.shape != (len(live),):
                raise BuryPolicyError(f"evaluator returned {scored.shape}, expected ({len(live)},)")
            for k, value in zip(live, scored):
                values[slots[k]] = value
        positions.clear()
        slots.clear()

    for w, (hands, _buried) in enumerate(worlds):
        if check is not None:
            check()
        canonical = tuple(tuple(hand) for hand in _validated_world_hands(rnd, hands, banker))
        for c, candidate in enumerate(candidates):
            positions.append(_post_bury_validated(rnd, banker, canonical, candidate))
            slots.append((w, c))
            if len(positions) == max_batch:
                flush()
    flush()
    return values


def stage_two_choice(values, margin: float, z: float):
    """The stage's decision over ``values[world, j]`` (column 0: the stage-1
    argmax, then the rest of the top in stage-1 order): ``(best, switched,
    means, paired_se)``.  ``best`` is the highest mean (the lowest ``j`` on a
    tie); ``switched`` holds when ``best != 0`` and its mean beats column 0's
    by more than ``margin`` AND by more than ``z`` standard errors of the
    paired difference over the worlds (0 with a single world)."""
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 2 or values.shape[0] < 1 or values.shape[1] < 2:
        raise BuryPolicyError("two-stage values must be [worlds >= 1, candidates >= 2]")
    if not np.isfinite(values).all():
        raise BuryPolicyError("two-stage values must be finite")
    means = values.mean(axis=0)
    best = min(range(values.shape[1]), key=lambda j: (-float(means[j]), j))
    worlds = values.shape[0]
    diffs = values - values[:, :1]
    paired_se = (diffs.std(axis=0, ddof=1) / math.sqrt(worlds) if worlds > 1
                 else np.zeros(values.shape[1]))
    gap = float(means[best] - means[0])
    switched = bool(best != 0 and gap > margin and gap > z * float(paired_se[best]))
    return best, switched, means, paired_se


def run_stage_two(bot, rnd, seat, candidates, means, config: TwoStageConfig, *,
                  started: float) -> tuple[int, dict]:
    """Stage 2 (module docstring) over the stage-1 ``means`` of ``candidates``:
    returns the FINAL candidate index and the record's ``two_stage``.  Never
    raises for an expiry or an error inside the stage: both keep the stage-1
    argmax."""
    stage_started = time.perf_counter()
    order = sorted(range(len(candidates)), key=lambda i: (-float(means[i]), i))
    stage1 = order[0]
    top = order[:config.top]
    deadline = stage_two_deadline(config, started=started, stage_started=stage_started,
                                  budget=getattr(bot, "bury_serving_budget_seconds", None))

    def check():
        if time.perf_counter() >= deadline:
            raise StageTwoExpired("two-stage bury deadline expired")

    telemetry = {"config": asdict(config), "stage1_index": int(stage1), "top": [int(i) for i in top],
                 "means": None, "paired_se": None, "chosen_index": int(stage1), "switched": False,
                 "completed": False, "fallback": None, "error_class": None,
                 "seconds": 0.0, "deadline_seconds": deadline - stage_started,
                 "world_attempts": None, "positions": 0, "terminal_positions": 0,
                 "policy_plays": 0, "policy_fallbacks": 0}
    player = None
    counts = {}
    try:
        if len(top) < 2:
            raise BuryPolicyError("two-stage needs at least two candidates")
        check()
        helper = make_bot("mc-s0-report-lcb", seed=_seed(SEED_LABEL, bot.seed))
        worlds, attempts = _worlds(helper, rnd, seat, config.worlds, "two-stage",
                                   check_budget=check)
        telemetry["world_attempts"] = attempts
        player = PolicyFirstTrick(bot.predict, bot.version, helper.rollout_policy,
                                  check_budget=check)
        values = score_common_worlds(rnd, [candidates[i] for i in top], worlds, bot.evaluator,
                                     player, config.tricks, check, counts)
        best, switched, stage2, paired_se = stage_two_choice(values, config.margin, config.z)
        telemetry.update(means=stage2.tolist(), paired_se=paired_se.tolist(), completed=True,
                         positions=len(top) * len(worlds),
                         chosen_index=int(top[best] if switched else stage1), switched=switched)
    except Exception as exc:          # BaseException (cancellation) is not caught
        telemetry.update(fallback="budget" if isinstance(exc, StageTwoExpired) else "error",
                         error_class=type(exc).__name__, chosen_index=int(stage1),
                         switched=False, means=None, paired_se=None)
    telemetry["terminal_positions"] = int(counts.get("terminal", 0))
    if player is not None:
        telemetry.update(policy_plays=int(player.policy_plays),
                         policy_fallbacks=int(player.fallbacks))
    telemetry["seconds"] = time.perf_counter() - stage_started
    return telemetry["chosen_index"], telemetry


__all__ = ["TOKEN", "RECORD_KEY", "CHOOSER", "TOP_DEFAULT", "WORLDS_DEFAULT", "TRICKS_DEFAULT",
           "MARGIN_DEFAULT", "Z_DEFAULT", "SECONDS_DEFAULT", "TOP_MAX", "WORLDS_MAX",
           "TRICKS_MAX", "Z_MAX", "SECONDS_MAX", "RESERVE_SECONDS", "SEED_LABEL",
           "TwoStageConfig", "StageTwoExpired", "stage_two_deadline", "terminal_value",
           "score_common_worlds", "stage_two_choice", "run_stage_two"]
