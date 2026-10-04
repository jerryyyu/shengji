from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from shengji.eval.m9_panel_plan import ROOTS
from shengji.eval.m9_panel_inputs import load_panel_inputs
from shengji.eval import m9_panel_inputs, m9_panel_recipe
from test_m9_panel_readout import _analysis_and_actions


FIXTURE_SOURCE = Path(__file__).parent / "tactical" / "public_observations.jsonl"
MAX_INPUT_BYTES = 8 * 1024 * 1024


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _analysis():
    # Do not allocate fifteen unused full-pool capture matrices per loader test.
    return _analysis_and_actions()[0]


def _saved_bytes(analysis=None) -> bytes:
    return json.dumps(
        {"analysis": _analysis() if analysis is None else analysis,
         "provenance": {}},
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _recipe(tmp_path: Path, saved: Path, fixtures: Path) -> dict[str, object]:
    return {
        "schema": m9_panel_recipe.SCHEMA,
        "python": "/env/bin/python",
        "source_root": str(tmp_path / "source"),
        "model": str(tmp_path / "model.npz"),
        "fixtures": str(fixtures),
        "saved_readout": str(saved),
        "output_dir": str(tmp_path / "output"),
        "evidence": str(tmp_path / "evidence.json"),
        "model_sha256": m9_panel_recipe.MODEL_SHA256,
        "fixture_sha256": m9_panel_recipe.FIXTURE_SHA256,
        "saved_readout_sha256": m9_panel_recipe.SAVED_READOUT_SHA256,
        "seeds": [0, 1, 2],
        "fill_seed": 0,
        "runtime_profile": "panel",
        "policy": m9_panel_recipe.POLICY,
    }


def _pin_hashes(monkeypatch, saved: bytes, fixtures: bytes) -> None:
    monkeypatch.setattr(m9_panel_recipe, "SAVED_READOUT_SHA256", _sha(saved))
    monkeypatch.setattr(m9_panel_recipe, "FIXTURE_SHA256", _sha(fixtures))


def _valid_inputs(monkeypatch, tmp_path: Path, *, analysis=None):
    saved_bytes = _saved_bytes(analysis)
    fixture_bytes = FIXTURE_SOURCE.read_bytes()
    saved = tmp_path / "readout.json"
    fixtures = tmp_path / "fixtures.jsonl"
    saved.write_bytes(saved_bytes)
    fixtures.write_bytes(fixture_bytes)
    _pin_hashes(monkeypatch, saved_bytes, fixture_bytes)
    return _recipe(tmp_path, saved, fixtures), saved, fixtures, saved_bytes, fixture_bytes


def test_load_authenticates_both_inputs_and_preflights_the_fixed_population(
        monkeypatch, tmp_path):
    recipe, saved, fixtures, saved_bytes, fixture_bytes = _valid_inputs(
        monkeypatch, tmp_path)

    loaded = load_panel_inputs(recipe)

    assert loaded.input_sha256 == {
        "saved_readout": _sha(saved_bytes),
        "fixtures": _sha(fixture_bytes),
    }
    assert set(loaded.analysis) == {
        "schema", "seeds", "fill_seed", "checkpoint_sha256", "roots",
    }
    assert {fixture.id for fixture in loaded.fixtures} == set(ROOTS)
    assert len(loaded.fixtures) == 4
    assert all(fixture.category == "observation" for fixture in loaded.fixtures)
    assert all(fixture.current_bot is None for fixture in loaded.fixtures)
    assert loaded.check_unchanged() is None
    assert saved.is_file() and fixtures.is_file()


def test_load_detaches_analysis_and_fixture_objects(monkeypatch, tmp_path):
    recipe, _, _, _, _ = _valid_inputs(monkeypatch, tmp_path)
    loaded = load_panel_inputs(recipe)

    loaded.analysis["roots"][0]["id"] = "mutated"
    loaded.fixtures[0].hand[0] = "D6"
    again = load_panel_inputs(recipe)
    assert again.analysis["roots"][0]["id"] in ROOTS
    assert again.fixtures[0].hand[0] != "D6"


def test_check_unchanged_detects_drift_and_missing_inputs(monkeypatch, tmp_path):
    recipe, saved, fixtures, _, _ = _valid_inputs(monkeypatch, tmp_path)
    loaded = load_panel_inputs(recipe)

    saved.write_bytes(saved.read_bytes() + b"\n")
    with pytest.raises(ValueError):
        loaded.check_unchanged()

    recipe, saved, fixtures, _, _ = _valid_inputs(monkeypatch, tmp_path)
    loaded = load_panel_inputs(recipe)
    fixtures.unlink()
    with pytest.raises(ValueError):
        loaded.check_unchanged()

    fixtures.unlink(missing_ok=True)
    with pytest.raises(ValueError):
        load_panel_inputs(recipe)


@pytest.mark.parametrize("which", ["saved_readout", "fixtures"])
def test_symlink_inputs_are_refused(monkeypatch, tmp_path, which):
    recipe, saved, fixtures, saved_bytes, fixture_bytes = _valid_inputs(
        monkeypatch, tmp_path)
    target = saved if which == "saved_readout" else fixtures
    link = tmp_path / (target.name + ".link")
    target.rename(link)
    target.symlink_to(link)
    _pin_hashes(monkeypatch, saved_bytes, fixture_bytes)
    with pytest.raises(ValueError):
        load_panel_inputs(recipe)


def test_bounded_input_reads_refuse_an_oversize_saved_readout(monkeypatch, tmp_path):
    fixture_bytes = FIXTURE_SOURCE.read_bytes()
    saved_bytes = b"{" + b" " * MAX_INPUT_BYTES + b"}"
    saved = tmp_path / "readout.json"
    fixtures = tmp_path / "fixtures.jsonl"
    saved.write_bytes(saved_bytes)
    fixtures.write_bytes(fixture_bytes)
    _pin_hashes(monkeypatch, saved_bytes, fixture_bytes)
    with pytest.raises(ValueError):
        load_panel_inputs(_recipe(tmp_path, saved, fixtures))


@pytest.mark.parametrize("which", ["saved_readout", "fixtures"])
def test_hash_mismatch_happens_before_either_parser(monkeypatch, tmp_path, which):
    recipe, saved, fixtures, saved_bytes, fixture_bytes = _valid_inputs(
        monkeypatch, tmp_path)
    if which == "saved_readout":
        saved.write_bytes(b"{}")
    else:
        fixtures.write_bytes(b"# changed after recipe authentication\n")

    def parser_called(*args, **kwargs):
        raise AssertionError("a hash mismatch must precede parsing either input")

    monkeypatch.setattr(m9_panel_inputs.guards, "_parse_finite_object",
                        parser_called)
    with pytest.raises(ValueError):
        load_panel_inputs(recipe)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"analysis":{},"provenance":{},"analysis":{}}',
        b'{"analysis":{"value":NaN},"provenance":{}}',
        b'{"analysis":{},"provenance":{}}\xff',
    ],
    ids=["duplicate-key", "nonfinite-number", "invalid-utf8"],
)
def test_saved_readout_strict_json_refusals(monkeypatch, tmp_path, payload):
    fixture_bytes = FIXTURE_SOURCE.read_bytes()
    saved = tmp_path / "readout.json"
    fixtures = tmp_path / "fixtures.jsonl"
    saved.write_bytes(payload)
    fixtures.write_bytes(fixture_bytes)
    _pin_hashes(monkeypatch, payload, fixture_bytes)
    with pytest.raises(ValueError):
        load_panel_inputs(_recipe(tmp_path, saved, fixtures))


