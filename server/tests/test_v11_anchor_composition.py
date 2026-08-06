"""Falsifying contract tests for the blind V11/search composition lane."""
from __future__ import annotations

import argparse
import copy
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import v11_anchor_composition as COMP  # noqa: E402
import v11_revalidate as DIRECT  # noqa: E402
import shengji.evaluation as EVAL  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.ballot import ballot_for_policy  # noqa: E402


def _upper(bot):
    return {name: getattr(bot, name) for name in dir(bot) if name.isupper()}


@pytest.mark.parametrize(("champion", "null"), [
    ("mc-strong", "mc-strong-null"),
    ("mc-s0-report-lcb", "mc-s0-report-lcb-null"),
    ("mc-s0-adaptive", "mc-s0-adaptive-null"),
])
def test_champion_null_is_exact_policy_with_only_a_shifted_rng(champion, null):
    base = make_bot(champion, seed=17)
    control = make_bot(null, seed=17)
    assert _upper(control) == _upper(base)
    assert type(control.rollout_policy) is type(base.rollout_policy)
    assert control.rng.getstate() != base.rng.getstate()
    assert ballot_for_policy(null).digest == ballot_for_policy(champion).digest


def test_blind_protocol_freezes_both_seed_blocks_and_all_champion_lanes():
    assert COMP.SHARD_COUNT == 8
    assert COMP.PROTOCOLS == {
        "screen": {
            "seed0": 137_000_000, "clusters": 2_048,
            "clusters_per_shard": 256,
            "claim": "blind_non_promotable_protected_composition_screen",
        },
        "confirm": {
            "seed0": 138_000_000, "clusters": 8_192,
            "clusters_per_shard": 1_024,
            "claim": "independent_protected_composition_strength_confirmation",
        },
    }
    for champion in COMP.CHAMPION_LANES:
        labels = COMP.labels_for(champion)
        assert set(labels) == {"anchor", "random", "champion", "null"}
        assert labels["champion"] == champion
        assert COMP.protocol_problems(champion) == []

    # The already-running direct policy gate remains its frozen 121M question.
    assert DIRECT.SEED0 == 121_000_000
    assert DIRECT.SEED_HI == 121_002_047
    assert DIRECT.LABELS == {
        "arm": "rl-override-v11pair",
        "null": "mc-strong-null",
        "reference": "mc-strong",
    }
    assert COMP.DIRECT_GIT_SHA == \
        "e66b90bc3a50d514472670ea99909add5ea30d19"


def _contrast(mean, half):
    return {"mean": mean, "half_width_95": half}


def _direct_aggregate(*, null_sane=True):
    stats = {
        "arm-reference": {
            "a": "arm", "b": "reference", "mean": 0.10,
            "half_width_95": 0.20, "clusters": 2_048,
        },
        "arm-null": {
            "a": "arm", "b": "null", "mean": 0.09,
            "half_width_95": 0.20, "clusters": 2_048,
        },
        "null-reference": {
            "a": "null", "b": "reference",
            "mean": 0.01 if null_sane else 0.20,
            "half_width_95": 0.10, "clusters": 2_048,
        },
    }
    criteria = DIRECT.gate_criteria(stats)
    counters = {
        label: {
            side: {
                "rollouts": 0, "searches": 0, "sample_attempts": 0,
                "accepted_worlds": 0, "failed_worlds": 0,
                "rejected_worlds": 0, "short_searches": 0,
                "zero_world": 0, "void_fallbacks": 0,
            }
            for side in ("arm", "opp")
        }
        for label in DIRECT.LABELS
    }
    return {
        "schema": DIRECT.AGGREGATE_SCHEMA,
        "git_sha": COMP.DIRECT_GIT_SHA,
        "clusters": 2_048, "seed0": 121_000_000,
        "seed_hi": 121_002_047,
        "checkpoint_sha256": COMP.CHECKPOINT_SHA256,
        "runtime_identity": {
            "host": "air", "python": "3.14.6", "fast_engine": True,
            "require_voids": True,
            "digests": {
                **COMP.DIRECT_SOURCE_SHA256,
                "fast_binary": "9" * 64,
            },
        },
        "shards": [f"direct-{i}.manifest.json" for i in range(8)],
        "record_counts": {label: 4_096 for label in DIRECT.LABELS},
        "counter_totals": counters,
        "stats": stats, "criteria": criteria,
        "anchor_test_authorized": criteria["all"],
        "production_promotion": False,
    }


