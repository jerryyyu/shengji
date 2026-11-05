"""Reconstruct a bounded lead root from a validated saved-result row."""

from collections import Counter
from random import Random

from shengji.ai.refusal import RefusalLedger
from shengji.engine.round import Round


def _int(value, name):
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _cards(value, name):
    if not isinstance(value, list) or any(not isinstance(card, str) for card in value):
        raise ValueError(f"{name} must be a list of card codes")
    return list(value)


def _entry(value, name, minimum):
    if not isinstance(value, list) or len(value) < minimum:
        raise ValueError(f"{name} is malformed")
    return value


def _validated_row(row):
    if not isinstance(row, dict):
        raise ValueError("saved row must be an object")
    seed = _int(row.get("seed"), "seed")
    trump_rank = row.get("trump_rank")
    if not isinstance(trump_rank, str) or not trump_rank:
        raise ValueError("trump_rank must be a nonempty string")
    planned_banker = row.get("planned_banker")
    if planned_banker is not None:
        planned_banker = _int(planned_banker, "planned_banker")
        if planned_banker not in range(4):
            raise ValueError("planned_banker is out of range")
    declares = row.get("declares")
    if not isinstance(declares, list):
        raise ValueError("declares must be a list")
    for index, declaration in enumerate(declares):
        entry = _entry(declaration, f"declares[{index}]", 4)
        decl_seat = _int(entry[0], f"declares[{index}].seat")
        if decl_seat not in range(4):
            raise ValueError("declaration seat is out of range")
        _cards(entry[1], f"declares[{index}].cards")
        if type(entry[2]) is not int or entry[2] < 1:
            raise ValueError("declaration strength is invalid")
        if type(entry[3]) is not bool:
            raise ValueError("declaration final flag is invalid")

    banker = _int(row.get("banker"), "banker")
    if banker not in range(4):
        raise ValueError("banker is out of range")
    trump = row.get("trump")
    if not isinstance(trump, str) or not trump:
        raise ValueError("trump must be a nonempty string")
    buried = _cards(row.get("buried"), "buried")
    if len(buried) != 8:
        raise ValueError("buried must contain eight cards")
    dtrace = row.get("dtrace")
    if not isinstance(dtrace, list):
        raise ValueError("dtrace must be a list")
    history = row.get("history")
    if not isinstance(history, list):
        raise ValueError("history must be a list")
    plays = []
    for index, event in enumerate(dtrace):
        if not isinstance(event, list) or not event:
            raise ValueError(f"dtrace[{index}] is malformed")
        if event[0] != "P":
            continue
        entry = _entry(event, f"dtrace[{index}]", 6)
        event_seat = _int(entry[1], f"dtrace[{index}].seat")
        if event_seat not in range(4):
            raise ValueError("play seat is out of range")
        hand_len = _int(entry[4], f"dtrace[{index}].handlen")
        if not 0 <= hand_len <= 33:
            raise ValueError("play handlen is out of range")
        attempted = _cards(entry[5], f"dtrace[{index}].attempted")
        if not attempted:
            raise ValueError("attempted play is empty")
        plays.append((event_seat, hand_len, attempted))
    for index, item in enumerate(history):
        entry = _entry(item, f"history[{index}]", 2)
        _cards(entry[1], f"history[{index}].accepted")
    return (seed, trump_rank, planned_banker, declares, banker, trump, buried,
            plays, history)


def reconstruct_saved_lead(row, play_index, seat):
    """Return ``(Round, RefusalLedger)`` at a saved acting lead.

    ``play_index`` counts only ``P`` entries in ``dtrace``.  Prefix plays use
    their attempted cards; ``history`` independently witnesses normalization
    of failed throws.  Every target-seat turn is observed before the play and
    the returned root is observed once more at the target decision point.
    """
    values = _validated_row(row)
    _int(play_index, "play_index")
    _int(seat, "seat")
    if seat not in range(4):
        raise ValueError("seat is out of range")
    (seed, trump_rank, planned_banker, declares, banker, trump, buried,
     plays, history) = values
    if not 0 <= play_index <= len(plays):
        raise ValueError("play_index is out of range")
    if len(history) < play_index:
        raise ValueError("history is missing a played prefix")

    try:
        rnd = Round(trump_rank, planned_banker, Random(seed))
        while rnd.phase == "deal":
            rnd.deal_next()
        for declaration in declares:
            rnd.declare(declaration[0], list(declaration[1]))
        rnd.finalize_declare()
    except Exception as exc:
        raise ValueError("invalid saved setup") from exc
    if rnd.banker != banker:
        raise ValueError("banker mismatch")
    expected_trump = "NT" if rnd.trump_is_nt else rnd.trump_suit
    if expected_trump != trump:
        raise ValueError("trump mismatch")
    try:
        rnd.bury(banker, list(buried))
    except Exception as exc:
        raise ValueError("invalid saved burial") from exc

    ledger = RefusalLedger()
    for index, (event_seat, hand_len, attempted) in enumerate(plays[:play_index]):
        if index >= len(history):
            raise ValueError("history is missing a played prefix")
        accepted = history[index][1]
        if rnd.turn != event_seat:
            raise ValueError("play prefix turn mismatch")
        if len(rnd.hands[event_seat]) != hand_len:
            raise ValueError("play prefix hand length mismatch")
        if event_seat == seat:
            ledger.observe(rnd)
        before = Counter(rnd.hands[event_seat])
        try:
            rnd.play(event_seat, list(attempted))
        except Exception as exc:
            raise ValueError("attempted play cannot be replayed") from exc
        if before - Counter(rnd.hands[event_seat]) != Counter(accepted):
            raise ValueError("accepted cards mismatch")

    if rnd.turn != seat or rnd.phase != "play" or rnd.trick is None or rnd.trick.plays:
        raise ValueError("target is not an acting empty-trick lead")
    ledger.observe(rnd)
    return rnd, ledger
