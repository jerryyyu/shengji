"""The S0 fleet packet is executable protocol, not prose."""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s0_aggregate as AGG  # noqa: E402
import s0_override_audit as AUDIT  # noqa: E402
import s0_packet as PACKET  # noqa: E402
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


def runtime_identity(binary="binary-a"):
    return {
        "host": "mini", "python": "3.14.6",
        "fast_engine": True, "require_voids": True,
        "digests": {"fast_binary": binary, "runner": "runner-a"},
    }


def test_all_frozen_s0_policy_contracts_are_live():
    for phase in S0.PROTOCOLS:
        assert S0.protocol_problems(phase) == []
    assert S0.TOTAL_CLUSTERS == 2048
    assert S0.SHARD_COUNT == 8
    assert S0.CLUSTERS_PER_SHARD == 256
    for phase in ("s0a", "s0b-mean", "s0b-lcb"):
        assert S0.phase_total_clusters(phase) == 2048
        assert S0.phase_clusters_per_shard(phase) == 256
    for phase in ("s0c-report-mean", "s0c-report-lcb",
                  "s0c-adaptive-mean", "s0c-adaptive-lcb"):
        assert S0.PROTOCOLS[phase]["kind"] == "confirmation"
        assert S0.phase_total_clusters(phase) == 8192
        assert S0.phase_clusters_per_shard(phase) == 1024
        assert S0.PROTOCOLS[phase]["seed0"] == 135_000_000


def test_record_gate_requires_paired_coverage_and_reconciled_exact_work():
    rows = by_label(block({"a": 1, "b": 0}))
    assert S0.record_problems(rows) == []
    rows["a"][0]["arm"]["short_searches"] = 1
    assert "a: short registered search dose" in S0.record_problems(rows)
    rows["a"][0]["arm"]["short_searches"] = 0
    rows["a"][0]["arm"]["void_fallbacks"] = 1
    assert "a: void-relaxed sampled world" in S0.record_problems(rows)
    rows["a"][0]["arm"]["void_fallbacks"] = 0
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
    assert stats["report_mean-uniform_work"]["mean"] > 0

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


def test_s0_confirmation_requires_superiority_and_a_clean_null():
    rows = by_label(block({"arm": 2.0, "null": 0.0, "reference": 0.0}))
    survivor, stats = AGG.choose_survivor("s0c-report-lcb", rows)
    assert survivor == "arm"
    assert stats["arm-reference"]["mean"] > 0
    assert stats["arm-null"]["mean"] > 0

    # Beating current is not attributable when the arm cannot beat the null.
    rows = by_label(block({"arm": 2.0, "null": 2.0, "reference": 0.0}))
    survivor, _ = AGG.choose_survivor("s0c-report-lcb", rows)
    assert survivor is None

    # A null that independently clears the bar invalidates confirmation.
    rows = by_label(block({"arm": 3.0, "null": 2.0, "reference": 0.0}))
    survivor, _ = AGG.choose_survivor("s0c-report-lcb", rows)
    assert survivor is None


def test_child_phases_are_bound_to_the_exact_parent_aggregate(tmp_path):
    parent = {
        "schema": "s0-mechanism-aggregate-v1",
        "phase": "s0a", "promotion": False, "git_sha": "abc",
        "clusters": 2048, "survivor_label": "report_mean",
        "survivor_policy": "mc-s0-report-mean",
        "runtime_identity": runtime_identity(),
    }
    path = tmp_path / "s0a.aggregate.json"
    path.write_text(json.dumps(parent))
    identity = S0.parent_identity(
        str(path), S0.PROTOCOLS["s0b-mean"], "abc", runtime_identity())
    assert identity["phase"] == "s0a"
    assert identity["survivor_policy"] == "mc-s0-report-mean"
    assert len(identity["sha256"]) == 64

    with pytest.raises(SystemExit, match="does not admit"):
        S0.parent_identity(str(path), S0.PROTOCOLS["s0b-lcb"], "abc",
                           runtime_identity())
    with pytest.raises(SystemExit, match="required via --parent"):
        S0.parent_identity(None, S0.PROTOCOLS["s0b-mean"], "abc",
                           runtime_identity())
    with pytest.raises(SystemExit, match="has no parent"):
        S0.parent_identity(str(path), S0.PROTOCOLS["s0a"], "abc",
                           runtime_identity())
    with pytest.raises(SystemExit, match="runtime identity"):
        S0.parent_identity(str(path), S0.PROTOCOLS["s0b-mean"], "abc",
                           runtime_identity("binary-b"))


def test_aggregate_requires_the_literal_frozen_seed_flip_set(
        tmp_path, monkeypatch):
    phase = "tiny-confirm"
    labels = {"arm": "mc-s0-report-mean", "null": "mc-strong-null",
              "reference": "mc-strong"}
    monkeypatch.setitem(S0.PROTOCOLS, phase, {
        "kind": "confirmation", "seed0": 1, "total_clusters": 2,
        "shard_count": 1, "parent_phase": "tiny-parent",
        "parent_policy": "mc-s0-report-mean", "labels": labels,
        "selection": "test-only frozen confirmation",
    })
    record_path = str(tmp_path / "tiny.jsonl")
    manifest = {
        "complete": True, "problems": [], "promotable": True,
        "tree_dirty": False, "fast_engine": True, "require_voids": True,
        "shard_index": 0, "shard_count": 1, "total_clusters": 2,
        "clusters": 2, "seed0": 1, "seed_hi": 2, "run_id": "tiny-run",
        "labels": labels,
        **runtime_identity(),
    }
    manifests = [(record_path + ".manifest.json", manifest)]
    records = by_label(block({"arm": 2.0, "null": 0.0,
                              "reference": 0.0}))
    for label, recs in records.items():
        for row in recs:
            row["run"] = "tiny-run"
            row["policy"] = labels[label]
            row["_source"] = record_path
    assert AGG.validate(phase, manifests, records) == []
    records["arm"][0]["seed"] = 99
    assert "arm: exact seed/flip coverage differs" in \
        AGG.validate(phase, manifests, records)


def test_runtime_identity_is_parent_bound_and_cross_phase_drift_refuses(tmp_path):
    runtime = runtime_identity()
    parent = {"sha256": "a" * 64, "phase": "s0a"}
    manifests = [("child.manifest.json", {
        "parent": parent, **runtime,
    })]
    assert AGG.runtime_identity(manifests) == runtime
    bound = AGG.aggregate_parent_identity(manifests, runtime)
    assert bound["sha256"] == parent["sha256"]
    assert bound["runtime_identity"] == runtime

    phase_a = tmp_path / "a.json"
    phase_b = tmp_path / "b.json"
    values = {
        "s0a": (phase_a, {"runtime_identity": runtime}),
        "s0b-mean": (phase_b, {"runtime_identity": runtime}),
    }
    phase_manifests = {
        "s0a": [(phase_a, runtime)],
        "s0b-mean": [(phase_b, runtime)],
    }
    assert PACKET.verify_runtime_chain(
        values, phase_manifests, expected=runtime) == runtime

    drift = runtime_identity("binary-b")
    values["s0b-mean"][1]["runtime_identity"] = drift
    phase_manifests["s0b-mean"] = [(phase_b, drift)]
    with pytest.raises(RuntimeError, match="cross-phase runtime identity drift"):
        PACKET.verify_runtime_chain(values, phase_manifests, expected=runtime)


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