def test_gate_requires_three_superiority_lcbs_and_a_clean_matched_null():
    passing = {
        "anchor-champion": _contrast(0.30, 0.20),
        "anchor-random": _contrast(0.29, 0.20),
        "anchor-null": _contrast(0.28, 0.20),
        "null-champion": _contrast(0.01, 0.10),
    }
    assert COMP.gate_criteria(passing)["all"] is True
    for key in ("anchor-champion", "anchor-random", "anchor-null"):
        failed = copy.deepcopy(passing)
        failed[key] = _contrast(0.10, 0.20)
        assert COMP.gate_criteria(failed)["all"] is False
    failed = copy.deepcopy(passing)
    failed["null-champion"] = _contrast(0.20, 0.10)
    assert COMP.gate_criteria(failed)["all"] is False


def test_direct_parent_requires_protocol_and_null_but_not_superiority(
        monkeypatch, tmp_path):
    path = tmp_path / "direct.aggregate.json"
    payload = _direct_aggregate()
    assert payload["anchor_test_authorized"] is False
    path.write_text(json.dumps(payload))
    parent = COMP.load_direct_parent(path, COMP.sha256(path))
    assert parent["criteria"] == payload["criteria"]
    assert parent["anchor_test_authorized"] is False
    assert parent["standalone_superiority_required"] is False

    with pytest.raises(COMP.ProtocolRefused, match="digest mismatch"):
        COMP.load_direct_parent(tmp_path / "missing.json", "0" * 64)

    broken = _direct_aggregate()
    broken["record_counts"]["arm"] -= 1
    path.unlink()
    path.write_text(json.dumps(broken))
    with pytest.raises(COMP.ProtocolRefused, match="record counts"):
        COMP.load_direct_parent(path, COMP.sha256(path))

    wrong_commit = _direct_aggregate()
    wrong_commit["git_sha"] = "1" * 40
    path.unlink()
    path.write_text(json.dumps(wrong_commit))
    with pytest.raises(COMP.ProtocolRefused, match="frozen git identity"):
        COMP.load_direct_parent(path, COMP.sha256(path))

    wrong_source = _direct_aggregate()
    wrong_source["runtime_identity"]["digests"]["runner"] = "2" * 64
    path.unlink()
    path.write_text(json.dumps(wrong_source))
    with pytest.raises(COMP.ProtocolRefused, match="runtime/source identity"):
        COMP.load_direct_parent(path, COMP.sha256(path))

    unsane = _direct_aggregate(null_sane=False)
    path.unlink()
    path.write_text(json.dumps(unsane))
    with pytest.raises(COMP.ProtocolRefused, match="matched-null"):
        COMP.load_direct_parent(path, COMP.sha256(path))

    changed_verdict = _direct_aggregate()
    changed_verdict["anchor_test_authorized"] = True
    path.unlink()
    path.write_text(json.dumps(changed_verdict))
    with pytest.raises(COMP.ProtocolRefused, match="original authorization"):
        COMP.load_direct_parent(path, COMP.sha256(path))

    monkeypatch.setattr(
        DIRECT, "protocol_problems", lambda: ["current policy drift"])
    valid = _direct_aggregate()
    path.unlink()
    path.write_text(json.dumps(valid))
    with pytest.raises(COMP.ProtocolRefused, match="current policy drift"):
        COMP.load_direct_parent(path, COMP.sha256(path))


def _select_none_packet():
    manifests = "; ".join(f"m{i} sha256={'a' * 64}" for i in range(8))
    return "\n".join([
        "STATE: S0_COMPLETE_SELECT_NONE",
        "HEAD / origin / dirty: HEAD=x; origin/main=x; dirty=''",
        f"s0a manifests (8/8): {manifests}",
        f"s0a aggregate: a.json sha256={'b' * 64} survivor=None promotion=False",
        "s0a coverage: records={}; seeds=1..2; flips=[0,1]; exact=true",
        ("s0a provenance: host=h; python=3; compiled_binary_sha256=x; "
         "within_phase=true; cross_phase=true; frozen_identity=true"),
        "s0a sampler counters: {}",
        "S0a effects:",
        "S0b: NOT REACHED",
        "S0c: NOT REACHED",
        ("Final production decision from registered rule: SELECT NONE; "
         "production remains mc-strong"),
        "CALIB / REPORT: sealed and unscored",
        "",
    ])


