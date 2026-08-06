"""The S0 fleet packet is executable protocol, not prose."""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s0_aggregate as AGG  # noqa: E402
import s0_override_audit as AUDIT  # noqa: E402
import s0_run as S0  # noqa: E402


def rec(label, seed, flip, utility, policy=None):
    counters = {"sample_attempts": 2, "accepted_worlds": 2,
                "failed_worlds": 0, "short_searches": 0, "zero_world": 0}
    return {"label": label, "seed": seed, "flip": flip,
            "policy": policy or label, "level_utility": utility,
            "arm": dict(counters), "opp": dict(counters)}


def block(values):
    return [rec(label, seed, flip, value)
            for label, value in values.items()
            for seed in (1, 2) for flip in (0, 1)]


def by_label(rows):
    out = {}
    for row in rows:
        out.setdefault(row["label"], []).append(row)
    return out


def test_all_frozen_s0_policy_contracts_are_live():
    for phase in S0.PROTOCOLS:
        assert S0.protocol_problems(phase) == []
    assert S0.TOTAL_CLUSTERS == 2048
    assert S0.SHARD_COUNT == 8
    assert S0.CLUSTERS_PER_SHARD == 256


def test_record_gate_requires_paired_coverage_and_reconciled_exact_work():
    rows = by_label(block({"a": 1, "b": 0}))
    assert S0.record_problems(rows) == []
    rows["a"][0]["arm"]["short_searches"] = 1
    assert "a: short registered search dose" in S0.record_problems(rows)
    rows["a"][0]["arm"]["short_searches"] = 0
    rows["a"].pop()
    assert any("deal coverage differs" in p for p in S0.record_problems(rows))


def test_s0a_survivor_rule_is_frozen_and_not_a_promotion():
    rows = by_label(block({"report_mean": 2.0, "report_lcb": 1.0,
                           "uniform_work": 0.5, "null": 0.0,
                           "reference": 0.0}))
    survivor, stats = AGG.choose_survivor("s0a", rows)
    assert survivor == "report_mean"
    assert stats["report_mean-reference"]["mean"] > \
        stats["uniform_work-reference"]["mean"]

    rows = by_label(block({"report_mean": 0.2, "report_lcb": 0.1,
                           "uniform_work": 0.5, "null": 0.0,
                           "reference": 0.0}))
    survivor, _ = AGG.choose_survivor("s0a", rows)
    assert survivor is None, "extra uniform compute explained the apparent gain"


def test_s0b_adaptive_must_beat_both_uniform_and_random_allocation():
    rows = by_label(block({"adaptive": 2.0, "report_uniform": 1.0,
                           "random": 0.5, "uniform_work": 0.0,
                           "null": 0.0, "reference": 0.0}))
    survivor, _ = AGG.choose_survivor("s0b-lcb", rows)
    assert survivor == "adaptive"
    rows = by_label(block({"adaptive": 2.0, "report_uniform": 1.0,
                           "random": 3.0, "uniform_work": 0.0,
                           "null": 0.0, "reference": 0.0}))
    survivor, _ = AGG.choose_survivor("s0b-lcb", rows)
    assert survivor == "report_uniform"


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
