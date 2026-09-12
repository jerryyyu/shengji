"""The value net's INPUT features for one seat, named, for the debug X-ray.

Jerry (2026-09-12): the X-ray should show every ML-derived feature explicitly
marked as a feature, so learned inputs are never confused with the memory
heuristics (voids, boss cards, ruff risk) that the same page also shows.

What this exposes and what it refuses, deliberately:

* The PUBLIC block only: ``encode_obs(rnd, seat, version=...)`` plus the
  ``round_end`` flag that ``value_afterstate.tensors_from_round`` appends.
  That block is built from the seat's own hand and public history alone
  (``Memory(rnd, seat, own_kitty=False)``), so it reveals nothing the seat
  cannot already see.
* The WORLD block is never built here.  In serving it holds SAMPLED hidden
  hands, one complete world per sample; on the X-ray it would either leak
  the real hidden hands or show one arbitrary sample as if it were fact.
  It is described, not rendered.

Slices are the encoder's own layout, read from ``rl.encode`` and
``rl.encode_versions``; a mismatch between these ranges and the encoder's
length is refused rather than guessed, so a future encoder bump cannot
silently mislabel columns.
"""

from __future__ import annotations

from ..engine.cards import SUITS, TRUMP
from ..rl.encode import CARD_INDEX, N_CARDS
from ..rl.encode_versions import ENC_VERSION, OBS_DIM_BY_VERSION, check_version, encode_obs

_SUITS_EFF = list(SUITS) + [TRUMP]
# the encoder's canonical order, derived from its own index so the two cannot disagree
CARD_ORDER = sorted(CARD_INDEX, key=CARD_INDEX.__getitem__)
assert len(CARD_ORDER) == N_CARDS
_REL = ("self", "next", "partner", "previous")


def _card_plane(values):
    """Nonzero entries of one 54-wide card plane as ``{card: count}``.

    The encoder stores copies as 0 / 0.5 / 1.0; report the copy count."""
    return {CARD_ORDER[i]: int(round(v * 2)) for i, v in enumerate(values) if v}


def _v1_groups():
    """Named slices of encoder v1 (531), in the exact order ``encode.encode_obs`` writes."""
    groups, at = [], 0

    def take(name, width, kind, **extra):
        nonlocal at
        groups.append({"name": name, "start": at, "width": width, "kind": kind, **extra})
        at += width

    take("own_hand", N_CARDS, "cards")
    for rel in _REL:
        take(f"played_by_{rel}", N_CARDS, "cards")
    for i in range(3):
        take(f"current_trick_play_{i + 1}", N_CARDS, "cards")
    take("unseen", N_CARDS, "cards")
    take("trump_suit_onehot", 5, "onehot", labels=["S", "H", "D", "C", "NT"])
    take("trump_rank_onehot", 13, "onehot")
    take("banker_relative", 4, "onehot", labels=list(_REL))
    take("attacker_points_frac", 1, "scalar")
    take("cards_remaining_frac", 1, "scalar")
    take("is_attacker", 1, "scalar")
    take("observed_voids", 20, "flags",
         labels=[f"{rel}:{eff}" for rel in _REL for eff in _SUITS_EFF])
    assert at == OBS_DIM_BY_VERSION[1], at
    return groups, at


def _v2_groups(at):
    """The 29 columns ``encode_versions.encode_obs_v2_columns`` appends, in order."""
    groups = []

    def take(name, width, kind, **extra):
        nonlocal at
        groups.append({"name": name, "start": at, "width": width, "kind": kind, **extra})
        at += width

    take("trick_winner_relative", 4, "onehot", labels=list(_REL))
    take("trick_winner_is_partner", 1, "scalar")
    take("trick_points_frac", 1, "scalar")
    take("lead_suit_onehot", 5, "onehot", labels=list(_SUITS_EFF))
    take("position_in_trick", 4, "onehot")
    take("lead_size_frac", 1, "scalar")
    take("points_regime_kink", 1, "scalar")
    take("points_band", 4, "onehot", labels=["<40", "<80", "<120", ">=120"])
    take("own_suit_lengths_frac", 5, "scalars", labels=list(_SUITS_EFF))
    take("unseen_trumps_frac", 1, "scalar")
    take("own_pair_rank_count_frac", 1, "scalar")
    take("hand_size_frac", 1, "scalar")
    assert at == OBS_DIM_BY_VERSION[2], at
    return groups, at


def ml_input_features(rnd, seat: int, evaluator) -> dict:
    """The evaluator's public input block for the ROOT state, named; a layout preview, not a scored input."""
    version = check_version(getattr(evaluator, "enc_version", None) or ENC_VERSION)
    obs = encode_obs(rnd, seat, version=version)
    groups, at = _v1_groups()
    if version >= 2:
        more, at = _v2_groups(at)
        groups += more
    if at != len(obs):
        # A newer encoder appended columns this module does not know by name.
        # Refuse to label them; say how many there are instead.
        groups.append({"name": f"encoder_v{version}_appended", "start": at,
                       "width": len(obs) - at, "kind": "unlabelled"})
        at = len(obs)
    rendered = {}
    for g in groups:
        chunk = obs[g["start"]:g["start"] + g["width"]]
        if g["kind"] == "cards":
            value = _card_plane(chunk)
        elif g["kind"] == "onehot":
            hot = [i for i, v in enumerate(chunk) if v]
            labels = g.get("labels")
            value = None if not hot else (labels[hot[0]] if labels else hot[0])
        elif g["kind"] == "flags":
            value = [g["labels"][i] for i, v in enumerate(chunk) if v]
        elif g["kind"] == "scalars":
            value = dict(zip(g["labels"], (round(float(v), 4) for v in chunk)))
        elif g["kind"] == "scalar":
            value = round(float(chunk[0]), 4)
        else:
            value = [round(float(v), 4) for v in chunk]
        rendered[g["name"]] = {"kind": "model-input", "type": g["kind"],
                               "columns": [g["start"], g["start"] + g["width"]],
                               "value": value}
    return {
        "kind": "model-input",
        # SCOPE, stated in the response because it is easy to misread (Codex,
        # PR #344 review): this is the ROOT/CURRENT board encoded once.  The
        # inputs behind the displayed candidate scores are NOT this vector:
        # `cwv_shortlist._means` applies each candidate, completes the trick,
        # and encodes that leaf in each sampled world, so ten of these groups
        # (own hand, the played-by planes, unseen, cards remaining, suit
        # lengths, pair count, hand size) differ per candidate and per world.
        "scope": "root_state_preview",
        "scope_note": ("encoder layout and the current board's values; NOT the input "
                       "behind any displayed candidate score, which is the "
                       "candidate's trick-completed afterstate in each sampled world"),
        "encoder_version": version,
        "public_dim": len(obs) + 1,
        "round_end_flag": float(rnd.phase == "round_end"),
        "groups": rendered,
        "world_block": {
            "kind": "model-input", "rendered": False,
            "why": "sampled hidden hands, one complete world per sample "
                   "(W per decision); never shown on the X-ray",
        },
    }