def test_terminal_s0_parent_is_hash_bound_and_derives_the_champion(tmp_path):
    packet = tmp_path / "s0-final-packet.txt"
    packet.write_text(_select_none_packet())
    packet_sha = COMP.sha256(packet)
    closeout = tmp_path / "s0-closeout.json"
    closeout.write_text(json.dumps({
        "schema": "s0-terminal-closeout-v1",
        "state": "S0_COMPLETE_SELECT_NONE",
        "packet_sha256": packet_sha,
        "phases": ["s0a"],
    }))
    closeout_sha = COMP.sha256(closeout)

    parent = COMP.load_s0_parent(
        packet, packet_sha, closeout, closeout_sha)
    assert parent["champion_policy"] == "mc-strong"
    assert parent["packet_sha256"] == packet_sha
    with pytest.raises(COMP.ProtocolRefused, match="packet digest"):
        COMP.load_s0_parent(packet, "0" * 64, closeout, closeout_sha)


def test_confirmation_parent_rederives_screen_gate_and_stays_blind(
        monkeypatch, tmp_path):
    s0_parent = {
        "terminal_state": "S0_COMPLETE_SELECT_NONE",
        "champion_policy": "mc-strong", "packet_sha256": "b" * 64,
        "closeout_sha256": "c" * 64, "phases": ["s0a"],
        "verification_boundary": "test",
    }
    labels = COMP.labels_for("mc-strong")
    direct_path = tmp_path / "direct.aggregate.json"
    direct_path.write_text(json.dumps(_direct_aggregate()))
    direct_parent = COMP.load_direct_parent(
        direct_path, COMP.sha256(direct_path))
    monkeypatch.setattr(
        COMP, "policy_contract", lambda name: {"policy": name})
    monkeypatch.setattr(
        COMP, "arm_ballots", lambda names: {name: "ballot" for name in names})
    stats = {
        "anchor-champion": _contrast(0.30, 0.20),
        "anchor-random": _contrast(0.29, 0.20),
        "anchor-null": _contrast(0.28, 0.20),
        "null-champion": _contrast(0.01, 0.10),
    }
    payload = {
        "schema": COMP.AGGREGATE_SCHEMA, "phase": "screen",
        "complete": True, "confirmation_authorized": True,
        "production_promotion": False,
        "seed0": 137_000_000, "seed_hi": 137_002_047,
        "clusters": 2_048, "champion_policy": "mc-strong",
        "s0_parent": s0_parent,
        "direct_v11_parent": direct_parent,
        "direct_v11_usage": COMP.DIRECT_USAGE,
        "labels": labels, "selection_rule": COMP.SELECTION_RULE,
        "checkpoint_sha256": COMP.CHECKPOINT_SHA256,
        "policy_contracts": {name: {"policy": name}
                             for name in labels.values()},
        "ballots": {name: "ballot" for name in labels.values()},
        "stats": stats, "criteria": COMP.gate_criteria(stats),
        "git_sha": "d" * 40,
        "runtime_identity": {"host": "air", "python": "3.14"},
        "input_shards": [
            {"shard_index": i, "manifest_sha256": "e" * 64,
             "records_sha256": "f" * 64,
             "manifest_path": f"screen-{i}.manifest.json",
             "records_path": f"screen-{i}.jsonl"}
            for i in range(8)
        ],
    }
    evidence_calls = []
    monkeypatch.setattr(
        COMP, "revalidate_screen_evidence",
        lambda *args: evidence_calls.append(args) or [])
    path = tmp_path / "screen.json"
    path.write_text(json.dumps(payload))
    parent = COMP.load_screen_parent(path, COMP.sha256(path), s0_parent)
    assert parent["confirmation_authorized"] is True
    assert len(evidence_calls) == 1

    payload["direct_v11_usage"] = {
        **COMP.DIRECT_USAGE, "standalone_authorization_used": True}
    path.unlink()
    path.write_text(json.dumps(payload))
    with pytest.raises(COMP.ProtocolRefused, match="changed direct-result"):
        COMP.load_screen_parent(path, COMP.sha256(path), s0_parent)


