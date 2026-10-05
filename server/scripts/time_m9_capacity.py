"""Off-population M9 timing, never panel admission or scientific collection.

Run only in a fresh isolated Perf process under an external hard timeout and
the agreed free-host guard. This script creates no queue claim or RELEASE.
Its fixed synthetic fixture cannot be replaced with the scientific population.
The qualified f7838cfb source remains untouched; copy this script outside it.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
from pathlib import Path
import sys
import time


STAGE = Path("/root/m9-recovery-f7838cfb-20261005.pt0Gyc")
MANIFEST_SHA = "146a97b34555937b2b9174df094fc2e7b30a24279bb849ce08af6aa6625200dd"
ADAPTER_SHA = "a2d2f776398781dd1b417d94a0b898c6af91a22ddc0972f4092a5e66c98fdb24"
FIXTURE_SHA = "fc375d84408f58e15521e7fb21696804aeae4900af0d461dc195334f58ca2c1b"
MODEL_SHA = "491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670"
SEED = 17


def require_runtime(runtime, phase):
    """Expose the authenticated adapter's diagnostic without relaxing its verdict."""
    if not runtime.check():
        detail = getattr(runtime, "last_failure", None)
        raise ValueError(f"runtime check {phase} failed; measurement invalid; "
                         f"diagnostic={detail!r}")


def pinned_bytes(path, expected):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("absolute nonsymlink input required")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"input digest mismatch: {path}")
    return raw


class Timing:
    def __init__(self, seconds, clock=time.monotonic):
        self.clock = clock
        self.start = self.last = clock()
        self.seconds = seconds
        self.max_gap = 0.0
        self.events = []

    def check(self):
        now = self.clock()
        self.max_gap = max(self.max_gap, now - self.last)
        self.last = now
        if now - self.start >= self.seconds:
            raise TimeoutError("capacity soft deadline reached; preserve output, no retry")

    def call(self, label, fn, *args, **kwargs):
        self.check()
        started = self.clock()
        print(f"CAPACITY {label} start", flush=True)
        try:
            return fn(*args, **kwargs)
        finally:
            elapsed = self.clock() - started
            self.events.append({"stage": label, "seconds": elapsed})
            print(f"CAPACITY {label} end seconds={elapsed:.6f}", flush=True)


@contextmanager
def timed_call(module, name, timing, label):
    """Time a composition boundary; restore even if the real call fails.

    No sampler, scorer, leaf, bot recipe, RNG or callback is replaced. These
    ephemeral wrappers exist only in this dedicated timing interpreter.
    """
    original = getattr(module, name)
    def wrapped(*args, **kwargs):
        return timing.call(label, original, *args, **kwargs)
    setattr(module, name, wrapped)
    try:
        yield
    finally:
        setattr(module, name, original)


def measure(collector, factory, fixture, ballots, *, mode, output, timing):
    """Run one real composition; save synthetic output and timing on failure.

    Caller supplies authenticated imports/factory and checks runtime afterwards.
    No retry, resumable scientific job or strategic readout is implemented here.
    """
    output.mkdir()  # exclusive; a failed attempt is retained, never overwritten
    status = "failed"
    failure = None
    try:
        result = timing.call(
            "panel_total_including_factories", collector,
            lambda: timing.call("bot_construction", factory), fixture,
            ballots[0], ballots[1], mode=mode, seed=SEED, fill_seed=0,
            expected_legal_count=1771, check_budget=timing.check)
        timing.check()
        def publish():
            from shengji.eval.m9_panel_persistence import _json_bytes
            from shengji.luna.atomic_io import publish_exclusive_bytes
            publish_exclusive_bytes(output / "synthetic-panel.json",
                                    _json_bytes(result), mode=0o400)
        timing.call("synthetic_publication", publish)
        timing.check()
        status = "complete"
    except BaseException as exc:
        failure = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        now = timing.clock()
        timing.max_gap = max(timing.max_gap, now - timing.last)
        report = {
            "purpose": "off-population capacity only; not a scientific panel",
            "mode": mode, "status": status, "failure": failure,
            "seconds_since_start": now - timing.start,
            "soft_deadline_seconds": timing.seconds,
            "max_observed_budget_check_gap_seconds": timing.max_gap,
            "events": timing.events,
            "stages_overlap": True,
            "runtime_postcheck": "required separately in stdout; not implied by complete",
        }
        with (output / "timing.json").open("x") as handle:
            json.dump(report, handle, indent=2, allow_nan=False)
            handle.write("\n")


