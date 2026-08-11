from __future__ import annotations

import signal
import sys
from pathlib import Path

import pytest

import teacher_stage_c_expanded_label_supervisor as SUP


def _config(tmp_path: Path) -> SUP.Config:
    return SUP.Config(
        expected_git="a" * 40,
        packet_path=tmp_path / "packet.json",
        expected_packet_sha256="b" * 64,
        review_record=tmp_path / "review.md",
        receipt_path=tmp_path / "receipt.json",
        expected_receipt_sha256="c" * 64,
    )


def _packet() -> dict:
    shards = []
    commands = []
    outputs = []
    for index in range(16):
        split = "DESIGN" if index < 12 else "CALIB"
        output = f"server/runs/logs/test/{split.lower()}/{index:02d}.json"
        outputs.append(output)
        shards.append({"index": index, "split": split})
        commands.append({
            "index": index,
            "split": split,
            "command": ["{python}", "worker.py", "{git}",
                        "{packet_sha256}", "{controller_review_record}",
                        "{receipt_sha256}"],
        })
    return {
        "schedule": {"shards": shards},
        "commands": {
            "run_shards": commands,
            "aggregate": ["{python}", "aggregate.py", "{git}"],
        },
        "result_contract": {
            "shards": outputs,
            "aggregate": "server/runs/logs/test/aggregate.json",
        },
    }


def test_shard_specs_expand_exact_two_wave_population(tmp_path: Path) -> None:
    config = _config(tmp_path)
    specs = SUP.shard_specs(_packet(), config)
    assert len(specs) == 16
    assert [spec.index for spec in specs] == list(range(16))
    assert specs[0].argv[0] == str(Path(__import__("sys").executable))
    assert specs[0].argv[2:] == (
        "a" * 40, "b" * 64, str(config.review_record), "c" * 64)
    assert len({spec.output for spec in specs}) == 16


def test_expand_command_refuses_unresolved_or_non_string_token(
        tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(SUP.ExpandedSupervisorRefused, match="unresolved"):
        SUP.expand_command(["{unknown}"], config)
    with pytest.raises(SUP.ExpandedSupervisorRefused, match="token drift"):
        SUP.expand_command([1], config)


def test_signal_is_deferred_through_spawn_window() -> None:
    owner = SUP.SignalOwner()
    with pytest.raises(SUP.ExpandedSupervisorInterrupted) as error:
        with owner.deferred_until_registered():
            owner._handle(signal.SIGTERM, None)
    assert error.value.signal_name == "SIGTERM"
    assert owner.spawning is False


def test_signal_owner_terminates_registered_real_child(
        tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(SUP, "REPO", tmp_path)
    spec = SUP.JobSpec(
        name="sleep", index=0,
        argv=(sys.executable, "-c", "import time; time.sleep(60)"),
        output=tmp_path / "unused.json",
        log_final=tmp_path / "sleep.log",
        exit_final=tmp_path / "sleep-exit.json",
    )
    job = None
    with pytest.raises(SUP.ExpandedSupervisorInterrupted):
        with SUP.SignalOwner() as owner:
            job = SUP._start_job(spec, owner)
            owner._handle(signal.SIGTERM, None)
    assert job is not None
    assert job.process.poll() is not None
    assert spec.log_final.is_file()
    assert spec.exit_final.is_file()
