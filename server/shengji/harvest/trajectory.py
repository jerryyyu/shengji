"""Natural-trajectory self-play generator: ``source: "trajectory"`` records.

Ledger basis: 29871a60 (data at scale from engine self-play) and 7a799e1c
(VALUE target = the round's final outcome; PRIOR target = the search's own
allocation over the exhaustive legal set; root exploration so off-ballot
moves can earn mass).  Tier i, engine only: nothing here spends LLM tokens.

What one run does
-----------------
``rounds / 2`` seeded deal clusters (deal seed ``seed0 + cluster``), each
played in both mirrors exactly as ``shengji.evaluation.run_arm`` seats an
arm: the four bots take seeds ``seed``, ``seed + 500_000``,
``seed + 1_000_000`` and ``seed + 1_500_000``; mirror 0 seats them
``[a1, b1, a2, b2]`` and mirror 1 ``[b1, a1, b2, a2]``.  All four seats play
the SAME registry policy (default ``mc-s0-report-lcb``), built through
``registry.make_bot`` (so the seed is forwarded and ``policy_name`` bound)
and then re-classed onto ``TrajectoryMixin`` -- a ``_candidates`` override,
the way ``OraclePriorMixin`` hands ``MCBot`` a modified ballot.  Every
``decide_play`` is followed by a read of ``MCBot.last_decision_record``
(``mc-decision-v2``: ``candidates``, ``n_by_candidate``, ``means``,
``paired_se``, ``eligible_indices``, ``work``, ``report_fold``).

Record mapping (``shengji-decision-record-v1``, ``source: "trajectory"``)
-------------------------------------------------------------------------
* ``round_seed`` and ``deck`` are both public: the deal is the
  reproducibility handle (as for room-log/highn); ``hidden_hands`` is null
  and there is no private split.
* ``ballot`` is the candidate list the search actually ran, exploration-added
  entries included; ``production_ballot`` is present only when exploration
  widened it and holds the plain ``MCBot._candidates`` list.
* ``allocation.weights`` is the search's allocation over the ballot,
  normalized to sum 1 and aligned with ``ballot`` (so it is zero outside the
  ballot by construction).  The counter, per candidate ``i``, is
  ``n_by_candidate[i]`` (the selection worlds on which candidate ``i`` was
  scored) PLUS the report-fold worlds actually used, credited to BOTH
  finalists (candidate 0 and ``report_candidate_index``) whenever the report
  fold ran, because each finalist was rolled out once per report world.
  Dummy residual rollouts (an equal-work control's ``dummy_rollouts``) are
  excluded: matched compute the decision rule never reads.  A decision the
  search never saw (a tractor-locked lead, a single-candidate ballot) and a
  zero-world fallback carry a point mass on the played action.
* ``action_values.means`` are the search's per-candidate means aligned with
  the ballot, acting-team perspective (higher is better for the acting
  seat's partnership; the policy's ``_score`` of rollout attacker points,
  sign-flipped for the banker team), with the paired SE against candidate 0.
  Non-finite floats become null.
* ``action`` is the submitted play; ``engine_play`` is stamped when the
  engine recorded different cards (a failed throw) and ``plays_prefix``
  carries the engine's cards.
* ``outcome`` is the FINAL round outcome, filled after the round ends,
  signed for the acting seat's partnership (``harvest.rebuild.outcome_for``:
  attacker points, winner team, level change, signed level utility, kitty
  bonus).
* ``source_ref`` = ``<run_id>:<cluster>:<mirror>:<seat>:<ply>`` (``bury``
  in place of the ply for a bury record); ``policy`` is the registry name;
  ``authority`` is null; ``exploration`` is documented in ``schema.py``.

Root exploration
----------------
With probability ``explore_rate`` per play decision that reaches a ballot,
up to ``explore_k`` uniformly random legal actions NOT already on the ballot
are appended, drawn from the exhaustive legal set of ``harvest.legal`` (a
bounded sample when the listing is capped).  The draws come from a
dedicated stream, ``random.Random(_child_seed((round_seed, mirror, seat),
"trajectory-explore"))``; the search's own ``self.rng`` is never touched,
so ``--explore-rate 0`` reproduces production decisions exactly (tested).
Added candidates receive selection worlds like any other candidate.  A
tractor-locked lead returns before a ballot exists (as in the oracle prior
arm) and is never widened.

Bury decisions
--------------
``MCBot.decide_bury`` exposes ``last_bury_record`` only when ``MC_BURY`` is
on.  The default policy (``mc-s0-report-lcb``, ``MC_BURY = False``) buries
with SmartBot's rule and exposes no record, so NO bury records are emitted
for it; the omission is visible as ``counts.bury_records == 0``.  A policy
whose bury path does expose a record (the registered ``*-structured-bury``
factories) gets one ``decision_kind: "bury"`` record per round, mapped like
a play record (ballot = the bury candidates, allocation from
``n_by_candidate``, means from ``mean_banker_value``).

Determinism and outputs
-----------------------
Rounds are independent (fresh bots, fresh ``Game``), so they may run in any
process; shards are merged in ``(cluster, mirror, seat, ply)`` order (a bury
record first within its seat) and the output bytes do not depend on
``--workers``.  ``run_id`` is a digest of the generating configuration
(policy, seed0, exploration, effective work, cap), never of the wall clock.
Outputs: ``trajectory.jsonl`` and ``manifest.json`` (through
``harvest.manifest``: git SHA, sha256 of the outputs, counts; the policy,
knobs, seeds and registered-vs-effective work sit under ``extras``).
"""

