"""Issue #340: the search's mean as the level-head target, soft two-class form.

The producer witnesses use the actual ``MCBot._score``, never a helper that
assumes the disputed formula."""
import glob
import json

import numpy as np
import pytest
import torch

from shengji.ai.mcbot import MCBot
from shengji.rl.value_afterstate import signed_level_category
from shengji.teacher_v1 import attacker_level_utility
from shengji.train import search_mean_sidecar as sc
from shengji.train.search_mean_target import _category, ramp_utility, soft_targets
# the trainer fixture family is module-local to test_cwv_train; importing registers it
from tests.test_cwv_train import store_dir, other_dir, records, other_records, luna, blocks  # noqa: F401
from tests.test_cwv_train import THIRDS, train_v0, train_cwv


def _producer(level_objective: bool) -> MCBot:
    """An MCBot whose ``_score`` is the producer's, without a full search setup."""
    bot = object.__new__(type("Producer", (MCBot,), {"LEVEL_OBJECTIVE": level_objective}))
    return bot


def test_producer_without_level_objective_scores_expected_points_and_is_the_eligible_one():
    """Every corpus (run A..L) ran LEVEL_OBJECTIVE=False: the search mean is an
    expected-points mean, the only producer the ramp target is defined for."""
    bot = _producer(False)
    for p in (0, 39, 79, 80, 100, 120, 240, 300):
        assert bot._score(p) == float(p)
    assert sc.ELIGIBLE_LEVEL_OBJECTIVE is False


def test_level_objective_producer_clips_the_bracket_so_its_mean_has_no_inverse():
    """Codex's witness: ``_score(240) = 188`` maps to utility 3.5 while the
    value truth is ``attacker_level_utility(240) = 4.5``; a producer flag of
    True is therefore refused at attach time."""
    bot = _producer(True)
    assert bot._score(240) == 188.0 and attacker_level_utility(240) == 4.5
    assert (bot._score(240) - 0.2 * 240) / 40 == 3.5  # the clipped bracket, not 4.5
    assert bot._score(200) == bot._score(240) - 0.2 * 40  # clip: 200 and 240 share bracket 3


def test_ramp_agrees_with_the_step_utility_at_every_bracket_lower_edge():
    edges = torch.tensor([0.0, 40.0, 80.0, 120.0, 160.0, 200.0, 240.0])
    want = torch.tensor([attacker_level_utility(int(p)) for p in edges.tolist()])
    assert torch.equal(ramp_utility(edges), want)
    # inside the lowest bracket the ramp climbs from the -2.5 class: 1 -> -2.475
    assert ramp_utility(torch.tensor([1.0])).item() == pytest.approx(-2.475)
    # the takeover cliff is kept: 79 -> -0.525, 80 -> 0.5
    assert ramp_utility(torch.tensor([79.0])).item() == pytest.approx(-0.525)
    assert ramp_utility(torch.tensor([80.0])).item() == pytest.approx(0.5)


def test_expected_points_on_a_bracket_edge_is_a_one_hot_on_that_class():
    for attacker in (True, False):
        # the acting team's signed expected points, as the producer wrote them
        mean = torch.tensor([(1.0 if attacker else -1.0) * 120.0])
        probs, used = soft_targets(mean, torch.tensor([attacker]), torch.tensor([7]))
        assert used.tolist() == [True]
        want = signed_level_category(120, attacker)
        assert probs[0].argmax().item() == want and probs[0, want].item() == pytest.approx(1.0)


def test_expected_points_inside_a_bracket_split_between_the_neighbouring_classes():
    # E[p] = 100 for the attackers: ramp 1.0, halfway between the 0.5 and 1.5 classes
    probs, used = soft_targets(torch.tensor([100.0]), torch.tensor([True]), torch.tensor([7]))
    lo, hi = signed_level_category(80, True), signed_level_category(120, True)
    assert used.tolist() == [True] and hi == lo + 1
    assert probs[0, lo].item() == pytest.approx(0.5) and probs[0, hi].item() == pytest.approx(0.5)
    # E[p] = 100 seen by a defender: mean is -100, the utility is -1.0 for them
    probs, used = soft_targets(torch.tensor([-100.0]), torch.tensor([False]), torch.tensor([7]))
    lo, hi = signed_level_category(120, False), signed_level_category(80, False)
    assert used.tolist() == [True] and hi == lo + 1
    assert probs[0, lo].item() == pytest.approx(0.5) and probs[0, hi].item() == pytest.approx(0.5)
    assert probs.sum().item() == pytest.approx(1.0)


