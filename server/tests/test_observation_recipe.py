"""Pure contract tests for the M9 observation command binding."""

import pytest

from shengji.eval.observation_recipe import (
    FIXTURE_SHA256,
    MODEL_SHA256,
    build_observation_command,
)


def recipe(tmp_path):
    return {
        "python": "/opt/venv/bin/python",
        "source_root": "/srv/shengji",
        "model": "/srv/models/smv3.npz",
        "fixtures": "/srv/shengji/server/tests/tactical/public_observations.jsonl",
        "output": str(tmp_path / "comparison.json"),
        "evidence": str(tmp_path / "evidence"),
        "seeds": [0, 1, 2],
        "fill_seed": 0,
        "timeout_seconds": 600,
        "model_sha256": MODEL_SHA256,
        "fixture_sha256": FIXTURE_SHA256,
    }


def test_exact_argv_and_immutable_copy(tmp_path):
    spec = recipe(tmp_path)
    command = build_observation_command(spec)
    assert command == (
        "/opt/venv/bin/python", "-I", "-B",
        "/srv/shengji/server/scripts/tactical_report.py",
        "--compare-observations", "--ckpt", "/srv/models/smv3.npz", "--sha256",
        MODEL_SHA256, "--fixtures",
        "/srv/shengji/server/tests/tactical/public_observations.jsonl",
        "--compare-seeds", "0,1,2", "--compare-fill-seed", "0", "--json",
        str(tmp_path / "comparison.json"),
    )
    spec["seeds"][:] = [9]
    spec["output"] = "/elsewhere/changed.json"
    assert command[-1] == str(tmp_path / "comparison.json")
    assert isinstance(command, tuple)


@pytest.mark.parametrize("field,value", [
    ("seeds", [2, 1, 0]), ("seeds", [0, 1, 1]),
    ("seeds", [0, 1]), ("seeds", [False, 1, 2]), ("fill_seed", True),
    ("timeout_seconds", True), ("timeout_seconds", 599),
    ("model_sha256", "0" * 64), ("fixture_sha256", "0" * 64),
])
def test_pinned_values_cannot_be_mutated(tmp_path, field, value):
    spec = recipe(tmp_path)
    spec[field] = value
    with pytest.raises(ValueError):
        build_observation_command(spec)


def test_unknown_key_is_rejected(tmp_path):
    spec = recipe(tmp_path)
    spec["argv"] = ["--unsafe"]
    with pytest.raises(ValueError):
        build_observation_command(spec)


@pytest.mark.parametrize("field,value", [
    ("python", "python"), ("model", "/srv/models/../model.npz"),
    ("fixtures", "/"), ("output", "/srv/shengji/server/results/../x.json"),
    ("output", "//tmp/results.json"), ("model", "/models/a\x00.npz"),
])
def test_paths_are_absolute_normalized_and_non_root(tmp_path, field, value):
    spec = recipe(tmp_path)
    spec[field] = value
    with pytest.raises(ValueError):
        build_observation_command(spec)


@pytest.mark.parametrize("output,evidence", [
    ("/srv/shengji/server/tests/tactical/out.json", "/srv/shengji/evidence"),
    ("/tmp/result.json", "/tmp/result.json"),
    ("/tmp/result.json", "/tmp/result.json.attempt"),
    ("/tmp/result.json", "/tmp/.result.json.partial"),
    ("/tmp/result.json", "/srv/shengji/evidence"),
])
def test_publication_paths_do_not_overlap_inputs_or_evidence(tmp_path, output, evidence):
    spec = recipe(tmp_path)
    spec["output"], spec["evidence"] = output, evidence
    with pytest.raises(ValueError):
        build_observation_command(spec)