from __future__ import annotations

import argparse
import hashlib
import math
import multiprocessing
import os
import random
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Callable

from ..ai.mcbot import MCBot, _child_seed
from ..ai.registry import make_bot
from ..engine.game import Game
from ..engine.round import actual_play_after
from ..evaluation import counters as production_counters
from .common import ExtractResult, action_key
from .legal import DEFAULT_CAP, LegalSet, bury_action_count, enumerate_legal
from .rebuild import (actor_role, deck_from_seed, outcome_for,
                      round_from_setup, setup_from_round)
from .schema import canonical_json, finalize_record

SOURCE = "trajectory"
DEFAULT_POLICY = "mc-s0-report-lcb"
DEFAULT_EXPLORE_RATE = 0.1
DEFAULT_EXPLORE_K = 2
ALLOCATION_KIND = "trajectory-allocation-v1"
ACTION_VALUES_KIND = "trajectory-action-values-v1"
ALLOCATION_COUNTER = ("selection worlds per candidate (n_by_candidate) plus "
                      "the report-fold worlds used, credited to both finalists "
                      "(candidate 0 and report_candidate_index); dummy residual "
                      "rollouts excluded")
BURY_ALLOCATION_COUNTER = "bury worlds per candidate (n_by_candidate)"
EXPLORE_STREAM = "trajectory-explore"
#: seat seeds relative to the deal seed, as ``evaluation.run_arm`` assigns
#: them to ``a1, a2, b1, b2``
SEAT_SEED_OFFSETS = (0, 500_000, 1_000_000, 1_500_000)
SERVER = Path(__file__).resolve().parents[2]


class TrajectoryError(RuntimeError):
    """The requested generation cannot be carried out as specified."""


# ------------------------------------------------------------------ the bot

class TrajectoryMixin:
    """Root exploration and ballot capture layered on a production MCBot.

    ``_candidates`` is the injection point: ``MCBot.decide_play`` calls it
    exactly once per decision that reaches a ballot and runs the search on
    the list it returns.  The override records the production list,
    enumerates the exhaustive legal set once (the record needs it anyway)
    and appends the exploration draw taken from the dedicated stream.  The
    search stream ``self.rng`` is never read here.
    """

    EXPLORE_RATE = 0.0
    EXPLORE_K = 0
    LEGAL_CAP: int | None = DEFAULT_CAP

    def _trajectory_init(self, explore_rng: random.Random) -> None:
        self.explore_rng = explore_rng
        self.explore_opportunities = 0
        self.explore_fired = 0
        self.explore_added = 0
        self._trajectory_reset()

    def _trajectory_reset(self) -> None:
        self.last_ballot: list[list[str]] | None = None
        self.last_production_ballot: list[list[str]] | None = None
        self.last_exploration: dict | None = None
        self.last_legal: LegalSet | None = None

    def decide_play(self, rnd, seat):
        self._trajectory_reset()
        return super().decide_play(rnd, seat)

    def _candidates(self, rnd, seat):
        if self.last_ballot is not None:
            raise TrajectoryError(
                "MCBot._candidates was consulted twice in one decision; the "
                "exploration draw would be repeated")
        base = [list(c) for c in super()._candidates(rnd, seat)]
        legal = enumerate_legal(rnd, seat, cap=self.LEGAL_CAP, must_include=base)
        ballot = [list(c) for c in base]
        exploration = None
        if self.EXPLORE_RATE > 0 and self.EXPLORE_K > 0:
            self.explore_opportunities += 1
            if self.explore_rng.random() < self.EXPLORE_RATE:
                keys = {action_key(c) for c in base}
                pool = [list(a) for a in legal.actions if tuple(a) not in keys]
                added = self.explore_rng.sample(pool, min(self.EXPLORE_K, len(pool)))
                ballot.extend(list(a) for a in added)
                exploration = {"rate": float(self.EXPLORE_RATE),
                               "added": [list(a) for a in added]}
                self.explore_fired += 1
                self.explore_added += len(added)
        self.last_production_ballot = base
        self.last_ballot = ballot
        self.last_exploration = exploration
        self.last_legal = legal
        return [list(c) for c in ballot]


