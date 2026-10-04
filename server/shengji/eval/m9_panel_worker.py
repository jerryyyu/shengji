"""In-memory composition of the fixed M9 panel jobs.

This worker delegates sampling/scoring to the reviewed panel adapter and
hands each completed panel to the caller's persistence callback.  Those
factory/collector calls can perform scientific work; this module itself does
not read files, load models, retry failures, or provide launch/permission
authority.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .m9_panel_plan import ROOTS, build_m9_panel_plan
from .m9_replay_binding import validate_m9_replay
from .public_fixture_panel import collect_public_fixture_panel


def _fixture_id(fixture: Any) -> Any:
    return getattr(fixture, "id", None)


def _strict_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be a strict integer")
    return value


def _validate_panel(panel: Any, job: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(panel, Mapping):
        raise ValueError("panel collector must return an object")
    if panel.get("schema") != "public-fixture-panel-v1":
        raise ValueError("panel schema mismatch")
    for key in ("fixture_id", "mode", "seed", "fill_seed", "checkpoint_sha256"):
        if panel.get(key) != job[key]:
            raise ValueError(f"panel {key} differs from planned job")
    _strict_int(panel.get("seed"), "panel.seed")
    if _strict_int(panel.get("fill_seed"), "panel.fill_seed") != 0:
        raise ValueError("panel.fill_seed must be 0")
    if _strict_int(panel.get("legal_count"), "panel.legal_count") != job["expected_legal_count"]:
        raise ValueError("panel legal pool size differs from planned job")
    effective = panel.get("effective")
    if not isinstance(effective, Mapping):
        raise ValueError("panel.effective must be an object")
    if _strict_int(effective.get("worlds"), "panel.effective.worlds") != 64:
        raise ValueError("panel effective world count must be strict 64")
    return panel


def collect_m9_panels(saved_analysis, fixtures, bot_factory_for_seed, *,
                      on_panel, check_budget=None):
    """Collect the fixed 15-job panel, delivering each result immediately.

    ``on_panel`` owns persistence of partial progress.  A successful return is
    only a collection-process receipt; provenance and served-choice claims
    remain false.
    """
    if not callable(bot_factory_for_seed):
        raise ValueError("bot_factory_for_seed must be callable")
    if not callable(on_panel):
        raise ValueError("on_panel callback is required")
    if check_budget is not None and not callable(check_budget):
        raise ValueError("check_budget must be callable")
    if (isinstance(fixtures, (str, bytes, bytearray))
            or not isinstance(fixtures, Sequence)):
        raise ValueError("fixtures must be a sequence")
    if len(fixtures) != len(ROOTS):
        raise ValueError("fixtures must contain exactly four roots")
    # Freeze every caller fixture before the first dispatch. A callback is
    # allowed to retain or mutate its detached record without changing later
    # jobs' roots.
    fixture_snapshot = copy.deepcopy(tuple(fixtures))
    fixture_ids = [_fixture_id(fixture) for fixture in fixture_snapshot]
    if (any(type(fixture_id) is not str for fixture_id in fixture_ids)
            or len(set(fixture_ids)) != len(ROOTS)
            or set(fixture_ids) != set(ROOTS)):
        raise ValueError("fixtures must be exactly the four unique planned roots")
    fixture_by_id = dict(zip(fixture_ids, fixture_snapshot))

    analysis_copy = copy.deepcopy(saved_analysis)
    plan = build_m9_panel_plan(analysis_copy)
    for job in plan:
        if check_budget is not None:
            check_budget()
        fixture = copy.deepcopy(fixture_by_id[job["fixture_id"]])
        panel = collect_public_fixture_panel(
            lambda seed=job["seed"]: bot_factory_for_seed(seed),
            fixture,
            job["control_ballot"], job["treatment_ballot"],
            mode=job["mode"], seed=job["seed"], fill_seed=job["fill_seed"],
            expected_legal_count=job["expected_legal_count"],
            check_budget=check_budget)
        panel = _validate_panel(panel, job)
        if job["require_m9_replay_match"]:
            replay = validate_m9_replay(panel, analysis_copy)
        else:
            replay = None
        record = {
            "job": copy.deepcopy(job),
            "panel": copy.deepcopy(panel),
            "replay_consistency": copy.deepcopy(replay),
            "ledger_cadence": ("fresh-root" if job["mode"] == "fresh-root"
                                else "single-seat-actor-turns"),
        }
        on_panel(record)
    return {
        "schema": "m9-panel-collection-v1",
        "completed_panels": len(plan),
        "primary_panels": sum(job["role"] == "primary" for job in plan),
        "secondary_panels": sum(job["role"] == "secondary" for job in plan),
        "provenance_verified": False,
        "serving_choice_assessed": False,
    }


__all__ = ["collect_m9_panels"]
