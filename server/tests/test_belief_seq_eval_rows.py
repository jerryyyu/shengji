"""Calib/test row selection of the belief trainer (``belief_seq --eval-rows``).

``sampler`` (the default) keeps the rows where the production sampler was
drawn; ``all`` keeps every row of the split, for extracts with no sampler
draws.  Both read the extract's own deal-to-split assignment.  An empty
selection is refused, the mode is recorded and a resume under another mode is
refused, and on all rows every sampler-relative metric is absent and named as
not measured while the log-losses against the constraint-aware uniform stay.

The extracts are synthetic games (``test_belief_labels``) run through the real
label and history extraction, one chunk per deal.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.train import belief_history as bh  # noqa: E402
from shengji.train import belief_labels as bl  # noqa: E402
from shengji.train import belief_seq as bs  # noqa: E402

from test_belief_labels import synthetic_cluster  # noqa: E402

SPLITS = ("train",) * 4 + ("calib",) * 2 + ("test",) * 2
ARCH = ["--d", "16", "--heads", "2", "--enc-layers", "1", "--xattn-layers", "1", "--x-hidden", "16"]


def build_extract(root, *, sampler: bool, splits=SPLITS):
    """An extract dir (labels + history manifests) with one chunk per deal;
    ``sampler`` draws the production sampler at every second decision."""
    store = root / "store" / "shards"
    store.mkdir(parents=True)
    paths = []
    for k in range(len(splits)):
        p = store / f"cluster-{k:06d}.jsonl"
        with open(p, "w") as fh:
            for r in synthetic_cluster(3000 + k):
                fh.write(json.dumps(r) + "\n")
        paths.append(p)
    out = root / "extract"
    (out / "hist").mkdir(parents=True)
    chunks, hist_files = [], {}
    for k, (p, split) in enumerate(zip(paths, splits)):
        part = bl.extract_cluster(p, store_index=0, cluster_index=k, calib=0.0, test=0.0,
                                  windows=[], sampler_worlds=4 if sampler else 0,
                                  sampler_splits=("train",), sampler_stride=2)
        name = f"{split}-{k:05d}.npz"
        np.savez(out / name, **{key: part[key] for key in bl.ARRAY_KEYS})
        chunks.append({"files": {split: {"file": name, "rows": int(len(part["X"])),
                                         "sha256": hashlib.sha256((out / name).read_bytes()
                                                                  ).hexdigest()}}})
        np.savez(out / "hist" / name, **bh.chunk_history(str(out / name), [str(q) for q in paths]))
        hist_files[name] = hashlib.sha256((out / "hist" / name).read_bytes()).hexdigest()
    (out / "manifest.json").write_text(json.dumps(
        {"schema": bl.SCHEMA, "feature_dim": bl.FEATURE_DIM, "feature_blocks": bl.FEATURE_BLOCKS,
         "chunks": chunks}))
    (out / "hist" / "manifest.json").write_text(json.dumps(
        {"schema": bh.SCHEMA, "files": hist_files, "source_extract_manifest_sha256":
         hashlib.sha256((out / "manifest.json").read_bytes()).hexdigest()}))
    return out


@pytest.fixture(scope="module")
def extracts(tmp_path_factory):
    root = tmp_path_factory.mktemp("evalrows")
    return {"sampler": build_extract(root / "s", sampler=True),
            "none": build_extract(root / "n", sampler=False)}


def quiet(*a, **k):
    pass


def chunk_deals(d, split):
    deals = set()
    for e in bs.extract_entries([str(d)], split):
        with np.load(e["path"]) as z:
            deals.update(np.unique(z["deal"]).tolist())
    return deals


def test_default_is_sampler_rows():
    p = bs.build_parser()
    assert p.parse_args(["train", "--data", "d", "--out", "o"]).eval_rows == "sampler"
    assert p.parse_args(["evaluate", "--data", "d", "--model", "a=b", "--out-json", "j",
                         "--out-md", "m"]).eval_rows == "sampler"


def test_all_rows_keep_the_extract_split_and_include_the_sampler_rows(extracts):
    d = [str(extracts["sampler"])]
    for split in ("calib", "test"):
        samp = bs.load_eval(d, split, bs._Verified(), log=quiet)
        every = bs.load_eval(d, split, bs._Verified(), log=quiet, rows="all")
        assert (samp["S_n"] > 0).all() and (every["S_n"] == 0).any()
        assert len(every["X"]) == sum(e["rows"] for e in bs.extract_entries(d, split))
        assert set(np.unique(every["deal"]).tolist()) == chunk_deals(extracts["sampler"], split)
        assert set(np.unique(samp["deal"]).tolist()) <= set(np.unique(every["deal"]).tolist())
        # every sampler row is an all-rows row (same cluster, decision and labels)
        key = lambda p: {(int(c), int(x)): p["Y"][i].tobytes()  # noqa: E731
                         for i, (c, x) in enumerate(zip(p["cluster"], p["decision"]))}
        ks, ke = key(samp), key(every)
        assert all(ke[k] == v for k, v in ks.items())


def test_an_empty_selection_is_refused(extracts, tmp_path):
    d = [str(extracts["none"])]
    with pytest.raises(bs.BeliefSeqError, match="no sampler rows.*--eval-rows all"):
        bs.load_eval(d, "calib", bs._Verified(), log=quiet)
    assert len(bs.load_eval(d, "calib", bs._Verified(), log=quiet, rows="all")["X"])
    no_calib = build_extract(tmp_path, sampler=False, splits=("train", "test"))
    with pytest.raises(bs.BeliefSeqError, match="no all rows"):
        bs.load_eval([str(no_calib)], "calib", bs._Verified(), log=quiet, rows="all")
    with pytest.raises(bs.BeliefSeqError, match="eval rows"):
        bs.load_eval(d, "calib", bs._Verified(), log=quiet, rows="some")


def train_args(data, out, *extra):
    return (["train", "--data", str(data), "--out", str(out), "--epochs", "1",
             "--buffer-chunks", "1", "--save-every", "1e9", "--threads", "2",
             "--rounds-per-batch", "2"] + ARCH + list(extra))


def evaluate(data, model, tmp_path, *extra):
    js, md = tmp_path / "e.json", tmp_path / "e.md"
    assert bs.main(["evaluate", "--data", str(data), "--model", f"m={model}", "--threads", "2",
                    "--world-states", "6", "--worlds", "4", "--out-json", str(js),
                    "--out-md", str(md)] + list(extra)) == 0
    return json.loads(js.read_text()), md.read_text()


def test_all_rows_train_and_evaluate_without_sampler_draws(extracts, tmp_path):
    data = extracts["none"]
    with pytest.raises(bs.BeliefSeqError, match="no sampler rows"):
        bs.main(train_args(data, tmp_path / "default"))
    out = tmp_path / "all"
    assert bs.main(train_args(data, out, "--eval-rows", "all")) == 0
    best = torch.load(out / "best.pt", weights_only=False)
    assert best["eval_rows"] == "all" and best["args"]["eval_rows"] == "all"
    ck = torch.load(out / "checkpoint.pt", weights_only=False)
    sub = ck["state"]["history"][-1]["calib_subsets"]
    assert set(sub) == {"all", "hands", "kitty"} and all(np.isfinite(v) for v in sub.values())
    assert sub["all"] == pytest.approx(ck["state"]["history"][-1]["calib_ll"])

    with pytest.raises(bs.BeliefSeqError, match="no sampler rows"):
        evaluate(data, out / "best.pt", tmp_path)
    res, md = evaluate(data, out / "best.pt", tmp_path, "--eval-rows", "all")
    assert res["eval_rows"] == "all" and res["reference"] == "uniform"
    assert res["alpha_sampler"] is None and res["worlds"] == {}
    assert set(res["not_measured"]) == {"sampler", "worlds"}
    for table in [res["tables"]["overall"], res["ece"], *res["by_trick"].values()]:
        assert "sampler" not in table
    ov = res["tables"]["overall"]
    for k in ("m", "uniform"):
        assert np.isfinite(ov[k]["hands"]["logloss"]) and np.isfinite(ov[k]["kitty"]["logloss"])
    assert set(res["bootstrap"]["hands"]) == {"m"}           # model vs the uniform
    assert "NOT MEASURED: sampler" in md and "NOT MEASURED: worlds" in md
    assert "| sampler |" not in md and "gain over the constraint-aware uniform" in md
    # with a paired comparison the phase table still reads gains over the uniform
    js, md2 = tmp_path / "e2.json", tmp_path / "e2.md"
    assert bs.main(["evaluate", "--data", str(data), "--model", f"a={out / 'best.pt'}",
                    "--model", f"b={out / 'best.pt'}", "--threads", "2", "--world-states", "6",
                    "--worlds", "4", "--eval-rows", "all", "--out-json", str(js),
                    "--out-md", str(md2)]) == 0
    phase = md2.read_text().split("by phase and role")[1].split("\n## ")[0]
    uniform_row = [line for line in phase.splitlines() if line.startswith("| uniform |")][0]
    assert set(uniform_row.strip("| ").split(" | ")[1:]) == {"+0.00%"}


def test_sampler_mode_keeps_every_metric(extracts, tmp_path):
    data = extracts["sampler"]
    out = tmp_path / "s"
    assert bs.main(train_args(data, out)) == 0
    assert torch.load(out / "best.pt", weights_only=False)["eval_rows"] == "sampler"
    res, md = evaluate(data, out / "best.pt", tmp_path)
    assert res["eval_rows"] == "sampler" and res["reference"] == "sampler"
    assert res["alpha_sampler"] > 0 and res["not_measured"] == {}
    assert set(res["worlds"]) == {"m", "sampler", "uniform"}
    assert set(res["bootstrap"]["hands"]) == {"m", "uniform"}
    assert "| sampler |" in md and "NOT MEASURED" not in md


def test_a_resume_under_another_mode_is_refused(extracts, tmp_path):
    data = extracts["sampler"]
    out = tmp_path / "r"
    out.mkdir()
    (out / "STOP").touch()
    assert bs.main(train_args(data, out, "--eval-rows", "all")) == 3
    (out / "STOP").unlink()
    with pytest.raises(bs.BeliefSeqError, match="--eval-rows sampler differs from the run's all"):
        bs.main(train_args(data, out))
    assert bs.main(train_args(data, out, "--eval-rows", "all")) == 0