def qualify(action, source, original, path, digest, capture, admit):
    """Same-entrypoint capture/verification, with no model or fixture work."""
    if action == "capture-runtime":
        if digest is not None:
            raise ValueError("capture has no supplied runtime digest")
        manifest = capture(source, profile="panel")
        for key in ("source_root", "source_files", "environment"):
            if manifest[key] != original[key]:
                raise ValueError("qualified stage changed: " + key)
        raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
        with path.open("xb") as handle:
            handle.write(raw)
        print("TIMING RUNTIME CAPTURED sha256=" + hashlib.sha256(raw).hexdigest(), flush=True)
        return None
    if action not in ("verify-runtime", "measure") or digest is None:
        raise ValueError("explicit action and verified timing-runtime digest required")
    manifest = json.loads(pinned_bytes(path, digest))
    runtime = admit(manifest, profile="panel")
    require_runtime(runtime, "during verification")
    return runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("capture-runtime", "verify-runtime", "measure"), required=True)
    parser.add_argument("--runtime-sha256")
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("fresh-root", "history-primed"), required=True)
    args = parser.parse_args()
    if not sys.flags.isolated or not sys.dont_write_bytecode or not sys.platform.startswith("linux"):
        parser.error("fresh Linux -I -B interpreter required")
    # Deliberately no model/source/output generalization or runtime recapture.
    if (args.output.parent != Path("/root/m9-capacity-recovery-20261005")
            or args.output.name != args.mode
            or any(p.is_symlink() for p in (args.output, *args.output.parents))):
        parser.error("output must be the dedicated timing root / mode")
    if args.output.exists():
        parser.error("existing attempt preserved; no retry")
    timing = Timing(120)
    source = STAGE / "source/server"
    fixture_raw = pinned_bytes(args.fixture, FIXTURE_SHA)
    original_manifest = json.loads(pinned_bytes(STAGE / "panel-runtime.json", MANIFEST_SHA))
    pinned_bytes(source / "shengji/eval/observation_runtime.py", ADAPTER_SHA)
    sys.path.insert(0, str(source))
    from shengji.eval.observation_runtime import ObservationRuntime, capture
    from shengji.eval import tactical, public_fixture_panel, fixed_tape_panel
    from shengji.eval.public_refusal_history import public_root_with_ledger
    from shengji.harvest.legal import enumerate_legal
    # Capture and verify through THIS entrypoint. The old qualification
    # driver's __main__.__file__ belongs to its dependency set, not ours.
    runtime_path = args.output.parent / "runtime.json"
    runtime = timing.call("runtime_qualification", qualify, args.action, source,
                          original_manifest, runtime_path, args.runtime_sha256,
                          capture, ObservationRuntime)
    if args.action != "measure":
        print("TIMING QUALIFICATION DONE; no model access", flush=True)
        return
    fixture = tactical.fixture_from_json(json.loads(fixture_raw))
    root, _ledger, _receipt = public_root_with_ledger(fixture, mode=args.mode)
    legal = enumerate_legal(root, fixture.seat, cap=4000)
    if not legal.complete or legal.count != 1771:
        raise ValueError("capacity fixture legal-pool mismatch")
    model = Path("/root/models/smv3out-491ee4bf.npz")
    # The real factory also checks the model digest; this first access binds it
    # before timing constructions. Retain factory caching behavior unchanged.
    timing.call("model_authentication", pinned_bytes, model, MODEL_SHA)
    environment = tactical.observation_comparison_environs(str(model), MODEL_SHA)["div+rc+tb+la"]
    def factory():
        return tactical.bot_from_environ(environment, seed=SEED)[1]
    require_runtime(runtime, "before timing")
    with ExitStack() as stack:
        for module, name, label in (
            (public_fixture_panel, "sample_public_refusal_tape", "public_replay_and_sampling"),
            (public_fixture_panel, "enumerate_legal", "legal_enumeration"),
            (fixed_tape_panel, "capture_fixed_tape", "fixed_tape_scoring"),
        ):
            stack.enter_context(timed_call(module, name, timing, label))
        measure(public_fixture_panel.collect_public_fixture_panel, factory, fixture,
                (legal.actions[:8], legal.actions[-8:]), mode=args.mode,
                output=args.output, timing=timing)
    require_runtime(runtime, "after timing")
    print("CAPACITY COMPLETE; runtime postcheck PASS; not scientific collection", flush=True)


if __name__ == "__main__":
    main()
