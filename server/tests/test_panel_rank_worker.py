"""Synthetic control-only S10 admission tests; no model or historical reads."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import observation_worker as helper
from scripts import panel_rank_worker as worker


def write_pin(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def bundle(tmp_path, mutate_spec=None, mutate_receipt=None, mutate_release=None):
    def pin(name):
        # These inputs deliberately do not exist: admission must not open them.
        return {"path": str(tmp_path / name), "sha256": "a" * 64}

    spec = {"schema": "panel-rank-invocation-v1", "index": 7,
            "timeout_seconds": 30, "output_dir": str(tmp_path / "output"),
            "ownership_dir": str(tmp_path / "rank-owner"),
            "files": {name: pin(name) for name in worker._INPUTS},
            "packet_sha256": "a" * 64, "collection_packet": pin("packet"),
            "controls": {name: pin(name) for name in
                         ("release", "claim", "reservation", "process_claim")},
            "runtime": pin("runtime"), "terminal_seal": pin("seal")}
    receipt = {"schema": "m9-panel-readout-receipt-v1",
               **{name: spec[name] for name in
                  ("packet_sha256", "collection_packet", "controls", "terminal_seal")},
               "input_sha256": {name: p["sha256"] for name, p in spec["files"].items()},
               "result_sha256": "b" * 64, "invocation_sha256": "c" * 64,
               "runtime": pin("old-runtime"), "provenance_verified": False}
    if mutate_receipt:
        mutate_receipt(receipt)
    spec["receipt"] = write_pin(tmp_path / "receipt.json", receipt)
    if mutate_spec:
        mutate_spec(spec)
    invocation = write_pin(tmp_path / "invocation.json", spec)
    release = {"schema": "panel-rank-release-v1", "decision": "RELEASE",
               "invocation_sha256": invocation["sha256"],
               "ownership_dir": spec["ownership_dir"], "packet_sha256": spec["packet_sha256"],
               "index": spec["index"]}
    if mutate_release:
        mutate_release(release)
    return invocation, write_pin(tmp_path / "new-release.json", release)


def test_reads_only_three_control_documents(tmp_path, monkeypatch):
    invocation, release = bundle(tmp_path)
    reads = []
    original = helper._stable_read

    def read(path, limit):
        reads.append(path.name)
        return original(path, limit)

    monkeypatch.setattr(helper, "_stable_read", read)
    spec, selected = worker.read_rank_authorization(helper, invocation, release)
    assert reads == ["invocation.json", "new-release.json", "receipt.json"]
    assert set(selected) == set(worker._META) | {"packet", "panel"}
    assert selected["panel"] == spec["files"]["validated-007.json"]
    selected["panel"]["sha256"] = "c" * 64
    assert spec["files"]["validated-007.json"]["sha256"] == "a" * 64
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("index", [True, -1, 15, 1.0, "1", None])
def test_bad_index(tmp_path, index):
    pins = bundle(tmp_path, mutate_spec=lambda s: s.update(index=index))
    with pytest.raises(ValueError, match="index"):
        worker.read_rank_authorization(helper, *pins)


@pytest.mark.parametrize("timeout", [True, False, 0, -1, "30", None])
def test_bad_timeout(tmp_path, timeout):
    pins = bundle(tmp_path, mutate_spec=lambda s: s.update(timeout_seconds=timeout))
    with pytest.raises(ValueError, match="timeout"):
        worker.read_rank_authorization(helper, *pins)


@pytest.mark.parametrize("change", [
    {"schema": "m9-panel-release-v1"}, {"decision": "HOLD"},
    {"invocation_sha256": "f" * 64}, {"extra": True},
])
def test_fresh_release_required_before_receipt(tmp_path, monkeypatch, change):
    pins = bundle(tmp_path, mutate_release=lambda r: r.update(change))
    (tmp_path / "receipt.json").unlink()
    with pytest.raises(ValueError, match="invocation-bound RELEASE"):
        worker.read_rank_authorization(helper, *pins)


@pytest.mark.parametrize("name", ["validated-007.json", "validated-014.json", "owner"])
def test_whole_inventory_bound_not_only_selected(tmp_path, name):
    pins = bundle(tmp_path, mutate_receipt=lambda r: r["input_sha256"].update({name: "f" * 64}))
    with pytest.raises(ValueError, match="inventory"):
        worker.read_rank_authorization(helper, *pins)


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_occupied_output_untouched(tmp_path, kind):
    pins = bundle(tmp_path)
    output = tmp_path / "output"
    if kind == "file":
        output.write_text("preserve")
    else:
        output.mkdir()
    with pytest.raises(ValueError, match="fresh output"):
        worker.read_rank_authorization(helper, *pins)
    assert output.exists()
    if kind == "file":
        assert output.read_text() == "preserve"


def test_output_cannot_contain_inputs(tmp_path):
    pins = bundle(tmp_path, mutate_spec=lambda s: s.update(output_dir=str(tmp_path)))
    with pytest.raises(ValueError, match="overlap"):
        worker.read_rank_authorization(helper, *pins)


@pytest.mark.parametrize("name", ["invocation.json", "new-release.json", "receipt.json"])
def test_tampered_control(tmp_path, name):
    pins = bundle(tmp_path)
    (tmp_path / name).write_bytes(b"{}")
    with pytest.raises(ValueError, match="SHA mismatch"):
        worker.read_rank_authorization(helper, *pins)


def test_cli_without_pins_is_fail_closed():
    result = subprocess.run([sys.executable, "-I", "-B", worker.__file__],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "ValueError" in result.stderr


@pytest.mark.parametrize("failure", [None, "fixture", "model", "prediction", "drift", "occupied",
                                    "runtime", "authorization", "deadline"])
def test_admitted_body_publication_and_refusal(tmp_path, monkeypatch, failure):
    from shengji.eval import tactical, m9_panel_recipe, selected_panel_reader, panel_rank_root
    from shengji.eval.m9_panel_plan import ROOTS

    pins = bundle(tmp_path)
    spec, selected_pins = worker.read_rank_authorization(helper, *pins)
    fixture = write_pin(tmp_path / "fixtures.jsonl", {"id": "synthetic"})
    model = tmp_path / "model.npz"
    model.write_bytes(b"synthetic-model-not-executable")
    recipe = {"fixtures": fixture["path"], "fixture_sha256": fixture["sha256"],
              "model": str(model), "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest()}
    for pin in selected_pins.values():
        Path(pin["path"]).write_bytes(b"synthetic-selected-placeholder")
    # Body tests isolate authenticated bootstrap and panel semantics; real
    # selected-reader/root suites cover those separately. No real model load.
    monkeypatch.setattr(m9_panel_recipe, "validate_panel_recipe", lambda _: None)
    monkeypatch.setattr(m9_panel_recipe, "panel_model_environ", lambda _: {})
    fixture_objects = [SimpleNamespace(id=name, category=tactical.OBSERVATION_CATEGORY,
                                      current_bot=None) for name in ROOTS]
    fixture_lines = b"\n".join(json.dumps({"id": f.id}).encode() for f in fixture_objects)
    Path(fixture["path"]).write_bytes(fixture_lines)
    recipe["fixture_sha256"] = hashlib.sha256(fixture_lines).hexdigest()
    monkeypatch.setattr(tactical, "fixture_from_json",
                        lambda obj: next(f for f in fixture_objects if f.id == obj["id"]))
    events = []
    gates = {"runtime": True, "authorization": True, "clock": 0.0}
    monkeypatch.setattr(worker.time, "monotonic", lambda: gates["clock"])

    def read(*args, **kwargs):
        events.append("selected-read")
        assert (tmp_path / "output" / "claim.json").is_file()
        return {"job": {"fixture_id": fixture_objects[0].id, "seed": 1},
                "input_sha256": {"panel": "a" * 64}}

    def factory(env, *, seed):
        events.append("factory")
        assert seed == 1
        return "synthetic", object()

    def project(*args, check_budget):
        check_budget()
        events.append("dual-arm-projection")
        if failure == "prediction":
            raise ValueError("synthetic prediction refusal")
        if failure == "drift":
            model.write_bytes(b"changed")
        if failure in ("runtime", "authorization"):
            gates[failure] = False
        if failure == "deadline":
            gates["clock"] = 31.0
        return {"projections": {"control": {}, "treatment": {}}}

    monkeypatch.setattr(selected_panel_reader, "read_selected_panel", read)
    monkeypatch.setattr(tactical, "bot_from_environ", factory)
    monkeypatch.setattr(panel_rank_root, "project_panel_rank_repairs", project)
    if failure in ("fixture", "model"):
        recipe["fixture_sha256" if failure == "fixture" else "model_sha256"] = "f" * 64
    if failure == "occupied":
        (tmp_path / "output").mkdir()
    args = (helper, spec, selected_pins, {"recipe": recipe},
            SimpleNamespace(check=lambda: gates["runtime"]))
    kwargs = dict(invocation_sha256=pins[0]["sha256"], release_pin=pins[1],
                  check_authorization=lambda: gates["authorization"])
    if failure:
        with pytest.raises((ValueError, FileExistsError, TimeoutError)):
            worker.execute_rank_once(*args, **kwargs)
        assert not (tmp_path / "output" / "receipt.json").exists()
        if failure != "occupied":
            refusal = json.loads((tmp_path / "output" / "refusal.json").read_bytes())
            assert refusal["stage"]
            assert "reason" not in refusal
            assert "synthetic prediction refusal" not in json.dumps(refusal)
        if failure in ("fixture", "model", "occupied"):
            assert events == []
    else:
        receipt = worker.execute_rank_once(*args, **kwargs)
        assert events == ["selected-read", "factory", "dual-arm-projection"]
        assert receipt["result_sha256"] == hashlib.sha256(
            (tmp_path / "output" / "result.json").read_bytes()).hexdigest()
        assert json.loads((tmp_path / "output" / "receipt.json").read_bytes()) == receipt
        with pytest.raises(FileExistsError):
            worker.execute_rank_once(*args, **kwargs)
        # A different output is not permission to repeat this panel read.
        spec["output_dir"] = str(tmp_path / "second-output")
        with pytest.raises(FileExistsError):
            worker.execute_rank_once(*args, **kwargs)
        assert not (tmp_path / "second-output").exists()
        assert len(events) == 3


def test_bootstrap_authenticates_exact_bytes():
    path = Path(worker.__file__).with_name("m9_panel_readout_worker.py")
    bootstrap = worker._load_bootstrap(hashlib.sha256(path.read_bytes()).hexdigest())
    assert bootstrap.__file__ == str(path)
    assert callable(bootstrap._verify_terminal_seal)
    with pytest.raises(ValueError, match="SHA mismatch"):
        worker._load_bootstrap("f" * 64)


def test_nonisolated_run_refuses_before_loading_bootstrap(monkeypatch):
    def forbidden(*args):
        pytest.fail("bootstrap loaded before interpreter gate")
    monkeypatch.setattr(worker, "_load_bootstrap", forbidden)
    monkeypatch.setattr(worker.sys, "flags", SimpleNamespace(isolated=0))
    with pytest.raises(ValueError, match="interpreter"):
        worker.run(*(["unused"] * 6))


def test_main_requires_and_forwards_exact_pins(monkeypatch):
    seen = []
    monkeypatch.setattr(worker, "run", lambda *args: seen.append(args))
    assert worker.main(["a"] * 5) == 1
    assert seen == []
    assert worker.main(["a", "b", "c", "d", "e", "f"]) == 0
    assert seen == [("a", "b", "c", "d", "e", "f")]


@pytest.mark.parametrize("field", ["invocation_sha256", "runtime", "provenance_verified"])
def test_incomplete_previous_receipt_refused(tmp_path, field):
    pins = bundle(tmp_path, mutate_receipt=lambda r: r.pop(field))
    with pytest.raises(ValueError, match="receipt required"):
        worker.read_rank_authorization(helper, *pins)


def test_qualification_cli_routes(monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "qualify_runtime", lambda *a, **kw: calls.append((a, kw)))
    assert worker.main(["--capture-runtime", "path", "sha", "boot", "helper", "out"]) == 0
    assert worker.main(["--verify-runtime", "path", "sha", "boot", "helper"]) == 0
    assert calls == [(("path", "sha", "boot", "helper"), {"output": "out"}),
                     (("path", "sha", "boot", "helper"), {})]
    assert worker.main(["--capture-runtime", "path", "sha", "boot", "helper"]) == 1


@pytest.mark.parametrize("drift", [False, True])
def test_rank_qualification_authenticates_before_capture(tmp_path, monkeypatch, drift):
    import importlib
    from scripts import m9_panel_readout_worker as bootstrap
    events = []
    baseline = {"source_root": str(Path(worker.__file__).parents[1]),
                "source_files": {"scripts/m9_panel_readout_worker.py": "b" * 64},
                "environment": {}}
    monkeypatch.setattr(worker, "_runtime_gate", lambda: events.append("gate"))
    monkeypatch.setattr(worker, "_load_bootstrap", lambda sha: bootstrap)
    monkeypatch.setattr(bootstrap, "_load_helper", lambda sha: helper)
    def authenticated(*args):
        events.append("authenticated-baseline")
        return baseline
    monkeypatch.setattr(bootstrap, "_read_qualification_runtime", authenticated)
    def capture(source, *, profile):
        assert events == ["gate", "authenticated-baseline"]
        assert profile == "panel-rank"
        events.append("capture")
        return dict(baseline, environment={"changed": True}) if drift else baseline
    real_import = importlib.import_module
    monkeypatch.setattr(importlib, "import_module", lambda name: SimpleNamespace(capture=capture)
                        if name == "shengji.eval.observation_runtime" else real_import(name))
    monkeypatch.setattr(sys, "path", list(sys.path))
    output = tmp_path / "qualified.json"
    if drift:
        with pytest.raises(ValueError, match="drift"):
            worker.qualify_runtime("path", "sha", "b" * 64, "helper", output=str(output))
        assert not output.exists()
    else:
        assert worker.qualify_runtime("path", "sha", "b" * 64, "helper", output=str(output)) == baseline
        assert json.loads(output.read_bytes()) == baseline
        with pytest.raises(ValueError, match="exists"):
            worker.qualify_runtime("path", "sha", "b" * 64, "helper", output=str(output))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="requires native Linux runtime")
def test_real_isolated_rank_runtime_capture_verify(tmp_path):
    """Actual model-free CLI, no patched runtime/gates/imports.

    Stage only application sources/native extension; never copy datasets or
    checkpoints. The baseline is an independently hashed source inventory,
    not a relabeled historical runtime manifest.
    """
    source = Path(worker.__file__).parents[1]
    if not list((source / "shengji" / "engine").glob("_fast*.so")):
        pytest.skip("compiled native engine required")
    staged = tmp_path / "checkout" / "server"
    for directory in ("scripts", "shengji"):
        shutil.copytree(source / directory, staged / directory,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    inventory = {p.relative_to(staged).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for folder in ("scripts", "shengji") for p in (staged / folder).rglob("*")
                 if p.is_file() and p.suffix in (".py", ".so")}
    environment = {"SHENGJI_FAST": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                   "MKL_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
                   "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    prefixes = ("SHENGJI_", "PYTHON", "OMP_", "OPENBLAS_", "MKL_", "VECLIB_", "NUMEXPR_",
                "LC_", "LD_", "DYLD_", "BLIS_", "GOTO_", "KMP_")
    env = {key: value for key, value in os.environ.items() if not key.startswith(prefixes)}
    env.update(environment)
    baseline = write_pin(tmp_path / "baseline.json", {
        "schema": "shengji-m9-runtime-v1", "source_root": str(staged),
        "source_files": inventory, "environment": environment})
    command = [sys.executable, "-I", "-B", str(staged / "scripts" / "panel_rank_worker.py")]
    bootstrap = inventory["scripts/m9_panel_readout_worker.py"]
    helper_sha = inventory["scripts/observation_worker.py"]
    output = tmp_path / "qualified.json"
    capture = subprocess.run(command + ["--capture-runtime", baseline["path"], baseline["sha256"],
                                        bootstrap, helper_sha, str(output)], env=env,
                             capture_output=True, text=True, timeout=60)
    assert capture.returncode == 0, capture.stderr
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    verify = subprocess.run(command + ["--verify-runtime", str(output), digest, bootstrap, helper_sha],
                            env=env, capture_output=True, text=True, timeout=60)
    assert verify.returncode == 0, verify.stderr
    manifest = json.loads(output.read_bytes())
    assert "shengji.eval.panel_rank_root" in manifest["external_runtime"]["imports"]
    assert manifest["source_files"] == inventory
    # Source drift cannot be adopted by verification.
    target = staged / "shengji" / "eval" / "panel_rank_root.py"
    target.write_bytes(target.read_bytes() + b"\n# synthetic source drift\n")
    refused = subprocess.run(command + ["--verify-runtime", str(output), digest, bootstrap, helper_sha],
                             env=env, capture_output=True, text=True, timeout=60)
    assert refused.returncode != 0
    assert "ValueError" in refused.stderr
    assert hashlib.sha256(output.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("mode", ["fresh-root", "history-primed"])
def test_body_real_root_capture_projection_and_publication(tmp_path, monkeypatch, mode):
    """Real root/rank/projection joins and publication, synthetic predictor.

    Reader admission is deliberately isolated here; this does not qualify the
    CLI bootstrap or runtime. Unlike the orchestration test this must exercise
    the real physical-card validator and both arm projections.
    """
    import copy
    import numpy as np
    from test_panel_rank_root import selected_inputs
    from shengji.eval import tactical, m9_panel_recipe, m9_panel_plan, selected_panel_reader

    selected, fixture, bot = selected_inputs(mode)
    pins = bundle(tmp_path)
    spec, selected_pins = worker.read_rank_authorization(helper, *pins)
    selected["input_sha256"] = {name: pin["sha256"] for name, pin in selected_pins.items()}
    original = copy.deepcopy(selected)
    rng = bot.sampler.rng.getstate()
    fixture_pin = write_pin(tmp_path / "fixtures.jsonl", fixture.to_json())
    model = tmp_path / "synthetic-model"
    model.write_bytes(b"not-a-checkpoint")
    recipe = {"fixtures": fixture_pin["path"], "fixture_sha256": fixture_pin["sha256"],
              "model": str(model), "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest()}
    for pin in selected_pins.values():
        Path(pin["path"]).write_bytes(b"reader-boundary-placeholder")
    monkeypatch.setattr(m9_panel_recipe, "validate_panel_recipe", lambda _: None)
    monkeypatch.setattr(m9_panel_recipe, "panel_model_environ", lambda _: {})
    monkeypatch.setattr(m9_panel_plan, "ROOTS", (fixture.id,))
    calls = []

    def predict(x):
        calls.append(len(x))
        return np.tile(np.arange(54), (len(x), 1))

    bot.predict = predict
    monkeypatch.setattr(tactical, "bot_from_environ", lambda env, *, seed: ("synthetic", bot))
    monkeypatch.setattr(selected_panel_reader, "read_selected_panel", lambda *a, **kw: selected)
    receipt = worker.execute_rank_once(
        helper, spec, selected_pins, {"recipe": recipe}, SimpleNamespace(check=lambda: True),
        invocation_sha256=pins[0]["sha256"], release_pin=pins[1], check_authorization=lambda: True)
    result_path = tmp_path / "output" / "result.json"
    result = json.loads(result_path.read_bytes())
    assert calls == [64]
    assert set(result["projections"]) == {"control", "treatment"}
    assert result["serving_choice_assessed"] is False
    assert receipt["result_sha256"] == hashlib.sha256(result_path.read_bytes()).hexdigest()
    assert selected == original
    assert bot.sampler.rng.getstate() == rng