def test_screen_parent_refuses_failed_independent_raw_revalidation(
        monkeypatch, tmp_path):
    """A caller-chosen aggregate digest is not itself an evidence receipt."""
    s0_parent = {
        "terminal_state": "S0_COMPLETE_SELECT_NONE",
        "champion_policy": "mc-strong", "packet_sha256": "b" * 64,
        "closeout_sha256": "c" * 64, "phases": ["s0a"],
        "verification_boundary": "test",
    }
    direct_path = tmp_path / "direct.aggregate.json"
    direct_path.write_text(json.dumps(_direct_aggregate()))
    direct_parent = COMP.load_direct_parent(
        direct_path, COMP.sha256(direct_path))
    labels = COMP.labels_for("mc-strong")
    monkeypatch.setattr(COMP, "policy_contract", lambda name: {"policy": name})
    monkeypatch.setattr(
        COMP, "arm_ballots", lambda names: {name: "ballot" for name in names})
    stats = {
        "anchor-champion": _contrast(0.30, 0.20),
        "anchor-random": _contrast(0.29, 0.20),
        "anchor-null": _contrast(0.28, 0.20),
        "null-champion": _contrast(0.01, 0.10),
    }
    payload = {
        "schema": COMP.AGGREGATE_SCHEMA, "phase": "screen",
        "complete": True, "confirmation_authorized": True,
        "production_promotion": False,
        "seed0": 137_000_000, "seed_hi": 137_002_047,
        "clusters": 2_048, "champion_policy": "mc-strong",
        "s0_parent": s0_parent, "direct_v11_parent": direct_parent,
        "direct_v11_usage": COMP.DIRECT_USAGE,
        "labels": labels, "selection_rule": COMP.SELECTION_RULE,
        "checkpoint_sha256": COMP.CHECKPOINT_SHA256,
        "policy_contracts": {name: {"policy": name}
                             for name in labels.values()},
        "ballots": {name: "ballot" for name in labels.values()},
        "stats": stats, "criteria": COMP.gate_criteria(stats),
        "git_sha": "d" * 40,
        "runtime_identity": {"host": "air", "python": "3.14"},
        "input_shards": [
            {"shard_index": i, "manifest_sha256": "e" * 64,
             "records_sha256": "f" * 64,
             "manifest_path": f"screen-{i}.manifest.json",
             "records_path": f"screen-{i}.jsonl"}
            for i in range(8)
        ],
    }
    path = tmp_path / "screen.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(
        COMP, "revalidate_screen_evidence",
        lambda *args: ["screen shard records digest mismatch"])
    with pytest.raises(COMP.ProtocolRefused, match="records digest mismatch"):
        COMP.load_screen_parent(path, COMP.sha256(path), s0_parent)


def test_bound_screen_inputs_reopen_exact_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(COMP, "SHARD_COUNT", 1)
    aggregate = tmp_path / "screen.aggregate.json"
    aggregate.write_text("{}")
    records = tmp_path / "screen-0.jsonl"
    records.write_text(json.dumps({"label": "anchor", "seed": 1}) + "\n")
    manifest = tmp_path / "screen-0.jsonl.manifest.json"
    manifest.write_text(json.dumps({
        "shard_index": 0, "records_sha256": COMP.sha256(records),
    }))
    inputs = [{
        "shard_index": 0,
        "manifest_path": manifest.name,
        "manifest_sha256": COMP.sha256(manifest),
        "records_path": records.name,
        "records_sha256": COMP.sha256(records),
    }]
    manifests, loaded = COMP.load_bound_screen_inputs(aggregate, inputs)
    assert manifests[0][0] == manifest.resolve()
    assert loaded["anchor"][0]["_source"] == str(records.resolve())

    records.write_text(json.dumps({"label": "anchor", "seed": 2}) + "\n")
    with pytest.raises(COMP.ProtocolRefused, match="records digest mismatch"):
        COMP.load_bound_screen_inputs(aggregate, inputs)


def test_screen_revalidation_recomputes_stats_from_records(monkeypatch):
    records = {}
    utility = {"anchor": 1, "random": -1, "champion": -1, "null": -1}
    for label, value in utility.items():
        records[label] = [
            {"label": label, "seed": seed, "flip": flip,
             "level_utility": value,
             "arm": _clean_counters(), "opp": _clean_counters()}
            for seed in (1, 2) for flip in (0, 1)
        ]
    stats = COMP.all_contrasts(records)
    payload = {
        "input_shards": [],
        "runtime_identity": {"host": "air"},
        "git_sha": "d" * 40,
        "record_counts": {label: len(rows)
                          for label, rows in records.items()},
        "counter_totals": COMP.counter_totals(records),
        "stats": stats,
        "criteria": COMP.gate_criteria(stats),
        "confirmation_authorized": True,
    }
    monkeypatch.setattr(
        COMP, "load_bound_screen_inputs",
        lambda aggregate_path, inputs: ([], records))
    monkeypatch.setattr(COMP, "validate_population", lambda *args: [])
    assert COMP.revalidate_screen_evidence(
        "screen.json", payload, {}, {}) == []

    payload["stats"] = copy.deepcopy(stats)
    payload["stats"]["anchor-champion"]["mean"] += 1
    assert "screen aggregate/raw paired statistics differ" in \
        COMP.revalidate_screen_evidence("screen.json", payload, {}, {})