_TRAJECTORY_CLASSES: dict[type, type] = {}


def trajectory_class(base_cls: type) -> type:
    cls = _TRAJECTORY_CLASSES.get(base_cls)
    if cls is None:
        cls = type(f"Trajectory_{base_cls.__name__}",
                   (TrajectoryMixin, base_cls), {})
        _TRAJECTORY_CLASSES[base_cls] = cls
    return cls


def make_trajectory_bot(config: dict, *, seed: int, explore_rng: random.Random):
    """The registry policy, built by name with its seed forwarded, re-classed
    onto the mixin and given the run's exploration/work knobs."""
    bot = make_bot(config["policy"], seed=seed)
    if not isinstance(bot, MCBot):
        raise TrajectoryError(
            f"policy {config['policy']!r} is not an MCBot search policy: it "
            "has no ballot and no decision record to harvest")
    bot.__class__ = trajectory_class(type(bot))
    bot._trajectory_init(explore_rng)
    bot.EXPLORE_RATE = float(config["explore_rate"])
    bot.EXPLORE_K = int(config["explore_k"])
    bot.LEGAL_CAP = config["cap"]
    work = config["work"]
    if work["select_worlds"] is not None:
        bot.N_DETERMINIZATIONS = int(work["select_worlds"])
    if work["report_worlds"] is not None:
        bot.REPORT_FOLD_WORLDS = int(work["report_worlds"])
    return bot


def mirror_seat_seeds(seed: int, mirror: int) -> list[int]:
    """Bot seed per seat for one deal ``seed``: mirror 0 seats
    ``[a1, b1, a2, b2]``, mirror 1 ``[b1, a1, b2, a2]``."""
    a1, a2, b1, b2 = (seed + off for off in SEAT_SEED_OFFSETS)
    return [a1, b1, a2, b2] if mirror == 0 else [b1, a1, b2, a2]


def explore_seed(seed: int, mirror: int, seat: int) -> int:
    return _child_seed((seed, mirror, seat), EXPLORE_STREAM)


# ------------------------------------------------------------ configuration

def build_config(*, policy: str = DEFAULT_POLICY, seed0: int,
                 explore_rate: float = DEFAULT_EXPLORE_RATE,
                 explore_k: int = DEFAULT_EXPLORE_K,
                 select_worlds: int | None = None,
                 report_worlds: int | None = None,
                 cap: int | None = DEFAULT_CAP) -> dict:
    if not 0.0 <= float(explore_rate) <= 1.0:
        raise TrajectoryError("explore_rate must be in [0, 1]")
    if int(explore_k) < 0:
        raise TrajectoryError("explore_k must be >= 0")
    if cap is not None and int(cap) < 1:
        raise TrajectoryError("cap must be >= 1 (or None for unbounded)")
    probe = make_bot(policy, seed=0)
    if not isinstance(probe, MCBot):
        raise TrajectoryError(
            f"policy {policy!r} is not an MCBot search policy: it has no "
            "ballot and no decision record to harvest")
    registered = {
        "n_determinizations": int(probe.N_DETERMINIZATIONS),
        "report_fold_worlds": int(probe.REPORT_FOLD_WORLDS),
        "report_rule": str(probe.REPORT_RULE),
    }
    effective = dict(registered)
    if select_worlds is not None:
        if int(select_worlds) < 1:
            raise TrajectoryError("select_worlds must be >= 1")
        effective["n_determinizations"] = int(select_worlds)
    if report_worlds is not None:
        if int(report_worlds) < 0:
            raise TrajectoryError("report_worlds must be >= 0")
        effective["report_fold_worlds"] = int(report_worlds)
    # MCBot refuses these combinations at decision time; refuse before any
    # compute is spent.
    rule, worlds = effective["report_rule"], effective["report_fold_worlds"]
    if rule != "none" and worlds <= 0:
        raise TrajectoryError(f"report rule {rule!r} needs report worlds > 0")
    if rule == "none" and worlds > 0:
        raise TrajectoryError("report worlds without a report rule")
    if rule == "lcb" and worlds < 30:
        raise TrajectoryError("the LCB report rule needs at least 30 report "
                              "worlds (MCBot refuses fewer)")
    config = {
        "policy": policy,
        "policy_class": type(probe).__name__,
        "trajectory_class": trajectory_class(type(probe)).__name__,
        "seed0": int(seed0),
        "explore_rate": float(explore_rate),
        "explore_k": int(explore_k),
        "cap": None if cap is None else int(cap),
        "work": {
            "select_worlds": None if select_worlds is None else int(select_worlds),
            "report_worlds": None if report_worlds is None else int(report_worlds),
            "registered": registered,
            "effective": effective,
            "production": effective == registered,
        },
        "policy_flags": {
            "adaptive_allocation": bool(probe.ADAPTIVE_ALLOCATION),
            "require_exact_work": bool(probe.REQUIRE_EXACT_WORK),
            "extra_selection_work": int(probe.EXTRA_SELECTION_WORK),
            "level_objective": bool(probe.LEVEL_OBJECTIVE),
            "tractor_lock": bool(probe.TRACTOR_LOCK),
            "mc_bury": bool(probe.MC_BURY),
            "exact_endgame": bool(probe.EXACT_ENDGAME),
        },
    }
    config["run_id"] = run_id_for(config)
    return config


