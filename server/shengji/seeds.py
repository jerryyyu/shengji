"""Seed-window registry: the committed ledger of every deal window a data
run has consumed, and the refusal that keeps two runs off the same deals.

Every generator and screen deals cluster ``c`` from ``seed0 + c``, so a run
is a half-open window of deal seeds ``[seed0, seed0 + clusters)``.  Run A
(seed0 20260905, 8,000 clusters) and Run B (seed0 20260906, 8,000) shared
7,999 of 8,000 deals and Run B added nothing in training; nothing in the
code refused it -- the check lived in a memory.  This module makes the
registry a file (``server/runs/seed_windows.json``, committed, append-only)
and the check a refusal that every run performs BEFORE it deals anything.

Covered entry points (each calls ``check_and_register`` before it deals):
``shengji.harvest.trajectory.generate`` (``scripts/trajectory.py``),
``scripts/cwv_duel.py calibrate`` and ``run``, ``scripts/vleaf_screen.py
calibrate`` and ``run``, ``scripts/netroll_screen.py calibrate`` and ``run``.
NOT wired yet: ``cwv_shortlist_screen``, ``learned_search_screen``,
``world_shortlist_screen`` and ``oracle_screen`` -- their windows are neither
checked nor registered.  The registry is a file local to this checkout /
path: the check excludes overlaps within one checkout only, and the
committed file on ``main`` is the source of truth that a cross-host
allocation must consult (and append to, via a merged PR); this is not a
fleet-wide exclusion.

Rules:

* a ``trajectory`` window (training data) must be disjoint from EVERY
  registered window; ``--allow-seed-overlap`` is the explicit override and
  the manifest records the conflicts;
* a ``screen`` window must never overlap a ``trajectory`` window (the net
  would be screened on its own training deals); overlap with another
  screen / calibration window is allowed only with ``--allow-seed-overlap``
  because same-seed replication is a deliberate design, and the run's
  manifest records which window it replicates;
* a ``calibration`` window (outcome-blind) must not overlap a trajectory
  window; it is registered so later windows can see it;
* every run registers its window on start; a resume / rerun of the same run
  (same name, seed0 and clusters) is accepted, a different span under the
  same name refuses.

``check_and_register`` is ONE transaction -- read, check, append, write --
under an exclusive ``fcntl.flock`` on the stable lock file
``<registry>.lock`` next to the registry (never on the registry inode
itself, which ``os.replace`` swaps on every write), so two concurrent
requests for the same span cannot both be admitted: the second re-reads the
registry inside the lock and sees the first.

``SHENGJI_SEED_WINDOWS`` points the registry elsewhere (tests; a scratch
registry); the default is the committed file.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import platform
import subprocess
import tempfile
import time
from pathlib import Path

SCHEMA = "shengji-seed-windows-v1"
PURPOSES = ("trajectory", "screen", "calibration", "other")
ENV_VAR = "SHENGJI_SEED_WINDOWS"
DEFAULT_REGISTRY = Path(__file__).resolve().parents[1] / "runs" / "seed_windows.json"
ENTRY_KEYS = ("name", "purpose", "seed0", "clusters", "span", "created_at",
              "host", "git_head", "note")


class SeedWindowError(RuntimeError):
    """A seed window overlaps a registered one, or the registry refuses an
    entry (duplicate name with a different span, malformed file)."""


# ----------------------------------------------------------------- windows

def window(seed0: int, clusters: int) -> tuple[int, int]:
    """The half-open deal-seed span ``[seed0, seed0 + clusters)``."""
    seed0, clusters = int(seed0), int(clusters)
    if clusters < 1:
        raise SeedWindowError(f"a seed window needs clusters >= 1, got {clusters}")
    return seed0, seed0 + clusters


def span_of(entry: dict) -> tuple[int, int]:
    lo, hi = entry["span"]
    return int(lo), int(hi)


def overlap_span(a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int] | None:
    """The seeds two half-open spans share, or None when disjoint."""
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    return (lo, hi) if lo < hi else None


def registry_path(path: str | os.PathLike | None = None) -> Path:
    """``path`` if given, else ``$SHENGJI_SEED_WINDOWS``, else the committed file."""
    if path is not None:
        return Path(path)
    override = os.environ.get(ENV_VAR)
    return Path(override) if override else DEFAULT_REGISTRY


def load(path: str | os.PathLike | None = None) -> dict:
    """The registry document (``{"schema", "windows": [...]}``); a missing
    file is an empty registry so a scratch path works from nothing."""
    file = registry_path(path)
    if not file.exists():
        return {"schema": SCHEMA, "windows": []}
    try:
        doc = json.loads(file.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SeedWindowError(f"{file}: not valid JSON ({exc})") from exc
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA \
            or not isinstance(doc.get("windows"), list):
        raise SeedWindowError(f"{file}: not a {SCHEMA} registry")
    for entry in doc["windows"]:
        _validate(entry, file)
    return doc


def _validate(entry: dict, where) -> None:
    missing = [k for k in ENTRY_KEYS if k not in entry]
    if missing:
        raise SeedWindowError(f"{where}: window {entry.get('name')!r} lacks {missing}")
    if entry["purpose"] not in PURPOSES:
        raise SeedWindowError(f"{where}: window {entry['name']!r} has purpose "
                              f"{entry['purpose']!r}, not one of {PURPOSES}")
    if tuple(entry["span"]) != window(entry["seed0"], entry["clusters"]):
        raise SeedWindowError(f"{where}: window {entry['name']!r} span {entry['span']} "
                              f"!= [seed0, seed0 + clusters) = "
                              f"{list(window(entry['seed0'], entry['clusters']))}")


def find(registry: dict, name: str) -> dict | None:
    for entry in registry["windows"]:
        if entry["name"] == name:
            return entry
    return None


def overlaps(registry: dict, seed0: int, clusters: int, *, purposes=None,
             exclude_name: str | None = None) -> list[dict]:
    """The registered windows whose span meets ``[seed0, seed0 + clusters)``,
    each returned as ``{**entry, "overlap": [lo, hi], "overlap_seeds": n}``.
    ``purposes`` restricts to those purposes; ``exclude_name`` skips the
    caller's own window (a resume)."""
    span = window(seed0, clusters)
    hits = []
    for entry in registry["windows"]:
        if exclude_name is not None and entry["name"] == exclude_name:
            continue
        if purposes is not None and entry["purpose"] not in purposes:
            continue
        shared = overlap_span(span, span_of(entry))
        if shared is not None:
            hits.append({**entry, "overlap": [shared[0], shared[1]],
                         "overlap_seeds": shared[1] - shared[0]})
    return hits


