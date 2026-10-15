"""S23: declaration and bury-rule inputs for the S17 belief model (offline, tier-i DEV).

The S17 row (``belief_labels.belief_features``) already carries the FINAL
declaration (declarer relative to the actor, its cards, pinned to the declarer
by ``Memory``), the banker and the trump.  What it does not carry:

* **superseded declarations** -- a round's earlier declarations.  A seat that
  declared and was overcalled showed its card(s) at the table; those copies are
  public.  ``Round`` keeps only the last declaration, so neither ``Memory`` nor
  the extract sees them;
* **the declaration sequence** -- how many declarations each seat made, who
  declared first, the final strength (single, pair, little-joker pair,
  big-joker pair), whether the banker overcalled another seat or reinforced its
  own call, no declaration at all (trump flipped from the kitty);
* **the bury rule's implied kitty** (board rows S31 / S23) for a seat that is not
  the banker: the banker's 33 cards at the bury -- its 25 kept plus the 8 buried
  -- drawn uniformly from the actor's unseen cards at play start with every
  public pin honoured, then the served bury's incumbent rule
  (`ai.heuristic.HeuristicBot.decide_bury`, the rule S31's ``kb`` uses) chooses
  the kitty.  Per card: the expected copies in the kitty and in the banker's
  kept hand over ``KB_DRAWS`` seeded draws, plus three summaries (kitty trumps,
  kitty points, kept trumps).  A prior, fixed at play start for the actor; the
  model's play-history inputs update it.

Not in the stores, so not here: declaration timing (deal position) and passes.

Inputs per (round, actor seat): ``DECL_ROW`` row features and ``DECL_CARD``
planes per card (seat-relative receivers next / partner / previous as in
``belief_labels``).  Everything is public to the actor or derived from its own
hand; nothing reads another hand or a non-banker's kitty.

The side extract ``decl/<split>-<chunk>.npz`` (``extract``) holds, per history
round of a chunk (``belief_history``'s round table), ``round_row`` ``(R, 4,
DECL_ROW)`` and ``round_card`` ``(R, 4, 54, DECL_CARD)`` indexed by the actor's
ABSOLUTE seat; ``belief_seq`` joins them by ``row_round`` / ``row_seat``.  The
live featurizer (``decision_declare_inputs``) rebuilds the same arrays from a
``Round`` and its declaration sequence; ``parity`` checks the two agree.

CLI: ``python -m shengji.train.belief_declare {extract,parity,bench}``.
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

from ..engine.cards import BJ, LJ, TRUMP, make_deck, points
from ..rl.encode import CARD_INDEX, N_CARDS

SCHEMA = "shengji-belief-declare-v2"
#: row features (per round and actor)
DECL_ROW_FEATURES = (
    "decls_rel0", "decls_rel1", "decls_rel2", "decls_rel3",
    "first_rel0", "first_rel1", "first_rel2", "first_rel3",
    "strength_single", "strength_pair", "strength_lj_pair", "strength_bj_pair",
    "n_decls", "banker_overcalled_other", "banker_reinforced", "no_declaration",
    "kb_available", "kb_kitty_trumps", "kb_kitty_points", "kb_kept_trumps",
)
#: per-card planes (seat-relative receivers as ``belief_labels.RECEIVERS``)
DECL_CARD_FEATURES = ("shown_rel1", "shown_rel2", "shown_rel3", "kb_kitty", "kb_kept")
DECL_ROW = len(DECL_ROW_FEATURES)
DECL_CARD = len(DECL_CARD_FEATURES)
#: bury-rule draws per (round, actor)
KB_DRAWS = 32
KITTY_SIZE = 8
BANKER_BURY_HAND = 33
_CODES = sorted(CARD_INDEX, key=CARD_INDEX.get)
_FULL = Counter(make_deck())


class BeliefDeclareError(ValueError):
    pass


# ------------------------------------------------------------------ features

def _strength(cards: Sequence[str], trump_rank: str) -> int:
    """1 single rank card, 2 rank pair, 3 little-joker pair, 4 big-joker pair."""
    if len(cards) == 1:
        return 1
    if cards[0] == LJ:
        return 3
    if cards[0] == BJ:
        return 4
    return 2


def _rng_for(seat: int, own_start: Sequence[str], declarations, trump_rank: str,
            banker: int) -> np.random.Generator:
    """The bury-rule draws' stream, seeded only by what the actor knows (its
    seat and play-start hand, the declaration sequence, trump rank, banker), so
    the extract and the live featurizer agree and no hidden card enters."""
    decl = ";".join(f"{int(d['seat'])}:{','.join(sorted(d['cards']))}" for d in declarations or [])
    key = f"{int(seat)}|{','.join(sorted(own_start))}|{decl}|{trump_rank}|{int(banker)}|s23-kb-v2"
    return np.random.default_rng(int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))


class _BuryStub:
    """What ``HeuristicBot.decide_bury`` reads: the ordering and the banker's hand."""

    def __init__(self, ordering, banker: int, hand: list[str]):
        self.ordering = ordering
        self.hands = [[], [], [], []]
        self.hands[banker] = hand


