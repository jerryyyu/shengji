"""Debug one logged belief-proposal decision.

Reads a decision recorded under ``SHENGJI_PV_BELIEF_LOG`` (`train.pv_search_policy`)
from a room log (``logs/<ROOM>.jsonl``: the ``decision`` of a bot ``play`` event)
or from a trajectory shard (``action_values.belief`` of a pv-search row), rebuilds
the decision state, and prints

* the logged summary and, per hidden card, the model's receiver marginals
  (dequantised from ``belief_snapshot``) beside the receiver that truly held each
  unknown copy (the deal is in the log), with the copy-mean probability and
  cross-entropy the model gave the truth;
* with ``--belief-package``, the regenerated proposal: the marginals recomputed
  (their largest difference from the snapshot, in 1/255 steps), and the worlds
  redrawn from ``belief_seed`` through the served history-legal loop, checked
  against the logged counts (``belief_proposed``, ``history_rejections``,
  ``history_fallback_worlds``).  Worlds filled by production's draw after the
  attempt cap come from the sampler stream, which is not logged: the tool says
  how many there were.

Usage (from ``server/``):
  uv run python scripts/belief_debug.py --log ../logs/ABCD.jsonl --list
  uv run python scripts/belief_debug.py --log ../logs/ABCD.jsonl --round 3 --ply 41 \
      --belief-package ~/Projects/shengji-wt/pkg/s17long-e2-763b5e05.npz
  uv run python scripts/belief_debug.py --shard cluster-000000.jsonl --line 17
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shengji.ai import belief_numpy as bn  # noqa: E402
from shengji.ai.refusal import Refusal  # noqa: E402

RECEIVERS = ("next", "partner", "prev", "kitty")
#: the probability floor for a quantised zero in the cross-entropy (half a step)
FLOOR = 0.5 / bn.SNAPSHOT_SCALE


class BeliefDebugError(ValueError):
    pass


def refusals_of(fields) -> list[Refusal]:
    return [Refusal(int(s), tuple(a), tuple(f), int(t))
            for s, a, f, t in fields.get("belief_refusals") or []]


# --------------------------------------------------------------- sources

def room_log_decisions(path):
    """Yield ``(round_no, ply, rnd_before, seat, decision)`` for every bot play
    event of the log whose decision carries a belief log, ``rnd_before`` the
    state the bot decided in (a fresh copy per decision)."""
    import copy
    from shengji.rl.replay_log import group_rounds, rebuild_round
    for round_no, events in sorted(group_rounds(str(path)).items()):
        rnd = rebuild_round(events)
        if rnd is None:
            continue
        ply = 0
        for e in events:
            if e["e"] != "play" or rnd.phase != "play":
                continue
            decision = e.get("decision") or {}
            if e.get("bot") and "belief_seed" in decision:
                yield round_no, ply, copy.deepcopy(rnd), int(e["seat"]), decision
            # a failed throw replays as attempted, so the engine posts its notice
            rnd.play(int(e["seat"]), list(e.get("attempted_cards") or e["cards"]))
            ply += 1


def room_log_decision(path, round_no: int, ply: int):
    for r, p, rnd, seat, decision in room_log_decisions(path):
        if r == round_no and p == ply:
            return rnd, seat, decision
    raise BeliefDebugError(f"no logged belief decision at round {round_no} ply {ply}")


def shard_decision(path, line: int):
    from shengji.harvest.rebuild import state_for_record
    with open(path) as fh:
        for i, raw in enumerate(fh):
            if i == line:
                record = json.loads(raw)
                break
        else:
            raise BeliefDebugError(f"{path} has no line {line}")
    av = record.get("action_values") or {}
    belief = dict(av.get("belief") or {})
    if "belief_seed" not in belief:
        raise BeliefDebugError("the row carries no belief log")
    belief.setdefault("worlds", av.get("worlds"))
    return state_for_record(record), int(record["seat"]), belief


# --------------------------------------------------------------- analysis

def truth_counts(rnd, seat: int, inp) -> np.ndarray:
    """(54, 4): per card, the UNKNOWN copies each receiver truly holds (the
    pinned copies ``K`` removed), from the deal the log carries."""
    from shengji.rl.encode import CARD_INDEX
    T = np.zeros((bn.N_CARDS, bn.N_RECV), np.int64)
    for rel in (1, 2, 3):
        for code in rnd.hands[(seat + rel) % 4]:
            T[CARD_INDEX[code], rel - 1] += 1
    if bool(np.asarray(inp["M"])[:, 3].any()) or int(inp["sizes"][3]) > 0:
        for code in rnd.buried or ():
            T[CARD_INDEX[code], 3] += 1
    U = T - np.asarray(inp["K"], np.int64)
    if (U < 0).any() or not np.array_equal(U.sum(-1), np.asarray(inp["n_c"])):
        raise BeliefDebugError("the deal does not match the decision's hidden copies")
    return U


def truth_report(P: np.ndarray, U: np.ndarray) -> dict:
    """The copy-mean probability the marginals gave the true receiver, the
    cross-entropy in bits, and the copies the model found least likely."""
    copies = int(U.sum())
    if copies == 0:
        return {"copies": 0}
    mass = float((U * P).sum() / copies)
    xent = float(-(U * np.log2(np.maximum(P, FLOOR))).sum() / copies)
    worst = sorted(((float(P[c, r]), c, r) for c, r in zip(*np.nonzero(U))))[:8]
    return {"copies": copies, "true_mass": round(mass, 4), "cross_entropy_bits": round(xent, 4),
            "worst": worst}


def regenerate(model, rnd, seat: int, fields, worlds: int):
    """The proposal rebuilt from the logged seed and its worlds redrawn through
    the served loop; returns ``(proposal, worlds, stats, fill)``."""
    from shengji.ai.history_legality import draw_constraints, sample_worlds_history_legal
    from shengji.ai.mcbot import MCBot
    from shengji.ai.memory import Memory
    if "belief_deadline_fired" in fields:
        raise BeliefDebugError(
            "deadline-enabled belief replay is unsupported: the record lacks "
            "a deterministic stop-attempt boundary; regenerated worlds would "
            "not establish this decision's sample")
    refusals = refusals_of(fields)
    sampler = MCBot(seed=0)
    propose = bn.BeliefProposal(model, rnd, seat, refusals, seed=int(fields["belief_seed"]),
                                batch=worlds, forbidden=draw_constraints(rnd, seat))
    mem = Memory(rnd, seat, own_kitty=getattr(sampler, "BANKER_KITTY", True))
    drawn, _attempts, stats = sample_worlds_history_legal(
        sampler, rnd, seat, worlds, refusals, mem=mem, propose=propose, constrain=True)
    return propose, drawn, stats, worlds - accepted_from_proposal(propose, stats)


def accepted_from_proposal(propose, stats) -> int:
    """The worlds the proposal supplied: every proposal draw is either rejected
    (refusal or history test) or accepted; the rest were filled by production's
    draw from the sampler stream."""
    return (int(propose.drawn) - int(stats.get("history_rejections", 0))
            - int(stats.get("refusal_rejections", 0)))


#: the logged counters a replay must reproduce; a counter the source did not
#: log is reported as None (never compared with a default)
REPLAY_CHECKS = ("belief_proposed", "history_rejections", "history_fallback_worlds")


def replay_checks(fields, propose, stats) -> dict:
    """Per logged counter: does the replay reproduce it (None: not logged)."""
    got = {"belief_proposed": int(propose.drawn),
           "history_rejections": stats.get("history_rejections"),
           "history_fallback_worlds": stats.get("history_fallback_worlds")}
    return {k: (None if k not in fields else got[k] == fields[k]) for k in REPLAY_CHECKS}


def world_truth_agreement(drawn, rnd, seat: int) -> list[float]:
    """Per world, the fraction of the other seats' cards placed with their true holder."""
    from collections import Counter
    total = sum(len(rnd.hands[s]) for s in range(4) if s != seat)
    out = []
    for hands, _buried in drawn:
        hit = sum(sum((Counter(hands[s]) & Counter(rnd.hands[s])).values())
                  for s in range(4) if s != seat)
        out.append(hit / total if total else 1.0)
    return out


