"""Audit frozen v11pair against Smart's fixed action on high-N DEV rows.

This deliberately does *not* score either policy against the row's selected
``best`` action.  v11 was trained independently of this corpus, and candidate
0 is the stored SmartBot action, so ``mean[v11] - mean[0]`` is a predeclared
fixed-pair comparison on common worlds.  It avoids the selected-maximum bias
that invalidates "regret to high-N best" as a promotion metric.

The result still estimates only the corpus's historical ``Q^Heuristic``
contract: old ballot, old non-strict sampler, raw points, heuristic
continuation, and an early-heavy state distribution.  It is useful for
diagnosing where v11 has signal and where its misses live; it cannot promote a
policy, tune a deployable threshold, or establish an MC anchor win.

Only the frozen DEV assignment is read.  CALIB and REPORT remain untouched.

    .venv/bin/python scripts/highn_v11_audit.py \
        --out runs/logs/highn_v11_fixed_pair_dev.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.corpus_split import load_split  # noqa: E402
from scripts.pilot_states import replay  # noqa: E402
from shengji.ai.mcbot import MCBot  # noqa: E402
from shengji.ai.smart import SmartBot  # noqa: E402
from shengji.engine.combos import decompose  # noqa: E402
from shengji.rl.encode import encode_action, encode_obs  # noqa: E402
from shengji.rl.npnet import NpNet  # noqa: E402


EXPECTED_NPZ_SHA256 = (
    "cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003"
)
MARGIN = 0.02


def digest(path: str, *, short: bool = False) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16] if short else h.hexdigest()


def canonical(cards) -> tuple[str, ...]:
    return tuple(sorted(cards))


def phase(trick: int) -> str:
    return "early" if trick < 5 else ("mid" if trick < 12 else "late")


def archetype(cards, rnd) -> str:
    """Coarse action type, using the engine for multi-card decomposition."""
    if len(cards) == 1:
        card = cards[0]
        if rnd.ordering is not None and rnd.ordering.is_trump(card):
            return "single_trump"
        return "single_point" if card[1:] in ("5", "10", "K") else "single_nonpoint"
    try:
        components = decompose(list(cards), rnd.ordering).components
    except Exception:
        components = []
    return components[0].kind if len(components) == 1 else "throw"


def clustered_mean(rows: list[dict]) -> dict:
    """Equal-row mean with an intercept-only deal-clustered standard error."""
    if not rows:
        return {"n": 0, "deals": 0, "mean": None, "se": None, "hw95": None}
    n = len(rows)
    mean = sum(r["delta"] for r in rows) / n
    residual_by_deal: dict[int, float] = defaultdict(float)
    for row in rows:
        residual_by_deal[row["seed"]] += row["delta"] - mean
    groups = len(residual_by_deal)
    finite_sample = groups / max(groups - 1, 1)
    se = math.sqrt(
        finite_sample * sum(v * v for v in residual_by_deal.values()) / (n * n)
    )
    return {"n": n, "deals": groups, "mean": mean, "se": se, "hw95": 1.96 * se}


def summarize(rows: list[dict]) -> dict:
    result = clustered_mean(rows)
    overrides = [row for row in rows if row["choice_index"] != 0]
    n_override = len(overrides)
    result.update({
        "overrides": n_override,
        "override_rate": n_override / max(len(rows), 1),
        "override_mean": (
            sum(row["delta"] for row in overrides) / n_override
            if overrides else None
        ),
        "override_harmful_rate": (
            sum(row["delta"] < 0 for row in overrides) / n_override
            if overrides else None
        ),
        "override_clear_positive_rate": (
            sum(row["delta"] > 2 * row["paired_se"] for row in overrides)
            / n_override if overrides else None
        ),
        "override_clear_negative_rate": (
            sum(row["delta"] < -2 * row["paired_se"] for row in overrides)
            / n_override if overrides else None
        ),
    })
    return result


def strata(rows: list[dict], field: str) -> dict:
    values = sorted({row[field] for row in rows}, key=str)
    return {str(value): summarize([row for row in rows if row[field] == value])
            for value in values}


def prediction_bins(rows: list[dict]) -> dict:
    bins = ((0.02, 0.03), (0.03, 0.05), (0.05, 0.10), (0.10, math.inf))
    result = {}
    for low, high in bins:
        selected = [row for row in rows
                    if row["choice_index"] != 0
                    and low < row["predicted_gain"] <= high]
        label = (f"({low:.2f},{high:.2f}]" if math.isfinite(high)
                 else f"({low:.2f},inf)")
        result[label] = summarize(selected)
    return result


def compact_case(row: dict) -> dict:
    fields = (
        "seed", "ply", "seat", "lead", "trick", "phase", "role",
        "n_candidates", "predicted_gain", "delta", "paired_se", "base",
        "choice", "base_archetype", "choice_archetype",
    )
    return {field: row[field] for field in fields}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="rl_data/highn_corpus_all.jsonl")
    parser.add_argument("--split", default="rl_data/corpus_split.v1.json")
    parser.add_argument("--checkpoint", default="snapshots_v11pair/ep07.npz")
    parser.add_argument("--out")
    parser.add_argument("--max-states", type=int, default=0,
                        help="bounded smoke only; 0 means every DEV row")
    args = parser.parse_args()

    checkpoint_digest = digest(args.checkpoint)
    if checkpoint_digest != EXPECTED_NPZ_SHA256:
        raise SystemExit(
            f"REFUSING: checkpoint SHA-256 {checkpoint_digest} is not frozen "
            f"v11pair {EXPECTED_NPZ_SHA256}")
    assignments = load_split(args.split)
    with open(args.split) as fh:
        split_payload = json.load(fh)
    if os.path.normpath(split_payload["corpus"]) != os.path.normpath(args.corpus):
        raise SystemExit(
            f"REFUSING: split binds {split_payload['corpus']}, not {args.corpus}")

    net = NpNet(args.checkpoint)
    smart = SmartBot()
    current_mc = MCBot(seed=0)
    audited: list[dict] = []
    errors: list[dict] = []
    smart_mismatches: list[dict] = []
    ballot_mismatches: list[dict] = []
    dev_seen = 0

    with open(args.corpus) as fh:
        for line in fh:
            record = json.loads(line)
            if assignments.get(record["seed"]) != "dev":
                continue
            if args.max_states and dev_seen >= args.max_states:
                break
            dev_seen += 1
            try:
                rnd = replay(record)
                seat = record["seat"]
                actions = [list(action) for action in record["candidates"]]
                if len(actions) != len(record["mean"]):
                    raise ValueError("candidate/value length mismatch")
                if len(actions) != len(record["paired_se"]):
                    raise ValueError("candidate/paired-SE length mismatch")
                encoded = [encode_action(action, rnd) for action in actions]
                values = net.value_candidates(encode_obs(rnd, seat), encoded)
                gains = [float(value) - float(values[0]) for value in values]
                predicted = max(range(len(gains)), key=gains.__getitem__)
                choice = predicted if gains[predicted] > MARGIN else 0

                smart_action = smart.decide_play(rnd, seat)
                if canonical(smart_action) != canonical(actions[0]):
                    smart_mismatches.append({
                        "seed": record["seed"], "ply": record["ply"],
                        "seat": seat, "stored": actions[0], "current": smart_action,
                    })
                current_actions = current_mc._candidates(rnd, seat)
                stored_keys = [canonical(action) for action in actions]
                current_keys = [canonical(action) for action in current_actions]
                exact_ballot = current_keys == stored_keys
                same_ballot_set = Counter(current_keys) == Counter(stored_keys)
                if not same_ballot_set and len(ballot_mismatches) < 50:
                    ballot_mismatches.append({
                        "seed": record["seed"], "ply": record["ply"],
                        "seat": seat, "stored": actions, "current": current_actions,
                    })

                is_lead = not bool(rnd.trick and rnd.trick.plays)
                trick = len(rnd.history)
                role = "attacker" if rnd.is_attacker(seat) else "defender"
                n_candidates = len(actions)
                size = (
                    "small" if n_candidates <= 4
                    else "med" if n_candidates <= 9 else "wide"
                )
                audited.append({
                    "seed": record["seed"], "ply": record["ply"], "seat": seat,
                    "lead": is_lead, "trick": trick, "phase": phase(trick),
                    "role": role, "candidate_size": size,
                    "n_candidates": n_candidates, "choice_index": choice,
                    "predicted_gain": gains[predicted],
                    "delta": float(record["mean"][choice]) - float(record["mean"][0]),
                    "paired_se": float(record["paired_se"][choice]),
                    "base": actions[0], "choice": actions[choice],
                    "base_archetype": archetype(actions[0], rnd),
                    "choice_archetype": archetype(actions[choice], rnd),
                    "current_ballot_exact": exact_ballot,
                    "current_ballot_same_set": same_ballot_set,
                    "worlds": int(record["worlds"]),
                })
            except Exception as exc:
                errors.append({
                    "seed": record.get("seed"), "ply": record.get("ply"),
                    "seat": record.get("seat"), "error": repr(exc),
                })

    overrides = [row for row in audited if row["choice_index"] != 0]
    transitions: dict[str, list[dict]] = defaultdict(list)
    for row in overrides:
        if row["lead"]:
            key = f"{row['base_archetype']}->{row['choice_archetype']}"
            transitions[key].append(row)
    transition_report = {
        key: summarize(value)
        for key, value in sorted(transitions.items(), key=lambda item: -len(item[1]))
    }

    loss_key = lambda row: (
        row["delta"] / row["paired_se"] if row["paired_se"] > 0 else math.inf
    )
    payload = {
        "schema": "highn-v11-fixed-pair-dev-v1",
        "created": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "git": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True,
            text=True, check=True).stdout.strip(),
        "tree_dirty_at_start": bool(subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True,
            text=True, check=True).stdout.strip()),
        "script_sha256_16": digest(str(Path(__file__).resolve()), short=True),
        "corpus": args.corpus,
        "corpus_sha256_16": digest(args.corpus, short=True),
        "split": args.split,
        "split_sha256_16": digest(args.split, short=True),
        "side": "dev",
        "checkpoint": args.checkpoint,
        "checkpoint_sha256": checkpoint_digest,
        "margin": MARGIN,
        "estimand": (
            "mean[v11 fixed choice] - mean[stored Smart candidate0], in "
            "acting-team raw points under historical Q^Heuristic"
        ),
        "dev_rows_seen": dev_seen,
        "rows_audited": len(audited),
        "deals_audited": len({row["seed"] for row in audited}),
        "replay_or_inference_errors": errors,
        "smart_candidate0_mismatches": smart_mismatches,
        "current_ballot_exact_mismatches": sum(
            not row["current_ballot_exact"] for row in audited),
        "current_ballot_set_mismatches": sum(
            not row["current_ballot_same_set"] for row in audited),
        "current_ballot_set_mismatch_examples": ballot_mismatches,
        "world_counts": sorted({row["worlds"] for row in audited}),
        "summary": summarize(audited),
        "current_ballot_set_match_summary": summarize([
            row for row in audited if row["current_ballot_same_set"]]),
        "strata": {
            "lead": strata(audited, "lead"),
            "phase": strata(audited, "phase"),
            "role": strata(audited, "role"),
            "candidate_size": strata(audited, "candidate_size"),
        },
        "predicted_margin_bins": prediction_bins(audited),
        "lead_override_transitions": transition_report,
        "clearest_losses": [compact_case(row) for row in sorted(
            (row for row in overrides if row["paired_se"] > 0), key=loss_key)[:20]],
        "largest_raw_losses": [compact_case(row) for row in sorted(
            overrides, key=lambda row: row["delta"])[:20]],
        "limitations": [
            "historical old ballot and non-strict sampler",
            "raw-point Q^Heuristic under heuristic continuation, not level utility",
            "overwhelmingly early state distribution",
            "diagnostic DEV only; no threshold/filter was fitted or promoted",
            "stored means cannot simulate stochastic N=30 anchor behavior",
        ],
    }

    rendered = json.dumps(payload, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(rendered + "\n")
        os.replace(tmp, out)
        print(f"wrote {out}")
    print(json.dumps({
        "rows": payload["rows_audited"],
        "deals": payload["deals_audited"],
        "errors": len(errors),
        "smart_candidate0_mismatches": len(smart_mismatches),
        "current_ballot_exact_mismatches": payload[
            "current_ballot_exact_mismatches"],
        "current_ballot_set_mismatches": payload[
            "current_ballot_set_mismatches"],
        "summary": payload["summary"],
        "lead": payload["strata"]["lead"],
        "phase": payload["strata"]["phase"],
    }, indent=2))


if __name__ == "__main__":
    main()