def kb_prior(ordering, banker: int, own_start: Sequence[str], pins_u: Counter,
             pins_other: Counter, rng: np.random.Generator, draws: int = KB_DRAWS
             ) -> tuple[np.ndarray, np.ndarray]:
    """``(kitty, kept)`` expected copies per card code: the banker's 33 cards
    drawn uniformly from the unseen pool (``pins_u`` always among them, the
    other seats' pins never), the kitty chosen by the incumbent bury rule."""
    from ..ai.heuristic import HeuristicBot
    pool = _FULL - Counter(own_start) - pins_u - pins_other
    need = BANKER_BURY_HAND - sum(pins_u.values())
    cards = sorted(pool.elements())
    if need < 0 or len(cards) < need:
        raise BeliefDeclareError("public pins do not fit the banker's bury hand")
    fixed = list(pins_u.elements())
    bot = HeuristicBot()
    kitty = np.zeros(N_CARDS, np.float64)
    kept = np.zeros(N_CARDS, np.float64)
    idx = np.arange(len(cards))
    for _ in range(draws):
        pick = rng.choice(idx, size=need, replace=False)
        hand = fixed + [cards[i] for i in pick]
        bur = bot.decide_bury(_BuryStub(ordering, banker, hand), banker)
        if len(bur) != KITTY_SIZE:
            raise BeliefDeclareError("the bury rule did not return eight cards")
        for c in bur:
            kitty[CARD_INDEX[c]] += 1
        for c in (Counter(hand) - Counter(bur)).elements():
            kept[CARD_INDEX[c]] += 1
    return kitty / draws, kept / draws


def declare_features(ordering, trump_rank: str, banker: int, seat: int,
                     declarations: Sequence[Mapping[str, Any]], own_start: Sequence[str], *,
                     draws: int = KB_DRAWS) -> tuple[np.ndarray, np.ndarray]:
    """``(row (DECL_ROW,), card (54, DECL_CARD))`` float32 for one actor of one
    round.  ``declarations`` is the round's declaration sequence (``setup``'s
    ``[{"seat", "cards"}]``, oldest first); ``own_start`` the actor's hand at
    play start (after the bury when the actor is the banker)."""
    row = np.zeros(DECL_ROW, np.float32)
    card = np.zeros((N_CARDS, DECL_CARD), np.float32)
    decls = [(int(d["seat"]), list(d["cards"])) for d in declarations or []]
    per_seat = Counter(s for s, _ in decls)
    for s, n in per_seat.items():
        row[(s - seat) % 4] = min(n, 2) / 2.0
    if decls:
        row[4 + (decls[0][0] - seat) % 4] = 1.0
        row[8 + _strength(decls[-1][1], trump_rank) - 1] = 1.0
        final_seat = decls[-1][0]
        row[13] = float(final_seat == banker and any(s != banker for s, _ in decls[:-1]))
        row[14] = float(per_seat[banker] >= 2)
    else:
        final_seat = None
        row[15] = 1.0
    row[12] = min(len(decls), 4) / 4.0
    # superseded declarations: the copies each seat showed (max over its calls)
    shown: dict[int, Counter] = {}
    for s, cards in decls[:-1]:
        c = Counter(cards)
        prev = shown.setdefault(s, Counter())
        for code, n in c.items():
            prev[code] = max(prev[code], n)
    for s, c in shown.items():
        rel = (s - seat) % 4
        if rel:
            for code, n in c.items():
                card[CARD_INDEX[code], rel - 1] = 0.5 * n
    if seat != banker:
        # every public pin: the final declaration with its declarer, superseded
        # calls with theirs; the banker's go into its bury hand
        pins: dict[int, Counter] = {s: Counter(c) for s, c in shown.items()}
        if final_seat is not None:
            fc = Counter(decls[-1][1])
            p = pins.setdefault(final_seat, Counter())
            for code, n in fc.items():
                p[code] = max(p[code], n)
        pins_u = pins.get(banker, Counter())
        pins_other = Counter()
        for s, c in pins.items():
            if s not in (banker, seat):
                pins_other += c
        kit, kept = kb_prior(ordering, banker, own_start, pins_u, pins_other,
                             _rng_for(seat, own_start, declarations, trump_rank, banker), draws)
        card[:, 3] = 0.5 * kit
        card[:, 4] = 0.5 * kept
        is_trump = np.asarray([ordering.eff_suit(c) == TRUMP for c in _CODES], np.float64)
        pts = np.asarray([points(c) for c in _CODES], np.float64)
        row[16] = 1.0
        row[17] = float(kit @ is_trump) / 8.0
        row[18] = float(kit @ pts) / 50.0
        row[19] = float(kept @ is_trump) / 25.0
    return row, card


