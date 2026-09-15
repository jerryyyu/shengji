"""Decision-identity gate for the served packages (#435 item 4).

The server plays from NumPy packages (`shengji.ai.cwv_numpy`,
`shengji.ai.cwv_prior_numpy`); every screen that produced the evidence played
from the Torch checkpoints. This gate plays the SAME decisions from both and
refuses unless every one of them is identical: the chosen action, the bot's
RNG state after the decision, the shortlist and its means, and (when a prior is
bound) the admission trace. A package that passes here serves the recipe the
evidence describes; one that does not must not be deployed.

    python scripts/cwv_serving_gate.py --value-torch m1.pt --value-numpy m1.npz \
        [--prior-torch prior.pt --prior-numpy prior.npz] [--rounds 8] \
        [--threshold 10000 --top 256] [--receipt gate.json]

Exit status 0 only when the gate PASSES: every decision identical AND, with a
prior bound, the prior actually fired at least once (a run in which it never
triggers is "incomplete-prior-never-fired", not a pass). The receipt records
every file's SHA256, the recipe, the counts and the SCOPE: only ``--serving``
(W32/N30, threshold 10000, top 256, prior bound) yields ``qualifies_serving``;
any other recipe is a smoke run of the same code paths and is labelled so.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

SCHEMA = "cwv-serving-gate-v1"

#: The SERVING recipe (fly.toml / `cwv_shortlist` defaults): the only scope whose PASS
#: qualifies a package for deployment. Anything else is a smoke run and says so.
SERVING_RECIPE = {"worlds": 32, "selection_worlds": 30, "alternatives": 4, "batch_size": 128,
                  "threshold": 10_000, "top": 256}


def file_sha256(path) -> str:
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _bot(value_ckpt, prior_ckpt, *, seed, worlds, selection_worlds, threshold, top):
    from shengji.ai.cwv_policy import shared_evaluator
    from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig

    evaluator = shared_evaluator(str(value_ckpt), threads=1, max_batch=128, encoding="mlp-static")
    config = CWVShortlistConfig(worlds=int(worlds), selection_worlds=int(selection_worlds),
                                alternatives=SERVING_RECIPE["alternatives"], batch_size=SERVING_RECIPE["batch_size"])
    if prior_ckpt is None:
        return CWVShortlistBot(evaluator, seed=seed, config=config, reuse_successors=True)
    from shengji.train.cwv_prior_admission import CWVPriorAdmissionBot, CWVPriorAdmissionConfig
    prior = CWVPriorAdmissionConfig(checkpoint=str(prior_ckpt), checkpoint_sha256=file_sha256(prior_ckpt),
                                    threshold=int(threshold), top=int(top))
    return CWVPriorAdmissionBot(evaluator, seed=seed, config=config, prior=prior, reuse_successors=True)


def _deal(rnd_seed):
    """A finished-deal round driven by the heuristic bot, ready for play."""
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.game import Game

    game = Game(random.Random(rnd_seed)); rnd = game.start_round(); h = HeuristicBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next(); c = h.decide_declare(rnd, seat)
        if c: rnd.declare(seat, c)
    for seat in range(4):
        c = h.decide_declare(rnd, seat, final=True)
        if c: rnd.declare(seat, c)
    rnd.finalize_declare(); rnd.bury(rnd.banker, h.decide_bury(rnd, rnd.banker))
    return rnd, h


def _trace(bot):
    detail = bot.last_shortlist or {}
    admission = detail.get("prior_admission")
    if admission is not None:
        # The recipe block names the prior FILE (path and SHA differ between the package and the
        # checkpoint by construction); everything else in the trace must agree exactly.
        admission = {k: v for k, v in admission.items()
                     if k not in ("prior_seconds", "prior_kind", "recipe", "prior_checkpoint_sha256")}
    return {"shortlist": [sorted(a) for a in detail.get("shortlist") or []],
            "means": [float(m) for m in detail.get("shortlist_means") or []],
            "admission": admission}


def _same(a, b) -> bool:
    if a["shortlist"] != b["shortlist"] or a["admission"] != b["admission"]:
        return False
    if len(a["means"]) != len(b["means"]):
        return False
    return bool(np.allclose(a["means"], b["means"], rtol=1e-4, atol=1e-5))


def run_gate(value_torch, value_numpy, prior_torch=None, prior_numpy=None, *, rounds=4,
             threshold=10_000, top=256, worlds=4, selection_worlds=4, seed=13, deal_seed=3000) -> dict:
    if (prior_torch is None) != (prior_numpy is None):
        raise ValueError("bind both prior files or neither")
    if not str(value_numpy).lower().endswith(".npz") or (prior_numpy is not None
                                                          and not str(prior_numpy).lower().endswith(".npz")):
        raise ValueError("the served side must be NumPy packages (.npz)")
    files = {"value_torch": value_torch, "value_numpy": value_numpy}
    if prior_torch is not None:
        files.update(prior_torch=prior_torch, prior_numpy=prior_numpy)
    recipe = {"worlds": int(worlds), "selection_worlds": int(selection_worlds),
              "alternatives": SERVING_RECIPE["alternatives"], "batch_size": SERVING_RECIPE["batch_size"],
              "threshold": int(threshold), "top": int(top)}
    serving = prior_torch is not None and recipe == SERVING_RECIPE
    receipt = {"schema": SCHEMA, "files": {k: {"path": str(v), "sha256": file_sha256(v)} for k, v in files.items()},
               "recipe": {**recipe, "rounds": int(rounds), "seed": int(seed), "deal_seed": int(deal_seed),
                          "prior_bound": prior_torch is not None},
               # What a PASS here may be cited for. Only the serving recipe with the prior bound
               # qualifies a deployment; every other run is a smoke test of the same code paths.
               "scope": "serving-w32-n30-prior" if serving else "smoke",
               "decisions": 0, "identical": 0, "prior_fired": 0, "first_mismatch": None, "result": None}
    kw = dict(seed=seed, worlds=worlds, selection_worlds=selection_worlds, threshold=threshold, top=top)
    served = _bot(value_numpy, prior_numpy, **kw)
    reference = _bot(value_torch, prior_torch, **kw)
    receipt["kinds"] = {"served_prior": getattr(served, "_prior_kind", None),
                        "reference_prior": getattr(reference, "_prior_kind", None)}
    if prior_numpy is not None and receipt["kinds"]["served_prior"] != "separate-numpy":
        raise ValueError("the served prior did not load as the NumPy package")
    t0 = time.perf_counter()
    for r in range(int(rounds)):
        rnd, h = _deal(deal_seed + r)
        while rnd.phase == "play":
            seat = rnd.turn
            if seat % 2 == 0:
                a = served.decide_play(copy.deepcopy(rnd), seat)
                b = reference.decide_play(copy.deepcopy(rnd), seat)
                ta, tb = _trace(served), _trace(reference)
                receipt["decisions"] += 1
                receipt["prior_fired"] += ta["admission"] is not None
                ok = sorted(a) == sorted(b) and served.rng.getstate() == reference.rng.getstate() and _same(ta, tb)
                receipt["identical"] += ok
                if not ok and receipt["first_mismatch"] is None:
                    receipt["first_mismatch"] = {"round": r, "decision": receipt["decisions"], "seat": seat,
                                                 "served": sorted(a), "reference": sorted(b),
                                                 "served_shortlist": ta["shortlist"], "reference_shortlist": tb["shortlist"]}
                rnd.play(seat, b)
            else:
                rnd.play(seat, h.decide_play(rnd, seat))
    receipt["seconds"] = round(time.perf_counter() - t0, 1)
    identical = receipt["decisions"] > 0 and receipt["identical"] == receipt["decisions"]
    if not identical:
        receipt["result"] = "mismatch" if receipt["decisions"] else "no-decisions"
    elif prior_torch is not None and receipt["prior_fired"] == 0:
        # Every decision agreed, but the prior never ran: the combined path is NOT certified.
        receipt["result"] = "incomplete-prior-never-fired"
    else:
        receipt["result"] = "identical"
    receipt["passed"] = receipt["result"] == "identical"
    receipt["qualifies_serving"] = bool(receipt["passed"] and serving)
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--value-torch", required=True)
    parser.add_argument("--value-numpy", required=True)
    parser.add_argument("--prior-torch")
    parser.add_argument("--prior-numpy")
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--threshold", type=int, default=10_000)
    parser.add_argument("--top", type=int, default=256)
    parser.add_argument("--worlds", type=int, default=4)
    parser.add_argument("--selection-worlds", type=int, default=4)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--serving", action="store_true",
                        help="use the serving recipe (W32/N30, threshold 10000, top 256): the only scope whose PASS qualifies a deploy")
    args = parser.parse_args(argv)
    if args.serving:
        args.worlds, args.selection_worlds = SERVING_RECIPE["worlds"], SERVING_RECIPE["selection_worlds"]
        args.threshold, args.top = SERVING_RECIPE["threshold"], SERVING_RECIPE["top"]
    receipt = run_gate(args.value_torch, args.value_numpy, args.prior_torch, args.prior_numpy,
                       rounds=args.rounds, threshold=args.threshold, top=args.top,
                       worlds=args.worlds, selection_worlds=args.selection_worlds)
    if args.receipt:
        args.receipt.write_text(json.dumps(receipt, indent=1, sort_keys=True))
    print(f"{'PASS' if receipt['passed'] else 'FAIL'} ({receipt['result']}, scope {receipt['scope']}"
          f"{', qualifies serving' if receipt['qualifies_serving'] else ''}): decisions {receipt['decisions']} "
          f"identical {receipt['identical']} prior fired {receipt['prior_fired']} secs {receipt['seconds']}")
    if receipt["first_mismatch"]:
        print("first mismatch:", json.dumps(receipt["first_mismatch"]))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
