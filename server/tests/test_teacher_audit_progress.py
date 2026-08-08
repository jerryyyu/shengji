"""Falsification tests for the outcome-blind Teacher progress reader."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import teacher_audit_progress as P  # noqa: E402


def _progress(shard: int, state: str, fold: str, world: int) -> dict:
    return {
        "audit_id": P.AUDIT_ID,
        "event": P.EVENT,
        "fold": fold,
        "kind": "champion-fold",
        "shard_count": P.SHARD_COUNT,
        "shard_index": shard,
        "state_id": state,
        "worlds_complete": world,
        "worlds_total": P.WORLDS_PER_FOLD,
    }


def _state(shard: int, state: str, complete: int) -> dict:
    return {
        "audit_id": P.AUDIT_ID,
        "event": P.EVENT,
        "kind": "state",
        "shard_count": P.SHARD_COUNT,
        "shard_index": shard,
        "state_id": state,
        "states_complete": complete,
        "states_total": P.STATES_PER_SHARD,
    }


def _terminal(shard: int) -> dict:
    return {
        "audit_id": P.AUDIT_ID,
        "mode": "label",
        "out": f"shard{shard:02d}.json",
        "shard_index": shard,
        "records": P.STATES_PER_SHARD,
        "records_digest": "a" * 64,
    }


def _write(path: Path, values: list[dict]) -> None:
    path.write_text("".join(json.dumps(value) + "\n" for value in values))


def _root(tmp_path: Path) -> Path:
    for shard in range(P.SHARD_COUNT):
        _write(
            tmp_path / f"{P.PROGRESS_PREFIX}{shard:02d}.log.partial", [])
    return tmp_path


def _complete_state(shard: int, state: str, complete: int) -> list[dict]:
    values = []
    for fold in P.FOLDS:
        values.extend(_progress(shard, state, fold, world)
                      for world in range(1, P.WORLDS_PER_FOLD + 1))
    values.append(_state(shard, state, complete))
    return values


def test_partial_summary_counts_only_registered_progress(tmp_path):
    root = _root(tmp_path)
    path = root / f"{P.PROGRESS_PREFIX}00.log.partial"
    _write(path, [_progress(0, "state-a", P.FOLDS[0], 1)])
    payload = P.summarize(root)
    assert payload["score_free"] is True
    assert payload["outer_worlds_complete"] == 1
    assert payload["outer_worlds_total"] == 4_096
    assert payload["states_complete"] == 0
    assert payload["published_label_shards"] == 0
    assert payload["outcome_opened"] is False


def test_complete_final_log_requires_exact_receipt(tmp_path):
    root = _root(tmp_path)
    partial = root / f"{P.PROGRESS_PREFIX}00.log.partial"
    final = root / f"{P.PROGRESS_PREFIX}00.log"
    values = []
    for index in range(1, P.STATES_PER_SHARD + 1):
        values.extend(_complete_state(0, f"state-{index}", index))
    values.append(_terminal(0))
    partial.unlink()
    _write(final, values)
    payload = P.summarize(root)
    assert payload["outer_worlds_complete"] == 512
    assert payload["states_complete"] == 8
    assert payload["published_label_shards"] == 1
    assert payload["shards"][0]["log_final"] is True


def test_outcome_or_unknown_field_refuses(tmp_path):
    root = _root(tmp_path)
    path = root / f"{P.PROGRESS_PREFIX}00.log.partial"
    value = _progress(0, "state-a", P.FOLDS[0], 1)
    value["level_utility"] = 2
    _write(path, [value])
    with pytest.raises(P.ProgressRefusal, match="progress keys"):
        P.summarize(root)


def test_nonmonotone_world_and_fold_refuse(tmp_path):
    root = _root(tmp_path)
    path = root / f"{P.PROGRESS_PREFIX}00.log.partial"
    _write(path, [_progress(0, "state-a", P.FOLDS[0], 2)])
    with pytest.raises(P.ProgressRefusal, match="fold order"):
        P.summarize(root)

    value = _progress(0, "state-a", P.FOLDS[0], 1)
    value["worlds_complete"] = True
    _write(path, [value])
    with pytest.raises(P.ProgressRefusal, match="fold types"):
        P.summarize(root)
    _write(path, [
        _progress(0, "state-a", P.FOLDS[0], 1),
        _progress(0, "state-a", P.FOLDS[1], 2),
    ])
    with pytest.raises(P.ProgressRefusal, match="fold order"):
        P.summarize(root)


def test_state_completion_requires_both_exact_folds(tmp_path):
    root = _root(tmp_path)
    path = root / f"{P.PROGRESS_PREFIX}00.log.partial"
    _write(path, [_progress(0, "state-a", P.FOLDS[0], 1),
                  _state(0, "state-a", 1)])
    with pytest.raises(P.ProgressRefusal, match="state order"):
        P.summarize(root)


def test_final_partial_collision_and_final_without_receipt_refuse(tmp_path):
    root = _root(tmp_path)
    final = root / f"{P.PROGRESS_PREFIX}00.log"
    _write(final, [])
    with pytest.raises(P.ProgressRefusal, match="exactly one"):
        P.summarize(root)
    (root / f"{P.PROGRESS_PREFIX}00.log.partial").unlink()
    with pytest.raises(P.ProgressRefusal, match="lacks publication"):
        P.summarize(root)


def test_cross_shard_state_identity_reuse_refuses(tmp_path):
    root = _root(tmp_path)
    _write(root / f"{P.PROGRESS_PREFIX}00.log.partial",
           [_progress(0, "same-state", P.FOLDS[0], 1)])
    _write(root / f"{P.PROGRESS_PREFIX}01.log.partial",
           [_progress(1, "same-state", P.FOLDS[0], 1)])
    with pytest.raises(P.ProgressRefusal, match="across shards"):
        P.summarize(root)


def test_within_shard_state_identity_reuse_refuses(tmp_path):
    root = _root(tmp_path)
    values = _complete_state(0, "same-state", 1)
    values.extend(_complete_state(0, "same-state", 2))
    _write(root / f"{P.PROGRESS_PREFIX}00.log.partial", values)
    with pytest.raises(P.ProgressRefusal, match="repeats a state"):
        P.summarize(root)
