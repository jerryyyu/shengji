"""Build a provenance-bound corpus from logged human decisions.

The play shard remains compatible with the historical RL loader, but it is a
behavioural/proposal asset rather than strength truth: returns are coarse round
outcomes and human skill is mixed. A sidecar retains replay keys for later
counterfactual Teacher labeling. Human bury actions are captured separately
because the play encoder/ballot does not represent the bury decision surface.

Usage:
  uv run python -m shengji.rl.human_shards \
      --source-manifest ../logs/manifests/fly-YYYY.sha256 \
      "../logs/*.jsonl" rl_data/human_v8
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import random
import shutil
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from ..engine.cards import total_points
from ..engine.round import KITTY_SIZE, Round
from .actions import enumerate_actions
from .bc_generate import round_value
from .dataset import Decision, TrajectoryWriter
from .encode import (ENC_VERSION, ENCODER_IMPLEMENTATION_SHA256,
                     ENCODER_SOURCE_SHA256S, OBS_SCHEMA, encode_action,
                     encode_obs)
from .replay_log import EXCLUDE_PLAYERS, group_rounds, rebuild_round

CORPUS_SCHEMA = "human-decision-corpus-v1"
PLAYER_HASH_DOMAIN = b"shengji-human-player-v1\0"
PLAY_BALLOT = "exhaustive-follows+throws-v1"
RETURN_TARGET = "signed-level-bracket-from-completed-round"
HUMAN_EVALUATION_SCHEMA = "human-vs-bot-evaluation-v1"


class HumanCorpusError(RuntimeError):
    """The corpus cannot be published without weakening its contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _player_id(name: str) -> str:
    return hashlib.sha256(PLAYER_HASH_DOMAIN + name.encode("utf-8")).hexdigest()[:16]


def _producer_identity() -> tuple[str, bool]:
    repo = Path(__file__).resolve().parents[3]
    try:
        git = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
            stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repo, text=True, stderr=subprocess.DEVNULL).strip())
        return git, dirty
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN", True


def _expand_paths(patterns: list[str]) -> tuple[list[Path], int]:
    found: dict[str, Path] = {}
    local_excluded = 0
    for pattern in patterns:
        matches = glob.glob(pattern) if any(c in pattern for c in "*?[") else [pattern]
        for match in matches:
            path = Path(match).resolve()
            if path.parent.name == "local":
                local_excluded += 1
                continue
            if path.is_file() and path.suffix == ".jsonl":
                found[str(path)] = path
    return [found[key] for key in sorted(found)], local_excluded


def _read_snapshot_members(path: Path | None) -> tuple[dict[str, str], str | None]:
    if path is None:
        return {}, None
    if not path.is_file():
        raise HumanCorpusError(f"missing source manifest: {path}")
    members: dict[str, str] = {}
    for line_no, line in enumerate(path.read_text().splitlines(), 1):
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or len(fields[0]) != 64:
            raise HumanCorpusError(f"malformed source manifest line {line_no}")
        name = Path(fields[1].lstrip("* ")).name
        if name in members:
            raise HumanCorpusError(f"duplicate source manifest member: {name}")
        members[name] = fields[0]
    if not members:
        raise HumanCorpusError("empty source manifest")
    return members, _sha256(path)


def _rebuild_before_bury(events: list[dict]) -> Round | None:
    start = next((event for event in events if event.get("e") == "round_start"), None)
    trump = next((event for event in events if event.get("e") == "trump"), None)
    bury = next((event for event in events if event.get("e") == "bury"), None)
    if start is None or trump is None or bury is None:
        return None
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
            rnd.declare(event["seat"], event["cards"])
    rnd.finalize_declare()
    if rnd.banker != trump.get("banker") or rnd.turn != bury.get("seat"):
        raise HumanCorpusError("logged trump/bury banker mismatch")
    return rnd