def test_straddling_the_takeover_cliff_is_the_surrogate_bias_by_construction():
    """ramp(E[p]) is not E[utility(p)]: rollouts at 60 and 100 average to 80,
    whose ramp is +0.5, while the realised utilities average to (-1.5 + 0.5) / 2."""
    probs, used = soft_targets(torch.tensor([80.0]), torch.tensor([True]), torch.tensor([7]))
    assert used.tolist() == [True]
    assert probs[0, signed_level_category(80, True)].item() == pytest.approx(1.0)
    assert (attacker_level_utility(60) + attacker_level_utility(100)) / 2 == -0.5


def test_missing_or_out_of_support_means_keep_the_realised_one_hot():
    means = torch.tensor([float("nan"), 1e9, -1e9])
    realised = torch.tensor([3, 150, 200])
    probs, used = soft_targets(means, torch.tensor([True, True, False]), realised)
    assert used.tolist() == [False, False, False]
    for i, cat in enumerate(realised.tolist()):
        assert probs[i, cat].item() == 1.0 and probs[i].sum().item() == 1.0


def _write_run(tmp_path, level_objective):
    run = tmp_path / "run"
    (run / "shards").mkdir(parents=True)
    (run / "run.json").write_text(json.dumps(
        {"config": {"policy_flags": {"level_objective": level_objective, "mc_bury": False}}}))
    shard = run / "shards" / "cluster-00000.jsonl"
    rows = [{"action": ["S2"], "record_sha256": "a" * 64,
             "preference": {"means": [-1.0, 2.5], "played_index": 1}},
            {"action": ["S3"], "record_sha256": "b" * 64, "preference": {"means": [], "played_index": 0}},
            {"note": "not a decision"}]
    shard.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return shard


def test_sidecar_round_trip_aligns_by_record_hash_and_records_the_producer(tmp_path):
    shard = _write_run(tmp_path, False)
    counts = sc.build_sidecar(shard, tmp_path / "side")
    assert counts["records"] == 2 and counts["with_mean"] == 1 and counts["level_objective"] is False
    arrays = {"record_sha256": np.asarray([b"b" * 64, b"a" * 64], dtype="S64")}
    sc.attach_search_means(arrays, counts["shard_sha256"], tmp_path / "side")
    got = arrays["search_mean_played"]
    assert np.isnan(got[0]) and got[1] == pytest.approx(2.5)


def _legacy_v2(side, sha, *, level_objective, keys=(b"a" * 64,), means=(2.5,)):
    """A sidecar as v2 wrote it: points only, no units column, the producer flag."""
    side.mkdir(parents=True, exist_ok=True)
    np.savez(sc.sidecar_path(side, sha), schema=np.asarray("cwv-search-mean-sidecar-v2"),
             level_objective=np.asarray(bool(level_objective)),
             record_sha256=np.asarray(list(keys), dtype="S64"),
             search_mean_played=np.asarray(list(means), dtype=np.float32))


def test_sidecar_from_a_level_objective_producer_is_refused_at_build_and_at_attach(tmp_path):
    shard = _write_run(tmp_path, True)
    # v3 refuses a points row under LEVEL_OBJECTIVE=True before writing anything
    with pytest.raises(sc.SidecarError, match="LEVEL_OBJECTIVE=True"):
        sc.build_sidecar(shard, tmp_path / "side")
    assert not (tmp_path / "side").exists() or not list((tmp_path / "side").glob("*.npz"))
    # a v2 file from such a producer is still refused where it is read
    sha = sc.shard_sha256(shard)
    _legacy_v2(tmp_path / "legacy", sha, level_objective=True)
    arrays = {"record_sha256": np.asarray([b"a" * 64], dtype="S64")}
    with pytest.raises(sc.SidecarError, match="LEVEL_OBJECTIVE=True"):
        sc.attach_search_means(arrays, sha, tmp_path / "legacy")


def test_sidecar_without_a_run_manifest_or_flag_is_refused_at_build(tmp_path):
    shard = tmp_path / "cluster-00000.jsonl"
    shard.write_text(json.dumps({"action": ["S2"], "record_sha256": "a" * 64,
                                 "preference": {"means": [1.0], "played_index": 0}}) + "\n")
    with pytest.raises(sc.SidecarError, match="run.json"):
        sc.build_sidecar(shard, tmp_path / "side")
    (tmp_path / "run.json").write_text(json.dumps({"config": {"policy_flags": {}}}))
    with pytest.raises(sc.SidecarError, match="level_objective"):
        sc.build_sidecar(shard, tmp_path / "side")


