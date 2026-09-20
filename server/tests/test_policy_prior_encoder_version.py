"""Root rows at a later encoder version (2026-09-19, the v5 kitty line).

``policy_prior`` was pinned to v2 (833-wide rows: public 561 + world 270 +
perspective 2), so a joint net at encoder v5 (public 617) had no rows to train
its policy head on.  ``extract --encoder-version`` builds rows at that width, the
manifest records the version, and every loader refuses rows built at another
version than the run's.  v2 is the default everywhere: an archived extraction
(no ``enc_version`` in its manifest) still opens as v2, byte for byte.
"""
import json
import random

import numpy as np
import pytest

from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.rl.value_afterstate_v2 import public_dim
from shengji.train import policy_prior as pp
from shengji.train.policy_rows import PolicyEval, PolicyRowsStream, open_policy_rows
from tests.test_cwv_train import store_dir, other_dir, records, other_records, luna, blocks  # noqa: F401


def _round(seed=5, plays=0):
    bot = SmartBot(); rnd = Game(random.Random(seed)).start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    for s in range(4):
        c = bot.decide_declare(rnd, s, final=True)
        if c:
            rnd.declare(s, c)
    rnd.finalize_declare(); rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    for _ in range(plays):
        rnd.play(rnd.turn, bot.decide_play(rnd, rnd.turn))
    return rnd


def test_input_dim_is_the_public_block_plus_world_and_perspective():
    assert pp.INPUT_DIM == pp.input_dim(2) == 833
    assert pp.input_dim(5) == public_dim(5) + pp.WORLD_RECEIVERS * 54 + 2 == 889
    assert pp.input_dim(1) == 532 + 270 + 2


@pytest.mark.parametrize("plays", [0, 9])
def test_root_rows_build_at_v5_including_the_opening_lead_and_v2_is_unchanged(plays):
    rnd = _round(plays=plays)
    seat = rnd.turn
    x2 = pp.flat_input(pp.root_tensors(rnd, seat), 2)
    assert x2.shape == (833,) and np.array_equal(x2, pp.flat_input(pp.root_tensors(rnd, seat, 2)))
    x5 = pp.flat_input(pp.root_tensors(rnd, seat, 5), 5)
    assert x5.shape == (889,)
    # the v1 prefix, the world block and the perspective are the same bytes; v5 only widens the public block
    assert np.array_equal(x5[:532], x2[:532])
    assert np.array_equal(x5[-272:], x2[-272:])
    with pytest.raises(pp.PolicyPriorError):
        pp.flat_input(pp.root_tensors(rnd, seat, 5), 2)


def test_v5_extraction_streams_only_into_a_v5_run_and_v2_archives_still_open(store_dir, tmp_path):
    v5 = tmp_path / "rows-v5"
    got = pp.extract(v5, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=400, workers=1,
                     chunk_rows=64, version=5)
    man = json.load(open(v5 / "manifest.json"))
    assert got["rows"] > 0 and man["enc_version"] == 5 and man["input_dim"] == 889
    stream = open_policy_rows(v5, version=5)
    assert isinstance(stream, PolicyRowsStream) and stream.input_dim == 889
    with pytest.raises(ValueError, match="encoder v2"):
        open_policy_rows(v5)                      # the default (v2) run refuses v5 rows
    v2 = tmp_path / "rows-v2"
    pp.extract(v2, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=400, workers=1, chunk_rows=64)
    man2 = json.load(open(v2 / "manifest.json"))
    assert man2["enc_version"] == 2 and man2["input_dim"] == 833
    # an archived extraction predates the field: it is v2
    del man2["enc_version"]
    json.dump(man2, open(v2 / "manifest.json", "w"))
    assert open_policy_rows(v2).input_dim == 833
    with pytest.raises(ValueError, match="encoder v5"):
        open_policy_rows(v2, version=5)
    # a v5 row set and a v2 row set from the same shards agree on their deal keys
    assert set(np.load(v5 / man["chunks"][0]["file"])["deal_key"]) <= set(
        k for c in man2["chunks"] for k in np.load(v2 / c["file"])["deal_key"])


def test_the_flat_eval_set_is_checked_against_the_runs_version(store_dir, tmp_path):
    out = tmp_path / "eval5"
    pp.extract(out, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=100, workers=1, version=5)
    summary = json.load(open(str(out) + ".summary.json"))
    assert summary["enc_version"] == 5 and summary["input_dim"] == 889
    assert PolicyEval(out, version=5).X.shape[1] == 889
    with pytest.raises(ValueError, match="not encoder v2"):
        PolicyEval(out)
