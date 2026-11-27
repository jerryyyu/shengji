"""Verify a produced belief-tree bank row and recover its paired gains."""
from collections import Counter
from math import isfinite
import re

from ..engine.cards import make_deck


_DECK_COPIES = Counter(make_deck())
_COMMON = {"deal_key", "decision_index", "mirror", "ply", "seat", "policy",
           "eligible", "ineligible_reason", "ballot"}
_FLAT_PASS = {"flat_means", "flat_final_action", "flat_final_accepted"}
_PAIRED = {"flat_action", "tree_action", "tree_means", "flat_all_tied",
           "yardsticks", "sf_gain", "vt_gain", "sf_regret_change"}


def _action(value):
    if (type(value) is not list or not value
            or any(type(card) is not str for card in value)
            or value != sorted(value) or Counter(value) - _DECK_COPIES):
        raise ValueError("expected a canonical nonempty card action")
    return tuple(value)


def _accepted(attempted, value):
    accepted = _action(value)
    if Counter(accepted) - Counter(attempted):
        raise ValueError("accepted lead is not a subset of the attempt")
    return accepted


def _number(value):
    if type(value) not in (int, float):
        raise ValueError("expected a finite bank estimate")
    try:
        if isfinite(value):
            return float(value)
    except OverflowError:
        pass
    raise ValueError("expected a finite bank estimate")


def _means(values, ballot_size):
    if type(values) is not list or len(values) != ballot_size:
        raise ValueError("estimate count differs from the ballot")
    return [_number(value) for value in values]


def checked_gains(row: dict) -> tuple[float, float] | None:
    """Validate a v2 row and return its signed tree-minus-flat gains.

    The caller matches the row identity against its reserved target. A valid
    singleton returns None. Malformed or inconsistent rows raise ValueError.
    """
    if type(row) is not dict or not _COMMON <= row.keys():
        raise ValueError("missing bank row fields")
    key, policy = row["deal_key"], row["policy"]
    if (type(key) is not str or not re.fullmatch(r"deck:[0-9a-f]{64}", key)
            or type(policy) is not str or not policy.strip()
            or any(type(row[name]) is not int for name in ("decision_index", "mirror", "ply", "seat"))):
        raise ValueError("invalid bank row identity")
    mirror, ply, seat = row["mirror"], row["ply"], row["seat"]
    offset = row["decision_index"] - ply
    if (mirror not in (0, 1) or seat not in range(4) or ply < 0 or ply % 4
            or (mirror == 0 and offset != 0) or (mirror == 1 and (offset <= 0 or offset % 4))):
        raise ValueError("invalid bank row lead identity")

    eligible, reason = row["eligible"], row["ineligible_reason"]
    if eligible is True and reason is None:
        fields = _COMMON | _FLAT_PASS | _PAIRED
    elif eligible is False and reason == "single_legal_action":
        fields = _COMMON
    elif eligible is False and reason == "single_admitted_action":
        fields = _COMMON | _FLAT_PASS
    else:
        raise ValueError("invalid bank row eligibility")
    if row.keys() != fields or type(row["ballot"]) is not list:
        raise ValueError("bank row fields disagree with eligibility")
    ballot = [_action(action) for action in row["ballot"]]
    ballot_keys = set(ballot)
    if (len(ballot_keys) != len(ballot)
            or (eligible and len(ballot) < 2) or (not eligible and len(ballot) != 1)):
        raise ValueError("invalid eligible or singleton ballot")
    if reason == "single_legal_action":
        return None

    flat = _means(row["flat_means"], len(ballot))
    final_action = _action(row["flat_final_action"])
    final_accepted = _accepted(final_action, row["flat_final_accepted"])
    if not eligible:
        if final_action != ballot[0]:
            raise ValueError("final selection differs from its single admitted action")
        return None

    tree = _means(row["tree_means"], len(ballot))
    flat_pick, tree_pick = flat.index(max(flat)), tree.index(max(tree))
    flat_all_tied = all(mean == flat[0] for mean in flat)
    if (_action(row["flat_action"]) != ballot[flat_pick]
            or _action(row["tree_action"]) != ballot[tree_pick]
            or row["flat_all_tied"] is not flat_all_tied):
        raise ValueError("picks or ties disagree with the paired means")
    yardsticks = row["yardsticks"]
    if type(yardsticks) is not list or len(yardsticks) != len(ballot):
        raise ValueError("yardstick count differs from the ballot")
    values = {}
    for item in yardsticks:
        if type(item) is not dict or item.keys() != {"action", "accepted", "sf", "vt"}:
            raise ValueError("invalid yardstick fields")
        action = _action(item["action"])
        if action not in ballot_keys or action in values:
            raise ValueError("yardstick actions must cover the ballot once")
        accepted = _accepted(action, item["accepted"])
        if action == final_action and accepted != final_accepted:
            raise ValueError("inconsistent accepted lead for the final flat action")
        values[action] = (_number(item["sf"]), _number(item["vt"]))

    flat_sf, flat_vt = values[ballot[flat_pick]]
    tree_sf, tree_vt = values[ballot[tree_pick]]
    sf, vt = tree_sf - flat_sf, tree_vt - flat_vt
    if (_number(row["sf_gain"]), _number(row["vt_gain"]), _number(row["sf_regret_change"])) != (sf, vt, -sf):
        raise ValueError("gains or regret sign disagree with the paired yardsticks")
    return sf, vt