def round_declare_features(rnd, declarations, *, draws: int = KB_DRAWS
                           ) -> tuple[np.ndarray, np.ndarray]:
    """``(4, DECL_ROW)`` and ``(4, 54, DECL_CARD)`` for the four actors of a round
    at play start (``rnd`` before any play)."""
    rows = np.zeros((4, DECL_ROW), np.float32)
    cards = np.zeros((4, N_CARDS, DECL_CARD), np.float32)
    for seat in range(4):
        rows[seat], cards[seat] = declare_features(
            rnd.ordering, rnd.trump_rank, int(rnd.banker), seat, declarations,
            list(rnd.hands[seat]), draws=draws)
    return rows, cards


def start_hand(rnd, seat: int) -> list[str]:
    """The actor's hand at play start: its hand now plus every card it has played."""
    out = list(rnd.hands[seat])
    for trick in list(rnd.history) + ([rnd.trick] if rnd.trick is not None else []):
        for tp in trick.plays:
            if tp.seat == seat:
                out += list(tp.cards)
    return out


def decision_declare_inputs(rnd, seat: int, declarations=None, *, draws: int = KB_DRAWS
                            ) -> tuple[np.ndarray, np.ndarray]:
    """The live featurizer: ``(row, card)`` as the extract stores them (float16
    rounded).  ``declarations`` is the round's sequence; None falls back to the
    final declaration alone (what a ``Round`` keeps)."""
    if declarations is None:
        d = rnd.declaration
        declarations = [] if d is None else [{"seat": d["seat"], "cards": d["cards"]}]
    row, card = declare_features(rnd.ordering, rnd.trump_rank, int(rnd.banker), int(seat),
                                 declarations, start_hand(rnd, seat), draws=draws)
    return (row.astype(np.float16).astype(np.float32),
            card.astype(np.float16).astype(np.float32))


# ------------------------------------------------------------------ side extract

def _first_records(shard: str) -> dict[int, dict]:
    """``{round_index: first play record}``: the record with an empty prefix of
    every mirror, in ``belief_labels.game_order``'s round order."""
    firsts: dict[int, dict] = {}
    with open(shard) as fh:
        for line in fh:
            if '"plays_prefix":[]' not in line and '"plays_prefix": []' not in line:
                continue
            r = json.loads(line)
            if r.get("decision_kind") != "play" or r.get("plays_prefix"):
                continue
            mirror = int(str(r["source_ref"]).split(":")[-3])
            firsts.setdefault(mirror, r)
    return {i: firsts[m] for i, m in enumerate(sorted(firsts))}