def run_id_for(config: dict) -> str:
    """A digest of what generates the records, so a rerun at the same seed
    and knobs reproduces ``source_ref`` byte for byte."""
    payload = {
        "policy": config["policy"],
        "seed0": config["seed0"],
        "explore_rate": config["explore_rate"],
        "explore_k": config["explore_k"],
        "cap": config["cap"],
        "work": config["work"]["effective"],
    }
    digest = hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()
    return f"traj-s{config['seed0']}-{digest[:12]}"


# ------------------------------------------------------------- record maps

def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def allocation_from_record(rec: dict, ballot: list[list[str]]) -> dict:
    """``allocation`` for a searched decision (see the module docstring)."""
    k = len(ballot)
    if [list(c) for c in rec["candidates"]] != ballot:
        raise TrajectoryError("decision record candidates differ from the "
                              "ballot handed to the search")
    n_by = [int(n) for n in rec["n_by_candidate"]]
    if len(n_by) != k:
        raise TrajectoryError("n_by_candidate is not aligned with the ballot")
    report_worlds = [0] * k
    fold = rec.get("report_fold")
    challenger = rec.get("report_candidate_index")
    if isinstance(fold, dict) and int(fold.get("worlds") or 0) > 0:
        if challenger is None or not 0 <= int(challenger) < k:
            raise TrajectoryError("report fold without a challenger index")
        for i in {0, int(challenger)}:
            report_worlds[i] += int(fold["worlds"])
    worlds = [a + b for a, b in zip(n_by, report_worlds)]
    total = sum(worlds)
    played = int(rec["played_index"])
    if total > 0:
        weights = [w / total for w in worlds]
    else:
        weights = [1.0 if i == played else 0.0 for i in range(k)]
    return {
        "kind": ALLOCATION_KIND,
        "weights": weights,
        "counter": ALLOCATION_COUNTER,
        "selection_worlds": n_by,
        "report_worlds": report_worlds,
        "total_worlds": total,
        "played_index": played,
        "raw_winner_index": rec.get("raw_winner_index"),
        "report_candidate_index": challenger,
        "reason": rec.get("reason"),
        "searched": True,
        "work": {key: _finite(v) for key, v in rec["work"].items()},
    }


def point_mass_allocation(reason: str) -> dict:
    return {
        "kind": ALLOCATION_KIND,
        "weights": [1.0],
        "counter": ALLOCATION_COUNTER,
        "selection_worlds": [0],
        "report_worlds": [0],
        "total_worlds": 0,
        "played_index": 0,
        "raw_winner_index": None,
        "report_candidate_index": None,
        "reason": reason,
        "searched": False,
        "work": None,
    }


def action_values_from_record(rec: dict) -> dict:
    fold = rec.get("report_fold")
    report = None
    if isinstance(fold, dict):
        report = {key: _finite(fold.get(key)) for key in (
            "gap", "se", "worlds", "attempts", "rejected", "complete", "rule",
            "critical", "statistic", "min_gain", "bound")}
    return {
        "kind": ACTION_VALUES_KIND,
        "perspective": "acting-team",
        "means": [_finite(m) for m in rec["means"]],
        "paired_se": [_finite(s) for s in rec["paired_se"]],
        "eligible_indices": [int(i) for i in rec["eligible_indices"]],
        "raw_winner_index": rec.get("raw_winner_index"),
        "report": report,
    }


