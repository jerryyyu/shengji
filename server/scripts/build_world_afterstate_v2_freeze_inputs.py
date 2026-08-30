"""Build the five inert, typed inputs required by the Value V2 freeze."""

from __future__ import annotations

import os
import sys


# Refuse the ambient import surface before importing project code.  The CLI is
# tied to the repository that physically contains this script; ``--repo`` may
# confirm that identity but may not redirect execution to another checkout.
if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("Value V2 freeze-input builder requires Python -P -B")
if os.environ.get("PYTHONPATH"):
    raise RuntimeError("Value V2 freeze-input builder refuses PYTHONPATH")

from pathlib import Path  # noqa: E402

SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
if not sys.path or sys.path[0] != str(SERVER):
    sys.path.insert(0, str(SERVER))


def _preimport_bytecode_scan(
        prefixes: tuple[Path, ...] | None = None) -> None:
    """Refuse ignored bytecode before importing any project module."""
    roots = prefixes or (SERVER / "scripts", SERVER / "shengji")
    for prefix in roots:
        if not prefix.is_dir() or prefix.is_symlink():
            raise RuntimeError("Value V2 freeze-input source root drift")
        for _current, dirs, files in os.walk(
                prefix, topdown=True, followlinks=False):
            if "__pycache__" in dirs or any(name.endswith(".pyc")
                                              for name in files):
                raise RuntimeError(
                    "Value V2 freeze-input builder refuses source bytecode artifacts")


if __name__ == "__main__":
    _preimport_bytecode_scan()

import argparse  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402

from shengji.rl import world_afterstate_v2_freeze_inputs as _inputs_module  # noqa: E402
from shengji.rl import world_afterstate_v2_freeze_builder as _builder_module  # noqa: E402
from shengji.rl.world_afterstate_v2_freeze_inputs import (  # noqa: E402
    build_freeze_inputs_v2, capacity_context, publish_inputs_v2,
)
from shengji.rl.world_afterstate_v2_freeze_builder import (  # noqa: E402
    capacity_source_sha256,
)


for _module in (_inputs_module, _builder_module):
    if not Path(_module.__file__).resolve().is_relative_to(SERVER.resolve()):
        raise RuntimeError("Value V2 freeze-input builder module origin drift")


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(("git", *args), cwd=repo, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("source Git authentication failed") from exc


def _read(path: Path, label: str) -> bytes:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise SystemExit(f"{label} path drift")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"{label} cannot be read") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--source-git", required=True)
    parser.add_argument("--capacity", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--deadline-seconds", type=int, required=True)
    parser.add_argument("--heartbeat-seconds", type=int, required=True)
    parser.add_argument("--max-attempts-per-slot", type=int, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    repo = args.repo
    if (not repo.is_absolute() or repo.is_symlink() or not repo.is_dir()
            or repo.resolve() != REPO.resolve()
            or args.source_git != _git(repo, "rev-parse", "HEAD")
            or _git(repo, "status", "--porcelain", "--untracked-files=all")):
        raise SystemExit("source Git differs from expected")
    evidence = args.evidence_root
    if not evidence.is_absolute() or evidence.exists() or evidence.is_symlink():
        raise SystemExit("evidence root must be absolute and unused")
    capacity_raw = _read(args.capacity, "capacity receipt")
    capacity, _tier, _population_workers, _label_workers = capacity_context(
        capacity_raw)
    if capacity.source_sha256 != capacity_source_sha256(repo):
        raise SystemExit("capacity receipt source differs from expected")
    values = build_freeze_inputs_v2(
        source_git=args.source_git, capacity_raw=capacity_raw,
        evidence_root=str(evidence), deadline_seconds=args.deadline_seconds,
        heartbeat_seconds=args.heartbeat_seconds,
        max_attempts_per_slot=args.max_attempts_per_slot)
    publish_inputs_v2(
        args.out_dir, protocol=values["protocol"],
        population=json.loads(values["population"]),
        config=json.loads(values["config"]),
        seed=json.loads(values["seed"]),
        continuation_policy=json.loads(values["continuation-policy"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