def test_parent_arguments_require_direct_then_only_the_screen_chain(monkeypatch):
    s0_parent = {"champion_policy": "mc-strong"}
    direct_parent = {"sha256": "a" * 64}
    screen_parent = {
        "direct_v11_parent": direct_parent,
        "confirmation_authorized": True,
    }
    monkeypatch.setattr(COMP, "load_s0_parent", lambda *args: s0_parent)
    monkeypatch.setattr(COMP, "load_direct_parent", lambda *args: direct_parent)
    monkeypatch.setattr(COMP, "load_screen_parent", lambda *args: screen_parent)

    common = dict(
        s0_packet="s0.txt", expected_s0_packet_sha256="b" * 64,
        s0_closeout="s0.json", expected_s0_closeout_sha256="c" * 64,
        direct_aggregate=None, expected_direct_aggregate_sha256=None,
        screen_parent=None, expected_screen_parent_sha256=None,
    )
    with pytest.raises(COMP.ProtocolRefused, match="requires the exact frozen"):
        COMP._parent_args(argparse.Namespace(phase="screen", **common))

    screen_args = {
        **common,
        "direct_aggregate": "direct.json",
        "expected_direct_aggregate_sha256": "d" * 64,
    }
    assert COMP._parent_args(
        argparse.Namespace(phase="screen", **screen_args)) == \
        (s0_parent, direct_parent, None)

    with pytest.raises(COMP.ProtocolRefused, match="requires the exact authorizing"):
        COMP._parent_args(argparse.Namespace(phase="confirm", **common))

    confirm_args = {
        **common,
        "screen_parent": "screen.json",
        "expected_screen_parent_sha256": "e" * 64,
    }
    assert COMP._parent_args(
        argparse.Namespace(phase="confirm", **confirm_args)) == \
        (s0_parent, direct_parent, screen_parent)
    with pytest.raises(COMP.ProtocolRefused, match="inherits direct provenance"):
        COMP._parent_args(argparse.Namespace(
            phase="confirm", **{
                **confirm_args,
                "direct_aggregate": "direct.json",
                "expected_direct_aggregate_sha256": "d" * 64,
            }))


@pytest.mark.parametrize("champion", [
    "mc-s0-report-lcb", "mc-s0-adaptive",
])
def test_promoted_terminal_decision_accepts_only_reachable_lcb_champions(champion):
    text = ("Final production decision from registered rule: "
            f"PROMOTE {champion}\n")
    assert COMP._terminal_decision(text, "S0_COMPLETE_PROMOTE") == champion
    with pytest.raises(COMP.ProtocolRefused, match="unregistered promoted"):
        COMP._terminal_decision(
            "Final production decision from registered rule: PROMOTE mc\n",
            "S0_COMPLETE_PROMOTE")


def _clean_counters():
    return {
        "rollouts": 30, "searches": 1, "sample_attempts": 30,
        "accepted_worlds": 30, "failed_worlds": 0, "rejected_worlds": 0,
        "short_searches": 0, "zero_world": 0, "void_fallbacks": 0,
        "exact_endgames": 0, "exact_endgame_attempts": 0,
        "exact_endgame_refusals": 0, "exact_endgame_budget_exceeded": 0,
        "exact_endgame_sessions": 0, "exact_endgame_nodes": 0,
        "exact_endgame_cache_hits": 0,
    }