def _play_fields(base: dict, run_id: str, cluster: int, mirror: int, rnd,
                 seat: int, prefix: list[dict], action: list[str], bot,
                 cap: int | None, stats: Counter) -> dict:
    rec = bot.last_decision_record
    ballot = bot.last_ballot
    legal = bot.last_legal
    production_ballot = None
    exploration = bot.last_exploration
    if ballot is None:
        # a tractor-locked lead: returned before any ballot was enumerated
        stats["tractor_locked"] += 1
        ballot = [list(action)]
        legal = enumerate_legal(rnd, seat, cap=cap, must_include=[action])
        allocation = point_mass_allocation("tractor_lock")
        action_values = None
    elif rec is None:
        if len(ballot) != 1 or action_key(ballot[0]) != action_key(action):
            raise TrajectoryError("no decision record for a contested ballot")
        stats["single_candidate"] += 1
        allocation = point_mass_allocation("single_candidate")
        action_values = None
    else:
        stats["searched"] += 1
        allocation = allocation_from_record(rec, ballot)
        action_values = action_values_from_record(rec)
        if action_key(rec["played"]) != action_key(action):
            raise TrajectoryError("decision record played a different action")
        if rec["work"].get("complete") is False:
            stats["incomplete_work"] += 1
    if exploration is not None:
        stats["explore_fired"] += 1
        stats["explore_added"] += len(exploration["added"])
        production_ballot = bot.last_production_ballot
        added_keys = {action_key(a) for a in exploration["added"]}
        if action_key(action) in added_keys:
            stats["explore_played"] += 1
    fields = {
        **base,
        "source_ref": f"{run_id}:{cluster}:{mirror}:{seat}:{len(prefix)}",
        "decision_kind": "play",
        "plays_prefix": [dict(p) for p in prefix],
        "seat": seat,
        "ply": len(prefix),
        "trick": len(prefix) // 4,
        "role": actor_role(rnd, seat),
        "legal_actions": [list(a) for a in legal.actions],
        "legal_actions_complete": legal.complete,
        "legal_actions_count": legal.count,
        "ballot": [list(c) for c in ballot],
        "production_ballot": production_ballot,
        "allocation": allocation,
        "action_values": action_values,
        "action": list(action),
        "exploration": exploration,
    }
    return fields


def _bury_fields(base: dict, run_id: str, cluster: int, mirror: int,
                 banker: int, hand_before: list[str], bury_cards: list[str],
                 raw: dict) -> dict:
    cands = [list(c["cards"]) for c in raw["candidates"]]
    n_by = [int(n) for n in raw["n_by_candidate"]]
    k = len(cands)
    if len(n_by) != k or not 0 <= int(raw["played_index"]) < k:
        raise TrajectoryError("bury record is not aligned with its candidates")
    played = int(raw["played_index"])
    if action_key(cands[played]) != action_key(bury_cards):
        raise TrajectoryError("bury record played a different burial")
    total = sum(n_by)
    weights = ([n / total for n in n_by] if total > 0 else
               [1.0 if i == played else 0.0 for i in range(k)])
    work = raw.get("work")
    return {
        **base,
        "source_ref": f"{run_id}:{cluster}:{mirror}:{banker}:bury",
        "decision_kind": "bury",
        "plays_prefix": [],
        "seat": banker, "ply": None, "trick": None,
        "role": "banker-team",
        "legal_actions": None, "legal_actions_complete": False,
        "legal_actions_count": bury_action_count(hand_before),
        "ballot": cands,
        "allocation": {
            "kind": ALLOCATION_KIND,
            "weights": weights,
            "counter": BURY_ALLOCATION_COUNTER,
            "selection_worlds": n_by,
            "report_worlds": [0] * k,
            "total_worlds": total,
            "played_index": played,
            "raw_winner_index": raw.get("raw_winner_index"),
            "report_candidate_index": None,
            "reason": raw.get("reason"),
            "searched": int(raw.get("candidate_count", k)) > 1,
            "work": ({key: _finite(v) for key, v in work.items()}
                     if isinstance(work, dict) else None),
        },
        "action_values": {
            "kind": ACTION_VALUES_KIND,
            "perspective": "acting-team",
            "means": [_finite(c.get("mean_banker_value")) for c in raw["candidates"]],
            "paired_se": None,
            "eligible_indices": None,
            "raw_winner_index": raw.get("raw_winner_index"),
            "report": None,
        },
        "action": list(bury_cards),
        "exploration": None,
    }


# ------------------------------------------------------------------- rounds

