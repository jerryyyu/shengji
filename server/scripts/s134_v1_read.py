#!/usr/bin/env python3
"""S134 V1 reader: the unified model's Q head against the served value's 64-world mixture, on Y BAR decisions.

Predeclared (board #1263 row S134, issue #1525; written here before any S134 training):

* **Sample.**  The Y value holdout store (``STORE``: seeds [1000100000, +3000), one deal per cluster) split by the
  G4b reader's rule ``int(sha256("g3-yhold|" + deal_key)[:8], 16) % 2`` (1 = BAR; 1,488 BAR deals, pinned).  The
  300 BAR clusters with the smallest ``sha256("s134-v1|" + str(cluster))`` (``SAMPLE_SALT``), every play decision
  of both rounds.  The list's sha256 is ``CHOSEN_SHA256``.
* **Reference (b).**  The served value ``f4f4127e`` averaged over the 64 worlds release 52's own sampler draws at
  that decision (``PVSearchBot._worlds``: B1a proposal, history-legal draw, refusal ledger fed after every play as
  release 52's event-complete rule does), each world's leaf the training row's afterstate
  (``cwv_policy.afterstate(..., finish_trick=False)``); NLL = -log of the mixture's probability of the realised
  category (G9's scorer, ``g9_score.py`` sha256 ``e62ba912``, rebuilt for release 52 and this store).  Reference
  (a), the same value on the true world, must equal the G4b anchors run's per-row base NLL exactly (``ANCHORS``).
* **Q.**  ``-log`` of the Q head's probability of the realised category at the actor's own play token.
* **Rows.**  Every play decision of the sample except round-ending plays (their leaf is terminal; G9 excluded them).
* **Bar.**  d = mean(Q NLL) - mean((b) NLL), paired by deal, 95% percentile CI from a deal bootstrap with 10,000
  resamples, seed 1 (G9's).  STRONG PASS: d <= -0.010 and the CI upper bound < 0.  KILL: d > +0.010.  PARITY:
  every other result.  Validity guards (``expert_labels/validity.py``) and the coverage / reproduction checks run
  first; any failure is DEV_INVALID and no outcome is computed.
* **Also read, not gates.**  B1 belief no-harm: the trainer's own calib LL of the unified belief head (bar
  <= 0.98982 on B1a's calib split; B1a 0.98782), and q_eff on the S112 points (paired 95% LB of unified - B1a >
  -0.010; S114's scorer with the exported belief package, run separately and passed in).  P1 policy: FT1's
  gate-7 R50H / YH reads need belief-format extracts of those stores, which stage 1 does not build (NOT
  AVAILABLE); recorded instead, on these Y BAR decisions, recall@1 / @8 of the played action for the policy head
  and for FT1 as served (64 sampled worlds), paired.

Stages (each resumable; ``OUT/status`` gets an armed line and one terminal line per stage):

  choose     the sample list (reads decks only)                       -> OUT/chosen.json
  extract    belief-format rows of the sample (``belief_labels`` / ``belief_history`` on a view store)
  score-ref  (a), (b) and FT1's served policy rank per decision         -> OUT/ref/w*.jsonl
  score-q    the unified package's Q NLL and policy rank per decision   -> OUT/q.jsonl
  analyze    guards, then the bar (once: refuses an existing result)    -> OUT/result.json

Claim limits: an offline NLL read on played moves only; no ranking, strength or latency claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

LANE = "s134v1"
SAMPLE_SALT = "s134-v1|"
SAMPLE_N = 300
SPLIT_SALT = "g3-yhold|"
BAR_HALF = 1
HOLDOUT_WINDOW = "g3-yhold-1000100000"
STORE = dict(path="/Users/jerryyu/.cache/codex-y-100k-rounds-expand/corpus",
             manifest_sha256="380b0f9299fd9059b0d1c44703dc7b3b322d2a664e156ee37e77affa4af478cd",
             seed0=1000100000, clusters=3000, bar_deals=1488)
#: sha256 of "\n".join(chosen clusters), computed by `choose` from the decks before any S134 training
CHOSEN_SHA256 = "03823c3861dcf44fcb163c11c43e1b485c4031ea4be99fbb1505bca45a7e99d9"
ANCHORS = dict(path="/Users/jerryyu/shengji-archive/2026-11-06-g4b-packet/readers/runs/g4bv-anchors/rows.npz",
               sha256="1518c0df9c250992930756c3ec77b91a6a688e1d321f6929b299aa5eb8119bad", column="base__nll")
RELEASE = 52
VALUE_SHA = "f4f4127ec0c8821b4aa07f7d651a4258c696f97a874707da2c78ad26c0c9b9fd"
PRIOR_SHA = "1fa201b288e78b3072979f55030aae44711ee214b50a14e155d0bbe11b6bb1bf"
G9_SCORER_SHA = "e62ba912957118745bb052ae953da83fc4383c2ab33cf6a2b44d253d158f93f0"
WORLDS = 64
LEGAL_CAP = 4000
BOOT, BOOT_SEED = 10_000, 1
STRONG_PASS_POINT, KILL_POINT = -0.010, 0.010
B1_CALIB_LL_MAX = 0.98982
B1_QEFF_PAIRED_LB_MIN = -0.010
P1_REFERENCE = dict(ft1_r50h_recall8=0.8798, ft1_r50h_recall1=0.4067, ft1_yh_expert_lead_recall8=0.7979,
                    bar_r50h_paired_lb=-0.010, bar_yh_delta=-0.005)
VERDICTS = ("STRONG_PASS", "PARITY", "KILL")
INVALID = "DEV_INVALID"


class Refusal(RuntimeError):
    pass


def need(ok, msg):
    if not ok:
        raise Refusal(msg)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def status(out: Path, msg: str) -> None:
    line = f"{now()} {LANE} {msg}"
    print(line, flush=True)
    with open(out / "status", "a") as fh:
        fh.write(line + "\n")


# ------------------------------------------------------------------ the sample

def half_of(deal_key: str) -> int:
    return int(hashlib.sha256((SPLIT_SALT + str(deal_key)).encode()).hexdigest()[:8], 16) % 2


def sample_rank(cluster: int) -> str:
    return hashlib.sha256((SAMPLE_SALT + str(int(cluster))).encode()).hexdigest()


def choose_clusters(bar_clusters, n=SAMPLE_N) -> list[int]:
    """The predeclared rule: the ``n`` BAR clusters with the smallest ``sample_rank``, in that order."""
    return sorted((int(c) for c in bar_clusters), key=sample_rank)[:n]


def list_sha(clusters) -> str:
    return hashlib.sha256("\n".join(str(int(c)) for c in clusters).encode()).hexdigest()


def deal_key_of_shard(path: Path) -> str:
    from shengji.harvest.rebuild import state_for_record
    from shengji.rl.value_afterstate import _deal_key
    with open(path) as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("decision_kind") == "play":
                return _deal_key(state_for_record(r))
    raise Refusal(f"{path}: no play record")


def store_manifest(store=STORE) -> dict:
    mpath = Path(store["path"], "manifest.json")
    need(sha256_file(mpath) == store["manifest_sha256"], "Y holdout store manifest drift")
    man = json.loads(mpath.read_text())
    seeds = sorted(int(s["seed"]) for s in man["shards"])
    need(seeds == list(range(store["seed0"], store["seed0"] + store["clusters"])), "Y holdout seeds differ")
    return man


def cmd_choose(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    man = store_manifest()
    bar = []
    for sh in man["shards"]:
        if half_of(deal_key_of_shard(Path(STORE["path"], sh["path"]))) == BAR_HALF:
            bar.append(int(sh["cluster"]))
    need(len(bar) == STORE["bar_deals"], f"{len(bar)} BAR deals, G4b pins {STORE['bar_deals']}")
    chosen = choose_clusters(bar)
    sha = list_sha(chosen)
    need(sha == CHOSEN_SHA256, f"chosen list {sha} != pinned {CHOSEN_SHA256}")
    smoke = int(a.smoke or 0)
    used = chosen[:smoke] if smoke else chosen
    (out / "chosen.json").write_text(json.dumps({"clusters": used, "sha256": list_sha(used), "full_sha256": sha,
                                                 "smoke": smoke, "salt": SAMPLE_SALT, "bar_deals": len(bar)}, indent=0))
    status(out, f"choose DONE clusters={len(used)} sha256={sha} smoke={smoke}")
    return 0


def load_chosen(out: Path, *, allow_smoke: bool = True) -> list[int]:
    """The sample; a smoke list (the pinned list's first N clusters) only where ``allow_smoke``."""
    c = json.loads((out / "chosen.json").read_text())
    need(list_sha(c["clusters"]) == c["sha256"], "chosen.json does not hash to its own sha")
    need(c["full_sha256"] == CHOSEN_SHA256, "chosen.json is not from the pinned list")
    need(c["sha256"] == CHOSEN_SHA256 or (allow_smoke and c["smoke"] == len(c["clusters"]) > 0),
         "chosen.json is a smoke subset")
    return [int(x) for x in c["clusters"]]


def shard_path(cluster: int) -> Path:
    return Path(STORE["path"], "shards", f"cluster-{int(cluster):06d}.jsonl")


# ------------------------------------------------------------------ extract

def cmd_extract(a) -> int:
    """A view store of the sample (manifest filtered, shards and sidecars symlinked), then the production
    belief-label and history extractors with every row in the test split."""
    from shengji.train import belief_history as bh
    from shengji.train import belief_labels as bl
    out = Path(a.out)
    chosen = load_chosen(out)
    man = store_manifest()
    view = out / "view" / "corpus"
    if not (out / "x" / "hist" / "manifest.json").exists():
        (view / "shards").mkdir(parents=True, exist_ok=True)
        keep = [sh for sh in man["shards"] if int(sh["cluster"]) in set(chosen)]
        need(len(keep) == len(chosen), "a chosen cluster is not in the store")
        for sh in keep:
            for rel in (sh["path"], sh["sidecar"]):
                dst = view / rel
                if not dst.exists():
                    os.symlink(Path(STORE["path"], rel), dst)
        (view / "manifest.json").write_text(json.dumps(dict(man, shards=keep)))
        # the extractor skips every registered non-trajectory seed window; this holdout is one of them and
        # is exactly what the read needs, so only its own window is lifted (any other overlap refuses)
        registered = bl.excluded_windows()
        hit = {w[2] for w in registered for sh in keep if w[0] <= int(sh["seed"]) < w[1]}
        need(hit == {HOLDOUT_WINDOW}, f"the sample's seeds lie in registered windows {sorted(hit)}")
        saved = bl.excluded_windows
        bl.excluded_windows = lambda registry=None: [w for w in registered if w[2] != HOLDOUT_WINDOW]
        try:
            bl.extract([str(view)], str(out / "x"), cluster_stride=1, cluster_offset=0, max_clusters_per_store=None,
                       calib=0.0, test=1.0, sampler_worlds=0, sampler_splits=(), sampler_stride=1,
                       workers=a.workers, task_clusters=10, resume=(out / "x").exists())
        finally:
            bl.excluded_windows = saved
        bh.extract([str(out / "x")], str(out / "view"), workers=a.workers)
    xm = json.loads((out / "x" / "manifest.json").read_text())
    rows = sum(c["files"]["test"]["rows"] for c in xm["chunks"] if "test" in c["files"])
    need(not xm["excluded_clusters"] and not xm["failed_clusters"], "extract excluded or failed a cluster")
    status(out, f"extract DONE rows={rows} manifest_sha256={sha256_file(out / 'x' / 'manifest.json')}")
    return 0


def load_extract(out: Path):
    """The sample's belief-format rows (test split), outcome-joined, with the original cluster number."""
    from shengji.train import belief_seq as bs
    from shengji.train import unified_seq as us
    view = out / "view" / "corpus"
    idx = us.OutcomeIndex()
    entries = us.entries_for([str(out / "x")], "test")
    part = bs.concat_parts([us.load_unified_part(e, bs._Verified(), idx) for e in entries])
    names = [p.name for p in sorted((view / "shards").glob("cluster-*.jsonl"))]
    part["orig_cluster"] = np.asarray([int(names[int(c)].split("-")[1].split(".")[0]) for c in part["cluster"]])
    return part


# ------------------------------------------------------------------ score-ref

def build_served_bot(pkg_dir: str):
    from shengji import releases
    from shengji.ai import belief_numpy
    from shengji.eval import served_config
    m = releases.load(RELEASE)
    paths = releases.package_paths(m, pkg_dir)
    need(set(paths) == set(m["packages"]), f"packages missing from {pkg_dir}: {sorted(set(m['packages']) - set(paths))}")
    env = releases.local_env(m, paths)
    process = {k: v for k, v in env.items() if k not in releases.PROCESS_KEYS}
    ctx = served_config.process_env(process)
    ctx.__enter__()
    registration, bot = releases._build(process, True, 1)
    belief_numpy.PREP_SECONDS = 60.0
    need(bot.evaluator.checkpoint_sha256 == VALUE_SHA, "served value is not f4f4127e")
    need(bot.worlds == WORLDS and bot.belief_worlds and bot.world_history_legal and bot.refusal_constraints
         and bot.refusal_event_complete, "release 52's sampler switches are not all on")
    return m, registration, bot


def seed_of(ref: str) -> int:
    return int(hashlib.sha256(("s134|" + ref).encode()).hexdigest()[:15], 16)


def _key(cards):
    return tuple(sorted(cards))


def ordered_plays(cluster: int) -> list[dict]:
    """A cluster's play records in table order (``belief_labels.game_order``: the extract's decision order)."""
    from shengji.train.belief_labels import _read_records, game_order
    return game_order(_read_records(shard_path(cluster)))


def score_ref_worker(out: Path, worker: int, workers: int, pkg_dir: str, limit: int = 0) -> None:
    from shengji.ai.cwv_policy import afterstate
    from shengji.ai.refusal import RefusalLedger
    from shengji.harvest.legal import enumerate_legal
    from shengji.harvest.rebuild import state_for_record
    from shengji.rl.value_afterstate import signed_level_category
    chosen = load_chosen(out)[worker::workers]
    m, registration, bot = build_served_bot(pkg_dir)
    ev = bot.evaluator
    path = out / "ref" / f"w{worker}.jsonl"
    path.parent.mkdir(exist_ok=True)
    done = set()
    if path.exists():
        for line in open(path):
            r = json.loads(line)
            if r.get("kind") == "row":
                done.add(r["ref"])
    fh = open(path, "a")
    fh.write(json.dumps(dict(kind="header", worker=worker, workers=workers, bot=bot.policy_name, release=RELEASE,
                             registration=registration, value=ev.checkpoint_sha256,
                             prior=getattr(bot.predict, "sha256", None), pid=os.getpid())) + "\n")
    n = 0
    for cl in chosen:
        ledgers: dict = {}
        cur_round = None
        for decision, rec in enumerate(ordered_plays(cl)):
            ref = rec["source_ref"]
            rk = ref.rsplit(":", 2)[0]
            if rk != cur_round:
                cur_round = rk
                ledgers = {s: RefusalLedger() for s in range(4)}
            seat = int(rec["seat"])
            root = state_for_record(rec)
            need(root.phase == "play" and root.turn == seat, f"{ref}: replay is not the actor's turn")
            for s in range(4):                    # event-complete: every seat reads each committed play's notice
                ledgers[s].observe(root)
            bot._refusals = ledgers[seat]
            if ref in done:
                continue
            t0 = time.perf_counter()
            bot.sampler.rng.seed(seed_of(ref))
            worlds, attempts = bot._worlds(root, seat)
            samp = dict(bot._last_sampling or {})
            o = rec["outcome"]
            role_att = (seat % 2) != (int(rec["setup"]["banker"]) % 2)
            target = signed_level_category(int(o["attacker_points"]), role_att)
            action = list(rec["action"])
            true_world = ([list(h) for h in root.hands], list(root.buried))
            leaves = [afterstate(root, seat, true_world[0], true_world[1], action, finish_trick=False)] + \
                     [afterstate(root, seat, h, b, action, finish_trick=False) for h, b in worlds]
            terminal = leaves[0].phase == "round_end"
            v = {}
            if not terminal and all(lf.phase != "round_end" for lf in leaves):
                P = ev.probabilities([ev.encoder(lf, seat) for lf in leaves])
                pt, ps = float(P[0, target]), float(P[1:, target].mean())
                v = dict(nll_true=-float(np.log(pt)), nll_mix=-float(np.log(ps)) if ps > 0 else float("inf"),
                         nll_world_mean=float(-np.log(np.maximum(P[1:, target], 1e-300)).mean()))
            sd = (rec.get("allocation") or {}).get("serving_decision") or {}
            ls = enumerate_legal(root, seat, cap=LEGAL_CAP, must_include=[action] + list(sd.get("admitted") or []))
            legal = [list(x) for x in ls.actions]
            j = next(i for i, x in enumerate(legal) if _key(x) == _key(action))
            pr = {}
            if len(legal) >= 2:
                ss = bot.scores(root, seat, legal, worlds).mean(axis=0)
                pr = dict(ft1_rank=int((ss > ss[j]).sum()), n_legal=len(legal), legal_sha=_legal_sha(legal))
            row = dict(kind="row", ref=ref, cluster=int(cl), decision=decision, round=rk, seat=seat,
                       ply=len(rec["plays_prefix"]), cards_left=len(root.hands[seat]), lead=not root.trick.plays,
                       role_attacker=role_att, target=int(target), terminal=terminal, worlds=len(worlds),
                       attempts=int(attempts), belief_fallback=bool(samp.get("belief_fallback")),
                       outcome={k: int(o[k]) for k in ("attacker_points", "kitty_bonus", "winner_team", "level_change")},
                       banker=int(rec["setup"]["banker"]), secs=round(time.perf_counter() - t0, 4), **v, **pr)
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            n += 1
            if limit and n >= limit:
                fh.close()
                return
    fh.write(json.dumps(dict(kind="worker_done", worker=worker, clusters=len(chosen))) + "\n")
    fh.close()


def _legal_sha(legal) -> str:
    return hashlib.sha256(json.dumps(sorted(_key(x) for x in legal)).encode()).hexdigest()[:16]


def cmd_score_ref(a) -> int:
    out = Path(a.out)
    if a.worker is not None:
        score_ref_worker(out, a.worker, a.workers, a.pkg_dir, a.limit)
        return 0
    status(out, f"score-ref armed (pid {os.getpid()}, reader sha256 {sha256_file(__file__)}, workers {a.workers})")
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    procs = [subprocess.Popen([sys.executable, "-B", __file__, "score-ref", "--out", str(out), "--pkg-dir", a.pkg_dir,
                               "--worker", str(i), "--workers", str(a.workers), "--limit", str(a.limit)],
                              env=env, stdout=open(out / f"ref-w{i}.log", "a"), stderr=subprocess.STDOUT)
             for i in range(a.workers)]
    rcs = [p.wait() for p in procs]
    if any(rcs):
        status(out, f"score-ref ABORT worker rcs {rcs}")
        return 1
    status(out, f"score-ref DONE workers={a.workers} limit={a.limit}")
    return 0


def load_ref(out: Path) -> tuple[list[dict], list[dict]]:
    rows, heads = [], []
    files = sorted((out / "ref").glob("w*.jsonl"))
    need(files, "no score-ref output")
    for f in files:
        ended = False
        for line in open(f):
            r = json.loads(line)
            if r["kind"] == "row":
                rows.append(r)
            elif r["kind"] == "header":
                heads.append(r)
            elif r["kind"] == "worker_done":
                ended = True
        need(ended, f"{f.name}: no worker_done line (incomplete)")
    return rows, heads


# ------------------------------------------------------------------ score-q

def cmd_score_q(a) -> int:
    from shengji.ai import unified_numpy as un
    from shengji.harvest.legal import enumerate_legal
    from shengji.harvest.rebuild import state_for_record
    from shengji.rl.encode import CARD_INDEX
    from shengji.train import belief_seq as bs
    from shengji.train import unified_seq as us
    out = Path(a.out)
    rt = un.load_unified_numpy(a.pkg, sha256=a.sha256)
    status(out, f"score-q armed (pid {os.getpid()}, reader sha256 {sha256_file(__file__)}, package {rt.package_sha256})")
    part = load_extract(out)
    rows_out = []
    t0 = time.time()
    for rids, rows in bs.round_batches(part, 8, None):
        b = us.make_unified_batch(part, rids, rows)
        by_cluster = defaultdict(list)
        for k, i in enumerate(rows):
            by_cluster[int(part["orig_cluster"][i])].append((int(part["decision"][i]), k, int(i)))
        for cl, items in by_cluster.items():
            plays = ordered_plays(cl)
            for decision, k, i in items:
                rec = plays[decision]
                need(int(rec["seat"]) == int(b["seat"][k]) and len(rec["plays_prefix"]) == int(b["ply"][k]),
                     f"cluster {cl} decision {decision}: extract row is not the record's decision")
                qp = rt.q_probs(un.batch_inputs(b, k, with_play=True))
                tgt = int(b["q_target"][k])
                pl = rt.policy_logits(un.batch_inputs(b, k, with_play=False))
                root = state_for_record(rec)
                action = list(rec["action"])
                sd = (rec.get("allocation") or {}).get("serving_decision") or {}
                ls = enumerate_legal(root, int(rec["seat"]), cap=LEGAL_CAP,
                                     must_include=[action] + list(sd.get("admitted") or []))
                legal = [list(x) for x in ls.actions]
                j = next(x for x, act in enumerate(legal) if _key(act) == _key(action))
                pr = {}
                if len(legal) >= 2:
                    sc = np.asarray([sum(float(pl[CARD_INDEX[c]]) for c in act) for act in legal])
                    pr = dict(q_policy_rank=int((sc > sc[j]).sum()), legal_sha=_legal_sha(legal))
                rows_out.append(dict(ref=rec["source_ref"], cluster=cl, decision=decision, q_target=tgt,
                                     nll_q=-float(np.log(max(qp[tgt], 1e-300))), **pr))
    rows_out.sort(key=lambda r: (r["cluster"], r["decision"]))
    with open(out / "q.jsonl", "w") as fh:
        for r in rows_out:
            fh.write(json.dumps(r) + "\n")
    status(out, f"score-q DONE rows={len(rows_out)} package={rt.package_sha256} seconds={time.time() - t0:.0f} "
                f"q.jsonl sha256 {sha256_file(out / 'q.jsonl')}")
    return 0


# ------------------------------------------------------------------ analyze

def _validity():
    sys.path.insert(0, str(SERVER / "scripts" / "expert_labels"))
    import validity as va
    return va


def deal_bootstrap(clusters, a, b=None, *, boot=BOOT, seed=BOOT_SEED):
    """Mean of ``a`` (or of ``a - b``, paired) over rows, and its 95% percentile CI resampling deals."""
    d = np.asarray(a, np.float64) - (0.0 if b is None else np.asarray(b, np.float64))
    uniq, inv = np.unique(np.asarray(clusters), return_inverse=True)
    K = len(uniq)
    s = np.bincount(inv, weights=d, minlength=K)
    n = np.bincount(inv, minlength=K).astype(np.float64)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, K, size=(boot, K))
    est = s[idx].sum(1) / n[idx].sum(1)
    lo, hi = np.percentile(est, [2.5, 97.5])
    return float(d.mean()), float(lo), float(hi)


