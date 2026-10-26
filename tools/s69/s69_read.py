#!/usr/bin/env python3
"""s69 DEV head-to-head reader (board #1075 row S69: where does R48 lose now?  The S61 design re-run against R48): paired, seat-swapped,
the S69 exploiter (R48 at the M27 expert budget: play worlds 256, admission K 32, exact caps 8 / 8, exact-lead deadline 9 s, exact node
caps 2e8, play budget 60 s, no lgfd; everything else R48's, the latency switches on both sides) at the exploiter seats vs R48 as served
(fly.toml at d33bfd70) at the defender seats, on the r2 rank-mixed plan per deal, 600 deals from 311060910.  s61dev_read.py (476ea123, the
Codex-PASSed S61 reader) with the arms, the binding, the zero play / belief fallback ceilings and the S61 comparison lines changed; the
read is predeclare_s69.md's, evaluated as written there.

  python3 s69_read_r3.py <output root> <lane status> <reservation> <out.json>      (host mode: the three paths must be TRUSTED's)
  python3 s69_read.py --check-imports                                            (loads the pinned helpers beside this file; no input)

BINDING (refuses, first): reader_lib.bind_inputs (the root, status and reservation are the reserved dispatch paths; the reservation names
this lane, its launcher sha256, status and output root); the status has exactly one terminal line '<stamp> s69 DEV output sealed; rc/status
only (strength qualification is reader-owned); LANE DONE' and no ABORT: / REFUSING: line (reader_lib.terminal_line, NO_TAIL: cloud has no
S17 handshake), exactly one DEV start line (the launcher's exact text: both pinned names, the nine overrides, deals, seed0, plan, workers,
stop) and one 'DEV END rc=0' line before it; <root>/duel.jsonl's sha256 equals its './duel.jsonl' line in <root>/SHA256SUMS.
INTEGRITY (refuses; no number is written): s61dev's (arm identity, no override fired, the pinned names, exactly DEALS seeds x 2 mirrors, the
r2 plan per deal, the 19-field dhist and its row schema on both sides with exact_deep_cards 8 on the exploiter and 7 on the defender, the
reconciliations, no defender 8-card stage, at least one complete exploiter 8-card lead and follow, the declare / bury producer shapes at
64 / 32 / K <= 64 on both sides), plus the decision trace (trace_gate), the play history (history_gate: --history's buried / history / failed_detail on every row,
reconciled with the trace as card multisets, failed_detail entry by entry) and the first-divergence form (the same state, two policies).
VALIDITY (validity.py on BOTH arms, before any outcome; a failure -> DEV_INVALID and no outcome): arm_fault_ceilings (ZERO play fallbacks
and ZERO belief fallbacks on each side; bury fallbacks <= 1% of the side's buries; declare abandons <= 1% of its declare evaluations; one
ceilings mapping for both arms), worlds_delivered (every search record reports the side's play worlds: 256 exploiter / 64 defender),
completion_shape (an evaluated declare completed its 64 worlds), outcome_consistency (every row obeys the engine's level rule).
THE READ (predeclared, descriptive; never a release, deploy or strength claim for any servable candidate; the exploiter is not servable):
  HEAD-TO-HEAD: the paired mean (levels/round; per deal the mean exploiter-signed level change over its two mirrors) with a 10,000-rep deal
    (cluster) bootstrap 95% percentile CI: EXPLOITER_AHEAD iff the CI lower bound > 0; DEFENDER_AHEAD iff the CI upper bound < 0; else
    NO_RESOLVED_GAP.
  ATTRIBUTION: each deal's paired margin is assigned whole to its first divergent decision (first_divergence): class declare / bury / lead /
    follow x trick band (pre-play; tricks 1-5, 6-10, 11-15, 16+) x rank group (first round at rank 2; fixed banker 2-6, 7-10, J-A).  A
    cell's contribution = (sum of its deals' margins) / all deals, in levels/round (the cells sum to the head-to-head mean); its 95% CI from
    the same bootstrap draws.  Reported: the top-3 loss cells (the largest positive contributions: R48's losses) with CIs, the top-3 gain
    cells, the class x trick marginal, the class / rank group / role marginals, the top decile of deals by margin, and the 20 largest
    exploiter wins with both actions.  FLAG: every class x trick x rank cell and every class x trick cell whose contribution point estimate
    is >= +0.020 levels/round (each a candidate board row; resolved iff its CI lower bound > 0).  ATTRIBUTION_INVALID (the head-to-head
    stands; no cell is reported as a finding) iff a deal whose mirrors never diverged has a nonzero margin.
  VERSUS S61 (descriptive): the head-to-head, the class marginals and every class x trick x rank cell of S61's sealed read (s61_reference.json,
    pinned) through compare_runs.versus_earlier_run: the difference, the independent-runs SE (each run's SE = its 95% percentile CI width /
    (2 x 1.95996)), the normal-approximation 95% interval and the caveat "independent runs, not a paired test".  The two runs differ in the
    defender (release 46 vs R48), the exploiter and the deals; the lines locate change, they measure nothing about either release.
"""
import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

#: the pinned helpers (fl-pilot/reader_lib), each loaded only at its sha256 and only from beside this reader (the host copy, the packet)
PINNED = {'row_schema': 'b7fe41d3e00049cf361ba0be4a750e0978417a5cf454eec1e8d611a05ba086df', 'validity': 'ba84c408c3b96fbe7834184df09a48dc66b3a1c492913c8f1462d36825ea1920', 'reader_lib': '9c7ea58bddf5d7fe5515a50a3239e0ea7d0b0defe4dcb315ebb50b719dea24ee', 'compare_runs': '8c2e26fdf3a70f30e720a51e8d33f68f3770641067d59d007b96032743fd9f57'}
S61_REFERENCE_SHA256 = "5d567cebea8c292710978d66aad423173fc3108ad169d7bef5229fb8810b451b"
LIB_DIRS = (Path(__file__).resolve().parent,)
ROW_SCHEMA_SHA = PINNED["row_schema"]


def _load_pinned(name):
    for d in LIB_DIRS:
        path = d / f"{name}.py"
        if path.is_file():
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != PINNED[name]:
                raise SystemExit(f"REFUSING: {name} source drift at {path} (expected {PINNED[name]})")
            spec = importlib.util.spec_from_loader(f"s69_{name}", loader=None)
            module = importlib.util.module_from_spec(spec)
            exec(compile(raw, str(path), "exec"), module.__dict__)
            return module
    raise SystemExit(f"REFUSING: {name}.py not found in {[str(d) for d in LIB_DIRS]}")


rs = _load_pinned("row_schema")
va = _load_pinned("validity")
rl = _load_pinned("reader_lib")
cr = _load_pinned("compare_runs")

R48 = "pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-rc252e656-bury-hybrid-bwv-cd6dd3d2b02a"   # R48 as served: fly.toml SHENGJI_BOT at d33bfd70, the DEFENDER seats
CAND = "pv-search-491ee4bf-w256-k32-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-ed8-els9000-edn200000000-xf8-xfcompactlevel-r9779eb5a-bury-hybrid-bwv-80b4500430de"   # the S69 exploiter (name_probe.out; re-derived on the host by check_names)
EX_ENV = "SHENGJI_PV_WORLDS=256 SHENGJI_PV_CANDIDATES=32 SHENGJI_PV_EXACT_DEEP_CARDS=8 SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS=8 SHENGJI_PV_EXACT_LEAD_MAX_SECONDS=9.0 SHENGJI_PV_EXACT_DEEP_MAX_NODES=200000000 SHENGJI_PV_EXACT_FOLLOW_MAX_NODES=200000000 SHENGJI_PV_SERVING_BUDGET_SECONDS=60 SHENGJI_PV_LEAF_GREEDY_DEADLINE="   # the launcher's EX_ENV
SEED0, DEALS, WORKERS, KILL_AFTER, BACKSTOP = 311060910, 600, 12, 28800, 28810
LANE = "s69"
TRUSTED = dict(lane=LANE, launcher_sha256="726a8af097551ff77b996e741ce070605bf50838b4d045f72fc6cab8b9cac802", host="shengji-cloud",
               root="/root/vol-dev-claude-s69-r48-20261026", status="/root/claude_s69_screen.status",
               reservation="/root/claude_reservations/s69_r2.json")   # the launcher's OUT and S, its reservation; launcher_sha256 = the RELEASE token
TERMINAL = "s69 DEV output sealed; rc/status only (strength qualification is reader-owned); LANE DONE"   # the launcher's final say, minus the stamp
START = (f"{LANE} DEV start: defender {R48} (R48 as served) vs exploiter {CAND} (S69 exploiter: {EX_ENV}); deals {DEALS} seed0 {SEED0} plan r2, "
         f"paired and seat-swapped, play histories kept (--history); workers {WORKERS}; group KILL at {KILL_AFTER} s (backstop {BACKSTOP} s)")   # the launcher's DEV start say, minus the stamp
