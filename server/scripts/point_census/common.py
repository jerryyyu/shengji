"""Shared, read-only core for the point-management census scripts.

Every script binds its inputs to an explicit ordered manifest (content SHAs,
counts) and emits exactly one canonical JSON document on stdout.  Nothing here
writes files, launches jobs, or carries any review/run authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.memory import Memory
from shengji.engine.cards import TRUMP, points
from shengji.engine import fast as FAST
from shengji.rl.actions import enumerate_actions
from shengji.rl.replay_log import EXCLUDE_PLAYERS, rebuild_round

MANIFEST_SCHEMA = "point-census-input-manifest-v1"
ALLOWED_USE = (
    "behavioural-cloning-control-design", "proposal-source",
    "teacher-disagreement-mining", "counterfactual-pilot-design",
)
_HB = HeuristicBot()
SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[2]
REPO = SCRIPT.parents[3]
SOURCE_PATHS = (
    "server/pyproject.toml",
    "server/setup.py",
    "server/uv.lock",
    "server/scripts/point_census/common.py",
    "server/scripts/point_census/e1_census.py",
    "server/scripts/point_census/e2_e3_search_objective.py",
    "server/scripts/point_census/e5_feed_ground_truth.py",
    "server/scripts/point_census/manifest.py",
    "server/scripts/point_census/p1_p2_rollout_probes.py",
    "server/shengji/__init__.py",
    "server/shengji/ai/__init__.py",
    "server/shengji/ai/heuristic.py",
    "server/shengji/ai/legacy_b3f8f61/__init__.py",
    "server/shengji/ai/legacy_b3f8f61/mcbot.py",
    "server/shengji/ai/legacy_b3f8f61/memory.py",
    "server/shengji/ai/mcbot.py",
    "server/shengji/ai/memory.py",
    "server/shengji/ai/registry.py",
    "server/shengji/ai/smart.py",
    "server/shengji/engine/__init__.py",
    "server/shengji/engine/_fast.pyx",
    "server/shengji/engine/cards.py",
    "server/shengji/engine/combos.py",
    "server/shengji/engine/fast.py",
    "server/shengji/engine/legal.py",
    "server/shengji/engine/round.py",
    "server/shengji/rl/__init__.py",
    "server/shengji/rl/actions.py",
    "server/shengji/rl/replay_log.py",
    "server/tests/test_point_census.py",
)


@dataclass(frozen=True)
class ValidatedLog:
    """One manifest-authenticated input, held as immutable bytes.

    Consumers never reopen the path after validation.  That makes the digest,
    strict JSON parse, and replay operate on the same byte sequence.
    """

    name: str
    raw: bytes


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(stable_bytes(path))


def is_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            and info.st_nlink == 1)


def stable_bytes(path: Path) -> bytes:
    """Read one regular, unlinked path once and reject identity mutation."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise SystemExit(f"REFUSED: cannot open stable input: {path}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise SystemExit(f"REFUSED: input is not regular/unlinked: {path}")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read()
        after = os.fstat(fd)
    finally:
        os.close(fd)
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size",
              "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, key) != getattr(after, key) for key in fields):
        raise SystemExit(f"REFUSED: input changed while reading: {path}")
    try:
        current = path.lstat()
    except OSError as exc:
        raise SystemExit(f"REFUSED: input path disappeared: {path}") from exc
    if (stat.S_ISLNK(current.st_mode)
            or current.st_dev != after.st_dev or current.st_ino != after.st_ino
            or current.st_nlink != 1):
        raise SystemExit(f"REFUSED: input path identity changed: {path}")
    return raw