def test_wrapper_shape_and_analysis_population_are_strict(monkeypatch, tmp_path):
    fixture_bytes = FIXTURE_SOURCE.read_bytes()
    fixtures = tmp_path / "fixtures.jsonl"
    fixtures.write_bytes(fixture_bytes)
    for wrapper in (
            {"analysis": _analysis()},
            {"analysis": _analysis(), "provenance": {}, "extra": True},
            {"analysis": {}, "provenance": {}},
    ):
        saved_bytes = json.dumps(wrapper, allow_nan=False).encode()
        saved = tmp_path / "readout.json"
        saved.write_bytes(saved_bytes)
        _pin_hashes(monkeypatch, saved_bytes, fixture_bytes)
        with pytest.raises(ValueError):
            load_panel_inputs(_recipe(tmp_path, saved, fixtures))


def test_missing_saved_selected_index_is_rejected_during_preflight(monkeypatch,
                                                                    tmp_path):
    analysis = _analysis()
    del analysis["roots"][0]["seeds"][0]["control"]["decision"]["selected_index"]
    recipe, _, _, _, _ = _valid_inputs(monkeypatch, tmp_path, analysis=analysis)
    with pytest.raises(ValueError, match="choice/index mapping invalid"):
        load_panel_inputs(recipe)


@pytest.mark.parametrize("payload,pattern", [
    (b'{"schema":"x","schema":"x"}', "duplicate JSON key"),
    (b'{"value":1e999}', "nonfinite JSON number"),
    (b'\xff', "utf-8"),
])
def test_repinned_fixture_json_is_strict(monkeypatch, tmp_path, payload, pattern):
    recipe, _, fixtures, saved_bytes, _ = _valid_inputs(monkeypatch, tmp_path)
    fixtures.write_bytes(payload)
    _pin_hashes(monkeypatch, saved_bytes, payload)
    recipe["fixture_sha256"] = _sha(payload)
    with pytest.raises(ValueError, match=pattern):
        load_panel_inputs(recipe)


