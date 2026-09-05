"""Production search labels for harvested decision records
(``scripts/label_harvest.py``).

Purpose
-------
The harvest (``shengji.harvest``) stores off-distribution decision states:
human plays, Luna's plays, the PT1 exact-world teacher, the room logs and
the mc-highn-240 corpus.  None of them carries production's own search
evidence at those states.  This module rebuilds every record's complete
round and runs the production policy (``mc-s0-report-lcb``: N30 selection
worlds, R300 report-fold worlds, registry defaults, no class knob, no
widening) from the acting seat, EXACTLY the way the self-play generator
captures a decision (``harvest.trajectory``: ``registry.make_bot`` with the
seed forwarded, ``MCBot.decide_play`` on the live round, then
``MCBot.last_decision_record`` / ``mc-decision-v2``), so the labelled rows
can serve as search-facing validation holdouts (``cwv_eval`` /
``train_cwv --eval-holdout``: rank regret needs these labels, calibration
and points need the record's outcome).

Rebuild (reused, never reimplemented)
-------------------------------------
``harvest.rebuild.state_for_record`` (deck + setup + plays_prefix through
the engine's own deal / declare / bury / play path, the same as
``cwv_data.bridge_record``), then fail-closed checks: the rebuilt seat to
act is the record's seat, the rebuilt hands equal ``hidden_hands`` when the
record carries them, the role agrees with the engine, the played action is
legal, and the record's ``legal_actions`` agree with the enumerator
(``harvest.legal.enumerate_legal``: a complete set must be equal; a capped
listing must contain the enumerator's own prefix and every recorded action
must be legal in the rebuilt state; exact counts must agree).  A record
that fails any check is REFUSED with a reason (``REFUSALS``); bury
decisions are refused (``bury_decision``: there is no play search to run).
The prefix is replayed play by play through ``Round.play`` and every
engine-accepted play is compared with the recorded cards: a recorded
SUBMITTED failed throw (the highn extractor stored the attempt, the engine
played its forced component; 13 rows, harvest audit) is repaired by the
engine itself -- the rebuilt state is the engine's, verified by the legal
set -- and stamped ``prefix_engine_diffs`` / ``failed_throw_prefix``.

Data-quality rules from the harvest audit
-----------------------------------------
* Identical labelling WORK is done ONCE.  ``state_key`` (``KEY_VERSION``
  2) is bound to the rebuilt state: the deck, the WHOLE setup (trump rank,
  banker, every declaration, the final declaration, trump, the burial,
  passes -- which with the deck fixes every hand after the burial), the
  canonical plays_prefix, the seat and the decision kind; ``work_key`` adds
  the played action (the search force-includes it, so a different played
  action at one state is different work and is labelled separately).  A
  record whose ``work_key`` an earlier record (or an already-labelled row)
  owns gets a row refused ``duplicate_state`` naming its twin, and the
  manifest lists them (room-log rounds logged twice, Luna positions reached
  in both mirrors, PT1's 4 seeds per position).  A record that fails
  ``validate_record`` never owns a work key (it is refused
  ``invalid_record`` before any dedup bookkeeping, at ingestion and when
  ownership is rebuilt from resumed shards), so a corrupt first copy can
  never shadow its valid twin.
* Migration: a run first admits its inputs and the directory (every input
  exists, policy / scale / cap match ``run.json``) WITHOUT touching a shard.
  Shards holding rows of an older ``key_version`` are then MOVED aside to
  ``shards/legacy-v<k>/`` (byte-identical, with a manifest), never
  truncated; every legacy row whose original record validates gets its
  keys re-derived under the current scheme and is carried forward into
  ``shards/<source>.migrated.jsonl`` -- its search result depends only on
  the record (seed, rebuild), never on the key -- except a ``duplicate_state``
  row whose twin no longer owns its new work key (a mis-dedup): that row
  is relabelled.
* ``harvest.schema.validate_record`` runs on every record at ingestion
  (``invalid_record`` refusal: a hash drift, a foreign field, a
  cross-field violation) and again on the stripped record when a labelled
  file is consumed (``cwv_eval.load_labeled_holdout``).
* ``human`` is 100% contained in ``room-log`` (its rows are the human_v8
  subset of the room-log human plays): it is not in the default
  ``--sources`` and is refused as duplicates when labelled next to room-log.
* Forced decisions (exactly one legal action) are labelled cheaply (no
  search) and flagged ``forced`` so the holdout metrics skip them.
* The ballot is ALWAYS production's list generated at label time
  (``ballot_source``); ``record_ballot_matches`` says whether the record's
  own ballot (when it has one) is the same set.
* Every row carries ``deal_key`` (``train.data.deal_key``) and
  ``state_key`` so holdout CIs can cluster by deal (Luna: 30 deals).

Capture
-------
``label_record``: a fresh registry bot at ``label_seed(record_sha256,
scale)`` (a ``_child_seed`` stream over the record hash: deterministic,
independent of worker and order), re-classed onto ``LabelMixin`` whose
``_candidates`` returns production's ballot with the PLAYED action
force-included when production did not list it (``played_in_ballot``
false).  ``decide_play`` runs; the ``mc-decision-v2`` record gives the
per-candidate selection means (acting-team-signed attacker points, the
units of trajectory ``action_values.means``), the paired SEs, the chosen
index, the reason, the report fold and the work; ``allocation`` and
``action_values`` are mapped by ``harvest.trajectory``'s own functions.  A
tractor-locked lead returns before any ballot exists and a one-candidate
ballot never searches: both are labelled ``searched: false`` with the
point-mass reason (``tractor_lock`` / ``single_candidate``) and no means,
as the generator records them.  ``--scale 3`` runs N90/R900 (the identity
is in the block).

Output
------
One row per input record: the input record UNTOUCHED (every field,
``record_sha256`` still valid) plus ``search_labels`` (the block, or null)
and ``label_refusal`` (``{"reason", "detail"}``, or null).  Rows are
appended to per-(source, worker) shards ``shards/<source>.w<k>[.private]
.jsonl`` (one ``write`` per line, 0600 for private inputs); a rerun reads
every shard, drops a torn last line, skips every ``record_sha256`` already
present and labels the rest (``--resume`` semantics are the default; the
run identity in ``run.json`` -- policy, scale, source tree digest --
must match).  ``manifest.json`` (atomic) carries per-source counts
(labelled / searched / unsearched by reason / refused by reason), the
sha256 and row count of every shard and of the merged per-source files
``<source>.labels[.private].jsonl`` (input order, the loader's input), the
code identity, the seed recipe and the wall statistics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing
import os
import statistics
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..ai.mcbot import MCBot, _child_seed
from ..ai.registry import make_bot
from ..harvest.common import action_key, sha256_file
from ..engine.round import actual_play_after
from ..harvest.legal import DEFAULT_CAP, LegalSet, enumerate_legal, is_legal
from ..harvest.rebuild import RebuildError, actor_role, deck_from_seed, round_from_setup
from ..harvest.schema import SCHEMA, SchemaError, canonical_json, validate_record
from .data import TrainDataError, deal_key
from ..harvest.trajectory import (SERVER, _source_tree_digest, action_values_from_record,
                                  allocation_from_record, environment_identity)

LABELS_SCHEMA = "shengji-harvest-labels-v1"
#: the state/work key scheme; rows at another version are relabelled
KEY_VERSION = 2
MANIFEST_SCHEMA = "shengji-harvest-labels-manifest-v1"
RUN_SCHEMA = "shengji-harvest-labels-run-v1"
POLICY = "mc-s0-report-lcb"
SEED_STREAM = "harvest-labels-v1"
SEED_RECIPE = f"_child_seed((record_sha256, scale), {SEED_STREAM!r}) (ai.mcbot._child_seed)"
#: the harvest files a source name resolves to inside ``--in-dir``
SOURCE_FILES = {
    "human": "human.jsonl",
    "luna-rpc": "luna-rpc.private.jsonl",
    "pt1": "pt1.private.jsonl",
    "room-log": "room-log.jsonl",
    "highn": "highn.jsonl",
}
SOURCES = tuple(SOURCE_FILES)
#: ``human`` is contained in ``room-log`` (audit): not labelled by default
DEFAULT_SOURCES = ("luna-rpc", "pt1", "room-log", "highn")
HUMAN_NOTE = ("human.jsonl is 100% contained in room-log.jsonl (the human_v8 subset of the "
              "room-log human plays; harvest audit): it is excluded from the default "
              "--sources and, when labelled next to room-log, its rows are duplicate_state")
REFUSALS = ("bury_decision", "not_play", "wrong_schema", "no_deck", "rebuild_failed",
            "turn_mismatch", "hidden_hands_mismatch", "role_drift", "action_illegal",
            "legal_set_mismatch", "search_failed", "duplicate_state", "invalid_record")
#: refusals that never own a work key (a twin of theirs is not "done work")
NON_OWNING = ("duplicate_state", "invalid_record")
#: the keys a labelled row adds to its harvest record
ROW_KEYS = ("search_labels", "label_refusal", "deal_key", "state_key", "work_key",
            "key_version", "migrated_from")
BALLOT_SOURCE = f"production:{POLICY} MCBot._candidates at label time"
UNSEARCHED = ("tractor_lock", "single_candidate")
#: test-only fault injection: a worker raises after this many rows
FAIL_AFTER_ENV = "SHENGJI_LABELS_FAIL_AFTER"
PROGRESS_SECS = 30.0


class LabelError(RuntimeError):
    """The labelling run cannot be carried out as specified."""


class LabelRefused(Exception):
    """One record cannot be labelled; ``reason`` is one of ``REFUSALS``."""

    def __init__(self, reason: str, detail: str = ""):
        assert reason in REFUSALS, reason
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


# ----------------------------------------------------------------- seeding

def label_seed(record_sha256: str, scale: int = 1) -> int:
    """The bot seed of one record: a named stream over the record hash."""
    return _child_seed((str(record_sha256), int(scale)), SEED_STREAM)


# ----------------------------------------------------------------- rebuild

def _canonical_setup(setup: Mapping[str, Any]) -> dict:
    decl = setup.get("declaration")
    return {
        "trump_rank": setup.get("trump_rank"), "banker": setup.get("banker"),
        "declarations": [[int(d["seat"]), sorted(d["cards"])]
                         for d in setup.get("declarations") or []],
        "declaration": None if decl is None else [int(decl["seat"]), sorted(decl["cards"]),
                                                  decl.get("strength")],
        "trump_suit": setup.get("trump_suit"), "trump_is_nt": bool(setup.get("trump_is_nt")),
        "buried": sorted(setup.get("buried") or []),
        "passed": sorted(int(x) for x in setup.get("passed") or []),
    }


def state_key(record: Mapping[str, Any]) -> str:
    """The identity of the rebuilt decision state (``KEY_VERSION``): deck +
    whole setup (declarations, final declaration, trump, burial, passes:
    with the deck this fixes every hand after the burial) + canonical
    plays_prefix + seat + decision_kind."""
    prefix = [[int(p["seat"]), sorted(p["cards"])] for p in record.get("plays_prefix") or []]
    body = [KEY_VERSION, record.get("deck"), _canonical_setup(record.get("setup") or {}),
            prefix, int(record["seat"]), record.get("decision_kind")]
    return hashlib.sha256(canonical_json(body).encode("ascii")).hexdigest()[:32]


def work_key(record: Mapping[str, Any]) -> str:
    """The identity of the labelling WORK: the state plus the played action
    the search must include."""
    body = [KEY_VERSION, state_key(record), sorted(record.get("action") or [])]
    return hashlib.sha256(canonical_json(body).encode("ascii")).hexdigest()[:32]


def record_deal_key(record: Mapping[str, Any]) -> str | None:
    deck = record.get("deck")
    if not isinstance(deck, list):
        return None
    try:
        return deal_key(list(deck))
    except TrainDataError:
        return None


def replay_checked(record: Mapping[str, Any]):
    """``rebuild.state_for_record``'s path (``round_from_setup`` then
    ``Round.play`` per prefix play) with every engine-accepted play compared
    with the recorded cards; returns ``(round, diffs)`` where ``diffs`` is
    ``[[index, recorded, engine], ...]`` (a recorded submitted failed throw
    the engine replaced by its forced component)."""
    deck = record.get("deck")
    if deck is None:
        deck = deck_from_seed(record["setup"]["trump_rank"], record["setup"]["banker"],
                              int(record["round_seed"]))
    rnd = round_from_setup(deck, record["setup"])
    diffs: list[list] = []
    for i, play in enumerate(record.get("plays_prefix") or []):
        seat = int(play["seat"])
        cards = list(play["cards"])
        prev_last = rnd.last_trick
        rnd.play(seat, cards)
        played = actual_play_after(rnd, seat, prev_last)
        if action_key(played) != action_key(cards):
            diffs.append([i, cards, list(played)])
    return rnd, diffs


def rebuild_for_label(record: Mapping[str, Any], *, cap: int | None = DEFAULT_CAP):
    """Rebuild the decision state of ``record`` and verify it against the
    record (module docstring); returns ``(round, LegalSet, prefix diffs)``
    or raises ``LabelRefused``."""
    if record.get("schema") != SCHEMA:
        raise LabelRefused("wrong_schema", repr(record.get("schema")))
    try:
        validate_record(record)
    except SchemaError as exc:
        raise LabelRefused("invalid_record", str(exc)) from exc
    kind = record.get("decision_kind")
    if kind == "bury":
        raise LabelRefused("bury_decision", "no play search at a bury decision")
    if kind != "play":
        raise LabelRefused("not_play", repr(kind))
    if record.get("deck") is None and record.get("round_seed") is None:
        raise LabelRefused("no_deck", "neither deck nor round_seed")
    try:
        rnd, diffs = replay_checked(record)
    except Exception as exc:  # noqa: BLE001 -- IllegalPlay, RebuildError, ...: refused, named
        raise LabelRefused("rebuild_failed", f"{type(exc).__name__}: {exc}") from exc
    seat = int(record["seat"])
    if rnd.phase != "play" or rnd.turn != seat:
        raise LabelRefused("turn_mismatch",
                           f"rebuilt phase {rnd.phase!r} turn {rnd.turn}, record seat {seat}")
    hidden = record.get("hidden_hands")
    if hidden is not None:
        hands = [sorted(h) for h in hidden.get("hands_by_seat") or []]
        if hands != [sorted(h) for h in rnd.hands]:
            raise LabelRefused("hidden_hands_mismatch",
                               "the rebuilt hands differ from hidden_hands.hands_by_seat")
        if sorted(hidden.get("buried") or []) != sorted(rnd.buried):
            raise LabelRefused("hidden_hands_mismatch",
                               "the rebuilt burial differs from hidden_hands.buried")
    if record.get("role") != actor_role(rnd, seat):
        raise LabelRefused("role_drift", f"record role {record.get('role')!r}, "
                                         f"engine {actor_role(rnd, seat)!r}")
    action = list(record["action"])
    if not is_legal(rnd, seat, action):
        raise LabelRefused("action_illegal", f"{action} is not legal in the rebuilt state")
    legal = enumerate_legal(rnd, seat, cap=cap, must_include=[action])
    recorded = record.get("legal_actions")
    if recorded is not None:
        rec_keys = {action_key(a) for a in recorded}
        illegal = [a for a in recorded if not is_legal(rnd, seat, list(a))]
        if illegal:
            raise LabelRefused("legal_set_mismatch",
                               f"{len(illegal)} recorded legal action(s) are illegal in the "
                               f"rebuilt state, e.g. {list(illegal[0])}")
        count = record.get("legal_actions_count")
        if count is not None and legal.count is not None and int(count) != legal.count:
            raise LabelRefused("legal_set_mismatch",
                               f"legal count {legal.count} rebuilt vs {count} recorded")
        if record.get("legal_actions_complete"):
            if not legal.complete or legal.keys() != rec_keys:
                raise LabelRefused("legal_set_mismatch",
                                   f"complete legal set differs: {len(legal.actions)} rebuilt "
                                   f"vs {len(recorded)} recorded")
        else:
            width = len(recorded) if cap is None else min(cap, len(recorded))
            prefix = legal.actions[:width]
            missing = [a for a in prefix if tuple(a) not in rec_keys]
            if missing:
                raise LabelRefused("legal_set_mismatch",
                                   f"{len(missing)} enumerated legal action(s) absent from the "
                                   f"recorded listing, e.g. {list(missing[0])}")
    return rnd, legal, diffs


# --------------------------------------------------------------------- bot

class LabelMixin:
    """``_candidates`` = production's ballot + the played action when it is
    missing.  The search stream ``self.rng`` is never read here."""

    def _label_reset(self, played: Sequence[str]) -> None:
        self.label_played = list(played)
        self.last_ballot: list[list[str]] | None = None
        self.last_production_ballot: list[list[str]] | None = None
        self.played_in_ballot: bool | None = None

    def _candidates(self, rnd, seat):
        if self.last_ballot is not None:
            raise LabelError("MCBot._candidates was consulted twice in one decision")
        production = [list(c) for c in super()._candidates(rnd, seat)]
        ballot = [list(c) for c in production]
        in_ballot = action_key(self.label_played) in {action_key(c) for c in production}
        if not in_ballot:
            ballot.append(list(self.label_played))
        self.last_production_ballot = production
        self.last_ballot = ballot
        self.played_in_ballot = in_ballot
        return [list(c) for c in ballot]


_LABEL_CLASSES: dict[type, type] = {}


def label_class(base_cls: type) -> type:
    cls = _LABEL_CLASSES.get(base_cls)
    if cls is None:
        cls = type(f"Label_{base_cls.__name__}", (LabelMixin, base_cls), {})
        _LABEL_CLASSES[base_cls] = cls
    return cls


def make_label_bot(*, seed: int, scale: int = 1, policy: str = POLICY,
                   work: tuple[int, int] | None = None):
    """The registry policy with its seed forwarded, re-classed onto the
    mixin; ``scale`` multiplies both work knobs (``work=(n, r)`` sets them
    outright: tests only, stamped in the block)."""
    bot = make_bot(policy, seed=seed)
    if not isinstance(bot, MCBot):
        raise LabelError(f"policy {policy!r} is not an MCBot search policy")
    bot.__class__ = label_class(type(bot))
    if work is not None:
        bot.N_DETERMINIZATIONS = int(work[0])
        bot.REPORT_FOLD_WORLDS = int(work[1])
    elif int(scale) != 1:
        bot.N_DETERMINIZATIONS = int(bot.N_DETERMINIZATIONS) * int(scale)
        bot.REPORT_FOLD_WORLDS = int(bot.REPORT_FOLD_WORLDS) * int(scale)
    return bot


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _index_of(ballot: Sequence[Sequence[str]], action: Sequence[str]) -> int | None:
    key = action_key(action)
    for i, cand in enumerate(ballot):
        if action_key(cand) == key:
            return i
    return None


def code_identity() -> dict:
    """What produced the labels: git, the mcbot / registry / legal / this
    module's bytes, the whole source tree, the ballot identity and the
    environment switches (``harvest.trajectory.environment_identity``)."""
    from ..ai import mcbot, registry
    from ..harvest import legal
    from ..engine import combos, fast

    def short(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]

    repo = SERVER.parent
    try:
        git_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                                 capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                                    cwd=repo, check=True, capture_output=True,
                                    text=True).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        git_sha, dirty = None, None
    probe = make_label_bot(seed=0)
    tree = _source_tree_digest(SERVER / "shengji")
    return {
        "git_sha": git_sha, "git_dirty": dirty,
        "source_tree_sha256": tree,
        "code_sha": tree[:16],
        "mcbot_sha256_16": short(Path(mcbot.__file__)),
        "registry_sha256_16": short(Path(registry.__file__)),
        "legal_sha256_16": short(Path(legal.__file__)),
        "labels_sha256_16": short(Path(__file__)),
        "ballot": mcbot._ballot_identity(probe),
        "fast_engine": bool(fast.HAVE_FAST and combos.decompose is fast.decompose),
        "env": environment_identity(),
        "python": sys.version.split()[0],
    }


def search_labels(record: Mapping[str, Any], rnd, *, scale: int = 1, code_sha: str | None,
                  work: tuple[int, int] | None = None, legal: LegalSet | None = None,
                  prefix_diffs: Sequence[Sequence] = ()) -> dict:
    """Run the production search at the rebuilt state and map its decision
    record to the ``search_labels`` block (module docstring)."""
    seat = int(record["seat"])
    action = list(record["action"])
    forced = bool(legal is not None and legal.complete and len(legal.actions) == 1)
    seed = label_seed(record["record_sha256"], scale)
    bot = make_label_bot(seed=seed, scale=scale, work=work)
    bot._label_reset(action)
    started = time.perf_counter()
    try:
        chosen = list(bot.decide_play(rnd, seat))
    except Exception as exc:  # noqa: BLE001 -- refused with the reason, never silent
        raise LabelRefused("search_failed", f"{type(exc).__name__}: {exc}") from exc
    wall_ms = round((time.perf_counter() - started) * 1000.0, 3)
    rec = bot.last_decision_record
    ballot = bot.last_ballot
    block: dict[str, Any] = {
        "schema": LABELS_SCHEMA,
        "policy": POLICY,
        "policy_class": type(bot).__mro__[2].__name__,   # the registry class under the mixin
        "scale": int(scale),
        "n_worlds": int(bot.N_DETERMINIZATIONS),
        "report_worlds": int(bot.REPORT_FOLD_WORLDS),
        "report_rule": bot.REPORT_RULE,
        "work_override": None if work is None else [int(work[0]), int(work[1])],
        "seed": seed,
        "seed_recipe": SEED_RECIPE,
        "chosen": chosen,
        "forced": forced,
        "legal_count": None if legal is None else legal.count,
        "ballot_source": BALLOT_SOURCE,
        "record_ballot_matches": None,
        "failed_throw_prefix": bool(prefix_diffs),
        "prefix_engine_diffs": [list(d) for d in prefix_diffs],
        "code_sha": code_sha,
        "wall_ms": wall_ms,
    }
    recorded_ballot = record.get("ballot")
    if ballot is None:
        # a tractor-locked lead: production returned before any ballot
        ballot = [list(chosen)]
        in_ballot = action_key(action) == action_key(chosen)
        block.update({
            "ballot": ballot, "production_ballot": [list(chosen)],
            "means": None, "se": None, "eligible_indices": None,
            "chosen_index": 0, "played_index": 0 if in_ballot else None,
            "played_in_ballot": in_ballot, "reason": "tractor_lock", "searched": False,
            "worlds_sampled": 0, "report_fold": None, "allocation": None,
            "action_values": None, "work": None,
        })
        return block
    played_index = _index_of(ballot, action)
    assert played_index is not None
    if isinstance(recorded_ballot, list):
        block["record_ballot_matches"] = (
            {action_key(c) for c in recorded_ballot}
            == {action_key(c) for c in bot.last_production_ballot})
    if rec is None:
        if len(ballot) != 1:
            raise LabelError("no decision record for a contested ballot")
        block.update({
            "ballot": [list(c) for c in ballot],
            "production_ballot": [list(c) for c in bot.last_production_ballot],
            "means": None, "se": None, "eligible_indices": None,
            "chosen_index": 0, "played_index": played_index,
            "played_in_ballot": bool(bot.played_in_ballot),
            "reason": "single_candidate", "searched": False,
            "worlds_sampled": 0, "report_fold": None, "allocation": None,
            "action_values": None, "work": None,
        })
        return block
    if [list(c) for c in rec["candidates"]] != [list(c) for c in ballot]:
        raise LabelError("decision record candidates differ from the ballot handed to "
                         "the search")
    if action_key(rec["played"]) != action_key(chosen):
        raise LabelError("decision record played a different action than decide_play")
    values = action_values_from_record(rec)
    block.update({
        "ballot": [list(c) for c in ballot],
        "production_ballot": [list(c) for c in bot.last_production_ballot],
        "means": values["means"],
        "se": values["paired_se"],
        "eligible_indices": values["eligible_indices"],
        "chosen_index": int(rec["played_index"]),
        "played_index": played_index,
        "played_in_ballot": bool(bot.played_in_ballot),
        "reason": rec.get("reason"),
        "searched": True,
        "worlds_sampled": int(rec["worlds"]),
        "report_fold": values["report"],
        "raw_winner_index": rec.get("raw_winner_index"),
        "report_candidate_index": rec.get("report_candidate_index"),
        "allocation": allocation_from_record(rec, [list(c) for c in ballot]),
        "action_values": values,
        "work": {k: _finite(v) for k, v in rec["work"].items()},
    })
    return block


def label_record(record: Mapping[str, Any], *, scale: int = 1, cap: int | None = DEFAULT_CAP,
                 code_sha: str | None = None, work: tuple[int, int] | None = None,
                 duplicate_of: str | None = None) -> dict:
    """The output row of one input record (module docstring: Output);
    ``duplicate_of`` names the labelled twin of an exact duplicate (no
    search, refused ``duplicate_state``)."""
    row = dict(record)
    row["deal_key"] = record_deal_key(record)
    row["key_version"] = KEY_VERSION
    try:
        row["state_key"] = state_key(record)
        row["work_key"] = work_key(record)
    except (KeyError, TypeError, ValueError, AttributeError):
        row["state_key"] = row["work_key"] = None
    started = time.perf_counter()
    try:
        # identity first: an invalid record is refused before it can be a
        # duplicate of anything (it never owns nor inherits a work key)
        if record.get("schema") == SCHEMA:
            try:
                validate_record(record)
            except SchemaError as exc:
                raise LabelRefused("invalid_record", str(exc)) from exc
        if duplicate_of is not None:
            row["search_labels"] = None
            row["label_refusal"] = {"reason": "duplicate_state", "detail": duplicate_of,
                                    "duplicate_of": duplicate_of, "wall_ms": 0.0}
            return row
        rnd, legal, diffs = rebuild_for_label(record, cap=cap)
        labels = search_labels(record, rnd, scale=scale, code_sha=code_sha, work=work,
                               legal=legal, prefix_diffs=diffs)
    except LabelRefused as exc:
        row["search_labels"] = None
        row["label_refusal"] = {"reason": exc.reason, "detail": exc.detail,
                                "wall_ms": round((time.perf_counter() - started) * 1000.0, 3)}
        return row
    row["search_labels"] = labels
    row["label_refusal"] = None
    return row


# ------------------------------------------------------------------ shards

def _is_private(path: Path) -> bool:
    return not (path.stat().st_mode & 0o044)


def shard_path(out_dir: Path, source: str, worker: int, private: bool) -> Path:
    suffix = ".private.jsonl" if private else ".jsonl"
    return Path(out_dir) / "shards" / f"{source}.w{worker}{suffix}"


def _atomic_write_text(path: Path, text: str, mode: int = 0o644) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_shard(path: Path) -> tuple[list[dict], bool]:
    """Every complete row of a shard; a torn last line (no newline or not
    JSON) is dropped and reported (``torn`` true) -- the rerun relabels it."""
    data = path.read_bytes()
    rows: list[dict] = []
    torn = False
    if not data:
        return rows, torn
    lines = data.split(b"\n")
    tail = lines.pop()               # b"" when the file ends with a newline
    if tail:
        torn = True
    for line in lines:
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            torn = True            # cannot be anything but the last write
    return rows, torn


def row_key_version(row: Mapping[str, Any]) -> int:
    return int(row.get("key_version") or 1)


def scan_shards(out_dir: Path) -> tuple[list[tuple[Path, list[dict]]], dict]:
    """``[(shard path, rows)]`` for every shard present, plus scan notes --
    READ-ONLY: a torn last line is reported (``torn``) and dropped from the
    rows, shards holding rows of another ``key_version`` are reported
    (``legacy``); ``truncate_torn`` / ``migrate_legacy`` do the writes,
    after the run has been admitted."""
    shards_dir = Path(out_dir) / "shards"
    notes: dict[str, Any] = {"torn": [], "shards": 0, "legacy": [], "legacy_rows": 0,
                             "key_version": KEY_VERSION}
    out: list[tuple[Path, list[dict]]] = []
    if not shards_dir.is_dir():
        return out, notes
    for path in sorted(shards_dir.glob("*.jsonl")):
        rows, torn = read_shard(path)
        if torn:
            notes["torn"].append(path.name)
        stale = sum(1 for r in rows if row_key_version(r) != KEY_VERSION)
        if stale:
            notes["legacy"].append(path.name)
            notes["legacy_rows"] += stale
        out.append((path, rows))
        notes["shards"] += 1
    return out, notes


def truncate_torn(out_dir: Path, names: Sequence[str]) -> None:
    for name in names:
        _truncate_torn(Path(out_dir) / "shards" / name)


def _append_rows(path: Path, rows: Sequence[Mapping[str, Any]], *, private: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600 if private else 0o644)
    try:
        if private:
            os.fchmod(fd, 0o600)
        for row in rows:
            _write_row(fd, row)
    finally:
        os.close(fd)


def migrate_legacy(out_dir: Path, existing: Sequence[tuple[Path, list[dict]]]) -> dict:
    """Move every shard holding rows of another ``key_version`` to
    ``shards/legacy-v<k>/`` (byte-identical, with a manifest) and carry its
    rows forward under the current scheme (module docstring): keys are
    re-derived from the original record; a row whose record does not
    validate, and a ``duplicate_state`` row whose twin does not own its new
    work key, are NOT carried (they are relabelled).  Returns a summary."""
    out_dir = Path(out_dir)
    legacy_shards = [(p, rows) for p, rows in existing
                     if any(row_key_version(r) != KEY_VERSION for r in rows)]
    summary: dict[str, Any] = {"shards": [], "carried": 0, "carried_duplicates": 0,
                               "relabel_invalid": 0, "relabel_misdedup": 0,
                               "relabel_unkeyed": 0, "rows": 0, "legacy_dirs": []}
    if not legacy_shards:
        return summary
    # owners under the NEW scheme: current rows first, then legacy rows
    owners: dict[str, str] = {}
    for _p, rows in existing:
        for row in rows:
            if row_key_version(row) == KEY_VERSION and row.get("work_key") \
                    and (row.get("label_refusal") or {}).get("reason") not in NON_OWNING:
                owners.setdefault(row["work_key"], row["record_sha256"])
    rekeyed: list[tuple[Path, dict, dict | None]] = []      # (shard, row, new keys)
    for path, rows in legacy_shards:
        for row in rows:
            record = {k: v for k, v in row.items() if k not in ROW_KEYS}
            keys = None
            try:
                validate_record(record)
                keys = {"state_key": state_key(record), "work_key": work_key(record),
                        "deal_key": record_deal_key(record)}
            except (SchemaError, KeyError, TypeError, ValueError, AttributeError):
                keys = None
            rekeyed.append((path, row, keys))
            if keys and (row.get("label_refusal") or {}).get("reason") not in NON_OWNING:
                owners.setdefault(keys["work_key"], row["record_sha256"])
    carried: dict[str, list[dict]] = {}
    privacy: dict[str, bool] = {}
    for path, row, keys in rekeyed:
        summary["rows"] += 1
        if keys is None:
            summary["relabel_invalid" if "seat" in row else "relabel_unkeyed"] += 1
            continue
        refusal = row.get("label_refusal") or {}
        if refusal.get("reason") == "invalid_record":
            summary["relabel_invalid"] += 1          # re-judged by the current validator
            continue
        if refusal.get("reason") == "duplicate_state":
            if owners.get(keys["work_key"]) != refusal.get("duplicate_of"):
                summary["relabel_misdedup"] += 1
                continue
            summary["carried_duplicates"] += 1
        new_row = {**row, **keys, "key_version": KEY_VERSION}
        if row_key_version(row) != KEY_VERSION:
            new_row["migrated_from"] = row_key_version(row)
        source = source_of_shard(path)
        carried.setdefault(source, []).append(new_row)
        privacy[source] = privacy.get(source, False) or ".private." in path.name
        summary["carried"] += 1
    # write the carried rows, then move the legacy shards aside (byte-identical)
    for source, rows in carried.items():
        suffix = ".private.jsonl" if privacy[source] else ".jsonl"
        _append_rows(out_dir / "shards" / f"{source}.migrated{suffix}", rows,
                     private=privacy[source])
    for path, rows in legacy_shards:
        version = min(row_key_version(r) for r in rows if row_key_version(r) != KEY_VERSION)
        legacy_dir = out_dir / "shards" / f"legacy-v{version}"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        target = legacy_dir / path.name
        n = 1
        while target.exists():
            target = legacy_dir / f"{path.stem}.{n}{path.suffix}"
            n += 1
        digest = sha256_file(path)
        size = path.stat().st_size
        os.replace(path, target)
        entry = {"name": target.name, "from": path.name, "sha256": digest, "bytes": size,
                 "rows": len(rows), "key_version": version, "private": ".private." in path.name}
        summary["shards"].append(entry)
        mpath = legacy_dir / "manifest.json"
        legacy_manifest = (json.loads(mpath.read_text()) if mpath.is_file()
                           else {"schema": MANIFEST_SCHEMA + "-legacy", "files": []})
        legacy_manifest["files"].append({**entry, "migrated_at": datetime.now(UTC).isoformat(),
                                         "migrated_to_key_version": KEY_VERSION})
        _atomic_write_text(mpath, json.dumps(legacy_manifest, indent=2, sort_keys=True) + "\n")
        if str(legacy_dir) not in summary["legacy_dirs"]:
            summary["legacy_dirs"].append(str(legacy_dir))
    return summary


def _truncate_torn(path: Path) -> None:
    """Cut a shard back to its last complete line."""
    data = path.read_bytes()
    keep = data.rfind(b"\n") + 1
    # drop trailing complete lines that do not parse either (defensive)
    lines = data[:keep].split(b"\n")
    good = 0
    for line in lines:
        if not line:
            continue
        try:
            json.loads(line)
        except ValueError:
            break
        good += len(line) + 1
    with open(path, "r+b") as fh:
        fh.truncate(good)


def source_of_shard(path: Path) -> str:
    return path.name.split(".", 1)[0]


# ----------------------------------------------------------------- workers

def _write_row(fd: int, row: Mapping[str, Any]) -> None:
    os.write(fd, (canonical_json(row) + "\n").encode("ascii"))


def _worker(args: tuple) -> dict:
    """One worker: its static share of the to-do records, appended to its
    own per-source shards.  Returns counts."""
    (worker, out_dir, tasks, scale, cap, code_sha, privacy) = args
    os.environ.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    fail_after = os.environ.get(FAIL_AFTER_ENV)
    fail_after = int(fail_after) if fail_after else None
    fds: dict[str, int] = {}
    counts: Counter = Counter()
    try:
        for source, line, duplicate_of in tasks:
            record = json.loads(line)
            row = label_record(record, scale=scale, cap=cap, code_sha=code_sha,
                               duplicate_of=duplicate_of)
            fd = fds.get(source)
            if fd is None:
                private = bool(privacy[source])
                path = shard_path(Path(out_dir), source, worker, private)
                path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                             0o600 if private else 0o644)
                if private:
                    os.fchmod(fd, 0o600)
                fds[source] = fd
            _write_row(fd, row)
            counts["rows"] += 1
            counts["labelled" if row["search_labels"] is not None else "refused"] += 1
            if duplicate_of is not None:
                counts["duplicates"] += 1
            if fail_after is not None and counts["rows"] >= fail_after:
                raise LabelError(f"injected failure after {fail_after} rows ({FAIL_AFTER_ENV})")
    finally:
        for fd in fds.values():
            os.close(fd)
    return {"worker": worker, **counts}


# ------------------------------------------------------------------- run

def read_input(path: Path) -> list[str]:
    with open(path, "rb") as fh:
        return [line.decode("ascii").rstrip("\n") for line in fh if line.strip()]


def _sha_of_line(line: str) -> str:
    # the hash sits at a fixed key; a full parse per line is affordable but
    # this keeps the scan of 34k highn rows cheap
    marker = '"record_sha256":"'
    i = line.find(marker)
    if i < 0:
        return json.loads(line)["record_sha256"]
    j = i + len(marker)
    return line[j:j + 64]


def check_resume(out_dir: Path, ident: dict, *, scale: int, cap: int | None,
                 allow_code_drift: bool, has_rows: bool, migrating: bool) -> dict | None:
    """READ-ONLY admission of ``out_dir`` for this run: the old ``run.json``
    (or None) once policy / scale / cap match and the code identity is
    acceptable (unchanged; or nothing labelled yet; or a key-version
    migration, whose carried rows keep their own ``code_sha``; or
    ``--allow-code-drift``)."""
    path = Path(out_dir) / "run.json"
    if not path.is_file():
        return None
    old = json.loads(path.read_text())
    if old.get("policy") != POLICY or int(old.get("scale", -1)) != int(scale) \
            or old.get("cap") != cap:
        raise LabelError(f"{path}: this directory labels policy {old.get('policy')!r} "
                         f"at scale {old.get('scale')} cap {old.get('cap')}; a "
                         f"{POLICY!r}/scale {scale}/cap {cap} run cannot resume it")
    drift = (old.get("code") or {}).get("source_tree_sha256") != ident["source_tree_sha256"]
    if drift and has_rows and not migrating and not allow_code_drift:
        raise LabelError(f"{path}: the source tree changed since this directory was "
                         "started (labels would mix code versions); pass "
                         "--allow-code-drift to continue anyway")
    return old


def _write_run(out_dir: Path, ident: dict, old: dict | None, *, scale: int, cap: int | None,
               migration: Mapping[str, Any] | None = None) -> dict:
    path = Path(out_dir) / "run.json"
    run = {"schema": RUN_SCHEMA, "policy": POLICY, "scale": int(scale), "cap": cap,
           "seed_recipe": SEED_RECIPE, "code": ident, "key_version": KEY_VERSION,
           "created_at": datetime.now(UTC).isoformat()}
    if old is not None:
        if (old.get("code") or {}).get("source_tree_sha256") != ident["source_tree_sha256"]:
            run["code_drift_from"] = old.get("code")
        run["created_at"] = old.get("created_at", run["created_at"])
        run["resumed_at"] = datetime.now(UTC).isoformat()
        if migration and migration.get("shards"):
            run["migrations"] = [*(old.get("migrations") or []),
                                 {"at": run["resumed_at"], "to_key_version": KEY_VERSION,
                                  **{k: v for k, v in migration.items() if k != "shards"},
                                  "shards": [s["from"] for s in migration["shards"]]}]
        elif old.get("migrations"):
            run["migrations"] = old["migrations"]
    _atomic_write_text(path, json.dumps(run, indent=2, sort_keys=True) + "\n")
    return run


def _wall_stats(values: Sequence[float]) -> dict:
    if not values:
        return {"n": 0, "mean_ms": None, "median_ms": None, "p90_ms": None, "total_ms": 0.0}
    vals = sorted(float(v) for v in values)
    return {"n": len(vals), "mean_ms": round(statistics.fmean(vals), 3),
            "median_ms": round(statistics.median(vals), 3),
            "p90_ms": round(vals[min(len(vals) - 1, int(0.9 * len(vals)))], 3),
            "total_ms": round(sum(vals), 3)}


def build_manifest(out_dir: Path, *, inputs: Mapping[str, Path], run: dict,
                   timings: Mapping[str, Any], argv: Sequence[str] | None,
                   input_rows: Mapping[str, int], merge: bool = True,
                   resume_notes: Mapping[str, Any] | None = None) -> dict:
    """Scan every shard, write the merged per-source files and ``manifest.json``."""
    out_dir = Path(out_dir)
    shards, notes = scan_shards(out_dir)
    if resume_notes:
        # the torn lines the run's opening scan dropped (this scan sees clean shards)
        notes["torn"] = sorted(set(notes["torn"]) | set(resume_notes.get("torn") or []))
    per_source: dict[str, dict] = {}
    rows_by_source: dict[str, dict[str, dict]] = {}
    duplicates: Counter = Counter()
    shard_rows: list[dict] = []
    for path, rows in shards:
        source = source_of_shard(path)
        bucket = rows_by_source.setdefault(source, {})
        for row in rows:
            sha = row["record_sha256"]
            if sha in bucket:
                duplicates[source] += 1
                continue
            bucket[sha] = row
        shard_rows.append({"path": f"shards/{path.name}", "sha256": sha256_file(path),
                           "bytes": path.stat().st_size, "rows": len(rows),
                           "source": source, "private": _is_private(path)})
    outputs: dict[str, dict] = {}
    for source in sorted(set(rows_by_source) | set(inputs)):
        bucket = rows_by_source.get(source, {})
        counts: dict[str, Any] = {
            "input_rows": int(input_rows.get(source, 0)) if source in input_rows else None,
            "rows": len(bucket), "labelled": 0, "searched": 0,
            "unsearched": Counter(), "refused": Counter(), "played_off_ballot": 0,
            "forced": 0, "failed_throw_prefix": 0, "record_ballot_differs": 0,
            "duplicate_state": 0, "duplicate_rows_dropped": int(duplicates.get(source, 0)),
        }
        dup_rows: list[dict] = []
        walls: list[float] = []
        walls_searched: list[float] = []
        deals: set[str] = set()
        for row in bucket.values():
            deck = row.get("deck")
            if isinstance(deck, list):
                deals.add(hashlib.sha256(canonical_json(deck).encode()).hexdigest()[:16])
            labels = row.get("search_labels")
            if labels is None:
                refusal = row.get("label_refusal") or {}
                counts["refused"][refusal.get("reason", "?")] += 1
                if refusal.get("reason") == "duplicate_state":
                    counts["duplicate_state"] += 1
                    dup_rows.append({"record_sha256": row["record_sha256"],
                                     "duplicate_of": refusal.get("duplicate_of"),
                                     "state_key": row.get("state_key"),
                                     "work_key": row.get("work_key")})
                continue
            counts["labelled"] += 1
            counts["forced"] += int(bool(labels.get("forced")))
            counts["failed_throw_prefix"] += int(bool(labels.get("failed_throw_prefix")))
            counts["record_ballot_differs"] += int(labels.get("record_ballot_matches") is False)
            walls.append(labels["wall_ms"])
            if labels["searched"]:
                counts["searched"] += 1
                walls_searched.append(labels["wall_ms"])
            else:
                counts["unsearched"][labels["reason"]] += 1
            if not labels["played_in_ballot"]:
                counts["played_off_ballot"] += 1
        counts["unsearched"] = dict(sorted(counts["unsearched"].items()))
        counts["refused"] = dict(sorted(counts["refused"].items()))
        counts["deals"] = len(deals)
        # None when this run did not read the source (its input count is unknown here)
        complete = (None if counts["input_rows"] is None
                    else counts["rows"] >= counts["input_rows"])
        entry: dict[str, Any] = {
            "input": None if source not in inputs else str(inputs[source]),
            "input_sha256": None if source not in inputs else sha256_file(inputs[source]),
            "counts": counts, "complete": complete,
            "wall": {"labelled": _wall_stats(walls), "searched": _wall_stats(walls_searched)},
            "duplicates": sorted(dup_rows, key=lambda d: d["record_sha256"]),
        }
        if merge and bucket:
            private = any(s["private"] for s in shard_rows if s["source"] == source)
            name = f"{source}.labels{'.private' if private else ''}.jsonl"
            ordered = list(bucket.values())
            if source in inputs:
                order = {_sha_of_line(line): i
                         for i, line in enumerate(read_input(inputs[source]))}
                ordered.sort(key=lambda r: order.get(r["record_sha256"], len(order)))
            merged = out_dir / name
            tmp = merged.with_name(f"{merged.name}.{os.getpid()}.tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
            digest = hashlib.sha256()
            with os.fdopen(fd, "wb") as fh:
                if private:
                    os.fchmod(fh.fileno(), 0o600)
                for row in ordered:
                    line = (canonical_json(row) + "\n").encode("ascii")
                    digest.update(line)
                    fh.write(line)
            os.replace(tmp, merged)
            outputs[name] = {"sha256": digest.hexdigest(), "records": len(ordered),
                             "bytes": merged.stat().st_size, "private": private,
                             "source": source, "complete": complete}
            entry["merged"] = name
        per_source[source] = entry
    totals = {
        "rows": sum(e["counts"]["rows"] for e in per_source.values()),
        "labelled": sum(e["counts"]["labelled"] for e in per_source.values()),
        "searched": sum(e["counts"]["searched"] for e in per_source.values()),
        "refused": sum(sum(e["counts"]["refused"].values()) for e in per_source.values()),
    }
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "labels_schema": LABELS_SCHEMA,
        "record_schema": SCHEMA,
        "created_at": datetime.now(UTC).isoformat(),
        "argv": list(argv) if argv is not None else None,
        "policy": POLICY, "scale": run["scale"], "cap": run["cap"],
        "work": {"n_worlds": 30 * int(run["scale"]), "report_worlds": 300 * int(run["scale"]),
                 "report_rule": "lcb"},
        "seed_recipe": SEED_RECIPE,
        "key_version": KEY_VERSION,
        "state_key": "sha256(KEY_VERSION, deck, canonical setup incl. declarations/burial/"
                     "passes, canonical plays_prefix, seat, decision_kind)[:32]",
        "work_key": "sha256(KEY_VERSION, state_key, sorted played action)[:32]; "
                    "duplicate_state dedups by work_key",
        "code": run["code"],
        "sources": per_source,
        "totals": totals,
        "notes": [HUMAN_NOTE,
                  "duplicate_state rows are exact twins (work_key: state + played action) of "
                  "a labelled row; "
                  "forced rows have one legal action and no search; failed_throw_prefix rows "
                  "carry a recorded submitted throw the engine replaced (prefix_engine_diffs)"],
        "shards": shard_rows,
        "outputs": outputs,
        "scan": notes,
        "timings": dict(timings),
    }
    _atomic_write_text(out_dir / "manifest.json",
                       json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def run(*, inputs: Mapping[str, Path], out_dir: str | os.PathLike, workers: int = 1,
        limit: int | None = None, scale: int = 1, cap: int | None = DEFAULT_CAP,
        allow_code_drift: bool = False, merge: bool = True,
        argv: Sequence[str] | None = None,
        log: Callable[[str], None] | None = print) -> dict:
    """Label ``inputs`` (source -> harvest file) into ``out_dir`` (module
    docstring), resuming whatever the directory already holds."""
    os.environ.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    say = log or (lambda _line: None)
    if int(scale) < 1:
        raise LabelError("--scale must be >= 1")
    if int(workers) < 1:
        raise LabelError("--workers must be >= 1")
    out = Path(out_dir)
    started = time.perf_counter()
    # ---- admission: nothing below this line touches the directory until
    # every input exists and the directory accepts this run
    for source, path in inputs.items():
        if source not in SOURCE_FILES:
            raise LabelError(f"unknown source {source!r}; one of {SOURCES}")
        if not Path(path).is_file():
            raise LabelError(f"{source}: input {path} missing")
    ident = code_identity()
    existing, notes = scan_shards(out)                       # read-only
    old_run = check_resume(out, ident, scale=int(scale), cap=cap,
                           allow_code_drift=allow_code_drift,
                           has_rows=any(rows for _p, rows in existing),
                           migrating=bool(notes["legacy"]))
    # ---- admitted: repair a torn line, migrate legacy shards, stamp run.json
    out.mkdir(parents=True, exist_ok=True)
    (out / "shards").mkdir(exist_ok=True)
    # legacy shards move aside byte-identical (a torn tail included); only a
    # shard that stays is cut back to its last complete line
    migration = migrate_legacy(out, existing)
    moved = {s["from"] for s in migration["shards"]}
    if notes["torn"]:
        truncate_torn(out, [n for n in notes["torn"] if n not in moved])
        say(f"resume: dropped a torn last line in {notes['torn']}")
    if migration["shards"]:
        say(f"migration: {len(migration['shards'])} legacy shard(s) ({migration['rows']} rows) "
            f"moved to {migration['legacy_dirs']}; carried {migration['carried']} "
            f"(of which {migration['carried_duplicates']} duplicates), relabelling "
            f"{migration['relabel_misdedup']} mis-deduped + {migration['relabel_invalid']} "
            f"invalid + {migration['relabel_unkeyed']} unkeyed")
        torn_names = list(notes["torn"])
        existing, notes = scan_shards(out)
        notes["torn"] = torn_names                # what this run found, moved or cut
    run_info = _write_run(out, ident, old_run, scale=int(scale), cap=cap, migration=migration)
    done: set[str] = set()
    claimed: dict[str, str] = {}          # work_key -> the record_sha256 that owns it
    for _path, rows in existing:
        for row in rows:
            done.add(row["record_sha256"])
            key = row.get("work_key")
            refusal = row.get("label_refusal") or {}
            if key and refusal.get("reason") not in NON_OWNING:
                claimed.setdefault(key, row["record_sha256"])
    say(f"resume: {len(done)} record(s) already labelled in {notes['shards']} shard(s)")
    tasks: list[tuple[str, str, str | None]] = []
    input_rows: dict[str, int] = {}
    privacy: dict[str, bool] = {}
    n_dup = 0
    for source, path in inputs.items():
        path = Path(path)
        lines = read_input(path)
        if limit is not None:
            lines = lines[:int(limit)]
        input_rows[source] = len(lines)
        privacy[source] = _is_private(path)
        todo: list[tuple[str, str, str | None]] = []
        for line in lines:
            sha = _sha_of_line(line)
            if sha in done:
                continue
            record = json.loads(line)
            try:
                # identity BEFORE any dedup bookkeeping: an invalid record
                # never owns a work key and is never a twin
                validate_record(record)
                key = work_key(record)
            except (SchemaError, KeyError, TypeError, ValueError, AttributeError):
                key = None                      # refused invalid_record by the worker
            twin = None if key is None else claimed.get(key)
            if twin is None and key is not None:
                claimed[key] = sha
            else:
                n_dup += 1
            todo.append((source, line, twin))
        say(f"{source}: {len(lines)} input row(s), {len(lines) - len(todo)} done, "
            f"{len(todo)} to do of which {sum(1 for t in todo if t[2])} duplicate_state "
            f"({'private' if privacy[source] else 'public'})")
        tasks.extend(todo)
    n_workers = max(1, min(int(workers), len(tasks))) if tasks else 1
    shares: list[list[tuple[str, str, str | None]]] = [[] for _ in range(n_workers)]
    for i, task in enumerate(tasks):
        shares[i % n_workers].append(task)
    args = [(w, str(out), share, int(scale), cap, ident["code_sha"], privacy)
            for w, share in enumerate(shares) if share]
    worker_reports: list[dict] = []
    failures: list[str] = []
    if args:
        say(f"labelling {len(tasks) - n_dup} record(s) (+{n_dup} duplicates) on {len(args)} "
            f"worker(s), scale {scale} (N{30 * int(scale)}/R{300 * int(scale)})")
    if len(args) == 1:
        try:
            worker_reports.append(_worker(args[0]))
        except LabelError as exc:
            failures.append(str(exc))
    elif args:
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=len(args)) as pool:
            pending = [pool.apply_async(_worker, (a,)) for a in args]
            last = time.perf_counter()
            while pending:
                still = []
                for fut in pending:
                    if fut.ready():
                        try:
                            worker_reports.append(fut.get())
                        except LabelError as exc:
                            failures.append(str(exc))
                    else:
                        still.append(fut)
                pending = still
                if pending:
                    time.sleep(0.5)
                    if time.perf_counter() - last >= PROGRESS_SECS:
                        last = time.perf_counter()
                        n_done = 0
                        for path in (out / "shards").glob("*.jsonl"):
                            with open(path, "rb") as fh:
                                n_done += sum(1 for _ in fh)
                        say(f"  progress: {n_done - len(done)}/{len(tasks)} "
                            f"({round(time.perf_counter() - started)}s)")
    wall = time.perf_counter() - started
    labelled_now = sum(int(r.get("rows", 0)) for r in worker_reports)
    timings = {
        "wall_secs": round(wall, 3), "workers": len(args), "records_this_run": labelled_now,
        "secs_per_record_this_run": (round(wall / labelled_now, 4) if labelled_now else None),
        "worker_reports": worker_reports, "failures": failures,
    }
    timings["migration"] = {k: v for k, v in migration.items() if k != "shards"}
    manifest = build_manifest(out, inputs={k: Path(v) for k, v in inputs.items()},
                              run=run_info, timings=timings, argv=argv,
                              input_rows=input_rows, merge=merge, resume_notes=notes)
    for source, entry in manifest["sources"].items():
        c = entry["counts"]
        say(f"{source}: rows={c['rows']}/{c['input_rows']} labelled={c['labelled']} "
            f"searched={c['searched']} unsearched={c['unsearched']} refused={c['refused']} "
            f"off_ballot={c['played_off_ballot']} "
            f"wall/searched median={entry['wall']['searched']['median_ms']}ms")
    say(f"manifest -> {out / 'manifest.json'} ({round(wall, 1)}s)")
    if failures:
        raise LabelError("; ".join(failures))
    return manifest


# ------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="label_harvest", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in-dir", type=Path, required=True,
                        help="harvest output directory (human.jsonl, "
                             "luna-rpc.private.jsonl, ...)")
    parser.add_argument("--out", type=Path, required=True, help="label directory")
    parser.add_argument("--sources", nargs="+", choices=SOURCES, default=list(DEFAULT_SOURCES),
                        metavar="SOURCE",
                        help=f"sources to label (default: {' '.join(DEFAULT_SOURCES)}; human "
                             "is contained in room-log and must be asked for explicitly)")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None,
                        help="label only the first N input rows of each source")
    parser.add_argument("--scale", type=int, default=1,
                        help="work multiplier: 1 = N30/R300 (production), 3 = N90/R900")
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP,
                        help=f"legal-set listing cap used for the check (default {DEFAULT_CAP})")
    parser.add_argument("--allow-code-drift", action="store_true",
                        help="continue a directory started under a different source tree")
    parser.add_argument("--no-merge", action="store_true",
                        help="skip the merged per-source files")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    inputs = {name: args.in_dir / SOURCE_FILES[name] for name in args.sources}
    try:
        run(inputs=inputs, out_dir=args.out, workers=args.workers, limit=args.limit,
            scale=args.scale, cap=args.cap, allow_code_drift=args.allow_code_drift,
            merge=not args.no_merge, argv=sys.argv if argv is None else ["label_harvest", *argv])
    except LabelError as exc:
        print(f"label_harvest: {exc}", file=sys.stderr, flush=True)
        return 2
    return 0


__all__ = [
    "BALLOT_SOURCE", "DEFAULT_SOURCES", "FAIL_AFTER_ENV", "HUMAN_NOTE", "KEY_VERSION",
    "LABELS_SCHEMA", "NON_OWNING", "ROW_KEYS", "MANIFEST_SCHEMA", "POLICY", "REFUSALS", "SEED_RECIPE",
    "SOURCES", "SOURCE_FILES", "UNSEARCHED", "LabelError", "LabelMixin", "LabelRefused",
    "build_manifest", "code_identity", "label_record", "label_seed", "make_label_bot",
    "check_resume", "migrate_legacy", "read_shard", "rebuild_for_label", "record_deal_key",
    "replay_checked", "row_key_version", "run", "scan_shards", "search_labels", "state_key",
    "truncate_torn", "work_key",
]