def verdict_of(point: float, upper: float) -> str:
    """The predeclared V1 rule."""
    if not (np.isfinite(point) and np.isfinite(upper)):
        return INVALID
    if point <= STRONG_PASS_POINT and upper < 0:
        return "STRONG_PASS"
    if point > KILL_POINT:
        return "KILL"
    return "PARITY"


def guards(ref_rows, q_rows, *, anchors=None):
    """Every check that must pass before an outcome is computed: coverage, alignment, the true-world
    reproduction and the validity guards.  Returns (valid, reasons, checks)."""
    va = _validity()
    reasons = []
    ref_by = {r["ref"]: r for r in ref_rows}
    q_by = {r["ref"]: r for r in q_rows}
    if len(ref_by) != len(ref_rows) or len(q_by) != len(q_rows):
        reasons.append("duplicate decision refs")
    if set(ref_by) != set(q_by):
        reasons.append(f"ref and Q rows cover different decisions ({len(set(ref_by) ^ set(q_by))} differ)")
    for ref in set(ref_by) & set(q_by):
        if ref_by[ref]["target"] != q_by[ref]["q_target"]:
            reasons.append(f"{ref}: the record's target and the sidecar join's differ")
            break
    scored = [r for r in ref_rows if not r["terminal"]]
    if any("nll_mix" not in r or not np.isfinite(r["nll_mix"]) for r in scored):
        reasons.append("a non-terminal row without a finite mixture NLL")
    if anchors is not None:
        miss = [r["ref"] for r in scored if r["ref"] not in anchors]
        diff = max((abs(r["nll_true"] - anchors[r["ref"]]) for r in scored if r["ref"] in anchors), default=0.0)
        if miss or diff != 0.0:
            reasons.append(f"(a) does not reproduce the G4b anchors: {len(miss)} rows missing, max |diff| {diff}")
    rounds = {}
    for r in ref_rows:
        rounds.setdefault(r["round"], dict(banker=r["banker"], **r["outcome"]))
    checks = [
        va.arm_fault_ceilings({"mix": {"belief_fallback": sum(r["belief_fallback"] for r in ref_rows),
                                       "search": len(ref_rows)},
                               "q": {"belief_fallback": 0, "search": len(q_rows)}},
                              dict(play_fallback=None, belief_fallback=0.01, bury_fallback=None, declare_abandon=None),
                              arms=("mix", "q")),
        va.worlds_delivered([(r["ref"], "mix", "search", r["worlds"]) for r in ref_rows]
                            + [(r["ref"], "q", "search", 1) for r in q_rows], {"mix": WORLDS, "q": 1}),
        va.outcome_consistency(list(rounds.items())),
    ]
    v = va.combine(checks)
    if v["verdict"] != va.VALID:
        reasons += v["reasons"]
    return not reasons, reasons, checks


