from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest


PATH = (Path(__file__).parents[1] / "scripts"
        / "bury_lead_combo_scored_dev_aggregate.py")
SPEC = importlib.util.spec_from_file_location("s6_aggregate_under_test", PATH)
AGG = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(AGG)


GIT = "a" * 40
SHA = "b" * 64


def _outcomes(live: int, widened: int, expanded: int) -> list[dict]:
    return [
        {"slot": "incumbent_live", "attacker_points": live},
        {"slot": "incumbent_widened", "attacker_points": widened},
        {"slot": "expanded", "attacker_points": expanded},
    ]


def _records(*, lead_values: list[int] | None = None,
             bury_values: list[int] | None = None,
             alternative_values: list[int] | None = None,
             distinct: bool = True) -> tuple[list[dict], list[dict]]:
    lead_values = lead_values or [1] * AGG.STATE_COUNT
    bury_values = bury_values or [1] * AGG.STATE_COUNT
    alternative_values = alternative_values or [1] * AGG.STATE_COUNT
    records = []
    selection_rows = []
    for index in range(AGG.STATE_COUNT):
        modes = {}
        for mode in AGG.MODES:
            lead = lead_values[index] if mode == "baseline" \
                else alternative_values[index]
            bury = bury_values[index] if mode == "baseline" \
                else alternative_values[index]
            live = 100
            widened = live - lead
            expanded = widened - bury
            modes[mode] = {
                "rows": [
                    {"slot_outcomes": _outcomes(live, widened, expanded)}
                    for _ in range(AGG.REPORT_WORLDS)
                ]
            }
        records.append({
            "deal_seed": 1_000 + index,
            "selection": {"selected_indices": {
                "incumbent_live": 0,
                "incumbent_widened": 1 if distinct else 0,
                "expanded": 2 if distinct else 0,
            }},
            "report": {"modes": modes},
        })
        selection_rows.append({
            "deal_seed": 1_000 + index,
            "selection_group": (
                "shape_rich" if index < 32 else "hash_uniform_anchor"),
        })
    return records, selection_rows


def _inputs() -> dict:
    return {
        "record_manifest_sha256": SHA,
        "record_manifest": [],
        "packet": {},
    }


def _review() -> dict:
    return {"commit": "c" * 40, "marker_sha256": "d" * 64}


def _resign(value: dict) -> None:
    material = dict(value)
    material.pop("internal_sha256", None)
    value["internal_sha256"] = AGG.digest(material)


def test_exact_primary_rule_advances_at_41_positive_states():
    values = [1] * 41 + [0] * 23
    records, rows = _records(lead_values=values, bury_values=values)
    result = AGG.aggregate_records(records, selection_rows=rows)
    assert result["decision"] == "ADVANCE_TO_FRESH_SCREEN_DESIGN"
    assert result["criteria"]["all_requirements_met"] is True
    lead = result["modes"]["baseline"]["contrasts"]["lead_source"]
    assert lead["positive_states"] == 41
    assert lead["sum"] == 41 * AGG.REPORT_WORLDS
    assert lead["fraction"] == "41/64"


def test_exact_primary_rule_selects_none_at_40_positive_states():
    values = [1] * 40 + [0] * 24
    records, rows = _records(lead_values=values, bury_values=values)
    result = AGG.aggregate_records(records, selection_rows=rows)
    assert result["decision"] == "SELECT_NONE_FOR_FRESH_SCREEN_DESIGN"
    assert result["criteria"]["positive_state_threshold_met"] == {
        "lead_source": False, "joint_bury_source": False}