def describe(conflict: dict) -> str:
    lo, hi = conflict["overlap"]
    return (f"{conflict['name']} ({conflict['purpose']}, seed0 {conflict['seed0']}, "
            f"{conflict['clusters']} clusters, span [{conflict['span'][0]}, "
            f"{conflict['span'][1]})) shares {conflict['overlap_seeds']} deal seed(s) "
            f"[{lo}, {hi})")


def require_disjoint(registry: dict, seed0: int, clusters: int, *, purposes=None,
                     exclude_name: str | None = None, what: str = "the requested window",
                     allow: bool = False) -> list[dict]:
    """Raise ``SeedWindowError`` naming every conflicting window and the
    overlapping seed range; return ``[]`` when the window is disjoint.
    ``allow`` (the caller's explicit ``--allow-seed-overlap``) returns the
    conflicts instead of raising."""
    hits = overlaps(registry, seed0, clusters, purposes=purposes, exclude_name=exclude_name)
    if hits and not allow:
        lo, hi = window(seed0, clusters)
        raise SeedWindowError(
            f"seed window [{lo}, {hi}) (seed0 {seed0}, {clusters} clusters) for {what} "
            f"overlaps {len(hits)} registered window(s): "
            + "; ".join(describe(h) for h in hits)
            + ". Pick a disjoint seed0 (scripts/seed_windows.py check SEED0 CLUSTERS), "
              "or pass --allow-seed-overlap for a deliberate replicate")
    return hits


# ---------------------------------------------------------------- register

def git_head() -> str | None:
    repo = Path(__file__).resolve().parents[2]
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def make_entry(*, name: str, purpose: str, seed0: int, clusters: int,
               note: str = "", created_at: str | None = None,
               host: str | None = None, git_head_sha: str | None = None) -> dict:
    if purpose not in PURPOSES:
        raise SeedWindowError(f"purpose {purpose!r} is not one of {PURPOSES}")
    lo, hi = window(seed0, clusters)
    return {"name": str(name), "purpose": purpose, "seed0": int(seed0),
            "clusters": int(clusters), "span": [lo, hi],
            "created_at": created_at or time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "host": host or platform.node(),
            "git_head": git_head_sha if git_head_sha is not None else git_head(),
            "note": str(note)}


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def lock_path(path: str | os.PathLike | None = None) -> Path:
    """The stable lock file next to the registry (``<registry>.lock``)."""
    file = registry_path(path)
    return file.with_name(file.name + ".lock")


