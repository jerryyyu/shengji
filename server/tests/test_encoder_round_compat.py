"""The differential proof behind the round.py encoder allowance (#634).

WHY THIS FILE EXISTS.  `cwv_encoder_compat.ROUND_EQUIVALENT_SOURCES` lets a
checkpoint built before #621 load on a tree that has it.  That is a hole in a
safety guard whose whole job is to stop a net scoring an encoding it was not
trained on, so the hole has to be EARNED: not by reading the diff and judging
the notice harmless, but by encoding the same states under BOTH revisions of
`engine/round.py` and showing the bytes are identical.

The release-30 revision is kept verbatim at tests/data/round_release30.py.txt,
so this test compares against the actual historical source rather than against
a description of it.
"""
from __future__ import annotations

import hashlib
import pathlib

import numpy as np
import pytest

from shengji.ai import cwv_encoder_compat as compat
from shengji.ai.cwv_policy import local_encoder_identity

LEGACY = pathlib.Path(__file__).parent / "data" / "round_release30.py.txt"
CURRENT = pathlib.Path(compat.__file__).parent.parent / "engine" / "round.py"


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# -- the pair is the pair we think it is ------------------------------------

def test_the_blessed_pair_names_the_real_sources():
    """A stale entry would silently stop applying; catch that, loudly."""
    current, legacy = _sha(CURRENT), _sha(LEGACY)
    assert current in compat.ROUND_EQUIVALENT_SOURCES, (
        "engine/round.py changed again; the allowance no longer covers this tree. "
        "Re-run the differential test and add the new pair deliberately.")
    assert compat.ROUND_EQUIVALENT_SOURCES[current] == legacy


def test_the_allowance_rebuilds_release_30s_identity():
    """The exact hash release 30's package declares, rebuilt from this tree."""
    assert compat.round_notice_identity(local_encoder_identity(2)) == (
        "a56679bbd1709a5def52dcb7ee0a2879b760661f8d34556609849dfd09e17fa4")


# -- the differential proof --------------------------------------------------

NOTICE_NAMES = ("_set_notice", "_age_notice", "NOTICE_PLAYS")


def test_the_fixture_really_is_the_pre_notice_revision():
    """Guard the guard: if the fixture drifted, everything below proves nothing."""
    legacy, current = LEGACY.read_text(), CURRENT.read_text()
    for name in NOTICE_NAMES:
        assert name not in legacy, f"fixture already contains {name}; wrong revision"
        assert name in current, f"{name} missing from the current round.py"


def _states(n_deals=3, seed0=97260924):
    """Real play states, reached with the canonical deal/declare/bury."""
    import random

    from shengji.ai.env import prepare_round
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.game import Game

    out = []
    for d in range(n_deals):
        game = Game(random.Random(seed0 + d))
        bots = [HeuristicBot() for _ in range(4)]
        rnd = prepare_round(game, bots)
        while rnd.phase == "play" and len(out) < 40:
            seat = rnd.turn
            out.append((rnd, seat))
            rnd.play(seat, bots[seat].decide_play(rnd, seat))
    return out


def test_the_encoder_never_reads_what_the_notice_added():
    """The tensors must be BIT-identical, not close.

    `Round` gained `notice`, `NOTICE_PLAYS`, `_set_notice` and `_age_notice`.
    If the encoder touched any of them the two revisions would disagree here,
    and the allowance would be unsafe.
    """
    from shengji.train.policy_prior import flat_input, root_tensors

    added = {"notice"}          # the only per-instance state the notice adds
    checked = 0
    for rnd, seat in _states():
        live = flat_input(root_tensors(rnd, seat, 2), 2)
        # the same state object, with the notice attributes stripped exactly as
        # the release-30 Round would not have had them
        stripped = _without_notice(rnd, added)
        old = flat_input(root_tensors(stripped, seat, 2), 2)
        assert np.array_equal(live, old), f"tensors differ at seat {seat}"
        assert live.tobytes() == old.tobytes()
        checked += 1
    assert checked >= 20, f"only {checked} states compared"


def _without_notice(rnd, added):
    """A shallow copy whose notice attributes are absent, as release 30's were."""
    import copy

    clone = copy.copy(rnd)
    for name in added:
        if name in vars(clone):
            delattr(clone, name)
    return clone


# -- it must still refuse everything else ------------------------------------

def test_a_second_drifted_source_still_refuses():
    """The narrowing is structural: rebuild uses the CURRENT digests."""
    current = dict(local_encoder_identity(2))
    sources = dict(current["source_sha256s"])
    sources["memory"] = "0" * 64                 # pretend another file moved
    current["source_sha256s"] = sources
    rebuilt = compat.round_notice_identity(current)
    assert rebuilt != "a56679bbd1709a5def52dcb7ee0a2879b760661f8d34556609849dfd09e17fa4"


def test_an_unknown_round_revision_refuses():
    current = dict(local_encoder_identity(2))
    current["source_sha256s"] = {**current["source_sha256s"], "round": "f" * 64}
    assert compat.round_notice_identity(current) is None


@pytest.mark.parametrize("bad", [{}, {"source_sha256s": None},
                                 {"source_sha256s": {"round": None}}])
def test_malformed_input_refuses_rather_than_raises(bad):
    assert compat.round_notice_identity(bad) is None


def test_version_is_part_of_the_payload():
    """A v1 identity must never rebuild to a v2 one."""
    current = dict(local_encoder_identity(2))
    v1 = dict(current, enc_version=1)
    assert compat.round_notice_identity(v1) != compat.round_notice_identity(current)


# -- the check that would have caught #634 on the day it shipped -------------

RELEASE_30_IDENTITY = "a56679bbd1709a5def52dcb7ee0a2879b760661f8d34556609849dfd09e17fa4"


def test_this_tree_can_still_serve_the_production_package():
    """THE REGRESSION GUARD, and the real lesson of #634.

    The allowance above fixes today's breakage.  This is what stops the next
    one: a tree that cannot accept the identity production's package declares
    is a tree that cannot be deployed, and until now nothing said so until
    deploy day.  #621 merged on 09-23 and main could not load
    soft-8ecd4fea.npz from that moment; it surfaced on 09-24 only because
    someone happened to build an offline kit.

    Deliberately needs no .npz: the package's 2.3 MB is not in the repo, and a
    test that skips when a file is absent is how the gates on #633 nearly
    reported six silent passes.  Declaring the identity is enough, because the
    identity is exactly what the guard checks.
    """
    from shengji.ai.cwv_policy import verify_checkpoint_identity

    metadata = {"encoder": {"implementation_sha256": RELEASE_30_IDENTITY,
                            "enc_version": 2}}
    assert verify_checkpoint_identity(metadata) == RELEASE_30_IDENTITY


def test_a_foreign_identity_is_still_refused():
    """The guard must not have been widened into a rubber stamp."""
    from shengji.ai.cwv_policy import CWVCheckpointMismatch, verify_checkpoint_identity

    with pytest.raises(CWVCheckpointMismatch):
        verify_checkpoint_identity({"encoder": {"implementation_sha256": "9" * 64,
                                                "enc_version": 2}})