def test_group_mean_and_alternative_continuation_are_load_bearing():
    lead = [1] * 9 + [-1] * 23 + [2] * 32
    bury = list(lead)
    records, rows = _records(lead_values=lead, bury_values=bury)
    result = AGG.aggregate_records(records, selection_rows=rows)
    assert result["modes"]["baseline"]["contrasts"]["lead_source"][
        "positive_states"] == 41
    assert result["criteria"]["baseline_report_mean_strictly_positive"][
        "lead_source"] is True
    assert result["criteria"]["baseline_selection_group_means_nonnegative"][
        "lead_source"]["shape_rich"] is False
    assert result["decision"] == "SELECT_NONE_FOR_FRESH_SCREEN_DESIGN"

    records, rows = _records(alternative_values=[-1] * AGG.STATE_COUNT)
    result = AGG.aggregate_records(records, selection_rows=rows)
    assert result["criteria"]["alternative_continuation_means_nonnegative"][
        "all_boss"]["lead_source"] is False
    assert result["decision"] == "SELECT_NONE_FOR_FRESH_SCREEN_DESIGN"


def test_selected_candidate_difference_is_required():
    records, rows = _records(distinct=False)
    result = AGG.aggregate_records(records, selection_rows=rows)
    assert result["criteria"][
        "at_least_one_selected_slot_differs_from_control"] is False
    assert result["decision"] == "SELECT_NONE_FOR_FRESH_SCREEN_DESIGN"


def test_population_slot_and_points_shapes_refuse():
    records, rows = _records()
    with pytest.raises(AGG.AggregateRefused, match="64 states"):
        AGG.aggregate_records(records[:-1], selection_rows=rows[:-1])
    broken = copy.deepcopy(records)
    broken[0]["report"]["modes"]["baseline"]["rows"][0][
        "slot_outcomes"].reverse()
    with pytest.raises(AGG.AggregateRefused, match="slot order"):
        AGG.aggregate_records(broken, selection_rows=rows)
    broken = copy.deepcopy(records)
    broken[0]["report"]["modes"]["baseline"]["rows"][0][
        "slot_outcomes"][0]["attacker_points"] = True
    with pytest.raises(AGG.AggregateRefused, match="attacker points"):
        AGG.aggregate_records(broken, selection_rows=rows)


def test_admission_is_closed_and_bool_counts_cannot_pass(monkeypatch):
    monkeypatch.setattr(AGG.secrets, "token_hex", lambda _size: "e" * 64)
    monkeypatch.setattr(AGG.time, "time_ns", lambda: 123)
    value = AGG.admission_payload(
        expected_git=GIT, review=_review(), inputs=_inputs())
    assert AGG.admission_problems(
        value, expected_git=GIT, review=_review(), inputs=_inputs()) == []
    value["strength_claim"] = True
    _resign(value)
    assert AGG.admission_problems(
        value, expected_git=GIT, review=_review(), inputs=_inputs())
    value["strength_claim"] = False
    value["created_time_ns"] = True
    _resign(value)
    assert AGG.admission_problems(
        value, expected_git=GIT, review=_review(), inputs=_inputs())


def test_result_mutation_refuses_even_with_forged_internal_hash():
    records, rows = _records()
    value = AGG.result_payload(
        expected_git=GIT, review=_review(), inputs=_inputs(),
        admission_raw=b"admission\n", records=records,
        selection_rows=rows)
    assert AGG.result_problems(value, expected=value) == []
    changed = copy.deepcopy(value)
    changed["statistics"]["decision"] = "ADVANCE_TO_PRODUCTION"
    _resign(changed)
    assert "aggregate result reconstruction drift" in AGG.result_problems(
        changed, expected=value)
    changed = copy.deepcopy(value)
    changed["authority"]["strength_claim"] = True
    _resign(changed)
    assert AGG.result_problems(changed, expected=value)


def test_review_claim_never_opens_scored_records(monkeypatch, capsys):
    monkeypatch.setattr(AGG, "require_fresh_process", lambda: None)
    monkeypatch.setattr(AGG, "require_clean_exact_git", lambda *_a, **_k: None)
    monkeypatch.setattr(
        AGG, "verify_inputs", lambda: (_inputs(), SimpleNamespace()))
    monkeypatch.setattr(AGG, "sha256_file", lambda _path: SHA)
    monkeypatch.setattr(
        AGG, "_open_records",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("review claim opened records")))
    AGG.review_claim_command(Namespace(expected_git=GIT))
    output = capsys.readouterr().out
    assert output.startswith(AGG.IMPLEMENTATION_REVIEW_PREFIX)
    assert '"scored_record_access_authorized":true' in output
    assert '"fresh_screen_execution_authorized":false' in output


