from __future__ import annotations

import json

import numpy as np
import torch

from shengji.train import simple_belief_train as train
from shengji.train.simple_belief_features import FEATURE_DIM, FEATURE_SCHEMA
from shengji.train.simple_belief_model import SimpleBeliefMLP


def _make_cache(root):
    rng = np.random.default_rng(8)
    descriptors = []
    for split in ("train", "dev", "check"):
        rows = 8 if split == "train" else 4
        key = f"deal:{split}"
        filename = f"{split}.npz"
        identity = f"identity-{split}"
        x = rng.normal(size=(rows, FEATURE_DIM)).astype(np.float32)
        allowed = np.ones((rows, 4, 54, 3), dtype=np.bool_)
        targets = np.zeros((rows, 4, 54), dtype=np.int64)
        np.savez_compressed(root / filename, x=x, allowed=allowed,
                            targets=targets, identity=np.asarray(identity),
                            deal_key=np.asarray(key))
        descriptors.append({"deal_key": key, "split": split, "path": filename,
                            "identity": identity, "rows": rows})
    recipe = {"schema": train.SCHEMA, "feature_schema": FEATURE_SCHEMA,
              "source_digest": "synthetic-source", "deals": descriptors}
    (root / "recipe.json").write_text(json.dumps(recipe, sort_keys=True))
    (root / "complete.json").write_text(json.dumps({
        "schema": train.SCHEMA, "completed_deals": 3, "rows": 16}))


def test_train_dev_only_and_checkpoint_metrics(tmp_path, monkeypatch):
    _make_cache(tmp_path)
    output = tmp_path / "run"
    original_load = train.np.load

    def no_check_open(path, *args, **kwargs):
        assert "check.npz" not in str(path)
        return original_load(path, *args, **kwargs)

    monkeypatch.setattr(train.np, "load", no_check_open)
    report = train.train_simple_belief(
        tmp_path, output, epochs=3, threads=1, batch_size=4,
        width=12, hidden=8, seed=3)
    assert report["completed_epochs"] == 3
    assert len(report["curves"]) == 3
    assert report["curves"][-1]["loss"] < report["curves"][0]["loss"]
    assert (output / "last.pt").exists() and (output / "best.pt").exists()
    assert json.loads((output / "curves.json").read_text()) == report["curves"]

    monkeypatch.undo()
    check = train.score_split(tmp_path, output / "best.pt",
                              split="check", threads=1)
    assert check["split"] == "check" and check["uncertain_cells"] > 0


def test_best_checkpoint_reload_and_deterministic_resume(tmp_path):
    _make_cache(tmp_path)
    direct = tmp_path / "direct"
    resumed = tmp_path / "resumed"
    direct_report = train.train_simple_belief(
        tmp_path, direct, epochs=4, threads=1, batch_size=4,
        width=10, hidden=7, seed=12)
    train.train_simple_belief(
        tmp_path, resumed, epochs=2, threads=1, batch_size=4,
        width=10, hidden=7, seed=12)
    resumed_report = train.train_simple_belief(
        tmp_path, resumed, epochs=4, threads=1, batch_size=4,
        width=10, hidden=7, seed=12, resume=True)
    curve_keys = {"epoch", "loss", "dev_ce", "dev_brier", "dev_uniform_ce",
                  "dev_uniform_brier", "dev_prior_ce", "dev_prior_brier"}
    assert [{key: row[key] for key in curve_keys}
            for row in resumed_report["curves"]] == [
                {key: row[key] for key in curve_keys}
                for row in direct_report["curves"]]
    first = torch.load(direct / "last.pt", map_location="cpu")
    second = torch.load(resumed / "last.pt", map_location="cpu")
    for key in first["model"]:
        assert torch.equal(first["model"][key], second["model"][key])

    best = torch.load(direct / "best.pt", map_location="cpu")
    model = SimpleBeliefMLP( FEATURE_DIM, width=10, hidden=7)
    model.load_state_dict(best["model"])
    dev = train.load_split(tmp_path, "dev")
    metrics = train._evaluate(model, dev, train._count_prior(
        train.load_split(tmp_path, "train")[2]), 4)
    assert metrics["ce"] == best["best_dev_ce"]


def test_recipe_identity_binding_refused_before_use(tmp_path):
    _make_cache(tmp_path)
    recipe = json.loads((tmp_path / "recipe.json").read_text())
    recipe["deals"][0]["identity"] = "wrong"
    (tmp_path / "recipe.json").write_text(json.dumps(recipe))
    with np.testing.assert_raises(ValueError):
        train.load_split(tmp_path, "train")


def test_interrupted_checkpoint_publication_preserves_best_and_resumes(tmp_path, monkeypatch):
    _make_cache(tmp_path)
    direct, interrupted = tmp_path / 'direct', tmp_path / 'interrupted'
    config = dict(epochs=3, threads=1, batch_size=4, width=10, hidden=7, seed=12)
    train.train_simple_belief(tmp_path, direct, **config)
    writer = train._atomic_torch
    def stop_between_best_and_last(path, payload):
        if path.name == 'last.pt' and payload['completed_epochs'] == 2:
            raise RuntimeError('injected stop after best before last')
        writer(path, payload)
    monkeypatch.setattr(train, '_atomic_torch', stop_between_best_and_last)
    with np.testing.assert_raises_regex(RuntimeError, 'injected stop'):
        train.train_simple_belief(tmp_path, interrupted, **config)
    best = torch.load(interrupted / 'best.pt', weights_only=True)
    last = torch.load(interrupted / 'last.pt', weights_only=True)
    assert best['completed_epochs'] == 2 and last['completed_epochs'] == 1
    with np.testing.assert_raises_regex(ValueError, 'occupied'):
        train.train_simple_belief(tmp_path, interrupted, **config)
    monkeypatch.setattr(train, '_atomic_torch', writer)
    train.train_simple_belief(tmp_path, interrupted, resume=True, **config)
    for name in ('best.pt', 'last.pt'):
        a = torch.load(direct / name, weights_only=True)
        b = torch.load(interrupted / name, weights_only=True)
        assert a['completed_epochs'] == b['completed_epochs']
        assert a['best_epoch'] == b['best_epoch']
        for key in a['model']:
            assert torch.equal(a['model'][key], b['model'][key])
