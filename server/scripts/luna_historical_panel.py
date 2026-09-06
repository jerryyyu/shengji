#!/usr/bin/env python3
"""Replay archived PT-Luna choices and export outcome-blind mechanics states.

This module intentionally has only standard-library imports at module import
time.  The archived teacher modules are loaded by :func:`run_export` after
the source checkout and input bindings have been checked.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence


SCHEMA = "luna-historical-panel-v1"
MODE = "opened-historical"
ARCHIVED_HEAD = "2394140bcdaebf72d81912a55ac18f5051848fe5"
REPORT_SHA256 = "fea40a5622efe2ce832483aebffbae8be25ca99bba11b60c8bfd0df666c27926"
THRESHOLDS = (0, 6, 12, 18)
ROLES = ("banker-team", "attacker-team")
class HistoricalPanelError(ValueError):
    """Input, source, replay, or artifact identity drift."""


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("ascii")


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(_canonical_bytes(value))


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HistoricalPanelError(f"cannot read JSON: {path}") from exc
    if type(value) is not dict:
        raise HistoricalPanelError(f"JSON object required: {path}")
    return value, _sha_bytes(raw)


def _git_output(repo: Path, *args: str) -> str:
    try:
        return subprocess.check_output(("git", "-C", str(repo), *args),
                                       stderr=subprocess.PIPE,
                                       text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HistoricalPanelError("archived source git check failed") from exc


def verify_source(repo: Path, *, expected_head: str = ARCHIVED_HEAD) -> dict[str, Any]:
    """Bind the archived checkout without rejecting unrelated untracked files."""
    repo = Path(repo).resolve()
    head = _git_output(repo, "rev-parse", "HEAD")
    if head != expected_head:
        raise HistoricalPanelError("archived source gitHEAD drift")
    # `git diff HEAD` includes staged and unstaged tracked changes, while the
    # explicit pathspec excludes the known unrelated prompt experiment.
    changed = _git_output(
        repo, "diff", "--name-only", "HEAD", "--",
        "server/shengji/engine", "server/shengji/ai", "server/shengji/rl")
    if changed:
        raise HistoricalPanelError("archived relevant tracked source changed")
    return {"repo": str(repo), "git_head": head}


def load_legacy_modules(repo: Path) -> tuple[Any, Any, Any]:
    """Import full/luna/sol from the archived checkout, lazily."""
    server = str(Path(repo).resolve() / "server")
    if server not in sys.path:
        sys.path.insert(0, server)
    try:
        full = importlib.import_module("shengji.rl.privileged_teacher_full_ab")
        luna = importlib.import_module("shengji.rl.privileged_teacher_luna0_report")
        sol = importlib.import_module("shengji.rl.privileged_teacher_sol0")
    except (ImportError, OSError) as exc:
        raise HistoricalPanelError("archived teacher import failed") from exc
    for module in (full, luna, sol):
        origin = getattr(module, "__file__", None)
        if not origin or not Path(origin).resolve().is_relative_to(Path(repo).resolve()):
            raise HistoricalPanelError("archived teacher import path drift")
    for name, module in tuple(sys.modules.items()):
        if not (name == "shengji" or name.startswith("shengji.")):
            continue
        origin = getattr(module, "__file__", None)
        if origin and not Path(origin).resolve().is_relative_to(Path(repo).resolve()):
            raise HistoricalPanelError("archived imported module path drift")
    return full, luna, sol


def _state_snapshot(rnd: Any) -> dict[str, object]:
    """Mirror current ``shengji.luna.game._state_snapshot`` exactly."""
    if rnd.phase == "round_end":
        return {"phase": "round_end", "terminal_redacted": True}
    return {"phase": rnd.phase, "turn": rnd.turn,
            "hands_by_seat": [sorted(hand) for hand in rnd.hands],
            "hidden_burial": sorted(rnd.buried), "banker": rnd.banker,
            "trump_rank": rnd.trump_rank, "trump_suit": rnd.trump_suit,
            "trump_is_nt": rnd.trump_is_nt,
            "attacker_points": rnd.attacker_points,
            "kitty_bonus": rnd.kitty_bonus,
            "declaration": (None if rnd.declaration is None else
                            dict(rnd.declaration)),
            "passed": sorted(rnd.passed),
            "last_trick_winner": rnd.last_trick_winner,
            "last_trick": (None if rnd.last_trick is None else {
                "leader": rnd.last_trick.leader,
                "plays": [{"seat": p.seat, "cards": list(p.cards)}
                          for p in rnd.last_trick.plays],
                "winner": rnd.last_trick.winner,
                "points": rnd.last_trick.points,
            }),
            "history": [{"leader": trick.leader,
                         "plays": [{"seat": p.seat, "cards": list(p.cards)}
                                   for p in trick.plays],
                         "winner": trick.winner, "points": trick.points}
                        for trick in rnd.history],
            "current_trick": None if rnd.trick is None else {
                "leader": rnd.trick.leader,
                "plays": [{"seat": p.seat, "cards": list(p.cards)
                           } for p in rnd.trick.plays],
                "winner": rnd.trick.winner,
                "points": rnd.trick.points,
            }}


def _without_budget(value: object) -> object:
    if isinstance(value, Mapping):
        return {k: _without_budget(v) for k, v in value.items() if k != "budget"}
    if isinstance(value, list):
        return [_without_budget(v) for v in value]
    return value


def _compare_observation(actual: Mapping[str, object], recorded: Mapping[str, object]) -> None:
    """Compare deterministic observation content, excluding budget counters."""
    a = _without_budget(actual)
    b = _without_budget(recorded)
    if a != b:
        raise HistoricalPanelError("historical observation drift")


def _accepted_events(evidence: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    transcript = evidence.get("transcript")
    if type(transcript) is not dict or type(transcript.get("events")) is not list:
        raise HistoricalPanelError("private transcript schema drift")
    transcript_status = transcript.get("status")
    if (isinstance(transcript_status, Mapping)
            and transcript_status.get("status") != "round_end"):
        raise HistoricalPanelError("private transcript incomplete")
    accepted: list[Mapping[str, Any]] = []
    observations: list[Mapping[str, Any]] = []
    for event in transcript["events"]:
        if type(event) is not dict:
            raise HistoricalPanelError("private event schema drift")
        if event.get("operation") == "observe" and event.get("response", {}).get("status") == "decision":
            observations.append(event["response"])
        # Rejected operations and rollouts are deliberately not replay inputs.
        if event.get("operation") == "play" and event.get("response", {}).get("status") == "play_committed":
            accepted.append(event)
    if not accepted:
        raise HistoricalPanelError("historical accepted play list empty")
    return accepted, observations


def _binding(record: Mapping[str, Any], *, report_sha: str,
             parent_sha: str, evidence_sha: str, source: Mapping[str, Any],
             thresholds: Sequence[int], execution: Mapping[str, Any] | None = None,
             seed_commitment_sha256: str | None = None) -> dict[str, Any]:
    coordinate = [record.get("trump_rank"), record.get("banker"), record.get("replicate")]
    role = record.get("role")
    return {"schema": SCHEMA, "mode": MODE, "source": dict(source),
            "execution": dict(execution or {}),
            "report_sha256": report_sha, "parent_report_sha256": parent_sha,
            "private_evidence_sha256": evidence_sha, "coordinate": coordinate,
            "role": role, "treatment_team": record.get("treatment_team"),
            "root_sha256": record.get("root_sha256"),
            "seed_commitment_sha256": seed_commitment_sha256,
            "thresholds": list(thresholds)}


def shard_path(out: Path, coordinate: Sequence[object], role: str) -> Path:
    rank, banker, replicate = coordinate
    return Path(out) / (f"rank-{rank}-banker-{banker}-replicate-{replicate}-{role}.json")


def _write_private(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    raw = _canonical_bytes(value)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _clone_after(session: Any, chosen: Sequence[str]) -> dict[str, object]:
    clone = copy.deepcopy(session.rnd)
    turn = clone.turn
    if turn is None:
        raise HistoricalPanelError("historical turn absent")
    clone.play(turn, list(chosen))
    return _state_snapshot(clone)


def replay_role(record: Mapping[str, Any], evidence: Mapping[str, Any], root: Any,
                secret: bytes, sol: Any, *, luna: Any | None = None,
                thresholds: Sequence[int] = THRESHOLDS,
                wall_seconds: float | None = None,
                session_factory: Callable[..., Any] | None = None,
                strict: bool = True) -> dict[str, Any]:
    """Replay one role and return a resumable shard (complete or partial)."""
    started = time.monotonic()
    accepted, _ = _accepted_events(evidence)
    coordinate = (record["trump_rank"], record["banker"], record["replicate"])
    transcript = evidence["transcript"]
    if (transcript.get("coordinate") not in (None, list(coordinate))
            or transcript.get("role") not in (None, record["role"])
            or transcript.get("treatment_team") not in (None, record["treatment_team"])):
        raise HistoricalPanelError("private transcript identity drift")
    factory = session_factory or sol.Sol0GameSession
    config_type = getattr(luna, "Luna0PlannerConfig", None)
    if config_type is None:
        config_type = getattr(sol, "Sol0PlannerConfig")
    session = factory(root, treatment_team=record["treatment_team"],
                      seed_secret=secret, coordinate=coordinate,
                      role=record["role"], config=config_type())
    # An observation immediately precedes the first accepted play in the
    # archived sequence; subsequent duplicate observes are harmless and the
    # latest one remains the matching ballot.
    event_index = 0
    latest_observe: Mapping[str, Any] | None = None
    positions: list[dict[str, Any]] = []
    assigned: set[int] = set()
    ordinal = 0
    try:
        for play_event in accepted:
            if wall_seconds is not None and time.monotonic() - started > wall_seconds:
                raise TimeoutError("historical replay wall deadline exceeded")
            while event_index < len(evidence["transcript"]["events"]):
                event = evidence["transcript"]["events"][event_index]
                event_index += 1
                if event is play_event:
                    break
                if event.get("operation") == "observe" and event.get("response", {}).get("status") == "decision":
                    latest_observe = event["response"]
            if latest_observe is None:
                raise HistoricalPanelError("historical observation missing")
            actual = session.observe()
            _compare_observation(actual, latest_observe)
            request = play_event.get("request")
            response = play_event.get("response")
            if type(request) is not dict or type(response) is not dict:
                raise HistoricalPanelError("historical play event schema drift")
            if request.get("op") != "play" or response.get("status") != "play_committed":
                raise HistoricalPanelError("historical accepted play schema drift")
            if (request.get("decision_sha256") != actual.get("decision_sha256")
                    or response.get("decision_sha256") != actual.get("decision_sha256")):
                raise HistoricalPanelError("historical decision SHA drift")
            index = request.get("candidate_index")
            candidates = actual.get("candidates")
            if (isinstance(index, bool) or not isinstance(index, int)
                    or type(candidates) is not list or not 0 <= index < len(candidates)):
                raise HistoricalPanelError("historical candidate index drift")
            chosen = candidates[index].get("cards") if type(candidates[index]) is dict else None
            recorded_cards = response.get("candidate_cards")
            if chosen != recorded_cards:
                raise HistoricalPanelError("historical candidate cards drift")
            ordinal += 1
            completed = len(getattr(session.rnd, "history", ()))
            due = [threshold for threshold in thresholds
                   if threshold not in assigned and completed >= threshold]
            before = _state_snapshot(session.rnd)
            after = _clone_after(session, chosen)
            if due:
                position = {
                    "snapshot": before,
                    "state_after_action": after,
                    "candidate_ballot": [dict(candidate) for candidate in candidates],
                    "chosen_action": {"candidate_index": index,
                                       "cards": list(recorded_cards),
                                       "confidence": request.get("confidence")},
                    "decision_sha256": request.get("decision_sha256"),
                    "decision_ordinal": ordinal,
                    "thresholds": due,
                }
                positions.append(position)
                assigned.update(due)
            session.play(request)
            latest_observe = None
        if not getattr(session, "complete", False):
            raise HistoricalPanelError("historical replay incomplete")
        expected_contested = record.get("luna0", {}).get("telemetry", {}).get("contested_decisions")
        if expected_contested is not None and expected_contested != len(accepted):
            raise HistoricalPanelError("historical accepted play count drift")
        expected_points = record.get("luna0", {}).get("attacker_points")
        if expected_points is not None and getattr(session.rnd, "attacker_points", expected_points) != expected_points:
            raise HistoricalPanelError("historical completion outcome drift")
        missing = [threshold for threshold in thresholds if threshold not in assigned]
        return {"positions": positions, "missing_thresholds": missing, "incomplete": False}
    except HistoricalPanelError as exc:
        if strict:
            raise
        missing = [threshold for threshold in thresholds if threshold not in assigned]
        return {"positions": positions, "missing_thresholds": missing,
                "incomplete": True, "error": str(exc)}
    except TimeoutError as exc:
        missing = [threshold for threshold in thresholds if threshold not in assigned]
        return {"positions": positions, "missing_thresholds": missing,
                "incomplete": True, "error": str(exc)}
    except Exception as exc:
        if strict:
            raise
        missing = [threshold for threshold in thresholds if threshold not in assigned]
        return {"positions": positions, "missing_thresholds": missing,
                "incomplete": True, "error": str(exc)}


def _next_retry_path(path: Path) -> Path:
    """Return a never-before-used retry path, chaining prior file digests."""
    path = Path(path)
    if not path.exists():
        return path
    previous = path
    sequence = 0
    while True:
        digest = _sha_bytes(previous.read_bytes())[:16]
        suffix = f"-retry-{digest}" if sequence == 0 else f"-retry-{digest}-{sequence}"
        candidate = path.with_name(path.stem + suffix + path.suffix)
        if not candidate.exists():
            return candidate
        previous = candidate
        sequence += 1


def _manifest(shards: list[Mapping[str, Any]], *, binding: Mapping[str, Any],
              incomplete: bool) -> dict[str, Any]:
    files = []
    positions = 0
    for shard in shards:
        path = shard["path"]
        files.append({"filename": Path(path).name, "sha256": shard["sha256"],
                      "coordinate": shard["coordinate"], "role": shard["role"],
                      "incomplete": shard["incomplete"],
                      "position_count": len(shard["positions"])})
        positions += len(shard["positions"])
    body = {"schema": SCHEMA, "mode": MODE, "incomplete": incomplete,
            "binding": dict(binding), "shards": files,
            "counts": {"roles": len(files), "positions": positions}}
    return {**body, "manifest_sha256": _sha(body)}


def run_export(*, old_repo: Path, report_path: Path, parent_report_path: Path,
               secret_path: Path, private_dir: Path, out: Path,
               wall_seconds: float = 1200.0, role_limit: int | None = None,
               thresholds: Sequence[int] = THRESHOLDS,
               modules: tuple[Any, Any, Any] | None = None) -> dict[str, Any]:
    if tuple(thresholds) != THRESHOLDS:
        raise HistoricalPanelError("threshold binding drift")
    if wall_seconds <= 0 or (role_limit is not None and role_limit <= 0):
        raise HistoricalPanelError("export limit drift")
    source = verify_source(old_repo)
    report, report_sha = _read_json(Path(report_path))
    if report_sha != REPORT_SHA256:
        raise HistoricalPanelError("historical report SHA drift")
    parent, parent_sha = _read_json(Path(parent_report_path))
    secret = Path(secret_path).read_bytes()
    if len(secret) != 32:
        raise HistoricalPanelError("seed secret length drift")
    seed_commitment = report.get("design", {}).get("seed_commitment_sha256")
    if type(seed_commitment) is not str or _sha_bytes(secret) != seed_commitment:
        raise HistoricalPanelError("seed commitment drift")
    if report.get("status") != "COMPLETE" or report.get("records", []) == []:
        raise HistoricalPanelError("historical report incomplete")
    if modules is None:
        modules = load_legacy_modules(old_repo)
    full, luna, sol = modules
    execution = {
        "archived_git_head": source["git_head"],
        "teacher_execution_git": report.get("design", {}).get("execution_git"),
        "full_execution_git": parent.get("design", {}).get("execution_git"),
    }
    try:
        design = full.FullABDesign(**{
            field.name: parent["design"][field.name]
            for field in dataclasses.fields(full.FullABDesign)})
    except (KeyError, TypeError, AttributeError) as exc:
        raise HistoricalPanelError("historical parent design drift") from exc
    # Preserve the sealed report order so --role-limit is a transparent smoke
    # prefix; the full run still covers every role exactly once.
    records = list(report["records"])
    if role_limit is not None:
        records = records[:role_limit]
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    shards: list[dict[str, Any]] = []
    started = time.monotonic()
    for record in records:
        if time.monotonic() - started >= wall_seconds:
            break
        coordinate = (record["trump_rank"], record["banker"], record["replicate"])
        evidence_path = Path(private_dir) / ("rank-%s-banker-%s-replicate-%s-%s.json" % (*coordinate, record["role"]))
        evidence, evidence_sha = _read_json(evidence_path)
        if evidence_sha != record.get("private_evidence_sha256"):
            raise HistoricalPanelError("private evidence SHA drift")
        binding = _binding(record, report_sha=report_sha, parent_sha=parent_sha,
                           evidence_sha=evidence_sha, source=source,
                           thresholds=thresholds, execution=execution,
                           seed_commitment_sha256=seed_commitment)
        path = shard_path(out, coordinate, record["role"])
        existing_path = path
        existing = None
        existing_sha = None
        candidates = [path] + sorted(path.parent.glob(path.stem + "-retry-*.json"))
        for candidate in candidates:
            if not candidate.exists():
                continue
            candidate_value, candidate_sha = _read_json(candidate)
            if (candidate_value.get("binding") == binding
                    and candidate_value.get("incomplete") is False):
                existing_path, existing, existing_sha = candidate, candidate_value, candidate_sha
                break
            if candidate == path:
                existing, existing_sha = candidate_value, candidate_sha
        if existing is not None:
            if (existing.get("binding") == binding and existing.get("incomplete") is False):
                shards.append({"path": existing_path, "sha256": existing_sha,
                               "coordinate": list(coordinate), "role": record["role"],
                               "incomplete": False, "positions": existing.get("positions", [])})
                continue
            if existing.get("incomplete") is False and existing.get("binding") != binding:
                raise HistoricalPanelError("completed historical shard binding drift")
        try:
            root = full._build_root(design, secret, *coordinate)
            if full._root_sha256(root) != record["root_sha256"]:
                raise HistoricalPanelError("historical root SHA drift")
            result = replay_role(record, evidence, root, secret, sol, luna=luna,
                                 thresholds=thresholds,
                                 wall_seconds=max(0.001, wall_seconds - (time.monotonic() - started)),
                                 strict=False)
        except Exception as exc:
            result = {"positions": [], "missing_thresholds": list(thresholds), "incomplete": True,
                      "error": str(exc)}
        shard = {"schema": SCHEMA, "mode": MODE, "binding": binding,
                 "source": dict(source), "execution": dict(execution),
                 "reports": {"historical": report_sha, "parent": parent_sha,
                             "private_evidence": evidence_sha},
                 "coordinate": list(coordinate), "role": record["role"],
                 "treatment_team": record["treatment_team"],
                 "positions": result["positions"],
                 "missing_thresholds": result["missing_thresholds"],
                 "incomplete": result["incomplete"]}
        if result.get("error"):
            shard["error"] = result["error"]
        # Preserve an earlier partial byte-for-byte; retries use a bound name.
        target = path
        if path.exists() and existing is not None and existing.get("incomplete") is True:
            target = _next_retry_path(path)
        if not (target.exists() and json.loads(target.read_text()).get("incomplete") is False):
            _write_private(target, shard)
        raw = target.read_bytes()
        stored = json.loads(raw.decode("utf-8"))
        shards.append({"path": target, "sha256": _sha_bytes(raw),
                       "coordinate": list(coordinate), "role": record["role"],
                       "incomplete": stored.get("incomplete", True),
                       "positions": stored.get("positions", [])})
        print(f"historical role {record['trump_rank']}/{record['banker']}/{record['replicate']} {record['role']}", file=sys.stderr, flush=True)
    manifest_binding = {"report_sha256": report_sha, "parent_report_sha256": parent_sha,
                        "source": source, "execution": execution,
                        "seed_commitment_sha256": seed_commitment,
                        "thresholds": list(thresholds)}
    incomplete = len(shards) != len(report.get("records", ())) or any(s["incomplete"] for s in shards)
    manifest = _manifest(shards, binding=manifest_binding, incomplete=incomplete)
    _write_private(out / "manifest.json", manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-repo", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--parent-report", required=True, type=Path)
    parser.add_argument("--seed-secret", required=True, type=Path)
    parser.add_argument("--private-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--wall-seconds", type=float, default=1200.0)
    parser.add_argument("--role-limit", type=int)
    args = parser.parse_args(argv)
    try:
        manifest = run_export(old_repo=args.old_repo, report_path=args.report,
                              parent_report_path=args.parent_report,
                              secret_path=args.seed_secret,
                              private_dir=args.private_dir, out=args.out,
                              wall_seconds=args.wall_seconds,
                              role_limit=args.role_limit)
    except HistoricalPanelError as exc:
        parser.error(str(exc))
    print(json.dumps({"schema": manifest["schema"], "mode": manifest["mode"],
                      "incomplete": manifest["incomplete"], "counts": manifest["counts"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