def test_review_record_requires_one_new_raw_prefix_and_no_later_variant(
        monkeypatch):
    commit = "1" * 40
    parent = "2" * 40
    expected = {"schema": "review", "git": GIT}
    marker = AGG.IMPLEMENTATION_REVIEW_PREFIX.encode() + AGG.canonical(expected)
    previous = b"prior ledger\n"
    current = previous + marker
    state = {"tip": current}
    monkeypatch.setattr(
        AGG.subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=0))

    def fake_git(*args, **_kwargs):
        if args[:3] == ("show", "-s", "--format=%P"):
            return parent
        if args[:3] == ("show", "-s", "--format=%an"):
            return AGG.REVIEWER_NAME
        if args[:3] == ("show", "-s", "--format=%ae"):
            return AGG.REVIEWER_EMAIL
        if args[:3] == ("show", "-s", "--format=%cn"):
            return AGG.REVIEWER_NAME
        if args[:3] == ("show", "-s", "--format=%ce"):
            return AGG.REVIEWER_EMAIL
        if args[:3] == ("show", "-s", "--format=%B"):
            return AGG.REVIEWER_SESSION_TRAILER + "fixture"
        if args[0] == "diff-tree":
            return AGG.REVIEW_LEDGER
        raise AssertionError(args)

    def fake_git_bytes(*args, **_kwargs):
        ref = args[-1]
        if ref.startswith(commit):
            return current
        if ref.startswith(parent):
            return previous
        return state["tip"]

    monkeypatch.setattr(AGG, "git", fake_git)
    monkeypatch.setattr(AGG, "git_bytes", fake_git_bytes)
    review, observed = AGG._review_record(
        commit=commit, prefix=AGG.IMPLEMENTATION_REVIEW_PREFIX,
        expected=expected, label="fixture review")
    assert observed == marker
    assert review["marker_sha256"] == AGG.sha256_bytes(marker)

    state["tip"] = current + (
        AGG.IMPLEMENTATION_REVIEW_PREFIX
        + '{"schema":"different"}\n').encode()
    with pytest.raises(AGG.AggregateRefused, match="marker drift"):
        AGG._review_record(
            commit=commit, prefix=AGG.IMPLEMENTATION_REVIEW_PREFIX,
            expected=expected, label="fixture review")


def test_run_consumes_gate_before_any_record_open(monkeypatch, capsys):
    state = {"gate": False}
    records, rows = _records()
    monkeypatch.setattr(AGG, "require_fresh_process", lambda: None)
    monkeypatch.setattr(AGG.os, "geteuid", lambda: 0)
    monkeypatch.setattr(AGG, "require_clean_exact_git", lambda *_a, **_k: None)
    monkeypatch.setattr(
        AGG, "verify_inputs", lambda: (_inputs(), SimpleNamespace()))
    monkeypatch.setattr(AGG, "sha256_file", lambda _path: SHA)
    monkeypatch.setattr(
        AGG, "_review_record",
        lambda **_kwargs: (_review(), b"marker\n"))
    monkeypatch.setattr(AGG, "admission_problems", lambda *_a, **_k: [])

    def gate(**_kwargs):
        state["gate"] = True
        return b"admission\n"

    def open_records(**_kwargs):
        assert state["gate"] is True
        return records, rows

    monkeypatch.setattr(AGG, "_write_gate", gate)
    monkeypatch.setattr(AGG, "_open_records", open_records)
    monkeypatch.setattr(AGG, "_write_output", lambda value: AGG.canonical(value))
    AGG.run_command(Namespace(expected_git=GIT, review_commit="c" * 40))
    assert "COMPLETE_AWAITING_AGGREGATE_RESULT_REVIEW" in capsys.readouterr().out


