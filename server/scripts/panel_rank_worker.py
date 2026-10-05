"""Prepared S10 selected-panel worker; not an independently qualified release.

Authenticates controls before selected access, preserves failed attempts and
never invokes collection/full-readout entry points. External review, exclusive
ownership and RELEASE for this exact invocation remain required. A matching
release document is a binding, not proof of external authority.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import time
import sys
import types


_META = ("owner", "process", "collection", "saved_readout", "plan")
_INPUTS = frozenset(_META) | {f"validated-{i:03d}.json" for i in range(15)}
_KEYS = frozenset({"schema", "files", "packet_sha256", "collection_packet",
                   "controls", "terminal_seal", "runtime", "output_dir",
                   "receipt", "index", "timeout_seconds", "ownership_dir"})


def _pin(helper, value, label):
    if type(value) is not dict or set(value) != {"path", "sha256"}:
        raise ValueError(f"exact {label} path/SHA pin required")
    helper._canonical_absolute(value["path"], label)
    helper._strict_sha(value["sha256"], label)


def _document(helper, pin, label):
    """One bounded, stable, hash-checked JSON snapshot; never panel data."""
    _pin(helper, pin, label)
    path = helper._canonical_absolute(pin["path"], label)
    raw, _ = helper._stable_read(path, 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != pin["sha256"]:
        raise ValueError(f"{label} SHA mismatch")
    return raw, helper._parse_object(raw)


def read_rank_authorization(helper, invocation_pin, release_pin):
    """Bind a new invocation to its new release and old receipt inventory.

    The release is a separate pinned document to avoid a circular hash: it
    names the invocation digest; the invocation does not name the release.
    Return a detached specification and the seven selected-reader pins. This
    does not open any panel, construct a model, or grant permission to do so.
    """
    raw, spec = _document(helper, invocation_pin, "invocation")
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"),
                           allow_nan=False).encode()
    if raw != canonical or set(spec) != _KEYS or spec.get("schema") != "panel-rank-invocation-v1":
        raise ValueError("exact canonical panel-rank invocation required")
    if type(spec["index"]) is not int or not 0 <= spec["index"] < 15:
        raise ValueError("strict panel index in [0, 15) required")
    timeout = spec["timeout_seconds"]
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("positive finite timeout required")
    helper._strict_sha(spec["packet_sha256"], "packet SHA")
    for name in ("collection_packet", "terminal_seal", "runtime", "receipt"):
        _pin(helper, spec[name], name)
    if spec["collection_packet"]["sha256"] != spec["packet_sha256"]:
        raise ValueError("collection packet digest mismatch")
    if type(spec["files"]) is not dict or set(spec["files"]) != _INPUTS:
        raise ValueError("exact twenty-file inventory required")
    if type(spec["controls"]) is not dict or set(spec["controls"]) != {"release", "claim", "reservation", "process_claim"}:
        raise ValueError("exact historical controls required")
    for name, pin in {**spec["files"], **spec["controls"]}.items():
        _pin(helper, pin, name)
    paths = [p["path"] for p in spec["files"].values()]
    if len(set(paths)) != len(paths):
        raise ValueError("distinct inventory paths required")
    output = helper._canonical_absolute(spec["output_dir"], "output")
    ownership = helper._canonical_absolute(spec["ownership_dir"], "rank ownership")
    if output == ownership or output in ownership.parents or ownership in output.parents:
        raise ValueError("distinct non-overlapping rank ownership/output required")
    # Do not permit publication to contain inputs, including the authorization
    # documents. Actual atomic output reservation belongs to the runner.
    pins = [*spec["files"].values(), *spec["controls"].values(),
            *(spec[n] for n in ("collection_packet", "terminal_seal", "runtime", "receipt")),
            invocation_pin, release_pin]
    for pin in pins:
        _pin(helper, pin, "protected input")
        path = helper._canonical_absolute(pin["path"], "protected input")
        if any(root == path or root in path.parents for root in (output, ownership)):
            raise ValueError("output overlaps protected input")
    if output.exists() or output.is_symlink():
        raise ValueError("fresh output required")
    if ownership.exists() or ownership.is_symlink():
        raise ValueError("rank ownership already spent")

    _, release = _document(helper, release_pin, "release")
    expected_release = {"schema": "panel-rank-release-v1", "decision": "RELEASE",
                        "invocation_sha256": invocation_pin["sha256"],
                        "ownership_dir": spec["ownership_dir"],
                        "packet_sha256": spec["packet_sha256"], "index": spec["index"]}
    if release != expected_release:
        raise ValueError("fresh invocation-bound RELEASE required")
    _, receipt = _document(helper, spec["receipt"], "receipt")
    receipt_keys = {"schema", "invocation_sha256", "packet_sha256", "collection_packet",
                    "controls", "terminal_seal", "result_sha256", "runtime",
                    "input_sha256", "provenance_verified"}
    if (set(receipt) != receipt_keys or receipt.get("schema") != "m9-panel-readout-receipt-v1"
            or receipt.get("provenance_verified") is not False):
        raise ValueError("completed M9 readout receipt required")
    helper._strict_sha(receipt["invocation_sha256"], "previous invocation SHA")
    _pin(helper, receipt["runtime"], "previous runtime")
    for name in ("packet_sha256", "collection_packet", "controls", "terminal_seal"):
        if receipt.get(name) != spec[name]:
            raise ValueError(f"receipt {name} mismatch")
    expected_hashes = {name: pin["sha256"] for name, pin in spec["files"].items()}
    if receipt.get("input_sha256") != expected_hashes:
        raise ValueError("receipt input inventory mismatch")
    helper._strict_sha(receipt.get("result_sha256"), "previous result SHA")
    selected = {name: spec["files"][name] for name in _META}
    selected["packet"] = spec["collection_packet"]
    selected["panel"] = spec["files"][f"validated-{spec['index']:03d}.json"]
    return copy.deepcopy(spec), copy.deepcopy(selected)


def execute_rank_once(helper, spec, selected_pins, packet, runtime, *,
                      invocation_sha256, release_pin, check_authorization):
    """Admitted body: exclusive claim, one selected read, dual-arm projection.

    Not a bootstrap. The caller must authenticate source/runtime, collection
    packet, terminal seal and historical controls before calling. The supplied
    authorization check must retain and check the new release/invocation pins.
    No collection or historical full-readout entry point is called here.
    """
    from shengji.eval import tactical
    from shengji.eval.m9_panel_recipe import validate_panel_recipe, panel_model_environ
    from shengji.eval.m9_panel_plan import ROOTS
    from shengji.eval.selected_panel_reader import read_selected_panel
    from shengji.eval.panel_rank_root import project_panel_rank_repairs
    from shengji.luna.atomic_io import publish_exclusive_bytes

    spec, packet = copy.deepcopy(spec), copy.deepcopy(packet)
    selected_pins = copy.deepcopy(selected_pins)
    helper._strict_sha(invocation_sha256, "invocation SHA")
    _pin(helper, release_pin, "new release")
    if not callable(check_authorization):
        raise ValueError("explicit live authorization check required")
    recipe = packet["recipe"]
    validate_panel_recipe(recipe)
    deadline = time.monotonic() + spec["timeout_seconds"]
    stamps = []

    def budget():
        if time.monotonic() >= deadline:
            raise TimeoutError("panel rank deadline expired")

    def checkpoint():
        budget()
        if check_authorization() is not True:
            raise ValueError("panel rank authorization changed")
        if runtime.check() is not True:
            raise ValueError("panel rank runtime changed")
        if any(helper._stamp(path) != stamp for path, stamp in stamps):
            raise ValueError("panel rank authenticated input changed")

    def publish(name, value):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode()
        publish_exclusive_bytes(output / name, raw, mode=0o400)
        return hashlib.sha256(raw).hexdigest()

    checkpoint()
    output = helper._canonical_absolute(spec["output_dir"], "rank output")
    ownership = helper._canonical_absolute(spec["ownership_dir"], "rank ownership")
    if output.exists() or output.is_symlink():
        raise FileExistsError("rank output already occupied")
    # The reviewed RELEASE must designate the single canonical ownership path
    # for this packet/index. Different output paths cannot bypass that claim.
    # A failed owner remains spent, including failures before output creation.
    ownership.mkdir(mode=0o700)
    ownership_raw = json.dumps({"schema": "panel-rank-owner-v1",
                               "invocation_sha256": invocation_sha256,
                               "packet_sha256": spec["packet_sha256"], "index": spec["index"],
                               "output_dir": str(output), "release": release_pin},
                              sort_keys=True, separators=(",", ":")).encode()
    owner_record = ownership / "claim.json"
    publish_exclusive_bytes(owner_record, ownership_raw, mode=0o400)
    stamps.append((owner_record, helper._stamp(owner_record)))
    # Atomic reservation precedes any selected panel read or model construction.
    # A failed/partial attempt remains occupied; no repair or retry here.
    output.mkdir(mode=0o700)
    stage = "claim"
    try:
        publish("claim.json", {"schema": "panel-rank-attempt-v1",
                               "invocation_sha256": invocation_sha256,
                               "release": release_pin, "status": "spent_no_retry"})
        stage = "fixture"
        fixture_path = helper._canonical_absolute(recipe["fixtures"], "fixtures")
        raw, mark = helper._stable_read(fixture_path, 8 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != recipe["fixture_sha256"]:
            raise ValueError("panel rank fixture SHA mismatch")
        stamps.append((fixture_path, mark))
        fixtures = []
        for line in raw.decode("utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                fixtures.append(tactical.fixture_from_json(helper._parse_object(line.encode())))
        if len(fixtures) != len(ROOTS) or {f.id for f in fixtures} != set(ROOTS):
            raise ValueError("exact M9 fixture population required")
        if any(f.category != tactical.OBSERVATION_CATEGORY or f.current_bot is not None
               for f in fixtures):
            raise ValueError("observation-only fixtures required")
        stage = "model-authentication"
        model = helper._canonical_absolute(recipe["model"], "model")
        before = helper._stamp(model)
        if helper._sha_file(model) != recipe["model_sha256"] or helper._stamp(model) != before:
            raise ValueError("panel rank model SHA mismatch or drift")
        stamps.append((model, before))
        # Record metadata BEFORE the selected read, then require it unchanged
        # after: no post-read stamp may silently adopt replaced input bytes.
        stamps.extend((helper._canonical_absolute(p["path"], "selected input"),
                       helper._stamp(Path(p["path"]))) for p in selected_pins.values())
        checkpoint()
        stage = "selected-reader"
        selected = read_selected_panel(selected_pins,
                                       packet_sha256=spec["packet_sha256"], index=spec["index"])
        checkpoint()
        fixture = next(f for f in fixtures if f.id == selected["job"]["fixture_id"])
        stage = "model-construction"
        _, bot = tactical.bot_from_environ(panel_model_environ(recipe), seed=selected["job"]["seed"])
        checkpoint()
        stage = "rank-projection"
        result = project_panel_rank_repairs(selected, fixture, bot, check_budget=budget)
        checkpoint()
        stage = "publication"
        result_sha = publish("result.json", result)
        checkpoint()
        receipt = {"schema": "panel-rank-receipt-v1", "invocation_sha256": invocation_sha256,
                   "result_sha256": result_sha, "input_sha256": selected["input_sha256"],
                   "previous_receipt": spec["receipt"], "release": release_pin,
                   "ownership_dir": str(ownership),
                   "runtime": spec["runtime"], "model_sha256": recipe["model_sha256"],
                   "fixture_sha256": recipe["fixture_sha256"], "provenance_verified": False,
                   "serving_choice_assessed": False, "strategic_quality_assessed": False}
        publish("receipt.json", receipt)
        return receipt
    except BaseException as exc:
        publish("refusal.json", {"schema": "panel-rank-refusal-v1",
                                 "error_type": type(exc).__name__, "stage": stage,
                                 "invocation_sha256": invocation_sha256})
        raise


def _load_bootstrap(digest):
    """Authenticate the stdlib-only sibling before executing any of its code."""
    if (type(digest) is not str or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)):
        raise ValueError("strict bootstrap SHA required")
    path = Path(__file__).parent / "m9_panel_readout_worker.py"
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("canonical bootstrap required")
    before = path.stat()
    if not path.is_file() or before.st_size > 256 * 1024:
        raise ValueError("bounded regular bootstrap required")
    with path.open("rb") as handle:
        raw = handle.read(256 * 1024 + 1)
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (len(raw) > 256 * 1024 or any(getattr(before, k) != getattr(after, k) for k in fields)
            or hashlib.sha256(raw).hexdigest() != digest):
        raise ValueError("bootstrap changed or SHA mismatch")
    module = types.ModuleType("_panel_rank_bootstrap")
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def _runtime_gate():
    if not sys.platform.startswith("linux") or not sys.flags.isolated or not sys.dont_write_bytecode:
        raise ValueError("isolated Linux -I -B interpreter required")
    if any(n == "shengji" or n.startswith("shengji.") or n == "scripts" or n.startswith("scripts.")
           for n in sys.modules):
        raise ValueError("application modules already imported")


def qualify_runtime(runtime_path, runtime_sha, bootstrap_sha, helper_sha, *, output=None):
    """Model-free rank-profile capture or verification through this bootstrap."""
    _runtime_gate()
    bootstrap = _load_bootstrap(bootstrap_sha)
    helper = bootstrap._load_helper(helper_sha)
    server = helper._canonical_absolute(str(Path(__file__).parents[1]), "server")
    baseline = bootstrap._read_qualification_runtime(helper, runtime_path, runtime_sha,
                                                     server, helper_sha)
    if baseline["source_files"].get("scripts/m9_panel_readout_worker.py") != bootstrap_sha:
        raise ValueError("runtime does not bind readout bootstrap")
    target = bootstrap._qualification_output(helper, output, server) if output is not None else None
    import importlib
    sys.path.insert(0, str(server))
    importlib.invalidate_caches()
    adapter = importlib.import_module("shengji.eval.observation_runtime")
    if target is None:
        admitted = adapter.ObservationRuntime(baseline, profile="panel-rank")
        if admitted.check() is not True:
            raise ValueError("rank runtime verification failed")
        return baseline
    manifest = adapter.capture(server, profile="panel-rank")
    for key in ("source_root", "source_files", "environment"):
        if manifest.get(key) != baseline.get(key):
            raise ValueError("qualification source/environment drift")
    raw = (json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    target = bootstrap._qualification_output(helper, output, server)
    with target.open("xb") as handle:
        handle.write(raw)
    return manifest


def run(invocation_path, invocation_sha, release_path, release_sha, bootstrap_sha, helper_sha):
    """Authenticate this invocation before importing application/model code."""
    _runtime_gate()
    bootstrap = _load_bootstrap(bootstrap_sha)
    helper = bootstrap._load_helper(helper_sha)
    invocation_pin = {"path": invocation_path, "sha256": invocation_sha}
    release_pin = {"path": release_path, "sha256": release_sha}
    # Preserve stamps from each authenticated read, including all historical
    # controls/seals. Rechecks never reread or rehash the raw panel inventory.
    control_stamps = []
    original_read = helper._stable_read

    def tracked_read(path, limit):
        raw, stamp = original_read(path, limit)
        control_stamps.append((path, stamp))
        return raw, stamp

    helper._stable_read = tracked_read
    spec, selected = read_rank_authorization(helper, invocation_pin, release_pin)
    _, packet = bootstrap._read_collection_packet(helper, spec)
    server = helper._canonical_absolute(str(Path(__file__).parents[1]), "server")
    manifest = helper._read_runtime(spec, server)
    if (manifest["source_files"].get("scripts/observation_worker.py") != helper_sha
            or manifest["source_files"].get("scripts/m9_panel_readout_worker.py") != bootstrap_sha):
        raise ValueError("bootstrap pins differ from authenticated source manifest")
    bootstrap._verify_terminal_seal(helper, spec, packet)
    controls = bootstrap._read_controls(helper, spec, packet)
    bootstrap._read_collection_runtime(helper, packet, controls)

    def authorization():
        if any(helper._stamp(p) != mark for p, mark in control_stamps):
            raise ValueError("authenticated control changed")
        return True

    authorization()
    import importlib
    sys.path.insert(0, str(server))
    importlib.invalidate_caches()
    adapter = importlib.import_module("shengji.eval.observation_runtime")
    runtime = adapter.ObservationRuntime(manifest, profile="panel-rank")
    return execute_rank_once(helper, spec, selected, packet, runtime,
                             invocation_sha256=invocation_sha, release_pin=release_pin,
                             check_authorization=authorization)


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)
    try:
        if args and args[0] == "--capture-runtime" and len(args) == 6:
            qualify_runtime(*args[1:5], output=args[5])
        elif args and args[0] == "--verify-runtime" and len(args) == 5:
            qualify_runtime(*args[1:])
        elif len(args) != 6 or args[0].startswith("--"):
            raise ValueError("six pinned invocation/release/bootstrap arguments required")
        else:
            run(*args)
    except BaseException as exc:
        print(type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