def chunk_declare(chunk_path: str, hist_path: str, shard_paths: Sequence[str], *,
                  draws: int = KB_DRAWS) -> dict[str, np.ndarray]:
    from ..harvest.rebuild import round_from_setup
    with np.load(chunk_path) as z:
        cl = z["cluster"].astype(np.int64)
        ri = z["round_index"].astype(np.int64)
    with np.load(hist_path) as z:
        row_round = z["row_round"].astype(np.int64)
        banker = z["banker"].astype(np.int64)
        R = len(z["round_n"])
    if len(row_round) != len(cl):
        raise BeliefDeclareError(f"{chunk_path}: history rows differ")
    key = np.full((R, 2), -1, np.int64)
    for i in range(len(cl)):
        r = row_round[i]
        if key[r, 0] < 0:
            key[r] = (cl[i], ri[i])
        elif key[r, 0] != cl[i] or key[r, 1] != ri[i]:
            raise BeliefDeclareError(f"{chunk_path}: round {r} spans two (cluster, round)s")
    if (key < 0).any():
        raise BeliefDeclareError(f"{chunk_path}: a history round has no row")
    rows = np.zeros((R, 4, DECL_ROW), np.float16)
    cards = np.zeros((R, 4, N_CARDS, DECL_CARD), np.float16)
    n_decl = np.zeros(R, np.int8)
    cache: dict[int, dict[int, dict]] = {}
    for r in range(R):
        c, rix = int(key[r, 0]), int(key[r, 1])
        if c not in cache:
            cache = {c: _first_records(shard_paths[c])}
        rec = cache[c].get(rix)
        if rec is None:
            raise BeliefDeclareError(f"{chunk_path}: cluster {c} has no round {rix}")
        rnd = round_from_setup(rec["deck"], rec["setup"])
        if int(rnd.banker) != int(banker[r]):
            raise BeliefDeclareError(f"{chunk_path}: round {r} banker differs from the history")
        decls = rec["setup"].get("declarations") or []
        a, b = round_declare_features(rnd, decls, draws=draws)
        rows[r], cards[r] = a, b
        n_decl[r] = len(decls)
    return {"round_row": rows, "round_card": cards, "round_key": key.astype(np.int32),
            "n_decl": n_decl}


def _chunk_task(args) -> dict:
    chunk_path, hist_path, out_path, shard_paths, draws = args
    t0 = time.time()
    if Path(out_path).exists():
        return {"out": out_path, "skipped": True,
                "sha256": hashlib.sha256(Path(out_path).read_bytes()).hexdigest(), "seconds": 0.0}
    arrays = chunk_declare(chunk_path, hist_path, shard_paths, draws=draws)
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    b = buf.getvalue()
    tmp = out_path + ".tmp"
    Path(tmp).write_bytes(b)
    os.replace(tmp, out_path)
    return {"out": out_path, "skipped": False, "rounds": int(len(arrays["round_row"])),
            "sha256": hashlib.sha256(b).hexdigest(), "seconds": time.time() - t0}