def _json_line(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


def _error_key(exc: BaseException) -> str:
    return type(exc).__name__


def _refuse_evaluation_round(events: list[dict], reference: str) -> None:
    """Keep people-facing evaluation evidence out of every training corpus.

    HUMAN-C1 will live under a physically separate log root, but paths can be
    copied or globbed incorrectly.  The immutable log tag is therefore a
    second, content-level boundary; scan the whole round so moving the tag
    cannot bypass it.  Refuse the whole publication rather than silently
    dropping a favorable or unfavorable evaluation subset.
    """
    for event in events:
        experiment = event.get("experiment")
        tagged = event.get("training_excluded") is True
        if isinstance(experiment, dict):
            tagged = tagged or experiment.get("training_excluded") is True
            tagged = tagged or experiment.get("schema") == HUMAN_EVALUATION_SCHEMA
        if tagged:
            raise HumanCorpusError(
                f"evaluation-only round cannot enter human corpus: {reference}")


def build_corpus(patterns: list[str], out_dir: str,
                 *, source_manifest: str | None = None,
                 run_id: str | None = None) -> dict:
    """Build one fresh corpus and return its published manifest.

    Publication is atomic: ``out_dir`` must not exist, work happens in a
    sibling ``.partial`` directory, and any exception removes that new partial.
    Source logs are read-only.
    """
    sources, local_excluded = _expand_paths(patterns)
    if not sources:
        raise HumanCorpusError("no source JSONL files")

    out = Path(out_dir).resolve()
    partial = out.with_name(out.name + ".partial")
    if out.exists() or partial.exists():
        raise HumanCorpusError(f"fresh output required: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)

    snapshot_path = Path(source_manifest).resolve() if source_manifest else None
    snapshot_members, snapshot_sha = _read_snapshot_members(snapshot_path)
    source_names = [source.name for source in sources]
    if len(source_names) != len(set(source_names)):
        raise HumanCorpusError("source basenames must be unique")
    non_snapshot_sources: list[str] = []
    if snapshot_members:
        source_by_name = {source.name: source for source in sources}
        missing = sorted(set(snapshot_members) - set(source_by_name))
        if missing:
            raise HumanCorpusError(
                f"snapshot members missing locally: {','.join(missing)}")
        non_snapshot_sources = sorted(set(source_by_name) - set(snapshot_members))
        sources = [source_by_name[name] for name in sorted(snapshot_members)]
    partial.mkdir()
    stats: Counter[str] = Counter()
    stats["source_files"] = len(sources)
    stats["non_snapshot_source_files_excluded"] = len(non_snapshot_sources)
    stats["local_directory_files_excluded"] = local_excluded
    rejections: Counter[str] = Counter()
    rejection_examples: dict[str, list[str]] = {}
    play_records: list[dict] = []
    bury_records: list[dict] = []
    player_counts: Counter[str] = Counter()
    writer = TrajectoryWriter(str(partial))

    def reject(reason: str, reference: str, exc: BaseException | None = None) -> None:
        key = reason if exc is None else f"{reason}:{_error_key(exc)}"
        rejections[key] += 1
        examples = rejection_examples.setdefault(key, [])
        if len(examples) < 3:
            examples.append(reference)

    try:
        source_rows = []
        source_shas: dict[Path, str] = {}
        for source in sources:
            source_sha = _sha256(source)
            source_shas[source] = source_sha
            if (source.name in snapshot_members
                    and snapshot_members[source.name] != source_sha):
                raise HumanCorpusError(
                    f"source differs from snapshot manifest: {source.name}")
            source_rows.append({
                "name": source.name,
                "sha256": source_sha,
                "bytes": source.stat().st_size,
                "fly_snapshot_member": source.name in snapshot_members,
            })
            try:
                rounds = group_rounds(str(source))
            except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                reject("source_parse", source.name, exc)
                continue
            stats["source_files_parsed"] += 1

            for round_no, events in sorted(rounds.items()):
                reference = f"{source.name}:round-{round_no}"
                stats["rounds_seen"] += 1
                start = next((e for e in events if e.get("e") == "round_start"), None)
                end = next((e for e in events if e.get("e") == "round_end"), None)
                if start is None:
                    reject("round_missing_start", reference)
                    continue
                _refuse_evaluation_round(events, reference)
                if end is None:
                    reject("round_incomplete", reference)
                    continue
                players = start.get("players")
                if not isinstance(players, list) or len(players) != 4:
                    reject("round_player_population", reference)
                    continue
                names = {int(p["seat"]): str(p["name"]) for p in players}
                if set(names) != {0, 1, 2, 3}:
                    reject("round_player_seats", reference)
                    continue
                excluded = {seat for seat, name in names.items()
                            if name in EXCLUDE_PLAYERS}

                try:
                    rnd = rebuild_round(events)
                    pre_bury = _rebuild_before_bury(events)
                    if rnd is None or pre_bury is None:
                        reject("round_missing_setup", reference)
                        continue
                except Exception as exc:
                    reject("round_setup_replay", reference, exc)
                    continue

                pending_decisions: list[Decision] = []
                pending_records: list[dict] = []
                pending_buries: list[dict] = []

                bury_event = next((e for e in events if e.get("e") == "bury"), None)
                if (bury_event is not None and bury_event.get("bot") is False
                        and bury_event.get("seat") not in excluded):
                    stats["human_bury_events"] += 1
                    try:
                        cards = list(bury_event["cards"])
                        if len(cards) != KITTY_SIZE:
                            raise HumanCorpusError("human bury card count")
                        # Mutating this private replay validates ownership and
                        # exact engine legality without touching the play replay.
                        hand_before = list(pre_bury.hands[pre_bury.banker])
                        pre_bury.bury(pre_bury.banker, cards)
                        player = _player_id(names[bury_event["seat"]])
                        pending_buries.append({
                            "source": source.name,
                            "round": round_no,
                            "seat": bury_event["seat"],
                            "player_id": player,
                            "banker": pre_bury.banker,
                            "trump_rank": pre_bury.trump_rank,
                            "trump_suit": pre_bury.trump_suit,
                            "trump_is_nt": pre_bury.trump_is_nt,
                            "hand_before": sorted(hand_before),
                            "chosen": sorted(cards),
                            "point_total": total_points(cards),
                        })
                    except Exception as exc:
                        reject("human_bury_replay", reference, exc)

                trick_no = 0
                replay_failed: BaseException | None = None
                for event_index, event in enumerate(events):
                    if event.get("e") != "play" or rnd.phase != "play":
                        continue
                    if rnd.trick is not None and not rnd.trick.plays:
                        trick_no += 1
                    seat = event.get("seat")
                    cards = event.get("cards")
                    if event.get("bot") is False:
                        stats["human_play_events"] += 1
                        if seat in excluded:
                            stats["human_play_excluded_test"] += 1
                        elif rnd.turn != seat:
                            reject("human_play_off_turn", reference)
                        elif not isinstance(cards, list):
                            reject("human_play_cards", reference)
                        else:
                            try:
                                actions = enumerate_actions(
                                    rnd, seat, exhaustive_follows=True,
                                    include_throws=True)
                                key = sorted(cards)
                                chosen = next((i for i, action in enumerate(actions)
                                               if sorted(action) == key), None)
                                appended = chosen is None
                                if appended:
                                    actions.append(list(cards))
                                    chosen = len(actions) - 1
                                surface = "lead" if not rnd.trick.plays else "follow"
                                player = _player_id(names[seat])
                                pending_decisions.append(Decision(
                                    obs=encode_obs(rnd, seat),
                                    actions=[encode_action(action, rnd)
                                             for action in actions],
                                    chosen=chosen,
                                    seat=seat,
                                    ret=(round_value(end["attacker_points"])
                                         if rnd.is_attacker(seat) else
                                         -round_value(end["attacker_points"]))))
                                pending_records.append({
                                    "source": source.name,
                                    "round": round_no,
                                    "event_index": event_index,
                                    "seat": seat,
                                    "player_id": player,
                                    "banker": rnd.banker,
                                    "role": ("attacker" if rnd.is_attacker(seat)
                                             else "defender"),
                                    "surface": surface,
                                    "trick": trick_no,
                                    "cards_remaining": sum(len(h) for h in rnd.hands),
                                    "chosen": sorted(cards),
                                    "candidate_count": len(actions),
                                    "human_action_appended": appended,
                                })
                            except Exception as exc:
                                reject("human_decision_encode", reference, exc)
                    try:
                        rnd.play(seat, cards)
                    except Exception as exc:
                        replay_failed = exc
                        break

                if replay_failed is not None:
                    reject("round_play_replay", reference, replay_failed)
                    continue
                if rnd.phase != "round_end":
                    reject("round_end_state", reference)
                    continue
                if rnd.attacker_points != end.get("attacker_points"):
                    reject("round_score_mismatch", reference)
                    continue

                stats["rounds_replayed"] += 1
                for decision, record in zip(pending_decisions, pending_records,
                                            strict=True):
                    writer.add(decision)
                    play_records.append(record)
                    player_counts[record["player_id"]] += 1
                    stats["play_decisions_accepted"] += 1
                    if record["human_action_appended"]:
                        stats["play_actions_off_ballot"] += 1
                bury_records.extend(pending_buries)
                stats["bury_decisions_accepted"] += len(pending_buries)

        if stats["play_decisions_accepted"] == 0:
            raise HumanCorpusError("zero accepted human play decisions")
        for source, expected_sha in source_shas.items():
            if _sha256(source) != expected_sha:
                raise HumanCorpusError(f"source changed during build: {source.name}")
        if snapshot_path is not None and _sha256(snapshot_path) != snapshot_sha:
            raise HumanCorpusError("source manifest changed during build")
        writer.flush()

        play_index = partial / "play_decisions.jsonl"
        bury_index = partial / "bury_decisions.jsonl"
        with play_index.open("w") as fh:
            for record in play_records:
                fh.write(_json_line(record))
        with bury_index.open("w") as fh:
            for record in bury_records:
                fh.write(_json_line(record))

        artifacts = []
        for artifact in sorted(partial.iterdir()):
            if artifact.name == "manifest.json":
                continue
            artifacts.append({
                "name": artifact.name,
                "sha256": _sha256(artifact),
                "bytes": artifact.stat().st_size,
            })
        producer_git, producer_tree_dirty = _producer_identity()
        manifest = {
            "schema": CORPUS_SCHEMA,
            "run_id": run_id or out.name,
            "created_at": datetime.now(UTC).isoformat(),
            "producer_git": producer_git,
            "producer_tree_dirty": producer_tree_dirty,
            "producer_sha256": _sha256(Path(__file__).resolve()),
            "source_manifest": (str(snapshot_path) if snapshot_path else None),
            "source_manifest_sha256": snapshot_sha,
            "non_snapshot_sources_excluded": non_snapshot_sources,
            "sources": source_rows,
            "encoder": {
                "version": ENC_VERSION,
                "schema": OBS_SCHEMA,
                "implementation_sha256": ENCODER_IMPLEMENTATION_SHA256,
                "source_sha256s": ENCODER_SOURCE_SHA256S,
            },
            "play_ballot": PLAY_BALLOT,
            "return_target": RETURN_TARGET,
            "player_identity_source": "round-start-seat-name",
            "stats": dict(sorted(stats.items())),
            "rejections": dict(sorted(rejections.items())),
            "rejection_examples": dict(sorted(rejection_examples.items())),
            "pseudonymous_player_decisions": dict(sorted(player_counts.items())),
            "artifacts": artifacts,
            "training_authorized": False,
            "strength_claim": False,
            "allowed_use": [
                "behavioural-cloning-control-design",
                "proposal-source",
                "teacher-disagreement-mining",
                "counterfactual-pilot-design",
            ],
        }
        manifest_path = partial / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True)
                                 + "\n")
        os.replace(partial, out)
        return manifest
    except Exception:
        shutil.rmtree(partial, ignore_errors=True)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("items", nargs="+",
                        help="source paths/globs followed by fresh output dir")
    parser.add_argument("--source-manifest",
                        help="Fly snapshot shasum manifest used for provenance")
    parser.add_argument("--run-id")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if len(args.items) < 2:
        raise SystemExit("provide at least one source path and one output dir")
    manifest = build_corpus(
        args.items[:-1], args.items[-1],
        source_manifest=args.source_manifest, run_id=args.run_id)
    stats = manifest["stats"]
    print(
        f"{stats['play_decisions_accepted']} human plays and "
        f"{stats.get('bury_decisions_accepted', 0)} human buries from "
        f"{stats['rounds_replayed']} replayed rounds -> {args.items[-1]}",
        flush=True)


if __name__ == "__main__":
    main()
