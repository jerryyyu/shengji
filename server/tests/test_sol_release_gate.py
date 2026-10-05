import json
from pathlib import Path

import pytest

from scripts import launch_production_llm_panel as launcher
from test_launch_production_llm_panel import _config, _stub_validation
from test_launch_sol_recovery import _binding, _report, _retention, _controls


EXPECTED = "a" * 64


@pytest.mark.parametrize("kind", ["missing", "wrong", "malformed", "extra_newline", "oversized", "directory", "symlink", "fifo"])
def test_recovery_release_rejects_unsafe_or_wrong_marker(tmp_path, kind):
    config = tmp_path / "config.json"
    config.write_text("{}")
    release = tmp_path / "RELEASE"
    if kind == "wrong":
        release.write_text("b" * 64)
    elif kind == "malformed":
        release.write_text("A" * 64 + "\n\n")
    elif kind == "extra_newline":
        release.write_text(EXPECTED + "\n\n")
    elif kind == "oversized":
        release.write_text(EXPECTED + "x" * 100)
    elif kind == "directory":
        release.mkdir()
    elif kind == "symlink":
        target = tmp_path / "target"
        target.write_text(EXPECTED)
        release.symlink_to(target)
    elif kind == "fifo":
        import os
        os.mkfifo(release)
    with pytest.raises(ValueError, match="RELEASE"):
        launcher._require_recovery_release(config, EXPECTED)


@pytest.mark.parametrize("suffix", ["", "\n"])
def test_recovery_release_accepts_exact_lowercase_config_digest(tmp_path, suffix):
    config = tmp_path / "config.json"
    config.write_text("{}")
    (tmp_path / "RELEASE").write_text(EXPECTED + suffix)
    launcher._require_recovery_release(config, EXPECTED)


def test_recovery_release_invalid_expected_digest_fails_closed(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{}")
    (tmp_path / "RELEASE").write_text(EXPECTED)
    with pytest.raises(ValueError, match="digest"):
        launcher._require_recovery_release(config, "A" * 64)


def test_recovery_arm_requires_release_before_reservation(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.update(schema=launcher.RECOVERY_SCHEMA, **_controls(),
                  retention=_retention(tmp_path))
    _stub_validation(monkeypatch, config)
    monkeypatch.setattr(launcher, "LOCK", tmp_path / "lock")
    monkeypatch.setattr(launcher.benchmark_batch, "assert_memory_headroom", lambda: True)
    monkeypatch.setattr(launcher, "supervise",
                        lambda *args, **kwargs: pytest.fail("provider launched"))

    with pytest.raises(ValueError, match="RELEASE"):
        launcher.run(tmp_path / "config.json", EXPECTED, arm=True)
    assert not (tmp_path / "lock").exists()
    assert not Path(config["output"]).exists()


def test_release_removal_after_first_row_blocks_next_dispatch(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.update(schema=launcher.RECOVERY_SCHEMA, **_controls(),
                  retention=_retention(tmp_path))
    _stub_validation(monkeypatch, config)
    monkeypatch.setattr(launcher, "LOCK", tmp_path / "lock")
    monkeypatch.setattr(launcher.benchmark_batch, "assert_memory_headroom", lambda: True)
    release = tmp_path / "RELEASE"
    release.write_text(EXPECTED)
    dispatched = []

    def supervise(command, *, row, output, **kwargs):
        dispatched.append(row)
        output.mkdir()
        report = _report(config["seeds"])
        report["config"]["retained_attempts"] = _binding()
        (output / "result.json").write_text(json.dumps(report))
        release.unlink()
        return {"row": row, "pid": 1, "returncode": 0,
                "status": "exited", "elapsed_seconds": 0.1}

    monkeypatch.setattr(launcher, "supervise", supervise)
    with pytest.raises(ValueError, match="RELEASE"):
        launcher.run(tmp_path / "config.json", EXPECTED, arm=True)
    assert dispatched == [launcher.RECOVERY_ROWS[0]]
    assert (Path(config["output"]) / launcher.RECOVERY_ROWS[0] / "result.json").exists()
    assert not (Path(config["output"]) / launcher.RECOVERY_ROWS[1]).exists()


def test_unarmed_run_does_not_require_release(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.update(schema=launcher.RECOVERY_SCHEMA, **_controls(),
                  retention=_retention(tmp_path))
    _stub_validation(monkeypatch, config)
    monkeypatch.setattr(launcher, "_require_recovery_release",
                        lambda *args: pytest.fail("release gate invoked"))
    assert launcher.run(tmp_path / "config.json", EXPECTED, arm=False)["status"] == "unarmed"
