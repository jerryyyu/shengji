"""#649: the producers write ``action_values.means`` in different UNITS and the soft policy
target's temperature is calibrated on points.  The pv-search stores' half-integer LEVEL means
(within-decision gaps ~0.02) softmaxed to a uniform target at T=1, so 16 corpora taught the
policy head "all candidates are equal".  The extract now brings every mean to the points
scale by its recorded units, refuses units it cannot scale, and says in its manifest what it
mixed."""
from __future__ import annotations

import json
import shutil

import numpy as np
import pytest

from shengji.harvest.common import sha256_file
from shengji.train import policy_prior as pp
from shengji.train.cwv_data import (POINTS_PER_LEVEL, POINTS_VALUE_UNITS, PV_VALUE_UNITS,
                                    TrainDataError, VALUE_UNITS_SCALE, search_means,
                                    search_means_points, value_units)
from tests.test_cwv_train import store_dir  # noqa: F401


def _rec(means, units=None):
    values = {"perspective": "acting-team", "eligible_indices": [0, 1], "means": list(means)}
    if units is not None:
        values["units"] = units
    return {"ballot": [["S2"], ["S3"]], "action_values": values}


def test_the_units_tag_matches_the_producers_constant():
    from shengji.harvest.trajectory import PV_VALUE_UNITS as producer
    assert PV_VALUE_UNITS == producer, "the literal in cwv_data drifted from the producer"


def test_no_units_means_points_and_is_left_alone():
    rec = _rec([85.0, 80.0])
    assert value_units(rec) == POINTS_VALUE_UNITS
    assert search_means_points(rec) == ([0, 1], [85.0, 80.0], POINTS_VALUE_UNITS)
    assert search_means(rec) == ([0, 1], [85.0, 80.0])


def test_half_level_means_are_brought_to_the_points_scale():
    rec = _rec([0.70, 0.68], units=PV_VALUE_UNITS)
    idx, means, units = search_means_points(rec)
    assert units == PV_VALUE_UNITS and idx == [0, 1]
    assert means == pytest.approx([0.70 * POINTS_PER_LEVEL, 0.68 * POINTS_PER_LEVEL])
    assert POINTS_PER_LEVEL == 40.0, "mcbot._score's LEVEL_OBJECTIVE bracket is 40 points"
    # the raw reader is unchanged: it is the record, not the training scale
    assert search_means(rec) == ([0, 1], [0.70, 0.68])


def test_the_scale_actually_separates_the_candidates_at_the_points_temperature():
    """The defect in one number: a typical PV gap of 0.02 half-levels is a 50/50 target at
    T=1; on the points scale it is not."""
    import torch
    from shengji.train.policy_prior import soft_ballot_targets
    raw = torch.tensor([[0.70, 0.68]]); mask = torch.tensor([[True, True]])
    flat, _ = soft_ballot_targets(raw, mask, 1.0)
    scaled, _ = soft_ballot_targets(raw * POINTS_PER_LEVEL, mask, 1.0)
    assert abs(float(flat[0, 0]) - 0.5) < 0.01
    assert float(scaled[0, 0]) > 0.68


def test_unknown_units_refuse_rather_than_scale_by_guess():
    rec = _rec([1.0, 2.0], units="furlongs-per-fortnight")
    with pytest.raises(TrainDataError, match="unknown_value_units"):
        value_units(rec)
    with pytest.raises(TrainDataError, match="unknown_value_units"):
        search_means_points(rec)


def _restamped_store(src, dst, units, means=(0.5, 0.25)):
    """A copy of a real store whose scored records carry ``action_values`` in ``units``,
    with the manifest hashes refreshed so the reader's drift check still passes."""
    shutil.copytree(src, dst)
    # sealed stores are written read-only; this is a scratch copy
    for path in dst.rglob("*"):
        if path.is_file():
            path.chmod(0o644)
    manifest = json.loads((dst / "manifest.json").read_text())
    stamped = 0
    for shard in manifest["shards"]:
        path = dst / shard["path"]
        out = []
        for line in path.read_text().splitlines():
            rec = json.loads(line)
            if rec.get("decision_kind") == "play" and len(rec.get("ballot") or []) >= 2:
                rec["action_values"] = {"perspective": "acting-team", "eligible_indices": [0, 1],
                                        "means": list(means), **({"units": units} if units else {})}
                stamped += 1
            out.append(json.dumps(rec))
        path.write_text("\n".join(out) + "\n")
        shard["sha256"] = sha256_file(path)
        shard["bytes"] = path.stat().st_size
    (dst / "manifest.json").write_text(json.dumps(manifest))
    assert stamped > 0
    return stamped


def test_the_extract_scales_pv_units_and_records_what_it_mixed(store_dir, tmp_path):  # noqa: F811
    _restamped_store(store_dir, tmp_path / "pv", PV_VALUE_UNITS)
    out = tmp_path / "rows"
    pp.extract(out, [str(tmp_path / "pv")], lo=0.0, hi=1.01, thin=1.0, max_rows=400,
               workers=1, chunk_rows=100)
    manifest = json.loads((out / "manifest.json").read_text())
    assert set(manifest["value_units"]) <= {PV_VALUE_UNITS, pp.NO_SEARCH_VALUES}
    assert manifest["value_units"][PV_VALUE_UNITS] > 0
    assert manifest["value_units_scale"] == VALUE_UNITS_SCALE and manifest["values_scale"] == "points"
    chunk = np.load(out / "chunk-00000.npz")
    vals, has = chunk["vals"], chunk["has_vals"]
    assert has.any()
    got = vals[has][:, :2]
    assert np.allclose(got, [[0.5 * POINTS_PER_LEVEL, 0.25 * POINTS_PER_LEVEL]]), got[:3]


def test_the_extract_leaves_points_producers_alone(store_dir, tmp_path):  # noqa: F811
    _restamped_store(store_dir, tmp_path / "pts", None, means=(85.0, 80.0))
    out = tmp_path / "rows"
    pp.extract(out, [str(tmp_path / "pts")], lo=0.0, hi=1.01, thin=1.0, max_rows=400,
               workers=1, chunk_rows=100)
    manifest = json.loads((out / "manifest.json").read_text())
    assert set(manifest["value_units"]) <= {POINTS_VALUE_UNITS, pp.NO_SEARCH_VALUES}
    assert manifest["value_units"][POINTS_VALUE_UNITS] > 0
    chunk = np.load(out / "chunk-00000.npz")
    got = chunk["vals"][chunk["has_vals"]][:, :2]
    assert np.allclose(got, [[85.0, 80.0]])


def test_the_extract_refuses_a_store_with_units_it_cannot_scale(store_dir, tmp_path):  # noqa: F811
    _restamped_store(store_dir, tmp_path / "odd", "furlongs-per-fortnight")
    with pytest.raises(TrainDataError, match="unknown_value_units"):
        pp.extract(tmp_path / "rows", [str(tmp_path / "odd")], lo=0.0, hi=1.01, thin=1.0,
                   max_rows=400, workers=1, chunk_rows=100)