def _manifest(tmp_path: Path) -> list[dict]:
    result = []
    for index in range(AGG.STATE_COUNT):
        name = f"state-{index:02d}-of-{AGG.STATE_COUNT}.json"
        raw = f"record-{index}".encode()
        path = tmp_path / name
        path.write_bytes(raw)
        path.chmod(0o444)
        result.append({
            "state_index": index,
            "deal_seed": index,
            "state_id": str(index),
            "record_file": name,
            "record_sha256": AGG.sha256_bytes(raw),
            "record_internal_sha256": f"{index + 1:064x}",
            "record_bytes": len(raw),
        })
    return result


def test_record_metadata_population_permissions_and_links(tmp_path, monkeypatch):
    monkeypatch.setattr(AGG, "RECORDS_DIR", tmp_path)
    manifest = _manifest(tmp_path)
    AGG._verify_record_metadata(manifest, require_root=False)
    extra = tmp_path / "extra.json"
    extra.write_text("extra")
    with pytest.raises(AGG.AggregateRefused, match="population"):
        AGG._verify_record_metadata(manifest, require_root=False)
    extra.unlink()
    target = tmp_path / manifest[0]["record_file"]
    target.chmod(0o644)
    with pytest.raises(AGG.AggregateRefused, match="metadata"):
        AGG._verify_record_metadata(manifest, require_root=False)
    target.chmod(0o444)
    hardlink = tmp_path / "hardlink"
    os.link(target, hardlink)
    with pytest.raises(AGG.AggregateRefused):
        AGG._verify_record_metadata(manifest, require_root=False)


def test_open_records_hashes_the_exact_bytes_it_parses(tmp_path, monkeypatch):
    manifest = []
    for index in range(AGG.STATE_COUNT):
        record = {
            "deal_seed": index,
            "internal_sha256": f"{index + 1:064x}",
            "state_id": str(index),
        }
        raw = AGG.canonical(record)
        name = f"state-{index:02d}-of-{AGG.STATE_COUNT}.json"
        path = tmp_path / name
        path.write_bytes(raw)
        path.chmod(0o444)
        manifest.append({
            "state_index": index,
            "deal_seed": index,
            "state_id": str(index),
            "record_file": name,
            "record_sha256": AGG.sha256_bytes(raw),
            "record_internal_sha256": record["internal_sha256"],
            "record_bytes": len(raw),
        })

    stable_bytes = AGG.stable_bytes
    monkeypatch.setattr(AGG, "RECORDS_DIR", tmp_path)
    monkeypatch.setattr(AGG, "_require_members", lambda *_a, **_k: None)
    monkeypatch.setattr(AGG, "_validate_gate", lambda: None)
    monkeypatch.setattr(AGG, "_require_loaded_origins", lambda _packet: None)
    monkeypatch.setattr(
        AGG, "stable_bytes",
        lambda path, *, label: stable_bytes(
            path, label=label, root_owned=False),
    )
    design = SimpleNamespace(
        _selection_rows=lambda: [{} for _ in range(AGG.STATE_COUNT)])
    scorer = SimpleNamespace(record_problems=lambda *_a, **_k: [])
    controller = SimpleNamespace(
        _load_scorer=lambda _packet: (design, scorer))
    inputs = {"packet": {}, "record_manifest": manifest}
    records, rows = AGG._open_records(
        inputs=inputs, controller=controller, expected_root_members=set())
    assert len(records) == len(rows) == AGG.STATE_COUNT

    target = tmp_path / manifest[0]["record_file"]
    original = target.read_bytes()
    reordered = (json.dumps({
        "state_id": "0",
        "internal_sha256": f"{1:064x}",
        "deal_seed": 0,
    }, separators=(",", ":")) + "\n").encode()
    assert len(reordered) == len(original)
    assert json.loads(reordered) == json.loads(original)
    assert AGG.sha256_bytes(reordered) != manifest[0]["record_sha256"]
    target.chmod(0o644)
    target.write_bytes(reordered)
    target.chmod(0o444)

    with pytest.raises(
            AGG.AggregateRefused,
            match="sealed scored record 0 SHA/size drift"):
        AGG._open_records(
            inputs=inputs, controller=controller,
            expected_root_members=set())