def play_trajectory_round(config: dict, cluster: int, seed: int, mirror: int
                          ) -> tuple[list[dict], dict]:
    """One self-play round on deal ``seed``; returns (records, stats).

    Drives the round exactly as ``shengji.ai.env.play_round`` does (deal with
    declarations, the final declare pass, finalize, bury, play), so that at
    ``explore_rate == 0`` the four bots make production's decisions.
    """
    run_id = config["run_id"]
    started = time.perf_counter()
    bots = [make_trajectory_bot(config, seed=s,
                                explore_rng=random.Random(explore_seed(seed, mirror, seat)))
            for seat, s in enumerate(mirror_seat_seeds(seed, mirror))]
    game = Game(random.Random(seed))
    rnd = game.start_round()
    deck = list(rnd.deck)
    if deck != deck_from_seed(rnd.trump_rank, rnd.banker, seed):
        raise TrajectoryError("the deal is not reproducible from round_seed")
    declarations: list[dict] = []
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({"seat": seat, "cards": list(cards)})
    for seat in range(4):  # the grace window, as play_round
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({"seat": seat, "cards": list(cards)})
    rnd.finalize_declare()
    banker = rnd.banker
    assert banker is not None
    hand_before_bury = sorted(rnd.hands[banker])
    bury_cards = list(bots[banker].decide_bury(rnd, banker))
    bury_raw = getattr(bots[banker], "last_bury_record", None)
    rnd.bury(banker, bury_cards)
    setup = setup_from_round(rnd)
    setup["declarations"] = declarations
    twin = round_from_setup(deck, setup)
    if ([sorted(h) for h in twin.hands] != [sorted(h) for h in rnd.hands]
            or twin.turn != rnd.turn or twin.trump_suit != rnd.trump_suit
            or bool(twin.trump_is_nt) != bool(rnd.trump_is_nt)):
        raise TrajectoryError("setup does not round-trip through rebuild")
    base = {
        "source": SOURCE,
        "policy": config["policy"],
        "round_seed": seed,
        "deck": deck,
        "setup": setup,
        "authority": None,
        "hidden_hands": None,
    }
    stats: Counter = Counter()
    pending: list[dict] = []
    if bury_raw is not None:
        pending.append(_bury_fields(base, run_id, cluster, mirror, banker,
                                    hand_before_bury, bury_cards, bury_raw))
        stats["bury_records"] += 1
    prefix: list[dict] = []
    while rnd.phase == "play":
        seat = rnd.turn
        assert seat is not None
        bot = bots[seat]
        action = list(bot.decide_play(rnd, seat))
        fields = _play_fields(base, run_id, cluster, mirror, rnd, seat, prefix,
                              action, bot, config["cap"], stats)
        prev_last = rnd.last_trick
        rnd.play(seat, action)
        played = actual_play_after(rnd, seat, prev_last)
        if action_key(played) != action_key(action):
            fields["engine_play"] = list(played)
            stats["failed_throws"] += 1
        pending.append(fields)
        prefix.append({"seat": seat, "cards": list(played)})
        stats["decisions"] += 1
    result = game.finish_round()
    records: list[dict] = []
    for fields in pending:
        outcome = outcome_for(result.attacker_points, banker=banker,
                              seat=fields["seat"], kitty_bonus=result.kitty_points)
        if (outcome["winner_team"] != result.winner_team
                or outcome["level_change"] != result.level_change):
            raise TrajectoryError("outcome differs from the engine's result")
        fields["outcome"] = outcome
        records.append(finalize_record(fields))
    stats["rounds"] = 1
    stats["plays"] = len(prefix)
    stats["records"] = len(records)
    for bot in bots:
        stats["explore_opportunities"] += bot.explore_opportunities
        stats["short_searches"] += bot.short_search_decisions
        stats["zero_world"] += bot.zero_world_decisions
        stats["search_calls"] += bot.search_calls
        stats["rollouts"] += bot.rollouts
    work = production_counters(bots)
    timing = {
        "wall_secs": round(time.perf_counter() - started, 4),
        "search_secs": round(float(work.pop("search_secs", 0.0)), 4),
    }
    return records, {"counts": dict(stats), "work": work, "timing": timing,
                     "cluster": cluster, "mirror": mirror, "seed": seed,
                     "attacker_points": int(result.attacker_points)}


def _round_task(args):
    config, cluster, seed, mirror = args
    return play_trajectory_round(config, cluster, seed, mirror)


def _record_order(record: dict) -> tuple[int, int]:
    return (int(record["seat"]), -1 if record["ply"] is None else int(record["ply"]))