def test_pre_flag_sidecar_is_refused_at_attach(tmp_path):
    side = tmp_path / "side"
    side.mkdir()
    np.savez(side / ("c" * 64 + ".npz"), record_sha256=np.asarray([b"a" * 64], dtype="S64"),
             search_mean_played=np.asarray([1.0], dtype=np.float32))
    arrays = {"record_sha256": np.asarray([b"a" * 64], dtype="S64")}
    with pytest.raises(sc.SidecarError, match="rebuild"):
        sc.attach_search_means(arrays, "c" * 64, side)


def test_manifest_hashes_label_bytes_not_only_sizes(tmp_path):
    shard = _write_run(tmp_path, False)
    counts = sc.build_sidecar(shard, tmp_path / "side")
    before = sc.manifest_sha256(tmp_path / "side")
    path = sc.sidecar_path(tmp_path / "side", counts["shard_sha256"])
    with np.load(path, allow_pickle=False) as npz:
        arrays = {k: npz[k] for k in npz.files}
    arrays["search_mean_played"] = arrays["search_mean_played"] + 1.0  # same size, other labels
    np.savez(path, **arrays)
    assert sc.manifest_sha256(tmp_path / "side") != before


def test_trainer_uses_the_search_mean_target_only_where_a_mean_exists(store_dir, luna, tmp_path,
                                                                        monkeypatch):
    luna_path, _rows = luna
    side = tmp_path / "sidecar"
    built = [sc.build_sidecar(p, side, level_objective=False)
             for p in sorted(glob.glob(str(store_dir) + "/**/*.jsonl", recursive=True))]
    assert built and sum(c["with_mean"] for c in built) > 0
    train_v0.train(data=[str(store_dir)], out=tmp_path / "public", device="cpu", epochs=1,
                   seed=7, batch_size=64, n_boot=10, log=None, cache_workers=1,
                   encoder_version=train_cwv.DEFAULTS["encoder_version"], **THIRDS)
    kw = dict(data=[str(store_dir)], eval_luna=str(luna_path), arch="mlp", device="cpu",
              epochs=1, seed=7, batch_size=64, n_boot=20, hidden=32, log=None,
              cache_workers=1, eval_workers=1, bench_batch=32,
              public_head=str(tmp_path / "public" / "best.pt"), **THIRDS)
    realised = train_cwv.train(out=tmp_path / "realised", **kw)
    searched = train_cwv.train(out=tmp_path / "searched", target="search-mean",
                               search_mean_sidecar=str(side), **kw)
    assert realised["target"] == {"kind": "realised"}
    assert searched["target"]["kind"] == "search-mean"
    assert searched["target"]["sidecar_manifest_sha256"] == sc.manifest_sha256(side)
    assert searched["target"]["producer_level_objective"] is False
    assert "ramp" in searched["target"]["estimand"]
    # the single-head path consumes signed-level rows too (sidecar v3): the receipt names both
    assert "bootstrap" in searched["target"]["level_estimand"]
    assert "two estimands" in searched["target"]["note"]
    ep = searched["epochs"][0]["train"]
    assert 0 < ep["search_mean_rows"] <= ep["rows"]
    # a different target trains different weights; the comparable numbers stay realised
    assert searched["epochs"][0]["train"]["cross_entropy"] != realised["epochs"][0]["train"]["cross_entropy"]
    assert searched["selection"]["criterion"] == realised["selection"]["criterion"]
    with pytest.raises(train_cwv.TrainError, match="search-mean-sidecar"):
        train_cwv.train(out=tmp_path / "bad", target="search-mean", **kw)
    # a sidecar from the wrong producer is refused before any training step: v3 refuses it
    # at build, so the trainer-side guard is exercised through v2 files from such a producer
    wrong = tmp_path / "wrong"
    for p in sorted(glob.glob(str(store_dir) + "/**/*.jsonl", recursive=True)):
        with pytest.raises(sc.SidecarError, match="LEVEL_OBJECTIVE=True"):
            sc.build_sidecar(p, wrong, level_objective=True)
        _legacy_v2(wrong, sc.shard_sha256(p), level_objective=True)
    with pytest.raises(sc.SidecarError, match="LEVEL_OBJECTIVE=True"):
        train_cwv.train(out=tmp_path / "refused", target="search-mean",
                        search_mean_sidecar=str(wrong), **kw)


