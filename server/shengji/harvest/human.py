"""Extractor: human_v8 decision pointers, resolved through the room-log
extractor.

``server/rl_data/human_v8/play_decisions.jsonl`` points at
``(source file, round, event_index, seat, chosen, player_id)``;
``bury_decisions.jsonl`` at ``(source, round, seat, hand_before, chosen)``.
Each pointer is resolved to the room-log record of that event; the record is
re-labelled ``source = "human"``, ``policy = "human:<pseudonym>"`` and gets
the corpus' governance labels (``training_authorized: false``, allowed_use).

Checks: the pointer's seat/chosen cards match the log event; the pointer's
pseudonym equals sha256(domain + round_start name)[:16]; bury ``hand_before``
equals the rebuilt pre-bury hand.  Room logs listed in the corpus manifest
are compared with the manifest's sha256 (append-only logs may have grown).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .common import (HUMAN_V8, REPO, ExtractResult, InputRegistry, action_key,
                     pseudonym, sha256_file)
from .rebuild import round_from_setup
from .room_log import (extract_round, file_bot_policy, log_ref, player_names,
                       read_rounds)
from .schema import finalize_record


class HumanPointerError(ValueError):
    pass


def _resolve_source(name: str, repo: Path = REPO) -> Path:
    candidates = [repo / "logs" / name, *sorted((repo / "logs" / "archive").glob(f"*/{name}")),
                  repo / "logs" / "local" / name]
    for path in candidates:
        if path.is_file():
            return path
    raise HumanPointerError(f"human_v8 source log not found: {name}")


def extract_human(human_dir: Path = HUMAN_V8, *, cap: int | None = 256,
                  registry: InputRegistry | None = None,
                  repo: Path = REPO) -> ExtractResult:
    registry = registry or InputRegistry()
    result = ExtractResult("human")
    manifest = registry.read_json(human_dir / "manifest.json")
    plays = list(registry.read_jsonl(human_dir / "play_decisions.jsonl"))
    buries = list(registry.read_jsonl(human_dir / "bury_decisions.jsonl"))
    authority = {
        "training_authorized": bool(manifest.get("training_authorized", False)),
        "strength_claim": bool(manifest.get("strength_claim", False)),
        "allowed_use": list(manifest.get("allowed_use") or []),
        "corpus_run_id": manifest.get("run_id"),
    }
    manifest_shas = {row["name"]: row["sha256"] for row in manifest.get("sources", [])}

    by_round: dict[tuple[str, int], dict] = defaultdict(lambda: {"plays": [], "buries": []})
    for line_no, row in enumerate(plays):
        by_round[(row["source"], int(row["round"]))]["plays"].append((line_no, row))
    for line_no, row in enumerate(buries):
        by_round[(row["source"], int(row["round"]))]["buries"].append((line_no, row))

    counts = {"pointers_play": len(plays), "pointers_bury": len(buries),
              "rounds": 0, "decisions": 0, "bury_records": 0,
              "sources": 0, "source_sha_matches_manifest": 0,
              "source_sha_differs_from_manifest": 0,
              "pseudonym_mismatch": 0, "off_ballot_flagged": 0}
    sources = sorted({name for name, _ in by_round})
    counts["sources"] = len(sources)
    rounds_cache: dict[str, dict[int, list[dict]]] = {}
    refs: dict[str, str] = {}
    fallbacks: dict[str, str | None] = {}
    for name in sources:
        path = _resolve_source(name, repo)
        sha = sha256_file(path)
        if manifest_shas.get(name) == sha:
            counts["source_sha_matches_manifest"] += 1
        else:
            counts["source_sha_differs_from_manifest"] += 1
        rounds_cache[name], _ = read_rounds(path, registry)
        refs[name] = log_ref(path, repo)
        fallbacks[name] = file_bot_policy(rounds_cache[name])

    ordered_play: list[tuple[int, dict]] = []
    ordered_bury: list[tuple[int, dict]] = []
    for (name, round_no), group in sorted(by_round.items()):
        events = rounds_cache[name].get(round_no)
        if events is None:
            raise HumanPointerError(f"{name}:round-{round_no} missing from log")
        records, _ = extract_round(refs[name], round_no, events, cap=cap,
                                   fallback_policy=fallbacks[name])
        by_ref = {r["source_ref"]: r for r in records}
        names = player_names(events)
        counts["rounds"] += 1
        for line_no, row in group["plays"]:
            ref = f"{refs[name]}:round-{round_no}:event-{int(row['event_index'])}"
            base = by_ref.get(ref)
            if base is None or base["decision_kind"] != "play":
                raise HumanPointerError(f"pointer {line_no} does not resolve: {ref}")
            if base["seat"] != int(row["seat"]):
                raise HumanPointerError(f"pointer {line_no}: seat drift")
            if action_key(base["action"]) != action_key(row["chosen"]):
                raise HumanPointerError(f"pointer {line_no}: chosen cards drift")
            if pseudonym(names[base["seat"]]) != row["player_id"]:
                counts["pseudonym_mismatch"] += 1
            if row.get("human_action_appended"):
                counts["off_ballot_flagged"] += 1
            record = dict(base)
            record.update({
                "source": "human",
                "source_ref": f"human_v8/play_decisions.jsonl:{line_no} -> {ref}",
                "policy": f"human:{row['player_id']}",
                "authority": authority,
            })
            ordered_play.append((line_no, finalize_record(record)))
        for line_no, row in group["buries"]:
            bury_rec = next(r for r in records if r["decision_kind"] == "bury")
            if bury_rec["seat"] != int(row["seat"]):
                raise HumanPointerError(f"bury pointer {line_no}: seat drift")
            if action_key(bury_rec["action"]) != action_key(row["chosen"]):
                raise HumanPointerError(f"bury pointer {line_no}: chosen drift")
            pre = round_from_setup(bury_rec["deck"], bury_rec["setup"],
                                   stop_before_bury=True)
            if sorted(pre.hands[pre.banker]) != sorted(row["hand_before"]):
                raise HumanPointerError(f"bury pointer {line_no}: hand_before drift")
            if pseudonym(names[bury_rec["seat"]]) != row["player_id"]:
                counts["pseudonym_mismatch"] += 1
            record = dict(bury_rec)
            record.update({
                "source": "human",
                "source_ref": f"human_v8/bury_decisions.jsonl:{line_no} -> "
                              f"{bury_rec['source_ref']}",
                "policy": f"human:{row['player_id']}",
                "authority": authority,
            })
            ordered_bury.append((line_no, finalize_record(record)))
    for _, record in sorted(ordered_play, key=lambda t: t[0]):
        result.add(record, None)
        counts["decisions"] += 1
    for _, record in sorted(ordered_bury, key=lambda t: t[0]):
        result.add(record, None)
        counts["bury_records"] += 1
    result.counts = counts
    result.inputs = registry.rows()
    result.extras["manifest_stats"] = manifest.get("stats")
    result.notes.append("policy pseudonyms are the corpus' player_id values "
                        "(sha256 of 'shengji-human-player-v1' + seat name)")
    return result


def load_manifest(human_dir: Path = HUMAN_V8) -> dict:
    return json.loads((human_dir / "manifest.json").read_text())