def load_anchors(refs) -> dict:
    need(sha256_file(ANCHORS["path"]) == ANCHORS["sha256"], "G4b anchors rows drift")
    with np.load(ANCHORS["path"]) as z:
        src = z["source_ref"].astype(str)
        col = z[ANCHORS["column"]]
    want = set(refs)
    return {r: float(v) for r, v in zip(src.tolist(), col.tolist()) if r in want}


def analysis(ref_rows, q_rows) -> dict:
    """The bar and the descriptive tables (call only after `guards` passed)."""
    q_by = {r["ref"]: r for r in q_rows}
    rows = [r for r in ref_rows if not r["terminal"]]
    cl = np.asarray([r["cluster"] for r in rows])
    q = np.asarray([q_by[r["ref"]]["nll_q"] for r in rows])
    mix = np.asarray([r["nll_mix"] for r in rows])
    true = np.asarray([r["nll_true"] for r in rows])
    point, lo, hi = deal_bootstrap(cl, q, mix)
    res = {"rows": len(rows), "deals": int(len(np.unique(cl))), "terminal_excluded": len(ref_rows) - len(rows),
           "nll": {"q": float(q.mean()), "mix_b": float(mix.mean()), "true_a": float(true.mean())},
           "d_q_minus_mix": {"point": point, "lo95": lo, "hi95": hi},
           "d_q_minus_true": dict(zip(("point", "lo95", "hi95"), deal_bootstrap(cl, q, true))),
           "verdict": verdict_of(point, hi),
           "rule": f"STRONG_PASS: d <= {STRONG_PASS_POINT} and hi95 < 0; KILL: d > +{KILL_POINT}; else PARITY"}
    strata = {"cards<=8": lambda r: r["cards_left"] <= 8, "cards9-16": lambda r: 9 <= r["cards_left"] <= 16,
              "cards17+": lambda r: r["cards_left"] >= 17, "lead": lambda r: r["lead"],
              "follow": lambda r: not r["lead"], "attacker": lambda r: r["role_attacker"],
              "banker_team": lambda r: not r["role_attacker"]}
    res["strata"] = {}
    for name, f in strata.items():
        m = np.asarray([f(r) for r in rows])
        if m.sum():
            res["strata"][name] = {"n": int(m.sum()), "q": float(q[m].mean()), "mix_b": float(mix[m].mean()),
                                   "d": dict(zip(("point", "lo95", "hi95"), deal_bootstrap(cl[m], q[m], mix[m])))}
    pol = [(r, q_by[r["ref"]]) for r in ref_rows if "ft1_rank" in r and "q_policy_rank" in q_by[r["ref"]]]
    if pol:
        pc = np.asarray([r["cluster"] for r, _ in pol])
        out = {"n": len(pol), "legal_sets_equal": all(r["legal_sha"] == x["legal_sha"] for r, x in pol)}
        for k in (1, 8):
            a = np.asarray([x["q_policy_rank"] < k for _, x in pol], float)
            f = np.asarray([r["ft1_rank"] < k for r, _ in pol], float)
            out[f"recall{k}"] = {"policy_head": float(a.mean()), "ft1_served": float(f.mean()),
                                 "d": dict(zip(("point", "lo95", "hi95"), deal_bootstrap(pc, a, f)))}
        res["p1_y_bar_descriptive"] = out
    return res


