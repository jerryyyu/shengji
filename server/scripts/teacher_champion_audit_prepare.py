#!/usr/bin/env python3
"""Prepare the frozen Teacher champion audit after a Stage-B PASS.

This external stdlib-only controller copies the exact terminal Stage-B parent
population into the independently frozen audit checkout and runs the audit
receipt creator synchronously.  It is intentionally separate from both the
result-producing evaluator and the label-worker supervisor.

The command is one-shot.  It never retries, resumes, overwrites, removes an
artifact, chooses an observed result, or launches an audit label.  A failure
leaves its partial/copy evidence in place and closes the attempt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


SCHEMA = "teacher-v1-champion-audit-preparation-v1"
EXIT_SCHEMA = "teacher-v1-champion-audit-receipt-exit-v1"
PRODUCER_GIT = "1a2a71333ea283784b19855e67e1ae231379ec79"
AUDIT_GIT = "182d1df21697cedd722edfd3215ea1e2a7dd8753"
AUDIT_SCRIPT_SHA256 = (
    "57796fda247a4152a58bb98508d24ae1063f7e2c843ccf436b8b111f7c887ead"
)
STAGE_B_STATE_SHA256 = (
    "90956da86f4f03074a1b4dc2d7198a3da5958470b733eacd104e066c523b4dc6"
)
AUDIT_STATE_SHA256 = (
    "d04d1c0fa507bab680da4d53eeb72325a97c8ca058aac0d01c16dfdcf44f7a34"
)
EXPECTED_PYTHON_VERSION = "Python 3.14.6"
RUN_ID = "teacher-v3-report-lcb-audit-v1-149m"
NAMESPACE = Path("runs/logs/teacher-v1-entry-149m-v3")
AUDIT_SCRIPT = Path("scripts/teacher_v1_champion_audit.py")
SUPERVISOR_SCRIPT_NAME = "teacher_champion_audit_supervisor.py"
STAGE_B_STATE_NAME = "stage_b_states.json"
AUDIT_STATE_NAME = "champion_audit_states.json"
STAGE_B_GATE_NAME = "stage_b_gate_v2.json"
CHEAP_RECEIPT_NAME = "stage_b_cheap_v2_receipt.json"
GOLD_RECEIPT_NAME = "stage_b_gold_v2_receipt.json"
AUDIT_RECEIPT_NAME = "champion_audit_receipt_v1.json"
PREPARATION_NAME = "champion_audit_preparation_v1.json"
SHARDS = 8
LABEL_NAMES = tuple(
    f"champion_audit_v1_shard{index:02d}.json" for index in range(SHARDS))
DESCENDANT_NAMES = (
    *LABEL_NAMES,
    "champion_audit_gate_v1.json",
    "champion_audit_supervisor_v1.jsonl",
)


class PreparationRefusal(RuntimeError):
    """The one-shot preparation boundary was violated."""


@dataclass(frozen=True)
class Config:
    producer_root: Path
    audit_root: Path
    python: Path
    expected_gate_sha256: str
    expected_preparer_sha256: str
    expected_supervisor_sha256: str


@dataclass(frozen=True)
class PreparationPaths:
    producer_namespace: Path
    audit_namespace: Path
    audit_script: Path
    audit_state: Path
    receipt: Path
    receipt_log: Path
    receipt_exit: Path
    preparation: Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def is_regular_unlinked(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def lexists(path: Path) -> bool:
    return os.path.lexists(path)


def adjacent_partial(path: Path) -> Path:
    return Path(str(path) + ".partial")


def paths_for(config: Config) -> PreparationPaths:
    producer_namespace = config.producer_root.resolve() / NAMESPACE
    audit_namespace = config.audit_root.resolve() / NAMESPACE
    return PreparationPaths(
        producer_namespace=producer_namespace,
        audit_namespace=audit_namespace,
        audit_script=config.audit_root.resolve() / AUDIT_SCRIPT,
        audit_state=audit_namespace / AUDIT_STATE_NAME,
        receipt=audit_namespace / AUDIT_RECEIPT_NAME,
        receipt_log=audit_namespace / "champion_audit_receipt_v1.log",
        receipt_exit=audit_namespace / "champion_audit_receipt_v1.exit.json",
        preparation=audit_namespace / PREPARATION_NAME,
    )


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _load_json(path: Path) -> Mapping[str, object]:
    if not is_regular_unlinked(path) or lexists(adjacent_partial(path)):
        raise PreparationRefusal(
            f"artifact is missing/nonregular/partial {path}")
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise PreparationRefusal(f"artifact cannot reopen {path}: {exc}") \
            from exc
    if not isinstance(payload, Mapping):
        raise PreparationRefusal(f"artifact is not an object {path}")
    return payload


def _load_pinned(path: Path, expected_sha256: str) -> Mapping[str, object]:
    if not is_sha256(expected_sha256):
        raise PreparationRefusal(f"malformed expected SHA for {path}")
    if not is_regular_unlinked(path) or lexists(adjacent_partial(path)):
        raise PreparationRefusal(
            f"artifact is missing/nonregular/partial {path}")
    if sha256_file(path) != expected_sha256:
        raise PreparationRefusal(f"artifact SHA drift {path}")
    return _load_json(path)


def _relative_item(item: object, *, expected_name: str,
                   expected_shard: int | None = None) -> tuple[Path, str]:
    if not isinstance(item, Mapping):
        raise PreparationRefusal(f"gate item {expected_name} is malformed")
    path = item.get("path")
    digest = item.get("sha256")
    expected = NAMESPACE / expected_name
    if path != str(expected) or not is_sha256(digest):
        raise PreparationRefusal(f"gate item {expected_name} binding drift")
    if expected_shard is not None and item.get("shard_index") != expected_shard:
        raise PreparationRefusal(f"gate item {expected_name} shard drift")
    return expected, str(digest)


def gate_parents(config: Config, paths: PreparationPaths) -> dict[str, object]:
    gate_path = paths.producer_namespace / STAGE_B_GATE_NAME
    gate = _load_pinned(gate_path, config.expected_gate_sha256)
    if (gate.get("schema") != "teacher-v1-gate-v1"
            or gate.get("complete") is not True
            or gate.get("stage") != "B"
            or gate.get("verdict") != "PASS"
            or gate.get("stage_c_authorized") is not True
            or gate.get("problems") != []):
        raise PreparationRefusal("Stage-B gate is not an exact terminal PASS")
    state_path, state_sha = _relative_item(
        gate.get("state_set"), expected_name=STAGE_B_STATE_NAME)
    if state_sha != STAGE_B_STATE_SHA256:
        raise PreparationRefusal("Stage-B state SHA differs from frozen parent")
    populations: dict[str, list[tuple[Path, str]]] = {}
    for field, stem in (("cheap_inputs", "stage_b_cheap_v2_shard"),
                        ("gold_inputs", "stage_b_gold_v2_shard")):
        items = gate.get(field)
        if not isinstance(items, list) or len(items) != SHARDS:
            raise PreparationRefusal(f"Stage-B gate {field} population drift")
        population = []
        for shard, item in enumerate(items):
            population.append(_relative_item(
                item, expected_name=f"{stem}{shard:02d}.json",
                expected_shard=shard))
        populations[field] = population
    return {
        "gate": gate,
        "gate_ref": {"path": str(NAMESPACE / STAGE_B_GATE_NAME),
                     "sha256": config.expected_gate_sha256},
        "state": (state_path, state_sha),
        **populations,
    }


def _receipt_binding(
        config: Config, paths: PreparationPaths,
        population: list[tuple[Path, str]], *, role: str,
        expected_name: str) -> tuple[Path, str]:
    bindings = []
    for relative, digest in population:
        manifest = _load_pinned(config.producer_root / relative, digest)
        binding = manifest.get("producer_receipt")
        if not isinstance(binding, Mapping):
            raise PreparationRefusal(f"{relative} lacks producer receipt")
        bindings.append(dict(binding))
    first = bindings[0]
    if any(binding != first for binding in bindings[1:]):
        raise PreparationRefusal(f"{role} receipt binding differs by shard")
    relative = NAMESPACE / expected_name
    if (first.get("path") != str(relative)
            or first.get("role") != role
            or not is_sha256(first.get("sha256"))
            or not is_sha256(first.get("nonce"))
            or not isinstance(first.get("run_id"), str)):
        raise PreparationRefusal(f"{role} receipt binding drift")
    receipt = _load_pinned(
        config.producer_root / relative, str(first["sha256"]))
    if (receipt.get("schema") != "teacher-v1-producer-receipt-v1"
            or receipt.get("complete") is not True
            or receipt.get("role") != role
            or receipt.get("run_id") != first["run_id"]
            or receipt.get("nonce") != first["nonce"]):
        raise PreparationRefusal(f"{role} receipt identity drift")
    return relative, str(first["sha256"])


def parent_population(config: Config, paths: PreparationPaths) -> dict[str, object]:
    parents = gate_parents(config, paths)
    cheap = parents["cheap_inputs"]
    gold = parents["gold_inputs"]
    assert isinstance(cheap, list) and isinstance(gold, list)
    cheap_receipt = _receipt_binding(
        config, paths, cheap, role="stage-b-cheap",
        expected_name=CHEAP_RECEIPT_NAME)
    gold_receipt = _receipt_binding(
        config, paths, gold, role="stage-b-gold",
        expected_name=GOLD_RECEIPT_NAME)
    ordered = [
        parents["state"], cheap_receipt, gold_receipt,
        *cheap, *gold,
        (NAMESPACE / STAGE_B_GATE_NAME, config.expected_gate_sha256),
    ]
    if len(ordered) != 20 or len({item[0] for item in ordered}) != 20:
        raise PreparationRefusal("audit parent population is not exact 20")
    for relative, digest in ordered:
        _load_pinned(config.producer_root / relative, digest)
    return {**parents, "cheap_receipt": cheap_receipt,
            "gold_receipt": gold_receipt, "ordered": ordered}


def preflight_problems(config: Config, paths: PreparationPaths) -> list[str]:
    problems = []
    if config.producer_root.resolve() == config.audit_root.resolve():
        problems.append("producer and audit roots must be distinct")
    for label, root, expected in (
            ("producer", config.producer_root, PRODUCER_GIT),
            ("audit", config.audit_root, AUDIT_GIT)):
        try:
            head = _git(root, "rev-parse", "HEAD")
            dirty = _git(root, "status", "--porcelain", "--untracked-files=all")
        except (OSError, subprocess.SubprocessError) as exc:
            problems.append(f"{label} git inspection failed: {exc}")
            continue
        if head != expected:
            problems.append(f"{label} git {head}, expected {expected}")
        if dirty:
            problems.append(f"{label} worktree is dirty")
    if not is_regular_unlinked(paths.audit_script) \
            or sha256_file(paths.audit_script) != AUDIT_SCRIPT_SHA256:
        problems.append("frozen audit script identity drift")
    if not is_regular_unlinked(paths.audit_state) \
            or sha256_file(paths.audit_state) != AUDIT_STATE_SHA256 \
            or lexists(adjacent_partial(paths.audit_state)):
        problems.append("frozen audit state identity drift")
    if not config.python.is_file() or not os.access(config.python, os.X_OK):
        problems.append(f"audit Python is not executable {config.python}")
    else:
        try:
            version_run = subprocess.run(
                [str(config.python), "--version"], check=False,
                capture_output=True, text=True)
            version = (version_run.stdout or version_run.stderr).strip()
        except OSError as exc:
            problems.append(f"audit Python version check failed: {exc}")
        else:
            if version_run.returncode or version != EXPECTED_PYTHON_VERSION:
                problems.append(
                    f"audit Python {version!r}, expected "
                    f"{EXPECTED_PYTHON_VERSION!r}")
    if (not is_sha256(config.expected_preparer_sha256)
            or sha256_file(Path(__file__).resolve())
            != config.expected_preparer_sha256):
        problems.append("preparer SHA predeclaration drift")
    supervisor_script = Path(__file__).resolve().with_name(
        SUPERVISOR_SCRIPT_NAME)
    if not is_sha256(config.expected_supervisor_sha256):
        problems.append("supervisor SHA predeclaration is malformed")
    elif (not is_regular_unlinked(supervisor_script)
          or sha256_file(supervisor_script)
          != config.expected_supervisor_sha256):
        problems.append("supervisor SHA predeclaration drift")
    owned = [paths.receipt, paths.receipt_log, paths.receipt_exit,
             paths.preparation]
    owned.extend(paths.audit_namespace / name for name in DESCENDANT_NAMES)
    for path in owned:
        if lexists(path) or lexists(adjacent_partial(path)):
            problems.append(f"one-shot output collision {path}")
        if path.name.endswith(".json"):
            for suffix in (".log", ".exit.json"):
                sibling = path.with_suffix(suffix)
                if lexists(sibling) or lexists(adjacent_partial(sibling)):
                    problems.append(f"one-shot output collision {sibling}")
    try:
        rows = subprocess.run(
            ["ps", "-axo", "command="], check=True,
            capture_output=True, text=True).stdout.splitlines()
    except (OSError, subprocess.SubprocessError) as exc:
        problems.append(f"process inspection failed: {exc}")
    else:
        target = paths.audit_script.name
        if any(target in row and any(
                mode in f" {row} " for mode in (" receipt ", " label "))
               for row in rows):
            problems.append("champion audit receipt/label worker already exists")
    return sorted(set(problems))


def _copy_exclusive(source: Path, destination: Path, expected_sha256: str) -> None:
    if lexists(destination) or lexists(adjacent_partial(destination)):
        raise PreparationRefusal(f"refusing parent collision {destination}")
    if not is_regular_unlinked(source) or sha256_file(source) != expected_sha256:
        raise PreparationRefusal(f"source parent identity drift {source}")
    partial = adjacent_partial(destination)
    try:
        with source.open("rb") as reader, partial.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=1 << 20)
            writer.flush()
            os.fsync(writer.fileno())
    except FileExistsError as exc:
        raise PreparationRefusal(f"refusing parent partial {partial}") from exc
    if sha256_file(partial) != expected_sha256:
        raise PreparationRefusal(f"copied parent SHA drift {partial}")
    os.link(partial, destination)
    if sha256_file(destination) != expected_sha256:
        raise PreparationRefusal(f"published parent SHA drift {destination}")
    partial.unlink()


def _publish_json(path: Path, payload: Mapping[str, object]) -> str:
    partial = adjacent_partial(path)
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
           + "\n").encode()
    try:
        with partial.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise PreparationRefusal(f"refusing output partial {partial}") from exc
    os.link(partial, path)
    digest = sha256_file(path)
    if digest != hashlib.sha256(raw).hexdigest():
        raise PreparationRefusal(f"published JSON bytes drift {path}")
    partial.unlink()
    return digest


def _receipt_command(config: Config, paths: PreparationPaths,
                     parents: Mapping[str, object]) -> tuple[str, ...]:
    cheap = parents["cheap_inputs"]
    gold = parents["gold_inputs"]
    assert isinstance(cheap, list) and isinstance(gold, list)
    argv = [
        str(config.python), str(paths.audit_script), "receipt",
        "--run-id", RUN_ID,
        "--expected-audit-git", AUDIT_GIT,
        "--expected-audit-script-sha256", AUDIT_SCRIPT_SHA256,
        "--stage-b-state-set", str(NAMESPACE / STAGE_B_STATE_NAME),
        "--expected-stage-b-state-set-sha256", STAGE_B_STATE_SHA256,
        "--audit-state-set", str(NAMESPACE / AUDIT_STATE_NAME),
        "--expected-audit-state-set-sha256", AUDIT_STATE_SHA256,
        "--stage-b-gate", str(NAMESPACE / STAGE_B_GATE_NAME),
        "--expected-stage-b-gate-sha256", config.expected_gate_sha256,
    ]
    for relative, digest in cheap:
        argv.extend(("--cheap", str(relative),
                     "--expected-cheap-sha256", digest))
    for relative, digest in gold:
        argv.extend(("--n30", str(relative),
                     "--expected-n30-sha256", digest))
    argv.extend(("--out", str(NAMESPACE / AUDIT_RECEIPT_NAME)))
    return tuple(argv)


def _child_environment() -> dict[str, str]:
    env = dict(os.environ)
    for name in (
            "SHENGJI_WEIGHTED_SPLITS", "SHENGJI_UNIFORM_DEAL",
            "SHENGJI_PHYSICAL_FILLS", "SHENGJI_ALLOW_BALLOT_MISMATCH"):
        env.pop(name, None)
    env["SHENGJI_FAST"] = "1"
    env["SHENGJI_REQUIRE_VOIDS"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _run_receipt(config: Config, paths: PreparationPaths,
                 parents: Mapping[str, object]) -> tuple[int, tuple[str, ...]]:
    argv = _receipt_command(config, paths, parents)
    log_partial = adjacent_partial(paths.receipt_log)
    try:
        log_handle = log_partial.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise PreparationRefusal(f"receipt log collision {log_partial}") from exc
    process = None
    try:
        process = subprocess.Popen(
            argv, cwd=config.audit_root, env=_child_environment(),
            stdout=log_handle, stderr=subprocess.STDOUT, text=True)
        try:
            code = process.wait()
        except BaseException:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise
    finally:
        log_handle.flush()
        os.fsync(log_handle.fileno())
        log_handle.close()
    os.link(log_partial, paths.receipt_log)
    log_partial.unlink()
    _publish_json(paths.receipt_exit, {
        "schema": EXIT_SCHEMA,
        "complete": True,
        "pid": None if process is None else process.pid,
        "returncode": None if process is None else process.returncode,
        "argv_sha256": hashlib.sha256(
            "\0".join(argv).encode()).hexdigest(),
    })
    assert process is not None and process.returncode is not None
    return process.returncode, argv


def prepare(config: Config) -> tuple[str, str]:
    paths = paths_for(config)
    problems = preflight_problems(config, paths)
    if problems:
        raise PreparationRefusal("preflight: " + "; ".join(problems))
    parents = parent_population(config, paths)
    ordered = parents["ordered"]
    assert isinstance(ordered, list)
    collisions = [
        config.audit_root / relative
        for relative, _digest in ordered
        if (lexists(config.audit_root / relative)
            or lexists(adjacent_partial(config.audit_root / relative)))
    ]
    if collisions:
        raise PreparationRefusal(
            f"parent destination collisions before copy: {collisions}")
    copied = []
    for relative, digest in ordered:
        source = config.producer_root / relative
        destination = config.audit_root / relative
        _copy_exclusive(source, destination, digest)
        copied.append({"path": str(relative), "sha256": digest})
    code, _argv = _run_receipt(config, paths, parents)
    if code != 0:
        raise PreparationRefusal(f"audit receipt creator exited {code}")
    receipt = _load_json(paths.receipt)
    receipt_sha256 = sha256_file(paths.receipt)
    if (receipt.get("schema") != "teacher-v1-champion-audit-receipt-v1"
            or receipt.get("complete") is not True
            or receipt.get("run_id") != RUN_ID
            or receipt.get("execution_predeclaration") != {
                "git": AUDIT_GIT,
                "audit_script_sha256": AUDIT_SCRIPT_SHA256,
            }):
        raise PreparationRefusal("audit receipt publication identity drift")
    receipt_exit_sha256 = sha256_file(paths.receipt_exit)
    receipt_log_sha256 = sha256_file(paths.receipt_log)
    summary = {
        "schema": SCHEMA,
        "complete": True,
        "producer_git": PRODUCER_GIT,
        "audit_git": AUDIT_GIT,
        "audit_script_sha256": AUDIT_SCRIPT_SHA256,
        "python": EXPECTED_PYTHON_VERSION,
        "preparer_sha256": config.expected_preparer_sha256,
        "expected_supervisor_sha256": config.expected_supervisor_sha256,
        "stage_b_gate": parents["gate_ref"],
        "copied_parents": copied,
        "receipt": {"path": str(NAMESPACE / AUDIT_RECEIPT_NAME),
                    "sha256": receipt_sha256},
        "receipt_log": {"path": str(NAMESPACE / paths.receipt_log.name),
                        "sha256": receipt_log_sha256},
        "receipt_exit": {"path": str(NAMESPACE / paths.receipt_exit.name),
                         "sha256": receipt_exit_sha256,
                         "returncode": 0},
        "audit_labels_authorized": True,
        "retry_authorized": False,
        "production_promotion": False,
    }
    preparation_sha256 = _publish_json(paths.preparation, summary)
    return receipt_sha256, preparation_sha256


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--producer-root", required=True)
    ap.add_argument("--audit-root", required=True)
    ap.add_argument("--python", required=True)
    ap.add_argument("--expected-stage-b-gate-sha256", required=True)
    ap.add_argument("--expected-preparer-sha256", required=True)
    ap.add_argument("--expected-supervisor-sha256", required=True)
    return ap


def _absolute_unresolved(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (Path.cwd() / path).absolute()


def main() -> None:
    args = parser().parse_args()
    config = Config(
        producer_root=Path(args.producer_root).resolve(),
        audit_root=Path(args.audit_root).resolve(),
        python=_absolute_unresolved(args.python),
        expected_gate_sha256=args.expected_stage_b_gate_sha256,
        expected_preparer_sha256=args.expected_preparer_sha256,
        expected_supervisor_sha256=args.expected_supervisor_sha256,
    )

    def refuse_signal(signum, _frame) -> None:
        raise PreparationRefusal(f"received signal {signum}")

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, refuse_signal)
    try:
        receipt_sha256, preparation_sha256 = prepare(config)
    except (OSError, ValueError, subprocess.SubprocessError,
            PreparationRefusal) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(3)
    print(json.dumps({
        "schema": SCHEMA,
        "receipt_sha256": receipt_sha256,
        "preparation_sha256": preparation_sha256,
        "audit_labels_authorized": True,
        "production_promotion": False,
    }, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
