"""Strict, bounded reconstruction of an S11 public trajectory.

This is a diagnostic adapter.  It replays the real submitted actions and
returns a copy of the selected decision root plus the refusals visible to the
selected actor.  It does not sample hidden hands, restore RNG state, or read
outcomes/model values.
"""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Mapping, Sequence
import re

from ..ai.refusal import RefusalLedger
from ..engine.round import actual_play_after
from ..harvest.rebuild import RebuildError, deck_from_seed, round_from_setup


class S11ReconstructionError(ValueError):
    """The supplied trajectory is not a complete, self-consistent replay."""


def _fail(message: str):
    raise S11ReconstructionError(message)


def _cards(value, label: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or any(type(c) is not str for c in value):
        _fail(f"{label} must be a list of card codes")
    return list(value)


def _same(value, other, label: str) -> None:
    if value != other:
        _fail(f"inconsistent {label}")


_SOURCE_REF = re.compile(r"^([^:]+):(\d+):(\d+):(\d+):(\d+)$")


def reconstruct_s11_trajectory(rows: Sequence[Mapping], selected_ply: int, *,
                               actor_seat: int | None = None) -> dict:
    """Replay one complete ordered deal/mirror trajectory.

    Each play row repeats ``deck`` and ``round_seed``, ``setup``, and contains
    ``source_ref`` (the canonical run/cluster/mirror/seat/ply identity),
    ``decision_kind='play'``, ``ply``, ``seat``, ``action``, ``engine_play``
    (optional only when equal to action), and the committed ``plays_prefix`` *before* that action. The
    replay must reach the engine's ``round_end`` phase; no synthetic terminal
    marker is accepted as a substitute.

    ``selected_ply`` is zero based and identifies the decision root before
    that row's action.  The returned ledger is observed only at that actor's
    turns through the selected root.  This is explicitly a history-primed
    diagnostic; it is not live RNG or provenance restoration.
    """
    if not isinstance(rows, (list, tuple)) or not rows:
        _fail("rows must be a nonempty ordered sequence")
    if type(selected_ply) is not int or not 0 <= selected_ply < len(rows):
        _fail("selected_ply must identify one supplied play row")

    first = rows[0]
    if not isinstance(first, Mapping):
        _fail("play rows must be mappings")
    if first.get("decision_kind") != "play":
        _fail("trajectory rows must have decision_kind='play'")
    source_ref = first.get("source_ref")
    match = _SOURCE_REF.fullmatch(source_ref) if isinstance(source_ref, str) else None
    if match is None:
        _fail("source_ref must be canonical run:cluster:mirror:seat:ply")
    run_id, cluster, mirror, source_seat, source_ply = match.groups()
    if mirror not in ("0", "1"):
        _fail("mirror must be 0 or 1")
    source_identity = (run_id, int(cluster), int(mirror))
    setup = first.get("setup")
    if not isinstance(setup, Mapping):
        _fail("setup is required")
    setup = copy.deepcopy(dict(setup))

    deck_value = first.get("deck")
    seed_value = first.get("round_seed")
    if deck_value is None or type(seed_value) is not int or seed_value < 0:
        _fail("trajectory needs valid deck and round_seed")
    deck = _cards(deck_value, "deck")
    try:
        seeded = deck_from_seed(setup["trump_rank"], setup["banker"], seed_value)
    except (KeyError, TypeError, ValueError, RebuildError) as exc:
        raise S11ReconstructionError("invalid round_seed/setup") from exc
    if deck != seeded:
        _fail("deck and round_seed disagree")

    ledger = RefusalLedger()
    try:
        rnd = round_from_setup(deck, setup)
    except (KeyError, TypeError, ValueError, RebuildError) as exc:
        raise S11ReconstructionError("invalid deck/setup") from exc

    selected_root = None
    selected_actor = actor_seat
    if selected_actor is None:
        selected_row = rows[selected_ply]
        if not isinstance(selected_row, Mapping):
            _fail("selected row is not a mapping")
        candidate = selected_row.get("seat")
        if type(candidate) is int:
            selected_actor = candidate
    committed: list[dict] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            _fail(f"row {index} is not a mapping")
        if row.get("decision_kind") != "play":
            _fail("trajectory rows must have decision_kind='play'")
        row_ref = row.get("source_ref")
        row_match = _SOURCE_REF.fullmatch(row_ref) if isinstance(row_ref, str) else None
        if row_match is None:
            _fail("source_ref must be canonical run:cluster:mirror:seat:ply")
        row_run, row_cluster, row_mirror, row_source_seat, row_source_ply = row_match.groups()
        if (row_run, int(row_cluster), int(row_mirror)) != source_identity:
            _fail("inconsistent trajectory identity")
        if type(row.get("ply")) is not int or row.get("ply") != index or int(row_source_ply) != index:
            _fail("plies must be exactly contiguous and ordered")
        _same(row.get("setup"), setup, "setup")
        _same(row.get("deck"), deck, "deck")
        if type(row.get("round_seed")) is not int:
            _fail("round_seed must be an integer")
        _same(row.get("round_seed"), seed_value, "round_seed")

        seat = row.get("seat")
        if type(seat) is not int or seat not in range(4) or seat != rnd.turn or int(row_source_seat) != seat:
            _fail(f"row {index} actor seat does not match engine turn")
        if selected_actor is None:
            selected_actor = seat
        elif type(selected_actor) is not int or selected_actor not in range(4):
            _fail("actor_seat must be a table seat")

        prefix = row.get("plays_prefix")
        if not isinstance(prefix, list) or prefix != committed:
            _fail(f"row {index} has a non-contiguous plays_prefix")
        action = _cards(row.get("action"), f"row {index} action")

        if index <= selected_ply and seat == selected_actor:
            ledger.observe(rnd)
        if index == selected_ply:
            if seat != selected_actor:
                _fail("selected row is not an actor turn")
            selected_root = copy.deepcopy(rnd)

        previous_last = rnd.last_trick
        try:
            rnd.play(seat, action)
        except Exception as exc:
            raise S11ReconstructionError(f"submitted action rejected at ply {index}") from exc
        actual = actual_play_after(rnd, seat, previous_last)
        expected = row.get("engine_play", action)
        expected = _cards(expected, f"row {index} engine_play")
        if Counter(actual) != Counter(expected):
            _fail(f"committed play mismatch at ply {index}")
        committed.append({"seat": seat, "cards": actual})

    if selected_root is None:
        _fail("selected root was not reconstructed")
    if rnd.phase != "round_end":
        _fail("trajectory is terminally truncated")
    return {
        "schema": "s11-history-primed-reconstruction-v1",
        "root": selected_root,
        "ledger": ledger,
        "selected_ply": selected_ply,
        "actor_seat": selected_actor,
        "identity": {"run_id": run_id, "cluster": int(cluster), "mirror": int(mirror)},
        "history_primed": True,
        "live_rng_state_reconstructed": False,
        "provenance_verified": False,
    }
