"""Aggregate verified paired deck outputs for the reserved offline teacher comparison."""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from collections import Counter

from .belief_tree_bank_settings import pilot_settings
from .belief_tree_bank_row import checked_gains


def _turn_id(row):
    identity = tuple(row[key] for key in ("mirror", "ply", "seat", "decision_index"))
    if any(type(v) is not int or v < 0 for v in identity):
        raise ValueError("invalid turn identity")
    return identity


def checked_deck(deck, reservation, *, source, bank_sha256, settings):
    """Bind the four scored or structurally excluded turns to one reserved deal."""
    expected = {"schema": "belief-tree-paired-deck-v2", "bank_sha256": bank_sha256,
                "shard_sha256": reservation["sha256"], "deal_key": reservation["key"],
                "round_seed": reservation["seed"], "run_id": source["run_id"],
                "policy": source["policy"]}
    if any(deck[key] != value for key, value in expected.items()):
        raise ValueError("deck output disagrees with its reservation")
    if json.dumps(deck["settings"], sort_keys=True) != json.dumps(settings, sort_keys=True):
        raise ValueError("deck scoring settings changed")
    targets = {_turn_id(t) for t in reservation["targets"]}
    if (len(reservation["targets"]) != 4 or len(targets) != 4
            or sorted(t[0] for t in targets) != [0, 0, 1, 1]
            or len({t[3] for t in targets}) != 4 or len({t[:2] for t in targets}) != 4):
        raise ValueError("invalid four-turn deck reservation")
    rows = deck["rows"]
    if len(rows) != 4 or {_turn_id(row) for row in rows} != targets:
        raise ValueError("missing, repeated or unreserved turn")
    gains = []
    counts = Counter()
    for row in rows:
        if row["policy"] != source["policy"] or row["deal_key"] != reservation["key"]:
            raise ValueError("wrong row deck or policy")
        gain = checked_gains(row)
        if gain is None:
            counts[row["ineligible_reason"]] += 1
        else:
            gains.append(gain)
            counts["flat_all_tied"] += int(row["flat_all_tied"])
            counts["identical_picks"] += int(row["flat_action"] == row["tree_action"])
            counts["final_differs_from_base"] += int(row["flat_final_action"] != row["flat_action"])
    return gains, counts


def _cluster_interval(groups, column):
    """Ratio of sums with each represented deck contributing one cluster residual."""
    n = sum(len(group) for group in groups)
    sums = [math.fsum(pair[column] for pair in group) for group in groups]
    mean = math.fsum(sums) / n
    c = len(groups)
    variance_sum = math.fsum((total - len(group) * mean) ** 2 for group, total in zip(groups, sums))
    se = math.sqrt(c / (c - 1) * variance_sum) / n
    return dict(mean=mean, se=se, lo=mean - 1.96 * se, hi=mean + 1.96 * se)


def analyze_bank(bank_bytes, decks, *, bank_sha256, settings):
    """Consume already admitted deck outputs with the independently pinned reservation and settings."""
    if hashlib.sha256(bank_bytes).hexdigest() != bank_sha256:
        raise ValueError("reserved bank digest mismatch")
    widths = ("depth_worlds", "reply_cap", "batch_size")
    if (type(settings) is not dict or set(settings) != {"seed", "reply_value_weight", *widths}
            or type(settings["seed"]) is not int or settings["seed"] < 0
            or any(type(settings[k]) is not int or settings[k] < 1 for k in widths)
            or type(settings["reply_value_weight"]) not in (float, int)
            or not math.isfinite(settings["reply_value_weight"]) or settings["reply_value_weight"] < 0):
        raise ValueError("invalid expected bank scoring settings")
    manifest = json.loads(bank_bytes)
    reservations = {r["key"]: r for r in manifest["deals"]}
    if (len(manifest["deals"]) != 188 or len(reservations) != 188
            or len({r["seed"] for r in reservations.values()}) != 188
            or len({r["shard"] for r in reservations.values()}) != 188):
        raise ValueError("expected the complete 188-deck reservation")
    seen = set()
    groups = []
    counts = Counter()
    for deck in decks:
        key = deck["deal_key"]
        if key not in reservations or key in seen:
            raise ValueError("unexpected or duplicate scored deck")
        seen.add(key)
        gains, diagnostics = checked_deck(deck, reservations[key], source=manifest["source"],
                                          bank_sha256=bank_sha256, settings=settings)
        counts.update(diagnostics)
        if gains:
            groups.append(gains)
    if seen != reservations.keys():
        raise ValueError("missing scored deck")
    n = sum(map(len, groups))
    result = dict(schema="belief-tree-paired-bank-analysis-v1", bank_sha256=bank_sha256,
                  policy=manifest["source"]["policy"], run_id=manifest["source"]["run_id"],
                  settings=dict(settings), reserved_decks=len(seen), eligible_turns=n,
                  represented_decks=len(groups), counts=dict(counts))
    if n < 700 or len(groups) < 175:
        return dict(result, verdict="INSUFFICIENT")
    sf = _cluster_interval(groups, 0)
    vt = _cluster_interval(groups, 1)
    regret = dict(mean=-sf["mean"], se=sf["se"], lo=-sf["hi"], hi=-sf["lo"])
    passed = sf["mean"] >= .003 and sf["lo"] > 0 and vt["mean"] >= 0 and regret["hi"] < 0
    return dict(result, served_finish_gain=sf, heuristic_finish_gain=vt,
                served_regret_change=regret, verdict="PASS" if passed else "FAIL")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analyze admitted deck JSON documents, one per stdin line.")
    parser.add_argument("--bank", required=True, type=Path)
    parser.add_argument("--bank-sha256", required=True)
    settings = parser.add_mutually_exclusive_group(required=True)
    settings.add_argument("--settings", type=json.loads)
    settings.add_argument("--pilot-settings", dest="settings", action="store_const", const=pilot_settings())
    args = parser.parse_args(argv)
    result = analyze_bank(args.bank.read_bytes(), (json.loads(line) for line in sys.stdin),
                          bank_sha256=args.bank_sha256, settings=args.settings)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
