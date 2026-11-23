from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Event

import pytest

import sealed_reader as reader
from seed_worker import _publish
import supervisor
from test_readout import slots


def _write_fixture(seed, root, env):
    directory = root / str(seed)
    directory.mkdir()
    return seed, _publish(directory, json.dumps(json.loads(env["FIXTURE"])[str(seed)]))


@pytest.fixture
def bundle(monkeypatch, tmp_path, slots):
    root = tmp_path.resolve() / "run"
    monkeypatch.setattr(supervisor, "FIRST_SEED", 100)
    monkeypatch.setattr(supervisor, "DEALS", 2)
    monkeypatch.setattr(supervisor, "arm_environment",
                        lambda _: {"SHENGJI_BOT": "fixture", "FIXTURE": json.dumps(slots)})
    monkeypatch.setattr(supervisor, "write_seed", _write_fixture)
    supervisor.run_reserved(root, [], "d" * 64, workers=2)
    source = Path(reader.__file__).resolve()
    spec = dict(schema="s158b-handoff-v1", root=str(root), reader="codex",
                reader_path=str(source), reader_sha256=reader._digest(source.read_bytes()),
                analysis_sha256=reader._digest(source.with_name("readout.py").read_bytes()),
                dispatch_sha256="d" * 64, arm_name="fixture", hold_paths=[str(root.parent / "HOLD")],
                terminal_sha256=reader._digest((root / "terminal.json").read_bytes()))
    return root, spec


def invoke(bundle):
    root, spec = bundle
    path = root.parent / "handoff.json"
    raw = json.dumps(spec).encode()
    path.write_bytes(raw)
    return reader.read_once(path, reader._digest(raw))


def test_supervisor_seals_to_saved_result(bundle, monkeypatch):
    result = invoke(bundle)
    assert result["verdict"] == "PASS" and result["eligible"] == 2
    root, _ = bundle
    (root / "slots" / "100" / "result.json").unlink()
    monkeypatch.setattr(reader.readout, "analyze", lambda *_a, **_k: pytest.fail("repeat read"))
    assert invoke(bundle) == result


@pytest.mark.parametrize("change", ["reader", "reader_path", "reader_sha256", "analysis_sha256",
                                    "terminal_sha256", "dispatch_sha256", "arm_name", "hold", "extra"])
def test_refused_before_claim(bundle, change):
    root, spec = bundle
    if change == "hold":
        Path(spec["hold_paths"][0]).touch()
    elif change == "extra":
        (root / "slots/102").mkdir()
    else:
        spec[change] = "wrong"
    with pytest.raises(ValueError):
        invoke(bundle)
    assert not (root / "codex-readout").exists()


def test_late_corruption_leaves_claim_without_verdict(bundle, monkeypatch):
    root, _ = bundle
    (root / "slots/101/result.json").write_bytes(b"{}")
    monkeypatch.setattr(reader.readout, "analyze", lambda *_a, **_k: pytest.fail("unsealed analysis"))
    with pytest.raises(ValueError, match="seal mismatch"):
        invoke(bundle)
    with pytest.raises(ValueError, match="already claimed"):
        invoke(bundle)
    assert not (root / "codex-readout/result.json").exists()


def test_overlapping_reader_cannot_open_slots(bundle, monkeypatch):
    root, _ = bundle
    entered, resume = Event(), Event()
    verify = reader._verified

    def pause(path, expected):
        if path == root / "slots/100/result.json":
            entered.set()
            assert resume.wait(5)
        return verify(path, expected)

    monkeypatch.setattr(reader, "_verified", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(invoke, bundle)
        try:
            assert entered.wait(5)
            with pytest.raises(ValueError, match="already claimed"):
                invoke(bundle)
        finally:
            resume.set()
        assert pending.result()["verdict"] == "PASS"


def test_fault_terminal_with_matching_hash_stays_closed(bundle):
    root, spec = bundle
    path = root / "terminal.json"
    terminal = json.loads(path.read_bytes())
    terminal["status"] = "FAULT"
    path.write_text(json.dumps(terminal))
    spec["terminal_sha256"] = reader._digest(path.read_bytes())
    with pytest.raises(ValueError, match="terminal"):
        invoke(bundle)
    assert not (root / "codex-readout").exists()


def test_hold_arriving_after_first_slot_stops_read(bundle, monkeypatch):
    root, _ = bundle
    original = reader._verified
    seen = []

    def verify(path, expected):
        raw = original(path, expected)
        if path.name == "result.json":
            seen.append(path)
            (root / "READOUT.HOLD").touch()
        return raw

    monkeypatch.setattr(reader, "_verified", verify)
    with pytest.raises(ValueError, match="HOLD"):
        invoke(bundle)
    assert seen == [root / "slots/100/result.json"]
    assert not (root / "codex-readout/receipt.json").exists()
