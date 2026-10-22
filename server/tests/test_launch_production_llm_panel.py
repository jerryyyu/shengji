from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import textwrap
import time

import pytest

from scripts import launch_production_llm_panel as launcher


def _config(tmp_path: Path) -> dict:
    return {
        "output": str(tmp_path / "campaign-output"),
        "source_root": str(tmp_path / "source"),
        "python": sys.executable,
        "model_assets": str(tmp_path / "model-assets.json"),
        "prepared_roots": str(tmp_path / "prepared-roots"),
        "prepared_roots_sha256": "a" * 64,
        "seeds": list(range(10)),
        "codex_binary": str(tmp_path / "codex"),
    }


def _stub_validation(monkeypatch, config):
    monkeypatch.setattr(launcher, "validate", lambda path, expected: (config, {}))
    monkeypatch.setattr(launcher, "fence", lambda stamps: None)
    monkeypatch.setattr(launcher.os, "nice", lambda increment: 10)


def _complete_report(path: Path, complete: bool = True):
    path.mkdir(parents=True, exist_ok=True)
    (path / "result.json").write_text(
        json.dumps({"mirrors": [{"complete": complete}] * 40})
    )


def test_unarmed_run_validates_but_never_launches(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _stub_validation(monkeypatch, config)
    monkeypatch.setattr(launcher, "LOCK", tmp_path / "lock")
    monkeypatch.setattr(
        launcher.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("launched"),
    )

    assert launcher.run(tmp_path / "campaign.json", "config-sha", arm=False) == {
        "status": "unarmed", "rows": 9, "rounds": 360,
    }


def _pt_campaign_fixture(tmp_path: Path, *, capacity_retries=False):
    path, _unused, _source = _real_validation_fixture(tmp_path)
    config = json.loads(path.read_text())
    expected_config = tmp_path / "pt-game.json"
    expected_config.write_text(json.dumps({
        "run": True,
        "policy": "release46-pv",
        "seeds": list(range(10)),
        "provider_capacity_retry_delays":
        [15, 30, 60] if capacity_retries else [],
    }, sort_keys=True))
    config.update(
        schema=launcher.PT_SCHEMA,
        rows=list(launcher.PT_ROWS),
        row_wall_seconds=launcher.PT_ROW_WALL_SECONDS,
        row_soft_tokens=launcher.PT_ROW_SOFT_TOKENS,
        recovery_controls={
            "capacity_retries": capacity_retries,
            "accept_recovered_reconnects": False,
            "invalid_action_feedback": True,
            "classify_final_action_failures": True,
        },
        failure_protocol=launcher.PRESERVE_ILLEGAL,
        illegal_failure_limit=8,
        information=["perfect"],
        hostname=socket.gethostname(),
        pt_expected_config={
            "path": str(expected_config),
            "sha256": hashlib.sha256(expected_config.read_bytes()).hexdigest(),
        },
        provider_capacity_retry_delays=[15, 30, 60] if capacity_retries else [],
    )
    path.write_text(json.dumps(config, sort_keys=True))
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), config