def cmd_analyze(a) -> int:
    out = Path(a.out)
    result = out / "result.json"
    need(not result.exists(), "result.json exists: the reader reads once")
    need(a.partial or not a.no_anchors, "--no-anchors is smoke only: a full read checks (a) against the G4b anchors")
    st = (out / "status").read_text()
    need(" score-ref DONE " in st and " score-q DONE " in st and " extract DONE " in st, "a stage is not DONE")
    ref_rows, heads = load_ref(out)
    q_rows = [json.loads(line) for line in open(out / "q.jsonl")]
    need(all(h["release"] == RELEASE and h["value"] == VALUE_SHA and h["prior"] == PRIOR_SHA for h in heads),
         "a score-ref worker ran another bot")
    chosen = load_chosen(out, allow_smoke=a.partial)
    expect = sum(len(ordered_plays(c)) for c in chosen)
    anchors = None if a.no_anchors else load_anchors([r["ref"] for r in ref_rows])
    ok, reasons, checks = guards(ref_rows, q_rows, anchors=anchors)
    if len(ref_rows) != expect and not a.partial:
        ok, reasons = False, reasons + [f"{len(ref_rows)} scored decisions, the sample has {expect}"]
    res = {"schema": "s134-v1-result-v1", "reader_sha256": sha256_file(__file__), "chosen_sha256": list_sha(chosen),
           "package": [h for h in st.splitlines() if " score-q DONE " in h][-1], "decisions_expected": expect,
           "partial": bool(a.partial), "anchors_checked": anchors is not None,
           "checks": [{k: c[k] for k in ("check", "verdict", "reasons")} for c in checks]}
    if not ok:
        res.update(verdict=INVALID, reasons=reasons)
    else:
        res.update(analysis(ref_rows, q_rows))
    if a.b1_calib_ll is not None:
        res["b1_calib_ll"] = {"value": a.b1_calib_ll, "bar": B1_CALIB_LL_MAX, "pass": a.b1_calib_ll <= B1_CALIB_LL_MAX}
    if a.b1_qeff_lb is not None:
        res["b1_qeff_paired_lb"] = {"value": a.b1_qeff_lb, "bar": B1_QEFF_PAIRED_LB_MIN,
                                    "pass": a.b1_qeff_lb > B1_QEFF_PAIRED_LB_MIN}
    res["p1_gate7"] = dict(P1_REFERENCE, status="NOT AVAILABLE in stage 1: R50H / YH have no belief-format extract")
    result.write_text(json.dumps(res, indent=1))
    status(out, f"analyze DONE verdict={res['verdict']} result sha256 {sha256_file(result)}")
    print(json.dumps({k: res[k] for k in ("verdict",) + (("d_q_minus_mix", "nll") if ok else ("reasons",))}, indent=1))
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("choose")
    c.add_argument("--out", required=True)
    c.add_argument("--smoke", type=int, default=0, help="smoke only: keep the list's first N clusters")
    e = sub.add_parser("extract")
    e.add_argument("--out", required=True)
    e.add_argument("--workers", type=int, default=4)
    r = sub.add_parser("score-ref")
    r.add_argument("--out", required=True)
    r.add_argument("--pkg-dir", required=True, help="local copies of release 52's packages (sha-checked)")
    r.add_argument("--workers", type=int, default=2)
    r.add_argument("--worker", type=int, default=None)
    r.add_argument("--limit", type=int, default=0, help="decisions per worker (smoke); 0 = all")
    q = sub.add_parser("score-q")
    q.add_argument("--out", required=True)
    q.add_argument("--pkg", required=True)
    q.add_argument("--sha256", required=True)
    z = sub.add_parser("analyze")
    z.add_argument("--out", required=True)
    z.add_argument("--b1-calib-ll", type=float, default=None)
    z.add_argument("--b1-qeff-lb", type=float, default=None)
    z.add_argument("--partial", action="store_true", help="smoke only: score a subset of the decisions")
    z.add_argument("--no-anchors", action="store_true", help="smoke only: skip the (a) reproduction check")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return {"choose": cmd_choose, "extract": cmd_extract, "score-ref": cmd_score_ref, "score-q": cmd_score_q,
                "analyze": cmd_analyze}[a.cmd](a)
    except Refusal as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        if Path(getattr(a, "out", ".")).is_dir():
            status(Path(a.out), f"{a.cmd} ABORT {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
