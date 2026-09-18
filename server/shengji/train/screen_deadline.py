"""Screen-only, process-supervised play deadlines. No live policy registration.

One spawned process per cluster shares evaluator caches across its bot instances.
Only completed RPCs commit bot/RNG state. Cancellation restores the previous
checkpoint, including RNG, rather than accepting half-computed search evidence.
"""
from __future__ import annotations

from contextlib import contextmanager
import math
import multiprocessing as mp
import os
import queue
import threading
import time
import traceback

from ..ai.smart import SmartBot

RECIPE = {"seconds": 300.0, "version": "spawn-total-play-v1",
          "fallback": "SmartBot-v1", "rng_recovery": "rollback-uncommitted-play"}


def validate_deadline(value):
    if (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
        raise ValueError("decision deadline must be finite and positive")
    return float(value)


def _snapshot(wrapped):
    # Evaluators are immutable runtime assets, reconstructed through the factory
    # and shared per process; they must never cross the per-move IPC channel.
    state = {k: v for k, v in vars(wrapped.bot).items() if k != "evaluator"}
    timing = {k: v for k, v in vars(wrapped).items() if k not in ("bot", "decisions")}
    defaults = {}
    for cls in reversed(type(wrapped.bot).__mro__):
        defaults.update({k: v for k, v in vars(cls).items()
                         if not k.startswith("__") and type(v) in (int, float, bool, str, tuple)})
    return {"state": state, "timing": timing, "defaults": defaults}


@contextmanager
def _phases(bot, send):
    """Instrument only the isolated instance; restore methods before checkpointing."""
    originals = {}
    phase = None
    largest_legal_count = None

    def mark(name, legal_count=None):
        nonlocal phase, largest_legal_count
        # Two-stage ranking first visits the full legal set, then a smaller
        # refinement pool. Retain the full population for tail/timeout
        # attribution rather than relabeling a huge root as a small decision.
        if legal_count is not None:
            largest_legal_count = max(legal_count, largest_legal_count or 0)
            legal_count = largest_legal_count
        if phase != name or legal_count is not None:
            phase = name
            send(name, legal_count)

    def install(name, before, after=None):
        method = getattr(bot, name, None)
        if method is None:
            return
        originals[name] = (name in vars(bot), vars(bot).get(name))
        def call(*args, **kwargs):
            before(args)
            result = method(*args, **kwargs)
            if after:
                after(result)
            return result
        setattr(bot, name, call)

    install("_candidates", lambda _: mark("enumeration"), lambda _: mark("selection"))
    install("_sample_hands", lambda _: mark("sampling") if phase == "enumeration" else None)
    install("_prior_scores", lambda args: mark("prior", len(args[2])))
    install("_means", lambda args: mark("ranking", len(args[2])))
    install("_report_fold_gap", lambda _: mark("report"))
    install("_continuation_matrix", lambda _: mark("value-continuation"))
    try:
        mark("enumeration")
        yield
    finally:
        for name, (present, value) in originals.items():
            if present:
                setattr(bot, name, value)
            else:
                delattr(bot, name)


def _worker(conn, factory, specs, checkpoints, parent_pid):
    # Linux cloud: kill a blocked native search even if its supervisor crashes.
    # Normal close/finally and multiprocessing daemon cleanup also cover macOS.
    if os.name == "posix" and __import__("sys").platform == "linux":
        import ctypes
        import signal
        if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise OSError("could not install deadline-worker parent-death signal")
        if os.getppid() != parent_pid:
            return
    bots = {}
    try:
        for index, spec in enumerate(specs):
            wrapped = factory(*spec)
            if index in checkpoints:
                checkpoint = checkpoints[index]
                wrapped.bot.__dict__.update(checkpoint["state"])
                wrapped.__dict__.update(checkpoint["timing"])
            bots[index] = wrapped
        while True:
            request, index, method, args, kwargs, spec = conn.recv()
            try:
                if index not in bots:
                    bots[index] = factory(*spec)
                wrapped = bots[index]
                wrapped.decisions.clear()
                if method == "register":
                    result = None
                elif method == "decide_play":
                    def progress(phase, count):
                        conn.send((request, "phase", (phase, count)))
                    with _phases(wrapped.bot, progress):
                        result = wrapped.decide_play(*args, **kwargs)
                else:
                    result = getattr(wrapped, method)(*args, **kwargs)
                conn.send((request, "result", (result, _snapshot(wrapped), wrapped.decisions)))
            except Exception:
                conn.send((request, "error", traceback.format_exc()))
    except (EOFError, BrokenPipeError):
        pass
    finally:
        conn.close()


class DecisionExpired(Exception):
    def __init__(self, phase, legal_count):
        self.phase, self.legal_count = phase, legal_count


class DeadlineSession:
    def __init__(self, factory, seconds=300):
        self.factory, self.seconds = factory, validate_deadline(seconds)
        self.specs, self.checkpoints = [], {}
        self.process = self.conn = None
        self.sequence = 0

    def _start(self):
        context = mp.get_context("spawn")
        parent, child = context.Pipe()
        self.process = context.Process(target=_worker,
            args=(child, self.factory, self.specs, self.checkpoints, os.getpid()), daemon=True)
        self.conn = parent
        self.process.start()
        child.close()

    def close(self):
        if self.process is not None:
            if self.process.is_alive():
                self.process.kill()
            self.process.join(timeout=1)
            if self.process.is_alive():
                raise RuntimeError("deadline worker could not be reaped")
            self.process.close()
            self.process = None
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def register(self, *spec):
        index = len(self.specs)
        self.specs.append(spec)
        self.call(index, "register", (), {}, deadline=time.monotonic() + 120)
        return DeadlinePolicy(self, index)

    def call(self, index, method, args, kwargs, *, deadline=None):
        self.sequence += 1
        request = self.sequence
        if self.process is None:
            self._start()
        conn = self.conn
        messages = queue.Queue()

        # Neither serializing/sending a Round nor receiving a large result may
        # block the watchdog. A reader thread handles the complete framed IPC.
        def exchange():
            try:
                conn.send((request, index, method, args, kwargs, self.specs[index]))
                while True:
                    message = conn.recv()
                    messages.put(message)
                    if message[1] != "phase":
                        return
            except Exception as exc:
                messages.put((request, "transport-error", repr(exc)))
        reader = threading.Thread(target=exchange, daemon=True)
        reader.start()
        phase, legal_count = "startup-or-transfer", None
        try:
            while True:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise DecisionExpired(phase, legal_count)
                try:
                    seq, kind, payload = messages.get(timeout=remaining)
                except queue.Empty:
                    raise DecisionExpired(phase, legal_count) from None
                if seq != request:
                    raise RuntimeError("deadline RPC request identity drift")
                # A complete reply arriving after expiry cannot rescue this move.
                if deadline is not None and time.monotonic() >= deadline:
                    raise DecisionExpired(phase, legal_count)
                if kind == "phase":
                    phase, count = payload
                    if count is not None:
                        legal_count = count
                    continue
                if kind != "result":
                    raise RuntimeError(f"deadline worker {kind}: {payload}")
                result, checkpoint, traces = payload
                self.checkpoints[index] = checkpoint
                return result, traces, phase, legal_count
        except BaseException:
            self.close()
            raise
        finally:
            reader.join(timeout=1)
            if reader.is_alive():
                raise RuntimeError("deadline transport thread did not stop")


class DeadlinePolicy:
    def __init__(self, session, index):
        self.session, self.index = session, index
        self.decisions = []
        self.decision_wall_seconds = 0.0
        self.timeout_count = 0

    def __getattr__(self, name):
        checkpoint = self.session.checkpoints[self.index]
        for section in ("timing", "state", "defaults"):
            if name in checkpoint[section]:
                return checkpoint[section][name]
        raise AttributeError(name)

    def decide_declare(self, rnd, seat, final=False):
        return self.session.call(self.index, "decide_declare", (rnd, seat), {"final": final})[0]

    def decide_bury(self, rnd, seat):
        return self.session.call(self.index, "decide_bury", (rnd, seat), {})[0]

    def decide_play(self, rnd, seat):
        started = time.monotonic()
        deadline = started + self.session.seconds
        # SmartBot's constructive, validated heuristic uses no model or worlds
        # and does not consume the searched bot's RNG or mutate its state.
        fallback = SmartBot().decide_play(rnd, seat)
        expired = False
        try:
            result, traces, phase, legal_count = self.session.call(
                self.index, "decide_play", (rnd, seat), {}, deadline=deadline)
            trace = dict(traces[-1]) if traces else {"seat": seat, "trick": len(rnd.history), "forced": True}
        except DecisionExpired as exc:
            result, phase, legal_count, expired = fallback, exc.phase, exc.legal_count, True
            self.timeout_count += 1
            state = self.session.checkpoints[self.index]["state"]
            for name in ("last_decision_record", "last_eval", "last_shortlist",
                         "last_double_shortlist", "last_alloc", "last_override_stats",
                         "last_successor_reuse"):
                if name in state:
                    state[name] = None
            if "last_n_worlds" in state:
                state["last_n_worlds"] = 0
            trace = {"seat": seat, "trick": len(rnd.history), "played": list(fallback),
                     "reason": "decision_deadline", "search_complete": False,
                     "report": None, "selection_N": None, "report_worlds": None}
        elapsed = time.monotonic() - started
        self.decision_wall_seconds += elapsed
        trace["deadline"] = {"seconds": self.session.seconds, "timed_out": expired,
            "elapsed_seconds": elapsed, "overshoot_seconds": max(0.0, elapsed - self.session.seconds),
            "phase": phase, "legal_count": legal_count,
            "fallback": list(fallback) if expired else None,
            "work_accounting_complete": not expired}
        self.decisions.append(trace)
        return result


def latency_summary(shards):
    out = {}
    for side in ("arm", "baseline"):
        rows = [decision["deadline"] for shard in shards for trace in shard["decision_traces"]
                if trace["side"] == side for decision in trace["decisions"]]
        values = sorted(row["elapsed_seconds"] for row in rows)
        n = len(values)
        timeouts = sum(row["timed_out"] for row in rows)
        def percentile(q):
            return values[max(0, math.ceil(q * n) - 1)] if n else None
        out[side] = {"decisions": n, "timeouts": timeouts,
            "timeout_fraction": timeouts / n if n else None,
            "above_seconds": {str(t): {"count": sum(v > t for v in values),
                "fraction": sum(v > t for v in values) / n if n else None}
                for t in (10, 30, 60, 300)},
            "p50": percentile(.5), "p95": percentile(.95), "p99": percentile(.99),
            "max": values[-1] if n else None, "work_accounting_complete": timeouts == 0}
    return out
