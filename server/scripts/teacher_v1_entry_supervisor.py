"""Fail-closed supervisor for the frozen teacher-v1 entry packet.

This owns exactly one transition:

    8 capture shards -> 8 selector diagnostics -> frozen 64-state Stage A set

It deliberately has no receipt, labelling, or gate phase.  A successful run
stops after publishing ``stage_a_states.json``.  Any failed child, artifact
collision, identity drift, incomplete population, or selection deficit closes
the attempt in place; this supervisor never resumes, appends, retries, or
substitutes a seed.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Callable, Sequence

SCRIPT_PATH = Path(__file__).resolve()
SCRIPTS_ROOT = SCRIPT_PATH.parent
SERVER_ROOT = SCRIPTS_ROOT.parent
LOGS_ROOT = SERVER_ROOT / "runs" / "logs"
STATE_SCRIPT = SCRIPTS_ROOT / "teacher_v1_states.py"

sys.path.insert(0, str(SERVER_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))

import teacher_v1_states as states  # noqa: E402
from shengji.teacher_v1 import (CAPTURE_DEALS_PER_SHARD,  # noqa: E402
                                CAPTURE_MAX_DEALS, CAPTURE_PACKET_ID,
                                CAPTURE_SEED_END, CAPTURE_SHARDS,
                                REPRESENTATIVE_CELLS, SEED_START,
                                STAGE_A_OTHER_STATES,
                                STAGE_A_REPRESENTATIVE_PER_CELL,
                                STAGE_A_STATES, STATE_SET_SCHEMA,
                                capture_packet, capture_shard_seeds,
                                is_sha256)


EXPECTED_PACKET = {
    "packet_id": "teacher-v1-entry-120m-v1",
    "seed0": 120_000_000,
    "seed_end_inclusive": 120_001_023,
    "max_deals": 1_024,
    "shard_count": 8,
    "sharding": "interleaved_seed_offset_mod_8",
    "deals_per_shard": 128,
}
EXPECTED_EXAM_SPLITS = (
    "rl_data/corpus_split.v1.json",
    "rl_data/corpus_split_late.v1.json",
    "rl_data/deep_lead_split.v1.json",
)
EXPECTED_EXAM_SHA256 = {
    "rl_data/corpus_split.v1.json":
        "bbc061f9c08f19f490d8b789d5c8f15542e28bdaa5504efb1adfe7ba40d9edc2",
    "rl_data/corpus_split_late.v1.json":
        "9b974ab16f3a76fb089efe8541690d9ecbfdcad9b174bb0623b7d456d0b2aa1c",
    "rl_data/deep_lead_split.v1.json":
        "9d72dcafffc1d8ac983be81f0f33275236f21f850aed019f9d081e0291812df6",
}
EXPECTED_V11_SHA256 = (
    "cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003"
)
RUNTIME_FIELDS = (
    "git", "tree_dirty", "promotable", "host", "python", "fast_engine",
    "require_voids", "fast_router_sha256", "fast_binary_sha256",
    "state_script_sha256",
)


class EntryRefusal(RuntimeError):
    """A condition that closes this entry-packet attempt."""


def _refuse_signal(signum, _frame) -> None:
    raise EntryRefusal(f"received signal {signum}; stopping supervised workers")


@dataclass(frozen=True)
class EntryPaths:
    root: Path
    captures: tuple[Path, ...]
    diagnostics: tuple[Path, ...]
    state_set: Path
    progress_partial: Path
    progress_final: Path


@dataclass(frozen=True)
class Job:
    name: str
    argv: tuple[str, ...]
    log_partial: Path
    log_final: Path


def entry_paths(root: Path) -> EntryPaths:
    return EntryPaths(
        root=root,
        captures=tuple(root / f"capture_shard{index:02d}.json"
                       for index in range(8)),
        diagnostics=tuple(root / f"diagnostic_shard{index:02d}.json"
                          for index in range(8)),
        state_set=root / "stage_a_states.json",
        progress_partial=root / "supervisor_progress.jsonl.partial",
        progress_final=root / "supervisor_progress.jsonl",
    )


def static_contract_problems() -> list[str]:
    """Compare imported constants to a literal, reviewable packet."""
    problems = []
    actual_scalars = {
        "packet_id": CAPTURE_PACKET_ID,
        "seed0": SEED_START,
        "seed_end_inclusive": CAPTURE_SEED_END,
        "max_deals": CAPTURE_MAX_DEALS,
        "shard_count": CAPTURE_SHARDS,
        "deals_per_shard": CAPTURE_DEALS_PER_SHARD,
    }
    for name, expected in EXPECTED_PACKET.items():
        if name == "sharding":
            continue
        if actual_scalars.get(name) != expected:
            problems.append(
                f"literal packet {name} drift: {actual_scalars.get(name)!r}"
            )
    if capture_packet() != EXPECTED_PACKET:
        problems.append("executable capture packet differs from literal packet")
    if STAGE_A_STATES != 64:
        problems.append(f"Stage-A size {STAGE_A_STATES}, required 64")
    if (STAGE_A_REPRESENTATIVE_PER_CELL != 4
            or STAGE_A_OTHER_STATES != 16
            or len(REPRESENTATIVE_CELLS) != 12):
        problems.append("Stage-A 48 representative + 16 challenge contract drift")
    if tuple(states.DEFAULT_EXAM_SPLITS) != EXPECTED_EXAM_SPLITS:
        problems.append("default exam-split population drift")
    if states.DEFAULT_EXAM_SPLIT_SHA256 != EXPECTED_EXAM_SHA256:
        problems.append("exam-split digest contract drift")
    if states.ACTOR != "mc-strong" or states.SELECTOR_WORLDS != 30:
        problems.append("capture/diagnostic policy contract drift")
    if states.V11_CHECKPOINT_SHA256 != EXPECTED_V11_SHA256:
        problems.append("v11 diagnostic checkpoint contract drift")

    shards = []
    if CAPTURE_SHARDS == 8:
        for index in range(8):
            expected = list(range(120_000_000 + index, 120_001_024, 8))
            try:
                actual = capture_shard_seeds(index)
            except Exception as exc:  # fail closed on a changed helper
                problems.append(f"capture shard {index} cannot be derived: {exc}")
                continue
            if actual != expected or len(actual) != 128:
                problems.append(f"capture shard {index} literal seed coverage drift")
            shards.extend(actual)
    if (len(shards) != 1_024 or len(set(shards)) != 1_024
            or sorted(shards) != list(range(120_000_000, 120_001_024))):
        problems.append("capture shards do not partition the exact 1,024 seeds")
    return problems


def _full_git_sha(value: str) -> bool:
    return (len(value) == 40
            and all(char in "0123456789abcdef" for char in value))


def runtime_problems(runtime: dict, expected_git: str) -> list[str]:
    problems = []
    if not _full_git_sha(expected_git):
        problems.append("expected git must be a full lowercase 40-character SHA")
    if runtime.get("git") != expected_git:
        problems.append(
            f"runtime git {runtime.get('git')!r}, expected {expected_git!r}"
        )
    if runtime.get("tree_dirty") or runtime.get("promotable") is not True:
        problems.append("runtime is dirty or non-promotable")
    if runtime.get("fast_engine") is not True:
        problems.append("compiled engine is not active")
    if runtime.get("require_voids") is not True:
        problems.append("strict void mode is not active")
    for key in (
        "fast_router_sha256", "fast_binary_sha256", "state_script_sha256"
    ):
        if not is_sha256(runtime.get(key)):
            problems.append(f"runtime {key} is not a SHA-256")
    return problems


def resolve_output_dir(value: str) -> Path:
    raw = Path(value)
    resolved = (raw if raw.is_absolute() else SERVER_ROOT / raw).resolve()
    logs_root = LOGS_ROOT.resolve()
    if resolved.parent != logs_root:
        raise EntryRefusal(
            f"output must be the direct packet directory under {logs_root}"
        )
    if resolved.name != EXPECTED_PACKET["packet_id"]:
        raise EntryRefusal(
            f"output directory must be named {EXPECTED_PACKET['packet_id']}"
        )
    return resolved


def prepare_output_dir(path: Path) -> None:
    """One directory is one attempt; even an empty prior directory refuses."""
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise EntryRefusal(
            f"refusing existing attempt directory {path}; no resume or replacement"
        ) from exc


def publish_exclusive(partial: Path, final: Path) -> None:
    """Publish without an overwrite-capable rename."""
    try:
        os.link(partial, final)
    except FileExistsError as exc:
        raise EntryRefusal(f"refusing to overwrite {final}") from exc
    os.unlink(partial)


class Progress:
    def __init__(self, paths: EntryPaths):
        self.paths = paths
        self._fh = open(paths.progress_partial, "x", encoding="utf-8")
        self._closed = False

    def event(self, phase: str, status: str, **fields) -> None:
        payload = {
            "time_ns": time.time_ns(), "phase": phase, "status": status,
            **fields,
        }
        self._fh.write(json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())
        suffix = " ".join(f"{key}={value}" for key, value in fields.items())
        print(f"PROGRESS {phase} {status}" + (f" {suffix}" if suffix else ""),
              flush=True)

    def close(self) -> None:
        if not self._closed:
            self._fh.close()
            self._closed = True

    def publish(self) -> None:
        self.close()
        publish_exclusive(self.paths.progress_partial, self.paths.progress_final)


def _log_paths(paths: EntryPaths, name: str) -> tuple[Path, Path]:
    return paths.root / f"{name}.log.partial", paths.root / f"{name}.log"


def capture_jobs(paths: EntryPaths) -> list[Job]:
    jobs = []
    for index, output in enumerate(paths.captures):
        name = f"capture_shard{index:02d}"
        partial, final = _log_paths(paths, name)
        jobs.append(Job(name, (
            sys.executable, str(STATE_SCRIPT), "capture",
            "--packet-id", EXPECTED_PACKET["packet_id"],
            "--seed0", str(EXPECTED_PACKET["seed0"]),
            "--max-deals", str(EXPECTED_PACKET["max_deals"]),
            "--shard-index", str(index),
            "--shard-count", str(EXPECTED_PACKET["shard_count"]),
            "--out", str(output),
        ), partial, final))
    return jobs


def diagnostic_jobs(paths: EntryPaths,
                    capture_sha256s: Sequence[str]) -> list[Job]:
    if len(capture_sha256s) != 8 or any(
        not is_sha256(value) for value in capture_sha256s
    ):
        raise EntryRefusal("diagnostics require eight literal capture SHA-256s")
    jobs = []
    for index, (source, output, digest) in enumerate(zip(
        paths.captures, paths.diagnostics, capture_sha256s, strict=True
    )):
        name = f"diagnostic_shard{index:02d}"
        partial, final = _log_paths(paths, name)
        jobs.append(Job(name, (
            sys.executable, str(STATE_SCRIPT), "diagnose",
            "--input", str(source),
            "--expected-input-sha256", digest,
            "--out", str(output),
        ), partial, final))
    return jobs


def freeze_job(paths: EntryPaths) -> Job:
    partial, final = _log_paths(paths, "freeze_stage_a")
    argv = [sys.executable, str(STATE_SCRIPT), "freeze", "--stage", "a"]
    for source in paths.diagnostics:
        argv += ["--input", str(source)]
    argv += ["--out", str(paths.state_set)]
    return Job("freeze_stage_a", tuple(argv), partial, final)


def _terminate(processes: Sequence[subprocess.Popen]) -> None:
    active = [process for process in processes if process.poll() is None]
    for process in active:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    for process in active:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


def run_jobs(
    phase: str,
    jobs: Sequence[Job],
    progress: Progress,
    *,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    poll_seconds: float = 1.0,
    heartbeat_seconds: float = 30.0,
) -> None:
    """Run one all-or-nothing phase and kill peers on its first refusal."""
    if not jobs:
        raise EntryRefusal(f"{phase} has no jobs")
    streams: dict[str, IO[str]] = {}
    processes: dict[str, subprocess.Popen] = {}
    job_by_name = {job.name: job for job in jobs}
    if len(job_by_name) != len(jobs):
        raise EntryRefusal(f"{phase} has duplicate job identities")
    try:
        # Reserve every log before launching any compute.
        for job in jobs:
            streams[job.name] = open(job.log_partial, "x", encoding="utf-8")
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        for job in jobs:
            processes[job.name] = popen(
                list(job.argv), cwd=SERVER_ROOT, env=environment,
                stdout=streams[job.name], stderr=subprocess.STDOUT,
            )
        progress.event(phase, "RUNNING", workers=len(processes))
        started = time.monotonic()
        last_heartbeat = started
        active = set(processes)
        while active:
            for name in list(active):
                process = processes[name]
                code = process.poll()
                if code is None:
                    continue
                stream = streams[name]
                stream.flush()
                os.fsync(stream.fileno())
                stream.close()
                del streams[name]
                active.remove(name)
                job = job_by_name[name]
                if code != 0:
                    progress.event(
                        phase, "REFUSED", worker=name, exit_code=code,
                        log=str(job.log_partial),
                    )
                    _terminate([processes[item] for item in active])
                    raise EntryRefusal(
                        f"{phase} worker {name} exited {code}; stopped peers"
                    )
                publish_exclusive(job.log_partial, job.log_final)
                progress.event(
                    phase, "WORKER_COMPLETE", worker=name,
                    complete=len(processes) - len(active), total=len(processes),
                )
            now = time.monotonic()
            if active and now - last_heartbeat >= heartbeat_seconds:
                progress.event(
                    phase, "HEARTBEAT", active=len(active),
                    complete=len(processes) - len(active), total=len(processes),
                    elapsed_seconds=round(now - started, 1),
                )
                last_heartbeat = now
            if active:
                time.sleep(poll_seconds)
        progress.event(phase, "COMPLETE", workers=len(processes))
    except BaseException:
        _terminate(list(processes.values()))
        raise
    finally:
        for stream in streams.values():
            stream.close()


def _artifact_runtime_problems(payload: dict, runtime: dict) -> list[str]:
    return [
        f"artifact/runtime {key} drift"
        for key in RUNTIME_FIELDS if payload.get(key) != runtime.get(key)
    ]


def _load_artifact(path: Path) -> tuple[dict, str]:
    partial = Path(str(path) + ".partial")
    if partial.exists():
        raise EntryRefusal(f"partial artifact remains at {partial}")
    if path.is_symlink() or not path.is_file():
        raise EntryRefusal(f"missing or non-regular artifact {path}")
    digest = states.sha256_file(str(path))
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise EntryRefusal(f"artifact {path} is not a JSON object")
    return payload, digest


def validate_capture_population(
    paths: EntryPaths, runtime: dict, actor: dict, exam_exclusion: dict,
) -> tuple[list[dict], list[str]]:
    manifests, hashes, problems = [], [], []
    for index, path in enumerate(paths.captures):
        payload, digest = _load_artifact(path)
        manifests.append(payload)
        hashes.append(digest)
        problems += [f"shard {index}: {problem}" for problem in
                     states.registered_capture_problems(payload)]
        if payload.get("shard_index") != index:
            problems.append(f"capture path {index} contains shard "
                            f"{payload.get('shard_index')}")
        problems += [f"shard {index}: {problem}" for problem in
                     _artifact_runtime_problems(payload, runtime)]
        if payload.get("actor") != actor:
            problems.append(f"capture shard {index} actor drift")
        if payload.get("exam_exclusion") != exam_exclusion:
            problems.append(f"capture shard {index} exam exclusion drift")
    if len(set(hashes)) != 8:
        problems.append("capture artifact hashes are not eight unique identities")
    if problems:
        raise EntryRefusal("capture population: " + "; ".join(sorted(set(problems))))
    return manifests, hashes


def validate_diagnostic_population(
    paths: EntryPaths,
    capture_manifests: Sequence[dict],
    capture_sha256s: Sequence[str],
    runtime: dict,
    actor: dict,
    exam_exclusion: dict,
) -> tuple[list[dict], list[str]]:
    if len(capture_manifests) != 8 or len(capture_sha256s) != 8:
        raise EntryRefusal("diagnostic validation requires all eight captures")
    manifests, hashes, problems = [], [], []
    for index, path in enumerate(paths.diagnostics):
        if states.sha256_file(str(paths.captures[index])) != capture_sha256s[index]:
            problems.append(f"capture shard {index} changed before diagnosis")
        payload, digest = _load_artifact(path)
        manifests.append(payload)
        hashes.append(digest)
        problems += [f"shard {index}: {problem}" for problem in
                     states.registered_diagnostic_problems(payload)]
        if payload.get("capture_shard_index") != index:
            problems.append(f"diagnostic path {index} contains shard "
                            f"{payload.get('capture_shard_index')}")
        if payload.get("capture_input_sha256") != capture_sha256s[index]:
            problems.append(f"diagnostic shard {index} capture hash drift")
        if payload.get("input") != str(paths.captures[index]):
            problems.append(f"diagnostic shard {index} capture path drift")
        problems += [f"shard {index}: {problem}" for problem in
                     _artifact_runtime_problems(payload, runtime)]
        if payload.get("actor") != actor:
            problems.append(f"diagnostic shard {index} actor drift")
        if payload.get("exam_exclusion") != exam_exclusion:
            problems.append(f"diagnostic shard {index} exam exclusion drift")
        if payload.get("v11_checkpoint_sha256") != states.V11_CHECKPOINT_SHA256:
            problems.append(f"diagnostic shard {index} v11 checkpoint drift")
    population_bad, _ = states.diagnostic_population_problems(manifests)
    problems += population_bad
    if len(set(hashes)) != 8:
        problems.append("diagnostic artifact hashes are not eight unique identities")
    if problems:
        raise EntryRefusal(
            "diagnostic population: " + "; ".join(sorted(set(problems)))
        )
    return manifests, hashes


def validate_stage_a_state_set(
    paths: EntryPaths,
    diagnostics: Sequence[dict],
    diagnostic_sha256s: Sequence[str],
    runtime: dict,
    actor: dict,
    exam_exclusion: dict,
) -> tuple[dict, str]:
    if len(diagnostics) != 8 or len(diagnostic_sha256s) != 8:
        raise EntryRefusal("Stage-A freeze requires all eight diagnostics")
    problems = []
    for index, path in enumerate(paths.diagnostics):
        if states.sha256_file(str(path)) != diagnostic_sha256s[index]:
            problems.append(f"diagnostic shard {index} changed during freeze")
    payload, digest = _load_artifact(paths.state_set)
    problems += states.state_set_packet_problems(payload)
    problems += states.stage_a_exclusion_problems(
        payload, diagnostics[0], set(diagnostic_sha256s)
    )
    if (payload.get("schema") != STATE_SET_SCHEMA
            or payload.get("stage") != "a"
            or payload.get("complete") is not True):
        problems.append("frozen output is not a complete Stage-A state set")
    selected = payload.get("states", [])
    if not isinstance(selected, list):
        problems.append("frozen output states are not a list")
        selected = []
    if (payload.get("requested") != 64 or payload.get("selected") != 64
            or len(selected) != 64):
        problems.append("frozen output is not exactly 64 states")
    if payload.get("actor") != actor:
        problems.append("frozen output actor drift")
    if payload.get("exam_exclusion") != exam_exclusion:
        problems.append("frozen output exam exclusion drift")
    problems += _artifact_runtime_problems(payload, runtime)
    if payload.get("excluded_stage_a") is not None:
        problems.append("Stage-A freeze unexpectedly carries a prior state set")
    if payload.get("stage_a_gate") is not None:
        problems.append("Stage-A freeze unexpectedly carries a Stage-A gate")

    inputs = payload.get("diagnostic_inputs", [])
    if len(inputs) == 8:
        for index, item in enumerate(inputs):
            if not isinstance(item, dict):
                problems.append(f"frozen diagnostic input {index} is not an object")
            elif (item.get("path") != str(paths.diagnostics[index])
                    or item.get("sha256") != diagnostic_sha256s[index]
                    or item.get("capture_shard_index") != index):
                problems.append(f"frozen diagnostic input {index} binding drift")

    valid_states = [state for state in selected if isinstance(state, dict)]
    if len(valid_states) != len(selected):
        problems.append("frozen Stage-A state is not an object")
    state_ids = [state.get("state_id") for state in valid_states]
    seeds = [state.get("seed") for state in valid_states]
    if (len(state_ids) != len(set(state_ids))
            or len(seeds) != len(set(seeds))):
        problems.append("frozen Stage-A states/deals are not unique")
    representative = Counter(
        (state.get("phase"), state.get("role"), state.get("decision"))
        for state in valid_states if state.get("kind") == "representative"
    )
    for cell in REPRESENTATIVE_CELLS:
        if representative[cell] != 4:
            problems.append(f"Stage-A representative cell {cell} != 4")
    for kind in ("boundary", "uncertainty"):
        if sum(state.get("kind") == kind for state in valid_states) != 8:
            problems.append(f"Stage-A {kind} count != 8")
    for state in valid_states:
        try:
            states.replay_state(state)
        except Exception as exc:
            problems.append(
                f"Stage-A state {state.get('state_id')} replay: "
                f"{type(exc).__name__}: {exc}"
            )
    if problems:
        raise EntryRefusal("Stage-A state set: " + "; ".join(sorted(set(problems))))
    return payload, digest


def expected_inventory(paths: EntryPaths, phase: str) -> set[str]:
    names = {paths.progress_partial.name}
    if phase in {"capture", "diagnostic", "freeze"}:
        names |= {path.name for path in paths.captures}
        names |= {f"capture_shard{index:02d}.log" for index in range(8)}
    if phase in {"diagnostic", "freeze"}:
        names |= {path.name for path in paths.diagnostics}
        names |= {f"diagnostic_shard{index:02d}.log" for index in range(8)}
    if phase == "freeze":
        names |= {paths.state_set.name, "freeze_stage_a.log"}
    return names


def require_inventory(paths: EntryPaths, phase: str) -> None:
    actual = {path.name for path in paths.root.iterdir()}
    expected = expected_inventory(paths, phase)
    if actual != expected:
        raise EntryRefusal(
            f"{phase} output inventory drift: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


def preflight(packet_id: str, expected_git: str) -> dict:
    problems = static_contract_problems()
    if packet_id != EXPECTED_PACKET["packet_id"]:
        problems.append(
            f"packet id {packet_id!r}, expected {EXPECTED_PACKET['packet_id']!r}"
        )
    if os.environ.get("SHENGJI_FAST") != "1":
        problems.append("set SHENGJI_FAST=1 exactly")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        problems.append("set SHENGJI_REQUIRE_VOIDS=1 exactly")
    if problems:
        raise EntryRefusal("static preflight: " + "; ".join(problems))

    runtime = states.runtime(False)
    problems = runtime_problems(runtime, expected_git)
    actor = states.actor_identity()
    if actor.get("policy") != "mc-strong" or not is_sha256(actor.get("identity")):
        problems.append("production mc-strong actor identity")
    exam_seeds, exclusion = states.load_exam_exclusion(
        list(EXPECTED_EXAM_SPLITS)
    )
    sources = exclusion.get("sources", [])
    source_identities = [
        (source.get("path"), source.get("sha256"))
        for source in sources if isinstance(source, dict)
    ]
    if (exclusion.get("verified") is not True or exclusion.get("overlap") != 0
            or source_identities != [
                (path, EXPECTED_EXAM_SHA256[path])
                for path in EXPECTED_EXAM_SPLITS
            ]
            or exam_seeds & set(range(120_000_000, 120_001_024))):
        problems.append("exam exclusion preflight")
    checkpoint = SERVER_ROOT / "snapshots_v11pair" / "ep07.npz"
    if (not checkpoint.is_file()
            or states.sha256_file(str(checkpoint)) != EXPECTED_V11_SHA256):
        problems.append("frozen v11 diagnostic checkpoint drift")
    if problems:
        raise EntryRefusal("runtime preflight: " + "; ".join(problems))
    return {
        "runtime": runtime, "actor": actor, "exam_exclusion": exclusion,
        "checkpoint_sha256": EXPECTED_V11_SHA256,
    }


def recheck(preflight_result: dict, expected_git: str) -> None:
    runtime = states.runtime(False)
    problems = runtime_problems(runtime, expected_git)
    if runtime != preflight_result["runtime"]:
        problems.append("runtime identity changed during supervision")
    if states.actor_identity() != preflight_result["actor"]:
        problems.append("actor identity changed during supervision")
    _, exclusion = states.load_exam_exclusion(list(EXPECTED_EXAM_SPLITS))
    if exclusion != preflight_result["exam_exclusion"]:
        problems.append("exam exclusion changed during supervision")
    checkpoint = SERVER_ROOT / "snapshots_v11pair" / "ep07.npz"
    if states.sha256_file(str(checkpoint)) != preflight_result["checkpoint_sha256"]:
        problems.append("v11 diagnostic checkpoint changed during supervision")
    if problems:
        raise EntryRefusal("identity recheck: " + "; ".join(problems))


def supervise(packet_id: str, expected_git: str, output_dir: Path) -> str:
    admitted = preflight(packet_id, expected_git)
    prepare_output_dir(output_dir)
    paths = entry_paths(output_dir)
    progress = Progress(paths)
    try:
        progress.event(
            "supervisor", "ADMITTED", packet_id=packet_id,
            git=expected_git, seed0=120_000_000, seed_end=120_001_023,
            shards=8, deals_per_shard=128, python=sys.executable,
            supervisor_sha256=states.sha256_file(str(SCRIPT_PATH)),
        )

        recheck(admitted, expected_git)
        run_jobs("capture", capture_jobs(paths), progress)
        recheck(admitted, expected_git)
        captures, capture_hashes = validate_capture_population(
            paths, admitted["runtime"], admitted["actor"],
            admitted["exam_exclusion"],
        )
        require_inventory(paths, "capture")
        progress.event("capture", "VALIDATED", artifacts=8, seeds=1_024)

        recheck(admitted, expected_git)
        run_jobs(
            "diagnostic", diagnostic_jobs(paths, capture_hashes), progress
        )
        recheck(admitted, expected_git)
        diagnostics, diagnostic_hashes = validate_diagnostic_population(
            paths, captures, capture_hashes, admitted["runtime"],
            admitted["actor"], admitted["exam_exclusion"],
        )
        require_inventory(paths, "diagnostic")
        progress.event("diagnostic", "VALIDATED", artifacts=8, seeds=1_024)

        recheck(admitted, expected_git)
        run_jobs("freeze", [freeze_job(paths)], progress)
        recheck(admitted, expected_git)
        _, state_set_sha256 = validate_stage_a_state_set(
            paths, diagnostics, diagnostic_hashes, admitted["runtime"],
            admitted["actor"], admitted["exam_exclusion"],
        )
        require_inventory(paths, "freeze")
        progress.event(
            "freeze", "FROZEN", states=64,
            state_set=str(paths.state_set), sha256=state_set_sha256,
            next_action="STOP_BEFORE_STAGE_A_RECEIPT_OR_LABELS",
        )
        progress.event(
            "supervisor", "COMPLETE", terminal="STAGE_A_STATES_FROZEN",
            labels_launched=False, stage_a_launched=False,
        )
        progress.publish()
        return state_set_sha256
    except BaseException as exc:
        try:
            progress.event(
                "supervisor", "REFUSED", error=f"{type(exc).__name__}: {exc}",
                labels_launched=False, stage_a_launched=False,
            )
        finally:
            progress.close()
        raise


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--packet-id", required=True)
    ap.add_argument(
        "--expected-git", required=True,
        help="full clean commit SHA staged in this worktree",
    )
    ap.add_argument(
        "--out-dir", required=True,
        help=("must resolve to runs/logs/teacher-v1-entry-120m-v1; the "
              "directory must not already exist"),
    )
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    os.chdir(SERVER_ROOT)
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _refuse_signal)
    try:
        output_dir = resolve_output_dir(args.out_dir)
        digest = supervise(args.packet_id, args.expected_git, output_dir)
    except Exception as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 3
    print(
        f"FROZEN Stage-A state set SHA-256 {digest}; STOPPED before receipts, "
        "labels, or Stage A",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