RANKS13 = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")
FIRST_INDICES = (0, 3, 5, 8)
#: the predeclared read: head-to-head words by the CI; the loss-cell flag; the validity ceilings (ONE mapping, on BOTH arms: zero play and belief fallbacks)
BAR = dict(ahead_ci_lower_above=0.0, behind_ci_upper_below=0.0, flag_min_contribution=0.020, top_k=3, top_decile_share=0.10, top_deals_listed=20,
           ceilings=dict(play_fallback=0, belief_fallback=0, bury_fallback=0.01, declare_abandon=0.01))
ARMS = ("ex", "r45")   # the harness's side keys: "ex" = the exploiter seats, "r45" = the defender seats (R48 as served here)
#: the side recipes' world counts (both sides R48's declare and bury knobs; the exploiter widens play worlds x4): value-declare worlds and wide-bury value worlds
DECLARE_WORLDS = {"ex": 64, "r45": 64}
PLAY_WORLDS = {"ex": 256, "r45": 64}
BURY_WORLDS = {"ex": 32, "r45": 32}
BURY_K = {"ex": 64, "r45": 64}
DHIST_LEN = 19   # s60dev: s59dev's 18 fields + field 18 = the search record's play worlds (None on a fallback).  s59dev's: schema12 (the record schema's last 12 chars: '-decision-v1' / '-fallback-v1'), hist_rej, hist_fb, attempts, belief_fb, belief_ms, belief_proposed, belief_err, maxh, lead, exact_deep_cards, lead_status, lead_abandon_reason, lead_changed, xf_attempted, xf_abandoned, xf_applied, seconds
MAXH, LEAD, ED, LST, LAR, LCH, XFA, XFB, XFC = range(8, 17)
BOOT_REPS, BOOT_SEED = 10000, 1


def round_plan(index):
    if index % 10 in FIRST_INDICES:
        return ("first", "2", None)
    return ("fixed_banker", RANKS13[index % 13], index % 4)


def refuse(msg):
    raise SystemExit(f"REFUSING: {msg}")


def read(path, *, seed0=SEED0, deals=DEALS, r48=R48, cand=CAND):
    rows = 0
    by = {}
    for line in open(path):
        r = json.loads(line)
        rows += 1
        if r.get("arm") != "identity" or sum((r.get("fired") or {}).values()) != 0:
            refuse(f"row seed {r.get('seed')} mirror {r.get('mirror')}: arm {r.get('arm')!r} / fired {r.get('fired')!r} (identity with no override expected)")
        if r.get("defender") != r48:
            refuse(f"row seed {r.get('seed')}: defender {r.get('defender')!r} is not R48 as served")
        if r.get("exploiter_base") != cand:
            refuse(f"row seed {r.get('seed')}: exploiter base {r.get('exploiter_base')!r} is not the S69 exploiter")
        key = (r.get("seed"), r.get("mirror"))
        if type(key[0]) is not int or key[1] not in (0, 1) or r.get("ex_team") != key[1]:
            refuse(f"row {key}: seed / mirror / ex_team form")
        if key in by:
            refuse(f"duplicate row {key}")
        by[key] = r
    want = {(seed0 + i, m) for i in range(deals) for m in (0, 1)}
    if set(by) != want:
        missing = sorted(want - set(by))[:5]; extra = sorted(set(by) - want)[:5]
        refuse(f"deals: {len(by)} rows, expected {2 * deals} ({deals} deals x 2 mirrors from {seed0}); missing {missing}, extra {extra}")
    for (seed, mirror), r in by.items():
        kind, rank, banker = round_plan(seed - seed0)
        if (r.get("round_kind"), r.get("trump_rank"), r.get("planned_banker")) != (kind, rank, banker):
            refuse(f"plan: seed {seed} mirror {mirror} recorded {(r.get('round_kind'), r.get('trump_rank'), r.get('planned_banker'))!r}, planned {(kind, rank, banker)!r}")
        if banker is not None and r.get("banker") != banker:
            refuse(f"plan: seed {seed} mirror {mirror} fixed banker {r.get('banker')!r}, planned {banker}")
        if r.get("ex_role") != ("banker" if r.get("banker") % 2 == mirror else "attacker"):
            refuse(f"role: seed {seed} mirror {mirror} ex_role {r.get('ex_role')!r} disagrees with banker {r.get('banker')} and ex_team {mirror}")
        for side in ("ex", "r45"):
            hist = (r.get("dhist") or {}).get(side)
            secs = (r.get("dsecs") or {}).get(side)
            if not isinstance(hist, list) or not isinstance(secs, list) or len(hist) != len(secs) or not hist:
                refuse(f"dhist / dsecs form: seed {seed} mirror {mirror} side {side}")
            for h in hist:
                if not isinstance(h, list) or len(h) != DHIST_LEN:
                    refuse(f"dhist entry form: seed {seed} mirror {mirror} side {side} ({len(h) if isinstance(h, list) else type(h).__name__} fields, expected {DHIST_LEN})")
            if not all(NONNEG(x) for x in secs):
                refuse(f"dsecs form: seed {seed} mirror {mirror} side {side} carries a non-number or negative decide_play time")
        drec, brec = r.get("declare_recs"), r.get("bury_rec")
        if not isinstance(drec, dict) or set(drec) != {"ex", "r45"} or not all(isinstance(drec[k], list) for k in drec):
            refuse(f"declare_recs form: seed {seed} mirror {mirror}")
        if not isinstance(brec, list) or len(brec) != 6:
            refuse(f"bury_rec form: seed {seed} mirror {mirror}")
        if brec[0] != ("ex" if r.get("banker") % 2 == mirror else "r45"):
            refuse(f"bury_rec side: seed {seed} mirror {mirror} records {brec[0]!r}, the banker {r.get('banker')} is on the other team")
    return by, rows


SEARCH_SCHEMA, FALLBACK_SCHEMA = "-decision-v1", "-fallback-v1"   # pv_search_policy RECORD_SCHEMA / FALLBACK_SCHEMA, the harness's schema[-12:]
#: OptionalStage.reason on an abandoned stage (optional_stage.py): a latched hard / soft expiry, or any other abandoning exception
ABANDON_REASONS = ("hard_budget", "soft_budget", "error")
LEAD_ELIGIBLE = ("lead_single_candidate", "lead_skipped_budget", "lead_abandoned", "lead_complete")
FOLLOW_ATTEMPTED = ("follow_complete", "follow_abandoned")
NONNEG = rs.number_at_least(0)


def decision_shapes(cap):
    """Every dhist entry form exploit_duel_s60.py (exploit_duel_s59.py's dhist, unchanged) can write from pv_search_policy at main 8d7aeb81 (PVSearchBot._search,
    _exact_lead_decision, the exact-follow stage, _decide_play's fallback record) for a side whose recipe carries exact_deep_cards = cap
    and exact_follow_max_cards = cap (ed8/xf8: 8; R48's ed7/xf7: 7), belief worlds on (both arms).

    Search record: exact_deep_cards = cap; exact_lead_status starts 'ineligible' and stays so unless leading at max hand <= cap, where it
    becomes single_candidate / skipped_budget / abandoned (with a reason) / complete; exact_lead_changed False except a complete stage's
    bool; exact_lead_abandon_reason ABSENT (None here) unless abandoned.  The follow record exists only when not leading, max hand <= cap
    and more than one admitted candidate: attempted True, then abandoned (a reason, applied False) or complete (abandoned None, applied a
    bool); otherwise all three ABSENT.  belief_fallback 0 with belief_error ABSENT, or 1 with belief_error the exception's class name.
    Fallback record: none of the search fields (all None), maxh and lead from the harness."""
    nn = rs.int_in(0, 10 ** 9)
    common = {0: rs.one_of(SEARCH_SCHEMA), 1: nn, 2: nn, 3: nn, 5: NONNEG, 6: nn, 10: rs.one_of(cap), 17: NONNEG, 18: rs.int_in(1, 256)}
    belief = {"belief_ok": {4: rs.one_of(0), 7: rs.NULL}, "belief_fallback": {4: rs.one_of(1), 7: rs.nonempty_str}}
    small, large, any_h = rs.int_in(1, cap), rs.int_in(cap + 1, 25), rs.int_in(1, 25)
    no_follow = {14: rs.NULL, 15: rs.NULL, 16: rs.NULL}
    not_lead_stage = {11: rs.one_of("ineligible"), 12: rs.NULL, 13: rs.one_of(False)}
    stages = {
        "follow_none": {8: any_h, 9: rs.one_of(False), **not_lead_stage, **no_follow},
        "follow_complete": {8: small, 9: rs.one_of(False), **not_lead_stage, 14: rs.one_of(True), 15: rs.NULL, 16: rs.BOOL},
        "follow_abandoned": {8: small, 9: rs.one_of(False), **not_lead_stage, 14: rs.one_of(True), 15: rs.one_of(*ABANDON_REASONS), 16: rs.one_of(False)},
        "lead_ineligible": {8: large, 9: rs.one_of(True), **not_lead_stage, **no_follow},
        "lead_single_candidate": {8: small, 9: rs.one_of(True), 11: rs.one_of("single_candidate"), 12: rs.NULL, 13: rs.one_of(False), **no_follow},
        "lead_skipped_budget": {8: small, 9: rs.one_of(True), 11: rs.one_of("skipped_budget"), 12: rs.NULL, 13: rs.one_of(False), **no_follow},
        "lead_abandoned": {8: small, 9: rs.one_of(True), 11: rs.one_of("abandoned"), 12: rs.one_of(*ABANDON_REASONS), 13: rs.one_of(False), **no_follow},
        "lead_complete": {8: small, 9: rs.one_of(True), 11: rs.one_of("complete"), 12: rs.NULL, 13: rs.BOOL, **no_follow},
    }
    shapes = {f"search/{st}/{bn}": {**common, **bf, **sf} for st, sf in stages.items() for bn, bf in belief.items()}
    shapes["fallback"] = {0: rs.one_of(FALLBACK_SCHEMA), **{i: rs.NULL for i in (1, 2, 3, 4, 5, 6, 7)}, 8: any_h, 9: rs.BOOL,
                          **{i: rs.NULL for i in range(10, 19)}}
    return shapes