def test_fixture_population_and_observation_metadata_are_exact(monkeypatch,
                                                                tmp_path):
    saved_bytes = _saved_bytes()
    source_lines = FIXTURE_SOURCE.read_bytes().splitlines(keepends=True)
    fixture_bytes = b"\n# ignored by the loader\n" + b"".join(source_lines)
    saved = tmp_path / "readout.json"
    fixtures = tmp_path / "fixtures.jsonl"
    saved.write_bytes(saved_bytes)
    fixtures.write_bytes(fixture_bytes)
    _pin_hashes(monkeypatch, saved_bytes, fixture_bytes)
    loaded = load_panel_inputs(_recipe(tmp_path, saved, fixtures))
    assert len(loaded.fixtures) == 4

    fixture_bytes = b"\n# ignored by the loader\n" + b"".join(source_lines[:3])
    fixtures.write_bytes(fixture_bytes)
    _pin_hashes(monkeypatch, saved_bytes, fixture_bytes)
    with pytest.raises(ValueError):
        load_panel_inputs(_recipe(tmp_path, saved, fixtures))

    bad_row = source_lines[0].replace(b'"current_bot":null', b'"current_bot":"fail"')
    fixture_bytes = bad_row + b"".join(source_lines[1:])
    fixtures.write_bytes(fixture_bytes)
    _pin_hashes(monkeypatch, saved_bytes, fixture_bytes)
    with pytest.raises(ValueError):
        load_panel_inputs(_recipe(tmp_path, saved, fixtures))


def test_loader_does_not_construct_a_model_or_run_a_bot(monkeypatch, tmp_path):
    recipe, _, _, _, _ = _valid_inputs(monkeypatch, tmp_path)
    from shengji.train import pv_search_policy as pv

    def forbidden(*args, **kwargs):
        raise AssertionError("panel input loading cannot construct or run a model")

    monkeypatch.setattr(pv, "pv_registry_entries", forbidden)
    loaded = load_panel_inputs(recipe)
    assert loaded.input_sha256["saved_readout"]