def extract(dirs: Sequence[str], stores_root: str, *, workers: int, splits: Sequence[str],
            only_files: set[str] | None = None, draws: int = KB_DRAWS, log=print) -> dict:
    """``decl/`` next to the chunks of each extract dir (resumable).  ``only_files``
    restricts to those chunk paths (e.g. the train subset a run reads); the
    manifest lists exactly the files present."""
    from .belief_labels import cluster_paths
    out = {}
    for d in dirs:
        man = json.loads((Path(d) / "manifest.json").read_text())
        hman_raw = (Path(d) / "hist" / "manifest.json").read_bytes()
        store = Path(stores_root) / Path(man["stores"][0]).name
        shards = [str(p) for p in cluster_paths(store)]
        dd = Path(d) / "decl"
        dd.mkdir(exist_ok=True)
        tasks = []
        for chunk in man["chunks"]:
            for split, e in chunk["files"].items():
                path = str(Path(d) / e["file"])
                if split not in splits or (only_files is not None and path not in only_files):
                    continue
                tasks.append((path, str(Path(d) / "hist" / e["file"]), str(dd / e["file"]), shards,
                              draws))
        t0 = time.time()
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for i, res in enumerate(pool.map(_chunk_task, tasks)):
                if (i + 1) % 50 == 0 or i + 1 == len(tasks):
                    log(f"[decl] {Path(d).name}: {i + 1}/{len(tasks)} {time.time() - t0:.0f}s", flush=True)
        files = {}
        for f in sorted(dd.glob("*.npz")):
            files[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
        dm = {"schema": SCHEMA, "source_hist_manifest_sha256": hashlib.sha256(hman_raw).hexdigest(),
              "store": str(store), "row_features": DECL_ROW_FEATURES,
              "card_features": DECL_CARD_FEATURES, "kb_draws": draws, "files": files}
        (dd / "manifest.json").write_text(json.dumps(dm, indent=1, default=list))
        out[d] = {"files": len(files), "seconds": time.time() - t0}
        log(json.dumps({Path(d).name: out[d]}), flush=True)
    return out


# ------------------------------------------------------------------ checks

def parity(dirs: Sequence[str], stores_root: str, *, files: int, seed: int) -> dict:
    """Replay rounds of extract chunks that have a ``decl`` file and compare the
    live featurizer at EVERY decision with the stored (round, actor) arrays."""
    from .belief_labels import _read_records, cluster_paths, iter_decisions
    rng = np.random.default_rng(seed)
    checked = bad = 0
    worst = 0.0
    for d in dirs:
        dm = json.loads((Path(d) / "decl" / "manifest.json").read_text())
        man = json.loads((Path(d) / "manifest.json").read_text())
        shards = [str(p) for p in cluster_paths(Path(stores_root) / Path(man["stores"][0]).name)]
        names = sorted(dm["files"])
        for name in [names[i] for i in rng.permutation(len(names))[:files]]:
            with np.load(Path(d) / "decl" / name) as z:
                rows, cards, key = z["round_row"], z["round_card"], z["round_key"]
            for r in rng.permutation(len(key))[:4]:
                c, rix = int(key[r, 0]), int(key[r, 1])
                plays = [x for x in _read_records(Path(shards[c])) if x.get("decision_kind") == "play"]
                for dec in iter_decisions(plays):
                    if dec.round_index != rix:
                        continue
                    a, b = decision_declare_inputs(dec.rnd, dec.seat,
                                                   dec.record["setup"].get("declarations") or [])
                    diff = max(float(np.abs(a - rows[r, dec.seat].astype(np.float32)).max()),
                               float(np.abs(b - cards[r, dec.seat].astype(np.float32)).max()))
                    worst = max(worst, diff)
                    checked += 1
                    bad += diff > 0
    return {"decisions": checked, "mismatched": bad, "max_abs_diff": worst}


def bench(stores_root: str, store: str, *, rounds: int, draws: int) -> dict:
    from ..harvest.rebuild import round_from_setup
    from .belief_labels import cluster_paths
    shards = cluster_paths(Path(stores_root) / store)
    t = []
    for p in shards[:rounds]:
        for rec in _first_records(str(p)).values():
            rnd = round_from_setup(rec["deck"], rec["setup"])
            t0 = time.perf_counter()
            round_declare_features(rnd, rec["setup"].get("declarations") or [], draws=draws)
            t.append(time.perf_counter() - t0)
    t = np.asarray(t)
    return {"rounds": len(t), "ms_p50": float(np.median(t) * 1e3), "ms_p90": float(np.quantile(t, 0.9) * 1e3)}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="belief_declare", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract")
    ex.add_argument("--data", nargs="+", required=True)
    ex.add_argument("--stores-root", required=True)
    ex.add_argument("--workers", type=int, default=2)
    ex.add_argument("--splits", default="train,calib,test")
    ex.add_argument("--train-rows", type=int, default=None,
                    help="decl only for the train chunks `belief_seq train --max-train-rows N "
                         "--seed S` reads (all calib/test chunks)")
    ex.add_argument("--calib-rows", type=int, default=30000)
    ex.add_argument("--test-rows", type=int, default=None)
    ex.add_argument("--seed", type=int, default=0)
    ex.add_argument("--draws", type=int, default=KB_DRAWS)
    pa = sub.add_parser("parity")
    pa.add_argument("--data", nargs="+", required=True)
    pa.add_argument("--stores-root", required=True)
    pa.add_argument("--files", type=int, default=2)
    pa.add_argument("--seed", type=int, default=0)
    be = sub.add_parser("bench")
    be.add_argument("--stores-root", required=True)
    be.add_argument("--store", required=True)
    be.add_argument("--rounds", type=int, default=20)
    be.add_argument("--draws", type=int, default=KB_DRAWS)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "extract":
        only = None
        splits = [s for s in args.splits.split(",") if s]
        if args.train_rows is not None:
            # exactly the chunks a `belief_seq train --max-train-rows N --calib-rows C --seed S`
            # and an `evaluate --calib-rows C --test-rows T --seed S` read
            from .belief_seq import extract_entries, pick_eval_entries, pick_train_entries
            only = {e["path"] for e in pick_train_entries(extract_entries(args.data, "train"),
                                                          args.train_rows, args.seed)}
            only |= {e["path"] for e in pick_eval_entries(extract_entries(args.data, "calib"),
                                                          args.calib_rows, args.seed)}
            only |= {e["path"] for e in pick_eval_entries(extract_entries(args.data, "test"),
                                                          args.test_rows, args.seed + 1)}
        extract(args.data, args.stores_root, workers=args.workers, splits=splits, only_files=only,
                draws=args.draws)
        return 0
    if args.command == "parity":
        r = parity(args.data, args.stores_root, files=args.files, seed=args.seed)
        print(json.dumps(r))
        return 1 if r["mismatched"] or not r["decisions"] else 0
    if args.command == "bench":
        print(json.dumps(bench(args.stores_root, args.store, rounds=args.rounds, draws=args.draws)))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