def decision_schema_gate(by):
    """Both sides, before any count: every dhist entry classified into exactly one producer shape, then the counts reconciled against
    independent recounts of the raw fields.  Returns {side: [(row, entry, shape stage) ...]} in a fixed order; a failure refuses."""
    out = {}
    for side, cap in (("ex", 8), ("r45", 7)):
        items = [((seed, mirror, i), h) for (seed, mirror), r in sorted(by.items()) for i, h in enumerate(r["dhist"][side])]
        try:
            labels, counts = rs.classify_rows(items, decision_shapes(cap), label=f"{side} dhist (cap {cap})", length=DHIST_LEN, with_where=True)
        except rs.RowSchemaRefusal as e:
            refuse(str(e))
        stage = lambda name: sum(v for k, v in counts.items() if k.startswith("search/") and k.split("/")[1] == name)
        search = sum(v for k, v in counts.items() if k.startswith("search/"))
        raw = lambda f: sum(1 for _, h in items if f(h))
        try:
            rs.reconcile([
                (f"{side} decisions = search + fallback", len(items), [search, counts["fallback"]]),
                (f"{side} search = schema {SEARCH_SCHEMA!r} rows", search, raw(lambda h: h[0] == SEARCH_SCHEMA)),
                (f"{side} fallback = schema {FALLBACK_SCHEMA!r} rows", counts["fallback"], raw(lambda h: h[0] == FALLBACK_SCHEMA)),
                (f"{side} lead eligible (search, leading, max hand <= {cap}) = single_candidate + skipped_budget + abandoned + complete",
                 raw(lambda h: h[0] == SEARCH_SCHEMA and h[LEAD] is True and h[MAXH] <= cap), [stage(k) for k in LEAD_ELIGIBLE]),
                (f"{side} lead ineligible (search, leading, max hand > {cap})", raw(lambda h: h[0] == SEARCH_SCHEMA and h[LEAD] is True and h[MAXH] > cap), stage("lead_ineligible")),
                (f"{side} follow attempted = complete + abandoned", raw(lambda h: h[0] == SEARCH_SCHEMA and h[XFA] is True), [stage(k) for k in FOLLOW_ATTEMPTED]),
                (f"{side} follow attempted <= follow eligible (search, following, max hand <= {cap})", [stage(k) for k in FOLLOW_ATTEMPTED],
                 raw(lambda h: h[0] == SEARCH_SCHEMA and h[LEAD] is False and h[MAXH] <= cap), "<="),
                (f"{side} belief fallbacks = search rows with belief_fallback 1", sum(v for k, v in counts.items() if k.endswith("/belief_fallback")),
                 raw(lambda h: h[0] == SEARCH_SCHEMA and type(h[4]) is int and h[4] == 1)),
            ], label=f"{side} dhist")
        except rs.RowSchemaRefusal as e:
            refuse(str(e))
        out[side] = [(items[j][0], items[j][1], lab) for j, lab in enumerate(labels)]
    return out


DECLARE_SCHEMA, BURY_SCHEMA, BURY_FALLBACK_SCHEMA = "pv-value-declare-decision-v1", "cwv-bury-policy-v1", "cwv-bury-fallback-v1"


def declare_shapes(side):
    """exploit_duel_s60.py's declare_recs entry: [schema, fallback_reason, evaluated, worlds, worlds_completed, record seconds, call wall]
    from PVSearchBot._value_declare_decision (pv_search_policy at main 8d7aeb81): evaluated = not stage.abandoned; fallback_reason =
    OptionalStage.reason (None when evaluated); worlds = the recipe's value_declare_worlds."""
    w = DECLARE_WORLDS[side]
    common = {0: rs.one_of(DECLARE_SCHEMA), 3: rs.one_of(w), 5: NONNEG, 6: NONNEG}
    # an evaluated declaration scored every world; an abandoned one may have completed any number of them, all included (the stage's
    # final hard check in OptionalStage.publish can fail after the last world)
    return {"declare/evaluated": {**common, 1: rs.NULL, 2: rs.one_of(True), 4: rs.one_of(w)},
            "declare/abandoned": {**common, 1: rs.one_of(*ABANDON_REASONS), 2: rs.one_of(False), 4: rs.int_in(0, w)}}


def bury_shapes(side):
    """exploit_duel_s60.py's bury_rec: [side, schema, fallback_reason, candidate_count, model_worlds, call wall] from
    CWVBuryMixin.decide_bury / _decide_bury (cwv_bury_policy at main 8d7aeb81) on the wide value-only chooser: a policy record (reason None,
    the chooser's candidates <= the side's K, model_worlds the side's) or the budget / search-error fallback (no model_worlds key)."""
    k = BURY_K[side]
    return {"bury/policy": {0: rs.one_of(side), 1: rs.one_of(BURY_SCHEMA), 2: rs.NULL, 3: rs.int_in(1, k), 4: rs.one_of(BURY_WORLDS[side]), 5: NONNEG},
            "bury/fallback": {0: rs.one_of(side), 1: rs.one_of(BURY_FALLBACK_SCHEMA), 2: rs.one_of("budget", "search-error"),
                              3: rs.Spec("int_or_null", lambda v: v is None or (type(v) is int and 0 <= v <= k)), 4: rs.NULL, 5: NONNEG}}


def declare_bury_gate(by):
    """Both sides: every declare record and every bury record classified into exactly one producer shape, then reconciled.  Returns the
    per-side tallies {side: dict(declares, declare_abandoned, declare_secs, buries, bury_fallback, bury_secs, bury_candidates)}."""
    out = {}
    for side in ("ex", "r45"):
        ditems = [((seed, mirror, i), d) for (seed, mirror), r in sorted(by.items()) for i, d in enumerate(r["declare_recs"][side])]
        bitems = [((seed, mirror), r["bury_rec"]) for (seed, mirror), r in sorted(by.items()) if r["bury_rec"][0] == side]
        try:
            dl, dc = rs.classify_rows(ditems, declare_shapes(side), label=f"{side} declare_recs", length=7, with_where=True) if ditems else ([], {"declare/evaluated": 0, "declare/abandoned": 0})
            bl, bc = rs.classify_rows(bitems, bury_shapes(side), label=f"{side} bury_rec", length=6, with_where=True) if bitems else ([], {"bury/policy": 0, "bury/fallback": 0})
            rs.reconcile([
                (f"{side} declares = evaluated + abandoned", len(ditems), [dc.get("declare/evaluated", 0), dc.get("declare/abandoned", 0)]),
                (f"{side} declare abandons = records with a reason", dc.get("declare/abandoned", 0), sum(1 for _, d in ditems if d[1] is not None)),
                (f"{side} buries = policy + fallback", len(bitems), [bc.get("bury/policy", 0), bc.get("bury/fallback", 0)]),
                (f"{side} bury fallbacks = fallback-schema records", bc.get("bury/fallback", 0), sum(1 for _, b in bitems if b[1] == BURY_FALLBACK_SCHEMA)),
            ], label=f"{side} declare / bury")
        except rs.RowSchemaRefusal as e:
            refuse(str(e))
        out[side] = dict(declares=len(ditems), declare_abandoned=dc.get("declare/abandoned", 0), buries=len(bitems), bury_fallback=bc.get("bury/fallback", 0),
                         declare_secs=[d[6] for _, d in ditems], bury_secs=[b[5] for _, b in bitems],
                         bury_candidates=[b[3] for _, b in bitems if b[1] == BURY_SCHEMA])
    if out["ex"]["buries"] + out["r45"]["buries"] != len(by):
        refuse(f"bury records: {out['ex']['buries']} + {out['r45']['buries']} != {len(by)} rows")
    return out


