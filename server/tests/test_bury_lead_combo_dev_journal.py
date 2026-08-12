"""Resumability and authority contracts for reusable bury exploration."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import bury_lead_combo_dev_journal as J  # noqa: E402
import bury_lead_combo_exploration as E  # noqa: E402
import bury_lead_combo_population as P  # noqa: E402


def _selection() -> dict:
    rows = [P.census_state(P.DEAL_SEED0 + offset) for offset in range(2)]
    selection = P.select_dev_states(
        rows, shape_count=1, anchor_count=1,
        require_full_population=False)
    # The unit fixture stands in for the byte-pinned 512-row derivation; all
    # selected rows themselves are real reconstructed states.
    selection["population"]["states"] = P.POPULATION_STATES
    assert P.selection_problems(selection) == []
    return selection


def _runtime() -> dict:
    return {
        "git": "a" * 40,
        "tree_dirty": False,
        "python": "3.14.3",
        "fast_binary_sha256": "b" * 64,
        "population_source_sha256": "c" * 64,
        "scorer_source_sha256": "d" * 64,
        "continuation_source_sha256": "f" * 64,
        "journal_source_sha256": "e" * 64,
    }


def _fake_scorer(status: str = "COMPLETE_EXPLORATION"):
    def score(rnd, seat, *, bot, incumbent_bury, worlds,
              attempt_factor, max_candidate_rollouts,
              continuation_mode):
        ballot = E.build_bury_lead_combo_ballot(
            rnd, seat, incumbent_bury, live_lead_ballot=bot._candidates)
        return {
            "schema": E.SCHEMA,
            "status": status,
            "candidate_count": ballot.combo_count,
            "scoring_contract": {
                "continuation_mode": continuation_mode,
                "recursive_mc_continuation": False,
            },
            "work": {
                "worlds_requested": worlds,
                "candidate_rollout_cap": max_candidate_rollouts,
            },
            "exploration_only": True,
            "confirmatory_inference": False,
            "strength_claim": False,
            "production_deployment": False,
        }
    return score


def test_state_journal_extends_and_resumes_without_recomputing(tmp_path):
    selection = _selection()
    output = tmp_path / "journal"
    events = []
    first = J.journal_selection(
        selection, output, worlds=1, base_seed=7, limit=1,
        runtime=_runtime(), scorer=_fake_scorer(), progress=events.append)
    assert first["new_records"] == 1
    assert first["reused_records"] == 0
    assert first["states_complete"] == 1
    assert events[-1]["event"] == "completed"
    assert (output / J.MANIFEST_NAME).is_file()
    assert len(list(output.glob("state-*.json"))) == 1

    events.clear()
    second = J.journal_selection(
        selection, output, worlds=1, base_seed=7, limit=2,
        runtime=_runtime(), scorer=_fake_scorer(), progress=events.append)
    assert second["new_records"] == 1
    assert second["reused_records"] == 1
    assert [event["event"] for event in events] == ["reused", "completed"]
    assert len(list(output.glob("state-*.json"))) == 2

    def forbidden(*_args, **_kwargs):
        raise AssertionError("valid journaled states were recomputed")

    third = J.journal_selection(
        selection, output, worlds=1, base_seed=7, limit=2,
        runtime=_runtime(), scorer=forbidden)
    assert third["new_records"] == 0
    assert third["reused_records"] == 2
    assert third["continuation_mode"] == "baseline"
    assert third["strength_claim"] is False
    assert third["production_deployment"] is False


def test_manifest_drift_refuses_before_new_scoring(tmp_path):
    selection = _selection()
    output = tmp_path / "journal"
    J.journal_selection(
        selection, output, worlds=1, base_seed=7, limit=1,
        runtime=_runtime(), scorer=_fake_scorer())

    def forbidden(*_args, **_kwargs):
        raise AssertionError("scoring ran after manifest drift")

    with pytest.raises(J.JournalRefused, match="manifest differs"):
        J.journal_selection(
            selection, output, worlds=5, base_seed=7, limit=2,
            runtime=_runtime(), scorer=forbidden)


def test_continuation_mode_is_manifest_bound_and_recorded(tmp_path):
    selection = _selection()
    output = tmp_path / "journal"
    result = J.journal_selection(
        selection, output, worlds=1, base_seed=7, limit=1,
        continuation_mode="boss_near", runtime=_runtime(),
        scorer=_fake_scorer())
    assert result["continuation_mode"] == "boss_near"
    manifest = json.loads((output / J.MANIFEST_NAME).read_bytes())
    record = json.loads(next(output.glob("state-*.json")).read_bytes())
    assert manifest["continuation_mode"] == "boss_near"
    assert record["result"]["scoring_contract"] == {
        "continuation_mode": "boss_near",
        "recursive_mc_continuation": False,
    }

    with pytest.raises(J.JournalRefused, match="manifest differs"):
        J.journal_selection(
            selection, output, worlds=1, base_seed=7, limit=1,
            continuation_mode="all_boss", runtime=_runtime(),
            scorer=_fake_scorer())


def test_unknown_continuation_mode_refuses_before_manifest_write(tmp_path):
    output = tmp_path / "journal"
    with pytest.raises(ValueError, match="continuation_mode"):
        J.journal_selection(
            _selection(), output, worlds=1, base_seed=7,
            continuation_mode="recursive_mc", runtime=_runtime(),
            scorer=_fake_scorer())
    assert not (output / J.MANIFEST_NAME).exists()


def test_corrupt_completed_record_refuses_instead_of_overwriting(tmp_path):
    selection = _selection()
    output = tmp_path / "journal"
    J.journal_selection(
        selection, output, worlds=1, base_seed=7, limit=1,
        runtime=_runtime(), scorer=_fake_scorer())
    record_path = next(output.glob("state-*.json"))
    record = json.loads(record_path.read_bytes())
    record["strength_claim"] = True
    record_path.write_text(json.dumps(record))
    before = record_path.read_bytes()
    with pytest.raises(J.JournalRefused, match="internal digest|authority"):
        J.journal_selection(
            selection, output, worlds=1, base_seed=7, limit=1,
            runtime=_runtime(), scorer=_fake_scorer())
    assert record_path.read_bytes() == before


def test_partial_exploration_is_retained_as_partial_not_strength(tmp_path):
    selection = _selection()
    summary = J.journal_selection(
        selection, tmp_path / "journal", worlds=3, base_seed=9, limit=1,
        runtime=_runtime(), scorer=_fake_scorer("PARTIAL_EXPLORATION"))
    assert summary["status_counts"] == {"PARTIAL_EXPLORATION": 1}
    assert summary["states_complete"] == 1
    assert summary["confirmatory_inference"] is False
    assert summary["strength_claim"] is False


def test_self_rehashed_census_swap_is_not_reusable(tmp_path):
    selection = _selection()
    output = tmp_path / "journal"
    J.journal_selection(
        selection, output, worlds=1, base_seed=7, limit=1,
        runtime=_runtime(), scorer=_fake_scorer())
    record_path = next(output.glob("state-*.json"))
    record = json.loads(record_path.read_bytes())
    record["source_census"]["combo_count"] += 1
    without_digest = dict(record)
    without_digest.pop("internal_sha256")
    record["internal_sha256"] = J.stable_digest(without_digest)
    record_path.write_text(json.dumps(record))
    with pytest.raises(J.JournalRefused,
                       match="census/selection identity"):
        J.journal_selection(
            selection, output, worlds=1, base_seed=7, limit=1,
            runtime=_runtime(), scorer=_fake_scorer())


def test_exclusive_writer_never_replaces_existing_file(tmp_path):
    path = tmp_path / "record.json"
    J._write_exclusive(path, {"first": True})
    first = path.read_bytes()
    with pytest.raises(J.JournalRefused, match="overwrite"):
        J._write_exclusive(path, {"second": True})
    assert path.read_bytes() == first


def test_negative_base_seed_refuses_before_manifest_write(tmp_path):
    with pytest.raises(ValueError, match="base_seed"):
        J.journal_selection(
            _selection(), tmp_path / "journal", worlds=1, base_seed=-1,
            runtime=_runtime(), scorer=_fake_scorer())
    assert not (tmp_path / "journal" / J.MANIFEST_NAME).exists()
