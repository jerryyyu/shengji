"""Synthetic witnesses only: never load a model or a scientific fixture."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


spec = importlib.util.spec_from_file_location(
    "m9_capacity_timing", Path(__file__).parents[1] / "scripts/time_m9_capacity.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_timer_exact_boundary_and_gap():
    clock = [10.0]
    timing = module.Timing(5, lambda: clock[0])
    clock[0] = 14.0
    timing.check()
    assert timing.max_gap == 4.0
    clock[0] = 15.0
    with pytest.raises(TimeoutError, match="soft deadline"):
        timing.check()


@pytest.mark.parametrize("fails", [False, True])
def test_boundary_wrapper_preserves_arguments_return_exception_and_identity(fails):
    calls = []
    sentinel = object()
    def original(*args, **kwargs):
        calls.append((args, kwargs))
        if fails:
            raise RuntimeError("synthetic failure")
        return sentinel
    owner = SimpleNamespace(call=original)
    timing = module.Timing(120)
    try:
        with module.timed_call(owner, "call", timing, "test-stage"):
            assert owner.call(1, flag=2) is sentinel
    except RuntimeError as exc:
        assert fails and str(exc) == "synthetic failure"
    assert owner.call is original
    assert calls == [((1,), {"flag": 2})]
    assert len(timing.events) == 1 and timing.events[0]["stage"] == "test-stage"


@pytest.mark.parametrize("mode", ["fresh-root", "history-primed"])
def test_real_composition_boundary_parameters_and_exclusive_output(tmp_path, mode):
    fixture, bot = object(), object()
    calls = []
    def collector(factory, actual_fixture, control, treatment, **kwargs):
        calls.append(kwargs)
        assert actual_fixture is fixture
        assert control == [["C3"]] and treatment == [["D3"]]
        assert factory() is bot
        kwargs["check_budget"]()
        return {"synthetic": True}
    output = tmp_path / mode
    timing = module.Timing(120)
    module.measure(collector, lambda: bot, fixture, ([["C3"]], [["D3"]]),
                   mode=mode, output=output, timing=timing)
    assert calls[0] == {"mode": mode, "seed": 17, "fill_seed": 0,
                        "expected_legal_count": 1771, "check_budget": timing.check}
    report = json.loads((output / "timing.json").read_text())
    assert report["status"] == "complete" and report["failure"] is None
    assert report["stages_overlap"] is True
    assert [e["stage"] for e in report["events"]] == [
        "bot_construction", "panel_total_including_factories", "synthetic_publication"]
    assert json.loads((output / "synthetic-panel.json").read_text()) == {"synthetic": True}
    before = (output / "timing.json").read_bytes()
    with pytest.raises(FileExistsError):
        module.measure(collector, lambda: bot, fixture, ([], []), mode=mode,
                       output=output, timing=timing)
    assert len(calls) == 1 and (output / "timing.json").read_bytes() == before


@pytest.mark.parametrize("error", [RuntimeError("failed"), TimeoutError("late")])
def test_failure_retains_timing_and_does_not_publish_result(tmp_path, error):
    def collector(*args, **kwargs):
        raise error
    output = tmp_path / "failed"
    with pytest.raises(type(error), match=str(error)):
        module.measure(collector, None, None, ([], []), mode="fresh-root",
                       output=output, timing=module.Timing(120))
    report = json.loads((output / "timing.json").read_text())
    assert report["status"] == "failed"
    assert report["failure"] == {"type": type(error).__name__, "message": str(error)}
    assert not (output / "synthetic-panel.json").exists()


def test_input_authentication_and_symlink_refusal(tmp_path):
    import hashlib
    path = tmp_path / "input"
    path.write_bytes(b"synthetic")
    digest = hashlib.sha256(b"synthetic").hexdigest()
    assert module.pinned_bytes(path, digest) == b"synthetic"
    with pytest.raises(ValueError, match="digest mismatch"):
        module.pinned_bytes(path, "0" * 64)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="nonsymlink"):
        module.pinned_bytes(link, digest)
