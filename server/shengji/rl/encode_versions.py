"""Versioned observation encoding: v1 unchanged, later versions APPEND.

``encode.py`` is deliberately NOT edited by this module.  Its bytes are an
identity: ``encode.ENCODER_SOURCE_SHA256S`` hashes the file, the transitive
contract in ``encoder_identity`` hashes it again, and
``train.cwv_data.cwv_encoder_identity`` folds that digest into the
``implementation_sha256`` that ``ai.cwv_policy.verify_checkpoint_identity``
accepts archived complete-world checkpoints on.  Any edit to ``encode.py``
-- even a purely additive one -- orphans those checkpoints and the registry
bots built on them.  That is what made PR #283 a wrong-shape change, and it
is why encoder v2 lives here instead.

The contract:

* ``encode_obs(rnd, seat)`` is ``encode.encode_obs(rnd, seat)``, delegated,
  so v1 is byte-identical by construction rather than by inspection.
* ``encode_obs(rnd, seat, version=n)`` for ``n > 1`` returns the v1 vector
  followed by that version's extra columns -- a strict extension, so
  ``encode_obs(..., version=n)[:531] == encode_obs(..., version=1)``.
* A consumer picks its version from the WIDTH ITS OWN CHECKPOINT DECLARES
  (``encoder_version_for``), never from the ``ENC_VERSION`` global.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from ..engine.cards import SUITS, TRUMP, total_points
from ..engine.combos import decompose
from ..engine.legal import beats
from ..engine.round import Round
from ..ai.memory import Memory
from . import encode as _v1
from .encode import ENC_VERSION, N_CARDS, OBS_DIM, OBS_SCHEMA  # noqa: F401  (re-export)

#: the highest version ``encode_obs`` can emit
ENC_VERSION_MAX = 3
OBS_SCHEMA_BY_VERSION = {
    1: OBS_SCHEMA,
    2: "rl-observation-v2-trick-state",
    3: "rl-observation-v3-relative-cursor",
}
#: v2 appends 16 trick-local, 5 points-regime and 8 hand-shape columns
_OBS_EXTRA_V2 = 16 + 5 + 8                                   # = 29
# v3 appends four relative next-to-act columns to v2.
_OBS_EXTRA_V3 = 4
OBS_DIM_BY_VERSION = {1: OBS_DIM, 2: OBS_DIM + _OBS_EXTRA_V2,
                      3: OBS_DIM + _OBS_EXTRA_V2 + _OBS_EXTRA_V3}  # 531, 560, 564


def check_version(version: object) -> int:
    """The encoder version ``version`` names, or raise."""
    if isinstance(version, bool) or not isinstance(version, int) \
            or version not in OBS_DIM_BY_VERSION:
        raise ValueError(f"unknown encoder version {version!r}")
    return int(version)


def obs_dim(version: int = ENC_VERSION) -> int:
    """The observation width of encoder ``version``."""
    return OBS_DIM_BY_VERSION[check_version(version)]


def obs_schema(version: int = ENC_VERSION) -> str:
    return OBS_SCHEMA_BY_VERSION[check_version(version)]


def encoder_version_for(arch: object) -> int:
    """The encoder version a CHECKPOINT was trained with.

    Dispatch is by checkpoint, never by the ``ENC_VERSION`` global: a
    checkpoint states its own input width (``train.model.DEFAULT_ARCH``
    records ``arch['obs_dim']``; an exported net's first trunk weight
    carries it), and exactly one encoder version produces that width.
    Accepts an arch mapping or a bare observation width.
    """
    width = arch.get("obs_dim") if isinstance(arch, Mapping) else arch
    if isinstance(width, bool) or not isinstance(width, int):
        raise ValueError("encoder dispatch needs an integer obs_dim")
    for version, dim in OBS_DIM_BY_VERSION.items():
        if dim == width:
            return version
    raise ValueError(f"no encoder version produces obs_dim {width}")


def trick_state(rnd: Round, seat: int) -> tuple[int | None, str | None, int]:
    """``(winning seat, lead effective suit, points on the table)`` for the
    trick in progress, or ``(None, None, 0)`` when ``seat`` is on lead.

    ``Round`` keeps a running incumbent only inside a trusted rollout; on the
    ordinary path the winner is resolved when the trick completes.  This
    recomputes it the same way ``Round`` does, so the observation can carry a
    fact the acting player plainly has and the v1 vector never stated.
    """
    del seat
    trick = rnd.trick
    if trick is None or not trick.plays:
        return None, None, 0
    o = rnd.ordering
    assert o is not None
    lead = trick.plays[0].cards
    winner = trick.plays[0].seat
    inc_suit = o.eff_suit(lead[0])
    inc_top = decompose(lead, o).top_level()
    for tp in trick.plays[1:]:
        won, top = beats(tp.cards, lead, inc_suit, inc_top, o)
        if won:
            winner, inc_top = tp.seat, top
            inc_suit = o.eff_suit(tp.cards[0])
    points = total_points(c for tp in trick.plays for c in tp.cards)
    return winner, o.eff_suit(lead[0]), points


def encode_obs_v2_columns(rnd: Round, seat: int) -> list[float]:
    """The 29 columns encoder v2 APPENDS to the v1 vector."""
    o = rnd.ordering
    assert o is not None
    # v1's own Memory construction, repeated here rather than shared, so
    # ``encode.py`` needs no edit; ``own_kitty=False`` is v1's historical
    # setting and the v2 columns must see the same unseen set.
    mem = Memory(rnd, seat, own_kitty=False)
    return _v2_columns_from_unseen(rnd, seat, mem.unseen)


def cursor_columns(rnd: Round, root_seat: int) -> list[float]:
    """Return v3's relative next-to-act one-hot cursor.

    A live play state must carry an actual engine seat.  Terminal states have
    no next actor and intentionally emit four zeroes; their ``turn`` is
    therefore not inspected.
    """
    if rnd.phase == "round_end":
        return [0.0] * _OBS_EXTRA_V3
    if rnd.phase != "play":
        raise ValueError("v3 cursor requires a play or round_end state")
    if isinstance(rnd.turn, bool) or not isinstance(rnd.turn, int) \
            or not 0 <= rnd.turn < 4:
        raise ValueError("v3 live-play turn must be an integer seat")
    if isinstance(root_seat, bool) or not isinstance(root_seat, int) \
            or not 0 <= root_seat < 4:
        raise ValueError("v3 cursor root seat must be an integer seat")
    result = [0.0] * _OBS_EXTRA_V3
    result[(rnd.turn - root_seat) % 4] = 1.0
    return result


def encode_obs_v3_columns(rnd: Round, root_seat: int) -> list[float]:
    """The four cursor columns encoder v3 appends to the v2 vector."""
    return cursor_columns(rnd, root_seat)


def _v2_columns_from_unseen(rnd: Round, seat: int,
                            unseen: Counter[str]) -> list[float]:
    """Shared feature arithmetic after public unseen counts are available.

    The reference entry point obtains them from Memory. The inference-only
    static adapter can reuse its validated v1 observation's half-copy plane.
    Neither caller changes the 29 feature definitions or private-kitty rule.
    """
    o = rnd.ordering
    assert o is not None
    obs: list[float] = []

    # --- the trick in progress (16) -----------------------------------
    winner, lead_suit, trick_pts = trick_state(rnd, seat)
    winner_rel = [0.0] * 4
    if winner is not None:
        winner_rel[(winner - seat) % 4] = 1.0
    obs += winner_rel
    obs.append(1.0 if (winner is not None and winner != seat
                       and (winner - seat) % 2 == 0) else 0.0)
    obs.append(min(trick_pts, 80) / 80.0)
    lead_onehot = [0.0] * 5
    if lead_suit is not None:
        lead_onehot[(list(SUITS) + [TRUMP]).index(lead_suit)] = 1.0
    obs += lead_onehot
    played_here = 0 if rnd.trick is None else len(rnd.trick.plays)
    position = [0.0] * 4
    position[min(played_here, 3)] = 1.0
    obs += position
    obs.append(len(rnd.trick.plays[0].cards) / 6.0
               if (rnd.trick is not None and rnd.trick.plays) else 0.0)

    # --- the points regime (5) ----------------------------------------
    # A point near the 80 threshold decides the level; a point at 20 does not.
    # v1 gave only a linear fraction of 200 and never stated the kink.
    pts_now = min(rnd.attacker_points, 200)
    obs.append(max(-1.0, min(1.0, (pts_now - 80) / 80.0)))
    band = [0.0] * 4
    band[0 if pts_now < 40 else 1 if pts_now < 80 else 2 if pts_now < 120 else 3] = 1.0
    obs += band

    # --- what the hand is made of (8) ---------------------------------
    hand = rnd.hands[seat]
    eff = [o.eff_suit(c) for c in hand]
    for name in list(SUITS) + [TRUMP]:
        obs.append(eff.count(name) / 27.0)
    obs.append(sum(1 for c in unseen.elements()
                   if o.eff_suit(c) == TRUMP) / 27.0)
    counts = Counter(hand)
    obs.append(sum(1 for v in counts.values() if v >= 2) / 13.0)
    obs.append(len(hand) / 27.0)

    assert len(obs) == _OBS_EXTRA_V2
    return obs


def encode_obs(rnd: Round, seat: int, *, version: int = ENC_VERSION) -> list[float]:
    """The observation of ``seat`` in encoder ``version``.

    Version 1 IS ``encode.encode_obs`` -- the same call, not a copy -- so its
    bytes cannot drift.  Later versions append to it.
    """
    version = check_version(version)
    obs = _v1.encode_obs(rnd, seat)
    assert len(obs) == OBS_DIM
    if version >= 2:
        obs += encode_obs_v2_columns(rnd, seat)
    if version >= 3:
        obs += encode_obs_v3_columns(rnd, seat)
    assert len(obs) == OBS_DIM_BY_VERSION[version]
    return obs


def call_encode(encoder, rnd: Round, seat: int, version: int = ENC_VERSION) -> list[float]:
    """Call ``encoder`` for ``version``, using the HISTORICAL two-argument
    call shape for v1.

    Consumers pass their own module-level ``encode_obs`` name, so a caller
    that wraps or replaces it (the privacy witness, the leaf-encoding
    recorders in the suite) still sees exactly the call v1 always made.  A
    version keyword only appears when a later version is actually wanted.
    """
    return encoder(rnd, seat) if check_version(version) == ENC_VERSION \
        else encoder(rnd, seat, version=version)


__all__ = [
    "ENC_VERSION", "ENC_VERSION_MAX", "OBS_DIM", "OBS_DIM_BY_VERSION",
    "OBS_SCHEMA", "OBS_SCHEMA_BY_VERSION", "check_version", "encode_obs",
    "encode_obs_v2_columns", "encoder_version_for", "obs_dim", "obs_schema",
    "encode_obs_v3_columns", "cursor_columns", "trick_state", "call_encode",
]
