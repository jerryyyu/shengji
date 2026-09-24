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
import os
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


# -- the differential proof: BOTH revisions actually execute ---------------
#
# The first version of this file compared the current Round against a shallow
# copy of itself with `notice` deleted.  That never ran release 30's code at
# all, so it could not have detected a changed transition, and it missed the
# other state the notice adds (`_notice_plays_left`).  Worse, it collected
# mutable round references and encoded them later, so its "40 states" were one
# object in its final position (Codex, #635).
#
# This replays the SAME seeded deals under BOTH revisions -- the legacy module
# is patched into engine.game, so release 30's Round runs deal, declare, bury
# and play -- forces the second replay through the FIRST one's exact action
# script so the two traverse identical states by construction, and encodes at
# each decision BEFORE the round mutates.

LEGACY_MODULE = "shengji.engine._round_release30"


def _load_legacy_round():
    """Import release 30's round.py as a package submodule.

    It uses relative imports (`from .cards import ...`), so it has to be loaded
    under the `shengji.engine` package or those fail; a top-level module name
    would raise ImportError rather than exercise anything.
    """
    import importlib.machinery
    import importlib.util
    import sys

    if LEGACY_MODULE in sys.modules:
        return sys.modules[LEGACY_MODULE]
    loader = importlib.machinery.SourceFileLoader(LEGACY_MODULE, str(LEGACY))
    spec = importlib.util.spec_from_loader(LEGACY_MODULE, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[LEGACY_MODULE] = module
    loader.exec_module(module)
    return module


VERSIONS = (1, 2, 4, 5, 6)          # every version whose identity hashes round.py


def _encodable_versions():
    from shengji.train.policy_prior import flat_input, root_tensors
    from shengji.ai.env import prepare_round
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.game import Game
    import random

    game = Game(random.Random(99260924))
    rnd = prepare_round(game, [HeuristicBot() for _ in range(4)])
    ok = []
    for v in VERSIONS:
        try:
            flat_input(root_tensors(rnd, rnd.turn, v), v)
            ok.append(v)
        except Exception:                            # noqa: BLE001
            pass
    return tuple(ok)


def _trace(seed, versions, *, legacy=False, script=None, limit=60):
    """Play one deal and snapshot the encoder's input at every decision.

    Snapshots are taken BEFORE `rnd.play`, and `flat_input` returns a fresh
    array, so nothing here aliases a mutating round.
    """
    import random

    from shengji.ai.env import prepare_round
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine import game as game_module
    from shengji.train.policy_prior import flat_input, root_tensors

    original = game_module.Round
    if legacy:
        game_module.Round = _load_legacy_round().Round
    try:
        game = game_module.Game(random.Random(seed))
        bots = [HeuristicBot() for _ in range(4)]
        rnd = prepare_round(game, bots)
        expected = LEGACY_MODULE if legacy else "shengji.engine.round"
        assert type(rnd).__module__ == expected, (
            f"replay ran {type(rnd).__module__}, not {expected}")
        states, played = [], []
        while rnd.phase == "play" and len(states) < limit:
            seat = rnd.turn
            states.append((seat, {v: flat_input(root_tensors(rnd, seat, v), v)
                                  for v in versions}))
            action = list(script[len(played)]) if script else bots[seat].decide_play(rnd, seat)
            rnd.play(seat, action)
            played.append(list(action))
        return states, played
    finally:
        game_module.Round = original


@pytest.mark.parametrize("seed", [98260924, 98260925, 98260926])
def test_both_revisions_encode_identical_tensors(seed):
    """The load-bearing proof: release 30's Round and this one, same deals."""
    versions = _encodable_versions()
    assert versions, "no encoder version could be exercised"

    live, script = _trace(seed, versions)
    old, replayed = _trace(seed, versions, legacy=True, script=script)

    assert len(live) >= 20, f"only {len(live)} decisions reached"
    assert len(live) == len(old), "the two revisions diverged in length"
    assert script[:len(replayed)] == replayed, "the legacy replay did not follow the script"

    for index, ((seat_a, a), (seat_b, b)) in enumerate(zip(live, old)):
        assert seat_a == seat_b, f"seat diverged at decision {index}"
        for v in versions:
            assert a[v].tobytes() == b[v].tobytes(), (
                f"encoder v{v} differs at decision {index}, seat {seat_a}")


def test_distinct_states_were_actually_compared():
    """Guard against the defect this test had: one object counted many times."""
    versions = _encodable_versions()
    live, _ = _trace(98260924, versions)
    distinct = {a[versions[0]].tobytes() for _, a in live}
    assert len(distinct) >= 20, (
        f"{len(live)} decisions produced only {len(distinct)} distinct encodings; "
        "the snapshots are aliasing a mutating round again")


def test_the_notice_state_itself_does_not_move_the_tensors():
    """Set the notice explicitly, since a failed throw is rare in random play.

    `_set_notice` writes `notice` AND `_notice_plays_left`; release 30 has
    neither. If the encoder read either, this would differ.
    """
    import random

    from shengji.ai.env import prepare_round
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.game import Game
    from shengji.train.policy_prior import flat_input, root_tensors

    versions = _encodable_versions()
    game = Game(random.Random(98260927))
    bots = [HeuristicBot() for _ in range(4)]
    rnd = prepare_round(game, bots)
    seat = rnd.turn
    before = {v: flat_input(root_tensors(rnd, seat, v), v) for v in versions}

    rnd._set_notice(seat, ["S2", "S3"], ["S2"])
    assert rnd.notice is not None and rnd._notice_plays_left == rnd.NOTICE_PLAYS
    after = {v: flat_input(root_tensors(rnd, seat, v), v) for v in versions}
    for v in versions:
        assert before[v].tobytes() == after[v].tobytes(), f"v{v} moved when the notice was set"

    # and while it ages
    for _ in range(3):
        rnd._age_notice()
    aged = {v: flat_input(root_tensors(rnd, seat, v), v) for v in versions}
    for v in versions:
        assert before[v].tobytes() == aged[v].tobytes(), f"v{v} moved while the notice aged"


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


def test_the_release_30_identity_is_still_accepted():
    """IDENTITY ONLY -- this does NOT prove the package loads (Codex, #635).

    Renamed from "can still serve the production package", which overstated it:
    it constructs no evaluator and no bot, so it cannot catch a schema, weights,
    backend or constructor incompatibility. What it does catch is the specific
    regression #634 was -- the guard refusing the identity production declares --
    and it catches it with no artifact, which is why it can run on every push.

    The real load coverage is the test below.
    """
    from shengji.ai.cwv_policy import verify_checkpoint_identity

    metadata = {"encoder": {"implementation_sha256": RELEASE_30_IDENTITY,
                            "enc_version": 2}}
    assert verify_checkpoint_identity(metadata) == RELEASE_30_IDENTITY


REQUIRE_PACKAGE = os.environ.get("SHENGJI_REQUIRE_PV_PACKAGE") == "1"
PACKAGE = os.environ.get("SHENGJI_PV_PACKAGE_PATH")
PACKAGE_SHA = "ccade130f34ae61def540441ef997e8d41cef9df96f9683406bbba59ae4ccc75"


def test_the_production_package_constructs_a_served_bot():
    """THE REAL LOAD SMOKE: hash-pinned artifact, actual bot construction.

    Under SHENGJI_REQUIRE_PV_PACKAGE=1 a missing or unreadable artifact FAILS
    rather than skips, because a required gate that skips itself is how the
    exploitability gates on #633 nearly reported six silent passes. Without
    that flag it skips and says so, so the suite still runs where the 2.3 MB
    package is not provisioned.

    NOT YET WIRED INTO CI: provisioning a pinned binary needs a decision
    nobody has made -- commit it to the repo, or fetch it from somewhere CI
    can reach. Raised on #635 rather than chosen unilaterally.
    """
    if not PACKAGE:
        if REQUIRE_PACKAGE:
            pytest.fail("SHENGJI_REQUIRE_PV_PACKAGE=1 but SHENGJI_PV_PACKAGE_PATH is unset")
        pytest.skip("set SHENGJI_PV_PACKAGE_PATH (and SHENGJI_REQUIRE_PV_PACKAGE=1 in CI)")
    path = pathlib.Path(PACKAGE)
    if not path.exists():
        pytest.fail(f"pinned package is missing: {path}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == PACKAGE_SHA, f"package is {actual[:12]}, not the pinned {PACKAGE_SHA[:12]}"

    from shengji.train.pv_search_policy import PVSearchBuryBot, make_pv_search_bot

    bot = make_pv_search_bot(str(path), sha256=PACKAGE_SHA, worlds=8, candidates=4,
                             cap=256, batch_size=64, bury_arm="hybrid")
    assert isinstance(bot, PVSearchBuryBot)
    assert bot.checkpoint_sha256 == PACKAGE_SHA


def test_a_foreign_identity_is_still_refused():
    """The guard must not have been widened into a rubber stamp."""
    from shengji.ai.cwv_policy import CWVCheckpointMismatch, verify_checkpoint_identity

    with pytest.raises(CWVCheckpointMismatch):
        verify_checkpoint_identity({"encoder": {"implementation_sha256": "9" * 64,
                                                "enc_version": 2}})