@contextlib.contextmanager
def locked(path: str | os.PathLike | None = None):
    """Hold the registry's exclusive ``fcntl.flock`` for the block.  The
    lock lives on a separate, never-replaced file: the registry itself is
    swapped by ``os.replace`` on every write, so a lock on its inode would
    protect nothing.  Not re-entrant (flock is per open file description)."""
    lock = lock_path(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def register(entry: dict, path: str | os.PathLike | None = None, *,
             reuse: bool = False) -> dict:
    """Append ``entry`` to the registry atomically (temp file + os.replace)
    under the registry lock.  A duplicate name refuses -- unless ``reuse``
    and the registered window has the same seed0 and clusters (a resume /
    rerun of the same run), in which case the existing entry is returned
    unchanged and nothing is written.  Returns the entry now in the
    registry.  Standalone use: no overlap check (see ``check_and_register``
    for the checked transaction)."""
    with locked(path):
        return _register_locked(entry, path, reuse=reuse)


def _register_locked(entry: dict, path=None, *, reuse: bool = False) -> dict:
    """``register`` inside an already-held registry lock."""
    file = registry_path(path)
    _validate(entry, "new entry")
    registry = load(file)
    existing = find(registry, entry["name"])
    if existing is not None:
        same = (existing["seed0"], existing["clusters"]) == (entry["seed0"], entry["clusters"])
        if reuse and same:
            return existing
        raise SeedWindowError(
            f"{file}: window {entry['name']!r} is already registered "
            f"(seed0 {existing['seed0']}, {existing['clusters']} clusters, "
            f"{existing['purpose']}, created {existing['created_at']})"
            + ("" if same else f"; the requested span [{entry['span'][0]}, "
                               f"{entry['span'][1]}) differs")
            + "; a resume must reuse its own window, a new run needs a new name")
    registry["windows"].append(entry)
    _atomic_write(file, json.dumps(registry, indent=2, sort_keys=False) + "\n")
    return entry


def check_and_register(*, name: str, purpose: str, seed0: int, clusters: int,
                       refuse: tuple[str, ...] | None, allow_overlap: bool = False,
                       resume: bool = False, note: str = "", path=None,
                       what: str | None = None) -> dict:
    """The one call the scripts make on start: refuse (or, with
    ``allow_overlap``, record) the overlaps, then register the window --
    as ONE transaction under the registry lock (read, check, append,
    write), so of two concurrent requests for overlapping spans exactly one
    is admitted and the other refuses naming it.

    ``refuse`` names the purposes an overlap always refuses (None = every
    purpose); overlaps with the other purposes refuse unless
    ``allow_overlap``.  Returns the receipt the caller stamps in its
    manifest: ``{"registry", "name", "purpose", "seed0", "clusters", "span",
    "resumed", "allow_seed_overlap", "conflicts": [...]}`` -- ``conflicts``
    are the windows this run deliberately replicates."""
    file = registry_path(path)
    what = what or f"{purpose} run {name}"
    exclude = name if resume else None
    always = PURPOSES if refuse is None else tuple(refuse)
    with locked(file):
        registry = load(file)                       # re-read INSIDE the lock
        require_disjoint(registry, seed0, clusters, purposes=always, exclude_name=exclude,
                         what=what)
        conflicts = overlaps(registry, seed0, clusters, exclude_name=exclude)
        if conflicts and not allow_overlap:
            require_disjoint(registry, seed0, clusters, exclude_name=exclude, what=what)
        entry = _register_locked(make_entry(name=name, purpose=purpose, seed0=seed0,
                                            clusters=clusters, note=note),
                                 file, reuse=resume)
    lo, hi = window(seed0, clusters)
    return {"registry": str(file), "name": name, "purpose": purpose, "seed0": int(seed0),
            "clusters": int(clusters), "span": [lo, hi], "resumed": bool(resume),
            "allow_seed_overlap": bool(allow_overlap),
            "conflicts": [{"name": c["name"], "purpose": c["purpose"], "seed0": c["seed0"],
                           "clusters": c["clusters"], "overlap": c["overlap"],
                           "overlap_seeds": c["overlap_seeds"]} for c in conflicts]}