# --------------------------------------------------------------- printing

def _code(i: int) -> str:
    return bn._codes()[i]


def report(rnd, seat: int, fields, *, model=None, out=None) -> dict:
    out = sys.stdout if out is None else out
    inp = bn.decision_inputs(rnd, seat, refusals_of(fields))
    P = bn.decode_snapshot(fields["belief_snapshot"])
    U = truth_counts(rnd, seat, inp)
    truth = truth_report(P, U)
    print(f"seat {seat}  trick {len(rnd.history)}  seed {fields['belief_seed']}", file=out)
    print("logged: " + ", ".join(f"{k}={fields.get(k)}" for k in (
        "belief_fallback", "belief_proposed", "belief_ms", "belief_entropy_bits",
        "belief_top_mass", "belief_hidden_copies", "history_rejections",
        "history_fallback_worlds")), file=out)
    print(f"truth: {truth.get('copies')} unknown copies, mean p(true receiver) "
          f"{truth.get('true_mass')}, cross-entropy {truth.get('cross_entropy_bits')} bits",
          file=out)
    print(f"{'card':>5} {'n':>2} " + " ".join(f"{r:>7}" for r in RECEIVERS) + "  truth", file=out)
    for c in np.flatnonzero(P.sum(-1) > 0):
        held = ",".join(f"{RECEIVERS[r]}x{U[c, r]}" for r in range(4) if U[c, r])
        print(f"{_code(c):>5} {int(inp['n_c'][c]):>2} "
              + " ".join(f"{P[c, r]:7.3f}" for r in range(4)) + f"  {held}", file=out)
    if truth.get("worst"):
        print("least likely truths: " + ", ".join(
            f"{_code(c)}@{RECEIVERS[r]} p={p:.3f}" for p, c, r in truth["worst"]), file=out)
    result = {"truth": truth}
    if model is not None:
        worlds = int(fields.get("worlds") or 64)
        propose, drawn, stats, fill = regenerate(model, rnd, seat, fields, worlds)
        diff = int(np.abs(np.rint(np.asarray(propose.P) * bn.SNAPSHOT_SCALE)
                          - np.rint(P * bn.SNAPSHOT_SCALE)).max())
        checks = replay_checks(fields, propose, stats)
        agree = world_truth_agreement(drawn, rnd, seat)
        print(f"regenerated: snapshot max diff {diff}/255; {len(drawn)} worlds, "
              f"{fill} filled from the unlogged sampler stream; counts match (None = not logged): "
              f"{checks}", file=out)
        print(f"worlds vs truth: placed-correctly fraction mean {np.mean(agree):.3f} "
              f"min {min(agree):.3f} max {max(agree):.3f}", file=out)
        result.update(snapshot_diff=diff, fill=fill, checks=checks, worlds=drawn,
                      agreement=agree)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--log", help="a room log (logs/<ROOM>.jsonl)")
    src.add_argument("--shard", help="a trajectory shard (JSONL)")
    ap.add_argument("--round", type=int, help="room log: the round number")
    ap.add_argument("--ply", type=int, help="room log: the play's index within the round (0-based)")
    ap.add_argument("--line", type=int, help="shard: the row's line (0-based)")
    ap.add_argument("--list", action="store_true", help="room log: list the logged belief decisions")
    ap.add_argument("--belief-package", help="the belief package, to regenerate the worlds")
    ap.add_argument("--belief-sha256", help="its sha256 (checked when given)")
    args = ap.parse_args(argv)
    if args.list:
        if not args.log:
            ap.error("--list reads a room log")
        for round_no, ply, rnd, seat, d in room_log_decisions(args.log):
            inp = bn.decision_inputs(rnd, seat, refusals_of(d))
            truth = truth_report(bn.decode_snapshot(d["belief_snapshot"]),
                                 truth_counts(rnd, seat, inp)) if "belief_snapshot" in d else {}
            print(f"round {round_no} ply {ply} seat {seat} entropy {d.get('belief_entropy_bits')} "
                  f"p(truth) {truth.get('true_mass')} xent {truth.get('cross_entropy_bits')}")
        return 0
    if args.log:
        if args.round is None or args.ply is None:
            ap.error("--log needs --round and --ply (or --list)")
        rnd, seat, fields = room_log_decision(args.log, args.round, args.ply)
    else:
        if args.line is None:
            ap.error("--shard needs --line")
        rnd, seat, fields = shard_decision(args.shard, args.line)
    if "belief_snapshot" not in fields:
        raise BeliefDebugError("the decision fell back: no snapshot (seed "
                               f"{fields.get('belief_seed')}, error {fields.get('belief_error')})")
    model = None
    if args.belief_package:
        model = bn.load_belief_numpy(args.belief_package, args.belief_sha256)
    report(rnd, seat, fields, model=model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
