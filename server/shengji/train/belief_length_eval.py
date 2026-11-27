"""Paired, empirical void coverage for the plain and joint-length proposals."""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import re
from time import perf_counter

import numpy as np

from ..ai.belief_numpy import load_belief_numpy
from . import belief_seq as bs
from .belief_eval import known_counts
from .belief_labels import stored_deal_id
from .belief_length_loss import MarginalLoss
from .belief_lengths import load_length_checkpoint


class VoidCounts:
    def __init__(self):
        self.bins = np.zeros((10, 3), dtype=np.float64)
        self.missed = 0

    def add(self, probability, truth):
        index = min(int(probability * 10), 9)
        self.bins[index] += [1, probability, truth]
        self.missed += int(truth and probability == 0)

    def report(self):
        pairs, _, voids = self.bins.sum(0)
        return {"candidate_pairs": int(pairs), "true_voids": int(voids),
                "missed_voids": self.missed,
                "miss_rate": self.missed / voids if voids else None,
                "sampled_void_ece": abs(self.bins[:, 1] - self.bins[:, 2]).sum() / pairs
                if pairs else None}


def decision(part, row):
    """Rebuild actor-visible inference inputs from a residualized extract row."""
    hist = part["_rounds"]
    r, ply = part["row_round"][row], part["row_ply"][row]
    raw = part["X"][row:row + 1].astype(np.float32)
    planes = bs.row_card_planes(raw)[0]
    pins = known_counts(raw)[0]
    # The base unseen plane counts half copies and includes the actor's own kitty.
    copies = 2 * planes[:, 8] - planes[:, 9] - pins.sum(1)
    if (copies < 0).any() or not np.array_equal(copies, copies.astype(int)):
        raise ValueError("invalid public residual counts")
    sizes = part["sizes"][row]
    if copies.sum() != sizes.sum():
        raise ValueError("public residual counts disagree with hand sizes")
    inp = {k: hist[k][r, :ply] for k in ("tok_int", "tok_f", "tok_cards", "tok_att")}
    inp.update(X=np.r_[raw[0], sizes.astype(np.float32) / 25], row_card=planes,
               M=part["M"][row], n_c=copies.astype(int), sizes=sizes, K=pins,
               banker=int(hist["banker"][r]), seat=int(part["row_seat"][row]),
               card_feat=hist["card_feat"][r])
    return inp


def cohort_selection(path, extract, belief_sha256):
    """Expected test rows keyed by both recorded round seed and dealt deck."""
    cohort = json.loads(Path(path).read_bytes())
    if cohort.get("belief_sha256", belief_sha256) != belief_sha256:
        raise ValueError("cohort belongs to a different belief package")
    bound = cohort.get("source", {}).get("extract_manifest_sha256")
    if bound is not None and bound != hashlib.sha256((Path(extract) / "manifest.json").read_bytes()).hexdigest():
        raise ValueError("cohort belongs to a different extract manifest")
    items = cohort["deals"]
    if not isinstance(items, list) or not items:
        raise ValueError("empty or malformed evaluation cohort")
    expected, seeds, ids = {}, set(), set()
    for item in items:
        seed, deck, rows = item["seed"], item["deal_key"], item["rows"]
        if (type(seed) is not int or seed < 0 or type(rows) is not int or rows < 1
                or not isinstance(deck, str) or not re.fullmatch(r"deck:[0-9a-f]{64}", deck)):
            raise ValueError("invalid evaluation cohort member")
        deal = int(stored_deal_id(deck))
        if seed in seeds or deal in ids:
            raise ValueError("duplicate seed or deal in evaluation cohort")
        expected[seed, deal] = rows
        seeds.add(seed)
        ids.add(deal)
    return expected, seeds, ids


