import importlib.util
import json
import os
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("receipt_summary", Path(__file__).parents[1] / "scripts/receipt_summary.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_bounded_projection():
    manifest = {"path": "x" * 10000, "schema": {"secret": "hidden"}, "sha256": "a" * 64}
    value = {"data": [{"root": "r", "manifests": [manifest] * 100}] * 100,
             "init": {"sha256": "b" * 64, "exposure": ["HIDDEN"] * 1000},
             "exposure": ["HIDDEN"] * 1000}
    result = module.summarize(value)
    assert result["data_count"] == 100
    assert result["data_omitted"] == 95
    assert result["data"][0]["manifests_omitted"] == 95
    assert len(result["data"][0]["manifests"][0]["path"]) == 240
    assert result["data"][0]["manifests"][0]["schema"] is None
    assert result["init_sha256"] == "b" * 64
    assert "HIDDEN" not in json.dumps(result)
    assert len(json.dumps(result)) < 12000


@pytest.mark.parametrize("value", [{}, {"data": None}, {"data": [None, {"manifests": [None]}], "init": []}])
def test_malformed_optional_shapes(value):
    assert isinstance(module.summarize(value), dict)


def test_input_limit_before_parse(tmp_path):
    path = tmp_path / "receipt.json"
    path.write_text("not json" * 100)
    with pytest.raises(ValueError, match="exceeds input limit"):
        module.read_summary(path, 10)


@pytest.mark.parametrize("text", ["not json SECRET", "[]", "null"])
def test_cli_refuses_without_echo(tmp_path, capsys, text):
    path = tmp_path / "receipt.json"
    path.write_text(text)
    assert module.main([str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "SECRET" not in captured.err


def test_regular_file_and_cli(tmp_path, capsys):
    path = tmp_path / "receipt.json"
    path.write_text('{"init":{"sha256":"abc"}}')
    assert module.main([str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["init_sha256"] == "abc"
    with pytest.raises(ValueError):
        module.read_summary(path, 0)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="regular file"):
        module.read_summary(fifo)
