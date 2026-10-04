"""Synthetic, import-only tests for the M9 runtime admission boundary."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from shengji.eval import observation_runtime as runtime
from shengji.eval.observation_lease import file_stamp


def _source(tmp_path):
    source = tmp_path / "source"
    (source / "shengji" / "engine").mkdir(parents=True)
    (source / "scripts").mkdir()
    (source / "shengji" / "__init__.py").write_text("# synthetic\n")
    (source / "shengji" / "engine" / "round.py").write_text("# synthetic\n")
    (source / "shengji" / "engine" / "libfast.so").write_bytes(b"synthetic-native")
    return source


def _fake_capture_context(tmp_path, monkeypatch):
    _fast_env(monkeypatch)
    source = _source(tmp_path)
    dependency = tmp_path / "external" / "numpy-core.py"
    dependency.parent.mkdir()
    dependency.write_text("# synthetic dependency\n")
    origins = {"shengji.synthetic": (object(), str(source / "shengji" / "__init__.py"))}
    dependencies = {str(dependency): file_stamp(dependency)}
    preload_calls = []
    monkeypatch.setattr(runtime, "preload",
                        lambda path, **kwargs: preload_calls.append(Path(path)))
    monkeypatch.setattr(runtime, "_origins", lambda path: origins)
    monkeypatch.setattr(runtime, "_dependencies", lambda path: dependencies)
    external = {"source_root": str(source),
                "imports": list(runtime.PRELOAD_IMPORTS),
                "synthetic": True}
    monkeypatch.setattr(runtime.runtime_fence, "capture",
                        lambda path, imports: copy.deepcopy(external))
    monkeypatch.setattr(runtime.runtime_fence, "_maps_snapshot", lambda path: {})
    return source, dependency, origins, dependencies, preload_calls


def _capture_manifest(tmp_path, monkeypatch):
    source, dependency, origins, dependencies, preload_calls = \
        _fake_capture_context(tmp_path, monkeypatch)
    before = sorted(str(path.relative_to(source)) for path in source.rglob("*"))
    manifest = runtime.capture(source)
    assert sorted(str(path.relative_to(source)) for path in source.rglob("*")) == before
    return manifest, source, dependency, origins, dependencies, preload_calls


def test_capture_is_import_only_and_binds_source_external_and_dependencies(
    tmp_path, monkeypatch,
):
    manifest, source, dependency, _, _, preload_calls = _capture_manifest(
        tmp_path, monkeypatch)

    assert manifest["schema"] == "shengji-m9-runtime-v1"
    assert manifest["source_root"] == str(source)
    assert set(manifest["source_files"]) == {
        "shengji/__init__.py", "shengji/engine/round.py", "shengji/engine/libfast.so",
    }
    assert all(not Path(path).is_absolute() for path in manifest["source_files"])
    assert manifest["source_files"]["shengji/engine/libfast.so"] == hashlib.sha256(
        b"synthetic-native").hexdigest()
    assert manifest["dependency_files"] == {
        str(dependency): runtime._sha(dependency),
    }
    assert manifest["external_runtime"]["imports"] == list(runtime.PRELOAD_IMPORTS)
    assert preload_calls == [source]
    assert set((source / "shengji").iterdir()) == {
        source / "shengji" / "__init__.py", source / "shengji" / "engine",
    }


def test_fixed_preload_import_surface_is_exact():
    assert runtime.PRELOAD_IMPORTS == (
        "shengji.eval.observation_admission",
        "shengji.eval.observation_queue",
        "scripts.tactical_report",
        "shengji.eval.observation_process",
        "shengji.eval.observation_recipe",
        "shengji.eval.observation_lease",
        "shengji.train.pv_search_policy",
        "shengji.train.policy_prior",
        "shengji.train.ballot_opportunity",
        "shengji.ai.cwv_numpy",
        "shengji.ai.cwv_prior_numpy",
        "shengji.ai.cwv_policy",
        "shengji.ai.refusal",
        "encodings.cp437",
    )


def test_panel_profile_capture_and_admission_require_same_explicit_profile(tmp_path, monkeypatch):
    source, _, _, _, _ = _fake_capture_context(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(runtime, "preload", lambda path, **kw: seen.append(kw["profile"]))
    monkeypatch.setattr(runtime.runtime_fence, "capture", lambda path, imports: {
        "source_root": str(path), "imports": imports})
    manifest = runtime.capture(source, profile="panel")
    assert manifest["external_runtime"]["imports"] == list(runtime.PANEL_PRELOAD_IMPORTS)
    assert runtime.PANEL_PRELOAD_IMPORTS == runtime.PRELOAD_IMPORTS + (
        "shengji.eval.m9_panel_persistence", "shengji.eval.m9_panel_readout")
    monkeypatch.setattr(runtime, "_routes", lambda path: None)
    monkeypatch.setattr(runtime.runtime_fence, "RuntimeFence",
                        lambda *args: SimpleNamespace(check=lambda: True))
    assert runtime.ObservationRuntime(manifest, profile="panel").check()
    assert seen == ["panel", "panel"]
    with pytest.raises(ValueError, match="import/source binding"):
        runtime.ObservationRuntime(manifest)  # no silent inference or fallback
    old = copy.deepcopy(manifest)
    old["external_runtime"]["imports"] = list(runtime.PRELOAD_IMPORTS)
    with pytest.raises(ValueError, match="import/source binding"):
        runtime.ObservationRuntime(old, profile="panel")


@pytest.mark.parametrize("profile", [None, True, "auto", "", []])
def test_unknown_profile_refused_before_filesystem_access(profile):
    for function in (runtime.preload, runtime.capture, runtime.ObservationRuntime):
        with pytest.raises(ValueError, match="runtime profile"):
            function(None, profile=profile)


def test_real_panel_import_surface_does_not_construct_models():
    source = Path(runtime.__file__).resolve().parents[2]
    script = '''
import importlib, sys
sys.path.insert(0, sys.argv[1])
from shengji.train import pv_search_policy as pv
def forbidden(*args, **kwargs):
    raise AssertionError("model factory invoked during preload")
pv.make_pv_search_bot = forbidden
from shengji.eval.observation_runtime import PANEL_PRELOAD_IMPORTS
for name in PANEL_PRELOAD_IMPORTS:
    importlib.import_module(name)
assert "shengji.eval.m9_panel_worker" in sys.modules
assert "shengji.eval.public_refusal_tape" in sys.modules
assert "shengji.eval.fixed_tape_capture" in sys.modules
assert "torch" not in sys.modules
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(source)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_observation_runtime_admission_hashes_before_preload_and_checks_without_rehash(
    tmp_path, monkeypatch,
):
    manifest, source, _, origins, dependencies, preload_calls = _capture_manifest(
        tmp_path, monkeypatch)
    class Fence:
        def __init__(self, value, path):
            assert value == manifest["external_runtime"]
            assert path == source
        def check(self):
            return True
    monkeypatch.setattr(runtime.runtime_fence, "RuntimeFence", Fence)
    monkeypatch.setattr(runtime, "_routes", lambda path: None)

    admitted = runtime.ObservationRuntime(manifest)
    assert preload_calls == [source, source]
    monkeypatch.setattr(runtime, "_sha", lambda path: pytest.fail("check rehashed"))
    assert admitted.check() is True
    assert admitted.source == source
    assert admitted.origins == origins
    assert admitted.deps == dependencies


@pytest.mark.parametrize("mutation", ["source", "extra", "dependency", "module"])
def test_source_extra_dependency_and_module_drift_are_detected(
    tmp_path, monkeypatch, mutation,
):
    manifest, source, dependency, origins, _, _ = _capture_manifest(tmp_path, monkeypatch)
    class Fence:
        def __init__(self, value, path):
            pass
        def check(self):
            return True
    monkeypatch.setattr(runtime.runtime_fence, "RuntimeFence", Fence)
    monkeypatch.setattr(runtime, "_routes", lambda path: None)
    if mutation == "source":
        (source / "shengji" / "engine" / "round.py").write_text("changed\n")
        with pytest.raises(ValueError, match="source hash"):
            runtime.ObservationRuntime(manifest)
        return
    if mutation == "extra":
        (source / "shengji" / "extra.py").write_text("extra\n")
        with pytest.raises(ValueError, match="source file set"):
            runtime.ObservationRuntime(manifest)
        return
    if mutation == "dependency":
        dependency.write_text("changed dependency\n")
        with pytest.raises(ValueError, match="dependency hash"):
            runtime.ObservationRuntime(manifest)
        return

    admitted = runtime.ObservationRuntime(manifest)
    changed = {"shengji.synthetic": (object(), origins["shengji.synthetic"][1])}
    monkeypatch.setattr(runtime, "_origins", lambda path: changed)
    assert admitted.check() is False


@pytest.mark.parametrize("mutation", ["schema", "imports", "escape", "dependency"])
def test_bad_manifest_schema_importset_and_paths_refuse(tmp_path, monkeypatch, mutation):
    manifest, source, dependency, _, _, _ = _capture_manifest(tmp_path, monkeypatch)
    class Fence:
        def __init__(self, value, path):
            pass
        def check(self):
            return True
    monkeypatch.setattr(runtime.runtime_fence, "RuntimeFence", Fence)
    monkeypatch.setattr(runtime, "preload", lambda path, **kwargs: None)
    monkeypatch.setattr(runtime, "_routes", lambda path: None)
    bad = copy.deepcopy(manifest)
    if mutation == "schema":
        bad["schema"] = "wrong"
    elif mutation == "imports":
        bad["external_runtime"]["imports"] = ["not.shengji"]
    elif mutation == "escape":
        bad["source_root"] = str(source / ".." / source.name)
    else:
        bad["dependency_files"][str(dependency)] = "0" * 64
    with pytest.raises(ValueError):
        runtime.ObservationRuntime(bad)


def test_capture_rejects_source_pyc_and_does_not_publish_or_launch(tmp_path,
                                                                    monkeypatch):
    source = _source(tmp_path)
    (source / "shengji" / "stale.pyc").write_bytes(b"stale")
    _fast_env(monkeypatch)
    monkeypatch.setattr(runtime, "sys", _linux_sys())
    monkeypatch.setattr(runtime, "_origins", lambda path: {})
    monkeypatch.setattr(runtime, "_routes", lambda path: None)
    monkeypatch.setattr(runtime, "runtime_fence", pytest.fail)
    with pytest.raises(ValueError, match="bytecode"):
        runtime.preload(source)
    assert not (source / "runtime.json").exists()


def _linux_sys(modules=None, *, dont_write_bytecode=True):
    return SimpleNamespace(platform="linux", dont_write_bytecode=dont_write_bytecode,
                           flags=SimpleNamespace(isolated=1),
                           modules=sys.modules if modules is None else modules,
                           path=list(sys.path))


def _fast_env(monkeypatch):
    for key in tuple(os.environ):
        if key.startswith(("SHENGJI_", "PYTHON", "OMP_", "OPENBLAS_", "MKL_",
                           "VECLIB_", "NUMEXPR_", "LC_", "LD_", "DYLD_",
                           "BLIS_", "GOTO_", "KMP_")):
            monkeypatch.delenv(key, raising=False)
    for key, value in runtime.ENVIRONMENT.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize("key", [
    "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "BLIS_NUM_THREADS",
    "GOTO_NUM_THREADS", "KMP_AFFINITY",
])
def test_synthetic_environment_isolates_host_overrides(monkeypatch, key):
    monkeypatch.setenv(key, "host-setting")
    _fast_env(monkeypatch)
    assert key not in os.environ
    assert runtime._environment() == runtime.ENVIRONMENT
    # Isolation belongs to the fixture; the real runtime must still refuse it.
    monkeypatch.setenv(key, "host-setting")
    with pytest.raises(ValueError, match="unapproved runtime override: " + key):
        runtime._environment()


@pytest.mark.parametrize("dont_write", [False, True])
def test_preload_and_routes_require_explicit_b_flag(tmp_path, monkeypatch, dont_write):
    source = _source(tmp_path)
    _fast_env(monkeypatch)
    monkeypatch.setattr(runtime, "sys", _linux_sys(dont_write_bytecode=dont_write))
    monkeypatch.setattr(runtime, "_origins", lambda path: {})
    monkeypatch.setattr(runtime, "_routes", lambda path: None)
    if dont_write:
        # The import route is stubbed; only the preload guard is under test.
        monkeypatch.setattr(runtime, "importlib", SimpleNamespace(
            invalidate_caches=lambda: None,
            import_module=lambda name: None,
        ))
        runtime.preload(source)
    else:
        with pytest.raises(ValueError, match="bytecode"):
            runtime.preload(source)


def test_foreign_origin_and_torch_guards_use_isolated_module_proxy(tmp_path, monkeypatch):
    source = _source(tmp_path)
    foreign = SimpleNamespace(__file__=str(tmp_path / "foreign.py"))
    (tmp_path / "foreign.py").write_text("foreign\n")
    monkeypatch.setattr(runtime, "sys", _linux_sys({"shengji.foreign": foreign}))
    with pytest.raises(ValueError, match="escaped source"):
        runtime._origins(source)

    monkeypatch.setattr(runtime, "sys", _linux_sys({"torch": object()}))
    with pytest.raises(ValueError, match="torch forbidden"):
        runtime._origins(source)


def test_native_route_guard_requires_callable_bound_routes(tmp_path, monkeypatch):
    source = _source(tmp_path)
    round_play = lambda *args: None
    native = SimpleNamespace(round_play=round_play)
    fast = SimpleNamespace(HAVE_FAST=True, _fast=native, decompose=lambda *a: None)
    combos = SimpleNamespace(decompose=fast.decompose)
    round_module = SimpleNamespace(Round=SimpleNamespace(play=round_play))
    numpy_model = SimpleNamespace(_native_erf=lambda value: value)
    modules = {
        "shengji.engine.fast": fast,
        "shengji.engine.combos": combos,
        "shengji.engine.round": round_module,
        "shengji.ai.cwv_numpy": numpy_model,
    }
    _fast_env(monkeypatch)
    monkeypatch.setattr(runtime, "sys", _linux_sys(modules))
    monkeypatch.setattr(runtime, "_origins", lambda path: {})
    runtime._routes(source)
    runtime.sys.dont_write_bytecode = False
    with pytest.raises(ValueError, match="bytecode"):
        runtime._routes(source)
    runtime.sys.dont_write_bytecode = True
    combos.decompose = lambda *args: None
    with pytest.raises(ValueError, match="native M9 routes"):
        runtime._routes(source)


def test_dependency_enumeration_records_external_python_cache_and_native_files(
    tmp_path, monkeypatch,
):
    source = _source(tmp_path)
    external_py = tmp_path / "external" / "package.py"
    external_pyc = tmp_path / "external" / "package.pyc"
    external_so = tmp_path / "external" / "libnative.so"
    external_py.parent.mkdir()
    external_py.write_text("external\n")
    external_pyc.write_bytes(b"pyc")
    external_so.write_bytes(b"native")
    source_module = SimpleNamespace(__file__=str(source / "shengji" / "__init__.py"),
                                    __cached__=None)
    external_module = SimpleNamespace(__file__=str(external_py),
                                      __cached__=str(external_pyc))
    native_module = SimpleNamespace(__file__=str(external_so), __cached__=None)
    modules = {"shengji.synthetic": source_module, "external": external_module,
               "external.native": native_module}
    monkeypatch.setattr(runtime, "sys", _linux_sys(modules))
    deps = runtime._dependencies(source)
    assert set(deps) == {str(external_py), str(external_pyc), str(external_so)}
    assert deps[str(external_py)] == file_stamp(external_py)
    before = deps[str(external_py)]
    external_py.write_text("changed\n")
    assert runtime._dependencies(source)[str(external_py)] != before


@pytest.mark.parametrize("key,value", [
    ("SHENGJI_PV_WORLDS", "1"), ("OPENBLAS_NUM_THREADS", "2"),
    ("LC_ALL", "C"), ("PYTHONPATH", "/foreign"), ("LD_PRELOAD", "/foreign.so"),
])
def test_environment_override_refused(monkeypatch, key, value):
    _fast_env(monkeypatch)
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        runtime._environment()


def test_isolated_interpreter_required_before_preload(tmp_path, monkeypatch):
    source = _source(tmp_path)
    _fast_env(monkeypatch)
    fake_sys = _linux_sys()
    fake_sys.flags.isolated = 0
    monkeypatch.setattr(runtime, "sys", fake_sys)
    monkeypatch.setattr(runtime.importlib, "import_module",
                        lambda name: pytest.fail("import before isolation check"))
    with pytest.raises(ValueError, match="isolated"):
        runtime.preload(source)


def test_inventory_excludes_venv_but_includes_scripts(tmp_path):
    source = _source(tmp_path)
    (source / "scripts" / "worker.py").write_text("# worker\n")
    (source / ".venv").mkdir()
    (source / ".venv" / "external.pyc").write_bytes(b"not application bytecode")
    inventory = runtime.source_stat_inventory(source)
    assert "scripts/worker.py" in inventory
    assert not any(name.startswith(".venv/") for name in inventory)


def test_mapped_uninventoried_source_library_refused(tmp_path, monkeypatch):
    source = _source(tmp_path)
    inventory = runtime.source_stat_inventory(source)
    native = source / "shengji" / "engine" / "libfast.so"
    monkeypatch.setattr(runtime.runtime_fence, "_maps_snapshot", lambda path: {str(native): None})
    runtime._mapped_source_coverage(source, inventory)
    monkeypatch.setattr(runtime.runtime_fence, "_maps_snapshot",
                        lambda path: {str(source / ".venv" / "libpython.so"): None})
    with pytest.raises(ValueError, match="outside application inventory"):
        runtime._mapped_source_coverage(source, inventory)


def test_venv_module_under_source_is_still_an_external_dependency(tmp_path, monkeypatch):
    source = _source(tmp_path)
    external = source / ".venv" / "package.py"
    external.parent.mkdir()
    external.write_text("# external\n")
    monkeypatch.setattr(runtime, "sys", _linux_sys({
        "external": SimpleNamespace(__file__=str(external), __cached__=None),
    }))
    assert str(external) in runtime._dependencies(source)


def test_manifest_origin_and_environment_binding(tmp_path, monkeypatch):
    manifest, source, _, _, _, _ = _capture_manifest(tmp_path, monkeypatch)
    manifest["environment"]["LC_ALL"] = "C"
    with pytest.raises(ValueError, match="environment"):
        runtime.ObservationRuntime(manifest)
    manifest["environment"] = dict(runtime.ENVIRONMENT)
    manifest["module_origins"] = {}
    with pytest.raises(ValueError, match="origin map"):
        runtime.ObservationRuntime(manifest)


@pytest.mark.parametrize("traversal", [True, False])
def test_application_origin_must_be_canonical_and_in_inventoried_code(
        tmp_path, monkeypatch, traversal):
    source = _source(tmp_path)
    (source / "sub").mkdir()
    foreign = tmp_path / "foreign.py"
    foreign.write_text("# not application source\n")
    if traversal:
        origin = str(source / "sub" / ".." / ".." / "foreign.py")
    else:
        untracked = source / "sub" / "extra.py"
        untracked.write_text("# outside managed directories\n")
        origin = str(untracked)
    monkeypatch.setattr(runtime, "sys", _linux_sys({
        "shengji.foreign": SimpleNamespace(__file__=origin),
    }))
    with pytest.raises(ValueError, match="canonical|outside source inventory"):
        runtime._origins(source)
