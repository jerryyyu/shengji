"""The frozen S0 override audit is an immutable, recomputable artifact.

Split out of ``test_s0_protocol.py`` on 2026-09-05 when the S0 campaign
scripts were removed.  ``scripts/s0_override_audit.py`` stays because it is
the predeclared DEV calibration that chose ``S0_REPORT_WORLDS`` (see the
comment in ``shengji/ai/registry.py``), and CORRECTNESS.md names
``tests/data/s0_override_audit.v1.json`` as the immutable asset.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s0_override_audit as AUDIT  # noqa: E402


def test_report_dose_is_chosen_by_the_frozen_rule_not_by_prose():
    detailed = []
    for gap in (2.0, 1.0, -1.0, -2.0):
        grid = []
        for n in AUDIT.DOSE_GRID:
            # n=30 falsely supports one negative; n>=60 is sign-clean and
            # retains both positives, so the registered smallest dose is 60.
            lcb = 1.0 if gap > 0 or (n == 30 and gap == -1.0) else -1.0
            grid.append({"gap": gap, "lcb_gt_0": lcb > 0})
        detailed.append({"report": {"gap": gap}, "dose_grid": grid})
    choice = AUDIT.choose_report_dose(detailed)
    assert choice["selected"] == 60
    assert choice["rule_satisfied"] is True


def test_frozen_override_audit_recomputes_and_is_immutable():
    path = Path(__file__).with_name("data") / "s0_override_audit.v1.json"
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == \
        "9703b50817fb03622c3739e44f73e19083b1e8337300be7054774e2308e13ef5"
    artifact = json.loads(raw)
    assert artifact["schema"] == AUDIT.SCHEMA
    assert artifact["tree_dirty"] is False
    assert len(artifact["decisions"]) == 150
    assert len({x["state_key"] for x in artifact["decisions"]}) == 150
    assert len(artifact["overrides"]) == 20
    assert all(len(x["paired_deltas"]) == 300
               and x["report"]["complete"] for x in artifact["overrides"])
    gaps = [x["report"]["gap"] for x in artifact["overrides"]]
    assert sum(g > 0 for g in gaps) == artifact["summary"]["positive_report_gap"]
    assert statistics.fmean(gaps) == \
        artifact["summary"]["mean_report_gap"]
    assert AUDIT.choose_report_dose(artifact["overrides"])["selected"] == 300
    supported_roles = {
        row["role"] for row in artifact["overrides"]
        if row["dose_grid"][-1]["lcb_gt_0"]
    }
    assert supported_roles == {"attacker", "defender"}, \
        "real signed DEV witnesses must force positive report overrides for " \
        "both acting-team roles; a never-override policy must not pass"

    from shengji.ai.registry import S0_REPORT_WORLDS

    assert S0_REPORT_WORLDS == artifact["summary"]["selected_report_worlds"]
