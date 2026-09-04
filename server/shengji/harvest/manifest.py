"""Extraction manifests: counts per source, sha256 of every input file read
and of every output JSONL.  Encoder-free by design (records are raw)."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .common import ExtractResult, sha256_file, write_jsonl
from .schema import SCHEMA

MANIFEST_SCHEMA = "shengji-harvest-manifest-v1"
SOURCE_ORDER = ("luna-rpc", "room-log", "pt1", "highn", "human")


def _git_head() -> str | None:
    repo = Path(__file__).resolve().parents[3]
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo,
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def write_source(out_dir: Path, result: ExtractResult, *, cap: int | None) -> dict:
    """Write ``<source>.jsonl`` (+ ``<source>.private.jsonl`` when the source
    has hidden hands) and the per-source sidecar ``<source>.manifest.json``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, dict] = {}
    public_path = out_dir / f"{result.source}.jsonl"
    n, digest = write_jsonl(public_path, result.public)
    outputs[public_path.name] = {"records": n, "sha256": digest, "private": False}
    private_path = out_dir / f"{result.source}.private.jsonl"
    if result.private:
        n, digest = write_jsonl(private_path, result.private, private=True)
        outputs[private_path.name] = {"records": n, "sha256": digest, "private": True}
    elif private_path.exists():
        private_path.unlink()
    sidecar = {
        "schema": MANIFEST_SCHEMA,
        "record_schema": SCHEMA,
        "source": result.source,
        "counts": dict(result.counts),
        "legal_actions_cap": cap,
        "notes": list(result.notes),
        "extras": result.extras,
        "inputs": list(result.inputs),
        "outputs": outputs,
        "encoder": None,
        "git_head": _git_head(),
    }
    path = out_dir / f"{result.source}.manifest.json"
    path.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n")
    return sidecar


def _count_records(path: Path) -> int:
    with path.open("rb") as fh:
        return sum(1 for _ in fh)


def build_manifest(out_dir: Path) -> dict:
    """Merge the per-source sidecars in ``out_dir`` into ``manifest.json``.

    The sidecars DECLARE the output population and this step closes it:
    every declared output must exist with its declared sha256, record count
    and private flag (private files must be named ``*.private.jsonl`` and be
    mode 0600), and every ``*.jsonl`` present must be declared by exactly one
    sidecar.  Any drift refuses instead of being recorded.
    """
    out_dir = Path(out_dir)
    sources: dict[str, dict] = {}
    declared: dict[str, tuple[str, dict]] = {}
    for path in sorted(out_dir.glob("*.manifest.json")):
        sidecar = json.loads(path.read_text())
        source = sidecar["source"]
        if source in sources:
            raise RuntimeError(f"{path.name}: duplicate sidecar for {source}")
        sources[source] = {k: v for k, v in sidecar.items()
                           if k not in ("schema", "record_schema")}
        for name, info in sidecar.get("outputs", {}).items():
            if name in declared:
                raise RuntimeError(f"{name}: declared by two sidecars")
            declared[name] = (source, info)
    present = {p.name for p in out_dir.glob("*.jsonl")}
    undeclared = sorted(present - set(declared))
    if undeclared:
        raise RuntimeError(f"undeclared output files: {undeclared}")
    outputs: dict[str, dict] = {}
    for name in sorted(declared):
        source, info = declared[name]
        # the declared name must be one plain file name inside out_dir: no
        # separators, no parent references, nothing a sidecar could use to
        # bind the manifest to bytes outside the extraction directory
        if (not name or name in (".", "..") or "/" in name or "\\" in name
                or name != Path(name).name):
            raise RuntimeError(f"{name!r}: output name must be a plain file name")
        path = out_dir / name
        try:
            st = os.lstat(path)                      # never follow a symlink
        except FileNotFoundError:
            raise RuntimeError(f"{name}: declared by {source} but missing") from None
        if stat.S_ISLNK(st.st_mode):
            raise RuntimeError(f"{name}: declared output is a symlink")
        if not stat.S_ISREG(st.st_mode):
            raise RuntimeError(f"{name}: declared output is not a regular file")
        private = bool(info.get("private", False))
        if private != name.endswith(".private.jsonl"):
            raise RuntimeError(f"{name}: private flag does not match its name")
        mode = st.st_mode & 0o777
        if private and mode != 0o600:
            raise RuntimeError(f"{name}: private output mode {oct(mode)} is not 0600")
        digest = sha256_file(path)
        if digest != info.get("sha256"):
            raise RuntimeError(f"{name}: sha256 differs from its sidecar")
        records = _count_records(path)
        if records != int(info.get("records", -1)):
            raise RuntimeError(f"{name}: record count {records} differs from "
                               f"its sidecar ({info.get('records')})")
        outputs[name] = {"sha256": digest, "bytes": st.st_size,
                         "records": records, "private": private, "mode": oct(mode)}
    gap_path = out_dir / "ballot_gap.json"
    ballot_gap = None
    if gap_path.is_file():
        ballot_gap = {"path": gap_path.name, "sha256": sha256_file(gap_path)}
    totals = {"decisions": 0, "rounds": 0, "private_records": 0}
    for source, sidecar in sources.items():
        counts = sidecar.get("counts", {})
        totals["decisions"] += int(counts.get("decisions", 0))
        totals["rounds"] += int(counts.get("rounds", 0))
        totals["private_records"] += int(counts.get("private_records", 0))
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "record_schema": SCHEMA,
        "created_at": datetime.now(UTC).isoformat(),
        "git_head": _git_head(),
        "encoder": None,
        "sources": {k: sources[k] for k in SOURCE_ORDER if k in sources}
                   | {k: v for k, v in sources.items() if k not in SOURCE_ORDER},
        "totals": totals,
        "outputs": outputs,
        "ballot_gap": ballot_gap,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def summary_lines(manifest: dict) -> list[str]:
    lines = []
    for source, sidecar in manifest["sources"].items():
        c = sidecar.get("counts", {})
        lines.append(f"{source}: rounds={c.get('rounds')} decisions={c.get('decisions')} "
                     f"private={c.get('private_records', 0)} "
                     + " ".join(f"{k}={v}" for k, v in c.items()
                                if k not in ("rounds", "decisions", "private_records")))
    t = manifest["totals"]
    lines.append(f"TOTAL: rounds={t['rounds']} decisions={t['decisions']} "
                 f"private={t['private_records']}")
    return lines
