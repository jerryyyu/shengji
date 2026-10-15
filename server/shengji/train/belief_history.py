"""Ordered play history for the belief-label extract (S17, history-input belief).

``belief_labels`` rows summarise the public state (who played which cards, voids,
caps) but not the ORDER of play: which seat led what, who followed with what,
who was winning when a point card was fed.  This module adds that order without
re-running the sampler: for every chunk ``<split>-<name>.npz`` of an extract dir
it replays the chunk's clusters from the trajectory store (the same
``game_order`` and engine replay ``belief_labels.iter_decisions`` uses) and writes
``hist/<split>-<name>.npz`` holding

* one token sequence per round (up to 100 plays), in ABSOLUTE seats -- the
  consumer rotates them into the actor's frame;
* per row, the round it belongs to and its ply (plays made before the decision),
  so the row's history is ``tokens[round, :ply]`` -- exactly the plays the actor
  has seen, never the one it is about to make or any later one;
* per round, the trump-relative card identity table (``card_features``) and the
  banker seat.

Each token is public: the seat, its position in the trick, the trick index, the
effective suit led, the cards the engine accepted, the cards of a refused throw
(``failed_throw`` notice, public), and derived public facts -- cards of the led
suit, all-trump, whether the play took the lead of the trick, who was winning
before it (partner / opponent of the player), points in the play and in the
trick so far.  Nothing reads a hidden hand.

Alignment is asserted row by row: the replayed trick number and the three other
hand sizes must equal the row's ``trick`` and ``sizes``, and the ply's seat is
the actor (its rows' ``role`` must match the replay's).

CLI: ``python -m shengji.train.belief_history extract --data DIR [DIR ...] --stores-root R``.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..engine.cards import SUITS, TRUMP, is_joker, card_rank, points
from ..harvest.rebuild import round_from_setup
from ..rl.encode import CARD_INDEX, N_CARDS
from .belief_labels import (BeliefLabelError, _played_cards, _read_records, cluster_paths,
                            game_order, role_of)

SCHEMA = "shengji-belief-history-v1"
MAX_PLAYS = 100
EFF = tuple(SUITS) + (TRUMP,)
#: integer columns of a token: absolute seat, position in trick, trick index, led eff suit
TOKEN_INT = ("seat", "pos", "trick", "lead_eff")
#: float columns of a token
TOKEN_FLOAT = ("n_cards", "frac_lead_suit", "all_trump", "short_of_lead", "takes_lead",
               "winner_partner", "winner_opponent", "play_points", "trick_points_before",
               "failed_throw")
N_TOKEN_FLOAT = len(TOKEN_FLOAT)
#: per-round, per-card identity under the round's trump
CARD_FEATURES = ("is_trump", "eff_S", "eff_H", "eff_D", "eff_C", "eff_T", "level", "points",
                 "is_joker", "is_rank_card", "is_trump_suit_rank")
N_CARD_FEATURES = len(CARD_FEATURES)
_CODES = sorted(CARD_INDEX, key=CARD_INDEX.get)


def card_features(ordering) -> np.ndarray:
    """``(54, N_CARD_FEATURES)``: each card code's role under this round's trump."""
    out = np.zeros((N_CARDS, N_CARD_FEATURES), np.float32)
    for i, code in enumerate(_CODES):
        eff = ordering.eff_suit(code)
        rank = card_rank(code)
        out[i, 0] = eff == TRUMP
        out[i, 1 + EFF.index(eff)] = 1.0
        out[i, 6] = ordering.level(code) / 16.0
        out[i, 7] = points(code) / 10.0
        out[i, 8] = is_joker(code)
        out[i, 9] = (not is_joker(code)) and rank == ordering.trump_rank
        out[i, 10] = out[i, 9] and code[0] == ordering.trump_suit
    return out


def _counts_u8(cards: Sequence[str]) -> np.ndarray:
    out = np.zeros(N_CARDS, np.uint8)
    for c in cards:
        out[CARD_INDEX[c]] += 1
    return out


def _winner_so_far(trick, ordering) -> int | None:
    """The seat currently taking ``trick`` (``Round._resolve_trick``'s loop over the
    plays made so far)."""
    from ..engine.combos import decompose
    from ..engine.legal import beats, uniform_suit
    if not trick.plays:
        return None
    lead = trick.plays[0].cards
    inc_suit = uniform_suit(lead, ordering)
    if inc_suit is None:
        return trick.plays[0].seat
    inc_top = decompose(lead, ordering).top_level()
    winner = trick.plays[0].seat
    for tp in trick.plays[1:]:
        won, top = beats(tp.cards, lead, inc_suit, inc_top, ordering)
        if won:
            winner, inc_top = tp.seat, top
            inc_suit = ordering.eff_suit(tp.cards[0])
    return winner


def replay_round_tokens(records: Sequence[Mapping[str, Any]]):
    """Replay one cluster's play records (``game_order``) and yield, per round,
    ``(round_index, tokens, card_feat, banker, decisions)`` where ``decisions`` is a
    list of ``(decision_index, ply, seat, trick, other_sizes, role)``."""
    stream = game_order(records)
    rnd = None
    round_index = -1
    decision_index = 0
    cur = None

    def finish():
        if cur is not None:
            return (cur["round_index"], cur["tok"], cur["card_feat"], cur["banker"], cur["dec"])
        return None

    for rec in stream:
        prefix = rec.get("plays_prefix") or []
        if not prefix:
            done = finish()
            if done is not None:
                yield done
            rnd = round_from_setup(rec["deck"], rec["setup"])
            round_index += 1
            cur = {"round_index": round_index, "tok": [], "dec": [],
                   "card_feat": card_features(rnd.ordering), "banker": int(rnd.banker)}
        elif rnd is None or len(prefix) != len(cur["tok"]):
            raise BeliefLabelError("records are not one ordered game")
        seat = int(rec["seat"])
        if rnd.phase != "play" or rnd.turn != seat:
            raise BeliefLabelError("the record's seat is not the replay's turn")
        ply = len(cur["tok"])
        trick_no = len(rnd.history) + 1
        cur["dec"].append((decision_index, ply, seat, trick_no,
                           tuple(len(rnd.hands[(seat + r) % 4]) for r in (1, 2, 3)),
                           role_of(rnd, seat)))
        decision_index += 1
        o = rnd.ordering
        pos = len(rnd.trick.plays)
        lead_eff = o.eff_suit(rnd.trick.plays[0].cards[0]) if pos else None
        prev_winner = _winner_so_far(rnd.trick, o) if pos else None
        trick_points_before = sum(points(c) for tp in rnd.trick.plays for c in tp.cards)
        before = len(rnd.history)
        attempted = list(rec["action"])
        rnd.play(seat, attempted)
        played = _played_cards(rnd, before)
        expected = rec.get("engine_play") or rec["action"]
        if Counter(played) != Counter(expected):
            raise BeliefLabelError("the engine's play differs from the record's engine_play")
        trick = rnd.history[-1] if len(rnd.history) > before else rnd.trick
        if lead_eff is None:
            lead_eff = o.eff_suit(played[0])
        n_lead = sum(o.eff_suit(c) == lead_eff for c in played)
        failed = Counter(played) != Counter(attempted)
        # who takes the trick once this play is on it
        partial = type(trick)(leader=trick.leader, plays=list(trick.plays[:pos + 1]))
        now_winner = _winner_so_far(partial, o)
        f = np.zeros(N_TOKEN_FLOAT, np.float32)
        f[0] = len(played) / 8.0
        f[1] = n_lead / len(played)
        f[2] = all(o.eff_suit(c) == TRUMP for c in played)
        f[3] = pos > 0 and n_lead < len(played)          # could not follow: a public void
        f[4] = pos > 0 and now_winner == seat
        if prev_winner is not None:
            f[5] = (prev_winner - seat) % 4 == 2
            f[6] = (prev_winner - seat) % 2 == 1
        f[7] = sum(points(c) for c in played) / 25.0
        f[8] = trick_points_before / 50.0
        f[9] = failed
        cur["tok"].append({
            "int": (seat, pos, trick_no - 1, EFF.index(lead_eff)),
            "f": f,
            "cards": _counts_u8(played),
            "att": _counts_u8(attempted) if failed else np.zeros(N_CARDS, np.uint8),
        })
    done = finish()
    if done is not None:
        yield done


def chunk_history(chunk_path: str, shard_paths: Sequence[str]) -> dict[str, np.ndarray]:
    """History arrays for one extract chunk, aligned to its rows (asserted)."""
    with np.load(chunk_path) as z:
        cl = z["cluster"].astype(np.int64)
        ri = z["round_index"].astype(np.int64)
        dec = z["decision"].astype(np.int64)
        trick = z["trick"].astype(np.int64)
        sizes = z["sizes"].astype(np.int64)
        role = z["role"].astype(np.int64)
    n = len(cl)
    row_round = np.full(n, -1, np.int32)
    row_ply = np.full(n, -1, np.int16)
    row_seat = np.full(n, -1, np.int8)
    rounds_int, rounds_f, rounds_cards, rounds_att, rounds_n, rounds_cf, rounds_banker = \
        [], [], [], [], [], [], []
    for c in dict.fromkeys(cl.tolist()):
        rows = np.flatnonzero(cl == c)
        by_dec = {int(dec[i]): int(i) for i in rows}
        recs = [r for r in _read_records(Path(shard_paths[c])) if r.get("decision_kind") == "play"]
        matched = 0
        for r_index, toks, cf, banker, decisions in replay_round_tokens(recs):
            rid = len(rounds_n)
            T = len(toks)
            if T > MAX_PLAYS:
                raise BeliefLabelError(f"round with {T} plays")
            ti = np.zeros((MAX_PLAYS, len(TOKEN_INT)), np.int8)
            tf = np.zeros((MAX_PLAYS, N_TOKEN_FLOAT), np.float16)
            tc = np.zeros((MAX_PLAYS, N_CARDS), np.uint8)
            ta = np.zeros((MAX_PLAYS, N_CARDS), np.uint8)
            for t, tok in enumerate(toks):
                ti[t] = tok["int"]
                tf[t] = tok["f"]
                tc[t] = tok["cards"]
                ta[t] = tok["att"]
            rounds_int.append(ti)
            rounds_f.append(tf)
            rounds_cards.append(tc)
            rounds_att.append(ta)
            rounds_n.append(T)
            rounds_cf.append(cf.astype(np.float16))
            rounds_banker.append(banker)
            for d_index, ply, seat, trick_no, other, rl in decisions:
                i = by_dec.get(d_index)
                if i is None:
                    continue
                if ri[i] != r_index:
                    raise BeliefLabelError(f"{chunk_path}: row round {ri[i]} != replay {r_index}")
                if trick[i] != trick_no:
                    raise BeliefLabelError(f"{chunk_path}: row trick {trick[i]} != replay {trick_no}")
                if tuple(sizes[i, :3]) != tuple(other):
                    raise BeliefLabelError(f"{chunk_path}: row hand sizes differ from the replay")
                if role[i] != rl:
                    raise BeliefLabelError(f"{chunk_path}: row role differs from the replay")
                row_round[i] = rid
                row_ply[i] = ply
                row_seat[i] = seat
                matched += 1
        if matched != len(rows):
            raise BeliefLabelError(f"{chunk_path}: cluster {c}: {matched} of {len(rows)} rows matched")
    if np.any(row_round < 0):
        raise BeliefLabelError(f"{chunk_path}: unmatched rows")
    return {"row_round": row_round, "row_ply": row_ply, "row_seat": row_seat,
            "tok_int": np.stack(rounds_int), "tok_f": np.stack(rounds_f),
            "tok_cards": np.stack(rounds_cards), "tok_att": np.stack(rounds_att),
            "round_n": np.asarray(rounds_n, np.int16), "card_feat": np.stack(rounds_cf),
            "banker": np.asarray(rounds_banker, np.int8)}


def _chunk_task(args) -> dict:
    chunk_path, out_path, shard_paths = args
    t0 = time.time()
    if Path(out_path).exists():
        b = Path(out_path).read_bytes()
        return {"chunk": chunk_path, "out": out_path, "skipped": True,
                "sha256": hashlib.sha256(b).hexdigest(), "seconds": 0.0}
    arrays = chunk_history(chunk_path, shard_paths)
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    b = buf.getvalue()
    tmp = out_path + ".tmp"
    Path(tmp).write_bytes(b)
    os.replace(tmp, out_path)
    return {"chunk": chunk_path, "out": out_path, "skipped": False, "rows": int(len(arrays["row_ply"])),
            "rounds": int(len(arrays["round_n"])), "sha256": hashlib.sha256(b).hexdigest(),
            "seconds": time.time() - t0}


def extract(dirs: Sequence[str], stores_root: str, *, workers: int, log=print) -> dict:
    """``hist/`` next to every chunk of every extract dir (resumable: a finished
    chunk file is kept); writes ``hist/manifest.json`` per dir."""
    out: dict[str, Any] = {}
    for d in dirs:
        man = json.loads((Path(d) / "manifest.json").read_text())
        stores = man["stores"]
        if len(stores) != 1:
            raise BeliefLabelError("one store per extract dir expected")
        store = Path(stores_root) / Path(stores[0]).name
        shards = [str(p) for p in cluster_paths(store)]
        hist = Path(d) / "hist"
        hist.mkdir(exist_ok=True)
        tasks = []
        for chunk in man["chunks"]:
            for split, entry in chunk["files"].items():
                tasks.append((str(Path(d) / entry["file"]), str(hist / entry["file"]), shards))
        t0 = time.time()
        results = []
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for i, res in enumerate(pool.map(_chunk_task, tasks)):
                results.append(res)
                if (i + 1) % 50 == 0 or i + 1 == len(tasks):
                    log(f"[hist] {Path(d).name}: {i + 1}/{len(tasks)} chunks, {time.time() - t0:.0f}s",
                        flush=True)
        hm = {"schema": SCHEMA, "source_extract_manifest_sha256":
              hashlib.sha256((Path(d) / "manifest.json").read_bytes()).hexdigest(),
              "store": str(store), "max_plays": MAX_PLAYS, "token_int": TOKEN_INT,
              "token_float": TOKEN_FLOAT, "card_features": CARD_FEATURES,
              "files": {Path(r["out"]).name: r["sha256"] for r in results},
              "rows": sum(r.get("rows", 0) for r in results),
              "rounds": sum(r.get("rounds", 0) for r in results)}
        (hist / "manifest.json").write_text(json.dumps(hm, indent=1, default=list))
        out[d] = {"chunks": len(results), "rows": hm["rows"], "rounds": hm["rounds"],
                  "seconds": time.time() - t0}
        log(json.dumps({Path(d).name: out[d]}), flush=True)
    return out


def audit(dirs: Sequence[str], out_json: str, log=print) -> dict:
    """Receipt for a set of extract dirs: per dir the store, cluster stride/offset,
    rows and deals per split, and the history manifest; plus the leakage check --
    no deal key (hash) is in two splits across ALL dirs (the split is the salted
    deal-key hash, so the same deal is in the same split in every extract)."""
    import numpy as np
    by_split: dict[str, set] = {"train": set(), "calib": set(), "test": set()}
    per_dir = []
    for d in dirs:
        man = json.loads((Path(d) / "manifest.json").read_text())
        hman = json.loads((Path(d) / "hist" / "manifest.json").read_text())
        rows = Counter()
        sampler_rows = Counter()
        deals: dict[str, set] = {k: set() for k in by_split}
        for c in man["chunks"]:
            for split, e in c["files"].items():
                with np.load(Path(d) / e["file"]) as z:
                    deal = z["deal"]
                    s_n = z["S_n"]
                rows[split] += len(deal)
                sampler_rows[split] += int((s_n > 0).sum())
                deals[split].update(np.unique(deal).tolist())
        for k in by_split:
            by_split[k] |= deals[k]
        per_dir.append({"dir": d, "store": man["stores"][0], "cluster_stride": man["cluster_stride"],
                        "cluster_offset": man.get("cluster_offset"), "split": man["split"],
                        "sampler": man["sampler"], "rows": dict(rows),
                        "sampler_rows": dict(sampler_rows),
                        "deals": {k: len(v) for k, v in deals.items()},
                        "failed_clusters": len(man.get("failed_clusters", [])),
                        "excluded_clusters": len(man.get("excluded_clusters", [])),
                        "manifest_sha256": hashlib.sha256((Path(d) / "manifest.json").read_bytes()
                                                          ).hexdigest(),
                        "hist_manifest_sha256": hashlib.sha256(
                            (Path(d) / "hist" / "manifest.json").read_bytes()).hexdigest(),
                        "hist_rows": hman["rows"]})
        log(json.dumps({Path(d).name: per_dir[-1]["rows"]}), flush=True)
    salts = {json.dumps(p["split"], sort_keys=True) for p in per_dir}
    overlap = {f"{a}&{b}": len(by_split[a] & by_split[b])
               for a, b in (("train", "calib"), ("train", "test"), ("calib", "test"))}
    out = {"schema": "s17-belief-corpus-receipt-v1", "dirs": per_dir, "split_configs": sorted(salts),
           "deals": {k: len(v) for k, v in by_split.items()}, "deal_overlap": overlap,
           "rows": {k: sum(p["rows"].get(k, 0) for p in per_dir) for k in by_split},
           "leakage_free": len(salts) == 1 and not any(overlap.values())}
    Path(out_json).write_text(json.dumps(out, indent=1, default=list))
    if not out["leakage_free"]:
        raise BeliefLabelError(f"split leakage or mixed split configs: {overlap} {salts}")
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="belief_history", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract", help="add ordered play history to belief-label extract dirs")
    ex.add_argument("--data", nargs="+", required=True)
    ex.add_argument("--stores-root", required=True)
    ex.add_argument("--workers", type=int, default=12)
    au = sub.add_parser("audit", help="corpus receipt + cross-split deal leakage check")
    au.add_argument("--data", nargs="+", required=True)
    au.add_argument("--out-json", required=True)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "extract":
        extract(args.data, args.stores_root, workers=args.workers)
        return 0
    if args.command == "audit":
        r = audit(args.data, args.out_json)
        print(json.dumps({k: r[k] for k in ("rows", "deals", "deal_overlap", "leakage_free")}))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