def evaluate(extract, head, training, belief, seed, worlds=64, *, ll_max_draws=None, ll_replicates=4, cohort=None, timing_only=False):
    if timing_only and (cohort is None or ll_max_draws is None):
        raise ValueError("timing requires a bounded cohort and a log-loss draw limit")
    started = perf_counter() if timing_only else None
    loss_seconds = 0.
    entries = bs.extract_entries([extract], "test", exclude_seed_windows=training["exclude_seed_window"])
    exposed = set(training["deals"])
    seen = set()
    stats = {arm: {role: VoidCounts() for role in ("banker", "other_seats", "kitty")}
             for arm in ("plain", "joint")}
    loss = MarginalLoss(ll_replicates, ll_max_draws) if ll_max_draws is not None else None
    verified = bs._Verified()
    selected = cohort_selection(cohort, extract, belief.package_sha256) if cohort is not None else None
    observed = defaultdict(set)
    decisions = 0
    for entry in entries:
        part = bs.load_part(entry, bs.ROW_KEYS + ("decision", "seed"), verified)
        deals = set(map(int, part["deal"]))
        if exposed & deals:
            raise ValueError("test deal in length-head training exposure")
        for row, truth in enumerate(part["Y"]):
            deal = int(part["deal"][row])
            if selected is not None:
                expected, seeds, ids = selected
                pair = (int(part["seed"][row]), deal)
                if pair not in expected:
                    if pair[0] in seeds or deal in ids:
                        raise ValueError("cohort seed and extracted deal disagree")
                    continue
                decision_id = int(part["decision"][row])
                if decision_id in observed[pair]:
                    raise ValueError("duplicate held-out decision in evaluation cohort")
                observed[pair].add(decision_id)
                if len(observed[pair]) > expected[pair]:
                    raise ValueError("extra rows for evaluation cohort")
            seen.add(deal)
            inp = decision(part, row)
            copies, mask, sizes = inp["n_c"], inp["M"], inp["sizes"]
            if not np.array_equal(truth.sum(1), copies) or not np.array_equal(truth.sum(0), sizes):
                raise ValueError("test labels disagree with public counts")
            decisions += 1
            suit = inp["card_feat"][:, 1:6].argmax(1)
            side = (suit[:, None] == np.arange(4)).astype(np.int64)
            possible = side.T @ mask > 0
            candidates = possible & (side.T @ inp["K"] == 0)
            score_loss = loss is not None and inp["seat"] != inp["banker"] and copies.any()
            if not candidates.any() and not score_loss:
                continue
            streams = np.random.SeedSequence([seed, int(part["deal"][row]), int(part["seed"][row]),
                                              int(part["decision"][row])]).spawn(3)
            q = bs.project_sizes(belief.marginals(inp), copies, sizes, mask)
            if score_loss:
                if timing_only:
                    loss_started = perf_counter()
                loss.add(inp, q, truth, head, streams[2])
                if timing_only:
                    loss_seconds += perf_counter() - loss_started
            if not candidates.any():
                continue
            baseline = bs.sample_worlds(q, copies, mask, sizes, worlds, np.random.default_rng(streams[0]))
            plain = np.einsum("cs,wcr->wsr", side, baseline)
            joint = head.draw_lengths(inp, mask, worlds, np.random.default_rng(streams[1]))
            actual = side.T @ truth
            banker_receiver = (inp["banker"] - inp["seat"]) % 4 - 1
            for s, r in zip(*np.nonzero(candidates)):
                role = "kitty" if r == 3 else "banker" if r == banker_receiver else "other_seats"
                for arm, table in (("plain", plain), ("joint", joint)):
                    stats[arm][role].add(np.mean(table[:, s, r] == 0), actual[s, r] == 0)
    if selected is not None and {pair: len(ids) for pair, ids in observed.items()} != selected[0]:
        raise ValueError("missing rows for evaluation cohort")
    if not decisions:
        raise ValueError("no held-out decisions")
    if timing_only:
        return {"decisions": decisions, "deals": len(seen), "worlds_per_void_arm": worlds,
                "evaluation_seconds": perf_counter() - started, "log_loss_seconds": loss_seconds,
                "scored_decisions": loss.decisions, "worlds_drawn": loss.draws,
                "maximum_worlds": loss.decisions * ll_replicates * ll_max_draws,
                "draw_limit_per_row_per_replicate": ll_max_draws, "replicates": ll_replicates,
                "unresolved_copy_observations": int(loss.unseen.sum())}
    return {"decisions": decisions, "deals": len(seen), "worlds": worlds, "seed": seed,
            "belief_sha256": belief.package_sha256,
            "nonbanker_marginal_log_loss": loss.report() if loss is not None else None,
            "arms": {arm: {role: count.report() for role, count in roles.items()}
                     for arm, roles in stats.items()}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", required=True)
    parser.add_argument("--length-checkpoint", required=True)
    parser.add_argument("--belief-package", required=True)
    parser.add_argument("--belief-sha256", required=True)
    parser.add_argument("--cohort", help="JSON file listing test deals by seed, deal_key and expected rows")
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--ll-max-draws", type=int, help="enable per-copy log-loss scoring with this trial limit")
    parser.add_argument("--ll-replicates", type=int, default=4)
    parser.add_argument("--timing-only", action="store_true",
                        help="measure bounded cohort evaluation and emit only timing and work counts")
    args = parser.parse_args(argv)
    if args.timing_only and (not args.cohort or args.ll_max_draws is None):
        parser.error("--timing-only requires --cohort and --ll-max-draws")
    head, training = load_length_checkpoint(args.length_checkpoint)
    belief = load_belief_numpy(args.belief_package, args.belief_sha256)
    print(json.dumps(evaluate(args.extract, head, training, belief, args.seed,
                              ll_max_draws=args.ll_max_draws, ll_replicates=args.ll_replicates, cohort=args.cohort,
                              timing_only=args.timing_only), allow_nan=False))


if __name__ == "__main__":
    main()
