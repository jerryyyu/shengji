"""Actual harvest -> compressed shard -> resume witnesses for optional labels."""
import copy
import json

import numpy as np
import pytest

from shengji.ai.registry import REGISTRY
from shengji.harvest import shortlist_scores, trajectory
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig


@pytest.fixture
def teacher(monkeypatch):
    class Evaluator:
        checkpoint_sha256 = "a" * 64
        enc_version = 2
        effective_encoding = "mlp-static"

    def build(seed=None):
        bot = CWVShortlistBot(Evaluator(), seed=seed,
                             config=CWVShortlistConfig(worlds=1, selection_worlds=2))
        bot.REPORT_FOLD_WORLDS = 30
        return bot

    name = "test-full-legal-capture"
    monkeypatch.setitem(REGISTRY, name, build)
    # Keep the real game, enumeration, sampler, candidate admission, MC wiring,
    # trajectory mapping and persistence. Cheap deterministic evaluators only.
    monkeypatch.setattr(CWVShortlistBot, "_means", lambda self, r, s, a, w:
                        np.asarray([float(len(cards)) for cards in a]))
    monkeypatch.setattr(CWVShortlistBot, "_rollout",
                        lambda self, r, s, h, b, a, **kw: float(len(a)))
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    return name


def test_real_generator_persists_labels_and_preserves_play(teacher, tmp_path):
    results = []
    for capture in (False, True):
        out = tmp_path / str(capture)
        manifest = trajectory.generate(
            rounds=2, seed0=4_700_000, out_dir=out, policy=teacher, workers=1,
            explore_rate=0, capture_full_legal_scores=capture,
            seed_windows=tmp_path / f"seeds-{capture}.json")
        records = [json.loads(line) for line in (out / manifest["shards"][0]["path"]).read_text().splitlines()]
        results.append((out, manifest, records))
    off, on = results
    assert off[1]["run_id"] != on[1]["run_id"]
    assert "capture_full_legal_scores" not in off[1]["config"]
    assert on[1]["config"]["capture_full_legal_scores"] is True

    def semantic(records):
        return [{k: v for k, v in r.items() if k not in ("source_ref", "record_sha256")}
                for r in records]

    assert semantic(off[2]) == semantic(on[2])
    path = shortlist_scores.score_path(on[0], 0)
    assert path.exists() and not shortlist_scores.score_path(off[0], 0).exists()
    rows = list(shortlist_scores.read_scores(path))
    plays = [r for r in on[2] if r["decision_kind"] == "play"]
    assert len(rows) == len(plays) > 20
    assert any(len(row["scores"]["actions"]) > 5 for row in rows if row["scores"])
    for row, record in zip(rows, plays):
        assert row["source_ref"] == record["source_ref"]
        assert row["record_sha256"] == record["record_sha256"]
        scores = row["scores"]
        assert scores is not None
        assert scores["checkpoint_sha256"] == "a" * 64 and scores["enc_version"] == 2
        if scores["means"] is not None:
            assert scores["means"] == [float(len(a)) for a in scores["actions"]]
        else:
            assert scores["unscored_reason"] == "forced"
    config = on[1]["config"]
    receipt, reason = trajectory.verify_shard(on[0], config, 0, config["seed0"])
    assert reason == "ok" and receipt["full_legal_scores"]["records"] == len(rows)
    before = path.read_bytes()
    assert shortlist_scores.publish_scores(on[0], 0, on[2], rows) == receipt["full_legal_scores"]
    assert path.read_bytes() == before
    # Public resume entry point must refuse a changed capture setting.
    with pytest.raises(trajectory.TrajectoryError, match="requested policy/seed/knobs/work"):
        trajectory.generate(rounds=2, seed0=config["seed0"], out_dir=on[0],
                            policy=teacher, explore_rate=0, resume=True,
                            seed_windows=tmp_path / "seeds-True.json")
    # Missing optional artifacts may not silently pass the existing shard check.
    path.unlink()
    assert trajectory.verify_shard(on[0], config, 0, config["seed0"])[1] == "full-legal score file binding"


def test_cli_flag_and_non_shortlist_refusal():
    args = trajectory.build_parser().parse_args([
        "--out", "/unused", "--rounds", "2", "--seed", "4700000", "--capture-full-legal-scores"])
    assert args.capture_full_legal_scores
    with pytest.raises(trajectory.TrajectoryError, match="requires a learned shortlist policy"):
        trajectory.build_config(seed0=4_700_000, capture_full_legal_scores=True)


@pytest.mark.parametrize("mutation", ["truncated", "duplicate", "nonfinite", "checkpoint", "binding"])
def test_bad_score_vectors_refused(mutation):
    record = {"source_ref": "r:0", "record_sha256": "b" * 64, "decision_kind": "play",
              "seat": 1, "ballot": [["S3"]], "legal_actions_count": 2}
    row = {"source_ref": "r:0", "record_sha256": "b" * 64, "scores": {
        "schema": shortlist_scores.SCHEMA, "kind": "model-world-mean",
        "perspective": "acting-team", "seat": 1,
        "continuation": "engine-root-then-heuristic-finish-trick",
        "checkpoint_sha256": "a" * 64, "enc_version": 2,
        "actions": [["S3"], ["S4"]], "means": [1.0, 2.0], "worlds": 32,
        "config": {"worlds": 32}, "unscored_reason": None}}
    shortlist_scores._validate(row, record)
    bad = copy.deepcopy(row)
    if mutation == "truncated":
        bad["scores"]["means"].pop()
    elif mutation == "duplicate":
        bad["scores"]["actions"][1] = ["S3"]
    elif mutation == "nonfinite":
        bad["scores"]["means"][0] = float("nan")
    elif mutation == "checkpoint":
        bad["scores"]["checkpoint_sha256"] = None
    else:
        bad["record_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="full-legal score"):
        shortlist_scores._validate(bad, record)
