"""A score-free, single-process cost journal for the exact lead stage.

The probe is deliberately installed at the two public seams used by the
qualifier.  It observes the objects passed by the serving path, but never
copies, samples, or calls back into the engine.  The journal is diagnostic
only: an exception from either seam has exactly the same identity and control
flow with or without the probe.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
import hashlib
import os
import platform
import json
import math
import threading
import time
from typing import Any

from shengji.ai import endgame
from shengji.train import pv_exact_endgame
from shengji.train import pv_search_policy as policy


_STAGE_LOCK = threading.Lock()
_INSTALLED_LOCK = threading.Lock()
_ACTIVE = threading.local()
_UNKNOWN = "UNKNOWN"


def _clock(value, default):
    return default if value is None else value


def _scalar_stats(stats: Any) -> dict[str, Any]:
    """Keep evaluator statistics scalar and bounded.

    Only the three known work counters are allowed; future scalar scores or
    string payloads must not silently enter this journal.
    """
    if not isinstance(stats, dict):
        return {}
    allowed = ("worlds_completed", "nodes", "cache_hits")
    return {key: stats[key] for key in allowed
            if key in stats and isinstance(stats[key], (int, float))
            and not isinstance(stats[key], bool)
            and (not isinstance(stats[key], float) or math.isfinite(stats[key]))}


def _json_sha256(value: Any) -> str:
    """Hash the closed JSON representation of a probe input.

    The serving path supplies lists of card strings, so JSON is deliberately
    the boundary here: no engine objects are copied or traversed beyond what
    the serializer requires.  Sorting keys and removing insignificant
    whitespace makes the fingerprint stable across hosts and runs.
    """
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _safe_json_sha256(value: Any) -> str | None:
    """Return an input fingerprint when the serving snapshot is JSON-shaped."""
    try:
        return _json_sha256(value)
    except (TypeError, ValueError, OverflowError):
        # Synthetic callers may pass opaque sentinels.  The probe must remain
        # observation-only for those calls; production worlds and actions are
        # JSON-shaped and therefore always receive a digest.
        return None


def _session_counter(sessions, name: str) -> int:
    total = 0
    for session in sessions:
        value = getattr(session, name, 0)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            total += value
    return total


def _thread_limits() -> dict[str, int | None]:
    limits = {}
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        raw = os.environ.get(name)
        if raw is None:
            continue
        try:
            value = int(raw)
        except ValueError:
            continue
        if 1 <= value <= 1024:
            limits[name] = value
    return limits


def _metadata() -> dict[str, Any]:
    # ``endgame.validate_follow`` is the alias actually consumed by the exact
    # engine (pure Python or the compiled implementation), not a guessed source
    # module.  Do not include an environment dump in the journal.
    return {
        "engine_validate_follow_module": getattr(
            endgame.validate_follow, "__module__", None),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "thread_limits": _thread_limits(),
    }


def _eligible(rnd, budget, baseline_elapsed) -> bool:
    try:
        leading = policy.leading(rnd)
        hand_ok = max(map(len, rnd.hands)) <= policy.EXACT_LEAD_LIMITS["max_hand_cards"]
    except (AttributeError, TypeError, ValueError):
        return False
    if not leading or not hand_ok:
        return False
    return budget is None or baseline_elapsed < policy.EXACT_LEAD_LIMITS["start_fraction"] * budget


def _write(sink, row: dict[str, Any]) -> None:
    sink.write(json.dumps(row, separators=(",", ":")) + "\n")
    sink.flush()


@contextmanager
def exact_lead_cost_probe(sink, *, perf_clock=None, thread_clock=None):
    """Temporarily journal exact-lead stage costs to writable *sink*.

    The patch is process-local and is removed on every exit.  A non-blocking
    stage lock makes accidental concurrent or nested exact stages fail closed,
    rather than producing a row with mixed ownership.
    """
    if not hasattr(sink, "write") or not hasattr(sink, "flush"):
        raise TypeError("cost sink must provide write() and flush()")
    clock = _clock(perf_clock, policy.time.perf_counter)
    cpu_clock = _clock(thread_clock, getattr(time, "thread_time", time.process_time))
    if not callable(clock) or not callable(cpu_clock):
        raise TypeError("probe clocks must be callable")

    original_stage = policy.PVSearchBot._exact_lead_decision
    original_evaluator = pv_exact_endgame.exact_first_trick_means
    original_session = pv_exact_endgame.ExactWorldSession
    metadata = _metadata()
    limits = policy.EXACT_LEAD_LIMITS

    with _INSTALLED_LOCK:
        if getattr(exact_lead_cost_probe, "_installed", False):
            raise RuntimeError("exact-lead cost probe is already installed")
        exact_lead_cost_probe._installed = True

    def evaluator_wrapper(*args, **kwargs):
        active = getattr(_ACTIVE, "row", None)
        if active is None:
            # The patch is intentionally narrow.  Calls outside a stage retain
            # their exact original behavior and are not journaled.
            return original_evaluator(*args, **kwargs)
        if active.get("evaluator_calls", 0) >= 1:
            raise RuntimeError("exact-lead evaluator called more than once")
        active["evaluator_calls"] += 1
        started_wall = clock()
        started_cpu = cpu_clock()
        error = None
        try:
            result = original_evaluator(*args, **kwargs)
            active["evaluator_normal"] = True
            try:
                active["evaluator_stats"] = _scalar_stats(result[1])
            except (IndexError, KeyError, TypeError):
                active["evaluator_stats"] = {}
            return result
        except BaseException as exc:
            error = exc
            active["evaluator_error"] = type(exc).__name__
            active["partial_worlds"] = _UNKNOWN
            raise
        finally:
            live = active.pop("_live", None)
            done = active.pop("_done", [0, 0, 0])
            tail = () if live is None else (live,)
            active["sessions_started"] = done[0]
            active["partial_nodes"] = done[1] + _session_counter(tail, "nodes")
            active["partial_cache_hits"] = done[2] + _session_counter(tail, "cache_hits")
            # Release the last cache before reading the evaluator clocks.
            del live, tail
            active["evaluator_seconds"] = max(0.0, clock() - started_wall)
            active["evaluator_cpu_seconds"] = max(0.0, cpu_clock() - started_cpu)
            if error is None:
                active.setdefault("partial_worlds", None)

    @wraps(original_session)
    def session_factory(*args, **kwargs):
        session = original_session(*args, **kwargs)
        active = getattr(_ACTIVE, "row", None)
        if active is not None:
            # Fold completed work without extending every world's cache life.
            done = active.setdefault("_done", [0, 0, 0])
            previous = active.get("_live")
            if previous is not None:
                done[1] += _session_counter((previous,), "nodes")
                done[2] += _session_counter((previous,), "cache_hits")
            done[0] += 1
            active["_live"] = session
        return session

    @wraps(original_stage)
    def stage_wrapper(self, rnd, seat, admitted, worlds, started, check_budget, priors, base):
        if not _STAGE_LOCK.acquire(blocking=False):
            raise RuntimeError("concurrent or nested exact-lead stage")
        row: dict[str, Any] = {}
        stage_started_wall = clock()
        stage_started_cpu = cpu_clock()
        normal = False
        stage_error = None
        previous = getattr(_ACTIVE, "row", None)
        try:
            baseline_elapsed = max(0.0, stage_started_wall - started)
            budget = getattr(self, "serving_budget_seconds", None)
            remaining = limits["max_seconds"] if budget is None else max(
                0.0, min(limits["max_seconds"],
                         limits["soft_fraction"] * budget - baseline_elapsed))
            row.update(metadata,
                       schema="exact-lead-cost-v1",
                       world_count=len(worlds), admitted_count=len(admitted),
                       serving_budget_seconds=budget,
                       exact_lead_limits={key: limits[key] for key in (
                           "max_hand_cards", "max_nodes", "max_seconds",
                           "start_fraction", "soft_fraction")},
                       baseline_elapsed_basis="perf_counter(stage_entry - decision_started)",
                       baseline_elapsed=baseline_elapsed,
                       remaining_soft_seconds=remaining,
                       remaining_soft_basis="stage-entry estimate, not the internal deadline",
                       eligible_start=_eligible(rnd, budget, baseline_elapsed),
                       evaluator_calls=0, sessions_started=0,
                       partial_nodes=0, partial_cache_hits=0, partial_worlds=None,
                       partial_worlds_basis=None,
                       worlds_sha256=None, admitted_sha256=None)
            _ACTIVE.row = row
            result = original_stage(self, rnd, seat, admitted, worlds, started,
                                    check_budget, priors, base)
            normal = True
            return result
        except BaseException as exc:
            stage_error = exc
            raise
        finally:
            elapsed = max(0.0, clock() - stage_started_wall)
            cpu_elapsed = max(0.0, cpu_clock() - stage_started_cpu)
            row["total_stage_seconds"] = elapsed
            row["cpu_seconds"] = cpu_elapsed
            evaluator_seconds = row.get("evaluator_seconds", 0.0)
            row["evaluator_seconds"] = evaluator_seconds
            row["non_evaluator_seconds"] = max(0.0, elapsed - evaluator_seconds)
            if stage_error is not None:
                row["stage_error"] = type(stage_error).__name__
                row["error"] = type(stage_error).__name__
                row["partial_worlds"] = _UNKNOWN
            if normal:
                state = getattr(self, "_exact_lead", {})
                if isinstance(state, dict):
                    for key in ("exact_lead_status", "exact_lead_abandon_reason",
                                "exact_lead_abandon_error", "exact_lead_worlds_completed"):
                        if key in state and isinstance(state[key], (bool, int, float, str)):
                            row[key.removeprefix("exact_lead_")] = state[key]
            # A soft expiry is raised from inside the active world session.
            # Only that typed abandonment supports this completed-world
            # count; malformed inputs and unrelated errors stay UNKNOWN.
            if (stage_error is None and row.get("status") == "abandoned"
                    and row.get("evaluator_error") == "_AdaptiveWorldsExpired"
                    and row.get("sessions_started", 0) > 0):
                row["partial_worlds"] = row["sessions_started"] - 1
                row["partial_worlds_basis"] = "sessions_started_minus_1_after_adaptive_expiry"
            row.setdefault("evaluator_stats", {})
            row.setdefault("evaluator_cpu_seconds", 0.0)
            row.setdefault("partial_worlds", None if normal else _UNKNOWN)
            if "error" not in row:
                row["error"] = row.get("evaluator_error")
            if row.get("evaluator_error") is None:
                row.pop("evaluator_error", None)
            sink_error = None
            try:
                # Hash immutable serving snapshots after elapsed timing has
                # been captured.  Serialization therefore cannot affect stage
                # guards or the reported evaluator/stage clocks.
                row["worlds_sha256"] = _safe_json_sha256(worlds)
                row["admitted_sha256"] = _safe_json_sha256(admitted)
                _write(sink, row)
            except BaseException as exc:
                sink_error = exc
            finally:
                if previous is None:
                    try:
                        del _ACTIVE.row
                    except AttributeError:
                        pass
                else:
                    _ACTIVE.row = previous
                _STAGE_LOCK.release()
            # A sink failure is a probe failure only when the wrapped stage
            # itself completed normally.  Preserve the original cancellation,
            # evaluator error, or stage error byte-for-byte otherwise.
            if sink_error is not None and stage_error is None:
                raise sink_error

    policy.PVSearchBot._exact_lead_decision = stage_wrapper
    pv_exact_endgame.exact_first_trick_means = evaluator_wrapper
    pv_exact_endgame.ExactWorldSession = session_factory
    try:
        yield
    finally:
        policy.PVSearchBot._exact_lead_decision = original_stage
        pv_exact_endgame.exact_first_trick_means = original_evaluator
        pv_exact_endgame.ExactWorldSession = original_session
        with _INSTALLED_LOCK:
            exact_lead_cost_probe._installed = False



