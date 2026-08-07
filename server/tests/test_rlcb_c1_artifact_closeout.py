"""Falsification tests for the artifact-only RLCB-C1 closeout."""
from __future__ import annotations

import copy
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rlcb_c1_artifact_closeout as CLOSE  # noqa: E402


def progress_rows():
    rows = [{
        "clusters": CLOSE.C1.TOTAL_CLUSTERS,
        "freeze_receipt_sha256": CLOSE.FREEZE_SHA256,
        "git": CLOSE.ORIGINAL_GIT,
        "namespace": CLOSE.C1.RUN_NAMESPACE,
        "shards": CLOSE.C1.SHARD_COUNT,
        "status": "ADMITTED",
        "time_ns": 1,
    }, {
        "status": "SHARDS_RUNNING", "time_ns": 2,
        "workers": CLOSE.C1.SHARD_COUNT,
    }]
    rows.extend({
        "complete": complete,
        "shard": shard,
        "status": "SHARD_COMPLETE",
        "time_ns": 3 + complete,
        "total": CLOSE.C1.SHARD_COUNT,
    } for complete, shard in enumerate((3, 0, 1, 7, 5, 6, 2, 4), 1))
    rows.append({
        "error": CLOSE.EXPECTED_REFUSAL,
        "production_promotion": False,
        "status": "SUPERVISOR_REFUSED",
        "time_ns": 20,
    })
    return rows


def test_exact_late_refusal_closes_only_after_all_eight_shards():
    assert CLOSE.supervisor_progress_problems(progress_rows()) == []

    changed = copy.deepcopy(progress_rows())
    changed.pop(-2)
    assert "supervisor exact eight-shard completion" in \
        CLOSE.supervisor_progress_problems(changed)

    changed = copy.deepcopy(progress_rows())
    changed[-1]["error"] = (
        "ProtocolRefused: RLCB-C1 refuses a dirty tree: M source.py")
    assert "supervisor exact late refusal reason" in \
        CLOSE.supervisor_progress_problems(changed)


def test_completed_or_shard_refused_supervisor_cannot_be_recharacterized():
    changed = copy.deepcopy(progress_rows())
    changed[-1]["status"] = "COMPLETE"
    problems = CLOSE.supervisor_progress_problems(changed)
    assert "supervisor unique terminal refusal" in problems
    assert "supervisor falsely completed or a shard refused" in problems

    changed = copy.deepcopy(progress_rows())
    changed.insert(-1, {
        "status": "REFUSED", "shard": 0, "exit_code": 3, "time_ns": 19})
    assert "supervisor falsely completed or a shard refused" in \
        CLOSE.supervisor_progress_problems(changed)


def test_closeout_contract_is_non_replay_and_non_production():
    source = Path(CLOSE.__file__).read_text()
    assert '"games_generated": 0' in source
    assert '"shards_retried": 0' in source
    assert '"statistics_changed": False' in source
    assert '"production_promotion": False' in source
    assert '"automatic_deployment": False' in source
    assert "run_arm(" not in source
    assert "supervise(" not in source
    assert "flyctl" not in source.lower()


def test_closeout_constants_bind_the_existing_terminal_bytes():
    assert CLOSE.ORIGINAL_GIT == \
        "ced1033e47bcb27b82136f72c757de40387a94f0"
    assert CLOSE.SUPERVISOR_PROGRESS_SHA256 == \
        "d3bb6aa9c2385cb57c84a5f65bd04d66bd99849570c5e913458228a6f5c1df8a"
    assert CLOSE.AGGREGATE_SHA256 == \
        "83f5a9df2f1db1fa45d50fb005b941b776d9ecc2c9f8703d3d62efff8f5ef5ea"