# ---------------------------------------------------------------- sidecar v3: units per row
def _write_pv_run(tmp_path, *, flag=None, name="pvrun"):
    """A pv-search-shaped store: play rows tagged with the signed-level units, a bury row
    under no tag whose means are mcbot points scores, and a null level_objective flag."""
    run = tmp_path / name
    (run / "shards").mkdir(parents=True)
    flags = {"level_objective": flag, "mc_bury": True, "search": "pv-search",
             "value_units": "expected-signed-level-half-integer", "worlds": 64}
    (run / "run.json").write_text(json.dumps({"config": {"policy_flags": flags}}))
    shard = run / "shards" / "cluster-00000.jsonl"
    units = "expected-signed-level-half-integer"
    rows = [{"action": ["S2"], "decision_kind": "play", "record_sha256": "a" * 64,
             "action_values": {"units": units, "means": [-0.467, -0.493], "eligible_indices": [0, 1],
                               "perspective": "acting-team"},
             "preference": {"means": [-0.467, -0.493], "played_index": 1}},
            {"action": ["S3"], "decision_kind": "play", "record_sha256": "b" * 64,
             "action_values": {"units": units, "means": [1.25], "eligible_indices": [0],
                               "perspective": "acting-team"},
             "preference": {"means": [1.25], "played_index": 0}},
            {"action": ["H3", "D3"], "decision_kind": "bury", "record_sha256": "c" * 64,
             "action_values": {"means": [-115.78, -117.5], "eligible_indices": None},
             "preference": {"means": [-115.78, -117.5], "played_index": 0}},
            {"note": "not a decision"}]
    shard.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return shard


def test_pv_sidecar_keeps_play_rows_as_signed_levels_and_drops_the_bury_row(tmp_path):
    shard = _write_pv_run(tmp_path)
    counts = sc.build_sidecar(shard, tmp_path / "side")
    assert counts["records"] == 3 and counts["with_mean"] == 2
    assert counts["level_rows"] == 2 and counts["points_rows"] == 0
    assert counts["level_objective"] is None
    arrays = {"record_sha256": np.asarray([b"c" * 64, b"b" * 64, b"a" * 64, b"z" * 64], dtype="S64")}
    sc.attach_search_means(arrays, counts["shard_sha256"], tmp_path / "side")
    level, mean = arrays["search_level_played"], arrays["search_mean_played"]
    assert np.isnan(level[0]) and np.isnan(mean[0])             # the bury row never entered
    assert level[1] == pytest.approx(1.25) and level[2] == pytest.approx(-0.493)
    assert np.isnan(level[3])
    assert np.isnan(mean).all()                                 # no points row in a pv store


def test_a_points_row_under_a_null_or_true_flag_is_refused_at_build(tmp_path):
    shard = _write_pv_run(tmp_path, name="untagged")
    rows = [json.loads(l) for l in shard.read_text().splitlines()]
    del rows[0]["action_values"]["units"]                        # a points row (no tag) ...
    shard.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    with pytest.raises(sc.SidecarError, match="no level_objective flag"):   # ... under a null flag
        sc.build_sidecar(shard, tmp_path / "side")
    with pytest.raises(sc.SidecarError, match="LEVEL_OBJECTIVE=True"):
        sc.build_sidecar(shard, tmp_path / "side2", level_objective=True)
    counts = sc.build_sidecar(shard, tmp_path / "side3", level_objective=False)
    assert counts["points_rows"] == 1 and counts["level_rows"] == 1   # mixed units, both kept
    arrays = {"record_sha256": np.asarray([b"a" * 64, b"b" * 64], dtype="S64")}
    sc.attach_search_means(arrays, counts["shard_sha256"], tmp_path / "side3")
    assert arrays["search_mean_played"][0] == pytest.approx(-0.493) and np.isnan(arrays["search_level_played"][0])
    assert arrays["search_level_played"][1] == pytest.approx(1.25) and np.isnan(arrays["search_mean_played"][1])


def test_an_unknown_units_tag_is_refused(tmp_path):
    shard = _write_pv_run(tmp_path, name="odd")
    rows = [json.loads(l) for l in shard.read_text().splitlines()]
    rows[0]["action_values"]["units"] = "furlongs"
    shard.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    with pytest.raises(sc.SidecarError, match="furlongs"):
        sc.build_sidecar(shard, tmp_path / "side")


