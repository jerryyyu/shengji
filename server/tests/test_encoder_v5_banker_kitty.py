"""Encoder v5: the banker's own buried kitty, the first encoder block that adds a
FACT rather than restating public state.  Secrecy, append-only layout, and the
identities of the already-published versions are all pinned here."""
import json
from collections import Counter
from pathlib import Path

import pytest

from shengji.ai.memory import Memory
from shengji.engine.cards import total_points
from shengji.rl import encode_versions as ev
from shengji.rl.encode import CARD_INDEX, N_CARDS, _counts
from shengji.rl.encode_banker_kitty import (BANKER_KITTY_COLUMNS, KITTY_POINTS_SCALE,
                                            N_BANKER_KITTY_COLUMNS, banker_kitty_columns,
                                            banker_kitty_known)
from shengji.rl.encoder_identity import PUBLISHED_DISPATCHER_SHA256, encoder_contract
from shengji.train.cwv_data import cache_path
from tests.test_world_shortlist import play_state

V2_DIM = 560
KITTY_SLICE = slice(V2_DIM, V2_DIM + N_BANKER_KITTY_COLUMNS)
#: the v1 unseen plane: hand, four seat-relative play histories, three trick planes, then unseen
UNSEEN_SLICE = slice(N_CARDS * 8, N_CARDS * 9)


def test_layout_is_v2_plus_fifty_six():
    assert N_BANKER_KITTY_COLUMNS == len(BANKER_KITTY_COLUMNS) == 1 + N_CARDS + 1 == 56
    assert ev.OBS_DIM_BY_VERSION[5] == ev.OBS_DIM_BY_VERSION[2] + 56 == 616
    assert ev.ENC_VERSION_MAX == 6   # v6 is the corrected-unseen-plane arm (#477)
    assert ev.OBS_SCHEMA_BY_VERSION[5] == "rl-observation-v5-banker-kitty"
    with pytest.raises(ValueError):
        ev.check_version(3)


def test_v5_extends_v2_without_disturbing_its_bytes():
    rnd = play_state(); seat = rnd.turn
    v1 = ev.encode_obs(rnd, seat, version=1)
    v2 = ev.encode_obs(rnd, seat, version=2)
    v5 = ev.encode_obs(rnd, seat, version=5)
    assert len(v5) == 616 and v5[:V2_DIM] == v2 and v5[:len(v1)] == v1


def test_the_banker_sees_its_own_burial_and_nobody_else_does():
    rnd = play_state()
    banker = rnd.banker
    assert rnd.buried, "the fixture must be past the bury"
    cols = banker_kitty_columns(rnd, banker)
    assert banker_kitty_known(rnd, banker) and cols[0] == 1.0
    assert cols[1:1 + N_CARDS] == _counts(list(rnd.buried))
    assert cols[-1] == pytest.approx(min(total_points(rnd.buried), KITTY_POINTS_SCALE)
                                     / KITTY_POINTS_SCALE)
    for seat in range(4):
        if seat == banker:
            continue
        assert not banker_kitty_known(rnd, seat)
        assert banker_kitty_columns(rnd, seat) == [0.0] * N_BANKER_KITTY_COLUMNS, \
            "the burial must never reach another seat's observation"


def test_zero_before_the_burial_exists():
    rnd = play_state()
    buried, rnd.buried = rnd.buried, []
    try:
        assert banker_kitty_columns(rnd, rnd.banker) == [0.0] * N_BANKER_KITTY_COLUMNS
    finally:
        rnd.buried = buried


def test_the_block_is_exactly_the_correction_the_world_sampler_already_makes():
    """The bug v5 fixes: the v1 unseen plane counts the banker's own burial as
    cards an opponent might hold, while ``Memory(own_kitty=True)`` -- what the
    world sampler uses -- does not.  Subtracting this block's plane from the
    unseen plane must reproduce the sampler's pool exactly."""
    rnd = play_state()
    banker = rnd.banker
    v5 = ev.encode_obs(rnd, banker, version=5)
    unseen_plane = v5[UNSEEN_SLICE]
    kitty_plane = v5[KITTY_SLICE][1:1 + N_CARDS]
    corrected = [u - k for u, k in zip(unseen_plane, kitty_plane)]
    sampler_pool = _counts(list(Memory(rnd, banker, own_kitty=True).unseen.elements()))
    assert corrected == pytest.approx(sampler_pool)
    assert unseen_plane != pytest.approx(sampler_pool), \
        "if these already agreed there would be nothing for v5 to fix"
    assert sum(kitty_plane) == pytest.approx(len(rnd.buried) * 0.5)


def test_published_identities_do_not_move_when_a_version_is_added():
    """v4's source closure contains the DISPATCHER, so publishing v5 would have
    changed v4's identity and orphaned its cache (176,002 shard files on the
    trainer) and its archived checkpoints.  Both published keys are pinned."""
    assert cache_path("/c", "SHA", version=2).name == "SHA.cwv-v2-a56679bbd170.npz"
    assert cache_path("/c", "SHA", version=4).name == "SHA.cwv-v4-d99e7836cc4c.npz"
    assert cache_path("/c", "SHA", version=5).name.startswith("SHA.cwv-v5-")
    assert set(PUBLISHED_DISPATCHER_SHA256) == {4}, \
        "pin v5 too once a checkpoint or cache is published against it"
    # each version's closure names its own block and not another version's
    assert "encode_banker_kitty" in encoder_contract(5)["source_sha256s"]
    assert "encode_opponent_pairs" not in encoder_contract(5)["source_sha256s"]
    assert "encode_banker_kitty" not in encoder_contract(4)["source_sha256s"]


def test_v4_bytes_are_unchanged_by_the_dispatcher_edit():
    """The pin above stops the file hash from noticing a dispatcher edit, so the
    bytes v4 actually emits are pinned instead."""
    golden = json.loads((Path(__file__).parent / "data" / "encoder_v4_golden.json").read_text())
    rnd = play_state(); seat = rnd.turn
    assert golden and golden[0]["seat"] == seat
    assert ev.encode_obs(rnd, seat, version=4) == pytest.approx(golden[0]["v4"])
    assert ev.encode_obs(rnd, seat, version=2) == pytest.approx(golden[0]["v2"])