def test_stable_bytes_and_strict_json_refuse_links_duplicates_nonfinite(
        tmp_path):
    target = tmp_path / "target.json"
    target.write_bytes(b'{"a":1}\n')
    target.chmod(0o444)
    assert AGG.stable_bytes(
        target, label="target", root_owned=False) == b'{"a":1}\n'
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(AGG.AggregateRefused):
        AGG.stable_bytes(link, label="link", root_owned=False)
    with pytest.raises(ValueError, match="duplicate"):
        AGG.strict_json(b'{"a":1,"a":2}')
    with pytest.raises(ValueError, match="nonfinite"):
        AGG.strict_json(b'{"a":NaN}')


def test_unsafe_invocation_refuses_and_isolated_safe_path_blocks_shadow(
        tmp_path):
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    unsafe = subprocess.run(
        [sys.executable, "-B", str(PATH), "verify-inputs",
         "--expected-git", GIT],
        cwd=PATH.parents[2], env=environment,
        capture_output=True, text=True, check=False,
    )
    assert unsafe.returncode != 0
    assert "isolated safe-path no-bytecode Python" in unsafe.stderr

    scripts = tmp_path / "server/scripts"
    scripts.mkdir(parents=True)
    copied = scripts / PATH.name
    copied.write_bytes(PATH.read_bytes())
    sentinel = tmp_path / "PREIMPORT_SHADOW_EXECUTED"
    (scripts / "json.py").write_text(
        "with open(" + repr(str(sentinel)) + ", 'x') as handle:\n"
        "    handle.write('executed before provenance checks\\n')\n"
        "raise RuntimeError('PREIMPORT_SHADOW_EXECUTED')\n",
        encoding="utf-8",
    )
    isolated = subprocess.run(
        [sys.executable, "-I", "-P", "-B", str(copied),
         "verify-inputs", "--expected-git", GIT],
        cwd=tmp_path, env=environment,
        capture_output=True, text=True, check=False,
    )
    assert isolated.returncode != 0
    assert not sentinel.exists()
    assert "PREIMPORT_SHADOW_EXECUTED" not in isolated.stderr


def test_parser_has_no_retry_resume_report_or_gameplay_command():
    parser = AGG.parser()
    commands = next(action for action in parser._actions
                    if getattr(action, "choices", None)).choices
    assert set(commands) == {
        "verify-inputs", "aggregate-review-claim", "run",
        "verify-result", "result-review-claim",
    }
    assert not set(commands) & {"retry", "resume", "extend", "report",
                                "score", "gameplay", "deploy"}


def test_result_review_claim_can_authorize_design_only(monkeypatch, capsys):
    records, rows = _records()
    value = AGG.result_payload(
        expected_git=GIT, review=_review(), inputs=_inputs(),
        admission_raw=b"admission\n", records=records,
        selection_rows=rows)
    raw = AGG.canonical(value)
    monkeypatch.setattr(
        AGG, "_reconstruct_output", lambda _args: (value, raw, _inputs()))
    AGG.result_review_claim_command(Namespace(
        expected_git=GIT, review_commit="c" * 40,
        expected_result_sha256=AGG.sha256_bytes(raw)))
    line = capsys.readouterr().out
    assert line.startswith(AGG.RESULT_REVIEW_PREFIX)
    claim = json.loads(line[len(AGG.RESULT_REVIEW_PREFIX):])
    assert claim["fresh_screen_design_authorized"] is True
    assert claim["fresh_screen_execution_authorized"] is False
    assert claim["strength_claim"] is False