def exact8_gate(by):
    """The row schema first (decision_schema_gate), then the exact8 gate (refuses) and the exact-stage tally (reported), every count from
    the shape each entry matched, never from a field's truthiness."""
    classified = decision_schema_gate(by)
    ex = dict(decisions=0, search=0, fallback=0, belief_fallback=0, d8=0, d8_lead=0, d8_follow=0, d8_lead_complete=0, d8_lead_abandoned=0,
              d8_lead_skipped_budget=0, d8_lead_single_candidate=0, d8_lead_changed=0, d8_follow_attempted=0, d8_follow_complete=0,
              d8_follow_abandoned=0, d8_follow_changed=0, le7_lead_not_complete=0, le7_follow_abandoned=0, abandon_reasons={})
    df = dict(decisions=0, search=0, fallback=0, belief_fallback=0, d8=0, d8_stage=0, le7_lead_not_complete=0, le7_follow_abandoned=0)
    for side, t in (("ex", ex), ("r45", df)):
        for where, h, lab in classified[side]:
            t["decisions"] += 1
            if lab == "fallback":
                t["fallback"] += 1
                continue
            _, st, bn = lab.split("/")
            t["search"] += 1; t["belief_fallback"] += int(bn == "belief_fallback")
            d8 = h[MAXH] == 8
            t["d8"] += int(d8)
            if h[MAXH] <= 7:
                t["le7_lead_not_complete"] += int(st in ("lead_abandoned", "lead_skipped_budget"))
                t["le7_follow_abandoned"] += int(st == "follow_abandoned")
            if side == "r45":
                df["d8_stage"] += int(d8 and st not in ("lead_ineligible", "follow_none"))
                continue
            if not d8:
                continue
            if h[LEAD]:
                ex["d8_lead"] += 1
                ex["d8_lead_complete"] += int(st == "lead_complete"); ex["d8_lead_abandoned"] += int(st == "lead_abandoned")
                ex["d8_lead_skipped_budget"] += int(st == "lead_skipped_budget"); ex["d8_lead_single_candidate"] += int(st == "lead_single_candidate")
                ex["d8_lead_changed"] += int(st == "lead_complete" and h[LCH] is True)
                if st == "lead_abandoned":
                    k = f"lead:{h[LAR]}"; ex["abandon_reasons"][k] = ex["abandon_reasons"].get(k, 0) + 1
            else:
                ex["d8_follow"] += 1
                if st in FOLLOW_ATTEMPTED:
                    ex["d8_follow_attempted"] += 1
                    if st == "follow_abandoned":
                        ex["d8_follow_abandoned"] += 1
                        k = f"follow:{h[XFB]}"; ex["abandon_reasons"][k] = ex["abandon_reasons"].get(k, 0) + 1
                    else:
                        ex["d8_follow_complete"] += 1; ex["d8_follow_changed"] += int(h[XFC] is True)
    try:
        rs.reconcile([
            ("ex 8-card leads = single_candidate + skipped_budget + abandoned + complete", ex["d8_lead"],
             [ex["d8_lead_single_candidate"], ex["d8_lead_skipped_budget"], ex["d8_lead_abandoned"], ex["d8_lead_complete"]]),
            ("ex 8-card follows attempted = complete + abandoned", ex["d8_follow_attempted"], [ex["d8_follow_complete"], ex["d8_follow_abandoned"]]),
            ("ex 8-card follows attempted <= 8-card follows", ex["d8_follow_attempted"], ex["d8_follow"], "<="),
            ("ex abandon reasons = 8-card lead + follow abandons", sum(ex["abandon_reasons"].values()), [ex["d8_lead_abandoned"], ex["d8_follow_abandoned"]]),
            ("ex decisions = search + fallback", ex["decisions"], [ex["search"], ex["fallback"]]),
            ("r45 decisions = search + fallback", df["decisions"], [df["search"], df["fallback"]]),
        ], label="exact8 tally")
    except rs.RowSchemaRefusal as e:
        refuse(str(e))
    if df["d8_stage"]:
        refuse(f"exact8: {df['d8_stage']} defender decisions at max hand 8 ran an exact stage (expected none: R48 is exact at <= 7)")
    if ex["search"] == 0 or ex["d8_lead_complete"] == 0 or ex["d8_follow_complete"] == 0:
        refuse(f"exact8: the exploiter completed {ex['d8_lead_complete']} 8-card exact leads and {ex['d8_follow_complete']} 8-card exact follows (expected at least one of each: ed8/xf8 never exercised)")
    return ex, df


