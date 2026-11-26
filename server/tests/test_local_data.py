"""`local_data`: the skip for absent untracked inputs never covers a tracked file."""

from __future__ import annotations

import subprocess

import pytest

import local_data
from local_data import LOCAL_DATA, SERVER, absent_local_data, require_local_data


@pytest.mark.parametrize("path", sorted(LOCAL_DATA))
def test_every_local_data_path_is_ignored_and_untracked(path):
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", path], cwd=SERVER,
                             capture_output=True, text=True)
    assert tracked.returncode != 0, f"{path} is tracked; a test must not skip on it"
    ignored = subprocess.run(["git", "check-ignore", "-q", path], cwd=SERVER)
    assert ignored.returncode == 0, f"{path} is not gitignored"


def test_an_absent_local_input_skips_and_names_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(local_data, "SERVER", tmp_path)
    with pytest.raises(pytest.skip.Exception, match="server/rl_data/highn_late_air.jsonl"):
        require_local_data("rl_data/highn_late_air.jsonl")


def test_a_missing_repository_input_fails_instead_of_skipping(tmp_path, monkeypatch):
    monkeypatch.setattr(local_data, "SERVER", tmp_path)
    with pytest.raises(AssertionError, match="is not untracked local data"):
        absent_local_data("rl_data/corpus_split.v1.json")


def test_present_inputs_run(tmp_path, monkeypatch):
    monkeypatch.setattr(local_data, "SERVER", tmp_path)
    (tmp_path / "rl_data").mkdir()
    (tmp_path / "rl_data" / "highn_corpus_all.jsonl").write_text("")
    (tmp_path / "rl_data" / "corpus_split.v1.json").write_text("")
    require_local_data("rl_data/highn_corpus_all.jsonl", "rl_data/corpus_split.v1.json")
