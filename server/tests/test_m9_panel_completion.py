"""Pure completion gate: execution status is not scientific acceptance."""
import copy

import pytest

from shengji.eval.m9_panel_readout import validate_panel_completion
from shengji.eval import m9_panel_readout as reader


def receipts():
    return [
        dict(schema="m9-panel-owner-terminal-v1", packet_sha256="a" * 64,
             process_status="exited", returncode=0, utc="2026-10-04T00:00:00+00:00",
             comparison_validated=False),
        dict(schema="m9-process-result-v1", status="exited", returncode=0,
             elapsed_seconds=10.5, comparison_validated=False, error_type=None),
        dict(schema="m9-panel-terminal-v1", status="complete", collected_count=15,
             validated_count=15, provenance_verified=False,
             receipt=dict(schema="m9-panel-collection-v1", completed_panels=15,
                          primary_panels=3, secondary_panels=12,
                          provenance_verified=False, serving_choice_assessed=False)),
    ]


def test_complete_execution_gate_does_not_mutate_or_claim_acceptance():
    values = receipts()
    before = copy.deepcopy(values)
    assert validate_panel_completion(*values, packet_sha256="a" * 64) is None
    assert values == before


@pytest.mark.parametrize("index,key,value", [
    (0, "packet_sha256", "b" * 64), (0, "schema", "m9-owner-terminal-v1"),
    (0, "process_status", "failed"), (0, "returncode", 1),
    (0, "returncode", False), (0, "comparison_validated", True), (0, "utc", ""),
    (1, "status", "timeout"), (1, "status", "drain_failed"),
    (1, "returncode", False), (1, "returncode", -9), (1, "error_type", "ValueError"),
    (1, "elapsed_seconds", float("nan")), (1, "elapsed_seconds", float("inf")),
    (1, "elapsed_seconds", -1), (1, "elapsed_seconds", True),
    (1, "comparison_validated", True), (2, "status", "failed"),
    (2, "collected_count", 14), (2, "validated_count", 14),
    (2, "validated_count", 15.0), (2, "provenance_verified", True),
])
def test_contradictory_or_partial_receipts_refuse(index, key, value):
    values = receipts()
    values[index][key] = value
    with pytest.raises(ValueError):
        validate_panel_completion(*values, packet_sha256="a" * 64)


@pytest.mark.parametrize("key", ["completed_panels", "primary_panels", "secondary_panels"])
@pytest.mark.parametrize("bad", [False, 0, 15.0])
def test_strict_population_receipt(key, bad):
    values = receipts()
    values[2]["receipt"][key] = bad
    with pytest.raises(ValueError):
        validate_panel_completion(*values, packet_sha256="a" * 64)


@pytest.mark.parametrize("index", [0, 1, 2])
def test_missing_or_extra_receipt_fields_refuse(index):
    for mode in ("missing", "extra"):
        values = receipts()
        if mode == "missing":
            values[index].pop("schema")
        else:
            values[index]["unexpected"] = 1
        with pytest.raises(ValueError):
            validate_panel_completion(*values, packet_sha256="a" * 64)


def test_final_guard_failure_after_complete_collection_is_not_readable():
    values = receipts()
    values[0].update(process_status="failed", returncode=1)
    values[1].update(status="failed", returncode=1)
    assert values[2]["status"] == "complete"
    with pytest.raises(ValueError, match="both report exited"):
        validate_panel_completion(*values, packet_sha256="a" * 64)


def test_failed_completion_never_opens_records():
    values = receipts()
    values[1]["returncode"] = 1
    calls = []
    with pytest.raises(ValueError):
        reader.read_completed_m9_panels({}, *values, packet_sha256="a" * 64,
                                       load_records=lambda: calls.append("raw"))
    assert calls == []


def test_success_loads_once_and_uses_real_reader():
    from test_m9_panel_readout import _records
    analysis, records = _records()
    calls = []
    def load():
        calls.append("raw")
        return records
    result = reader.read_completed_m9_panels(
        analysis, *receipts(), packet_sha256="a" * 64, load_records=load)
    assert calls == ["raw"]
    assert result["panel_count"] == 15
    assert result["provenance_verified"] is False
    assert result["strategic_quality_assessed"] is False


def test_loader_failure_is_not_retried():
    calls = []
    failure = OSError("sealed file inaccessible")
    def load():
        calls.append("raw")
        raise failure
    with pytest.raises(OSError) as caught:
        reader.read_completed_m9_panels(
            {}, *receipts(), packet_sha256="a" * 64, load_records=load)
    assert caught.value is failure and calls == ["raw"]
