"""Per-entry seed-window files (``runs/seed_windows.d/<name>.json``) are
part of the registry: overlaps with them refuse exactly like overlaps with
``seed_windows.json`` entries, and a malformed, misnamed or duplicate file
refuses the whole registry."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

from shengji import seeds

SERVER = Path(__file__).resolve().parents[1]
COMMITTED = seeds.DEFAULT_REGISTRY


def _cli():
    spec = importlib.util.spec_from_file_location(
        "seed_windows_cli", SERVER / "scripts" / "seed_windows.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def registry() -> Path:
    """A scratch copy of the committed registry file (no directory yet)."""
    path = Path(os.environ["SHENGJI_SEED_WINDOWS"])
    shutil.copy(COMMITTED, path)
    return path


def _clear_seed0() -> int:
    """A seed0 above every committed window."""
    return max(seeds.span_of(w)[1] for w in seeds.load(COMMITTED)["windows"]) + 1_000


def _entry(name: str, seed0: int, clusters: int = 500, purpose: str = "trajectory") -> dict:
    return seeds.make_entry(name=name, purpose=purpose, seed0=seed0, clusters=clusters,
                            note="test", created_at="2026-11-03T00:00:00+0000",
                            host="test-host", git_head_sha="0" * 40)


def _write(registry: Path, entry, filename: str | None = None) -> Path:
    directory = registry.with_name(registry.stem + ".d")
    directory.mkdir(exist_ok=True)
    target = directory / (filename or f"{entry['name']}.json")
    target.write_text(entry if isinstance(entry, str) else json.dumps(entry, indent=2) + "\n")
    return target


def _check(registry: Path, seed0: int, clusters: int, purpose: str = "trajectory") -> int:
    return _cli().main(["--registry", str(registry), "check", str(seed0), str(clusters),
                        "--purpose", purpose])


def test_registry_dir_sits_beside_the_registry_file(registry):
    assert seeds.registry_dir(COMMITTED) == COMMITTED.parent / "seed_windows.d"
    assert seeds.registry_dir(registry) == registry.parent / "seed_windows.d"


def test_committed_dir_entries_load_and_keep_the_file_entries_first():
    on_disk = json.loads(COMMITTED.read_text())["windows"]
    loaded = seeds.load(COMMITTED)["windows"]
    assert loaded[:len(on_disk)] == on_disk
    assert [w["name"] for w in loaded[len(on_disk):]] == [
        w["name"] for w in seeds.load_dir(seeds.registry_dir(COMMITTED))]


def test_dir_entry_clear_of_all_passes_then_refuses_its_own_window(registry, capsys):
    seed0 = _clear_seed0()
    assert _check(registry, seed0, 500) == 0
    _write(registry, _entry("dir-run-clear", seed0))

    assert _check(registry, seed0, 500) == 2
    assert _check(registry, seed0 + 499, 10, purpose="screen") == 2
    assert "dir-run-clear" in capsys.readouterr().out
    with pytest.raises(seeds.SeedWindowError, match="dir-run-clear"):
        seeds.check_and_register(name="other-run", purpose="trajectory", seed0=seed0 + 10,
                                 clusters=5, refuse=None)
    assert _check(registry, seed0 + 500, 500) == 0


def test_dir_entry_overlapping_a_file_entry_is_refused_on_both(registry, capsys):
    run_c = seeds.find(seeds.load(registry), "run-C")
    _write(registry, _entry("dir-run-over-c", run_c["seed0"] + 100, clusters=50))

    assert _check(registry, run_c["seed0"] + 120, 5) == 2
    out = capsys.readouterr().out
    assert "run-C" in out and "dir-run-over-c" in out
    hits = seeds.overlaps(seeds.load(registry), run_c["seed0"] + 120, 5)
    assert {h["name"] for h in hits} == {"run-C", "dir-run-over-c"}


def test_register_appends_to_the_file_and_refuses_a_dir_name(registry):
    seed0 = _clear_seed0()
    _write(registry, _entry("dir-run-a", seed0))
    before = json.loads(registry.read_text())["windows"]

    with pytest.raises(seeds.SeedWindowError, match="already registered"):
        seeds.register(_entry("dir-run-a", seed0), registry)
    seeds.register(_entry("file-run-b", seed0 + 1_000), registry)

    after = json.loads(registry.read_text())["windows"]
    assert [w["name"] for w in after] == [w["name"] for w in before] + ["file-run-b"]
    assert "dir-run-a" not in {w["name"] for w in after}


def test_duplicate_name_across_file_and_dir_refuses(registry, capsys):
    run_a = seeds.find(seeds.load(registry), "run-A")
    _write(registry, _entry("run-A", _clear_seed0()))

    with pytest.raises(seeds.SeedWindowError, match="'run-A' is already registered"):
        seeds.load(registry)
    assert _check(registry, run_a["seed0"], 1) == 2
    assert "REFUSING" in capsys.readouterr().err


@pytest.mark.parametrize("text,match", [
    ("{not json", "not valid JSON"),
    ("[]", "not a window object"),
    ('"run"', "not a window object"),
    ('{"name": "bad-run"}', "lacks"),
])
def test_malformed_dir_file_refuses(registry, text, match, capsys):
    _write(registry, text, filename="bad-run.json")

    with pytest.raises(seeds.SeedWindowError, match=match):
        seeds.load(registry)
    assert _check(registry, _clear_seed0(), 1) == 2
    assert "REFUSING" in capsys.readouterr().err


def test_dir_entry_with_a_bad_span_refuses(registry):
    entry = _entry("bad-span", _clear_seed0())
    entry["span"] = [entry["span"][0], entry["span"][1] + 1]
    _write(registry, entry)

    with pytest.raises(seeds.SeedWindowError, match="span"):
        seeds.load(registry)


def test_filename_must_equal_name(registry, capsys):
    _write(registry, _entry("real-name", _clear_seed0()), filename="other-name.json")

    with pytest.raises(seeds.SeedWindowError, match="filename must be the window name"):
        seeds.load(registry)
    assert _check(registry, _clear_seed0(), 1) == 2


def test_non_json_files_in_the_dir_are_ignored(registry):
    _write(registry, "notes\n", filename="README.md")

    assert seeds.load(registry)["windows"] == json.loads(registry.read_text())["windows"]


def test_dir_files_load_in_filename_order(registry):
    seed0 = _clear_seed0()
    _write(registry, _entry("b-run", seed0))
    _write(registry, _entry("a-run", seed0 + 1_000))

    names = [w["name"] for w in seeds.load(registry)["windows"]]
    assert names[-2:] == ["a-run", "b-run"]


def test_list_counts_dir_entries(registry, capsys):
    _write(registry, _entry("dir-listed", _clear_seed0()))

    assert _cli().main(["--registry", str(registry), "list"]) == 0
    out = capsys.readouterr().out
    assert "(1 from " in out and "dir-listed" in out