def test_run_shard_is_blind_nonpromotable_and_does_not_log_scores(
        monkeypatch, tmp_path):
    runtime = {
        "host": "host", "python": "3.14", "fast_engine": True,
        "require_voids": True, "experimental_sampler_flags": [],
        "digests": {"runner": "a" * 64},
    }
    s0_parent = {
        "terminal_state": "S0_COMPLETE_SELECT_NONE",
        "champion_policy": "mc-strong", "packet_sha256": "b" * 64,
        "closeout_sha256": "c" * 64, "phases": ["s0a"],
        "verification_boundary": "test",
    }
    direct_parent = {
        "schema": DIRECT.AGGREGATE_SCHEMA,
        "sha256": "e" * 64,
        "criteria": {"null_current_interval_contains_0": True, "all": False},
        "anchor_test_authorized": False,
        "standalone_superiority_required": False,
        "matched_null_sanity_required": True,
    }
    monkeypatch.setattr(COMP, "require_runtime", lambda: (object(), runtime))
    monkeypatch.setattr(
        COMP, "_parent_args", lambda args: (s0_parent, direct_parent, None))
    monkeypatch.setattr(COMP, "protocol_problems", lambda champion: [])
    monkeypatch.setattr(
        COMP, "git", lambda *args: "d" * 40
        if args == ("rev-parse", "HEAD") else "")
    monkeypatch.setattr(COMP, "policy_contract", lambda name: {"policy": name})
    monkeypatch.setattr(
        COMP, "arm_ballots", lambda names: {name: "ballot" for name in names})

    calls = []

    def fake_run_arm(label, policy, opponent, clusters, seed0, fh, run_id,
                     progress=True, progress_scores=True):
        calls.append((label, policy, opponent, clusters, seed0,
                      progress, progress_scores))
        rows = []
        for offset in range(clusters):
            for flip in (0, 1):
                row = {
                    "run": run_id, "label": label, "policy": policy,
                    "seed": seed0 + offset, "flip": flip,
                    "won": 1, "level_utility": 1,
                    "arm": _clean_counters(), "opp": _clean_counters(),
                }
                rows.append(row)
                fh.write(json.dumps(row) + "\n")
        return rows

    monkeypatch.setattr(COMP, "run_arm", fake_run_arm)
    out = tmp_path / "screen.jsonl"
    COMP.run_shard(argparse.Namespace(
        phase="screen", shard_index=0, smoke=True, out=str(out)))
    manifest = json.loads(Path(str(out) + ".manifest.json").read_text())
    assert manifest["evidence_grade"] is False
    assert manifest["screen_only"] is True
    assert manifest["production_promotion"] is False
    assert manifest["direct_v11_parent"] == direct_parent
    assert manifest["direct_v11_usage"] == COMP.DIRECT_USAGE
    assert manifest["direct_v11_parent"]["anchor_test_authorized"] is False
    assert "paired" not in manifest, "a shard manifest must not reveal effects"
    assert manifest["records_sha256"] == COMP.sha256(out)
    assert [call[0] for call in calls] == [
        "anchor", "random", "champion", "null"]
    assert all(call[-1] is False for call in calls)


def test_shard_publication_never_replaces_a_concurrent_final(tmp_path):
    partial = tmp_path / "long-run.jsonl.partial"
    final = tmp_path / "long-run.jsonl"
    partial.write_text("our completed evidence\n")
    final.write_text("concurrent evidence\n")
    with pytest.raises(COMP.ProtocolRefused, match="concurrently published"):
        COMP.publish_partial_exclusive(partial, final)
    assert final.read_text() == "concurrent evidence\n"
    assert partial.read_text() == "our completed evidence\n"

    final.unlink()
    COMP.publish_partial_exclusive(partial, final)
    assert final.read_text() == "our completed evidence\n"
    assert not partial.exists()


def test_evaluator_can_report_progress_without_partial_scores(
        monkeypatch, capsys):
    class Bot:
        pass

    monkeypatch.setattr(EVAL, "make_bot", lambda *args, **kwargs: Bot())
    monkeypatch.setattr(EVAL, "Game", lambda rng: object())
    monkeypatch.setattr(
        EVAL, "play_round",
        lambda game, policies: SimpleNamespace(winner_team=0, level_change=1))
    EVAL.run_arm(
        "blind", "p", "o", 51, 10, io.StringIO(), "run",
        progress_scores=False)
    output = capsys.readouterr().out
    assert "blind: 100/102 rounds" in output
    assert "rounds," not in output


def test_record_gate_refuses_sampler_or_out_of_scope_exact_work():
    rows = {
        label: [{"seed": 1, "flip": flip,
                 "arm": _clean_counters(), "opp": _clean_counters()}
                for flip in (0, 1)]
        for label in ("anchor", "random", "champion", "null")
    }
    assert COMP.record_problems(rows) == []
    rows["anchor"][0]["arm"]["exact_endgame_attempts"] = 1
    assert "anchor/arm: nonzero exact_endgame_attempts" in \
        COMP.record_problems(rows)
