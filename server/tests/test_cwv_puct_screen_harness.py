"""The PUCT arm through the REAL screen harness (#436, PUCT P1 ABORT).

Lane PUCT P1 aborted at its first contested decision (cloud, 2026-10-02
01:14:39Z, frozen main-18): ``search_screen.TimedPolicy.decide_play`` reads a
record that carries ``candidates`` as an MC shortlist record and indexes
``rec["report_worlds_requested"]``, which ``CWVPuctBot`` did not publish, so
the 300 s deadline worker relayed ``KeyError: 'report_worlds_requested'``.
The bot-level latency pass and the registry probes never went through that
wrapper.

This drives the lane's own path: the arm registered from
``SHENGJI_CWV_PUCT_*`` (as a spawned worker sees it), ``cwv_shortlist_screen
--arm policy`` for one cluster (both mirrors), under the 300 s deadline worker,
on the synthetic joint package of ``test_cwv_puct_package_prior``.
"""
from __future__ import annotations

import json
import os

import pytest

from shengji.ai import registry
from shengji.ai.cwv_puct import (CWV_PUCT_DECISION_SCHEMA, cwv_puct_registry_entries,
                                 puct_env_recipe)
from shengji.ai.registry import REGISTRY, make_bot
from shengji.train import cwv_shortlist_screen as screen

from test_cwv_puct_package_prior import _write_joint_package

PREFIX = "SHENGJI_CWV_PUCT_"


@pytest.fixture
def puct_arm(tmp_path, monkeypatch):
    path = tmp_path / "tiny-joint.npz"
    sha = _write_joint_package(path, 3)
    for key in [k for k in os.environ if k.startswith(PREFIX)]:
        monkeypatch.delenv(key)
    env = {"CKPT": str(path), "SHA256": sha, "SIMULATIONS": "4", "PRIOR": "package",
           "LEAF_FINISH_TRICK": "1", "WORLD_POOL": "2", "BATCH": "2"}
    for key, value in env.items():
        monkeypatch.setenv(PREFIX + key, value)
    recipe = puct_env_recipe()
    names = sorted(cwv_puct_registry_entries(recipe.pop("checkpoint"),
                                             recipe.pop("simulations"), **recipe))
    registry._register_cwv_puct_from_env()
    arm = f"mc-cwvpuct-{sha[:8]}-s4-pprior-ftl"
    assert arm in names and arm in REGISTRY
    try:
        yield arm
    finally:
        for name in names:
            REGISTRY.pop(name, None)


def test_puct_arm_plays_one_cluster_through_the_deadline_worker(puct_arm, tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    probe = make_bot(puct_arm, seed=0)
    assert type(probe).__name__.startswith("CWVPuct_s4_w2_k2")
    out = tmp_path / "puct"
    screen.main(["--arm", "policy", "--arm-policy", puct_arm, "--out", str(out),
                 "--clusters", "1", "--workers", "1", "--seed0", "36360910",
                 "--decision-deadline", "300"])
    assert not (out / "failure.json").exists()
    shard, = [json.loads(p.read_text()) for p in out.glob("cluster-*.json")]
    arm = [t for t in shard["decision_traces"] if t["side"] == "arm"]
    decisions = [d for t in arm for d in t["decisions"]]
    searched = [d for d in decisions if "incumbent" in d]
    assert searched, "no contested PUCT decision reached the timed wrapper"
    for d in searched:
        assert d["report_worlds"] == 0            # no report fold, honestly zero
        assert d["challenger"] is None and d["report"] is None
        assert d["selection_N"] == 2              # the world pool per decision
        assert d["reason"] in ("puct_argmax_visits", "candidate0_best",
                               "selection_underfilled")
        assert d["deadline"]["timed_out"] is False
    summary = json.loads((out / "summary.json").read_text())
    assert summary["arm"] == "policy" and puct_arm in summary["arm_description"]