def _no_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def strict_json(raw: bytes, label: str):
    try:
        return json.loads(
            raw, object_pairs_hook=_no_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {value}")))
    except (UnicodeError, ValueError) as exc:
        raise SystemExit(f"REFUSED: invalid strict JSON in {label}") from exc


def log_events(raw: bytes, label: str) -> list[dict]:
    events = []
    for index, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            raise SystemExit(f"REFUSED: empty JSONL row in {label}:{index}")
        event = strict_json(line, f"{label}:{index}")
        if not isinstance(event, dict):
            raise SystemExit(f"REFUSED: non-object JSONL row in {label}:{index}")
        events.append(event)
    if not events:
        raise SystemExit(f"REFUSED: empty JSONL input: {label}")
    return events


def group_events(events: list[dict], label: str) -> dict[int, list[dict]]:
    """Round number -> strict event rows, without reopening the JSONL."""
    grouped: dict[int, list[dict]] = defaultdict(list)
    for index, event in enumerate(events, start=1):
        rno = event.get("round")
        if isinstance(rno, bool) or not isinstance(rno, int):
            raise SystemExit(
                f"REFUSED: invalid round number in {label}:{index}")
        grouped[rno].append(event)
    return dict(grouped)


def _counts(raw: bytes, label: str) -> tuple[int, int]:
    events = log_events(raw, label)
    return (sum(event.get("e") == "round_start" for event in events),
            sum(event.get("e") == "play" for event in events))


def emit(value) -> None:
    sys.stdout.buffer.write(canonical(value))


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO, check=True, text=True,
            capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("REFUSED: source Git cannot be authenticated") from exc


def _source_receipt(tool_path: Path) -> dict:
    git = _git("rev-parse", "HEAD").strip()
    if (not isinstance(git, str) or len(git) != 40
            or any(c not in "0123456789abcdef" for c in git)):
        raise SystemExit("REFUSED: source Git identity drift")
    if _git("status", "--porcelain=v1", "--untracked-files=no"):
        raise SystemExit("REFUSED: tracked source tree is dirty")
    source_sha256s = {}
    for logical in SOURCE_PATHS:
        path = REPO / logical
        if not regular_unlinked(path):
            raise SystemExit(f"REFUSED: source path drift: {logical}")
        current_raw = stable_bytes(path)
        current = sha256_bytes(current_raw)
        try:
            committed = subprocess.run(
                ["git", "show", f"{git}:{logical}"], cwd=REPO, check=True,
                capture_output=True).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise SystemExit(f"REFUSED: untracked source path: {logical}") \
                from exc
        if committed != current_raw:
            raise SystemExit(f"REFUSED: source/Git drift: {logical}")
        source_sha256s[logical] = current
    try:
        tool_logical = str(tool_path.resolve().relative_to(REPO))
    except ValueError as exc:
        raise SystemExit("REFUSED: census tool escapes source repository") \
            from exc
    if tool_logical not in source_sha256s:
        raise SystemExit("REFUSED: census tool is outside source closure")
    flags = {name: os.environ.get(name) for name in (
        "SHENGJI_FAST", "SHENGJI_REQUIRE_VOIDS")}
    if any(value not in {None, "1"} for value in flags.values()):
        raise SystemExit("REFUSED: unsupported runtime flag value")
    native = getattr(FAST, "_fast", None)
    native_path = (None if native is None else
                   Path(str(getattr(native, "__file__", ""))).resolve())
    if flags["SHENGJI_FAST"] == "1" and (
            not FAST.HAVE_FAST or not getattr(FAST, "_saved", None)
            or native_path is None or not regular_unlinked(native_path)):
        raise SystemExit("REFUSED: requested compiled routing is inactive")
    python = Path(sys.executable).resolve()
    if not regular_unlinked(python):
        raise SystemExit("REFUSED: Python executable identity drift")
    return {
        "source_git": git,
        "tracked_tree_clean": True,
        "tool_path": tool_logical,
        "source_sha256s": source_sha256s,
        "source_manifest_sha256": sha256_bytes(canonical(source_sha256s)),
        "runtime_flags": flags,
        "fast_engine": bool(FAST.HAVE_FAST),
        "fast_routed": bool(getattr(FAST, "_saved", None)),
        "native_path": None if native_path is None else str(native_path),
        "native_sha256": (None if native_path is None
                           else sha256_file(native_path)),
        "python_executable": sys.executable,
        "python_executable_resolved": str(python),
        "python_executable_sha256": sha256_file(python),
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def identity_receipt(manifest: dict, manifest_sha256: str,
                     tool_path: Path) -> dict:
    """Score-free provenance stamp bound into every census output."""
    return {
        "manifest_sha256": manifest_sha256,
        "manifest_internal_sha256": sha256_bytes(canonical(manifest)),
        **_source_receipt(tool_path),
    }


def build_manifest(logs_dir: str) -> dict:
    rows = []
    for path in sorted(Path(logs_dir).glob("*.jsonl")):
        if not regular_unlinked(path):
            raise SystemExit(f"REFUSED: input is not regular/unlinked: {path.name}")
        raw = stable_bytes(path)
        rounds, plays = _counts(raw, path.name)
        rows.append({"name": path.name, "sha256": sha256_bytes(raw),
                     "bytes": len(raw), "rounds": rounds, "plays": plays})
    if not rows:
        raise SystemExit(f"REFUSED: no .jsonl inputs under {logs_dir}")
    return {
        "schema": MANIFEST_SCHEMA,
        "allowed_use": list(ALLOWED_USE),
        "files": rows,
        "totals": {"files": len(rows),
                   "rounds": sum(r["rounds"] for r in rows),
                   "plays": sum(r["plays"] for r in rows)},
    }


def load_validated_manifest(
    manifest_path: str, logs_dir: str, expected_manifest_sha256: str,
) -> tuple[dict, list[ValidatedLog], str]:
    """Validate the frozen manifest against on-disk inputs; refuse any drift."""
    path = Path(manifest_path)
    if not is_sha256(expected_manifest_sha256):
        raise SystemExit("REFUSED: expected manifest SHA-256 is invalid")
    if not regular_unlinked(path):
        raise SystemExit("REFUSED: manifest is not regular/unlinked")
    raw_manifest = stable_bytes(path)
    if sha256_bytes(raw_manifest) != expected_manifest_sha256:
        raise SystemExit("REFUSED: manifest file SHA-256 drift")
    manifest = strict_json(raw_manifest, str(path))
    if raw_manifest != canonical(manifest):
        raise SystemExit("REFUSED: manifest is not canonical JSON")
    if (not isinstance(manifest, dict)
            or set(manifest) != {"schema", "allowed_use", "files", "totals"}
            or manifest.get("schema") != MANIFEST_SCHEMA
            or manifest.get("allowed_use") != list(ALLOWED_USE)
            or not isinstance(manifest.get("files"), list)
            or not manifest["files"]):
        raise SystemExit("REFUSED: manifest schema drift")
    rows = manifest["files"]
    names = [row.get("name") if isinstance(row, dict) else None
             for row in rows]
    if (any(not isinstance(name, str) or not name
            or Path(name).name != name or "/" in name or "\\" in name
            for name in names)
            or len(set(names)) != len(names) or names != sorted(names)):
        raise SystemExit("REFUSED: manifest file ordering/path drift")
    actual_paths = list(Path(logs_dir).glob("*.jsonl"))
    if any(not regular_unlinked(input_path) for input_path in actual_paths):
        raise SystemExit("REFUSED: manifest input population contains a link")
    actual_names = sorted(input_path.name for input_path in actual_paths)
    if actual_names != names:
        raise SystemExit("REFUSED: manifest input population drift")
    ordered = []
    totals = {"files": len(rows), "rounds": 0, "plays": 0}
    for row in rows:
        if (set(row) != {"name", "sha256", "bytes", "rounds", "plays"}
                or not is_sha256(row.get("sha256"))
                or any(isinstance(row.get(key), bool)
                       or not isinstance(row.get(key), int)
                       or row.get(key) < (1 if key == "bytes" else 0)
                       for key in ("bytes", "rounds", "plays"))):
            raise SystemExit("REFUSED: manifest row schema drift")
        input_path = Path(logs_dir) / row["name"]
        raw = stable_bytes(input_path)
        if sha256_bytes(raw) != row["sha256"] or len(raw) != row["bytes"]:
            raise SystemExit(f"REFUSED: manifest input drift: {row['name']}")
        rounds, plays = _counts(raw, row["name"])
        if (rounds, plays) != (row["rounds"], row["plays"]):
            raise SystemExit(f"REFUSED: manifest input count drift: {row['name']}")
        totals["rounds"] += rounds
        totals["plays"] += plays
        ordered.append(ValidatedLog(row["name"], raw))
    if (not isinstance(manifest.get("totals"), dict)
            or set(manifest["totals"]) != {"files", "rounds", "plays"}
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0 for value in manifest["totals"].values())
            or manifest["totals"] != totals):
        raise SystemExit("REFUSED: manifest totals drift")
    return manifest, ordered, expected_manifest_sha256


def iter_decisions(ordered_paths):
    """Yield (file, round_no, event_index, rnd, seat, human_cards) in
    manifest order at each genuine human play decision."""
    for item in ordered_paths:
        events = log_events(item.raw, item.name)
        first = next((event for event in events
                      if event.get("e") == "round_start"), None)
        if not first:
            continue
        excluded = {p["seat"] for p in first["players"]
                    if p["name"] in EXCLUDE_PLAYERS}
        for rno, evs in sorted(group_events(events, item.name).items()):
            rnd = rebuild_round(evs)
            if rnd is None:
                continue
            plays = [e for e in evs if e["e"] == "play"]
            for index, e in enumerate(plays):
                seat, cards = e["seat"], e["cards"]
                if (rnd.phase == "play" and not e.get("bot")
                        and seat not in excluded):
                    yield item.name, rno, index, rnd, seat, list(cards)
                try:
                    rnd.play(seat, list(cards))
                except Exception:
                    break


def decision_key(manifest_sha: str, file: str, rno: int, index: int) -> int:
    """Stable per-decision seed independent of iteration order."""
    raw = f"{manifest_sha}:{file}:{rno}:{index}".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big")


def trick_context(rnd, seat):
    """(is_lead, winning_play, partner_winning, trick_points, seats_to_act)."""
    t = rnd.trick
    if t is None or not t.plays:
        return True, None, False, 0, []
    win_seat, inc_suit, inc_top = _HB._current_winner(rnd)
    winning = next(p for p in t.plays if p.seat == win_seat)
    tpts = sum(points(c) for tp in t.plays for c in tp.cards)
    order = [(t.leader + k) % 4 for k in range(4)]
    played = {p.seat for p in t.plays}
    to_act = [s for s in order if s not in played and s != seat]
    return False, (winning, inc_suit, inc_top), win_seat % 2 == seat % 2, tpts, to_act


def legal_point_actions(rnd, seat):
    """Legal follow actions carrying points, via the engine ballot."""
    try:
        actions = enumerate_actions(rnd, seat, exhaustive_follows=True)
    except Exception:
        raise SystemExit("REFUSED: legality enumeration failed")
    return [a for a in actions if sum(points(c) for c in a) > 0]


def classify_boss(rnd, seat, winning_play, inc_suit, inc_top, to_act):
    """Public-info incumbent classification.

    literal   — the rollout gate's own predicate (trump or top plain rank).
    inferred  — not literal, but Memory (public info) proves no unseen card
                of the incumbent's shape beats it; `strict` additionally
                requires no ruff risk from the seats still to act.
    open      — neither.  Multi-component incumbents are labeled complex.
    """
    o = rnd.ordering
    literal = inc_suit == TRUMP or inc_top >= len(o.plain_ranks) - 1
    cards = winning_play.cards
    if literal:
        return "literal", True
    mem = Memory(rnd, seat)
    if len(cards) == 1:
        boss = mem.is_boss(cards[0])
    elif len(cards) == 2 and cards[0] == cards[1]:
        boss = mem.pair_is_boss(cards[0])
    else:
        return "complex", False
    if not boss:
        return "open", False
    lead_suit = inc_suit
    strict = not mem.ruff_risk(lead_suit, to_act)
    return ("inferred_strict" if strict else "inferred_loose"), False


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return round(center - half, 4), round(center + half, 4)