def run_rounds(config: dict, *, rounds: int, seed0: int, workers: int = 1,
               progress: Callable[[int, int, int], None] | None = None
               ) -> tuple[list[dict], list[dict]]:
    """Play ``rounds`` rounds (``rounds/2`` clusters x both mirrors).

    Records are merged in ``(cluster, mirror, seat, ply)`` order regardless
    of how the worker pool scheduled the rounds.
    """
    if rounds < 2 or rounds % 2:
        raise TrajectoryError("rounds must be an even number >= 2: every "
                              "deal cluster plays both mirrors")
    if workers < 1:
        raise TrajectoryError("workers must be >= 1")
    keys = [(c, m) for c in range(rounds // 2) for m in (0, 1)]
    tasks = {(c, m): (config, c, seed0 + c, m) for c, m in keys}
    results: dict[tuple[int, int], tuple[list[dict], dict]] = {}
    done = decisions = 0

    def note(key):
        nonlocal done, decisions
        done += 1
        decisions += results[key][1]["counts"].get("decisions", 0)
        if progress:
            progress(done, len(keys), decisions)

    if workers == 1:
        for key in keys:
            results[key] = _round_task(tasks[key])
            note(key)
    else:
        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=min(workers, len(keys)),
                                 mp_context=ctx) as pool:
            futures = {pool.submit(_round_task, tasks[key]): key for key in keys}
            for future, key in futures.items():
                results[key] = future.result()
                note(key)
    records: list[dict] = []
    stats: list[dict] = []
    for key in keys:
        recs, st = results[key]
        records.extend(sorted(recs, key=_record_order))
        stats.append(st)
    return records, stats


# ----------------------------------------------------------------- identity

def _git(args, cwd) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=cwd, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _digest(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def identity(config: dict) -> dict:
    from ..engine.ballot import mc_ballot
    from ..engine import combos, fast
    repo = SERVER.parent
    probe = make_trajectory_bot(config, seed=0, explore_rng=random.Random(0))
    return {
        "git_sha": _git(["rev-parse", "HEAD"], repo),
        "git_dirty": bool(_git(["status", "--porcelain", "--untracked-files=no"],
                               repo)),
        "trajectory_module_sha256_16": _digest(Path(__file__)),
        "mcbot_sha256_16": _digest(SERVER / "shengji" / "ai" / "mcbot.py"),
        "registry_sha256_16": _digest(SERVER / "shengji" / "ai" / "registry.py"),
        "legal_sha256_16": _digest(SERVER / "shengji" / "harvest" / "legal.py"),
        "fast_engine": bool(fast.HAVE_FAST and combos.decompose is fast.decompose),
        "require_voids": bool(os.environ.get("SHENGJI_REQUIRE_VOIDS")),
        "ballot": str(mc_ballot(probe)),
        "python": sys.version.split()[0],
    }


# ------------------------------------------------------------------- driver

def generate(*, rounds: int, seed0: int, out_dir: str | os.PathLike,
             workers: int = 1, policy: str = DEFAULT_POLICY,
             explore_rate: float = DEFAULT_EXPLORE_RATE,
             explore_k: int = DEFAULT_EXPLORE_K,
             select_worlds: int | None = None, report_worlds: int | None = None,
             cap: int | None = DEFAULT_CAP,
             progress: Callable[[int, int, int], None] | None = None,
             argv: list[str] | None = None) -> dict:
    """Generate ``trajectory.jsonl`` + ``manifest.json`` in ``out_dir``."""
    from .manifest import build_manifest, write_source
    os.environ.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    config = build_config(policy=policy, seed0=seed0, explore_rate=explore_rate,
                          explore_k=explore_k, select_worlds=select_worlds,
                          report_worlds=report_worlds, cap=cap)
    ident = identity(config)
    started = time.perf_counter()
    records, per_round = run_rounds(config, rounds=rounds, seed0=seed0,
                                    workers=workers, progress=progress)
    wall = time.perf_counter() - started
    result = ExtractResult(SOURCE)
    for record in records:
        result.add(record, None)
    counts: Counter = Counter()
    work: Counter = Counter()
    search_secs = 0.0
    for st in per_round:
        counts.update(st["counts"])
        work.update(st["work"])
        search_secs += st["timing"]["search_secs"]
    for key in ("rounds", "decisions", "bury_records", "searched",
                "tractor_locked", "single_candidate", "explore_opportunities",
                "explore_fired", "explore_added", "explore_played",
                "short_searches", "zero_world", "incomplete_work",
                "failed_throws", "plays", "records"):
        counts.setdefault(key, 0)
    result.counts = {k: int(counts[k]) for k in sorted(counts)}
    result.extras = {
        "run_id": config["run_id"],
        "policy": {"name": config["policy"], "class": config["policy_class"],
                   "trajectory_class": config["trajectory_class"],
                   "flags": config["policy_flags"]},
        "knobs": {"seed0": config["seed0"], "rounds": int(rounds),
                  "clusters": rounds // 2, "workers": int(workers),
                  "explore_rate": config["explore_rate"],
                  "explore_k": config["explore_k"], "cap": config["cap"]},
        "seeds": {"deal": "seed0 + cluster; Game(random.Random(seed))",
                  "seats": "seed + (0, 500000, 1000000, 1500000) as a1, a2, "
                           "b1, b2; mirror 0 seats [a1, b1, a2, b2], mirror 1 "
                           "[b1, a1, b2, a2]",
                  "explore": f"random.Random(_child_seed((seed, mirror, seat), "
                             f"{EXPLORE_STREAM!r}))"},
        "work": {**config["work"], "realized": {k: int(work[k]) for k in sorted(work)}},
        "identity": ident,
        "rounds": [{"cluster": st["cluster"], "mirror": st["mirror"],
                    "seed": st["seed"], "attacker_points": st["attacker_points"],
                    "decisions": st["counts"].get("decisions", 0)}
                   for st in per_round],
        "timing": {"wall_secs": round(wall, 3),
                   "search_secs": round(search_secs, 3),
                   "decisions_per_sec": (round(counts["decisions"] / wall, 3)
                                         if wall > 0 else None),
                   "round_wall_secs": [st["timing"]["wall_secs"] for st in per_round]},
        "argv": list(argv) if argv is not None else None,
    }
    result.notes = [
        "allocation.weights = worlds_i / sum(worlds), worlds_i = "
        "n_by_candidate[i] + report-fold worlds credited to candidate 0 and "
        "report_candidate_index when the report fold ran; dummy residual "
        "rollouts excluded; point mass on the played action when the search "
        "never ran (tractor_lock, single_candidate) or scored zero worlds",
        "records ordered by (cluster, mirror, seat, ply); a bury record "
        "precedes its seat's plays",
        "bury records only when the policy's bury path exposes "
        "last_bury_record (MC_BURY); the default policy emits none",
        "exploration draws come from a dedicated stream; the search RNG is "
        "untouched, so explore_rate 0 reproduces production decisions",
    ]
    write_source(out_dir, result, cap=cap)
    manifest = build_manifest(out_dir)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trajectory", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rounds", type=int, required=True,
                        help="total rounds (even): rounds/2 clusters x 2 mirrors")
    parser.add_argument("--seed", type=int, required=True,
                        help="seed0; cluster c deals from seed0 + c")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out", required=True, type=Path, help="output directory")
    parser.add_argument("--policy", default=DEFAULT_POLICY,
                        help=f"registry policy for all four seats (default {DEFAULT_POLICY})")
    parser.add_argument("--explore-rate", type=float, default=DEFAULT_EXPLORE_RATE,
                        help="per-decision probability of widening the ballot "
                             f"(default {DEFAULT_EXPLORE_RATE}; 0 = production)")
    parser.add_argument("--explore-k", type=int, default=DEFAULT_EXPLORE_K,
                        help=f"legal actions added per exploring decision (default {DEFAULT_EXPLORE_K})")
    parser.add_argument("--select-worlds", type=int, default=None,
                        help="override N selection worlds (reduced work; stamped as effective)")
    parser.add_argument("--report-worlds", type=int, default=None,
                        help="override R report worlds (reduced work; LCB needs >= 30)")
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP,
                        help=f"max legal actions listed per record (default {DEFAULT_CAP}; 0 = unbounded)")
    return parser


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    args = build_parser().parse_args(argv)
    cap = None if args.cap == 0 else args.cap

    def progress(done: int, total: int, decisions: int) -> None:
        print(f"  round {done}/{total}: decisions={decisions}", flush=True)

    try:
        manifest = generate(
            rounds=args.rounds, seed0=args.seed, out_dir=args.out,
            workers=args.workers, policy=args.policy,
            explore_rate=args.explore_rate, explore_k=args.explore_k,
            select_worlds=args.select_worlds, report_worlds=args.report_worlds,
            cap=cap, progress=progress,
            argv=sys.argv if argv is None else ["trajectory", *argv])
    except TrajectoryError as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    source = manifest["sources"][SOURCE]
    counts = source["counts"]
    timing = source["extras"]["timing"]
    print(f"{SOURCE}: run_id={source['extras']['run_id']} rounds={counts['rounds']} "
          f"decisions={counts['decisions']} bury_records={counts['bury_records']} "
          f"searched={counts['searched']} explored={counts['explore_fired']} "
          f"added={counts['explore_added']} short={counts['short_searches']} "
          f"wall={timing['wall_secs']}s decisions/s={timing['decisions_per_sec']}",
          flush=True)
    for name, info in manifest["outputs"].items():
        print(f"  {name}: sha256={info['sha256']} bytes={info['bytes']}", flush=True)
    print(f"manifest -> {Path(args.out) / 'manifest.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