def test_a_v2_sidecar_still_attaches_as_points_with_an_empty_level_column(tmp_path):
    shard = _write_run(tmp_path, False)
    sha = sc.shard_sha256(shard)
    side = tmp_path / "side"
    side.mkdir()
    np.savez(sc.sidecar_path(side, sha), schema=np.asarray("cwv-search-mean-sidecar-v2"),
             level_objective=np.asarray(False), record_sha256=np.asarray([b"a" * 64], dtype="S64"),
             search_mean_played=np.asarray([2.5], dtype=np.float32))
    arrays = {"record_sha256": np.asarray([b"a" * 64, b"b" * 64], dtype="S64")}
    sc.attach_search_means(arrays, sha, side)
    assert arrays["search_mean_played"][0] == pytest.approx(2.5) and np.isnan(arrays["search_mean_played"][1])
    assert np.isnan(arrays["search_level_played"]).all()


def test_a_signed_level_is_the_two_point_target_directly_and_beats_a_points_mean():
    realised = torch.tensor([0, 0, 0, 0])
    role = torch.tensor([True, False, True, True])
    mean = torch.tensor([float("nan"), float("nan"), 100.0, float("nan")])
    level = torch.tensor([1.25, -0.493, 2.5, float("nan")])
    probs, used = soft_targets(mean, role, realised, level=level)
    assert used.tolist() == [True, True, True, False]
    cat = lambda x: int(_category(torch.tensor([x])).item())  # noqa: E731
    # row 0: 1.25 sits 3/4 of the way from 0.5 to 1.5
    assert probs[0, cat(0.5)] == pytest.approx(0.25)
    assert probs[0, cat(1.5)] == pytest.approx(0.75)
    # row 1: a defender's level is already signed for the acting team; no re-signing
    assert probs[1, cat(-0.5)] == pytest.approx(0.993, abs=1e-3)
    assert probs[1, cat(0.5)] == pytest.approx(0.007, abs=1e-3)      # the class ABOVE
    # row 2: the level wins over the points mean (ramp(100) = 1.0 would split 0.5/1.5)
    assert probs[2, cat(2.5)] == pytest.approx(1.0)
    # row 3: nothing usable keeps the realised one-hot
    assert probs[3, 0] == 1.0
    # without the level argument the same call is the old behaviour
    old, old_used = soft_targets(mean, role, realised)
    assert old_used.tolist() == [False, False, True, False]


def test_trainer_search_head_learns_pv_style_level_rows(store_dir, luna, tmp_path):
    """The real trainer with --search-head on a sidecar whose every row is stamped as a
    signed level (the fixture store's means are points; the override makes the rows
    pv-shaped for the data path): the head trains on them and the receipt counts them."""
    luna_path, _rows = luna
    side = tmp_path / "sidecar-level"
    built = [sc.build_sidecar(p, side, level_objective=False, units_override=sc.UNITS_SIGNED_LEVEL)
             for p in sorted(glob.glob(str(store_dir) + "/**/*.jsonl", recursive=True))]
    assert sum(c["level_rows"] for c in built) > 0 and sum(c["points_rows"] for c in built) == 0
    train_v0.train(data=[str(store_dir)], out=tmp_path / "public", device="cpu", epochs=1,
                   seed=7, batch_size=64, n_boot=10, log=None, cache_workers=1,
                   encoder_version=train_cwv.DEFAULTS["encoder_version"], **THIRDS)
    kw = dict(data=[str(store_dir)], eval_luna=str(luna_path), arch="mlp", device="cpu",
              epochs=1, seed=7, batch_size=64, n_boot=20, hidden=32, log=None,
              cache_workers=1, eval_workers=1, bench_batch=32,
              public_head=str(tmp_path / "public" / "best.pt"), **THIRDS)
    out = train_cwv.train(out=tmp_path / "twohead", search_head=True, search_head_weight=1.0,
                          search_mean_sidecar=str(side), **kw)
    ep = out["epochs"][0]["train"]
    # every used row here is a level row: the fixture's points values (-115..) are far outside
    # the half-level support, so only rows whose value happens to land inside count
    assert ep["search_head_rows"] == ep["search_head_level_rows"]
    assert "bootstrap" in out["search_head"]["level_estimand"]
    on_disk = json.loads((tmp_path / "twohead" / "metrics.json").read_text())
    assert on_disk["epochs"][0]["train"]["search_head_level_rows"] == ep["search_head_level_rows"]
