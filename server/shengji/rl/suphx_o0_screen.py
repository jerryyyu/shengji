"""Frozen Suphx O0 oracle-acquisition screen.

The stdlib-only launcher refuses experimental environment switches before this
module is imported.  ``freeze`` creates the exact model seeds, causal training
deal identities and one-state-per-DEV-deal diagnostic population without
performing a learner update.  Training remains impossible until a separate
immutable review admission is published against the exact packet bytes.

O0 is deliberately not a strength or production experiment.  Its only claim
is whether three fixed full-information learners acquire a non-collapsed
ordinary-play signal relative to their own initial/public-only controls.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import platform
import random
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch

from ..ai.env import play_round
from ..ai.memory import Memory
from ..ai.smart import SmartBot
from ..engine.combos import decompose, pair_count
from ..engine.game import Game
from ..engine.legal import IllegalPlay
from ..engine.round import Round, Trick, actual_play_after
from .actions import enumerate_actions
from .douzero_micro import (BALLOT_SCHEMA, ROLE_NAMES, acting_team_return)
from .encode import ACT_DIM, encode_action
from .exact_resume import exact_resume_boundary_identity, state_digest
from .selfplay_contract import (CheckpointRef, load_verified, sha256_file)
from .suphx_actor import (clipped_attacker_bracket_return, derive_deal_seed,
                          load_actor, publish_initial_actor)
from .suphx_learning import (SuphxPolicyGradientUpdate, SuphxSchedule,
                             SuphxScheduledCollector, algorithm_sha256,
                             new_bundle, new_runner, resume_runner)
from .suphx_micro import (EXPERIMENT, PERFECT_DIM, apply_privilege_mask,
                          encode_feature_partition)
from .suphx_o0_preflight import verify_preflight
from .suphx_policy import (POLICY_SPEC, SuphxPolicyValue, new_from_scratch_model,
                           role_for, surface_for, surface_key)
from .synchronous_selfplay import _runner_contract_sha256


SCREEN_SCHEMA = "suphx-o0-fixed-ensemble-oracle-acquisition-v1"
SPEC_SCHEMA = "suphx-o0-frozen-spec-v1"
DEV_SCHEMA = "suphx-o0-frozen-dev-v1"
PACKET_SCHEMA = "suphx-o0-launch-packet-v1"
ADMISSION_SCHEMA = "suphx-o0-independent-review-admission-v1"
TRAIN_SCHEMA = "suphx-o0-training-manifest-v1"
TRAIN_LEDGER_SCHEMA = "suphx-o0-training-ledger-v1"
DEV_RESULT_SCHEMA = "suphx-o0-dev-result-v1"
DEV_ROW_SCHEMA = "suphx-o0-dev-round-v1"
GATE_SCHEMA = "suphx-o0-terminal-gate-v1"
PACKET_REVIEW_SCHEMA = "suphx-o0-packet-review-v1"
PACKET_REVIEW_MARKER = "SUPHX_O0_PACKET_REVIEW_V1 "

ARMS = ("oracle", "public")
KEEP_PROBABILITIES = {"oracle": 1.0, "public": 0.0}
ITERATIONS = 64
RESUME_BOUNDARY = 32
LEARNING_RATE = 1e-3
DEV_SEED0 = 160_100_000
DEV_DEALS = 128
ENTROPY_FLOOR = 0.35
ONE_SIDED_ALPHA = 0.05
# scipy.stats.t.ppf(.95, 127), frozen to avoid an undeclared SciPy runtime.
T_CRITICAL_DF127 = 1.6569403435420647
EXPECTED_SURFACES = tuple(POLICY_SPEC["surfaces"])
COMPARISONS = ("oracle_minus_initial", "oracle_minus_public", "same_model_null")
PREFLIGHT_SHA256 = (
    "4f0c3dd542634b66fd0826a8caef5dc21c7a8b083f96804d1f2f9bbe653ee434"
)
PREFLIGHT_RELATIVE_PATH = "server/runs/logs/suphx-o0-runtime-preflight-v1.json"
RUN_RELATIVE_ROOT = "server/runs/logs/suphx-o0-fixed-ensemble-v1"
# Current sequential evaluation namespaces (historical through C1/Teacher-v3,
# including sealed DEV/CALIB/REPORT assets) are all at or below this bound.
# O0's own DEV range ends exactly here.  Derived training deals must sit above
# the entire reserved interval, not merely avoid the 128 literal O0 DEV seeds.
CURRENT_RESERVED_DEAL_SEED_CEILING = DEV_SEED0 + DEV_DEALS - 1
SEED_IDENTITIES = (
    {
        "index": 0,
        "model_seed": 160_000_001,
        "learner_rng_seed": 160_010_001,
        "oracle_runner_root_seed": 160_020_001,
        "public_runner_root_seed": 160_021_001,
        "deal_stream_root_seed": 160_030_001,
    },
    {
        "index": 1,
        "model_seed": 160_000_002,
        "learner_rng_seed": 160_010_002,
        "oracle_runner_root_seed": 160_020_002,
        "public_runner_root_seed": 160_021_002,
        "deal_stream_root_seed": 160_030_002,
    },
    {
        "index": 2,
        "model_seed": 160_000_003,
        "learner_rng_seed": 160_010_003,
        "oracle_runner_root_seed": 160_020_003,
        "public_runner_root_seed": 160_021_003,
        "deal_stream_root_seed": 160_030_003,
    },
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SERVER_ROOT = _REPO_ROOT / "server"
# Mutable only as a test seam. Every executable artifact boundary below calls
# _require_run_root(), so reviewed production bytes have one namespace rather
# than an operator-selected directory that could alias another experiment.
EXPECTED_RUN_ROOT = (_REPO_ROOT / RUN_RELATIVE_ROOT).resolve()
_MATERIAL_RELATIVE_PATHS = (
    "docs_archive/SUPHX_MICRO_SPEC.md",
    "server/scripts/suphx_o0_screen.py",
    "server/shengji/rl/suphx_o0_screen.py",
    "server/shengji/rl/suphx_o0_preflight.py",
    "server/shengji/rl/suphx_micro.py",
    "server/shengji/rl/suphx_policy.py",
    "server/shengji/rl/suphx_actor.py",
    "server/shengji/rl/suphx_learning.py",
    "server/shengji/rl/actions.py",
    "server/shengji/rl/douzero_micro.py",
    "server/shengji/rl/encode.py",
    "server/shengji/rl/exact_resume.py",
    "server/shengji/rl/selfplay_contract.py",
    "server/shengji/rl/synchronous_selfplay.py",
    "server/shengji/ai/env.py",
    "server/shengji/ai/heuristic.py",
    "server/shengji/ai/mcbot.py",
    "server/shengji/ai/memory.py",
    "server/shengji/ai/smart.py",
    "server/shengji/engine/cards.py",
    "server/shengji/engine/combos.py",
    "server/shengji/engine/fast.py",
    "server/shengji/engine/game.py",
    "server/shengji/engine/legal.py",
    "server/shengji/engine/round.py",
)


class SuphxO0ScreenError(RuntimeError):
    """The frozen O0 evidence or authority boundary was violated."""


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def _partial(path: str | Path) -> Path:
    target = Path(os.path.abspath(os.fspath(path)))
    return target.with_name(f".{target.name}.partial")


def _require_regular_final(path: str | Path) -> Path:
    # Preserve the lexical final path so resolving a symlink cannot disguise
    # the fact that the named evidence artifact itself is a link.
    target = Path(os.path.abspath(os.fspath(path)))
    if target.is_symlink() or not target.is_file() or os.path.lexists(
            _partial(target)):
        raise SuphxO0ScreenError(
            f"artifact is absent, linked, or partial: {target}")
    return target


def _publish_bytes(path: str | Path, payload: bytes) -> CheckpointRef:
    target = Path(os.path.abspath(os.fspath(path)))
    partial = _partial(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(target) or os.path.lexists(partial):
        raise FileExistsError(f"refusing to overwrite {target} or {partial}")
    try:
        with partial.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(partial, target)
        ref = CheckpointRef.capture(target)
        if ref.sha256 != hashlib.sha256(payload).hexdigest() \
                or target.read_bytes() != payload:
            raise SuphxO0ScreenError("published artifact failed byte reopen")
        partial.unlink()
        _require_regular_final(target)
        ref.verify()
        return ref
    except BaseException:
        # Preserve any linked final/partial as terminal failure evidence.
        raise


def _publish_json(path: str | Path, value: object) -> CheckpointRef:
    return _publish_bytes(path, _canonical_json(value))


def _load_json(ref: CheckpointRef) -> Any:
    _require_regular_final(ref.path)
    return load_verified(
        ref, lambda path: json.loads(Path(path).read_text()))


def _ref(value: object, *, label: str) -> CheckpointRef:
    if not isinstance(value, Mapping) or set(value) != {"path", "sha256"}:
        raise SuphxO0ScreenError(f"{label} reference fields mismatch")
    ref = CheckpointRef(str(value["path"]), str(value["sha256"]))
    _require_regular_final(ref.path)
    ref.verify()
    return ref


class _ExclusiveJsonl:
    def __init__(self, path: str | Path):
        self.target = Path(os.path.abspath(os.fspath(path)))
        self.partial = _partial(self.target)
        self.target.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(self.target) or os.path.lexists(self.partial):
            raise FileExistsError(
                f"refusing to overwrite {self.target} or {self.partial}")
        self.handle = self.partial.open("xb")
        self.count = 0

    def write(self, value: object) -> None:
        self.handle.write(_canonical_json(value))
        self.count += 1

    def publish(self) -> CheckpointRef:
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.handle.close()
        expected = sha256_file(self.partial)
        os.link(self.partial, self.target)
        ref = CheckpointRef.capture(self.target)
        if ref.sha256 != expected:
            raise SuphxO0ScreenError("published JSONL failed byte reopen")
        ref.verify()
        self.partial.unlink()
        _require_regular_final(self.target)
        ref.verify()
        return ref

    def abandon(self) -> None:
        if not self.handle.closed:
            self.handle.flush()
            os.fsync(self.handle.fileno())
            self.handle.close()


def _load_jsonl(ref: CheckpointRef) -> list[Any]:
    _require_regular_final(ref.path)

    def load(path: str) -> list[Any]:
        with open(path) as handle:
            return [json.loads(line) for line in handle if line.strip()]

    return load_verified(ref, load)


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=_REPO_ROOT, check=check,
        capture_output=True, text=True)


def _material_status() -> str:
    return _git(
        "status", "--porcelain", "--untracked-files=all", "--",
        *_MATERIAL_RELATIVE_PATHS,
    ).stdout.strip()


def source_identity() -> dict[str, Any]:
    from ..engine import fast

    compiled = getattr(fast, "_fast", None)
    compiled_path = getattr(compiled, "__file__", None)
    if not fast.HAVE_FAST or not compiled_path:
        raise SuphxO0ScreenError("compiled engine binary is unavailable")
    files = {
        path: sha256_file(_REPO_ROOT / path)
        for path in _MATERIAL_RELATIVE_PATHS
    }
    files["compiled_engine"] = sha256_file(Path(compiled_path))
    return {"schema": "suphx-o0-material-source-identity-v1", "files": files}


def runtime_identity() -> dict[str, Any]:
    from ..engine import combos, fast

    if os.environ.get("SHENGJI_FAST") != "1" \
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise SuphxO0ScreenError("compiled strict environment is not active")
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise SuphxO0ScreenError("compiled engine routing is not active")
    dirty = _material_status()
    if dirty:
        raise SuphxO0ScreenError(
            "material O0 source paths are dirty: " + dirty)
    if not torch.are_deterministic_algorithms_enabled() \
            or torch.is_deterministic_algorithms_warn_only_enabled():
        raise SuphxO0ScreenError("strict deterministic Torch is not active")
    return {
        "schema": "suphx-o0-runtime-v1",
        "git": _git("rev-parse", "HEAD").stdout.strip(),
        "material_tree_clean": True,
        "host": platform.node(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "torch": torch.__version__,
        "torch_threads": torch.get_num_threads(),
        "torch_interop_threads": torch.get_num_interop_threads(),
        "fast_engine": True,
        "strict_voids": True,
        "deterministic_algorithms": True,
        "deterministic_warn_only": False,
        "source_identity": source_identity(),
    }


def _runtime_compatibility_problems(producer: object) -> list[str]:
    if not isinstance(producer, Mapping):
        return ["packet runtime is not an object"]
    try:
        current = runtime_identity()
    except (OSError, subprocess.SubprocessError, SuphxO0ScreenError) as exc:
        return [f"current runtime refused: {exc}"]
    problems = []
    producer_git = producer.get("git")
    if not isinstance(producer_git, str) or len(producer_git) != 40:
        problems.append("packet producer git identity")
    else:
        if _git(
                "merge-base", "--is-ancestor", producer_git,
                current["git"], check=False).returncode:
            problems.append("packet producer git is not an ancestor")
        changed = _git(
            "diff", "--name-only", f"{producer_git}..{current['git']}",
            "--", *_MATERIAL_RELATIVE_PATHS,
        ).stdout.strip()
        if changed:
            problems.append("packet material paths changed since freeze")
    for key in (
        "schema", "material_tree_clean", "host", "machine", "python",
        "numpy", "torch", "torch_threads", "torch_interop_threads",
        "fast_engine", "strict_voids", "deterministic_algorithms",
        "deterministic_warn_only", "source_identity",
    ):
        if producer.get(key) != current.get(key):
            problems.append(f"packet runtime {key} drift")
    return sorted(set(problems))


def _seed_identity(index: int) -> dict[str, int]:
    if isinstance(index, bool) or not isinstance(index, int) \
            or index not in range(len(SEED_IDENTITIES)):
        raise SuphxO0ScreenError("seed index must be 0, 1, or 2")
    return dict(SEED_IDENTITIES[index])


def _runner_seed(identity: Mapping[str, int], arm: str) -> int:
    if arm not in ARMS:
        raise SuphxO0ScreenError(f"unsupported O0 arm {arm!r}")
    return int(identity[f"{arm}_runner_root_seed"])


def _named_seed(*parts: object) -> int:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def _trick_payload(trick: Trick | None) -> object:
    if trick is None:
        return None
    return {
        "leader": trick.leader,
        "plays": [
            {"seat": play.seat, "cards": list(play.cards)}
            for play in trick.plays
        ],
        "winner": trick.winner,
        "points": trick.points,
    }


def _round_payload(rnd: Round, seat: int) -> dict[str, Any]:
    return {
        "seat": seat,
        "deck": list(rnd.deck),
        "deal_pos": rnd._deal_pos,
        "hands": [list(hand) for hand in rnd.hands],
        "kitty": list(rnd.kitty),
        "trump_rank": rnd.trump_rank,
        "banker": rnd.banker,
        "first_round": rnd.first_round,
        "phase": rnd.phase,
        "turn": rnd.turn,
        "declaration": copy.deepcopy(rnd.declaration),
        "passed": sorted(rnd.passed),
        "trump_suit": rnd.trump_suit,
        "trump_is_nt": rnd.trump_is_nt,
        "buried": list(rnd.buried),
        "trick": _trick_payload(rnd.trick),
        "last_trick": _trick_payload(rnd.last_trick),
        "history": [_trick_payload(trick) for trick in rnd.history],
        "attacker_points": rnd.attacker_points,
        "kitty_bonus": rnd.kitty_bonus,
        "last_trick_winner": rnd.last_trick_winner,
    }


def _remaining_multiset(rnd: Round) -> Counter[str]:
    cards = [card for hand in rnd.hands for card in hand]
    cards.extend(rnd.buried)
    return Counter(cards)


def _chronological_world_problems(
        original: Round, changed: Round) -> list[str]:
    """Replay every public play against an alternative hidden allocation.

    Snapshot-only void/pair/run caps are necessary but insufficient. Moving a
    remaining card can give a player a pair or throw-beating component that
    they would already have been obliged to expose earlier in the round.
    Rebuild each post-burial hand, then drive the real ``Round.play`` boundary
    at every historical information set.
    """
    if original.phase != "play" or changed.phase != "play" \
            or original.banker not in range(4) \
            or original.ordering is None or changed.ordering is None \
            or original.trick is None or changed.trick is None:
        return ["chronological replay requires a live play state"]

    public_tricks = list(original.history)
    if any(len(trick.plays) != 4 for trick in public_tricks):
        return ["chronological replay found an incomplete resolved trick"]
    current = original.trick
    if len(current.plays) >= 4:
        return ["chronological replay found a resolved current trick"]

    played_by: list[list[str]] = [[] for _ in range(4)]
    for trick in (*public_tricks, current):
        for play in trick.plays:
            if play.seat not in range(4):
                return ["chronological replay found an invalid public seat"]
            played_by[play.seat].extend(play.cards)

    replay = copy.deepcopy(changed)
    replay.hands = [
        list(changed.hands[seat]) + played_by[seat]
        for seat in range(4)
    ]
    if any(len(hand) != 25 for hand in replay.hands):
        return ["chronological replay did not reconstruct four 25-card hands"]
    reconstructed = Counter(
        card for hand in replay.hands for card in hand)
    reconstructed.update(changed.buried)
    if reconstructed != Counter(original.deck):
        return ["chronological replay does not conserve the dealt deck"]

    replay.phase = "play"
    replay.turn = original.banker
    replay.trick = Trick(leader=original.banker)
    replay.last_trick = None
    replay.history = []
    replay.attacker_points = 0
    replay.kitty_bonus = 0
    replay.last_trick_winner = None
    replay.message = None
    # Never inherit the rollout-only validation bypass into an evidence gate.
    replay._trusted_rollout = False

    for trick_index, expected in enumerate((*public_tricks, current)):
        if replay.trick is None or replay.trick.leader != expected.leader:
            actual_leader = None if replay.trick is None \
                else replay.trick.leader
            return [
                f"chronological trick {trick_index} leader drift: "
                f"expected {expected.leader}, got {actual_leader}"
            ]
        for play_index, public_play in enumerate(expected.plays):
            previous_last = replay.last_trick
            try:
                replay.play(public_play.seat, list(public_play.cards))
            except (IllegalPlay, AssertionError, ValueError) as exc:
                return [
                    f"chronological trick {trick_index} play {play_index} "
                    f"seat {public_play.seat} is illegal: {exc}"
                ]
            actual = actual_play_after(
                replay, public_play.seat, previous_last)
            if actual != public_play.cards:
                detail = f": {replay.message}" if replay.message else ""
                return [
                    f"chronological trick {trick_index} play {play_index} "
                    f"seat {public_play.seat} changed from "
                    f"{public_play.cards!r} to {actual!r}{detail}"
                ]
        if trick_index < len(public_tricks):
            if replay.last_trick is None \
                    or _trick_payload(replay.last_trick) \
                    != _trick_payload(expected):
                return [
                    f"chronological trick {trick_index} resolution drift"
                ]

    if _trick_payload(replay.trick) != _trick_payload(current):
        return ["chronological current-trick replay drift"]
    if replay.turn != original.turn:
        return [
            f"chronological turn drift: expected {original.turn}, "
            f"got {replay.turn}"
        ]
    if any(Counter(replay.hands[seat]) != Counter(changed.hands[seat])
           for seat in range(4)):
        return ["chronological replay did not recover remaining hands"]
    if replay.attacker_points != original.attacker_points:
        return ["chronological attacker-points drift"]
    return []


def information_set_world_problems(
        original: Round, changed: Round, seat: int) -> list[str]:
    """Validate a reachable hidden allocation against public obligations.

    This is intentionally stricter than checking encoder equality.  A tensor
    can be public-invariant even when its hidden allocation contradicts a
    demonstrated void, pair obligation, tractor obligation, declaration, or
    card conservation.  Such an impossible world cannot prove oracle use.
    """
    if not isinstance(original, Round) or not isinstance(changed, Round) \
            or seat not in range(4) or original.ordering is None:
        return ["world validator requires play rounds and a valid seat"]
    problems = []
    public_fields = (
        "trump_rank", "banker", "first_round", "phase", "turn",
        "declaration", "passed", "trump_suit", "trump_is_nt", "trick",
        "last_trick", "history", "attacker_points", "kitty_bonus",
        "last_trick_winner",
    )
    for name in public_fields:
        if getattr(original, name) != getattr(changed, name):
            problems.append(f"public field changed: {name}")
    if changed.ordering is None \
            or vars(original.ordering) != vars(changed.ordering):
        problems.append("ordering changed")
    if original.hands[seat] != changed.hands[seat]:
        problems.append("actor hand changed")
    if [len(hand) for hand in original.hands] != [
            len(hand) for hand in changed.hands]:
        problems.append("remaining hand sizes changed")
    if len(original.buried) != len(changed.buried):
        problems.append("burial size changed")
    if original.banker == seat and original.buried != changed.buried:
        problems.append("banker legal-private burial changed")
    if _remaining_multiset(original) != _remaining_multiset(changed):
        problems.append("remaining-card conservation changed")
    if original.deck != changed.deck or original.kitty != changed.kitty \
            or original._deal_pos != changed._deal_pos:
        problems.append("fixed deal identity changed")
    if problems:
        return sorted(set(problems))

    memory = Memory(original, seat, own_kitty=True)
    ordering = original.ordering
    hidden_seats = [other for other in range(4) if other != seat]
    for other in hidden_seats:
        by_suit: dict[str, list[str]] = defaultdict(list)
        for card in changed.hands[other]:
            by_suit[ordering.eff_suit(card)].append(card)
        for eff_suit in memory.voids[other]:
            if by_suit.get(eff_suit):
                problems.append(
                    f"seat {other} holds demonstrated-void suit {eff_suit}")
        for eff_suit, cards in by_suit.items():
            cap = memory.max_pairs(other, eff_suit)
            if cap is not None and pair_count(cards) > cap:
                problems.append(
                    f"seat {other} exceeds pair cap in {eff_suit}")
            run_cap = memory.max_run(other, eff_suit)
            if run_cap is not None \
                    and decompose(cards, ordering).max_pair_run() > run_cap:
                problems.append(
                    f"seat {other} exceeds tractor-run cap in {eff_suit}")

    declaration = original.declaration
    if isinstance(declaration, Mapping) \
            and declaration.get("seat") in hidden_seats:
        declarer = int(declaration["seat"])
        shown = Counter(declaration.get("cards", []))
        played = memory.played_by[declarer]
        for card, count in shown.items():
            remaining = count - played[card]
            if remaining <= 0:
                continue
            possible = Counter(changed.hands[declarer])
            # A declaring banker may legally bury a shown card.  A non-banker
            # declarer has no path from its hand into the hidden burial.
            if declarer == original.banker and seat != original.banker:
                possible += Counter(changed.buried)
            if possible[card] < remaining:
                problems.append(
                    f"unplayed declaration card {card} left declarer/burial")
    if not problems:
        problems.extend(_chronological_world_problems(original, changed))
    return sorted(set(problems))


def _legal_hidden_hand_neighbor(rnd: Round, seat: int) -> Round:
    hidden = [other for other in range(4) if other != seat]
    for left_offset, left in enumerate(hidden):
        for right in hidden[left_offset + 1:]:
            for left_i, left_card in enumerate(rnd.hands[left]):
                for right_i, right_card in enumerate(rnd.hands[right]):
                    if left_card == right_card:
                        continue
                    changed = copy.deepcopy(rnd)
                    changed.hands[left][left_i], changed.hands[right][right_i] = (
                        changed.hands[right][right_i],
                        changed.hands[left][left_i],
                    )
                    if information_set_world_problems(rnd, changed, seat):
                        continue
                    before = encode_feature_partition(rnd, seat)
                    after = encode_feature_partition(changed, seat)
                    if not np.array_equal(before["perfect"], after["perfect"]):
                        return changed
    raise SuphxO0ScreenError(
        "DEV state lacks a legal hidden-hand ownership neighbor")


def _legal_hidden_burial_neighbor(rnd: Round, seat: int) -> Round:
    if seat == rnd.banker:
        raise SuphxO0ScreenError(
            "banker burial is legal-private, not a hidden witness")
    for other in range(4):
        if other == seat:
            continue
        for hand_i, hand_card in enumerate(rnd.hands[other]):
            for bury_i, buried_card in enumerate(rnd.buried):
                if hand_card == buried_card:
                    continue
                changed = copy.deepcopy(rnd)
                changed.hands[other][hand_i], changed.buried[bury_i] = (
                    changed.buried[bury_i], changed.hands[other][hand_i])
                if information_set_world_problems(rnd, changed, seat):
                    continue
                before = encode_feature_partition(rnd, seat)
                after = encode_feature_partition(changed, seat)
                if not np.array_equal(before["perfect"], after["perfect"]):
                    return changed
    raise SuphxO0ScreenError(
        "DEV non-banker state lacks a legal hidden-burial neighbor")


@dataclass
class _CapturedDecision:
    rnd: Round
    seat: int
    surface: str
    ballot: tuple[tuple[str, ...], ...]
    ordinal: int


class _CaptureSmart:
    def __init__(self, records: list[_CapturedDecision]):
        self.control = SmartBot()
        self.records = records

    def decide_declare(self, rnd, seat, final=False):
        return self.control.decide_declare(rnd, seat, final=final)

    def decide_bury(self, rnd, seat):
        return self.control.decide_bury(rnd, seat)

    def decide_play(self, rnd, seat):
        actions = enumerate_actions(
            rnd, seat, exhaustive_follows=False, include_throws=False)
        if len(actions) > 1:
            self.records.append(_CapturedDecision(
                rnd=copy.deepcopy(rnd),
                seat=seat,
                surface=surface_key(role_for(rnd, seat), surface_for(rnd)),
                ballot=tuple(tuple(action) for action in actions),
                ordinal=len(self.records),
            ))
        return self.control.decide_play(rnd, seat)


def _capture_dev_state(deal_seed: int, deal_index: int) \
        -> tuple[dict[str, Any], _CapturedDecision]:
    if deal_seed != DEV_SEED0 + deal_index \
            or deal_index not in range(DEV_DEALS):
        raise SuphxO0ScreenError("DEV deal identity is outside frozen range")
    records: list[_CapturedDecision] = []
    game = Game(random.Random(deal_seed))
    log = play_round(game, [_CaptureSmart(records) for _ in range(4)])
    target_surface = EXPECTED_SURFACES[deal_index % len(EXPECTED_SURFACES)]
    eligible = [record for record in records if record.surface == target_surface]
    if not eligible:
        raise SuphxO0ScreenError(
            f"DEV deal {deal_seed} lacks target surface {target_surface}")
    witnessed = []
    for record in eligible:
        try:
            hand_neighbor = _legal_hidden_hand_neighbor(record.rnd, record.seat)
        except SuphxO0ScreenError:
            continue
        burial_neighbor = None
        if record.seat != record.rnd.banker:
            try:
                burial_neighbor = _legal_hidden_burial_neighbor(
                    record.rnd, record.seat)
            except SuphxO0ScreenError:
                pass
        witnessed.append((record, hand_neighbor, burial_neighbor))
    if not witnessed:
        raise SuphxO0ScreenError(
            f"DEV deal {deal_seed} lacks a legal hidden-world witness for "
            f"{target_surface}")
    # Prefer a state that also supplies the non-banker hidden-burial challenge;
    # fall back only when this deal/surface has none.  The full DEV freezer
    # separately requires burial witnesses in every role/surface stratum.
    with_burial = [item for item in witnessed if item[2] is not None]
    selection_pool = with_burial or witnessed
    selected_index = _named_seed(
        "suphx-o0-dev-state", deal_seed, target_surface) % len(selection_pool)
    selected, hand_neighbor, burial_neighbor = selection_pool[selected_index]
    role = role_for(selected.rnd, selected.seat)
    target = acting_team_return(
        clipped_attacker_bracket_return(log.attacker_points), role)
    entry = {
        "deal_index": deal_index,
        "deal_seed": deal_seed,
        "target_surface": target_surface,
        "eligible_surface_states": len(eligible),
        "legal_hand_witness_states": len(witnessed),
        "legal_burial_witness_states": len(with_burial),
        "selected_witness_pool_ordinal": selected_index,
        "selected_global_ordinal": selected.ordinal,
        "seat": selected.seat,
        "role": ROLE_NAMES[role],
        "surface": selected.surface,
        "ballot_schema": BALLOT_SCHEMA,
        "ballot_sha256": state_digest(selected.ballot),
        "state_sha256": state_digest(_round_payload(
            selected.rnd, selected.seat)),
        "legal_hidden_hand_neighbor_sha256": state_digest(_round_payload(
            hand_neighbor, selected.seat)),
        "legal_hidden_burial_neighbor_sha256": (
            None if burial_neighbor is None else state_digest(_round_payload(
                burial_neighbor, selected.seat))
        ),
        "target": float(target),
    }
    return entry, selected


def _dev_payload(*, progress: bool = False) -> dict[str, Any]:
    entries = []
    counts: Counter[str] = Counter()
    burial_counts: Counter[str] = Counter()
    for index in range(DEV_DEALS):
        entry, _ = _capture_dev_state(DEV_SEED0 + index, index)
        entries.append(entry)
        counts[entry["surface"]] += 1
        if entry["legal_hidden_burial_neighbor_sha256"] is not None:
            burial_counts[entry["surface"]] += 1
        if progress and ((index + 1) % 16 == 0 or index + 1 == DEV_DEALS):
            print(
                f"PROGRESS O0 DEV asset {index + 1}/{DEV_DEALS}",
                flush=True)
    expected_counts = {
        surface: DEV_DEALS // len(EXPECTED_SURFACES)
        for surface in EXPECTED_SURFACES
    }
    if dict(counts) != expected_counts:
        raise SuphxO0ScreenError(
            f"DEV surface stratification drift: {dict(counts)}")
    if set(burial_counts) != set(EXPECTED_SURFACES) \
            or any(burial_counts[surface] <= 0
                   for surface in EXPECTED_SURFACES):
        raise SuphxO0ScreenError(
            f"DEV hidden-burial surface coverage drift: {dict(burial_counts)}")
    return {
        "schema": DEV_SCHEMA,
        "claim": "one frozen SmartBot state and terminal target per DEV deal",
        "seed0": DEV_SEED0,
        "deals": DEV_DEALS,
        "deal_seeds": list(range(DEV_SEED0, DEV_SEED0 + DEV_DEALS)),
        "selector": (
            "cyclic role/surface target; SHA256-derived ordinal among exact "
            "multi-action SmartBot states"
        ),
        "surface_counts": expected_counts,
        "hidden_burial_witness_surface_counts": {
            surface: burial_counts[surface] for surface in EXPECTED_SURFACES},
        "entries": entries,
        "training_use": False,
        "o1_schedule_selection": False,
        "production_use": False,
    }


def _validate_dev_payload_identity(payload: object) -> dict[str, Any]:
    expected_fields = {
        "schema", "claim", "seed0", "deals", "deal_seeds", "selector",
        "surface_counts", "hidden_burial_witness_surface_counts", "entries",
        "training_use", "o1_schedule_selection", "production_use",
    }
    expected_counts = {
        surface: DEV_DEALS // len(EXPECTED_SURFACES)
        for surface in EXPECTED_SURFACES
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_fields \
            or payload.get("schema") != DEV_SCHEMA \
            or payload.get("seed0") != DEV_SEED0 \
            or payload.get("deals") != DEV_DEALS \
            or payload.get("deal_seeds") \
            != list(range(DEV_SEED0, DEV_SEED0 + DEV_DEALS)) \
            or payload.get("surface_counts") != expected_counts \
            or not isinstance(payload.get("entries"), list) \
            or len(payload["entries"]) != DEV_DEALS \
            or any(payload.get(name) is not False for name in (
                "training_use", "o1_schedule_selection", "production_use")):
        raise SuphxO0ScreenError("frozen O0 DEV identity drift")
    burial_counts = payload.get("hidden_burial_witness_surface_counts")
    if not isinstance(burial_counts, Mapping) \
            or set(burial_counts) != set(EXPECTED_SURFACES) \
            or any(isinstance(burial_counts[surface], bool)
                   or not isinstance(burial_counts[surface], int)
                   or burial_counts[surface] <= 0
                   for surface in EXPECTED_SURFACES):
        raise SuphxO0ScreenError("frozen O0 DEV burial coverage drift")
    return dict(payload)


def _deal_collision_proof() -> dict[str, Any]:
    by_seed: dict[str, list[int]] = {}
    owners: dict[int, str] = {}
    for identity in SEED_IDENTITIES:
        index = int(identity["index"])
        deals = [
            derive_deal_seed(
                int(identity["deal_stream_root_seed"]), sequence, 0)
            for sequence in range(ITERATIONS)
        ]
        if len(set(deals)) != ITERATIONS:
            raise SuphxO0ScreenError("within-seed causal deal collision")
        for deal in deals:
            if deal in owners:
                raise SuphxO0ScreenError(
                    f"between-seed causal deal collision with {owners[deal]}")
            owners[deal] = f"seed_{index}"
        by_seed[str(index)] = deals
    dev = set(range(DEV_SEED0, DEV_SEED0 + DEV_DEALS))
    overlap = sorted(dev & set(owners))
    if overlap:
        raise SuphxO0ScreenError("training and DEV deal identities collide")
    reserved_overlap = sorted(
        deal for deal in owners
        if 0 <= deal <= CURRENT_RESERVED_DEAL_SEED_CEILING)
    if reserved_overlap:
        raise SuphxO0ScreenError(
            "derived training deals overlap the reserved evidence namespace")
    return {
        "schema": "suphx-o0-deal-collision-proof-v1",
        "training_deals_by_seed": by_seed,
        "training_deal_digest_by_seed": {
            key: state_digest(value) for key, value in by_seed.items()},
        "training_deals_total": len(owners),
        "dev_deals": sorted(dev),
        "dev_deal_digest": state_digest(sorted(dev)),
        "within_seed_collisions": 0,
        "between_seed_collisions": 0,
        "training_dev_collisions": 0,
        "reserved_sequential_evidence_namespace": {
            "inclusive_lo": 0,
            "inclusive_hi": CURRENT_RESERVED_DEAL_SEED_CEILING,
            "covers": (
                "all registered historical through C1/Teacher-v3 sequential "
                "DEV/CALIB/REPORT deal ranges plus O0 DEV"
            ),
        },
        "training_reserved_namespace_collisions": 0,
        "oracle_public_share_deals_within_seed": True,
    }


def _spec_payload() -> dict[str, Any]:
    return {
        "schema": SPEC_SCHEMA,
        "screen_schema": SCREEN_SCHEMA,
        "artifact_root": RUN_RELATIVE_ROOT,
        "claim": (
            "oracle acquisition for one exact fixed three-seed ensemble; "
            "not recipe-level, strength, O1, or production evidence"
        ),
        "fixed_ensemble": [dict(value) for value in SEED_IDENTITIES],
        "training": {
            "arms": [
                {"name": arm, "keep_probability": KEEP_PROBABILITIES[arm]}
                for arm in ARMS
            ],
            "iterations_per_arm": ITERATIONS,
            "rounds_per_iteration": 1,
            "updates_per_iteration": 1,
            "learning_rate": LEARNING_RATE,
            "resume_boundary": RESUME_BOUNDARY,
            "initial_weights_equal_within_seed": True,
            "shared_actor_independent_deals_within_seed": True,
            "domain_separated_runner_mask_action_streams": True,
            "actor_refresh": "after_every_completed_iteration",
            "terminal_candidate_adopted": True,
        },
        "dev": {
            "seed0": DEV_SEED0,
            "deals": DEV_DEALS,
            "one_state_per_deal": True,
            "flips": [0, 1],
            "ordinary_policy": "deterministic greedy",
            "ballot_schema": BALLOT_SCHEMA,
            "declaration": "SmartBot",
            "burial": "SmartBot",
            "hidden_world_validation": (
                "full chronological Round.play replay including follow-shape "
                "and successful-throw legality"
            ),
        },
        "primary_comparisons": [
            "oracle terminal minus exact gamma=1 initial",
            "oracle terminal minus equal-seed public terminal",
        ],
        "null": "same model, both team flips, exact zero per deal and seed",
        "inference": {
            "unit": "DEV deal cluster after averaging two flips and 3 seeds",
            "one_sided_alpha_each": ONE_SIDED_ALPHA,
            "family_alpha_max": 0.10,
            "distribution": "Student t",
            "df": DEV_DEALS - 1,
            "critical_value": T_CRITICAL_DF127,
            "both_primary_lcbs_gt": 0.0,
            "every_seed_primary_mean_gt": 0.0,
        },
        "health": {
            "exact_work_provenance_resume": True,
            "all_four_surfaces_every_seed_arm": True,
            "median_normalized_entropy_floor": ENTROPY_FLOOR,
            "oracle_legal_hidden_hand_and_burial_logit_witness_every_surface":
                True,
            "public_legal_hidden_hand_and_burial_exact_invariance": True,
            "finite_model_and_controller": True,
        },
        "authority": {
            "pass": "freeze and independently review O1 only",
            "failure": "SELECT NONE; no extension or tuning",
            "strength": False,
            "production": False,
        },
    }


def _preflight_ref() -> CheckpointRef:
    path = _REPO_ROOT / PREFLIGHT_RELATIVE_PATH
    ref = CheckpointRef.capture(_require_regular_final(path))
    if ref.sha256 != PREFLIGHT_SHA256:
        raise SuphxO0ScreenError("runtime preflight SHA-256 drift")
    payload = verify_preflight(path)
    if payload.get("passed") is not True \
            or payload.get("dose_recommendation", {}).get(
                "iterations_per_arm") != ITERATIONS \
            or any(payload.get(name) is not False for name in (
                "o0_launch_authorized", "o1_authorized",
                "training_authorized", "production_promotion")):
        raise SuphxO0ScreenError("runtime preflight authority/dose drift")
    ref.verify()
    return ref


def _initial_manifest_path(root: Path, index: int) -> Path:
    return root / "initial" / f"seed_{index}.json"


def _packet_path(root: Path) -> Path:
    return root / "launch_packet.json"


def _require_run_root(root: str | Path) -> Path:
    resolved = Path(root).resolve()
    expected = Path(EXPECTED_RUN_ROOT).resolve()
    if resolved != expected:
        raise SuphxO0ScreenError(
            "O0 artifact root is not the exact predeclared namespace: "
            f"expected {expected}, got {resolved}")
    return resolved


def _artifact_names_payload() -> dict[str, str]:
    return {
        "admission": "review_admission.json",
        "review_copy": "review_record.txt",
        "training": "train/seed_{index}_{arm}.json",
        "training_ledger": "train/seed_{index}_{arm}.jsonl",
        "dev_result": "dev/seed_{index}.json",
        "dev_rows": "dev/seed_{index}.jsonl",
        "gate": "gate.json",
    }


def _packet_review_claim(
        review_bytes: bytes, packet_ref: CheckpointRef) -> dict[str, Any]:
    try:
        review_text = review_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SuphxO0ScreenError(
            "independent-review record is not UTF-8") from exc
    matches = [
        line[len(PACKET_REVIEW_MARKER):]
        for line in review_text.splitlines()
        if line.startswith(PACKET_REVIEW_MARKER)
    ]
    if len(matches) != 1:
        raise SuphxO0ScreenError(
            "independent-review record must contain exactly one O0 packet "
            "review marker")
    try:
        claim = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise SuphxO0ScreenError(
            "independent-review marker payload is invalid JSON") from exc
    expected = {
        "schema": PACKET_REVIEW_SCHEMA,
        "verdict": "PASS",
        "packet_sha256": packet_ref.sha256,
        "independent_review": True,
        "training_authorized": True,
        "o1_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    if claim != expected:
        raise SuphxO0ScreenError(
            "independent-review marker does not grant the exact narrow "
            "packet authority")
    return expected


def freeze_packet(root: str | Path) -> CheckpointRef:
    root = _require_run_root(root)
    if root.exists() and any(root.iterdir()):
        raise SuphxO0ScreenError("O0 freeze root must be absent or empty")
    root.mkdir(parents=True, exist_ok=True)
    runtime = runtime_identity()
    preflight_ref = _preflight_ref()
    spec = _spec_payload()
    dev = _dev_payload(progress=True)
    collision = _deal_collision_proof()
    spec_ref = _publish_json(root / "spec.json", spec)
    dev_ref = _publish_json(root / "dev.json", dev)
    initial_refs: dict[str, dict[str, str]] = {}
    for identity in SEED_IDENTITIES:
        index = int(identity["index"])
        model = new_from_scratch_model(int(identity["model_seed"]))
        actor_ref = publish_initial_actor(
            model, root / "initial" / f"seed_{index}_actor")
        model_state = state_digest(model.state_dict())
        reopened = load_verified(actor_ref, load_actor)
        if state_digest(reopened.state_dict()) != model_state:
            raise SuphxO0ScreenError("initial actor state failed exact reopen")
        manifest_ref = _publish_json(_initial_manifest_path(root, index), {
            "schema": "suphx-o0-initial-model-v1",
            "screen_schema": SCREEN_SCHEMA,
            "seed_identity": dict(identity),
            "actor_ref": actor_ref.as_dict(),
            "model_state_sha256": model_state,
            "oracle_public_initial_bytes_equal": True,
            "training_updates": 0,
            "production_promotion": False,
        })
        initial_refs[str(index)] = manifest_ref.as_dict()
    packet = {
        "schema": PACKET_SCHEMA,
        "screen_schema": SCREEN_SCHEMA,
        "artifact_root": RUN_RELATIVE_ROOT,
        "spec_ref": spec_ref.as_dict(),
        "dev_ref": dev_ref.as_dict(),
        "preflight_ref": preflight_ref.as_dict(),
        "initial_manifest_refs": initial_refs,
        "deal_collision_proof": collision,
        "runtime": runtime,
        "artifact_names": _artifact_names_payload(),
        "review_required": True,
        "training_authorized": False,
        "o1_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    packet_ref = _publish_json(_packet_path(root), packet)
    verify_packet(packet_ref, semantic_replay=True)
    return packet_ref


def _same_ref(value: object, expected: CheckpointRef, label: str) -> None:
    ref = _ref(value, label=label)
    if ref != expected:
        raise SuphxO0ScreenError(f"{label} identity mismatch")


def _verify_initial(root: Path, index: int) \
        -> tuple[CheckpointRef, CheckpointRef, dict[str, Any]]:
    identity = _seed_identity(index)
    manifest_ref = CheckpointRef.capture(
        _require_regular_final(_initial_manifest_path(root, index)))
    payload = _load_json(manifest_ref)
    expected_fields = {
        "schema", "screen_schema", "seed_identity", "actor_ref",
        "model_state_sha256", "oracle_public_initial_bytes_equal",
        "training_updates", "production_promotion",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_fields \
            or payload.get("schema") != "suphx-o0-initial-model-v1" \
            or payload.get("screen_schema") != SCREEN_SCHEMA \
            or payload.get("seed_identity") != identity \
            or payload.get("oracle_public_initial_bytes_equal") is not True \
            or payload.get("training_updates") != 0 \
            or payload.get("production_promotion") is not False:
        raise SuphxO0ScreenError("initial model manifest drift")
    actor_ref = _ref(payload["actor_ref"], label="initial actor")
    expected = new_from_scratch_model(identity["model_seed"])
    reopened = load_verified(actor_ref, load_actor)
    expected_state = state_digest(expected.state_dict())
    if payload.get("model_state_sha256") != expected_state \
            or state_digest(reopened.state_dict()) != expected_state:
        raise SuphxO0ScreenError("initial model bytes/seed drift")
    return manifest_ref, actor_ref, dict(payload)


def verify_packet(
        ref: CheckpointRef, *, semantic_replay: bool = True) \
        -> dict[str, Any]:
    packet = _load_json(ref)
    expected_fields = {
        "schema", "screen_schema", "artifact_root", "spec_ref", "dev_ref",
        "preflight_ref", "initial_manifest_refs", "deal_collision_proof",
        "runtime", "artifact_names", "review_required",
        "training_authorized", "o1_authorized", "strength_claim",
        "production_promotion",
    }
    if not isinstance(packet, Mapping) or set(packet) != expected_fields \
            or packet.get("schema") != PACKET_SCHEMA \
            or packet.get("screen_schema") != SCREEN_SCHEMA \
            or packet.get("artifact_root") != RUN_RELATIVE_ROOT \
            or packet.get("artifact_names") != _artifact_names_payload() \
            or packet.get("review_required") is not True \
            or any(packet.get(name) is not False for name in (
                "training_authorized", "o1_authorized", "strength_claim",
                "production_promotion")):
        raise SuphxO0ScreenError("launch packet fields/authority drift")
    root = _require_run_root(Path(ref.path).resolve().parent)
    if Path(ref.path).resolve() != _packet_path(root):
        raise SuphxO0ScreenError("launch packet is outside its exact path")
    spec_ref = CheckpointRef.capture(_require_regular_final(root / "spec.json"))
    dev_ref = CheckpointRef.capture(_require_regular_final(root / "dev.json"))
    _same_ref(packet["spec_ref"], spec_ref, "spec")
    _same_ref(packet["dev_ref"], dev_ref, "DEV")
    if _load_json(spec_ref) != _spec_payload():
        raise SuphxO0ScreenError("frozen O0 spec drift")
    dev = _validate_dev_payload_identity(_load_json(dev_ref))
    if semantic_replay and dev != _dev_payload(progress=True):
        raise SuphxO0ScreenError("frozen O0 DEV population drift")
    preflight = _preflight_ref()
    _same_ref(packet["preflight_ref"], preflight, "runtime preflight")
    if packet.get("deal_collision_proof") != _deal_collision_proof():
        raise SuphxO0ScreenError("causal deal collision proof drift")
    refs = packet.get("initial_manifest_refs")
    if not isinstance(refs, Mapping) \
            or set(refs) != {str(index) for index in range(3)}:
        raise SuphxO0ScreenError("initial manifest population drift")
    for index in range(3):
        manifest_ref, _, _ = _verify_initial(root, index)
        _same_ref(refs[str(index)], manifest_ref, "initial manifest")
    runtime_problems = _runtime_compatibility_problems(packet.get("runtime"))
    if runtime_problems:
        raise SuphxO0ScreenError(
            "frozen O0 runtime identity drift: "
            + "; ".join(runtime_problems))
    ref.verify()
    return dict(packet)


def admit_packet(
        packet_ref: CheckpointRef, *, expected_packet_sha256: str,
        review_record: str | Path, expected_review_sha256: str) \
        -> CheckpointRef:
    """Publish the only training admission after an external byte review.

    The command deliberately cannot manufacture review content.  It copies a
    caller-selected, hash-pinned regular file into the frozen namespace and
    binds that immutable copy to the exact packet.  Operator invocation is the
    external authority assertion; O0 code never calls this function itself.
    """
    if packet_ref.sha256 != expected_packet_sha256:
        raise SuphxO0ScreenError("expected launch-packet SHA-256 mismatch")
    packet = verify_packet(packet_ref, semantic_replay=False)
    root = _require_run_root(Path(packet_ref.path).resolve().parent)
    review_path = _require_regular_final(review_record)
    if review_path.resolve().is_relative_to(root):
        raise SuphxO0ScreenError(
            "independent-review source must be outside the O0 run namespace")
    review_bytes = review_path.read_bytes()
    review_sha256 = hashlib.sha256(review_bytes).hexdigest()
    if review_sha256 != expected_review_sha256:
        raise SuphxO0ScreenError("expected independent-review SHA-256 mismatch")
    if not review_bytes.strip():
        raise SuphxO0ScreenError("independent-review record is empty")
    review_claim = _packet_review_claim(review_bytes, packet_ref)
    review_ref = _publish_bytes(root / "review_record.txt", review_bytes)
    if review_ref.sha256 != expected_review_sha256:
        raise SuphxO0ScreenError("copied review bytes changed")
    admission = {
        "schema": ADMISSION_SCHEMA,
        "screen_schema": SCREEN_SCHEMA,
        "packet_ref": packet_ref.as_dict(),
        "review_record_ref": review_ref.as_dict(),
        "review_record_source_sha256": expected_review_sha256,
        "review_claim": review_claim,
        "operator_asserted_independent_review": True,
        "runtime_sha256": state_digest(packet["runtime"]),
        "training_authorized": True,
        "o1_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    return _publish_json(root / "review_admission.json", admission)


def _require_admission(root: str | Path) \
        -> tuple[CheckpointRef, CheckpointRef, dict[str, Any]]:
    root = _require_run_root(root)
    packet_ref = CheckpointRef.capture(
        _require_regular_final(_packet_path(root)))
    packet = verify_packet(packet_ref, semantic_replay=False)
    admission_ref = CheckpointRef.capture(
        _require_regular_final(root / "review_admission.json"))
    admission = _load_json(admission_ref)
    expected_fields = {
        "schema", "screen_schema", "packet_ref", "review_record_ref",
        "review_record_source_sha256", "review_claim",
        "operator_asserted_independent_review", "runtime_sha256",
        "training_authorized", "o1_authorized", "strength_claim",
        "production_promotion",
    }
    if not isinstance(admission, Mapping) or set(admission) != expected_fields \
            or admission.get("schema") != ADMISSION_SCHEMA \
            or admission.get("screen_schema") != SCREEN_SCHEMA \
            or admission.get("operator_asserted_independent_review") is not True \
            or admission.get("training_authorized") is not True \
            or any(admission.get(name) is not False for name in (
                "o1_authorized", "strength_claim", "production_promotion")) \
            or admission.get("runtime_sha256") != state_digest(packet["runtime"]):
        raise SuphxO0ScreenError("review admission fields/authority drift")
    _same_ref(admission["packet_ref"], packet_ref, "admitted packet")
    review_ref = _ref(
        admission["review_record_ref"], label="independent review copy")
    review_bytes = Path(review_ref.path).read_bytes()
    if review_ref.sha256 != admission.get("review_record_source_sha256") \
            or not review_bytes.strip() \
            or admission.get("review_claim") != _packet_review_claim(
                review_bytes, packet_ref):
        raise SuphxO0ScreenError("independent review copy drift")
    admission_ref.verify()
    return packet_ref, admission_ref, dict(admission)


def _schedule(identity: Mapping[str, int], arm: str) -> SuphxSchedule:
    if arm not in ARMS:
        raise SuphxO0ScreenError(f"unsupported O0 arm {arm!r}")
    return SuphxSchedule(
        segment_id=f"suphx-o0-seed-{identity['index']}-{arm}",
        keep_probabilities=(KEEP_PROBABILITIES[arm],) * ITERATIONS,
        learning_rate=LEARNING_RATE,
        deal_stream_root_seed=int(identity["deal_stream_root_seed"]),
    )


def _train_manifest_path(root: Path, index: int, arm: str) -> Path:
    return root / "train" / f"seed_{index}_{arm}.json"


class _ObservedCollector:
    def __init__(self, inner):
        self.inner = inner
        self.samples = 0
        self.surface_counts: Counter[str] = Counter()
        self.game_seed: int | None = None

    def __call__(self, identity):
        batch = self.inner(identity)
        game_seeds = set()
        for sample in batch.samples:
            self.surface_counts[surface_key(
                sample["role"], sample["decision_surface"])] += 1
            game_seeds.add(int(sample["game_seed"]))
        self.samples = len(batch.samples)
        if self.samples <= 0 or len(game_seeds) != 1:
            raise SuphxO0ScreenError(
                "training iteration did not produce one complete round")
        self.game_seed = next(iter(game_seeds))
        return batch


def _finite_model(model: SuphxPolicyValue) -> bool:
    return all(bool(torch.all(torch.isfinite(value)))
               for value in model.state_dict().values())


def _entropy_controller(model: SuphxPolicyValue) -> dict[str, float]:
    values = {
        key: float(head.entropy_alpha.item())
        for key, head in model.surfaces.items()
    }
    if set(values) != set(EXPECTED_SURFACES) \
            or any(not math.isfinite(value) or not 0.0 <= value <= 0.1
                   for value in values.values()):
        raise SuphxO0ScreenError("entropy-controller state is invalid")
    return values


def _run_iteration_block(
        *, runner, schedule: SuphxSchedule, writer: _ExclusiveJsonl,
        index: int, arm: str, start: int, stop: int,
        totals: Counter[str], game_seeds: list[int]) -> None:
    for sequence in range(start, stop):
        collector = _ObservedCollector(SuphxScheduledCollector(
            runner.contract_sha256, schedule))
        receipt = runner.run_iteration(
            collector, SuphxPolicyGradientUpdate(schedule))
        adopted = runner.adopt_current_candidate_as_actor()
        if receipt.batch.sequence != sequence \
                or receipt.progress.next_iteration != sequence + 1 \
                or receipt.progress.next_batch != sequence + 1 \
                or receipt.samples_added != collector.samples \
                or collector.game_seed is None \
                or adopted != receipt.candidate_ref:
            raise SuphxO0ScreenError(
                "synchronous O0 iteration work/adoption drift")
        expected_deal = derive_deal_seed(
            schedule.deal_stream_root_seed, sequence, 0)
        if collector.game_seed != expected_deal:
            raise SuphxO0ScreenError("causal training deal identity drift")
        totals["iterations"] += 1
        totals["rounds"] += 1
        totals["updates"] += 1
        totals["samples"] += collector.samples
        for key, count in collector.surface_counts.items():
            totals[key] += count
        game_seeds.append(collector.game_seed)
        writer.write({
            "schema": TRAIN_LEDGER_SCHEMA,
            "screen_schema": SCREEN_SCHEMA,
            "seed_index": index,
            "arm": arm,
            "sequence": sequence,
            "batch_identity": receipt.batch.as_dict(),
            "candidate_ref": receipt.candidate_ref.as_dict(),
            "adopted_actor_ref": adopted.as_dict(),
            "samples": collector.samples,
            "surface_counts": {
                key: collector.surface_counts[key]
                for key in EXPECTED_SURFACES
            },
            "game_seed": collector.game_seed,
            "progress": {
                "next_iteration": receipt.progress.next_iteration,
                "next_batch": receipt.progress.next_batch,
            },
        })
        if (sequence + 1) % 8 == 0:
            print(
                f"PROGRESS O0 seed={index} arm={arm} "
                f"{sequence + 1}/{ITERATIONS}", flush=True)


def train_arm(root: str | Path, index: int, arm: str) -> CheckpointRef:
    root = _require_run_root(root)
    if arm not in ARMS:
        raise SuphxO0ScreenError(f"unsupported O0 arm {arm!r}")
    packet_ref, admission_ref, _ = _require_admission(root)
    identity = _seed_identity(index)
    initial_manifest_ref, initial_actor_ref, initial = _verify_initial(
        root, index)
    schedule = _schedule(identity, arm)
    arm_root = root / "train" / f"seed_{index}_{arm}"
    bundle = new_bundle(
        model_seed=identity["model_seed"],
        learner_rng_seed=identity["learner_rng_seed"],
        learning_rate=LEARNING_RATE,
    )
    if state_digest(bundle.learner.state_dict()) != \
            initial["model_state_sha256"]:
        raise SuphxO0ScreenError("training learner differs from frozen initial")
    runner = new_runner(
        bundle=bundle,
        actor_ref=initial_actor_ref,
        snapshot_dir=arm_root / "candidates",
        root_seed=_runner_seed(identity, arm),
        schedule=schedule,
    )
    ledger = _ExclusiveJsonl(root / "train" / f"seed_{index}_{arm}.jsonl")
    totals: Counter[str] = Counter()
    game_seeds: list[int] = []
    try:
        _run_iteration_block(
            runner=runner, schedule=schedule, writer=ledger,
            index=index, arm=arm, start=0, stop=RESUME_BOUNDARY,
            totals=totals, game_seeds=game_seeds)
        midpoint_ref = runner.save_checkpoint(
            arm_root / f"resume_{RESUME_BOUNDARY:03d}.pt")
        midpoint_actor = runner.actor_ref
        midpoint_candidate = runner.candidate_ref
        midpoint_boundary = exact_resume_boundary_identity(midpoint_ref)
        # Reconstruct every mutable component before doing the second half.
        resumed_bundle = new_bundle(
            model_seed=identity["model_seed"],
            learner_rng_seed=identity["learner_rng_seed"],
            learning_rate=LEARNING_RATE,
        )
        runner = resume_runner(
            midpoint_ref,
            bundle=resumed_bundle,
            actor_ref=midpoint_actor,
            candidate_ref=midpoint_candidate,
            snapshot_dir=arm_root / "candidates",
            root_seed=_runner_seed(identity, arm),
            schedule=schedule,
        )
        if runner.progress.next_iteration != RESUME_BOUNDARY \
                or runner.actor_ref != midpoint_candidate:
            raise SuphxO0ScreenError("midpoint resume boundary drift")
        _run_iteration_block(
            runner=runner, schedule=schedule, writer=ledger,
            index=index, arm=arm, start=RESUME_BOUNDARY, stop=ITERATIONS,
            totals=totals, game_seeds=game_seeds)
        terminal_ref = runner.save_checkpoint(
            arm_root / f"resume_{ITERATIONS:03d}.pt")
        ledger_ref = ledger.publish()
    except BaseException:
        ledger.abandon()
        raise
    terminal_actor = runner.actor_ref
    terminal_candidate = runner.candidate_ref
    if terminal_actor != terminal_candidate \
            or runner.progress.next_iteration != ITERATIONS \
            or runner.progress.next_batch != ITERATIONS:
        raise SuphxO0ScreenError("terminal candidate was not exactly adopted")
    expected_deals = [
        derive_deal_seed(schedule.deal_stream_root_seed, sequence, 0)
        for sequence in range(ITERATIONS)
    ]
    if game_seeds != expected_deals:
        raise SuphxO0ScreenError("complete training deal stream drift")
    surface_counts = {key: totals[key] for key in EXPECTED_SURFACES}
    if any(count <= 0 for count in surface_counts.values()):
        raise SuphxO0ScreenError("training arm lacks a role/surface")
    if totals["iterations"] != ITERATIONS \
            or totals["rounds"] != ITERATIONS \
            or totals["updates"] != ITERATIONS \
            or totals["samples"] != sum(surface_counts.values()):
        raise SuphxO0ScreenError("terminal training dose drift")
    if not _finite_model(runner.learner):
        raise SuphxO0ScreenError("terminal model is non-finite")
    controller = _entropy_controller(runner.learner)
    terminal_boundary = exact_resume_boundary_identity(terminal_ref)
    expected_contract = _runner_contract_sha256(
        experiment=EXPERIMENT,
        root_seed=_runner_seed(identity, arm),
        algorithm_sha256=algorithm_sha256(schedule),
    )
    if terminal_boundary.get("contract_sha256") != expected_contract \
            or terminal_boundary.get("progress") != {
                "next_iteration": ITERATIONS, "next_batch": ITERATIONS} \
            or terminal_boundary.get("actor_ref") != terminal_actor.as_dict() \
            or terminal_boundary.get("candidate_ref") \
            != terminal_candidate.as_dict():
        raise SuphxO0ScreenError("terminal exact-resume identity drift")
    payload = {
        "schema": TRAIN_SCHEMA,
        "screen_schema": SCREEN_SCHEMA,
        "packet_ref": packet_ref.as_dict(),
        "admission_ref": admission_ref.as_dict(),
        "initial_manifest_ref": initial_manifest_ref.as_dict(),
        "seed_identity": identity,
        "arm": arm,
        "keep_probability": KEEP_PROBABILITIES[arm],
        "schedule": schedule.as_dict(),
        "algorithm_sha256": algorithm_sha256(schedule),
        "runner_contract_sha256": expected_contract,
        "ledger_ref": ledger_ref.as_dict(),
        "midpoint_resume_ref": midpoint_ref.as_dict(),
        "midpoint_boundary_sha256": state_digest(midpoint_boundary),
        "terminal_resume_ref": terminal_ref.as_dict(),
        "terminal_boundary_sha256": state_digest(terminal_boundary),
        "terminal_actor_ref": terminal_actor.as_dict(),
        "terminal_model_state_sha256": state_digest(
            runner.learner.state_dict()),
        "entropy_controller": controller,
        "iterations": totals["iterations"],
        "rounds": totals["rounds"],
        "updates": totals["updates"],
        "samples": totals["samples"],
        "surface_counts": surface_counts,
        "deal_seed_digest": state_digest(game_seeds),
        "exact_midpoint_resume_exercised": True,
        "terminal_candidate_adopted": True,
        "model_finite": True,
        "complete": True,
        "o1_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    ref = _publish_json(_train_manifest_path(root, index, arm), payload)
    _load_training(root, index, arm)
    return ref


def _load_training(root: str | Path, index: int, arm: str) \
        -> tuple[CheckpointRef, CheckpointRef, dict[str, Any]]:
    root = _require_run_root(root)
    if arm not in ARMS:
        raise SuphxO0ScreenError(f"unsupported O0 arm {arm!r}")
    packet_ref, admission_ref, _ = _require_admission(root)
    identity = _seed_identity(index)
    initial_manifest_ref, initial_actor_ref, _ = _verify_initial(root, index)
    schedule = _schedule(identity, arm)
    ref = CheckpointRef.capture(
        _require_regular_final(_train_manifest_path(root, index, arm)))
    payload = _load_json(ref)
    expected_fields = {
        "schema", "screen_schema", "packet_ref", "admission_ref",
        "initial_manifest_ref", "seed_identity", "arm", "keep_probability",
        "schedule", "algorithm_sha256", "runner_contract_sha256",
        "ledger_ref", "midpoint_resume_ref", "midpoint_boundary_sha256",
        "terminal_resume_ref", "terminal_boundary_sha256",
        "terminal_actor_ref", "terminal_model_state_sha256",
        "entropy_controller", "iterations", "rounds", "updates", "samples",
        "surface_counts", "deal_seed_digest",
        "exact_midpoint_resume_exercised", "terminal_candidate_adopted",
        "model_finite", "complete", "o1_authorized", "strength_claim",
        "production_promotion",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_fields \
            or payload.get("schema") != TRAIN_SCHEMA \
            or payload.get("screen_schema") != SCREEN_SCHEMA \
            or payload.get("seed_identity") != identity \
            or payload.get("arm") != arm \
            or payload.get("keep_probability") != KEEP_PROBABILITIES[arm] \
            or payload.get("schedule") != schedule.as_dict() \
            or payload.get("algorithm_sha256") != algorithm_sha256(schedule) \
            or payload.get("complete") is not True \
            or payload.get("exact_midpoint_resume_exercised") is not True \
            or payload.get("terminal_candidate_adopted") is not True \
            or payload.get("model_finite") is not True \
            or any(payload.get(name) is not False for name in (
                "o1_authorized", "strength_claim", "production_promotion")):
        raise SuphxO0ScreenError("training manifest identity/authority drift")
    _same_ref(payload["packet_ref"], packet_ref, "training packet")
    _same_ref(payload["admission_ref"], admission_ref, "training admission")
    _same_ref(
        payload["initial_manifest_ref"], initial_manifest_ref,
        "training initial manifest")
    ledger_ref = _ref(payload["ledger_ref"], label="training ledger")
    midpoint_ref = _ref(
        payload["midpoint_resume_ref"], label="midpoint checkpoint")
    terminal_ref = _ref(
        payload["terminal_resume_ref"], label="terminal checkpoint")
    terminal_actor = _ref(
        payload["terminal_actor_ref"], label="terminal actor")
    midpoint = exact_resume_boundary_identity(midpoint_ref)
    terminal = exact_resume_boundary_identity(terminal_ref)
    expected_contract = _runner_contract_sha256(
        experiment=EXPERIMENT,
        root_seed=_runner_seed(identity, arm),
        algorithm_sha256=algorithm_sha256(schedule),
    )
    if payload.get("runner_contract_sha256") != expected_contract \
            or payload.get("midpoint_boundary_sha256") != state_digest(midpoint) \
            or payload.get("terminal_boundary_sha256") != state_digest(terminal) \
            or midpoint.get("progress") != {
                "next_iteration": RESUME_BOUNDARY,
                "next_batch": RESUME_BOUNDARY} \
            or terminal.get("progress") != {
                "next_iteration": ITERATIONS, "next_batch": ITERATIONS} \
            or terminal.get("contract_sha256") != expected_contract \
            or terminal.get("actor_ref") != terminal_actor.as_dict() \
            or terminal.get("candidate_ref") != terminal_actor.as_dict():
        raise SuphxO0ScreenError("training exact-resume boundary drift")
    rows = _load_jsonl(ledger_ref)
    if len(rows) != ITERATIONS:
        raise SuphxO0ScreenError("training ledger dose drift")
    totals: Counter[str] = Counter()
    deals = []
    previous_actor = initial_actor_ref
    for sequence, row in enumerate(rows):
        if not isinstance(row, Mapping) \
                or row.get("schema") != TRAIN_LEDGER_SCHEMA \
                or row.get("screen_schema") != SCREEN_SCHEMA \
                or row.get("seed_index") != index \
                or row.get("arm") != arm \
                or row.get("sequence") != sequence \
                or row.get("progress") != {
                    "next_iteration": sequence + 1,
                    "next_batch": sequence + 1}:
            raise SuphxO0ScreenError("training ledger row identity drift")
        batch = row.get("batch_identity")
        if not isinstance(batch, Mapping) \
                or batch.get("sequence") != sequence \
                or batch.get("contract_sha256") != expected_contract:
            raise SuphxO0ScreenError("training batch identity drift")
        _same_ref(batch.get("actor"), previous_actor, "training batch actor")
        candidate = _ref(row.get("candidate_ref"), label="training candidate")
        _same_ref(row.get("adopted_actor_ref"), candidate, "candidate adoption")
        previous_actor = candidate
        samples = row.get("samples")
        counts = row.get("surface_counts")
        expected_deal = derive_deal_seed(
            schedule.deal_stream_root_seed, sequence, 0)
        if isinstance(samples, bool) or not isinstance(samples, int) \
                or samples <= 0 or not isinstance(counts, Mapping) \
                or set(counts) != set(EXPECTED_SURFACES) \
                or any(isinstance(value, bool) or not isinstance(value, int)
                       or value < 0 for value in counts.values()) \
                or sum(counts.values()) != samples \
                or row.get("game_seed") != expected_deal:
            raise SuphxO0ScreenError("training ledger work/deal drift")
        totals["samples"] += samples
        for key, value in counts.items():
            totals[key] += value
        deals.append(expected_deal)
    if previous_actor != terminal_actor \
            or payload.get("iterations") != ITERATIONS \
            or payload.get("rounds") != ITERATIONS \
            or payload.get("updates") != ITERATIONS \
            or payload.get("samples") != totals["samples"] \
            or payload.get("surface_counts") != {
                key: totals[key] for key in EXPECTED_SURFACES} \
            or any(totals[key] <= 0 for key in EXPECTED_SURFACES) \
            or payload.get("deal_seed_digest") != state_digest(deals):
        raise SuphxO0ScreenError("training terminal totals drift")
    model = load_verified(terminal_actor, load_actor)
    if not _finite_model(model) \
            or payload.get("terminal_model_state_sha256") != state_digest(
                model.state_dict()) \
            or payload.get("entropy_controller") != _entropy_controller(model):
        raise SuphxO0ScreenError("terminal model/controller drift")
    ref.verify()
    return ref, terminal_actor, dict(payload)


def _score_state(
        model: SuphxPolicyValue, rnd: Round, seat: int, *, gamma: float) \
        -> dict[str, Any]:
    if gamma not in (0.0, 1.0):
        raise SuphxO0ScreenError("O0 diagnostics require an exact endpoint")
    actions = enumerate_actions(
        rnd, seat, exhaustive_follows=False, include_throws=False)
    if len(actions) <= 1:
        raise SuphxO0ScreenError("DEV diagnostic state is not multi-action")
    partition = encode_feature_partition(rnd, seat)
    mask = np.full(PERFECT_DIM, gamma, dtype=np.float32)
    masked = apply_privilege_mask(partition["perfect"], mask)
    encoded_actions = np.asarray(
        [encode_action(action, rnd) for action in actions],
        dtype=np.float32,
    ).reshape(-1, ACT_DIM)
    role = role_for(rnd, seat)
    surface = surface_for(rnd)
    logits, value = model.score_candidates(
        role=role,
        surface=surface,
        observation=partition["observation"],
        legal_private=partition["legal_private"],
        history=partition["public_history"],
        masked_perfect=masked,
        actions=encoded_actions,
    )
    probabilities = torch.softmax(logits, dim=0)
    entropy = float((-(probabilities * torch.log(probabilities))).sum().item())
    normalized_entropy = entropy / math.log(len(actions))
    if not math.isfinite(normalized_entropy) \
            or not -1e-7 <= normalized_entropy <= 1.0 + 1e-6:
        raise SuphxO0ScreenError("normalized policy entropy is invalid")
    return {
        "role": role,
        "surface": surface,
        "surface_key": surface_key(role, surface),
        "partition": partition,
        "actions": tuple(tuple(action) for action in actions),
        "logits": logits.detach().cpu(),
        "value": float(value.item()),
        "greedy": int(torch.argmax(logits).item()),
        "normalized_entropy": normalized_entropy,
    }


def _hidden_ownership_swap(rnd: Round, seat: int) -> Round:
    return _legal_hidden_hand_neighbor(rnd, seat)


class _GreedyOrdinary:
    def __init__(self, model: SuphxPolicyValue, gamma: float):
        self.model = model
        self.gamma = gamma
        self.decisions = 0

    def decide_play(self, rnd: Round, seat: int):
        scored = _score_state_allow_forced(
            self.model, rnd, seat, gamma=self.gamma)
        self.decisions += 1
        return list(scored["actions"][scored["greedy"]])


def _score_state_allow_forced(
        model: SuphxPolicyValue, rnd: Round, seat: int, *, gamma: float) \
        -> dict[str, Any]:
    actions = enumerate_actions(
        rnd, seat, exhaustive_follows=False, include_throws=False)
    if not actions:
        raise SuphxO0ScreenError("greedy ordinary ballot is empty")
    partition = encode_feature_partition(rnd, seat)
    mask = np.full(PERFECT_DIM, gamma, dtype=np.float32)
    encoded_actions = np.asarray(
        [encode_action(action, rnd) for action in actions],
        dtype=np.float32,
    ).reshape(-1, ACT_DIM)
    role = role_for(rnd, seat)
    surface = surface_for(rnd)
    logits, value = model.score_candidates(
        role=role,
        surface=surface,
        observation=partition["observation"],
        legal_private=partition["legal_private"],
        history=partition["public_history"],
        masked_perfect=apply_privilege_mask(partition["perfect"], mask),
        actions=encoded_actions,
    )
    return {
        "actions": tuple(tuple(action) for action in actions),
        "logits": logits.detach().cpu(),
        "value": float(value.item()),
        "greedy": int(torch.argmax(logits).item()),
    }


class _SetupComposite:
    def __init__(self, ordinary: _GreedyOrdinary):
        self.ordinary = ordinary
        self.control = SmartBot()

    def decide_declare(self, rnd, seat, final=False):
        return self.control.decide_declare(rnd, seat, final=final)

    def decide_bury(self, rnd, seat):
        return self.control.decide_bury(rnd, seat)

    def decide_play(self, rnd, seat):
        return self.ordinary.decide_play(rnd, seat)


def _candidate_role(banker: int, candidate_team: int) -> int:
    if banker not in range(4) or candidate_team not in (0, 1):
        raise SuphxO0ScreenError("candidate role inputs are invalid")
    # ROLE_NAMES is {attacker, defender}; use the model's exact role router by
    # parity rather than relying on a local numeric convention.
    return next(
        role for role, name in ROLE_NAMES.items()
        if name == ("defender" if banker % 2 == candidate_team else "attacker")
    )


def _comparison_round(
        *, comparison: str, index: int, deal_seed: int, flip: int,
        candidate_model: SuphxPolicyValue, reference_model: SuphxPolicyValue,
        candidate_ref: CheckpointRef, reference_ref: CheckpointRef,
        candidate_gamma: float, reference_gamma: float) -> dict[str, Any]:
    if comparison not in COMPARISONS or flip not in (0, 1):
        raise SuphxO0ScreenError("DEV comparison/flip is invalid")
    candidate_team = flip
    actors = []
    policies = []
    for seat in range(4):
        if seat % 2 == candidate_team:
            actor = _GreedyOrdinary(candidate_model, candidate_gamma)
        else:
            actor = _GreedyOrdinary(reference_model, reference_gamma)
        actors.append(actor)
        policies.append(_SetupComposite(actor))
    game = Game(random.Random(deal_seed))
    log = play_round(game, policies)
    role = _candidate_role(int(log.banker), candidate_team)
    attacker_return = clipped_attacker_bracket_return(log.attacker_points)
    signed = acting_team_return(attacker_return, role)
    return {
        "schema": DEV_ROW_SCHEMA,
        "screen_schema": SCREEN_SCHEMA,
        "seed_index": index,
        "comparison": comparison,
        "deal_seed": deal_seed,
        "flip": flip,
        "candidate_team": candidate_team,
        "banker": log.banker,
        "candidate_role": ROLE_NAMES[role],
        "attacker_points": log.attacker_points,
        "attacker_bracket_return": attacker_return,
        "candidate_signed_return": signed,
        "candidate_won": int(log.winner_team == candidate_team),
        "candidate_decisions": sum(
            actors[seat].decisions for seat in range(4)
            if seat % 2 == candidate_team),
        "reference_decisions": sum(
            actors[seat].decisions for seat in range(4)
            if seat % 2 != candidate_team),
        "candidate_ref": candidate_ref.as_dict(),
        "reference_ref": reference_ref.as_dict(),
        "candidate_gamma": candidate_gamma,
        "reference_gamma": reference_gamma,
        "ballot_schema": BALLOT_SCHEMA,
        "ordinary_policy": "deterministic_greedy_first_argmax",
        "setup_controls": "SmartBot_declaration_and_burial",
    }


def _compute_dev_diagnostics(
        *, root: Path, index: int, oracle_model: SuphxPolicyValue,
        public_model: SuphxPolicyValue, initial_model: SuphxPolicyValue) \
        -> dict[str, Any]:
    packet_ref = CheckpointRef.capture(_require_regular_final(_packet_path(root)))
    packet = verify_packet(packet_ref, semantic_replay=False)
    dev_ref = _ref(packet["dev_ref"], label="diagnostic DEV")
    dev = _load_json(dev_ref)
    entries = dev.get("entries") if isinstance(dev, Mapping) else None
    if not isinstance(entries, list) or len(entries) != DEV_DEALS:
        raise SuphxO0ScreenError("diagnostic DEV entries drift")
    entropy: dict[str, dict[str, list[float]]] = {
        arm: {surface: [] for surface in EXPECTED_SURFACES}
        for arm in ARMS
    }
    oracle_hand_witness = {surface: 0.0 for surface in EXPECTED_SURFACES}
    public_hand_invariance = {surface: True for surface in EXPECTED_SURFACES}
    oracle_burial_witness = {surface: 0.0 for surface in EXPECTED_SURFACES}
    public_burial_invariance = {
        surface: True for surface in EXPECTED_SURFACES}
    burial_witness_counts: Counter[str] = Counter()
    value_error = {
        "oracle_initial": [],
        "oracle_terminal": [],
        "public_terminal": [],
    }
    greedy_changes = Counter()
    for deal_index, frozen in enumerate(entries):
        expected, captured = _capture_dev_state(
            DEV_SEED0 + deal_index, deal_index)
        if expected != frozen:
            raise SuphxO0ScreenError("DEV selected-state semantic replay drift")
        changed = _hidden_ownership_swap(captured.rnd, captured.seat)
        if state_digest(_round_payload(changed, captured.seat)) != frozen[
                "legal_hidden_hand_neighbor_sha256"]:
            raise SuphxO0ScreenError(
                "DEV legal hidden-hand witness replay drift")
        oracle = _score_state(
            oracle_model, captured.rnd, captured.seat, gamma=1.0)
        oracle_changed = _score_state(
            oracle_model, changed, captured.seat, gamma=1.0)
        public = _score_state(
            public_model, captured.rnd, captured.seat, gamma=0.0)
        public_changed = _score_state(
            public_model, changed, captured.seat, gamma=0.0)
        initial = _score_state(
            initial_model, captured.rnd, captured.seat, gamma=1.0)
        if oracle["actions"] != captured.ballot \
                or public["actions"] != captured.ballot \
                or initial["actions"] != captured.ballot \
                or oracle_changed["actions"] != captured.ballot \
                or public_changed["actions"] != captured.ballot:
            raise SuphxO0ScreenError("DEV ordered ballot drift")
        surface = captured.surface
        if oracle["surface_key"] != surface \
                or public["surface_key"] != surface:
            raise SuphxO0ScreenError("DEV role/surface routing drift")
        entropy["oracle"][surface].append(oracle["normalized_entropy"])
        entropy["public"][surface].append(public["normalized_entropy"])
        difference = float(torch.max(torch.abs(
            oracle["logits"] - oracle_changed["logits"])).item())
        if not math.isfinite(difference):
            raise SuphxO0ScreenError("oracle hidden-logit witness is non-finite")
        oracle_hand_witness[surface] = max(
            oracle_hand_witness[surface], difference)
        invariant = (
            torch.equal(public["logits"], public_changed["logits"])
            and public["value"] == public_changed["value"]
            and public["greedy"] == public_changed["greedy"]
        )
        public_hand_invariance[surface] = (
            public_hand_invariance[surface] and invariant)
        frozen_burial = frozen["legal_hidden_burial_neighbor_sha256"]
        if frozen_burial is not None:
            burial_changed = _legal_hidden_burial_neighbor(
                captured.rnd, captured.seat)
            if state_digest(_round_payload(
                    burial_changed, captured.seat)) != frozen_burial:
                raise SuphxO0ScreenError(
                    "DEV legal hidden-burial witness replay drift")
            oracle_burial = _score_state(
                oracle_model, burial_changed, captured.seat, gamma=1.0)
            public_burial = _score_state(
                public_model, burial_changed, captured.seat, gamma=0.0)
            if oracle_burial["actions"] != captured.ballot \
                    or public_burial["actions"] != captured.ballot:
                raise SuphxO0ScreenError(
                    "DEV hidden-burial ordered ballot drift")
            burial_difference = float(torch.max(torch.abs(
                oracle["logits"] - oracle_burial["logits"])).item())
            if not math.isfinite(burial_difference):
                raise SuphxO0ScreenError(
                    "oracle hidden-burial witness is non-finite")
            oracle_burial_witness[surface] = max(
                oracle_burial_witness[surface], burial_difference)
            public_burial_invariance[surface] = (
                public_burial_invariance[surface]
                and torch.equal(public["logits"], public_burial["logits"])
                and public["value"] == public_burial["value"]
                and public["greedy"] == public_burial["greedy"]
            )
            burial_witness_counts[surface] += 1
        target = float(frozen["target"])
        value_error["oracle_initial"].append((initial["value"] - target) ** 2)
        value_error["oracle_terminal"].append((oracle["value"] - target) ** 2)
        value_error["public_terminal"].append((public["value"] - target) ** 2)
        greedy_changes["oracle"] += int(
            oracle["greedy"] != initial["greedy"])
        greedy_changes["public"] += int(
            public["greedy"] != initial["greedy"])
        if (deal_index + 1) % 16 == 0 or deal_index + 1 == DEV_DEALS:
            print(
                f"PROGRESS O0 DEV diagnostics seed={index} "
                f"{deal_index + 1}/{DEV_DEALS}",
                flush=True)
    entropy_summary = {
        arm: {
            surface: {
                "states": len(entropy[arm][surface]),
                "median_normalized_entropy": float(np.median(
                    entropy[arm][surface])),
            }
            for surface in EXPECTED_SURFACES
        }
        for arm in ARMS
    }
    return {
        "dev_state_count": DEV_DEALS,
        "entropy": entropy_summary,
        "oracle_hidden_hand_logit_max_abs_difference": oracle_hand_witness,
        "public_hidden_hand_permutation_exact": public_hand_invariance,
        "oracle_hidden_burial_logit_max_abs_difference":
            oracle_burial_witness,
        "public_hidden_burial_permutation_exact": public_burial_invariance,
        "hidden_burial_witness_counts": {
            surface: burial_witness_counts[surface]
            for surface in EXPECTED_SURFACES
        },
        "value_mse_diagnostic": {
            name: float(np.mean(values)) for name, values in value_error.items()
        },
        "greedy_action_change_rate_diagnostic": {
            name: greedy_changes[name] / DEV_DEALS for name in ARMS
        },
    }


def _dev_result_path(root: Path, index: int) -> Path:
    return root / "dev" / f"seed_{index}.json"


def evaluate_seed(root: str | Path, index: int) -> CheckpointRef:
    root = _require_run_root(root)
    packet_ref, admission_ref, _ = _require_admission(root)
    initial_manifest_ref, initial_ref, _ = _verify_initial(root, index)
    oracle_train_ref, oracle_ref, _ = _load_training(root, index, "oracle")
    public_train_ref, public_ref, _ = _load_training(root, index, "public")
    initial_model = load_verified(initial_ref, load_actor)
    oracle_model = load_verified(oracle_ref, load_actor)
    public_model = load_verified(public_ref, load_actor)
    if state_digest(oracle_model.state_dict()) == state_digest(
            initial_model.state_dict()) \
            or state_digest(public_model.state_dict()) == state_digest(
                initial_model.state_dict()):
        raise SuphxO0ScreenError("O0 training arm did not change its model")
    diagnostics = _compute_dev_diagnostics(
        root=root,
        index=index,
        oracle_model=oracle_model,
        public_model=public_model,
        initial_model=initial_model,
    )
    definitions = {
        "oracle_minus_initial": (
            oracle_model, initial_model, oracle_ref, initial_ref, 1.0, 1.0),
        "oracle_minus_public": (
            oracle_model, public_model, oracle_ref, public_ref, 1.0, 0.0),
        "same_model_null": (
            initial_model, initial_model, initial_ref, initial_ref, 1.0, 1.0),
    }
    writer = _ExclusiveJsonl(root / "dev" / f"seed_{index}.jsonl")
    counts = Counter()
    try:
        for comparison in COMPARISONS:
            candidate_model, reference_model, candidate_ref, reference_ref, \
                candidate_gamma, reference_gamma = definitions[comparison]
            for deal_offset, deal_seed in enumerate(
                    range(DEV_SEED0, DEV_SEED0 + DEV_DEALS)):
                for flip in (0, 1):
                    row = _comparison_round(
                        comparison=comparison,
                        index=index,
                        deal_seed=deal_seed,
                        flip=flip,
                        candidate_model=candidate_model,
                        reference_model=reference_model,
                        candidate_ref=candidate_ref,
                        reference_ref=reference_ref,
                        candidate_gamma=candidate_gamma,
                        reference_gamma=reference_gamma,
                    )
                    counts[comparison] += 1
                    writer.write(row)
                if (deal_offset + 1) % 16 == 0 \
                        or deal_offset + 1 == DEV_DEALS:
                    print(
                        f"PROGRESS O0 DEV seed={index} "
                        f"comparison={comparison} "
                        f"{counts[comparison]}/{2 * DEV_DEALS}",
                        flush=True)
        raw_ref = writer.publish()
    except BaseException:
        writer.abandon()
        raise
    if any(counts[name] != 2 * DEV_DEALS for name in COMPARISONS):
        raise SuphxO0ScreenError("DEV comparison dose drift")
    payload = {
        "schema": DEV_RESULT_SCHEMA,
        "screen_schema": SCREEN_SCHEMA,
        "packet_ref": packet_ref.as_dict(),
        "admission_ref": admission_ref.as_dict(),
        "initial_manifest_ref": initial_manifest_ref.as_dict(),
        "oracle_training_ref": oracle_train_ref.as_dict(),
        "public_training_ref": public_train_ref.as_dict(),
        "seed_index": index,
        "model_refs": {
            "initial": initial_ref.as_dict(),
            "oracle": oracle_ref.as_dict(),
            "public": public_ref.as_dict(),
        },
        "comparisons": list(COMPARISONS),
        "deal_seed0": DEV_SEED0,
        "deals": DEV_DEALS,
        "flips": [0, 1],
        "rounds": writer.count,
        "comparison_rounds": dict(counts),
        "diagnostics": diagnostics,
        "raw_ref": raw_ref.as_dict(),
        "complete": True,
        "o1_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    ref = _publish_json(_dev_result_path(root, index), payload)
    _load_dev_result(root, index, semantic_replay=False)
    return ref


def _exact_two_flip_means(rows: Sequence[Mapping[str, Any]]) \
        -> dict[int, float]:
    expected = {
        (seed, flip)
        for seed in range(DEV_SEED0, DEV_SEED0 + DEV_DEALS)
        for flip in (0, 1)
    }
    seen = set()
    grouped: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        key = (row.get("deal_seed"), row.get("flip"))
        if key not in expected or key in seen:
            raise SuphxO0ScreenError("DEV rows have duplicate/extra flip")
        value = row.get("candidate_signed_return")
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(float(value)):
            raise SuphxO0ScreenError("DEV utility is non-finite")
        seen.add(key)
        grouped[int(key[0])].append(float(value))
    if seen != expected \
            or any(len(values) != 2 for values in grouped.values()):
        raise SuphxO0ScreenError("DEV rows lack exact two-flip coverage")
    return {
        deal: float(np.mean(values))
        for deal, values in sorted(grouped.items())
    }


def _load_dev_result(root: str | Path, index: int, *, semantic_replay: bool) \
        -> tuple[CheckpointRef, dict[str, dict[int, float]], dict[str, Any]]:
    root = _require_run_root(root)
    packet_ref, admission_ref, _ = _require_admission(root)
    initial_manifest_ref, initial_ref, _ = _verify_initial(root, index)
    oracle_train_ref, oracle_ref, _ = _load_training(root, index, "oracle")
    public_train_ref, public_ref, _ = _load_training(root, index, "public")
    ref = CheckpointRef.capture(
        _require_regular_final(_dev_result_path(root, index)))
    payload = _load_json(ref)
    expected_fields = {
        "schema", "screen_schema", "packet_ref", "admission_ref",
        "initial_manifest_ref", "oracle_training_ref", "public_training_ref",
        "seed_index", "model_refs", "comparisons", "deal_seed0", "deals",
        "flips", "rounds", "comparison_rounds", "diagnostics", "raw_ref",
        "complete", "o1_authorized", "strength_claim", "production_promotion",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_fields \
            or payload.get("schema") != DEV_RESULT_SCHEMA \
            or payload.get("screen_schema") != SCREEN_SCHEMA \
            or payload.get("seed_index") != index \
            or payload.get("comparisons") != list(COMPARISONS) \
            or payload.get("deal_seed0") != DEV_SEED0 \
            or payload.get("deals") != DEV_DEALS \
            or payload.get("flips") != [0, 1] \
            or payload.get("rounds") != 2 * DEV_DEALS * len(COMPARISONS) \
            or payload.get("comparison_rounds") != {
                name: 2 * DEV_DEALS for name in COMPARISONS} \
            or payload.get("complete") is not True \
            or any(payload.get(name) is not False for name in (
                "o1_authorized", "strength_claim", "production_promotion")):
        raise SuphxO0ScreenError("DEV result identity/authority drift")
    for value, expected, label in (
        (payload["packet_ref"], packet_ref, "DEV packet"),
        (payload["admission_ref"], admission_ref, "DEV admission"),
        (payload["initial_manifest_ref"], initial_manifest_ref,
         "DEV initial manifest"),
        (payload["oracle_training_ref"], oracle_train_ref,
         "DEV oracle training"),
        (payload["public_training_ref"], public_train_ref,
         "DEV public training"),
    ):
        _same_ref(value, expected, label)
    model_refs = payload.get("model_refs")
    if not isinstance(model_refs, Mapping) \
            or set(model_refs) != {"initial", "oracle", "public"}:
        raise SuphxO0ScreenError("DEV model reference population drift")
    for name, expected in (
        ("initial", initial_ref), ("oracle", oracle_ref), ("public", public_ref)):
        _same_ref(model_refs[name], expected, f"DEV {name} model")
    models = {
        "initial": load_verified(initial_ref, load_actor),
        "oracle": load_verified(oracle_ref, load_actor),
        "public": load_verified(public_ref, load_actor),
    }
    diagnostics = payload.get("diagnostics")
    if not isinstance(diagnostics, Mapping):
        raise SuphxO0ScreenError("DEV diagnostics are not an object")
    if semantic_replay:
        expected_diagnostics = _compute_dev_diagnostics(
            root=root,
            index=index,
            oracle_model=models["oracle"],
            public_model=models["public"],
            initial_model=models["initial"],
        )
        if diagnostics != expected_diagnostics:
            raise SuphxO0ScreenError("DEV diagnostic recomputation drift")
    definitions = {
        "oracle_minus_initial": (
            models["oracle"], models["initial"], oracle_ref, initial_ref,
            1.0, 1.0),
        "oracle_minus_public": (
            models["oracle"], models["public"], oracle_ref, public_ref,
            1.0, 0.0),
        "same_model_null": (
            models["initial"], models["initial"], initial_ref, initial_ref,
            1.0, 1.0),
    }
    rows = _load_jsonl(_ref(payload["raw_ref"], label="DEV raw rows"))
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    seen = set()
    replayed = 0
    replay_total = 2 * DEV_DEALS * len(COMPARISONS)
    for row in rows:
        if not isinstance(row, Mapping) \
                or row.get("schema") != DEV_ROW_SCHEMA \
                or row.get("screen_schema") != SCREEN_SCHEMA \
                or row.get("seed_index") != index \
                or row.get("comparison") not in COMPARISONS \
                or row.get("ballot_schema") != BALLOT_SCHEMA \
                or row.get("ordinary_policy") \
                != "deterministic_greedy_first_argmax" \
                or row.get("setup_controls") \
                != "SmartBot_declaration_and_burial":
            raise SuphxO0ScreenError("DEV raw row identity drift")
        key = (row["comparison"], row.get("deal_seed"), row.get("flip"))
        if key in seen:
            raise SuphxO0ScreenError("DEV raw row collision")
        seen.add(key)
        definition = definitions[row["comparison"]]
        candidate_model, reference_model, candidate_ref, reference_ref, \
            candidate_gamma, reference_gamma = definition
        _same_ref(row.get("candidate_ref"), candidate_ref, "DEV row candidate")
        _same_ref(row.get("reference_ref"), reference_ref, "DEV row reference")
        if row.get("candidate_gamma") != candidate_gamma \
                or row.get("reference_gamma") != reference_gamma:
            raise SuphxO0ScreenError("DEV row endpoint gamma drift")
        candidate_team = int(row.get("flip"))
        if row.get("candidate_team") != candidate_team:
            raise SuphxO0ScreenError("DEV candidate-team flip drift")
        role = _candidate_role(int(row.get("banker")), candidate_team)
        expected_return = clipped_attacker_bracket_return(
            int(row.get("attacker_points")))
        expected_signed = acting_team_return(expected_return, role)
        if row.get("candidate_role") != ROLE_NAMES[role] \
                or row.get("attacker_bracket_return") != expected_return \
                or row.get("candidate_signed_return") != expected_signed:
            raise SuphxO0ScreenError("DEV signed utility drift")
        if semantic_replay:
            expected_row = _comparison_round(
                comparison=str(row["comparison"]),
                index=index,
                deal_seed=int(row["deal_seed"]),
                flip=int(row["flip"]),
                candidate_model=candidate_model,
                reference_model=reference_model,
                candidate_ref=candidate_ref,
                reference_ref=reference_ref,
                candidate_gamma=candidate_gamma,
                reference_gamma=reference_gamma,
            )
            if _canonical_json(dict(row)) != _canonical_json(expected_row):
                raise SuphxO0ScreenError(
                    f"DEV semantic replay mismatch for {key}")
            replayed += 1
            if replayed % 64 == 0 or replayed == replay_total:
                print(
                    f"PROGRESS O0 DEV replay seed={index} "
                    f"{replayed}/{replay_total}",
                    flush=True)
        grouped[str(row["comparison"])].append(row)
    expected_keys = {
        (comparison, deal, flip)
        for comparison in COMPARISONS
        for deal in range(DEV_SEED0, DEV_SEED0 + DEV_DEALS)
        for flip in (0, 1)
    }
    if seen != expected_keys:
        raise SuphxO0ScreenError("DEV raw population drift")
    by_comparison = {
        comparison: _exact_two_flip_means(grouped[comparison])
        for comparison in COMPARISONS
    }
    ref.verify()
    return ref, by_comparison, dict(payload)


def _student_t_summary(values: Sequence[float]) -> dict[str, float | int]:
    if len(values) != DEV_DEALS \
            or any(not math.isfinite(float(value)) for value in values):
        raise SuphxO0ScreenError("primary inference cluster population drift")
    array = np.asarray(values, dtype=np.float64)
    mean = float(array.mean())
    se = float(array.std(ddof=1) / math.sqrt(len(array)))
    half = T_CRITICAL_DF127 * se
    return {
        "n": len(values),
        "mean": mean,
        "se": se,
        "one_sided_alpha": ONE_SIDED_ALPHA,
        "df": len(values) - 1,
        "critical_value": T_CRITICAL_DF127,
        "lcb": mean - half,
    }


def _compute_gate(root: str | Path, *, semantic_replay: bool) -> dict[str, Any]:
    root = _require_run_root(root)
    packet_ref, admission_ref, _ = _require_admission(root)
    inputs: dict[str, Any] = {
        "packet": packet_ref.as_dict(),
        "admission": admission_ref.as_dict(),
        "training": {},
        "dev": {},
    }
    by_seed: dict[int, dict[str, dict[int, float]]] = {}
    seed_means: dict[str, dict[str, float]] = {}
    training_surface_health = True
    entropy_health = True
    oracle_witness_health = True
    public_invariance_health = True
    finite_health = True
    diagnostic_summary: dict[str, Any] = {}
    for index in range(len(SEED_IDENTITIES)):
        inputs["training"][str(index)] = {}
        for arm in ARMS:
            train_ref, _, training = _load_training(root, index, arm)
            inputs["training"][str(index)][arm] = train_ref.as_dict()
            counts = training["surface_counts"]
            training_surface_health = training_surface_health and all(
                isinstance(counts.get(surface), int)
                and counts[surface] > 0
                for surface in EXPECTED_SURFACES)
            finite_health = finite_health and (
                training.get("model_finite") is True
                and all(math.isfinite(float(value))
                        for value in training["entropy_controller"].values()))
        dev_ref, comparisons, dev = _load_dev_result(
            root, index, semantic_replay=semantic_replay)
        inputs["dev"][str(index)] = dev_ref.as_dict()
        by_seed[index] = comparisons
        diagnostics = dev["diagnostics"]
        diagnostic_summary[str(index)] = diagnostics
        for arm in ARMS:
            for surface in EXPECTED_SURFACES:
                cell = diagnostics["entropy"][arm][surface]
                entropy_health = entropy_health and (
                    cell.get("states") == DEV_DEALS // len(EXPECTED_SURFACES)
                    and float(cell.get("median_normalized_entropy"))
                    >= ENTROPY_FLOOR)
        oracle_witness_health = oracle_witness_health and all(
            float(diagnostics[
                "oracle_hidden_hand_logit_max_abs_difference"][surface]) > 0.0
            and float(diagnostics[
                "oracle_hidden_burial_logit_max_abs_difference"][surface])
            > 0.0
            and int(diagnostics["hidden_burial_witness_counts"][surface]) > 0
            for surface in EXPECTED_SURFACES)
        public_invariance_health = public_invariance_health and all(
            diagnostics[
                "public_hidden_hand_permutation_exact"][surface] is True
            and diagnostics[
                "public_hidden_burial_permutation_exact"][surface] is True
            for surface in EXPECTED_SURFACES)
        seed_means[str(index)] = {
            comparison: float(np.mean(list(comparisons[comparison].values())))
            for comparison in COMPARISONS
        }

    expected_deals = set(range(DEV_SEED0, DEV_SEED0 + DEV_DEALS))
    cluster_values: dict[str, list[float]] = {
        comparison: [] for comparison in COMPARISONS}
    null_exact = True
    for deal in sorted(expected_deals):
        for comparison in COMPARISONS:
            values = [by_seed[index][comparison][deal] for index in range(3)]
            cluster_values[comparison].append(float(np.mean(values)))
            if comparison == "same_model_null":
                null_exact = null_exact and all(value == 0.0 for value in values)
    primary = {
        comparison: _student_t_summary(cluster_values[comparison])
        for comparison in ("oracle_minus_initial", "oracle_minus_public")
    }
    criteria = {
        "exact_packet_admission_training_and_dev_reopen": True,
        "exact_same_model_two_flip_null_zero": null_exact,
        "all_training_seed_arm_surfaces_observed": training_surface_health,
        "all_terminal_models_and_controllers_finite": finite_health,
        "all_seed_arm_surface_entropy_medians_at_least_0_35": entropy_health,
        "all_seed_oracle_surfaces_have_legal_hand_and_burial_logit_witness":
            oracle_witness_health,
        "all_seed_public_surfaces_are_legal_hand_and_burial_invariant":
            public_invariance_health,
        "oracle_minus_initial_deal_cluster_lcb_positive":
            float(primary["oracle_minus_initial"]["lcb"]) > 0.0,
        "oracle_minus_public_deal_cluster_lcb_positive":
            float(primary["oracle_minus_public"]["lcb"]) > 0.0,
        "every_seed_oracle_minus_initial_mean_positive": all(
            seed_means[str(index)]["oracle_minus_initial"] > 0.0
            for index in range(3)),
        "every_seed_oracle_minus_public_mean_positive": all(
            seed_means[str(index)]["oracle_minus_public"] > 0.0
            for index in range(3)),
    }
    passed = all(criteria.values())
    failures = sorted(name for name, value in criteria.items() if not value)
    return {
        "schema": GATE_SCHEMA,
        "screen_schema": SCREEN_SCHEMA,
        "root": str(root),
        "inputs": inputs,
        "fixed_ensemble_estimand": True,
        "seed_comparison_means": seed_means,
        "deal_cluster_primary": primary,
        "same_model_null": {
            "exact_zero_every_seed_deal": null_exact,
            "cluster_mean": float(np.mean(
                cluster_values["same_model_null"])),
        },
        "diagnostics": diagnostic_summary,
        "criteria": criteria,
        "failures": failures,
        "verdict": "PASS" if passed else "SELECT_NONE",
        "passed_oracle_acquisition": passed,
        "authorizes_o1_freeze_and_independent_review": passed,
        "authorizes_o1_training": False,
        "strength_claim": False,
        "production_promotion": False,
    }


def run_gate(root: str | Path) -> CheckpointRef:
    root = _require_run_root(root)
    payload = _compute_gate(root, semantic_replay=True)
    ref = _publish_json(root / "gate.json", payload)
    verify_gate(ref, semantic_replay=False)
    return ref


def _walk_refs(value: object):
    if isinstance(value, Mapping):
        if set(value) == {"path", "sha256"}:
            yield _ref(value, label="gate input")
        else:
            for child in value.values():
                yield from _walk_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_refs(child)


def verify_gate(
        ref: CheckpointRef, *, semantic_replay: bool = True) -> dict[str, Any]:
    payload = _load_json(ref)
    expected_fields = {
        "schema", "screen_schema", "root", "inputs",
        "fixed_ensemble_estimand", "seed_comparison_means",
        "deal_cluster_primary", "same_model_null", "diagnostics", "criteria",
        "failures", "verdict", "passed_oracle_acquisition",
        "authorizes_o1_freeze_and_independent_review",
        "authorizes_o1_training", "strength_claim", "production_promotion",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_fields \
            or payload.get("schema") != GATE_SCHEMA \
            or payload.get("screen_schema") != SCREEN_SCHEMA \
            or payload.get("fixed_ensemble_estimand") is not True \
            or payload.get("verdict") not in {"PASS", "SELECT_NONE"} \
            or payload.get("authorizes_o1_training") is not False \
            or payload.get("strength_claim") is not False \
            or payload.get("production_promotion") is not False:
        raise SuphxO0ScreenError("terminal O0 gate identity/authority drift")
    root = _require_run_root(str(payload.get("root")))
    if Path(ref.path).resolve() != root / "gate.json":
        raise SuphxO0ScreenError("terminal O0 gate is outside its exact path")
    for artifact in _walk_refs(payload.get("inputs")):
        artifact.verify()
    recomputed = _compute_gate(
        root, semantic_replay=semantic_replay)
    if payload != recomputed:
        raise SuphxO0ScreenError("terminal O0 gate recomputation drift")
    passed = payload["verdict"] == "PASS"
    if payload.get("passed_oracle_acquisition") is not passed \
            or payload.get("authorizes_o1_freeze_and_independent_review") \
            is not passed \
            or passed is not all(payload["criteria"].values()) \
            or payload.get("failures") != sorted(
                name for name, value in payload["criteria"].items()
                if not value):
        raise SuphxO0ScreenError("terminal O0 gate verdict arithmetic drift")
    ref.verify()
    return dict(payload)


def _print_ref(label: str, ref: CheckpointRef) -> None:
    print(json.dumps({label: ref.as_dict()}, sort_keys=True), flush=True)


def cli_main(argv: list[str] | None = None) -> int:
    torch.use_deterministic_algorithms(True, warn_only=False)
    parser = argparse.ArgumentParser(
        description="Frozen fixed-ensemble Suphx O0 oracle-acquisition screen")
    sub = parser.add_subparsers(dest="command", required=True)

    freeze = sub.add_parser("freeze")
    freeze.add_argument("--root", required=True)
    verify_packet_parser = sub.add_parser("verify-packet")
    verify_packet_parser.add_argument("--packet", required=True)
    admit = sub.add_parser("admit")
    admit.add_argument("--root", required=True)
    admit.add_argument("--expected-packet-sha256", required=True)
    admit.add_argument("--review-record", required=True)
    admit.add_argument("--expected-review-sha256", required=True)
    train = sub.add_parser("train")
    train.add_argument("--root", required=True)
    train.add_argument("--seed-index", type=int, required=True)
    train.add_argument("--arm", choices=ARMS, required=True)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--root", required=True)
    evaluate.add_argument("--seed-index", type=int, required=True)
    gate = sub.add_parser("gate")
    gate.add_argument("--root", required=True)
    verify_gate_parser = sub.add_parser("verify-gate")
    verify_gate_parser.add_argument("--gate", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            _print_ref("launch_packet", freeze_packet(args.root))
            return 0
        if args.command == "verify-packet":
            packet_ref = CheckpointRef.capture(
                _require_regular_final(args.packet))
            verify_packet(packet_ref, semantic_replay=True)
            _print_ref("verified_packet", packet_ref)
            return 0
        if args.command == "admit":
            root = Path(args.root).resolve()
            packet_ref = CheckpointRef.capture(
                _require_regular_final(_packet_path(root)))
            ref = admit_packet(
                packet_ref,
                expected_packet_sha256=args.expected_packet_sha256,
                review_record=args.review_record,
                expected_review_sha256=args.expected_review_sha256,
            )
            _print_ref("review_admission", ref)
            return 0
        if args.command == "train":
            _print_ref("training_manifest", train_arm(
                args.root, args.seed_index, args.arm))
            return 0
        if args.command == "evaluate":
            _print_ref("dev_result", evaluate_seed(
                args.root, args.seed_index))
            return 0
        if args.command == "gate":
            ref = run_gate(args.root)
            payload = _load_json(ref)
            print(json.dumps({
                "gate": ref.as_dict(),
                "verdict": payload["verdict"],
                "authorizes_o1_freeze_and_independent_review": payload[
                    "authorizes_o1_freeze_and_independent_review"],
                "authorizes_o1_training": False,
                "strength_claim": False,
                "production_promotion": False,
            }, sort_keys=True), flush=True)
            return 0 if payload["verdict"] == "PASS" else 4
        gate_ref = CheckpointRef.capture(
            _require_regular_final(args.gate))
        payload = verify_gate(gate_ref)
        print(json.dumps({
            "verified": True,
            "verdict": payload["verdict"],
            "authorizes_o1_training": False,
            "strength_claim": False,
            "production_promotion": False,
        }, sort_keys=True), flush=True)
        return 0 if payload["verdict"] == "PASS" else 4
    except (FileExistsError, OSError, ValueError, subprocess.SubprocessError,
            SuphxO0ScreenError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 3
