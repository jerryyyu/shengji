"""Exclusive partial evidence for an externally authorized M9 collection.

This is not a launcher, RELEASE check, seal, or scientific acceptance gate.
The caller must supply the reviewed runtime/model recipe and process wrapper.
Real factory calls perform scientific work. No retry or recovery is provided.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from ..luna.atomic_io import publish_exclusive_bytes
from .m9_panel_plan import build_m9_panel_plan
from .m9_panel_worker import collect_m9_panels


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def run_m9_panel_collection(saved_analysis, fixtures, bot_factory_for_seed, *,
                            output_dir, check_budget=None):
    """Persist raw and validated panels separately in a never-reused directory.

    Raw panels are published BEFORE validation so a mismatch can be diagnosed
    without recollection. A validated file records helper checks, not artifact
    authentication or strategic quality. Uncatchable process death may leave
    only partial files; absence of a terminal receipt is never success.
    The worker retains replay ValueError as primary if failure-record delivery
    is interrupted; the interrupt is preserved as its cause in terminal data.
    """
    analysis = copy.deepcopy(saved_analysis)
    jobs = build_m9_panel_plan(analysis)
    analysis_sha256 = hashlib.sha256(_json_bytes(analysis)).hexdigest()
    output = Path(output_dir)
    output.mkdir(mode=0o700)  # existing directory/symlink consumes no new work
    collected = validated = 0

    def publish(name, value):
        publish_exclusive_bytes(output / name, _json_bytes(value), mode=0o400)

    def on_collected(record):
        nonlocal collected
        if collected != validated or collected >= len(jobs):
            raise ValueError("unexpected raw panel publication order")
        if record["job"] != jobs[collected]:
            raise ValueError("raw panel job differs from fixed plan")
        publish(f"collected-{collected:03d}.json", record)
        collected += 1

    def on_panel(record):
        nonlocal validated
        if collected != validated + 1 or record["job"] != jobs[validated]:
            raise ValueError("unexpected validated panel publication order")
        if record.get("validation_status") == "failed":
            publish(f"rejected-{validated:03d}.json", record)
            return  # worker rethrows; never count this as validated
        if record.get("validation_status") != "passed":
            raise ValueError("missing explicit panel validation status")
        publish(f"validated-{validated:03d}.json", record)
        validated += 1

    def terminal(status, **fields):
        return {"schema": "m9-panel-terminal-v1", "status": status,
                "collected_count": collected, "validated_count": validated,
                "provenance_verified": False, **fields}

    try:
        publish("plan.json", {"schema": "m9-panel-attempt-v1", "jobs": jobs,
                              "analysis_sha256": analysis_sha256,
                              "provenance_verified": False})
        receipt = collect_m9_panels(
            analysis, fixtures, bot_factory_for_seed,
            on_panel=on_panel, on_collected=on_collected,
            check_budget=check_budget)
        if collected != len(jobs) or validated != len(jobs):
            raise ValueError("incomplete panel publication population")
    except BaseException as exc:
        try:
            publish("terminal.json", terminal(
                "failed", error_type=type(exc).__name__, error=str(exc),
                error_cause_type=(type(exc.__cause__).__name__
                                  if exc.__cause__ is not None else None),
                error_cause=(str(exc.__cause__) if exc.__cause__ is not None else None),
                error_notes=list(getattr(exc, "__notes__", []))))
        except BaseException as evidence_error:
            # Keep the original failure and all staged bytes; never repair or
            # overwrite a failed publication. The process wrapper owns stderr.
            exc.add_note(f"failed to publish terminal evidence: {evidence_error!r}")
        raise
    result = terminal("complete", receipt=receipt)
    publish("terminal.json", result)
    return result