def test_pt_campaign_schema_binds_exact_recipe_and_expected_config(tmp_path):
    path, digest, config = _pt_campaign_fixture(tmp_path)
    actual, stamps = launcher.validate(path, digest)
    assert actual["rows"] == ["release46-pv"]
    assert actual["row_wall_seconds"] == 21600
    assert actual["row_soft_tokens"] == 20000000
    assert Path(config["pt_expected_config"]["path"]) in stamps

    for mutation in (
        lambda value: value.update(information=["private"]),
        lambda value: value.update(continuation={}),
        lambda value: value.update(hostname=""),
        lambda value: value["pt_expected_config"].update(
            sha256="0" * 64),
    ):
        mutated = json.loads(path.read_text())
        mutation(mutated)
        path.write_text(json.dumps(mutated, sort_keys=True))
        with pytest.raises(ValueError):
            launcher.validate(path, hashlib.sha256(path.read_bytes()).hexdigest())
        path.write_text(json.dumps(config, sort_keys=True))

    expected_path = Path(config["pt_expected_config"]["path"])
    for seeds in (list(range(1, 11)), [False, *range(1, 10)]):
        expected_path.write_text(json.dumps({"seeds": seeds}, sort_keys=True))
        config["pt_expected_config"]["sha256"] = hashlib.sha256(
            expected_path.read_bytes()).hexdigest()
        path.write_text(json.dumps(config, sort_keys=True))
        with pytest.raises(ValueError, match="seeds mismatch"):
            launcher.validate(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_pt_campaign_accepts_bounded_capacity_retry_recipe(tmp_path):
    path, digest, config = _pt_campaign_fixture(tmp_path, capacity_retries=True)
    actual, _stamps = launcher.validate(path, digest)
    assert actual["recovery_controls"]["capacity_retries"] is True
    assert config["provider_capacity_retry_delays"] == [15, 30, 60]


def test_pt_campaign_binds_capacity_retry_to_expected_config(tmp_path):
    path, digest, config = _pt_campaign_fixture(tmp_path, capacity_retries=True)
    expected_path = Path(config["pt_expected_config"]["path"])
    expected_path.write_text(json.dumps({"run": True, "seeds": list(range(10))},
                                        sort_keys=True))
    config["pt_expected_config"]["sha256"] = hashlib.sha256(
        expected_path.read_bytes()).hexdigest()
    path.write_text(json.dumps(config, sort_keys=True))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="capacity retry mismatch"):
        launcher.validate(path, digest)

    inverse_root = tmp_path / "inverse"
    inverse_root.mkdir()
    path, _digest, config = _pt_campaign_fixture(inverse_root)
    expected_path = Path(config["pt_expected_config"]["path"])
    expected_path.write_text(json.dumps({
        "run": True, "seeds": list(range(10)),
        "provider_capacity_retry_delays": [15, 30, 60]}, sort_keys=True))
    config["pt_expected_config"]["sha256"] = hashlib.sha256(
        expected_path.read_bytes()).hexdigest()
    path.write_text(json.dumps(config, sort_keys=True))
    with pytest.raises(ValueError, match="capacity retry mismatch"):
        launcher.validate(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_pt_campaign_unarmed_is_one_cell_and_never_dispatches(tmp_path, monkeypatch):
    path, digest, _config_value = _pt_campaign_fixture(tmp_path)
    monkeypatch.setattr(launcher.subprocess, "run",
                        lambda *args, **kwargs: pytest.fail("launched"))
    assert launcher.run(path, digest) == {
        "status": "unarmed", "rows": 1, "rounds": 20,
    }


def test_pt_campaign_rechecks_gates_and_dispatches_exact_adapter(tmp_path, monkeypatch):
    path, digest, config = _pt_campaign_fixture(tmp_path)
    lock = tmp_path / "pt-host-lock"
    monkeypatch.setattr(launcher, "PT_LOCK", lock)
    monkeypatch.setattr(launcher.os, "nice", lambda increment: 10)
    monkeypatch.setattr(launcher, "_require_pt_memory", lambda stage: None)
    monkeypatch.setattr(launcher, "_require_recovery_release", lambda *args: None)
    monkeypatch.setattr(launcher, "fence", lambda stamps: None)
    seen = {}

    def fake_adapter(**kwargs):
        assert not Path(kwargs["output"]).exists()
        seen.update(kwargs)
        return {"status": "exited", "returncode": 0}

    monkeypatch.setattr(launcher, "supervise_pt_adapter", fake_adapter)
    result = launcher.run(path, digest, arm=True)
    assert result == {"status": "exited", "returncode": 0}
    assert seen["config_path"] == config["pt_expected_config"]["path"]
    assert seen["expected_sha256"] == config["pt_expected_config"]["sha256"]
    assert seen["cwd"] == config["source_root"]
    assert seen["output"] == Path(config["output"])
    assert seen["wall"] == 21630
    assert seen["python"] == config["python"]
    assert seen["model_assets"] == config["model_assets"]
    assert seen["prepared_roots"] == config["prepared_roots"]
    assert seen["prepared_roots_sha256"] == config["prepared_roots_sha256"]
    assert seen["codex_binary"] == config["codex_binary"]
    assert not Path(config["output"]).exists()


@pytest.mark.parametrize("gate", ["hostname", "nice", "memory", "release", "hold", "host", "fence"])
def test_pt_campaign_refuses_admission_gates_before_adapter(tmp_path, monkeypatch, gate):
    path, digest, config = _pt_campaign_fixture(tmp_path)
    lock = tmp_path / "pt-host-lock"
    monkeypatch.setattr(launcher, "PT_LOCK", lock)
    monkeypatch.setattr(launcher.os, "nice", lambda increment: 10)
    monkeypatch.setattr(launcher, "_require_pt_memory", lambda stage: None)
    monkeypatch.setattr(launcher, "_require_recovery_release", lambda *args: None)
    monkeypatch.setattr(launcher, "fence", lambda stamps: None)
    monkeypatch.setattr(launcher, "supervise_pt_adapter",
                        lambda **kwargs: pytest.fail("adapter dispatched"))
    if gate == "hostname":
        monkeypatch.setattr(launcher.socket, "gethostname", lambda: "wrong-host")
    elif gate == "nice":
        monkeypatch.setattr(launcher.os, "nice", lambda increment: 0)
    elif gate == "memory":
        monkeypatch.setattr(launcher, "_require_pt_memory",
                            lambda stage: (_ for _ in ()).throw(ValueError("memory headroom")))
    elif gate == "release":
        monkeypatch.setattr(launcher, "_require_recovery_release",
                            lambda *args: (_ for _ in ()).throw(ValueError("RELEASE")))
    elif gate == "hold":
        (tmp_path / "HOLD").touch()
    elif gate == "host":
        lock.mkdir()
        (lock / "owner").write_text("peer-owned")
    elif gate == "fence":
        monkeypatch.setattr(
            launcher, "fence",
            lambda stamps: (_ for _ in ()).throw(ValueError("source fence")),
        )
    error = FileExistsError if gate == "host" else ValueError
    match = ("host" if gate == "hostname" else "nice" if gate == "nice"
             else "memory" if gate == "memory" else "RELEASE" if gate == "release"
             else "HOLD" if gate == "hold" else "source fence" if gate == "fence"
             else None)
    with pytest.raises(error, match=match):
        launcher.run(path, digest, arm=True)
    assert not Path(config["output"]).exists()
    if gate == "host":
        assert (lock / "owner").read_text() == "peer-owned"
    else:
        assert not lock.exists()


def test_pt_campaign_failure_preserves_terminal_and_partials(tmp_path, monkeypatch):
    path, digest, config = _pt_campaign_fixture(tmp_path)
    lock = tmp_path / "pt-host-lock"
    monkeypatch.setattr(launcher, "PT_LOCK", lock)
    monkeypatch.setattr(launcher.os, "nice", lambda increment: 10)
    monkeypatch.setattr(launcher, "_require_pt_memory", lambda stage: None)
    monkeypatch.setattr(launcher, "_require_recovery_release", lambda *args: None)
    monkeypatch.setattr(launcher, "fence", lambda stamps: None)

    def failed_adapter(**kwargs):
        output = Path(kwargs["output"])
        output.mkdir()
        (output / "terminal.json").write_text(json.dumps({"status": "failed"}))
        return {"status": "exited", "returncode": 23}

    monkeypatch.setattr(launcher, "supervise_pt_adapter", failed_adapter)
    with pytest.raises(ValueError, match="PT terminal failed"):
        launcher.run(path, digest, arm=True)
    assert (Path(config["output"]) / "terminal.json").read_text()


@pytest.mark.parametrize("mutation", ["hold", "source", "release"])
def test_pt_callback_rechecks_mutation_after_dry_preflight(tmp_path, monkeypatch, mutation):
    path, digest, config = _pt_campaign_fixture(tmp_path)
    source = Path(config["source_root"]) / "recipe.py"
    lock = tmp_path / "pt-host-lock"
    monkeypatch.setattr(launcher, "PT_LOCK", lock)
    monkeypatch.setattr(launcher.os, "nice", lambda increment: 10)
    monkeypatch.setattr(launcher, "_require_pt_memory", lambda stage: None)
    monkeypatch.setattr(launcher, "_require_recovery_release", lambda *args: None)

    def fake_adapter(**kwargs):
        if mutation == "hold":
            (tmp_path / "HOLD").touch()
        elif mutation == "source":
            source.write_text("recipe = 2\n")
        elif mutation == "release":
            monkeypatch.setattr(
                launcher, "_require_recovery_release",
                lambda *args: (_ for _ in ()).throw(ValueError("RELEASE drift")),
            )
        kwargs["before_dispatch"]()
        pytest.fail("real supervisor dispatched")

    monkeypatch.setattr(launcher, "supervise_pt_adapter", fake_adapter)
    with pytest.raises(ValueError, match="HOLD|source|RELEASE"):
        launcher.run(path, digest, arm=True)
    assert not Path(config["output"]).exists()


@pytest.mark.parametrize("marker", ["HOLD", "output"])
def test_hold_or_existing_output_refuses_before_launch(tmp_path, monkeypatch, marker):
    config = _config(tmp_path)
    _stub_validation(monkeypatch, config)
    monkeypatch.setattr(launcher, "LOCK", tmp_path / "lock")
    path = tmp_path / "campaign-output" if marker == "output" else tmp_path / "HOLD"
    path.mkdir()
    (path / "sentinel").write_text("preserve")
    monkeypatch.setattr(
        launcher.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("launched"),
    )

    with pytest.raises(ValueError, match="HOLD or existing campaign output"):
        launcher.run(tmp_path / "campaign.json", "config-sha", arm=True)
    assert (path / "sentinel").read_text() == "preserve"


def test_live_lock_is_never_replaced(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _stub_validation(monkeypatch, config)
    lock = tmp_path / "lock"
    lock.mkdir()
    owner = lock / "owner.json"
    owner.write_text('{"pid": 123}')
    monkeypatch.setattr(launcher, "LOCK", lock)

    with pytest.raises(FileExistsError):
        launcher.run(tmp_path / "campaign.json", "config-sha", arm=True)
    assert owner.read_text() == '{"pid": 123}'


def test_reservation_cleanup_removes_only_owned_identity(tmp_path):
    lock = tmp_path / "lock"
    with launcher.reservation(lock):
        assert json.loads((lock / "owner.json").read_text())["campaign"] == "sol-nine-policy"
    assert not lock.exists()

    with launcher.reservation(lock):
        original = tmp_path / "original-lock"
        lock.rename(original)
        lock.mkdir()
        (lock / "peer.json").write_text("peer-owned")
    assert original.exists()
    assert (lock / "peer.json").read_text() == "peer-owned"


def test_host_reservation_platform_contract():
    assert launcher.default_reservation_path('linux') == Path('/root/.claude-light.lock')
    assert launcher.default_reservation_path('darwin') == Path('/private/tmp/shengji-sol-panel-mini.lock')


def test_light_lane_blocks_sol_without_modifying_owner(tmp_path):
    lock = tmp_path / '.claude-light.lock'
    lock.mkdir()
    (lock / 'owner').write_text('12345 v54ep9 synthetic\n')
    with pytest.raises(FileExistsError):
        with launcher.reservation(lock, shared_host=True):
            pytest.fail('overlap')
    assert (lock / 'owner').read_text() == '12345 v54ep9 synthetic\n'
    assert list(lock.iterdir()) == [lock / 'owner']


def test_sol_blocks_another_light_lane_and_releases_after_failure(tmp_path):
    lock = tmp_path / '.claude-light.lock'
    with pytest.raises(RuntimeError, match='synthetic row failure'):
        with launcher.reservation(lock, shared_host=True):
            assert (lock / 'owner').read_text() == f'{os.getpid()} sol-nine-policy\n'
            with pytest.raises(FileExistsError):
                lock.mkdir()
            raise RuntimeError('synthetic row failure')
    assert not lock.exists()


def test_shared_cleanup_preserves_changed_peer_owner(tmp_path):
    lock = tmp_path / '.claude-host.lock'
    with pytest.raises(OSError):
        with launcher.reservation(lock, shared_host=True):
            (lock / 'owner').write_text('67890 peer\n')
    assert (lock / 'owner').read_text() == '67890 peer\n'


@pytest.mark.parametrize('recovery', [False, True])
def test_linux_run_refuses_light_lane_before_creating_output(tmp_path, monkeypatch, recovery):
    config = _config(tmp_path)
    if recovery:
        config['schema'] = launcher.RECOVERY_SCHEMA
        monkeypatch.setattr(launcher, '_require_recovery_memory', lambda stage: None)
        (tmp_path / 'RELEASE').write_text('a' * 64)
    _stub_validation(monkeypatch, config)
    lock = tmp_path / '.claude-light.lock'
    lock.mkdir()
    (lock / 'owner').write_text('12345 screen\n')
    monkeypatch.setattr(launcher, 'LOCK', lock)
    monkeypatch.setattr(launcher.sys, 'platform', 'linux')
    monkeypatch.setattr(launcher, 'supervise', lambda *a, **kw: pytest.fail('launched'))
    with pytest.raises(FileExistsError):
        launcher.run(tmp_path / 'campaign.json', 'a' * 64, arm=True)
    assert not Path(config['output']).exists()
    assert (lock / 'owner').read_text() == '12345 screen\n'


def test_linux_run_uses_light_reservation_and_preserves_screen(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _stub_validation(monkeypatch, config)
    screen = tmp_path / '.claude-host.lock'
    screen.mkdir()
    (screen / 'owner').write_text('12345 screen\n')
    light = tmp_path / launcher.default_reservation_path('linux').name
    monkeypatch.setattr(launcher, 'LOCK', light)
    monkeypatch.setattr(launcher.sys, 'platform', 'linux')

    def stop_at_dispatch(*args, **kwargs):
        assert (light / 'owner').read_text() == f'{os.getpid()} sol-nine-policy\n'
        assert (screen / 'owner').read_text() == '12345 screen\n'
        raise RuntimeError('synthetic dispatch boundary')

    monkeypatch.setattr(launcher, 'supervise', stop_at_dispatch)
    with pytest.raises(RuntimeError, match='synthetic dispatch boundary'):
        launcher.run(tmp_path / 'campaign.json', 'config-sha', arm=True)
    assert not light.exists()
    assert (screen / 'owner').read_text() == '12345 screen\n'
    assert json.loads((Path(config['output']) / 'terminal.json').read_text())['status'] == 'failed'


@pytest.mark.parametrize("failure", ["nonzero", "incomplete", "deadline"])
def test_sequential_campaign_stops_and_preserves_partial_artifacts(
    tmp_path, monkeypatch, failure,
):
    config = _config(tmp_path)
    _stub_validation(monkeypatch, config)
    monkeypatch.setattr(launcher, "LOCK", tmp_path / "lock")
    monkeypatch.setattr(launcher, "ROWS", ("first", "second", "third"))
    calls = []

    def fake_supervise(command, *, cwd, env, log, row, output, wall=43200, python):
        calls.append(row)
        output.mkdir(parents=True, exist_ok=True)
        (output / "partial.json").write_text("keep")
        if row == "first":
            _complete_report(output)
            return {"row": row, "pid": 1, "returncode": 0,
                    "status": "exited", "elapsed_seconds": 0.1}
        if failure == "nonzero":
            return {"row": row, "pid": 2, "returncode": 7,
                    "status": "exited", "elapsed_seconds": 0.1}
        if failure == "deadline":
            return {"row": row, "pid": 2, "returncode": -signal.SIGKILL,
                    "status": "deadline", "elapsed_seconds": 0.1}
        _complete_report(output, complete=False)
        return {"row": row, "pid": 2, "returncode": 0,
                "status": "exited", "elapsed_seconds": 0.1}

    monkeypatch.setattr(launcher, "supervise", fake_supervise)
    with pytest.raises(ValueError, match="row terminated|incomplete row"):
        launcher.run(tmp_path / "campaign.json", "config-sha", arm=True)

    assert calls == ["first", "second"]
    output = Path(config["output"])
    assert (output / "first" / "partial.json").read_text() == "keep"
    assert (output / "second" / "partial.json").read_text() == "keep"
    assert not (output / "third").exists()
    terminal = json.loads((output / "terminal.json").read_text())
    assert terminal["status"] == "failed"
    assert len(terminal["rows"]) == 2


def _real_validation_fixture(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "recipe.py"
    source.write_text("recipe = 1\n")
    native = source_root / "native.so"
    native.write_bytes(b"not-loaded-by-validation")
    model = tmp_path / "model.bin"
    model.write_bytes(b"model")
    model_assets = tmp_path / "model-assets.json"
    model_assets.write_text(json.dumps({"sol": str(model)}))
    roots = tmp_path / "prepared-roots"
    roots.mkdir()
    (roots / "root-0.json").write_text("{}")
    (roots / "result.json").write_text("roots")
    codex = tmp_path / "codex"
    codex.write_text("codex")
    config = {
        "schema": "sol-nine-policy-campaign-v1",
        "rows": list(launcher.ROWS),
        "row_wall_seconds": 43200,
        "row_soft_tokens": 45000000,
        "provider_call_seconds": 300,
        "seeds": list(range(10)),
        "source_root": str(source_root),
        "source_files": {
            "recipe.py": hashlib.sha256(source.read_bytes()).hexdigest(),
            "native.so": hashlib.sha256(native.read_bytes()).hexdigest(),
        },
        "model_assets": str(model_assets),
        "model_assets_sha256": hashlib.sha256(model_assets.read_bytes()).hexdigest(),
        "prepared_roots": str(roots),
        "prepared_roots_sha256": hashlib.sha256((roots / "result.json").read_bytes()).hexdigest(),
        "codex_binary": str(codex),
        "codex_binary_sha256": hashlib.sha256(codex.read_bytes()).hexdigest(),
        "python": sys.executable,
        "output": str(tmp_path / "output"),
    }
    config_path = tmp_path / "campaign.json"
    config_path.write_text(json.dumps(config, sort_keys=True))
    expected = hashlib.sha256(config_path.read_bytes()).hexdigest()
    return config_path, expected, source


@pytest.mark.parametrize("pin", ["0" * 64, "ABC", None, True, 123])
def test_declared_codex_digest_is_verified(tmp_path, pin):
    path, _, _ = _real_validation_fixture(tmp_path)
    config = json.loads(path.read_text())
    config["codex_binary_sha256"] = pin
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="Codex binary"):
        launcher.validate(path, hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.mark.parametrize('bare', [False, True])
@pytest.mark.parametrize('gate', ['unarmed', 'hold', 'release', 'memory', 'host', 'source',
                                 'predecessor_missing', 'predecessor_live'])
def test_stage2_predecessor_entry_preserves_real_launcher_gates(tmp_path, monkeypatch, gate, bare):
    from test_launch_sol_recovery import _stage1, _stage2_predecessor

    path, _, source = _real_validation_fixture(tmp_path)
    config = _stage1(json.loads(path.read_text()))
    config.update(schema=launcher.STAGE2_SCHEMA, rows=list(launcher.STAGE2_ROWS))
    entry, predecessor, save = _stage2_predecessor(
        tmp_path, monkeypatch,
        mutate=lambda result: result['prepared_roots'].update(
            source_result_sha256=config['prepared_roots_sha256']))
    config['predecessor_publication'] = predecessor['predecessor_publication']
    if gate == 'predecessor_missing':
        config.pop('predecessor_publication')
    if gate == 'predecessor_live':
        monkeypatch.setattr(entry.os, 'kill', lambda *args: None)
    ref = save('campaign.json', config)
    monkeypatch.setattr(launcher.os, 'nice', lambda _: 10)
    monkeypatch.setattr(launcher.benchmark_batch, 'assert_memory_headroom',
                        lambda: gate != 'memory')
    monkeypatch.setattr(launcher, 'supervise', lambda *a, **k: pytest.fail('worker dispatched'))
    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda *a, **k: pytest.fail('process launched'))
    lock = tmp_path / 'host-lock'
    monkeypatch.setattr(launcher, 'LOCK', lock)
    run = launcher.run if bare else entry.run
    if gate == 'hold':
        (tmp_path / 'HOLD').touch()
    elif gate == 'host':
        lock.mkdir()
        (lock / 'owner').write_text('peer-owned')
        (tmp_path / 'RELEASE').write_text(ref['sha256'])
    elif gate == 'source':
        source.write_text('changed source')
    if gate == 'unarmed':
        assert run(path, ref['sha256']) == {'status': 'unarmed', 'rows': 7, 'rounds': 280}
    else:
        error, message = {
            'hold': (ValueError, 'HOLD'),
            'release': (ValueError, 'RELEASE'),
            'memory': (ValueError, 'memory headroom'),
            'host': (FileExistsError, None),
            'source': (ValueError, 'source'),
            'predecessor_missing': (ValueError, 'predecessor publication required'),
            'predecessor_live': (ValueError, 'predecessor process still exists'),
        }[gate]
        with pytest.raises(error, match=message):
            run(path, ref['sha256'], arm=True)
    assert not Path(config['output']).exists()
    if gate == 'host':
        assert (lock / 'owner').read_text() == 'peer-owned'
    else:
        assert not lock.exists()


def test_substituted_codex_refuses_before_reservation(tmp_path, monkeypatch):
    path, expected, _ = _real_validation_fixture(tmp_path)
    config = json.loads(path.read_text())
    Path(config["codex_binary"]).write_text("other")
    lock = tmp_path / "lock"
    monkeypatch.setattr(launcher, "LOCK", lock)
    monkeypatch.setattr(launcher, "supervise", lambda *a, **kw: pytest.fail("launch"))
    with pytest.raises(ValueError, match="Codex binary"):
        launcher.run(path, expected, arm=True)
    assert not lock.exists()
    assert not Path(config["output"]).exists()


def test_historical_packet_without_codex_pin_remains_valid(tmp_path):
    path, _, _ = _real_validation_fixture(tmp_path)
    config = json.loads(path.read_text())
    del config["codex_binary_sha256"]
    path.write_text(json.dumps(config))
    launcher.validate(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_codex_mutation_after_validation_is_fenced(tmp_path):
    path, expected, _ = _real_validation_fixture(tmp_path)
    config, stamps = launcher.validate(path, expected)
    Path(config["codex_binary"]).write_text("other")
    with pytest.raises(ValueError, match="changed after validation"):
        launcher.fence(stamps)


def test_codex_mutation_during_hash_is_refused(tmp_path, monkeypatch):
    path, expected, _ = _real_validation_fixture(tmp_path)
    binary = Path(json.loads(path.read_text())["codex_binary"])
    original = launcher.hashlib.file_digest

    def mutate(handle, algorithm):
        result = original(handle, algorithm)
        binary.write_text("other")
        return result

    monkeypatch.setattr(launcher.hashlib, "file_digest", mutate)
    with pytest.raises(ValueError, match="Codex binary hash or identity drift"):
        launcher.validate(path, expected)


def test_config_hash_drift_is_refused(tmp_path):
    config_path, expected, _ = _real_validation_fixture(tmp_path)
    config_path.write_text(config_path.read_text() + "\n")
    with pytest.raises(ValueError, match="config hash mismatch"):
        launcher.validate(config_path, expected)


def _pt_adapter_config(tmp_path, *, capacity_retries=False):
    path = tmp_path / "pt-config.json"
    config = {"run": True, "seeds": list(range(10)),
              "provider_capacity_retry_delays":
              [15, 30, 60] if capacity_retries else []}
    path.write_text(json.dumps(config, sort_keys=True))
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), config


@pytest.mark.parametrize("capacity_retries", [False, True])
def test_pt_adapter_uses_real_parser_for_dry_preflight_and_supervised_command(
        tmp_path, monkeypatch, capacity_retries):
    """The adapter's producer command is parser-checked before supervision."""
    config_path, expected, _frozen = _pt_adapter_config(
        tmp_path, capacity_retries=capacity_retries)
    model_assets = tmp_path / "model-assets.json"
    model_assets.write_text("{}")
    output = tmp_path / "pt-output"
    captured = {}
    retry_delays = [15, 30, 60] if capacity_retries else []
    dry_report = {"mode": "dry-run", "planned_arms": ["sol-perfect"],
                  "planned_mirrors": 20,
                  "config": {"run": False, "seeds": list(range(10)),
                             "provider_capacity_retry_delays": retry_delays}}

    def fake_run(command, **kwargs):
        assert command[-1] != "--run"
        assert ("--retry-provider-capacity" in command) is capacity_retries
        assert kwargs == {"cwd": tmp_path, "env": {"PT": "1"},
                          "capture_output": True, "text": True,
                          "timeout": 60, "check": False}
        from scripts import production_llm_panel as panel
        original = panel.run_row

        def fake_row(**values):
            captured.update(values)
            return dry_report

        monkeypatch.setattr(panel, "run_row", fake_row)
        try:
            from contextlib import redirect_stdout
            import io
            with redirect_stdout(io.StringIO()) as stream:
                assert panel.main(command[4:]) == 0
            assert json.loads(stream.getvalue()) == dry_report
        finally:
            monkeypatch.setattr(panel, "run_row", original)
        return subprocess.CompletedProcess(command, 0, json.dumps(dry_report), "")

    supervised = {}
    callback_seen = []

    def fake_supervise(command, **kwargs):
        assert callback_seen == ["dry-complete"]
        supervised.update(command=command, kwargs=kwargs)
        return {"status": "exited", "returncode": 0}

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    monkeypatch.setattr(launcher, "supervise_pt", fake_supervise)
    result = launcher.supervise_pt_adapter(
        config_path=config_path, expected_sha256=expected, cwd=tmp_path,
        env={"PT": "1"}, output=output, wall=123, python="/python",
        model_assets=model_assets, prepared_roots=tmp_path / "roots",
        prepared_roots_sha256="a" * 64, codex_binary=tmp_path / "codex",
        before_dispatch=lambda: callback_seen.append("dry-complete"))

    assert result == {"status": "exited", "returncode": 0}
    assert captured == {
        "row": "release46-pv", "model_paths": {},
        "prepared_roots_from": str(tmp_path / "roots"),
        "prepared_roots_sha256": "a" * 64,
        "output": str(output / "benchmark"), "seeds": tuple(range(10)),
        "codex_binary": str(tmp_path / "codex"), "run": False,
        "capacity_retries": capacity_retries, "accept_recovered_reconnects": False,
        "invalid_action_feedback": True,
        "classify_final_action_failures": True,
        "failure_protocol": "preserve-model-illegal-v1",
        "retention_plan": None, "retention_plan_sha256": None,
        "information": "perfect", "resource_profile": "s47-pt",
    }
    expected_command = [
        "/python", "-B", "-m", "scripts.production_llm_panel",
        "--row", "release46-pv", "--model-assets", str(model_assets),
        "--prepared-roots-from", str(tmp_path / "roots"),
        "--prepared-roots-sha256", "a" * 64,
        "--seeds", *map(str, range(10)),
        "--output", str(output / "benchmark"),
        "--codex-binary", str(tmp_path / "codex"),
        "--information", "perfect", "--resource-profile", "s47-pt",
        "--invalid-action-feedback", "--classify-final-action-failures",
        "--failure-protocol", "preserve-model-illegal-v1"]
    if capacity_retries:
        expected_command.append("--retry-provider-capacity")
    expected_command.append("--run")
    assert supervised["command"] == expected_command
    assert supervised["kwargs"] == {
        "config_path": config_path, "expected_sha256": expected,
        "cwd": tmp_path, "env": {"PT": "1"}, "output": output,
        "wall": 123, "python": "/python",
    }
    assert not output.exists()


@pytest.mark.parametrize("defect", ["bool_seed", "run", "mode", "arms", "mirrors", "resources"])
def test_pt_adapter_refuses_dry_config_drift_before_supervision(tmp_path, monkeypatch, defect):
    config_path, expected, _ = _pt_adapter_config(tmp_path)
    model_assets = tmp_path / "model-assets.json"
    model_assets.write_text("{}")
    report = {"mode": "dry-run", "planned_arms": ["sol-perfect"],
              "planned_mirrors": 20,
              "config": {"run": False, "seeds": list(range(10))}}
    if defect == "bool_seed":
        report["config"]["seeds"][0] = False
    elif defect == "run":
        report["config"]["run"] = True
    elif defect == "resources":
        report["config"]["token_limit"] = 45000000
    elif defect == "mode":
        report["mode"] = "run"
    elif defect == "arms":
        report["planned_arms"] = ["sol-actor-only", "sol-perfect"]
    else:
        report["planned_mirrors"] = 40
    monkeypatch.setattr(
        launcher.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, json.dumps(report), ""),
    )
    monkeypatch.setattr(launcher, "supervise_pt",
                        lambda *args, **kwargs: pytest.fail("supervised"))
    with pytest.raises(ValueError, match="drift"):
        launcher.supervise_pt_adapter(
            config_path=config_path, expected_sha256=expected, cwd=tmp_path,
            env={}, output=tmp_path / "out", wall=30, python=sys.executable,
            model_assets=model_assets, prepared_roots=tmp_path / "roots",
            prepared_roots_sha256="a" * 64, codex_binary=tmp_path / "codex")
    assert not (tmp_path / "out").exists()


def test_pt_adapter_bad_hash_refuses_before_dry_parser_or_supervisor(tmp_path, monkeypatch):
    config_path, _expected, _ = _pt_adapter_config(tmp_path)
    monkeypatch.setattr(launcher.subprocess, "run",
                        lambda *args, **kwargs: pytest.fail("dry parser"))
    monkeypatch.setattr(launcher, "supervise_pt",
                        lambda *args, **kwargs: pytest.fail("supervised"))
    with pytest.raises(ValueError, match="config hash mismatch"):
        launcher.supervise_pt_adapter(
            config_path=config_path, expected_sha256="0" * 64, cwd=tmp_path,
            env={}, output=tmp_path / "out", wall=30, python=sys.executable,
            model_assets=tmp_path / "assets", prepared_roots=tmp_path / "roots",
            prepared_roots_sha256="a" * 64, codex_binary=tmp_path / "codex")


@pytest.mark.parametrize("delays", [None, {}, [15, 30, 600],
                                     [15.0, 30, 60], [True, 30, 60]])
def test_pt_adapter_rejects_invalid_capacity_retry_schedule_before_dry(
        tmp_path, monkeypatch, delays):
    config_path, _expected, config = _pt_adapter_config(tmp_path)
    config["provider_capacity_retry_delays"] = delays
    config_path.write_text(json.dumps(config, sort_keys=True))
    expected = hashlib.sha256(config_path.read_bytes()).hexdigest()
    monkeypatch.setattr(launcher.subprocess, "run",
                        lambda *args, **kwargs: pytest.fail("dry parser"))
    with pytest.raises(ValueError, match="capacity retry declaration"):
        launcher.supervise_pt_adapter(
            config_path=config_path, expected_sha256=expected, cwd=tmp_path,
            env={}, output=tmp_path / "out", wall=30, python=sys.executable,
            model_assets=tmp_path / "assets", prepared_roots=tmp_path / "roots",
            prepared_roots_sha256="a" * 64, codex_binary=tmp_path / "codex")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("mutation,match", [
    (lambda config: config.update(run=False), "run=True"),
    (lambda config: config["seeds"].__setitem__(0, -1), "distinct integer seeds"),
])
def test_pt_adapter_rejects_frozen_run_or_seed_contract_before_preflight(
        tmp_path, monkeypatch, mutation, match):
    config_path, _expected, config = _pt_adapter_config(tmp_path)
    mutation(config)
    config_path.write_text(json.dumps(config, sort_keys=True))
    expected = hashlib.sha256(config_path.read_bytes()).hexdigest()
    monkeypatch.setattr(launcher.subprocess, "run",
                        lambda *args, **kwargs: pytest.fail("dry parser"))
    with pytest.raises(ValueError, match=match):
        launcher.supervise_pt_adapter(
            config_path=config_path, expected_sha256=expected, cwd=tmp_path,
            env={}, output=tmp_path / "out", wall=30, python=sys.executable,
            model_assets=tmp_path / "assets", prepared_roots=tmp_path / "roots",
            prepared_roots_sha256="a" * 64, codex_binary=tmp_path / "codex")


@pytest.mark.parametrize("schema,delays,accepted", [
    ("sol-nine-policy-campaign-v1", [], True),
    ("sol-nine-policy-campaign-v1", [15, 30, 60], False),
    ("sol-nine-policy-campaign-v2", [15, 30, 60], True),
    ("sol-nine-policy-campaign-v2", [], False),
    ("sol-nine-policy-campaign-v2", [15, 30, 600], False),
    ("sol-nine-policy-campaign-v2", [15.0, 30, 60], False),
])
def test_retry_recipe_is_explicit_and_bounded(tmp_path, schema, delays, accepted):
    path, _, _ = _real_validation_fixture(tmp_path)
    config = json.loads(path.read_text())
    config.update(schema=schema, provider_capacity_retry_delays=delays)
    path.write_text(json.dumps(config))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if accepted:
        actual, _ = launcher.validate(path, digest)
        assert actual["provider_capacity_retry_delays"] == delays
    else:
        with pytest.raises(ValueError, match="campaign recipe drift"):
            launcher.validate(path, digest)


def test_capacity_flag_dispatched_for_all_rows_without_row_retries(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config["provider_capacity_retry_delays"] = [15, 30, 60]
    _stub_validation(monkeypatch, config)
    monkeypatch.setattr(launcher, "LOCK", tmp_path / "lock")
    seen = []

    def supervise(command, *, row, output, **kwargs):
        seen.append(row)
        assert command.count("--retry-provider-capacity") == 1
        _complete_report(output)
        return {"returncode": 0, "status": "exited", "row": row}

    monkeypatch.setattr(launcher, "supervise", supervise)
    terminal = launcher.run(tmp_path / "campaign.json", "synthetic", arm=True)
    assert terminal["status"] == "complete"
    assert seen == list(launcher.ROWS)


def test_source_hash_drift_is_refused(tmp_path):
    config_path, expected, source = _real_validation_fixture(tmp_path)
    source.write_text("recipe = 2\n")
    with pytest.raises(ValueError, match="source drift"):
        launcher.validate(config_path, expected)


def test_source_inventory_rejects_extra_and_symlinked_code(tmp_path):
    config_path, expected, source = _real_validation_fixture(tmp_path)
    source_root = source.parent
    (source_root / "extra.py").write_text("extra = 1\n")
    with pytest.raises(ValueError, match="source inventory drift"):
        launcher.validate(config_path, expected)

    (source_root / "extra.py").unlink()
    (source_root / "linked.py").symlink_to(source)
    with pytest.raises(ValueError, match="source inventory symlink"):
        launcher.validate(config_path, expected)


def test_fence_rejects_source_inventory_added_after_admission(tmp_path):
    config_path, expected, source = _real_validation_fixture(tmp_path)
    _config_value, stamps = launcher.validate(config_path, expected)
    (source.parent / "late.py").write_text("late = 1\n")
    with pytest.raises(ValueError, match="source inventory changed"):
        launcher.fence(stamps)


def test_armed_environment_cleans_provider_overrides_and_pins_blas_threads(
    tmp_path, monkeypatch,
):
    config = _config(tmp_path)
    _stub_validation(monkeypatch, config)
    monkeypatch.setattr(launcher, "LOCK", tmp_path / "lock")
    monkeypatch.setattr(launcher, "ROWS", ("only",))
    monkeypatch.setenv("SHENGJI_SECRET", "do-not-forward")
    monkeypatch.setenv("PYTHONPATH", "do-not-forward")
    captured = {}

    def fake_supervise(command, *, cwd, env, log, row, output, wall=43200, python):
        captured.update(env)
        _complete_report(output)
        return {"row": row, "pid": 1, "returncode": 0,
                "status": "exited", "elapsed_seconds": 0.1}

    monkeypatch.setattr(launcher, "supervise", fake_supervise)
    assert launcher.run(tmp_path / "campaign.json", "config-sha", arm=True)["status"] == "complete"
    assert "PYTHONPATH" not in captured
    assert {key for key in captured if key.startswith("SHENGJI_")} == {"SHENGJI_FAST"}
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
        assert captured[key] == "1"


class _FakeChild:
    pid = 2468

    def __init__(self, polls, waits):
        self._polls = iter(polls)
        self._waits = iter(waits)
        self.returncode = None
        self.wait_calls = []

    def poll(self):
        value = next(self._polls)
        if value is not None:
            self.returncode = value
        return value

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        action = next(self._waits)
        if isinstance(action, BaseException):
            raise action
        self.returncode = action
        return action


def test_supervisor_observation_timeout_is_not_job_failure(tmp_path, monkeypatch, capsys):
    child = _FakeChild([None, 0, 0], [subprocess.TimeoutExpired(["worker"], 30)])
    seen = {}
    monkeypatch.setattr(
        launcher.subprocess, "Popen",
        lambda command, **kwargs: seen.update(command=command, kwargs=kwargs) or child,
    )
    monkeypatch.setattr(launcher.time, "monotonic", iter([0.0, 1.0, 2.0, 3.0]).__next__)
    killpg = []
    monkeypatch.setattr(launcher.os, "killpg", lambda *args: killpg.append(args))

    result = launcher.supervise(["worker"], cwd="/work", env={}, log=io.StringIO(),
                                row="first", output=tmp_path / "output", wall=10,
                                python="/pinned/python")
    assert seen["command"][0] == "/pinned/python"
    assert result["status"] == "exited"
    assert result["returncode"] == 0
    assert not killpg
    assert json.loads(capsys.readouterr().out)["event"] == "row-live"
    assert seen["kwargs"]["start_new_session"] is True
    assert seen["kwargs"]["stdin"] is subprocess.DEVNULL


def test_supervisor_deadline_kills_only_owned_group_and_tolerates_race(tmp_path, monkeypatch):
    child = _FakeChild([None, None], [-signal.SIGKILL])
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda command, **kwargs: child)
    monkeypatch.setattr(launcher.time, "monotonic", iter([0.0, 11.0, 11.0]).__next__)
    killpg = []

    def raced_killpg(*args):
        killpg.append(args)
        raise ProcessLookupError

    monkeypatch.setattr(launcher.os, "killpg", raced_killpg)
    result = launcher.supervise(["worker"], cwd="/work", env={}, log=io.StringIO(),
                                row="first", output=tmp_path / "output", wall=10)
    assert result["status"] == "deadline"
    assert result["returncode"] == -signal.SIGKILL
    assert killpg == [(child.pid, signal.SIGKILL)]
    assert child.wait_calls == [None]


def test_parent_death_watchdog_kills_row_but_not_unrelated_peer(tmp_path):
    """A killed launcher cannot strand its row, and never owns peer groups."""
    server_root = Path(__file__).parents[1]
    identities = tmp_path / "identities"
    log_path = tmp_path / "row.log"
    output_path = tmp_path / "row-output"
    worker = (
        "import pathlib, subprocess, sys, time, os; "
        "peer = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(60)'], start_new_session=True); "
        "pathlib.Path(sys.argv[1]).write_text(f'{os.getpid()} {peer.pid}'); "
        "time.sleep(60)"
    )
    runner = textwrap.dedent(
        f"""
        import os
        from pathlib import Path
        import sys
        from scripts.launch_production_llm_panel import supervise

        identities = Path({str(identities)!r})
        identities.parent.mkdir(parents=True, exist_ok=True)
        with Path({str(log_path)!r}).open("w") as log:
            supervise(
                [{sys.executable!r}, "-c", {worker!r}, {str(identities)!r}],
                cwd={str(server_root)!r}, env=dict(os.environ), log=log,
                row="witness", output=Path({str(output_path)!r}), wall=60,
            )
        """
    )
    launcher_process = subprocess.Popen(
        [sys.executable, "-c", runner], cwd=server_root,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    row_pid = peer_pid = None
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not identities.exists():
            time.sleep(0.02)
        if not identities.exists():
            launcher_process.kill()
            _stdout, stderr = launcher_process.communicate(timeout=5)
            pytest.fail(stderr.decode())
        row_pid, peer_pid = map(int, identities.read_text().split())
        launcher_process.kill()
        launcher_process.wait(timeout=5)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(row_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        with pytest.raises(ProcessLookupError):
            os.kill(row_pid, 0)
        os.kill(peer_pid, 0)
    finally:
        if launcher_process.poll() is None:
            launcher_process.kill()
            launcher_process.wait(timeout=5)
        if row_pid is not None:
            try:
                os.kill(row_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if peer_pid is not None:
            try:
                os.kill(peer_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
