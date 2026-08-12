#!/usr/bin/env python3
"""Freeze and verify the score-free H0-v3 execution controller.

H0 asks a deliberately narrow question: when a human, frozen V11pair, or a
matched random proposer supplies a move outside the live report-LCB ballot,
does that move survive a fair counterfactual comparison?  The reviewed v3
design fixes the population, candidate caps, three independent world streams,
continuation policy, and maximum work.  This module turns that paper contract
into an executable, fail-closed controller without running the experiment.

``freeze`` and ``verify`` are score-free.  They reopen the exact reviewed
design, human corpus, source-log snapshot, V11 checkpoint, and live champion;
replay all 557 selected decisions; build every candidate union; and publish
only candidate/work geometry.  They never sample a belief world, roll out an
action, consume outcome fields, create a label, train, promote, or deploy.

The frozen packet also specifies the future one-shot shard/result schemas and
terminal verification rules.  Counterfactual execution remains disabled until
an independent controller review publishes a separate exact PASS marker.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import stat
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import h0_human_counterfactual_packet as DESIGN  # noqa: E402
import live_champion_parent as LIVE_PARENT  # noqa: E402
from shengji.ai.bury import structured_bury_ballot  # noqa: E402
from shengji.ai.memory import Memory  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.ai.smart import SmartBot  # noqa: E402
from shengji.engine.cards import total_points  # noqa: E402
from shengji.engine.round import KITTY_SIZE, Round  # noqa: E402
from shengji.rl.actions import enumerate_actions  # noqa: E402
from shengji.rl.bc_generate import round_value  # noqa: E402
from shengji.rl.encode import encode_action, encode_obs  # noqa: E402
from shengji.rl.replay_log import group_rounds, rebuild_round  # noqa: E402
from shengji.rl.torch_policy import _load_npnet  # noqa: E402


SCHEMA = "human-h0-counterfactual-controller-v3"
PACKET_ID = "human-v8-h0-counterfactual-controller-v3"
RUN_ID = "human-v8-h0-counterfactual-execution-v3"
SHARD_SCHEMA = "human-h0-counterfactual-shard-v3"
AGGREGATE_SCHEMA = "human-h0-counterfactual-aggregate-v3"
REVIEW_SCHEMA = "human-h0-counterfactual-controller-review-v3"
REVIEW_MARKER = "H0_HUMAN_COUNTERFACTUAL_CONTROLLER_V3_REVIEW "
RECEIPT_SCHEMA = "human-h0-counterfactual-execution-receipt-v3"
ADMISSION_SCHEMA = "human-h0-counterfactual-admission-slot-v3"
SHARD_COUNT = 8

SAMPLER_FLAGS = (
    "SHENGJI_WEIGHTED_SPLITS",
    "SHENGJI_UNIFORM_DEAL",
    "SHENGJI_PHYSICAL_FILLS",
    "SHENGJI_ALLOW_BALLOT_MISMATCH",
)

DESIGN_PACKET_LOGICAL_PATH = (
    "server/runs/logs/human-v8-h0-counterfactual-pilot-v3/"
    "design_packet.json"
)
DESIGN_PACKET_SHA256 = (
    "4d3f0a35082c6957f2a468686b8eedbd6d7cbbf9540503fcea08cccf27c8cc3c"
)
DESIGN_PACKET_INTERNAL_SHA256 = (
    "63377cad2e39c80d0e4867b253d287b1095ed066131c2b409ca3fe82f5ed68d4"
)
DESIGN_PACKET_GIT = "d6214ceae7c3f0ddb0c00f67d92b71f32ba579f7"
DESIGN_PRODUCER_GIT = "b02b6deb1ef0bda44eaf10ea349cb050355a7f15"
DESIGN_REVIEW_GIT = "239f13ce52a8be81108fdebf9bd0e96742e60133"
DESIGN_REVIEW_SCHEMA = "human-h0-counterfactual-design-review-v3"
DESIGN_REVIEW_MARKER = "H0_HUMAN_COUNTERFACTUAL_DESIGN_V3_REVIEW "
CORPUS_MANIFEST_SHA256 = (
    "b9699790bdfe1c217922c9f9c72b237c1856174fa64c11753329a8ff11e16553"
)
SOURCE_MANIFEST_SHA256 = (
    "07ff18fb35f2fb987f18b37b5100172e2751681fbfed17285ce7d7035232aa5e"
)
SELECTED_PLAY_ROWS_SHA256 = (
    "18673b20ca0a5b1a8e476f3bcf45cf9d08f90f4244f9c5ee07cb8bd8cd47711d"
)
SELECTED_BURY_ROWS_SHA256 = (
    "cdfe77dfbec0e97fb8935c5822239acd6db60c644c433c32a4445913459aa1e8"
)
V11PAIR_SHA256 = DESIGN.V11PAIR_SHA256
MAX_CANDIDATE_WORLDS = DESIGN.TOTAL_MAX_CANDIDATE_WORLDS

SOURCE_PATHS = (
    ".gitignore",
    "server/scripts/h0_human_counterfactual_runtime.py",
    "server/scripts/h0_human_counterfactual_packet.py",
    "server/scripts/live_champion_parent.py",
    "server/shengji/ai/bury.py",
    "server/shengji/ai/heuristic.py",
    "server/shengji/ai/mcbot.py",
    "server/shengji/ai/memory.py",
    "server/shengji/ai/registry.py",
    "server/shengji/ai/smart.py",
    "server/shengji/engine/ballot.py",
    "server/shengji/engine/cards.py",
    "server/shengji/engine/combos.py",
    "server/shengji/engine/game.py",
    "server/shengji/engine/legal.py",
    "server/shengji/engine/round.py",
    "server/shengji/rl/actions.py",
    "server/shengji/rl/bc_generate.py",
    "server/shengji/rl/encode.py",
    "server/shengji/rl/npnet.py",
    "server/shengji/rl/replay_log.py",
    "server/shengji/rl/torch_policy.py",
)


class ControllerRefused(RuntimeError):
    """The H0 controller or one of its immutable inputs drifted."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ControllerRefused(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ControllerRefused(f"JSON root is not an object: {path}")
    return value


