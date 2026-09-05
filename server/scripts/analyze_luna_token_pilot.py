"""Opened-DEV decision comparison under two fixed continuation policies.

These rollouts are a sensitivity diagnostic, not optimal-action labels and
not a head-to-head strength result. Never count repeated positions as games.
"""
import argparse
from collections import defaultdict
import itertools
from pathlib import Path
import time

from scripts.luna_token_pilot import ARMS, load, publish
from shengji.luna import game
from shengji.luna.turn import DecisionPacket


def analyze(root, max_seconds=120):
    root = Path(root)
    packets = {}
    decisions = defaultdict(dict)
    for arm in ARMS:
        for path in sorted(root.glob(f"{arm}-[0-9]*.json")):
            call = load(path)
            if not call["accepted"]:
                continue
            for raw, decision in zip(call["packets"], call["decisions"], strict=True):
                packet = DecisionPacket.from_mapping(raw)
                packets[packet.sha256] = packet
                decisions[packet.sha256][arm] = decision["candidate_index"]
    complete = {h: d for h, d in decisions.items() if set(d) == set(ARMS)}
    started = time.monotonic()
    rows = []
    for h, chosen in sorted(complete.items()):
        path = root / f"quality-{h}.json"
        if path.exists():
            rows.append(load(path))
            continue
        packet = packets[h]
        rnd = game._round_from_snapshot(packet.state)
        scores = {}
        for index in sorted({0, *chosen.values()}):
            scores[str(index)] = {}
            for continuation in ("heuristic-all", "smart-all"):
                if time.monotonic() - started > max_seconds:
                    raise RuntimeError("quality diagnostic wall exhausted; completed positions retained")
                bot = game.ProductionBallotBot(seed=0)
                bot.rollout_policy, bot.EXACT_ENDGAME = game._continuation(continuation, packet.team)
                sampled = {seat: list(rnd.hands[seat]) for seat in range(4) if seat != rnd.turn}
                session = bot._new_exact_world_session(rnd, list(rnd.buried))
                points = bot._rollout(rnd, rnd.turn, sampled, list(rnd.buried),
                                      list(packet.candidates[index]), exact_session=session)
                scores[str(index)][continuation] = game.signed_level_utility(
                    int(points), banker_seat=rnd.banker, perspective_seat=packet.team)
        row = {"packet_sha256": h, "coordinate": list(packet.coordinate),
               "decision_index": packet.decision_index, "chosen": chosen, "scores": scores}
        publish(path, row)
        rows.append(row)
    summary = {}
    for arm in ARMS:
        cluster_diffs = defaultdict(list)
        prior_diffs = []
        for row in rows:
            scores = row["scores"]
            def value(index):
                return sum(scores[str(index)].values()) / 2
            cluster_diffs[tuple(row["coordinate"])].append(
                value(row["chosen"][arm]) - value(row["chosen"]["baseline"]))
            prior_diffs.append(value(row["chosen"][arm]) - value(0))
        clusters = [sum(v) / len(v) for v in cluster_diffs.values()]
        boot = sorted(sum(x) / len(x) for x in itertools.product(clusters, repeat=len(clusters))) if clusters else []
        summary[arm] = {
            "positions": len(rows), "independent_games": len(clusters),
            "agrees_with_baseline": sum(r["chosen"][arm] == r["chosen"]["baseline"] for r in rows),
            "differs_from_candidate_zero": sum(r["chosen"][arm] != 0 for r in rows),
            "mean_proxy_signed_level_difference_vs_baseline": sum(clusters) / len(clusters) if clusters else None,
            "exploratory_game_bootstrap_95pct": [boot[int(.025 * (len(boot)-1))], boot[int(.975 * (len(boot)-1))]] if boot else None,
            "mean_position_proxy_difference_vs_prior": sum(prior_diffs) / len(prior_diffs) if prior_diffs else None,
        }
    result = {"rows": rows, "arms": summary, "matched_positions": len(rows),
              "unmatched_positions": len(packets) - len(rows),
              "continuations": ["heuristic-all", "smart-all"],
              "claim": "Fixed-continuation sensitivity only; neither optimal labels nor gameplay strength. "
                       "Four games give very weak quality precision. Teacher thoughts are not graded."}
    destination = root / "quality-summary.json"
    if not destination.exists():
        publish(destination, result)
    return result


if __name__ == "__main__":
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    result = analyze(args.root)
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, sort_keys=True))