def boot(x, reps=BOOT_REPS, seed=BOOT_SEED):
    x = np.asarray(x, float)
    if not len(x):
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(reps, len(x)))
    m = x[idx].mean(1)
    return [float(x.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def pct(a, q):
    return float(np.percentile(a, q)) if len(a) else None


PHASES = ("D", "F", "B", "P")
HAND, KITTY, DEAL_CALLS = 25, 8, 100
TRICK_BUCKETS = ((5, "tricks 1-5"), (10, "tricks 6-10"), (15, "tricks 11-15"), (10 ** 9, "tricks 16+"))


def _cards_ok(c):
    return isinstance(c, list) and all(type(x) is str and x for x in c) and c == sorted(c)


def trace_gate(by):
    """Every row's dtrace (exploit_duel_s61.py: [phase, seat, trick, lead, hand, cards] per decision) in the round's exact form, and
    reconciled with the row's other records; a failure refuses.  The form: 100 deal-time declare calls (phase D, hand <= 25), the 4 final
    calls for seats 0..3 (phase F, hand 25), the banker's bury (phase B, the row's banker, a 33-card hand, 8 cards), then the plays (phase
    P) in tricks of 4: a lead (lead True, trick = the previous trick + 1, from 0) then leader+1..3 (lead False, the same trick).  Typed:
    seats ints 0..3, hands ints, cards sorted lists of non-empty strings, trick / lead None off the plays.  Reconciled: the non-empty D / F
    entries equal the row's declares (seat, sorted cards, final); each seat's hand before a play equals 25 minus what it played before
    (a failed throw, listed in failed_throws by play index, plays fewer cards than chosen: the next hand is then only bounded), and every
    hand is empty at the end; per side, the plays equal dhist in count and in the lead flag, and the hand is <= dhist's max hand."""
    for (seed, mirror), r in sorted(by.items()):
        w = f"seed {seed} mirror {mirror}"
        t = r.get("dtrace")
        if not isinstance(t, list) or len(t) < DEAL_CALLS + 5:
            refuse(f"dtrace form: {w}")
        for i, e in enumerate(t):
            ok = (isinstance(e, list) and len(e) == 6 and e[0] in PHASES and type(e[1]) is int and 0 <= e[1] <= 3
                  and type(e[4]) is int and 0 <= e[4] <= HAND + KITTY and _cards_ok(e[5]))
            if ok and e[0] == "P":
                ok = type(e[2]) is int and e[2] >= 0 and type(e[3]) is bool and 1 <= len(e[5]) <= e[4]
            elif ok:
                ok = e[2] is None and e[3] is None
            if not ok:
                refuse(f"dtrace entry form: {w} index {i}: {e!r:.160}")
        phases = "".join(e[0] for e in t)
        n_plays = len(t) - DEAL_CALLS - 5
        if phases[:DEAL_CALLS + 5] != "D" * DEAL_CALLS + "FFFFB" or set(phases[DEAL_CALLS + 5:]) != {"P"} or n_plays % 4:
            refuse(f"dtrace order: {w} (expected {DEAL_CALLS} D, 4 F, 1 B, then plays in tricks of 4; {len(t)} entries)")
        fin, bury, plays = t[DEAL_CALLS:DEAL_CALLS + 4], t[DEAL_CALLS + 4], t[DEAL_CALLS + 5:]
        if [e[1] for e in fin] != [0, 1, 2, 3] or any(e[4] != HAND for e in fin) or any(e[4] > HAND for e in t[:DEAL_CALLS]):
            refuse(f"dtrace declare calls: {w} (final calls for seats 0..3 at hand {HAND}; deal-time hands <= {HAND})")
        if bury[1] != r.get("banker") or bury[4] != HAND + KITTY or len(bury[5]) != KITTY:
            refuse(f"dtrace bury: {w} records seat {bury[1]!r}, hand {bury[4]!r}, {len(bury[5])} cards (banker {r.get('banker')!r}, hand {HAND + KITTY}, {KITTY} cards)")
        decl = r.get("declares")
        if not isinstance(decl, list) or not all(isinstance(d, list) and len(d) == 4 and isinstance(d[1], list) for d in decl):
            refuse(f"declares form: {w}")
        if [[e[1], e[5], e[0] == "F"] for e in t[:DEAL_CALLS + 4] if e[5]] != [[d[0], sorted(d[1]), d[3]] for d in decl]:
            refuse(f"dtrace declares: {w} (the non-empty declare calls differ from the row's declares)")
        ft = r.get("failed_throws")
        if not isinstance(ft, list) or not all(isinstance(f, list) and len(f) == 3 and type(f[0]) is int and 0 <= f[0] < n_plays
                                               and f[1] == plays[f[0]][1] and f[2] is (f[1] % 2 == mirror) for f in ft):
            refuse(f"failed_throws form: {w} (each [play index, its seat, seat on the exploiter team])")
        failed = {f[0] for f in ft}
        lo, hi = {s_: HAND for s_ in range(4)}, {s_: HAND for s_ in range(4)}
        trick, leader = -1, None
        for k, e in enumerate(plays):
            pos, seat = k % 4, e[1]
            if pos == 0:
                if e[3] is not True or e[2] != trick + 1:
                    refuse(f"dtrace tricks: {w} play {k} (a lead of trick {trick + 1} expected, got {e[:5]!r})")
                trick, leader = e[2], seat
            elif e[3] is not False or e[2] != trick or seat != (leader + pos) % 4:
                refuse(f"dtrace tricks: {w} play {k} (seat {(leader + pos) % 4} following trick {trick} expected, got {e[:5]!r})")
            if not lo[seat] <= e[4] <= hi[seat]:
                refuse(f"dtrace hand: {w} play {k} seat {seat} holds {e[4]}, expected {lo[seat]}..{hi[seat]}")
            if k in failed:
                lo[seat], hi[seat] = e[4] - len(e[5]) + 1, e[4] - 1
            else:
                lo[seat] = hi[seat] = e[4] - len(e[5])
        if any(not lo[s_] <= 0 <= hi[s_] for s_ in range(4)):
            refuse(f"dtrace hand: {w} a seat ends with cards in hand ({lo}..{hi})")
        for side in ARMS:
            mine = [e for e in plays if (e[1] % 2 == mirror) == (side == "ex")]
            hist = r["dhist"][side]
            if len(mine) != len(hist) or any(h[LEAD] is not e[3] or not (type(h[MAXH]) is int and h[MAXH] >= e[4]) for e, h in zip(mine, hist)):
                refuse(f"dtrace vs dhist: {w} side {side} ({len(mine)} plays vs {len(hist)} dhist entries, or a lead flag / hand disagrees)")
        history_gate(r, w, bury, plays, failed)


def _strict_submultiset(sub, whole):
    """sub is a non-empty multiset strictly inside whole: every card at most as often as in whole, and fewer cards in total."""
    cs, cw = Counter(sub), Counter(whole)
    return 0 < len(sub) < len(whole) and all(cs[c] <= cw[c] for c in cs)


def history_gate(r, w, bury, plays, failed):
    """s69 runs the producer with --history (the same-root replay fixtures need it; S61's extraction was refused without it): every row
    carries buried (the banker's 8 buried cards = the trace's bury entry, as a multiset), history ([seat, cards actually played] per play,
    one per trace play, the same seat; the same MULTISET of cards, or for a failed throw (failed_throws) a strict sub-multiset of the chosen
    cards) and failed_detail ([play index, seat, attempted, actual], exactly one entry per failed throw: the index a failed play, the seat
    the trace's seat at that play, attempted = the trace's chosen cards and actual = history's cards at that play, each as a multiset).
    Card multiplicity counts throughout (two decks: a card can appear twice).  Anything else refuses."""
    b, hist, fd = r.get("buried"), r.get("history"), r.get("failed_detail")
    if not (isinstance(b, list) and isinstance(hist, list) and isinstance(fd, list)):
        refuse(f"history form: {w} (buried / history / failed_detail missing: the producer ran without --history)")
    if not all(type(c) is str for c in b) or Counter(b) != Counter(bury[5]):
        refuse(f"history buried: {w} buried {sorted(map(str, b))!r:.120} differs from the trace's bury {bury[5]!r:.120}")
    if len(hist) != len(plays):
        refuse(f"history length: {w} {len(hist)} history entries vs {len(plays)} trace plays")
    for k, (h, e) in enumerate(zip(hist, plays)):
        ok = isinstance(h, list) and len(h) == 2 and h[0] == e[1] and isinstance(h[1], list) and all(type(c) is str for c in h[1])
        if ok and k not in failed:
            ok = Counter(h[1]) == Counter(e[5])
        elif ok:
            ok = _strict_submultiset(h[1], e[5])
        if not ok:
            refuse(f"history play: {w} play {k}: history {h!r:.120} vs trace {e[:2] + e[5:]!r:.120}")
    seen = set()
    for f in fd:
        if not (isinstance(f, list) and len(f) == 4 and type(f[0]) is int and isinstance(f[2], list) and isinstance(f[3], list)
                and all(type(c) is str for c in f[2] + f[3])):
            refuse(f"history failed_detail: {w} entry {f!r:.120} is not [play index, seat, attempted, actual]")
        k, seat, att, act = f
        if k in seen or k not in failed:
            refuse(f"history failed_detail: {w} entry index {k} is {'repeated' if k in seen else 'not a failed throw'} (failed_throws {sorted(failed)!r})")
        seen.add(k)
        if seat != plays[k][1]:
            refuse(f"history failed_detail: {w} play {k}: seat {seat!r}, the trace's seat {plays[k][1]}")
        if Counter(att) != Counter(plays[k][5]):
            refuse(f"history failed_detail: {w} play {k}: attempted {att!r:.80} is not the trace's chosen {plays[k][5]!r:.80}")
        if Counter(act) != Counter(hist[k][1]) or not _strict_submultiset(act, att):
            refuse(f"history failed_detail: {w} play {k}: actual {act!r:.80} is not history's {hist[k][1]!r:.80} or not a strict sub-multiset of attempted")
    if seen != set(failed):
        refuse(f"history failed_detail: {w} covers {sorted(seen)!r}, failed_throws {sorted(failed)!r}")


def first_divergence(t0, t1, where):
    """The index of the first entry where the two mirrors' traces differ, or None.  Up to that index both mirrors played the same round
    (the same deal, the same seeds, the same actions), so at that index the same seat acts in the same state, once as the exploiter and
    once as R48: the entries must differ in their cards only (anything else refuses)."""
    for i, (a, b) in enumerate(zip(t0, t1)):
        if a != b:
            if a[:5] != b[:5]:
                refuse(f"divergence form: {where} index {i}: the first differing entries differ in state {a[:5]!r} vs {b[:5]!r}, not only in their cards")
            return i
    if len(t0) != len(t1):
        refuse(f"divergence form: {where}: identical traces of different lengths ({len(t0)} vs {len(t1)})")
    return None


def decision_class(e):
    return {"D": "declare", "F": "declare", "B": "bury"}.get(e[0]) or ("lead" if e[3] else "follow")


def trick_bucket(e):
    return "pre-play" if e[0] != "P" else next(lab for lim, lab in TRICK_BUCKETS if e[2] < lim)


def rank_group(kind, rank):
    if kind == "first":
        return "first round (rank 2)"
    i = RANKS13.index(rank)
    return "fixed 2-6" if i <= 4 else ("fixed 7-10" if i <= 8 else "fixed J-A")


def attribute(by, seeds, seed0, lv):
    """Per deal: its paired margin and its first divergent decision (class, trick bucket, rank group, the acting seat's role, both
    actions).  The exploiter acted in the mirror whose exploiter team holds the seat's parity (mirror m: the exploiter on seats of parity m)."""
    recs = []
    for j, sd in enumerate(seeds):
        r0, r1 = by[(sd, 0)], by[(sd, 1)]
        kind, rank, planned = round_plan(sd - seed0)
        i = first_divergence(r0["dtrace"], r1["dtrace"], f"seed {sd}")
        if i is None:
            recs.append(dict(seed=sd, margin=float(lv[j]), diverged=False))
            continue
        e0, e1 = r0["dtrace"][i], r1["dtrace"][i]
        seat = e0[1]
        if e0[0] in ("B", "P"):
            if r0["banker"] != r1["banker"]:
                refuse(f"divergence form: seed {sd}: the mirrors' bankers differ ({r0['banker']} vs {r1['banker']}) before their first divergence at a {e0[0]} decision")
            role = "banker team" if seat % 2 == r0["banker"] % 2 else "attackers"
        else:
            role = "undecided" if kind == "first" else ("banker team" if seat % 2 == planned % 2 else "attackers")
        exa, r48a = (e0, e1) if seat % 2 == 0 else (e1, e0)
        recs.append(dict(seed=sd, margin=float(lv[j]), diverged=True, index=i, phase=e0[0], seat=seat, trick=e0[2], lead=e0[3], hand=e0[4],
                         cls=decision_class(e0), bucket=trick_bucket(e0), rank_group=rank_group(kind, rank), role=role, kind=kind, rank=rank,
                         exploiter_action=exa[5], r48_action=r48a[5]))
    return recs


KEYS = {
    "class_trick_rank": lambda r: f"{r['cls']} | {r['bucket']} | {r['rank_group']}",
    "class_trick": lambda r: f"{r['cls']} | {r['bucket']}",
    "class": lambda r: r["cls"],
    "rank_group": lambda r: r["rank_group"],
    "role": lambda r: f"{r['cls']} | {r['role']}",
}


def cell_tables(recs, idx):
    """{level: [cell rows]}: per cell, its deals, its contribution (sum of its deals' margins / all deals, levels/round) with the 95% CI
    of the same bootstrap draws as the head-to-head (idx; a draw's contribution = its multiplicity-weighted cell sum / all deals), the mean
    margin within the cell, and its won / lost deals."""
    n = len(recs)
    m = np.array([r["margin"] for r in recs])
    mult = np.zeros(idx.shape)
    np.add.at(mult, (np.arange(idx.shape[0])[:, None], idx), 1.0)   # draw x deal multiplicities
    out, cols, where = {}, [], []
    for level, keyf in KEYS.items():
        groups = {}
        for j, r in enumerate(recs):
            if r["diverged"]:
                groups.setdefault(keyf(r), []).append(j)
        out[level] = []
        for key, members in sorted(groups.items()):
            x = np.zeros(n)
            x[members] = m[members]
            cols.append(x); where.append((level, len(out[level])))
            out[level].append(dict(cell=key, deals=len(members), contribution=float(x.mean()), ci=None,
                                   mean_margin_in_cell=float(m[members].mean()), won=int((m[members] > 0).sum()), lost=int((m[members] < 0).sum())))
    if cols:
        draws = mult @ np.stack(cols, axis=1) / n
        lo_, hi_ = np.percentile(draws, 2.5, axis=0), np.percentile(draws, 97.5, axis=0)
        for k, (level, i) in enumerate(where):
            out[level][i]["ci"] = [float(lo_[k]), float(hi_[k])]
    return out


def top_decile(recs, seeds):
    n = len(recs)
    k = -(-n * int(100 * BAR["top_decile_share"]) // 100)
    order = sorted(range(n), key=lambda j: (-recs[j]["margin"], seeds[j]))
    top = [recs[j] for j in order[:k]]
    cells = {}
    for r in top:
        key = KEYS["class_trick_rank"](r) if r["diverged"] else "(no divergence)"
        c = cells.setdefault(key, dict(deals=0, contribution=0.0))
        c["deals"] += 1
        c["contribution"] += r["margin"] / n
    by_ct = {}
    for r in top:
        if r["diverged"]:
            by_ct[KEYS["class_trick"](r)] = by_ct.get(KEYS["class_trick"](r), 0) + 1
    listed = [{k_: r.get(k_) for k_ in ("seed", "margin", "diverged", "index", "phase", "seat", "trick", "lead", "hand", "cls", "bucket", "rank_group",
                                         "role", "kind", "rank", "exploiter_action", "r48_action")} for r in (recs[j] for j in order[:BAR["top_deals_listed"]])]
    return dict(deals=k, margin_min=top[-1]["margin"] if top else None, contribution=sum(r["margin"] for r in top) / n,
                cells=dict(sorted(cells.items(), key=lambda kv: (-kv[1]["contribution"], kv[0]))), class_trick_counts=dict(sorted(by_ct.items())),
                largest_wins=listed)


def bind(root, status, reservation, *, trusted=TRUSTED):
    """FIRST: reader_lib.bind_inputs (the reserved dispatch paths and the reservation record); then the lane status's exact terminal line
    (no ABORT / REFUSING line; NO_TAIL), its one DEV start line (the launcher's exact text) and its one DEV END rc=0 line, in that order;
    then <root>/duel.jsonl's sha256 against its './duel.jsonl' line in <root>/SHA256SUMS.  Returns the binding and the input path."""
    try:
        b = rl.bind_inputs(root, status, reservation, trusted=trusted)
        t = rl.terminal_line(b["status"], trusted["lane"], TERMINAL, tails=rl.NO_TAIL)
    except rl.ReaderRefusal as e:
        refuse(str(e))
    lines = open(b["status"], encoding="utf-8").read().split("\n")[:-1]
    start = re.compile(rl.TS + " " + re.escape(START))
    end = re.compile(rl.TS + " " + re.escape(f"{LANE} DEV END rc=0 wall_s=") + r"[0-9]+(\.[0-9]+)? maxrss_kb=[0-9]+")
    si = [i for i, line in enumerate(lines) if start.fullmatch(line)]
    ei = [i for i, line in enumerate(lines) if end.fullmatch(line)]
    if len(si) != 1 or len(ei) != 1 or sum(" DEV start" in line for line in lines) != 1 or sum(" DEV END " in line for line in lines) != 1 or not si[0] < ei[0] < t["index"]:
        refuse(f"status: need one DEV start line (the launcher's exact text), then one 'DEV END rc=0' line, before the terminal line (found starts {si}, ends {ei}, terminal {t['index']})")
    rootp = Path(b["root"])
    path, sums = rootp / "duel.jsonl", rootp / "SHA256SUMS"
    if not path.is_file() or path.is_symlink() or not sums.is_file() or sums.is_symlink():
        refuse(f"output root {rootp}: duel.jsonl or SHA256SUMS missing or not a regular file")
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    sraw = sums.read_bytes()
    hit = [line.split() for line in sraw.decode("utf-8").splitlines() if line.endswith("  ./duel.jsonl")]
    if len(hit) != 1 or hit[0][0] != got:
        refuse(f"SHA256SUMS: the input's sha256 {got} is not the lane's single './duel.jsonl' entry ({hit!r:.200})")
    return dict(binding=b, terminal=t["line"], status_sha256=t["status_sha256"], input_sha256=got,
                sums_sha256=hashlib.sha256(sraw).hexdigest()), str(path)


def load_s61_reference(path=None):
    """S61's sealed read (s61dev result.json, archived 2026-10-22), projected to the numbers the comparison lines use; pinned by sha256."""
    path = Path(path) if path else Path(__file__).resolve().parent / "s61_reference.json"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != S61_REFERENCE_SHA256:
        refuse(f"s61_reference.json drift at {path} (expected {S61_REFERENCE_SHA256})")
    return json.loads(raw)


def _se(ci):
    return (ci[1] - ci[0]) / (2 * cr.Z95)


def versus_s61(levels, tables, ref):
    """Comparison lines vs S61 (compare_runs.versus_earlier_run; descriptive): the head-to-head, the class marginals, and every class x trick x
    rank cell S61 reported.  A cell absent in this run counts as contribution 0 with no SE of its own: its line uses S61's SE alone (stated)."""
    lines, rows = [], []
    floor = lambda ci: max(_se(ci), 1e-12) if ci is not None else 1e-12   # a zero-width CI (a cell of all-zero margins) or an absent side: SE ~ 0, stated in the note
    def one(quantity, now_mean, now_ci, then_mean, then_ci, note=""):
        c = cr.versus_earlier_run(quantity, now=(now_mean, floor(now_ci)), earlier=(then_mean, floor(then_ci)),
                                  now_name="S69", earlier_name="S61", digits=4)
        rows.append(dict(quantity=quantity, s69=now_mean, s69_ci=now_ci, s61=then_mean, s61_ci=then_ci, diff=c["diff"], se=c["se"], lo=c["lo"], hi=c["hi"], note=note))
        lines.append(c["line"] + (f" [{note}]" if note else ""))
    one("head-to-head levels/round (S61: its exploiter vs release 46, other deals; SE = 95% CI width / 3.92)", levels[0], levels[1:], ref["levels"][0], ref["levels"][1:])
    for level in ("class", "class_trick_rank"):
        mine = {c["cell"]: c for c in tables[level]}
        for cell in sorted(set(ref["tables"][level]) | set(mine)):
            then = ref["tables"][level].get(cell)
            now = mine.get(cell)
            if then is None:
                one(f"cell contribution [{cell}]", now["contribution"], now["ci"], 0.0, None, note="absent in S61: S61 side taken as 0 with no SE")
            elif now is None:
                one(f"cell contribution [{cell}]", 0.0, None, then["contribution"], then["ci"], note="absent in S69: S69 side taken as 0 with no SE")
            else:
                one(f"cell contribution [{cell}]", now["contribution"], now["ci"], then["contribution"], then["ci"])
    cr.audit_comparison_lines(lines, earlier_names=("S61",))
    return rows, lines


def analyze(root, *, status, reservation, trusted=TRUSTED, seed0=SEED0, deals=DEALS, s61_reference=None):
    bound, path = bind(root, status, reservation, trusted=trusted)
    return analyze_rows(path, bound=bound, seed0=seed0, deals=deals, s61_reference=s61_reference)


def analyze_rows(path, *, bound, seed0=SEED0, deals=DEALS, s61_reference=None):
    """Everything after the binding; analyze() is the lane's entry.  Called directly only on non-lane rows (the local smoke, the host
    rehearsal, the e2e fixture), with bound=None."""
    by, rows = read(path, seed0=seed0, deals=deals)
    trace_gate(by)
    ex, df = exact8_gate(by)
    db = declare_bury_gate(by)
    seeds = sorted({s for s, _ in by})
    lv = np.array([(by[(s, 0)]["ex_levels"] + by[(s, 1)]["ex_levels"]) / 2 for s in seeds])
    pt = np.array([(by[(s, 0)]["ex_attacker_points_signed"] + by[(s, 1)]["ex_attacker_points_signed"]) / 2 for s in seeds])
    out = dict(schema="s69-dev-h2h-read-v1", pinned=PINNED, s61_reference_sha256=S61_REFERENCE_SHA256, lane=LANE, deals=len(seeds), rows=rows, seeds=[seeds[0], seeds[-1]],
               defender=R48, exploiter_base=CAND, plan="r2 per deal (index % 10 in {0, 3, 5, 8} first round at rank 2; else fixed banker, rank RANKS13[index % 13], banker index % 4)",
               input_sha256=hashlib.sha256(open(path, "rb").read()).hexdigest(), binding=bound, bootstrap=dict(reps=BOOT_REPS, seed=BOOT_SEED, unit="deal (mean of its two mirrors)"))
    # validity on BOTH arms, before any outcome (reader_lib/validity.py)
    counts = {side: dict(decisions=t["decisions"], play_fallback=t["fallback"], search=t["search"], belief_fallback=t["belief_fallback"],
                         buries=db[side]["buries"], bury_fallback=db[side]["bury_fallback"], declares=db[side]["declares"],
                         declare_abandon=db[side]["declare_abandoned"]) for side, t in (("ex", ex), ("r45", df))}
    worlds = [((sd, mi, i), side, "search" if h[0] == SEARCH_SCHEMA else "fallback", h[18])
              for (sd, mi), r in sorted(by.items()) for side in ARMS for i, h in enumerate(r["dhist"][side])]
    declares = [dict(where=(sd, mi, side, i), arm=side, evaluated=d[2], worlds=d[3], completed=d[4])
                for (sd, mi), r in sorted(by.items()) for side in ARMS for i, d in enumerate(r["declare_recs"][side])]
    req = va.CORE_OUTCOME_FIELDS + ("kitty_points", "last_trick_winner", "ex_team", "ex_levels", "ex_attacker_points_signed", "ex_role")
    checks = [va.arm_fault_ceilings(counts, BAR["ceilings"], arms=ARMS, tier="DEV"),
              va.worlds_delivered(worlds, PLAY_WORLDS, tier="DEV"),
              va.completion_shape(declares, tier="DEV", expected_worlds_by_arm=DECLARE_WORLDS),
              va.outcome_consistency([(k, r) for k, r in sorted(by.items())], tier="DEV", require=req)]
    v = va.combine(checks, tier="DEV")
    out["validity"] = dict(verdict=v["verdict"], reasons=v["reasons"], checks=v["checks"], detail={c["check"]: c["detail"] for c in checks})
    # reported per side (never a condition): s60dev's tallies and latency
    q4 = lambda a: [pct(a, 50), pct(a, 95), pct(a, 99), max(a) if a else None]
    lat = {}
    for side in ARMS:
        pairs = [(h, x) for r in by.values() for h, x in zip(r["dhist"][side], r["dsecs"][side])]
        lat[side] = dict(decide_play_p50_p95_p99_max=q4([x for _, x in pairs]),
                         decide_play_maxhand8_p50_p95_p99_max=q4([x for h, x in pairs if h[MAXH] == 8]),
                         decide_play_maxhand_gt8_p50_p95_p99_max=q4([x for h, x in pairs if h[MAXH] > 8]),
                         declare_seconds_p50_p99_max=[pct(db[side]["declare_secs"], 50), pct(db[side]["declare_secs"], 99), max(db[side]["declare_secs"], default=None)],
                         bury_seconds_p50_p99_max=[pct(db[side]["bury_secs"], 50), pct(db[side]["bury_secs"], 99), max(db[side]["bury_secs"], default=None)],
                         bury_candidates_p50_max=[pct(db[side]["bury_candidates"], 50), max(db[side]["bury_candidates"], default=None)])
    failed = {"ex": 0, "r45": 0}
    for r in by.values():
        for _, _, is_ex in r["failed_throws"]:
            failed["ex" if is_ex else "r45"] += 1
    lead_elig = ex["d8_lead"] - ex["d8_lead_single_candidate"]
    dbx = {side: {k: v_ for k, v_ in db[side].items() if not k.endswith("_secs") and k != "bury_candidates"} for side in db}
    out["exploiter"] = dict(ex, **lat["ex"], **dbx["ex"], failed_throws=failed["ex"],
                            exact8_rates=dict(lead_complete_share=(ex["d8_lead_complete"] / lead_elig) if lead_elig else None,
                                              follow_complete_share=(ex["d8_follow_complete"] / ex["d8_follow_attempted"]) if ex["d8_follow_attempted"] else None))
    out["defender"] = dict(df, **lat["r45"], **dbx["r45"], failed_throws=failed["r45"])
    e, d = out["exploiter"], out["defender"]
    for side, tt in (("ex", e), ("r45", d)):
        tt["play_worlds_mismatch"] = sum(1 for r in by.values() for h in r["dhist"][side] if h[0] == SEARCH_SCHEMA and h[18] != PLAY_WORLDS[side])
    pc = lambda x: "n/a" if x is None else f"{100 * x:.1f}%"
    ar = ", ".join(f"{k} {v_}" for k, v_ in sorted(ex["abandon_reasons"].items())) or "none"
    lines_common = [
        f"Faults per arm (validity inputs): play fallbacks exploiter {e['fallback']} of {e['decisions']} vs defender {d['fallback']} of {d['decisions']}; belief fallbacks {e['belief_fallback']} of {e['search']} vs {d['belief_fallback']} of {d['search']}; bury fallbacks {e['bury_fallback']} of {e['buries']} vs {d['bury_fallback']} of {d['buries']}; declare abandons {e['declare_abandoned']} of {e['declares']} vs {d['declare_abandoned']} of {d['declares']}; search records off the side's play worlds ({PLAY_WORLDS['ex']} / {PLAY_WORLDS['r45']}) {e['play_worlds_mismatch']} vs {d['play_worlds_mismatch']}.",
        f"Exact stages at max hand 8 (exploiter; reported): leads {ex['d8_lead']} (single-candidate {ex['d8_lead_single_candidate']}), complete {ex['d8_lead_complete']} ({pc(e['exact8_rates']['lead_complete_share'])} of eligible), abandoned {ex['d8_lead_abandoned']}, skipped_budget {ex['d8_lead_skipped_budget']}; follows attempted {ex['d8_follow_attempted']}, complete {ex['d8_follow_complete']} ({pc(e['exact8_rates']['follow_complete_share'])}), abandoned {ex['d8_follow_abandoned']}; reasons: {ar}. <= 7-card lead not complete / follow abandoned: exploiter {ex['le7_lead_not_complete']} / {ex['le7_follow_abandoned']}, defender {df['le7_lead_not_complete']} / {df['le7_follow_abandoned']}.",
        f"Latency on the duel host under its workers (not serving latency): decide_play p50 / p95 / p99 / max exploiter {e['decide_play_p50_p95_p99_max']} vs defender {d['decide_play_p50_p95_p99_max']}; bury s p50 / p99 / max {e['bury_seconds_p50_p99_max']} vs {d['bury_seconds_p50_p99_max']}; declare s {e['declare_seconds_p50_p99_max']} vs {d['declare_seconds_p50_p99_max']}; failed throws exploiter {failed['ex']} vs defender {failed['r45']}.",
        "DEV tier i evidence for the S69 row only: not a strength claim for any servable candidate (the exploiter is R48 at a lifted budget on the duel host and is not servable); no release, deploy, latency or memory claim; the attribution credits each deal's whole margin to its first divergent decision (a locator, not a causal decomposition), and the top-3 cells are chosen by their point estimates (their CIs are not selection-adjusted).",
    ]
    if v["verdict"] != va.VALID:
        out["levels"] = out["points"] = out["attribution"] = None
        out["bar"] = dict(BAR, verdict="DEV_INVALID", reasons=v["reasons"], attribution_status=None, flags=[])
        out["canonical_lines"] = [
            f"s69 DEV head-to-head ({len(seeds)} deals from {seeds[0]}): DEV_INVALID, no outcome computed. Validity (validity.py, both arms): {'; '.join(v['reasons'][:6])}.",
        ] + lines_common
        return out
    # the outcome: the head-to-head margin, then the attribution
    out["levels"] = boot(lv)
    out["points"] = boot(pt)
    out["nonzero_share"] = float((lv != 0).mean())
    m, lo, hi = out["levels"]
    verdict = "EXPLOITER_AHEAD" if lo > BAR["ahead_ci_lower_above"] else ("DEFENDER_AHEAD" if hi < BAR["behind_ci_upper_below"] else "NO_RESOLVED_GAP")
    kinds = {sd: round_plan(sd - seed0) for sd in seeds}
    out["split_descriptive"] = {
        "first_round": boot([lv[i] for i, sd in enumerate(seeds) if kinds[sd][0] == "first"]),
        "fixed_banker": boot([lv[i] for i, sd in enumerate(seeds) if kinds[sd][0] != "first"]),
        "note": "descriptive only; never the read"}
    for role in ("banker", "attacker"):
        g = [by[(sd, mi)]["ex_levels"] for sd in seeds for mi in (0, 1) if by[(sd, mi)]["ex_role"] == role]
        out[f"games_{role}"] = {"n": len(g), "mean": boot(g)}
    recs = attribute(by, seeds, seed0, lv)
    idx = np.random.default_rng(BOOT_SEED).integers(0, len(lv), size=(BOOT_REPS, len(lv)))   # the head-to-head's own draws (boot)
    undiverged = [r for r in recs if not r["diverged"]]
    bad = [r["seed"] for r in undiverged if r["margin"] != 0]
    status_a = "ATTRIBUTION_INVALID" if bad else "ATTRIBUTION_OK"
    out["attribution"] = dict(status=status_a, deals_diverged=len(recs) - len(undiverged), deals_not_diverged=len(undiverged),
                              not_diverged_nonzero_seeds=bad[:20], not_diverged_nonzero=len(bad),
                              definition="first divergent decision between the two mirrors (first_divergence); a cell's contribution = its deals' margin sum / all deals")
    out["bar"] = dict(BAR, verdict=verdict, reasons=[], attribution_status=status_a, flags=[])
    if bad:
        out["canonical_lines"] = [
            f"s69 DEV head-to-head (paired, seat-swapped, r2 plan per deal, {len(seeds)} deals from {seeds[0]}): the S69 exploiter minus R48 as served = {m:+.4f} levels/round, 95% CI [{lo:+.4f}, {hi:+.4f}] (deal bootstrap {BOOT_REPS}); points {out['points'][0]:+.2f} [{out['points'][1]:+.2f}, {out['points'][2]:+.2f}]; nonzero share {out['nonzero_share']:.3f}.",
            f"Read (predeclared): validity VALID on both arms; EXPLOITER_AHEAD iff CI lower > 0, DEFENDER_AHEAD iff CI upper < 0, else NO_RESOLVED_GAP.  Verdict {verdict}.  Attribution {status_a} ({out['attribution']['deals_diverged']} deals diverged, {len(undiverged)} never diverged, {len(bad)} of those with a nonzero margin); attribution findings suppressed.",
            f"Split (descriptive): first-round deals {out['split_descriptive']['first_round']}, fixed-banker deals {out['split_descriptive']['fixed_banker']}; exploiter games as banker {out['games_banker']['mean']}, as attacker {out['games_attacker']['mean']}.",
        ] + lines_common
        return out
    tables = cell_tables(recs, idx)
    joint = tables["class_trick_rank"]
    losses = sorted([c for c in joint if c["contribution"] > 0], key=lambda c: (-c["contribution"], c["cell"]))[:BAR["top_k"]]
    gains = sorted([c for c in joint if c["contribution"] < 0], key=lambda c: (c["contribution"], c["cell"]))[:BAR["top_k"]]
    flags = [dict(level=level, cell=c["cell"], contribution=c["contribution"], ci=c["ci"], deals=c["deals"], resolved=c["ci"][0] > 0)
             for level in ("class_trick_rank", "class_trick") for c in tables[level] if c["contribution"] >= BAR["flag_min_contribution"]]
    out["bar"]["flags"] = flags
    total = sum(c["contribution"] for c in tables["class"])
    out["attribution"].update(cells_sum=total, top_loss_cells=losses, top_gain_cells=gains, tables=tables, top_decile=top_decile(recs, seeds))
    fmt = lambda c: f"{c['cell']}: {c['contribution']:+.4f} [{c['ci'][0]:+.4f}, {c['ci'][1]:+.4f}] ({c['deals']} deals, won {c['won']} lost {c['lost']})"
    ct = ", ".join(f"{c['cell']} {c['contribution']:+.4f}" for c in sorted(tables["class_trick"], key=lambda c: -c["contribution"]))
    td = out["attribution"]["top_decile"]
    out["canonical_lines"] = [
        f"s69 DEV head-to-head (paired, seat-swapped, r2 plan per deal, {len(seeds)} deals from {seeds[0]}): the S69 exploiter minus R48 as served = {m:+.4f} levels/round, 95% CI [{lo:+.4f}, {hi:+.4f}] (deal bootstrap {BOOT_REPS}); points {out['points'][0]:+.2f} [{out['points'][1]:+.2f}, {out['points'][2]:+.2f}]; nonzero share {out['nonzero_share']:.3f}.",
        f"Read (predeclared): validity VALID on both arms; EXPLOITER_AHEAD iff CI lower > 0, DEFENDER_AHEAD iff CI upper < 0, else NO_RESOLVED_GAP.  Verdict {verdict}.  Attribution {status_a} ({out['attribution']['deals_diverged']} deals diverged, {len(undiverged)} never diverged, {len(bad)} of those with a nonzero margin; cells sum {total:+.4f}).",
        "Top-3 loss cells (R48's largest losses; class | trick | rank group, levels/round): " + ("; ".join(fmt(c) for c in losses) or "none positive") + ".",
        f"Flag (contribution >= {BAR['flag_min_contribution']:+.3f}, each a candidate row): " + ("; ".join(f"[{f_['level']}] {f_['cell']} {f_['contribution']:+.4f} [{f_['ci'][0]:+.4f}, {f_['ci'][1]:+.4f}]{' resolved' if f_['resolved'] else ''}" for f_ in flags) or "none") + ".",
        f"Class x trick (contributions): {ct}.  Top-3 gain cells (R48 ahead): " + ("; ".join(fmt(c) for c in gains) or "none negative") + ".",
        f"Top decile ({td['deals']} deals, margin >= {td['margin_min']}): contribution {td['contribution']:+.4f}; by class x trick {td['class_trick_counts']}.",
        f"Split (descriptive): first-round deals {out['split_descriptive']['first_round']}, fixed-banker deals {out['split_descriptive']['fixed_banker']}; exploiter games as banker {out['games_banker']['mean']}, as attacker {out['games_attacker']['mean']}.",
    ] + lines_common
    ref = load_s61_reference(s61_reference)
    rows_cmp, lines_cmp = versus_s61(out["levels"], tables, ref)
    out["versus_s61"] = dict(reference_sha256=S61_REFERENCE_SHA256, source=ref.get("source"), caveat=cr.CAVEAT, rows=rows_cmp)
    out["canonical_lines"] += lines_cmp
    cr.audit_comparison_lines(out["canonical_lines"], earlier_names=("S61",))   # every line naming S61 is a versus_earlier_run line; no equality wording
    return out


def check_imports():
    """The staging preflight: the pinned helpers load from beside this file at their shas, and so does the S61 reference."""
    ref = load_s61_reference()
    print(f"imports ok: {sorted(PINNED)} at their pinned sha256 from {LIB_DIRS[0]}; s61_reference {S61_REFERENCE_SHA256[:12]} ({len(ref['tables']['class_trick_rank'])} S61 cells)")


def main(argv):
    if argv == ["--check-imports"]:
        check_imports()
        return
    if len(argv) != 4:
        raise SystemExit(__doc__)
    out = analyze(argv[0], status=argv[1], reservation=argv[2])
    with open(argv[3], "x") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
        fh.write("\n")
    for line in out["canonical_lines"]:
        print(line)


if __name__ == "__main__":
    main(sys.argv[1:])