def _load_jsonl(path: Path) -> list[dict]:
    try:
        rows = [json.loads(line) for line in path.read_text().splitlines()
                if line.strip()]
    except (OSError, ValueError) as exc:
        raise ControllerRefused(f"cannot read JSONL {path}: {exc}") from exc
    if any(not isinstance(row, dict) for row in rows):
        raise ControllerRefused(f"non-object JSONL row: {path}")
    return rows


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout.strip()


def admission_slot_logical_path() -> str:
    return f"server/runs/locks/{RUN_ID}.consumed.json"


def require_admission_slot_ignored() -> dict:
    """Prove the sole expected runtime mutation is outside Git status.

    The exact ``.gitignore`` bytes are part of ``SOURCE_PATHS``.  We still
    verify the concrete v3 path here so a broad or stale cleanliness assumption
    cannot strand a one-shot admission after its durable tombstone is written.
    """
    logical_path = admission_slot_logical_path()
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", logical_path], cwd=REPO,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ControllerRefused(
            f"admission slot is not Git-ignored: {logical_path}")
    return {"logical_path": logical_path, "gitignored": True}


def require_clean_tree(message: str) -> None:
    """Reject every tracked or unignored untracked mutation."""
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise ControllerRefused(message)


def producer_identity(*, smoke: bool) -> dict:
    git = _git("rev-parse", "HEAD")
    require_admission_slot_ignored()
    dirty = bool(_git("status", "--porcelain", "--untracked-files=all"))
    if dirty and not smoke:
        raise ControllerRefused("real controller freeze refuses a dirty tree")
    return {
        "git": git,
        "tree_dirty": dirty,
        "script_sha256": sha256_file(SCRIPT),
        "promotable": not smoke,
    }


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    partial = Path(str(path) + ".partial")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path) or os.path.lexists(partial):
        raise ControllerRefused(f"refusing to overwrite {path}")
    try:
        with partial.open("xb") as handle:
            handle.write(canonical_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(partial, path)
        partial.unlink()
    except BaseException:
        if partial.exists() and not path.exists():
            partial.unlink()
        raise
    if not is_regular_unlinked(path):
        raise ControllerRefused("published artifact is not regular/unlinked")


def action_key(action: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(str(card) for card in action))


def row_key(split: str, surface: str, replay_key: str) -> str:
    return f"{split}|{surface}|{replay_key}"


def seed_for(domain: bytes, split: str, replay_key: str,
             surface: str, purpose: str) -> int:
    payload = canonical_json([split, replay_key, surface, purpose])
    return int.from_bytes(hashlib.sha256(domain + payload).digest()[:8], "big")


def attacker_level_utility(attacker_points: float) -> float:
    """Return the terminal level reward, including the +/- deal half-level."""
    points = float(attacker_points)
    if not math.isfinite(points) or points < 0:
        raise ControllerRefused("non-finite/negative attacker points")
    if not points.is_integer():
        raise ControllerRefused("attacker points must be integral")
    return float(round_value(int(points)))


def acting_utility(attacker_points: float, *, attacker: bool) -> float:
    value = attacker_level_utility(attacker_points)
    return value if attacker else -value


def _marker_claim(path: Path, marker: str) -> dict:
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise ControllerRefused(f"cannot read review record: {exc}") from exc
    matches = [line[len(marker):] for line in lines if line.startswith(marker)]
    if len(matches) != 1:
        raise ControllerRefused(
            f"review record must contain exactly one {marker.strip()} marker")
    try:
        claim = json.loads(matches[0])
    except ValueError as exc:
        raise ControllerRefused("review marker is not valid JSON") from exc
    if not isinstance(claim, dict):
        raise ControllerRefused("review marker claim is not an object")
    return claim


def require_design_review(path: Path) -> dict:
    claim = _marker_claim(path, DESIGN_REVIEW_MARKER)
    expected = {
        "schema": DESIGN_REVIEW_SCHEMA,
        "git": DESIGN_PACKET_GIT,
        "producer_git": DESIGN_PRODUCER_GIT,
        "packet_sha256": DESIGN_PACKET_SHA256,
        "superseded_v2_packet_sha256": DESIGN.V2_PACKET_SHA256,
        "corpus_manifest_sha256": CORPUS_MANIFEST_SHA256,
        "v11_checkpoint_sha256": V11PAIR_SHA256,
        "live_parent_authenticator_sha256": DESIGN.LIVE_PARENT_AUTH_SHA256,
        "selected_play_rows_sha256": SELECTED_PLAY_ROWS_SHA256,
        "selected_bury_rows_sha256": SELECTED_BURY_ROWS_SHA256,
        "play_candidate_cap": DESIGN.PLAY_MAX_UNIQUE_CANDIDATES,
        "bury_candidate_cap": DESIGN.BURY_MAX_UNIQUE_CANDIDATES,
        "max_candidate_worlds": MAX_CANDIDATE_WORLDS,
        "design_plays": DESIGN.PLAY_TARGETS["DESIGN"],
        "audit_plays": DESIGN.PLAY_TARGETS["AUDIT"],
        "design_buries": DESIGN.BURY_TARGETS["DESIGN"],
        "audit_buries": DESIGN.BURY_TARGETS["AUDIT"],
        "outcomes_computed": False,
        "independent_review": True,
        "execution_controller_implementation_authorized": True,
        "counterfactual_execution_authorized": False,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "verdict": "PASS",
    }
    if claim != expected:
        raise ControllerRefused("H0-v3 design review marker drift")
    return claim


def validate_design_packet(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise ControllerRefused("design packet is not regular/unlinked")
    if sha256_file(path) != DESIGN_PACKET_SHA256:
        raise ControllerRefused("H0-v3 design packet SHA-256 drift")
    packet = _load_json(path)
    if (packet.get("schema") != DESIGN.SCHEMA
            or packet.get("packet_id") != DESIGN.PACKET_ID
            or packet.get("packet_sha256") != DESIGN_PACKET_INTERNAL_SHA256
            or packet.get("producer", {}).get("git") != DESIGN_PRODUCER_GIT
            or packet.get("human_corpus", {}).get("manifest_sha256") !=
            CORPUS_MANIFEST_SHA256
            or packet.get("human_corpus", {}).get("source_manifest_sha256") !=
            SOURCE_MANIFEST_SHA256
            or packet.get("split_contract", {}).get(
                "selected_play_rows_sha256") != SELECTED_PLAY_ROWS_SHA256
            or packet.get("split_contract", {}).get("bury_surface", {}).get(
                "selected_bury_rows_sha256") != SELECTED_BURY_ROWS_SHA256):
        raise ControllerRefused("H0-v3 design identity drift")
    authority = packet.get("authority")
    if authority != {
        "score_free": True,
        "outcomes_computed": False,
        "design_review_authorized": True,
        "execution_controller_implementation_authorized": False,
        "counterfactual_execution_authorized": False,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "human_evaluation_data_may_train_or_select": False,
    }:
        raise ControllerRefused("H0-v3 design authority drift")
    execution = packet.get("counterfactual_execution_required", {})
    work = execution.get("work_ceiling", {})
    if (execution.get("belief_sampler") != "strict-public-history-v1"
            or execution.get("rollout_continuation", {}).get("policy") !=
            "HeuristicBot"
            or execution.get("pilot_selection", {}).get("worlds") != 30
            or execution.get("pilot_report", {}).get("worlds") != 300
            or work.get("all_rows_max_candidate_worlds") !=
            MAX_CANDIDATE_WORLDS):
        raise ControllerRefused("H0-v3 execution contract drift")
    return packet


def _source_manifest_members(path: Path) -> dict[str, str]:
    if not is_regular_unlinked(path):
        raise ControllerRefused("source manifest is not regular/unlinked")
    if sha256_file(path) != SOURCE_MANIFEST_SHA256:
        raise ControllerRefused("source manifest SHA-256 drift")
    members: dict[str, str] = {}
    for line_no, line in enumerate(path.read_text().splitlines(), 1):
        fields = line.split(maxsplit=1)
        if (len(fields) != 2 or not is_sha256(fields[0])
                or Path(fields[1].lstrip("* ")).name != fields[1].lstrip("* ")):
            raise ControllerRefused(
                f"malformed source manifest line {line_no}")
        name = fields[1].lstrip("* ")
        if name in members:
            raise ControllerRefused(f"duplicate source member {name}")
        members[name] = fields[0]
    if not members:
        raise ControllerRefused("empty source manifest")
    return members


def validate_inputs(design_packet: dict, corpus: Path, source_root: Path,
                    source_manifest: Path, v11_checkpoint: Path
                    ) -> tuple[dict, list[dict], list[dict], list[dict]]:
    manifest, plays, buries = DESIGN.validate_corpus(
        corpus, CORPUS_MANIFEST_SHA256)
    if manifest.get("source_manifest_sha256") != SOURCE_MANIFEST_SHA256:
        raise ControllerRefused("corpus source-manifest identity drift")
    members = _source_manifest_members(source_manifest)
    source_records = manifest.get("sources")
    if not isinstance(source_records, list):
        raise ControllerRefused("corpus source catalog missing")
    expected = {
        item.get("name"): item for item in source_records
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if set(expected) != set(members) or len(expected) != len(source_records):
        raise ControllerRefused("corpus/source-manifest population drift")
    catalog = []
    for name in sorted(members):
        item = expected[name]
        path = source_root / name
        if (not is_regular_unlinked(path)
                or members[name] != item.get("sha256")
                or sha256_file(path) != members[name]
                or path.stat().st_size != item.get("bytes")
                or item.get("fly_snapshot_member") is not True):
            raise ControllerRefused(f"source snapshot drift: {name}")
        catalog.append({
            "name": name,
            "sha256": members[name],
            "bytes": path.stat().st_size,
        })
    if (not is_regular_unlinked(v11_checkpoint)
            or sha256_file(v11_checkpoint) != V11PAIR_SHA256):
        raise ControllerRefused("V11pair checkpoint drift")

    selected_plays = design_packet["split_contract"]["selected"]
    selected_buries = design_packet["split_contract"]["bury_surface"]["selected"]
    play_by_key = {DESIGN.play_key(row): row for row in plays}
    bury_by_key = {DESIGN.bury_key(row): row for row in buries}
    for split in ("DESIGN", "AUDIT"):
        if len(selected_plays.get(split, [])) != DESIGN.PLAY_TARGETS[split]:
            raise ControllerRefused(f"{split} selected play count drift")
        if len(selected_buries.get(split, [])) != DESIGN.BURY_TARGETS[split]:
            raise ControllerRefused(f"{split} selected bury count drift")
        for row in selected_plays[split]:
            source = play_by_key.get(row.get("replay_key"))
            if source is None or DESIGN._row_record(source) != row:
                raise ControllerRefused("selected play no longer matches corpus")
        for row in selected_buries[split]:
            source = bury_by_key.get(row.get("replay_key"))
            if source is None or DESIGN._bury_record(source) != row:
                raise ControllerRefused("selected bury no longer matches corpus")
    return manifest, plays, buries, catalog


class ReplayCache:
    """Read each immutable source log once while replaying selected rows."""

    def __init__(self, source_root: Path):
        self.source_root = source_root
        self._rounds: dict[str, dict[int, list[dict]]] = {}

    def events(self, source: str, round_no: int) -> list[dict]:
        if source not in self._rounds:
            self._rounds[source] = group_rounds(str(self.source_root / source))
        try:
            return self._rounds[source][round_no]
        except KeyError as exc:
            raise ControllerRefused(
                f"missing source round {source}:round-{round_no}") from exc


def replay_play(cache: ReplayCache, row: Mapping[str, object]) -> Round:
    events = cache.events(str(row["source"]), int(row["round"]))
    rnd = rebuild_round(events)
    if rnd is None:
        raise ControllerRefused("selected play source lacks complete setup")
    trick_no = 0
    target = int(row["event_index"])
    for event_index, event in enumerate(events):
        if event.get("e") != "play" or rnd.phase != "play":
            continue
        if rnd.trick is not None and not rnd.trick.plays:
            trick_no += 1
        if event_index == target:
            expected = {
                "seat": row["seat"],
                "cards": action_key(row["human_action"]),
                "surface": row["surface"],
                "role": row["role"],
                "trick": row["trick"],
                "cards_remaining": row["cards_remaining"],
            }
            actual = {
                "seat": event.get("seat"),
                "cards": action_key(event.get("cards", [])),
                "surface": "lead" if not rnd.trick.plays else "follow",
                "role": "attacker" if rnd.is_attacker(rnd.turn) else "defender",
                "trick": trick_no,
                "cards_remaining": sum(len(hand) for hand in rnd.hands),
            }
            if rnd.turn != row["seat"] or actual != expected:
                raise ControllerRefused("selected play replay identity drift")
            clone = copy.deepcopy(rnd)
            try:
                clone.play(int(row["seat"]), list(row["human_action"]))
            except Exception as exc:
                raise ControllerRefused(
                    f"selected human action is replay-illegal: {exc}") from exc
            return rnd
        try:
            rnd.play(int(event["seat"]), list(event["cards"]))
        except Exception as exc:
            raise ControllerRefused(
                f"source play before selected row is invalid: {exc}") from exc
    raise ControllerRefused("selected play event index not reached")


def replay_bury(cache: ReplayCache, row: Mapping[str, object]) -> Round:
    events = cache.events(str(row["source"]), int(row["round"]))
    start = next((event for event in events
                  if event.get("e") == "round_start"), None)
    trump = next((event for event in events if event.get("e") == "trump"), None)
    bury = next((event for event in events if event.get("e") == "bury"), None)
    if start is None or trump is None or bury is None:
        raise ControllerRefused("selected bury source lacks complete setup")
    rnd = Round(start["trump_rank"], start["banker"], random.Random(0))
    rnd.deck = list(start["deck"])
    rnd.hands = [[], [], [], []]
    rnd._deal_pos = 0
    rnd.phase = "deal"
    rnd.kitty = list(start["deck"][100:])
    while rnd.phase == "deal":
        rnd.deal_next()
    for event in events:
        if event.get("e") == "declare":
            rnd.declare(int(event["seat"]), list(event["cards"]))
    rnd.finalize_declare()
    expected = {
        "seat": row["seat"],
        "cards": action_key(row["human_bury"]),
        "banker": row["banker"],
        "trump_rank": row["trump_rank"],
        "trump_suit": row["trump_suit"],
        "trump_is_nt": row["trump_is_nt"],
        "point_total": row["point_total"],
    }
    actual = {
        "seat": bury.get("seat"),
        "cards": action_key(bury.get("cards", [])),
        "banker": rnd.banker,
        "trump_rank": rnd.trump_rank,
        "trump_suit": rnd.trump_suit,
        "trump_is_nt": rnd.trump_is_nt,
        "point_total": total_points(bury.get("cards", [])),
    }
    if (actual != expected or rnd.turn != row["seat"]
            or rnd.phase != "bury" or len(row["human_bury"]) != KITTY_SIZE):
        raise ControllerRefused("selected bury replay identity drift")
    clone = copy.deepcopy(rnd)
    try:
        clone.bury(int(row["seat"]), list(row["human_bury"]))
    except Exception as exc:
        raise ControllerRefused(
            f"selected human bury is replay-illegal: {exc}") from exc
    return rnd


def _dedupe_actions(actions: Iterable[Sequence[str]]) -> list[list[str]]:
    seen: set[tuple[str, ...]] = set()
    result = []
    for action in actions:
        key = action_key(action)
        if key not in seen:
            seen.add(key)
            result.append(list(key))
    return result


def build_play_union(rnd: Round, seat: int, human_action: Sequence[str],
                     split: str, replay_key_value: str, net,
                     production_bot=None) -> tuple[list[dict], dict]:
    bot = production_bot or make_bot("mc-s0-report-lcb", seed=0)
    live = _dedupe_actions(bot._candidates(rnd, seat))
    cap = (DESIGN.LIVE_LEAD_MAX_CANDIDATES if not rnd.trick.plays else
           DESIGN.LIVE_FOLLOW_MAX_CANDIDATES)
    if not live or len(live) > cap:
        raise ControllerRefused("live production ballot cap/emptiness drift")
    human = list(action_key(human_action))
    exhaustive = sorted(
        (action_key(action) for action in enumerate_actions(
            rnd, seat, exhaustive_follows=True, include_throws=True)),
    )
    exhaustive = list(dict.fromkeys(exhaustive))
    if action_key(human) not in exhaustive:
        # The reviewed corpus explicitly permits actions absent from the
        # bounded analysis enumeration, but the engine replay above proves
        # legality. Include the action as the human source only; it does not
        # enter the V11/random novel pool by self-reference.
        exhaustive.append(action_key(human))
        exhaustive.sort()
    live_keys = {action_key(action) for action in live}
    human_key = action_key(human)
    novel_pool = [key for key in exhaustive
                  if key not in live_keys and key != human_key]

    v11_key = random_key = None
    values: list[float] = []
    if novel_pool:
        obs = encode_obs(rnd, seat)
        enc = [encode_action(list(key), rnd) for key in novel_pool]
        values = [float(value) for value in net.value_candidates(obs, enc)]
        if len(values) != len(novel_pool) or not all(map(math.isfinite, values)):
            raise ControllerRefused("V11 returned missing/non-finite scores")
        v11_index = max(range(len(novel_pool)), key=lambda index: values[index])
        v11_key = novel_pool[v11_index]
        proposal_seed = seed_for(
            DESIGN.PROPOSAL_SEED_DOMAIN, split, replay_key_value,
            "play", "matched-random",
        )
        random_key = random.Random(proposal_seed).choice(novel_pool)

    by_key: dict[tuple[str, ...], dict] = {}
    order: list[tuple[str, ...]] = []

    def add(action: Sequence[str], source: str) -> None:
        key = action_key(action)
        if key not in by_key:
            by_key[key] = {"cards": list(key), "sources": []}
            order.append(key)
        if source not in by_key[key]["sources"]:
            by_key[key]["sources"].append(source)

    for action in live:
        add(action, "live_production_ballot")
    add(human, "human_action")
    if v11_key is not None:
        add(v11_key, "v11pair_top_proposal")
        add(random_key, "matched_random_proposal")
    union = [by_key[key] for key in order]
    if len(union) > DESIGN.PLAY_MAX_UNIQUE_CANDIDATES:
        raise ControllerRefused("play candidate union exceeds reviewed cap")
    for candidate in union:
        candidate["sources"].sort()
    return union, {
        "live_candidates": len(live),
        "analysis_actions": len(exhaustive),
        "novel_pool": len(novel_pool),
        "human_in_live_ballot": human_key in live_keys,
        "v11_proposed": v11_key is not None,
        "random_proposed": random_key is not None,
        "v11_random_same": v11_key is not None and v11_key == random_key,
        "v11_score_count": len(values),
    }


def build_bury_union(rnd: Round, seat: int,
                     human_bury: Sequence[str]) -> tuple[list[dict], dict]:
    incumbent = SmartBot().decide_bury(rnd, seat)
    ballot = structured_bury_ballot(
        rnd.hands[seat], rnd.ordering, incumbent,
        max_candidates=DESIGN.BURY_STRUCTURED_MAX_CANDIDATES,
    )
    if (not ballot.candidates
            or action_key(ballot.candidates[0].cards) != action_key(incumbent)
            or len(ballot.candidates) > DESIGN.BURY_STRUCTURED_MAX_CANDIDATES):
        raise ControllerRefused("structured bury candidate-zero/cap drift")
    by_key: dict[tuple[str, ...], dict] = {}
    order: list[tuple[str, ...]] = []

    def add(cards: Sequence[str], sources: Iterable[str]) -> None:
        key = action_key(cards)
        if key not in by_key:
            by_key[key] = {"cards": list(key), "sources": []}
            order.append(key)
        for source in sources:
            if source not in by_key[key]["sources"]:
                by_key[key]["sources"].append(source)

    for candidate in ballot.candidates:
        add(candidate.cards, ("structured_bury_ballot", *candidate.sources))
    human_key = action_key(human_bury)
    add(human_key, ("human_action",))
    union = [by_key[key] for key in order]
    if len(union) > DESIGN.BURY_MAX_UNIQUE_CANDIDATES:
        raise ControllerRefused("bury candidate union exceeds reviewed cap")
    for candidate in union:
        candidate["sources"].sort()
    return union, {
        "structured_candidates": len(ballot.candidates),
        "structured_generated_unique": ballot.generated_unique,
        "structured_truncated": ballot.truncated,
        "human_in_structured_ballot": human_key in {
            action_key(candidate.cards) for candidate in ballot.candidates},
    }


def selected_rows(design_packet: dict) -> list[dict]:
    rows = []
    for split in ("DESIGN", "AUDIT"):
        for row in design_packet["split_contract"]["selected"][split]:
            rows.append({"split": split, "surface_type": "play", **row})
        for row in design_packet["split_contract"]["bury_surface"][
                "selected"][split]:
            rows.append({"split": split, "surface_type": "bury", **row})
    return sorted(rows, key=lambda row: row_key(
        row["split"], row["surface_type"], row["replay_key"]))


def build_schedule(design_packet: dict, shard_count: int = SHARD_COUNT) -> dict:
    if shard_count <= 0:
        raise ControllerRefused("shard count must be positive")
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in selected_rows(design_packet):
        groups[str(row["deal_key"])].append(row)
    weighted = []
    for deal, rows in groups.items():
        weight = sum(
            DESIGN.PLAY_MAX_CANDIDATE_WORLDS
            if row["surface_type"] == "play"
            else DESIGN.BURY_MAX_CANDIDATE_WORLDS
            for row in rows
        )
        weighted.append((weight, deal, rows))
    loads = [0] * shard_count
    assignments: dict[str, int] = {}
    for weight, deal, _rows in sorted(weighted, key=lambda item: (-item[0], item[1])):
        shard = min(range(shard_count), key=lambda index: (loads[index], index))
        assignments[deal] = shard
        loads[shard] += weight
    shards = []
    for shard in range(shard_count):
        rows = [row for row in selected_rows(design_packet)
                if assignments[str(row["deal_key"])] == shard]
        shards.append({
            "index": shard,
            "deal_keys": sorted({str(row["deal_key"]) for row in rows}),
            "row_keys": [row_key(row["split"], row["surface_type"],
                                 row["replay_key"]) for row in rows],
            "play_rows": sum(row["surface_type"] == "play" for row in rows),
            "bury_rows": sum(row["surface_type"] == "bury" for row in rows),
            "max_candidate_worlds": loads[shard],
        })
    if sum(loads) != MAX_CANDIDATE_WORLDS:
        raise ControllerRefused("schedule work ceiling does not reconcile")
    if len(assignments) != len(groups):
        raise ControllerRefused("schedule deal assignment drift")
    payload = {
        "cluster": "deal",
        "algorithm": "deterministic-largest-max-work-first",
        "shard_count": shard_count,
        "shards": shards,
    }
    payload["schedule_sha256"] = sha256_bytes(canonical_json(payload))
    return payload


def score_free_preflight(design_packet: dict, source_root: Path,
                         v11_checkpoint: Path) -> dict:
    cache = ReplayCache(source_root)
    net = _load_npnet(str(v11_checkpoint))
    counts: Counter[str] = Counter()
    candidate_hist: Counter[str] = Counter()
    cell_counts: Counter[str] = Counter()
    rows_digest = []
    for row in selected_rows(design_packet):
        split = row["split"]
        surface_type = row["surface_type"]
        key = row_key(split, surface_type, row["replay_key"])
        if surface_type == "play":
            rnd = replay_play(cache, row)
            union, diagnostics = build_play_union(
                rnd, int(row["seat"]), row["human_action"], split,
                row["replay_key"], net,
            )
            surface = str(row["surface"])
            role = str(row["role"])
            phase = str(row["phase"])
            counts["play_rows"] += 1
            counts["human_in_live_ballot"] += int(
                diagnostics["human_in_live_ballot"])
            counts["empty_novel_pool"] += int(diagnostics["novel_pool"] == 0)
            counts["v11_proposals"] += int(diagnostics["v11_proposed"])
            counts["random_proposals"] += int(diagnostics["random_proposed"])
            counts["v11_random_same"] += int(diagnostics["v11_random_same"])
            counts["analysis_actions"] += diagnostics["analysis_actions"]
            counts["novel_pool_actions"] += diagnostics["novel_pool"]
        else:
            rnd = replay_bury(cache, row)
            union, diagnostics = build_bury_union(
                rnd, int(row["seat"]), row["human_bury"])
            surface = "bury"
            role = "defender"
            phase = "pre-play"
            counts["bury_rows"] += 1
            counts["human_in_structured_ballot"] += int(
                diagnostics["human_in_structured_ballot"])
            counts["structured_generated_unique"] += diagnostics[
                "structured_generated_unique"]
            counts["structured_truncated"] += int(
                diagnostics["structured_truncated"])
        candidate_hist[f"{surface_type}:{len(union)}"] += 1
        cell_counts[f"{split}:{surface_type}:{surface}:{phase}:{role}"] += 1
        rows_digest.append({
            "row_key": key,
            "candidate_count": len(union),
            "candidate_keys": [candidate["cards"] for candidate in union],
            "candidate_sources": [candidate["sources"] for candidate in union],
        })
    if (counts["play_rows"] != sum(DESIGN.PLAY_TARGETS.values())
            or counts["bury_rows"] != sum(DESIGN.BURY_TARGETS.values())):
        raise ControllerRefused("score-free preflight row count drift")
    return {
        "status": "VERIFIED_SCORE_FREE",
        "rows_replayed": counts["play_rows"] + counts["bury_rows"],
        "counts": dict(sorted(counts.items())),
        "candidate_count_histogram": dict(sorted(candidate_hist.items())),
        "cell_counts": dict(sorted(cell_counts.items())),
        "candidate_geometry_sha256": sha256_bytes(canonical_json(rows_digest)),
        "worlds_sampled": 0,
        "candidate_world_rollouts": 0,
        "outcomes_computed": False,
    }


def runtime_sources() -> dict:
    sources = {path: sha256_file(REPO / path) for path in SOURCE_PATHS}
    sources[str(SCRIPT.relative_to(REPO))] = sha256_file(SCRIPT)
    from shengji.engine import fast
    fast_path = Path(fast._fast.__file__)
    sources["compiled_fast_binary"] = sha256_file(fast_path)
    return dict(sorted(sources.items()))


def require_execution_runtime() -> dict:
    """Reopen the exact sampler/native mode required by the H0 design.

    The v1 controller merely hashed whichever compiled binary happened to be
    importable.  It did not make the future runtime refuse pure Python or
    void-relaxed sampling.  This function is called both while freezing the
    score-free packet and every time the execution runtime opens that packet.
    """
    if os.environ.get("SHENGJI_FAST") != "1":
        raise ControllerRefused("set SHENGJI_FAST=1")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise ControllerRefused("set SHENGJI_REQUIRE_VOIDS=1")
    enabled = [name for name in SAMPLER_FLAGS if os.environ.get(name)]
    if enabled:
        raise ControllerRefused(
            f"experimental sampler/ballot flags must be unset: {enabled}")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise ControllerRefused("compiled engine requested but not active")
    return {
        "environment": {
            "SHENGJI_FAST": "1",
            "SHENGJI_REQUIRE_VOIDS": "1",
        },
        "experimental_sampler_flags": [],
        "fast_engine": True,
        "fast_router_sha256": sha256_file(fast.__file__),
        "compiled_fast_binary_sha256": sha256_file(fast._fast.__file__),
    }


def command_templates(schedule: dict) -> dict:
    shard_commands = []
    for shard in schedule["shards"]:
        shard_commands.append([
            "{python}", "server/scripts/h0_human_counterfactual_runtime.py",
            "run-shard", "--expected-git", "{git}",
            "--controller-packet", "{controller_packet}",
            "--expected-controller-packet-sha256", "{controller_packet_sha256}",
            "--execution-receipt", "{execution_receipt}",
            "--expected-execution-receipt-sha256", "{execution_receipt_sha256}",
            "--design-packet", "{design_packet}", "--corpus", "{corpus}",
            "--source-root", "{source_root}",
            "--source-manifest", "{source_manifest}",
            "--v11-checkpoint", "{v11_checkpoint}",
            "--shard-index", str(shard["index"]), "--out",
            f"server/runs/logs/{RUN_ID}/shard-{shard['index']:02d}.json",
        ])
    return {
        "admit_once": [
            "{python}", "server/scripts/h0_human_counterfactual_runtime.py",
            "admit", "--expected-git", "{git}",
            "--controller-packet", "{controller_packet}",
            "--expected-controller-packet-sha256", "{controller_packet_sha256}",
            "--review-record", "{controller_review_record}",
            "--design-packet", "{design_packet}", "--corpus", "{corpus}",
            "--source-root", "{source_root}",
            "--source-manifest", "{source_manifest}",
            "--v11-checkpoint", "{v11_checkpoint}",
            "--namespace", f"server/runs/logs/{RUN_ID}",
            "--out", f"server/runs/logs/{RUN_ID}/execution-receipt.json",
        ],
        "run_shards": shard_commands,
        "aggregate": [
            "{python}", "server/scripts/h0_human_counterfactual_runtime.py",
            "aggregate", "--expected-git", "{git}",
            "--controller-packet", "{controller_packet}",
            "--expected-controller-packet-sha256", "{controller_packet_sha256}",
            "--execution-receipt", "{execution_receipt}",
            "--expected-execution-receipt-sha256", "{execution_receipt_sha256}",
            "--shards", *[
                f"server/runs/logs/{RUN_ID}/shard-{index:02d}.json"
                for index in range(SHARD_COUNT)
            ], "--out", f"server/runs/logs/{RUN_ID}/aggregate.json",
        ],
        "terminal_verify": [
            "{python}", "server/scripts/h0_human_counterfactual_runtime.py",
            "verify-result", "--expected-git", "{git}",
            "--controller-packet", "{controller_packet}",
            "--expected-controller-packet-sha256", "{controller_packet_sha256}",
            "--execution-receipt", "{execution_receipt}",
            "--expected-execution-receipt-sha256", "{execution_receipt_sha256}",
            "--design-packet", "{design_packet}", "--corpus", "{corpus}",
            "--source-root", "{source_root}",
            "--source-manifest", "{source_manifest}",
            "--v11-checkpoint", "{v11_checkpoint}",
            "--shards", *[
                f"server/runs/logs/{RUN_ID}/shard-{index:02d}.json"
                for index in range(SHARD_COUNT)
            ], "--aggregate", f"server/runs/logs/{RUN_ID}/aggregate.json",
            "--replay-every-row",
        ],
    }


def result_contract(schedule: dict) -> dict:
    return {
        "durable_one_shot_admission_slot": admission_slot_logical_path(),
        "admission_slot_published_before_receipt": True,
        "receipt_deletion_cannot_reissue": True,
        "admission_slot_gitignored": True,
        "admit_then_runtime_reopen_required": True,
        "unrelated_git_dirt_refused": True,
        "shard_schema": SHARD_SCHEMA,
        "aggregate_schema": AGGREGATE_SCHEMA,
        "every_selected_row_exactly_once": True,
        "deal_cluster_never_crosses_shards": True,
        "row_states": ["COMPLETE", "REFUSED_SCORE_FREE"],
        "refused_row_forbids": [
            "candidates", "reference", "selection", "report",
            "raw_attacker_points", "utilities", "estimands",
        ],
        "refused_row_requires": (
            "exact outcome-free attempted-work and sampler counters"
        ),
        "complete_row_requires": {
            "play_reference": (
                "exact live report-LCB; <=14x30 selection + 2x300 report"
            ),
            "pilot_selection": "all deduplicated union actions x30 common worlds",
            "pilot_report": (
                "deduplicated reference/human/selected actions x300 fresh "
                "common worlds"
            ),
            "continuation": "HeuristicBot after the fixed root action",
            "metric": "acting-team-signed-level-utility",
        },
        "work": {
            "candidate_world_ceiling": MAX_CANDIDATE_WORLDS,
            "actual_work_recomputed_from_actions_and_accepted_worlds": True,
            "short_or_failed_fold_refuses_the_row": True,
            "no_row_replacement_or_resampling": True,
        },
        "completion_gate": {
            "all_shards_required": SHARD_COUNT,
            "any_refused_row": "REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY",
            "all_rows_complete": "PUBLISH_DIAGNOSTIC_ONLY",
            "audit_never_tunes_design": True,
            "no_promotion_gate": True,
        },
        "diagnostic_estimation": {
            "splits_reported_separately": ["DESIGN", "AUDIT"],
            "estimands": [
                "human-minus-reference-paired-utility",
                "selected-minus-reference-paired-utility",
                "selected-minus-human-paired-utility",
            ],
            "one_value_per_deal_cluster": "mean of complete rows in deal",
            "summary": "equal-deal mean, sample cluster SE, 1.96xSE",
            "formal_strength_or_promotion_test": False,
        },
        "terminal_verifier": {
            "must_reopen_every_input": True,
            "must_recompute_candidate_sources": True,
            "must_rederive_utility_from_raw_attacker_points": True,
            "must_recompute_every_seeded_row_with_replay_every_row": True,
            "must_match_shards_and_aggregate_byte_semantics": True,
        },
        "schedule_sha256": schedule["schedule_sha256"],
    }


def build_controller_packet(design_path: Path, corpus: Path,
                            source_root: Path, source_manifest: Path,
                            v11_checkpoint: Path, review_record: Path,
                            *, smoke: bool) -> dict:
    execution_runtime = require_execution_runtime()
    design_packet = validate_design_packet(design_path)
    design_review = require_design_review(review_record)
    manifest, _plays, _buries, catalog = validate_inputs(
        design_packet, corpus, source_root, source_manifest, v11_checkpoint)
    try:
        parent = LIVE_PARENT.require_portable_live_champion_parent()
    except LIVE_PARENT.ProtocolRefused as exc:
        raise ControllerRefused(f"live parent refused: {exc}") from exc
    if parent != design_packet["proposal_contract"]["live_parent"][
            "expected_parent"]:
        raise ControllerRefused("live parent differs from reviewed design")
    schedule = build_schedule(design_packet)
    preflight = score_free_preflight(
        design_packet, source_root, v11_checkpoint)
    packet = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "run_id": RUN_ID,
        "producer": producer_identity(smoke=smoke),
        "design": {
            "logical_path": DESIGN_PACKET_LOGICAL_PATH,
            "sha256": DESIGN_PACKET_SHA256,
            "internal_sha256": DESIGN_PACKET_INTERNAL_SHA256,
            "producer_git": DESIGN_PRODUCER_GIT,
            "packet_git": DESIGN_PACKET_GIT,
            "review_git": DESIGN_REVIEW_GIT,
            "review_claim": design_review,
        },
        "inputs": {
            "human_corpus": {
                "manifest_sha256": CORPUS_MANIFEST_SHA256,
                "artifacts": design_packet["human_corpus"]["artifacts"],
                "producer_git": manifest["producer_git"],
            },
            "source_snapshot": {
                "manifest_sha256": SOURCE_MANIFEST_SHA256,
                "members": catalog,
                "members_sha256": sha256_bytes(canonical_json(catalog)),
            },
            "v11pair": design_packet["proposal_contract"][
                "v11pair_checkpoint"],
            "live_parent": parent,
            "selected_play_rows_sha256": SELECTED_PLAY_ROWS_SHA256,
            "selected_bury_rows_sha256": SELECTED_BURY_ROWS_SHA256,
        },
        "execution_runtime": execution_runtime,
        "runtime_sources": runtime_sources(),
        "rng": {
            "derivation": (
                "sha256(domain || canonical-json([split,replay_key,surface,"
                "purpose])) first 64 bits"
            ),
            "reference_world_domain_sha256": sha256_bytes(
                DESIGN.REFERENCE_WORLD_DOMAIN),
            "pilot_selection_world_domain_sha256": sha256_bytes(
                DESIGN.SELECTION_WORLD_DOMAIN),
            "pilot_report_world_domain_sha256": sha256_bytes(
                DESIGN.REPORT_WORLD_DOMAIN),
            "proposal_domain_sha256": sha256_bytes(DESIGN.PROPOSAL_SEED_DOMAIN),
            "independent_streams_not_disjoint_realized_support": True,
            "world_collisions_are_diagnostic_never_rejected": True,
        },
        "schedule": schedule,
        "score_free_preflight": preflight,
        "commands": command_templates(schedule),
        "result_contract": result_contract(schedule),
        "review_contract": {
            "schema": REVIEW_SCHEMA,
            "marker": REVIEW_MARKER.strip(),
            "required_verdict": "PASS",
            "pass_authorizes": "one counterfactual execution receipt only",
            "hold_authorizes": "no execution",
            "required_claim_fields": [
                "schema", "git", "controller_script_sha256",
                "runtime_script_sha256",
                "packet_sha256", "design_packet_sha256",
                "design_review_git", "corpus_manifest_sha256",
                "source_manifest_sha256", "v11_checkpoint_sha256",
                "selected_play_rows_sha256", "selected_bury_rows_sha256",
                "schedule_sha256", "candidate_geometry_sha256",
                "max_candidate_worlds", "score_free_preflight_verified",
                "strict_runtime_verified", "fast_router_sha256",
                "compiled_fast_binary_sha256",
                "admission_slot_logical_path",
                "deletion_proof_one_shot",
                "worlds_sampled_before_review",
                "outcomes_computed_before_review", "independent_review",
                "one_counterfactual_execution_authorized",
                "labels_authorized", "training_authorized",
                "strength_claim", "production_promotion",
                "production_deployment", "verdict",
            ],
            "packet_sha256_field": "external SHA-256 of this canonical file",
        },
        "authority": {
            "score_free": True,
            "worlds_sampled": False,
            "outcomes_computed": False,
            "controller_review_authorized": True,
            "counterfactual_execution_authorized": False,
            "labels_authorized": False,
            "training_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
            "human_evaluation_data_may_train_or_select": False,
        },
    }
    packet["packet_sha256"] = sha256_bytes(canonical_json(packet))
    return packet


def packet_problems(packet: dict, expected: dict) -> list[str]:
    problems = []
    if packet != expected:
        problems.append("controller packet full recomputation drift")
    authority = packet.get("authority", {})
    if authority != expected.get("authority"):
        problems.append("controller authority drift")
    if (authority.get("score_free") is not True
            or authority.get("worlds_sampled") is not False
            or authority.get("outcomes_computed") is not False
            or authority.get("counterfactual_execution_authorized") is not False
            or authority.get("labels_authorized") is not False
            or authority.get("training_authorized") is not False
            or authority.get("strength_claim") is not False
            or authority.get("production_promotion") is not False
            or authority.get("production_deployment") is not False):
        problems.append("controller authority widened")
    preflight = packet.get("score_free_preflight", {})
    if (preflight.get("worlds_sampled") != 0
            or preflight.get("candidate_world_rollouts") != 0
            or preflight.get("outcomes_computed") is not False):
        problems.append("score-free preflight widened")
    runtime = packet.get("execution_runtime", {})
    if (runtime != expected.get("execution_runtime")
            or runtime.get("environment") != {
                "SHENGJI_FAST": "1", "SHENGJI_REQUIRE_VOIDS": "1"}
            or runtime.get("experimental_sampler_flags") != []
            or runtime.get("fast_engine") is not True):
        problems.append("execution runtime contract drift")
    contract = packet.get("result_contract", {})
    if (contract.get("durable_one_shot_admission_slot")
            != admission_slot_logical_path()
            or contract.get("admission_slot_published_before_receipt") is not True
            or contract.get("receipt_deletion_cannot_reissue") is not True
            or contract.get("admission_slot_gitignored") is not True
            or contract.get("admit_then_runtime_reopen_required") is not True
            or contract.get("unrelated_git_dirt_refused") is not True):
        problems.append("one-shot admission contract drift")
    return sorted(set(problems))


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--design-packet", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--v11-checkpoint", required=True)
    parser.add_argument("--review-record", required=True)
    parser.add_argument("--controller-packet", required=True)
    parser.add_argument("--expected-git")
    parser.add_argument("--smoke", action="store_true")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for command in ("freeze", "verify"):
        child = commands.add_parser(command)
        _common_arguments(child)
        if command == "verify":
            child.add_argument("--expected-controller-packet-sha256")
    return root


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if args.expected_git and _git("rev-parse", "HEAD") != args.expected_git:
        raise ControllerRefused("producer Git differs from expected Git")
    expected = build_controller_packet(
        Path(args.design_packet), Path(args.corpus), Path(args.source_root),
        Path(args.source_manifest), Path(args.v11_checkpoint),
        Path(args.review_record), smoke=args.smoke,
    )
    packet_path = Path(args.controller_packet)
    if args.command == "freeze":
        publish_exclusive(packet_path, expected)
        print(json.dumps({
            "status": "FROZEN_FOR_CONTROLLER_REVIEW",
            "packet": str(packet_path),
            "sha256": sha256_file(packet_path),
            "rows_replayed": expected["score_free_preflight"]["rows_replayed"],
            "worlds_sampled": 0,
            "counterfactual_execution_authorized": False,
        }, sort_keys=True))
        return
    if not is_regular_unlinked(packet_path):
        raise ControllerRefused("controller packet is not regular/unlinked")
    if (args.expected_controller_packet_sha256
            and sha256_file(packet_path) !=
            args.expected_controller_packet_sha256):
        raise ControllerRefused("controller packet SHA-256 drift")
    actual = _load_json(packet_path)
    problems = packet_problems(actual, expected)
    if problems:
        raise ControllerRefused("; ".join(problems))
    print(json.dumps({
        "status": "VERIFIED_FOR_CONTROLLER_REVIEW",
        "packet": str(packet_path),
        "sha256": sha256_file(packet_path),
        "rows_replayed": expected["score_free_preflight"]["rows_replayed"],
        "worlds_sampled": 0,
        "counterfactual_execution_authorized": False,
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except ControllerRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
