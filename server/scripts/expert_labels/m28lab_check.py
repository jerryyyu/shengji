#!/usr/bin/env python3
"""m28lab_check.py (r2) -- the VALIDITY checker of the m28lab rows (board row M28, stage 1 of step 1b; the lane's launcher is
claude_m28lab_cloud.sh).  Not a strength reader: it reads no outcome, computes no bar and writes no claim about the policy head.  The rows
are the product; this file says whether they are the rows the launcher promised.  Every check below refuses or reads INVALID BEFORE anything
is reported.

Binding (reader_lib, the reviewed h1a / S66 library, FIRST).  `reader_lib.bind_inputs(root, status, reservation, trusted=TRUSTED)`: in HOST
mode the three paths must be canonical (a symlink component refuses before any normalization) and EQUAL to the reserved dispatch paths, and
the reservation record must bind this lane, launcher sha, status and output root; in ARCHIVE mode (`--manifest host_manifest.json
--manifest-sha256 <sha printed on the host by make_host_manifest.py>`) the copies sit beside the manifest under the dispatch basenames and
reproduce its file set and every hash.  Then `reader_lib.terminal_line` (exactly one terminal LANE DONE line, nothing after it, no ABORT: /
REFUSING: anywhere), then this lane's status lines (the armed line with the trusted launcher sha, an optional resume line whose previous
status is preserved under the root with the named sha, one DEV start and one DEV END rc=0 per phase fullmatching the launcher's texts, the
SHA256SUMS line naming the sealed file) -- all before any dataset file is opened.  There is no permissive copy switch.

Identity (refuses).  summary.json and every shard header carry the pinned schema, probe_rev, lifted block, names, envs (no test override),
worlds 64 / 256, cap 60, knobs, record_capsule, units, encoder v2 x 833, SHENGJI_FAST=1, the play and belief package shas, the producer's and
the harness's source sha256; every shard's window is its slice.  Every completed shard directory carries its manifest (binding equal to the
phase's, every file listed with its sha256 and present, counts equal to its end row); no `.partial` directory remains; `diag/` entries exist
only under a resumed attempt.

Coverage and schema (refuses).  Every deal of the window has one deal_done row; every decision of every deal has exactly one record at indices
0..n-1; the deal row's labelled list, drop count and self-row count equal the rows'; every row's required fields have the required types;
every deal row's declare records and bury record have the configured shapes (row_schema).

Validity (INVALID before any report):
- validity.arm_fault_ceilings on live / served / expert with ONE ceilings mapping: play fallback (a non-search record; for the expert a dropped
  decision) <= 2 % of decisions, belief fallback 0 of SEARCH records (a fallback record carries no belief draw: r2b, after the r2 read counted
  the budget-dropped expert records as belief fallbacks too); validity.worlds_delivered 64 / 64 / 256 on every search record;
- the GENERATING decisions (r2): validity.arm_fault_ceilings on the live bots' declare and bury records (the only arm that declares and
  buries): declare_abandon (a declare record with a fallback reason) <= 0 % of declares, bury_fallback (a fallback bury record) <= 0 % of deals
  -- lifted bots have no clock to abandon on; validity.completion_shape on every declare record (evaluated => all 64 worlds completed; the
  configured 64 pinned); an evaluated declare short of its worlds or a bad-schema fallback is a fault, never n/a;
- the lifted contract on every live and served record (caps == LIFTED_CAPS, h1a r3a's stage_faults); the expert's declared caps (its abandoned
  stages reported); the world-pairing digest on every labelled decision;
- the training rows: rows_expert / rows_self of every shard load through `open_policy_rows`, one to one with the kept decisions / the
  self-flagged live rows by (deal, index), taken in the ballot, means / prior_lo ballot-long and finite, Y the multi-hot, X 833, units pinned,
  deal keys the deal rows', tags well-formed;
- the replay capsule (r2, record_capsule phases): one capsule per kept decision, its served record and worlds digest the decision's, its deck
  the deal key's, its snapshot at the decision's seat; and a SAMPLE of capsules per shard (--replay-per-shard, >= 1 on the real lane) is
  replayed through the REAL served path (a fresh registry bot, the recorded worlds injected: expert_label_probe.replay_capsule) and must
  reproduce the recorded ballot, pick, indices, worlds and digest exactly and the means / prior log-odds within REPLAY_ATOL (1e-9: exact
  on the producing host, last-ulp differences on another host; the maximum difference is reported);
- row floors per phase (TRAIN kept lead labels >= 16,000 over >= 1,500 deals; HELD-OUT >= 5,000 over >= 250). `--no-floors` is refused on the
  real lane (the bench copy's floors are 0 and its result says bench).

Reported (no claim): counts per phase, labels per deal, drops by reason, expert stages, the action-type shares (HELD-OUT: the tag the design
reads), in-ballot and rank shares, expert wall-time quantiles, per-shard wall; the deal-key EXPOSURE of each phase is written beside the result
(`<out>.exposure.json`) for the trained package's checkpoint lineage.

Off-ballot served moves (profile `y`).  Y's lead confirmation (lcc32) replaces the base winner by a challenger priced on fresh worlds, so
the challenger rides in the recorded ballot with no base-pass mean and `selected_action` finds no ballot selection: the served arm's `cards`
is None, the expert row's `served_taken` is None and the move is in `played`.  Such a decision is a VALID label row: the expert's label
(its move, ballot and means) is unaffected and the served comparison is the played move (`served_comparison`: taken = played,
off_ballot True).  The live seat's decision has no self row (the producer writes no X for it) and is counted in the deal row's
`self_skipped`.  The checker counts both per rule (`off_ballot` in the phase report); a served search record without a ballot selection
under no registered rule, a `self_skipped` count that is not the live rows skipped under a rule, or an expert row whose `served_taken`
is not the served selection reads INVALID.  The R48 profile registers no rule, so any such record is INVALID there.  A replayed
capsule's means and prior log-odds must hold None on the same slots and agree within REPLAY_ATOL elsewhere.

Rows-only mode (`rows`): the identity, coverage, schema, validity and rows checks above on a phase directory without the lane binding
(status, reservation and root seal belong to the lane's own packet); each shard's files are checked against its own manifest.
`--subset N` checks shards 0..N-1 of a larger or unfinished phase: summary.json and the row floors are then not read.

Usage (cwd the tree's server/, FIND_GAPS_* as the launcher sets them; torch for the loader):
  python3 m28lab_check.py <root> <status> <reservation> <out.json> [--manifest host_manifest.json --manifest-sha256 HEX]
                          [--lane m28lab|m28labbench --launcher-sha SHA] [--replay-per-shard N]
  python3 m28lab_check.py rows <root> <out.json> --profile r48|y --phase NAME=SEED0,DEALS,SHARDS,LATE_LEAD_P,FOLLOW_P,CAPSULE [--phase ...]
                          [--subset N] [--replay-per-shard N]"""
import argparse
import gzip
import hashlib
import importlib.util
import json
import math
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import reader_lib as rl  # noqa: E402
import row_schema as rs  # noqa: E402
import validity as va  # noqa: E402

LANE = 'm28lab'
REV = 'r2'
HOST = 'shengji-cloud'
TRUSTED = dict(lane=LANE, launcher_sha256='64fb200fe1a3b401ab262172fb2d05810cff9361e454f539c36593c895b06b80', host=HOST, root='/root/vol-dev-claude-m28lab-r2-r48-20261025',
               status='/root/claude_m28lab_r2_screen.status', reservation='/root/claude_reservations/m28lab_r2.json')
POLICY_TEXT = 'R48 recipe under lifted budgets with internal wall deadlines removed'
SERVED_NAME = 'pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-rc252e656-bury-hybrid-bwv-cd6dd3d2b02a'
EXPERT_NAME = 'pv-search-491ee4bf-w256-k32-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-ed8-els9000-edn200000000-xf8-xfcompactlevel-rf46b9754-bury-hybrid-bwv-63b7cb149669'
EXPERT_ENV = [['SHENGJI_PV_CANDIDATES', '32'], ['SHENGJI_PV_EXACT_DEEP_CARDS', '8'], ['SHENGJI_PV_EXACT_DEEP_MAX_NODES', '200000000'],
              ['SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS', '8'], ['SHENGJI_PV_EXACT_FOLLOW_MAX_NODES', '200000000'],
              ['SHENGJI_PV_EXACT_LEAD_MAX_SECONDS', '9.0'], ['SHENGJI_PV_LEAF_GREEDY_DEADLINE', ''], ['SHENGJI_PV_WORLDS', '256']]
LIFTED = {'serving_budget_seconds': None, 'bury_serving_budget_seconds': None, 'leaf_greedy_deadline_ms': 0, 'exact_lead_max_seconds': 86400.0, 'belief_prep_seconds': 'inf'}
LIFTED_CAPS = {'serving_budget_seconds': None, 'leaf_greedy_deadline_ms': 0, 'exact_lead_max_seconds': 86400.0, 'belief_prep_seconds': 'inf'}
EXPERT_CAPS = {'serving_budget_seconds': 60.0, 'leaf_greedy_deadline_ms': 0, 'exact_lead_max_seconds': 9.0, 'belief_prep_seconds': 'inf'}
PV_SHA = '491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670'
BELIEF_SHA = '424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e'
PROBE_SHA = 'cbaa075f8974f5c5fa64d3e7dbc5d6616bf3f8a818a7dc1d2917d8e371e5f63f'            # the producer's source sha256 (= the launcher's PROBE_SHA; every header and shard manifest carries it)
HARNESS_SHA = 'b15d292f564f2643e35d50e07584cecab839b1e61f9890bc31dc8363f495ceec'
PINS = dict(schema='m28lab-v2', probe_rev=REV, lifted=LIFTED, lifted_caps=LIFTED_CAPS, expert_caps=EXPERT_CAPS, rows_units='value-head-levels',
            enc_version=2, input_dim=833, served_worlds=64, expert_worlds=256, declare_worlds=64, served_name=SERVED_NAME, expert_name=EXPERT_NAME,
            served_env=[], expert_env=sorted(EXPERT_ENV), expert_cap_secs=60.0, late_trick=12, plan='r2', workers=12, pv_sha256=PV_SHA, belief_sha256=BELIEF_SHA,
            source_sha256=PROBE_SHA, harness_sha256=HARNESS_SHA, capsule_schema='m28lab-capsule-v3', shard_manifest_schema='m28lab-shard-manifest-v2',
            phases={'train': dict(seed0=272180910, deals=1608, shards=134, late_lead_prob=0.3333, prob_follow=0.14, record_capsule=False),
                    'heldout': dict(seed0=272190910, deals=360, shards=36, late_lead_prob=1.0, prob_follow=0.20, record_capsule=True)})
BENCH_PHASES = {'train': dict(seed0=272090000, deals=24, shards=24, late_lead_prob=0.3333, prob_follow=0.14, record_capsule=False),
                'heldout': dict(seed0=272090100, deals=12, shards=12, late_lead_prob=1.0, prob_follow=0.20, record_capsule=True)}
#: one ceilings mapping on every PLAY arm (play / belief), one on the GENERATING arm (declare / bury: the live bots), the row floors per phase
BAR = dict(play_ceilings=dict(play_fallback=0.02, belief_fallback=0.0, bury_fallback=None, declare_abandon=None),
           generating_ceilings=dict(play_fallback=None, belief_fallback=None, bury_fallback=0.0, declare_abandon=0.0),
           floors={'train': dict(kept_leads_min=16000, deals_min=1500), 'heldout': dict(kept_leads_min=5000, deals_min=250)})
ARMS = ('live', 'served', 'expert')
RECORD_SCHEMA = 'pv-search-decision-v1'
FALLBACK_SCHEMA = 'pv-search-fallback-v1'
DECLARE_SCHEMA = 'pv-value-declare-decision-v1'
BURY_SCHEMA, BURY_FALLBACK = 'cwv-bury-policy-v1', 'cwv-bury-fallback-v1'
ACTION_TYPES = ('single', 'pair', 'tractor', 'throw')
REPLAY_ATOL = 1e-9     # means / prior log-odds of a replayed capsule: exact on the producing host; last-ulp (~1e-15) differences on another host
NUM0 = rs.number_at_least(0)
INT_OR_NULL = rs.Spec('INT_OR_NULL', lambda v: v is None or (type(v) is int))
#: the live bots' declare record [schema, fallback_reason, evaluated, worlds, worlds_completed, seconds] and bury record
#: [schema, fallback_reason, candidate_count, model_worlds] (h1a's shapes, type-strict)
DECLARE_SHAPES = {'declare evaluated': {0: rs.one_of(DECLARE_SCHEMA), 1: rs.NULL, 2: rs.one_of(True), 3: rs.int_in(1, 4096), 4: rs.int_in(0, 4096), 5: NUM0},
                  'declare abandoned': {0: rs.one_of(DECLARE_SCHEMA), 1: rs.Spec('nonempty str', lambda v: isinstance(v, str) and v != ''), 2: rs.one_of(False), 3: rs.int_in(1, 4096), 4: rs.int_in(0, 4096), 5: NUM0}}
BURY_SHAPES = {'bury model': {0: rs.one_of(BURY_SCHEMA), 1: rs.NULL, 2: rs.int_in(1, 10**6), 3: rs.int_in(1, 4096)},
               'bury fallback': {0: rs.one_of(BURY_FALLBACK), 1: rs.Spec('nonempty str', lambda v: isinstance(v, str) and v != ''), 2: INT_OR_NULL, 3: rs.NULL}}
#: the served-arm rules under which a search record's played move is the recorded ballot's unpriced slot (the module docstring)
OFF_BALLOT_RULES = {'lcc_applied': lambda rec: rec.get('lead_confirm_status') == 'applied' and rec.get('lead_confirm_applied') is True}
#: release 49 (Y = R48 + sc8 + lcc32) as the served arm, through the producer the Y label lanes ran; the expert is M28's.  The Y lanes bind
#: their own status and output paths, so a Y check runs in rows-only mode with the phase windows given on the command line.
Y_SERVED_NAME = 'pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-lcc32-r9f8f5c05-bury-hybrid-bwv-d12d7acfc860-sc8'
Y_PINS = dict(PINS, served_name=Y_SERVED_NAME, expert_env=sorted(EXPERT_ENV + [['SHENGJI_PV_LEAD_CONFIRM', ''], ['SHENGJI_PV_SINGLETON_CHALLENGER', '']]),
              source_sha256='d38bb1d20a2f19de7aa9a25696bc220347a88bcd674d8e5279da4dd8023443ae', harness_sha256='96954d5fee94d6f7d99925c94bc88a8f0faa0d80cad2650df8de995798309af7',
              served_base_sha256='d67f6b9d999493f3442be32eff757ab9eb8876380f3b63a5de73096a2cc72e36', workers=None, phases={},
              off_ballot_rules=('lcc_applied',), phase_extras=r'drive_summary\.[0-9TZ-]+\.\d+\.json')
PROFILES = {'r48': PINS, 'y': Y_PINS}


def terminal(pins):
    t, h = pins['phases']['train'], pins['phases']['heldout']
    return (f"DEV output sealed (train {t['shards']} shards x {t['deals'] // t['shards']} deals; heldout {h['shards']} shards x {h['deals'] // h['shards']} deals); "
            f"rows only, validity is checker-owned, no outcome is read at this stage; LANE DONE")


class CheckRefusal(rl.ReaderRefusal):
    """An input the checker will not read: identity, coverage or schema (binding refusals come from reader_lib as ReaderRefusal)."""


def refuse(msg):
    raise CheckRefusal(f'REFUSING: {msg}')


def q(xs, p):
    xs = sorted(xs)
    return None if not xs else xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]


def stage_faults(rec, lifted=True):
    """h1a r3a: on a lifted R48 record the runtime emits the greedy-deadline fields only when that stage is armed and an abandon reason only when
    the exact-lead stage was abandoned, so their presence (a False, a 0) is a fault against the lifted contract; on the expert (its declared
    caps) fired / abandoned stages are reported."""
    out = []
    if rec.get('exact_lead_status') in ('abandoned', 'skipped_budget'):
        out.append(f"exact_lead_{rec['exact_lead_status']}")
    if lifted:
        for k in ('exact_lead_abandon_reason', 'lgf_deadline_fired', 'lgf_deadline_cut_leaves'):
            if rec.get(k) is not None:
                out.append(f'{k}_present')
    elif rec.get('lgf_deadline_fired') is True:
        out.append('lgf_deadline_fired')
    for k in ('exact_follow_abandoned', 'tiebreak_abandoned', 'reselect_abandoned'):
        if rec.get(k) is not None:
            out.append(k)
    return out


def off_ballot_reason(rec, rules):
    """The registered rule (of ``rules``) a search record satisfies, else None."""
    if rec.get('schema') != RECORD_SCHEMA:
        return None
    return next((r for r in rules if OFF_BALLOT_RULES[r](rec)), None)


def served_comparison(served, rules=()):
    """(taken, off_ballot, reason) of a labelled decision's served arm record: its ballot selection (reason None); under a registered
    off-ballot rule the played move, which must be the selected ballot slot, the only one without a finite mean (off_ballot True, the rule);
    a fallback record (None, False, 'fallback'); any other record without a selection (None, False, 'unexplained').  A consumer that
    compares the expert with the served arm reads the served move through this, not through the expert row's ``served_taken``."""
    if served.get('cards') is not None:
        return served['cards'], False, None
    if served.get('schema') != RECORD_SCHEMA:
        return None, False, 'fallback'
    reason = off_ballot_reason(served, rules)
    adm, idx, sel, means = served.get('admitted') or [], served.get('admitted_indices') or [], served.get('selected_index'), served.get('value_means') or []
    if reason is None or not isinstance(served.get('played'), list) or len(adm) < 2 or len(adm) != len(idx) or len(means) != len(adm) or sel not in idx:
        return None, False, 'unexplained'
    slot = idx.index(sel)
    if sorted(adm[slot]) != sorted(served['played']) or means[slot] is not None \
            or any(m is None or not math.isfinite(float(m)) for j, m in enumerate(means) if j != slot):
        return None, False, 'unexplained'
    return served['played'], True, reason


def served_taken_matches(meta, served, rules, card_index):
    """(ok, off_ballot) of an expert row's ``served_taken`` against its decision's served record: the served selection's card indices,
    or None when the decision has no selection (off the ballot under a rule, or a fallback)."""
    taken, off, _ = served_comparison(served, rules)
    want = None if off or taken is None else sorted(card_index[c] for c in taken)
    got = meta.get('served_taken')
    return (sorted(got) if isinstance(got, list) else got) == want, off


def slot_diff(got, want):
    """The largest |got - want| over a replayed listing's slots; inf when the lengths differ or a None (an unpriced slot) is not matched."""
    got, want = got or [], want or []
    if len(got) != len(want) or any((x is None) != (y is None) for x, y in zip(got, want)):
        return float('inf')
    return max((abs(float(x) - float(y)) for x, y in zip(got, want) if x is not None), default=0.0)


def worlds_digest(worlds):
    h = hashlib.sha256()
    for hands, buried in worlds:
        h.update(json.dumps([[sorted(x) for x in hands], sorted(buried)]).encode())
    return h.hexdigest()


# ------------------------------------------------------------------ status (after reader_lib's binding and terminal)

def check_status(status_path, trusted, pins, root):
    """The launcher's status, line for line: one armed line with the trusted sha; at most one resume line, whose previous status exists under
    the root with the named sha; one DEV start and one DEV END rc=0 per phase; the SHA256SUMS line (returned for the sums check)."""
    lane = re.escape(trusted['lane'])
    m_rev = re.fullmatch(rf'claude_{lane}_([a-z0-9]+)_screen\.status', os.path.basename(trusted['status']))   # the revision suffix of the reserved status: the launcher's REV
    if not m_rev:
        refuse(f'the trusted status {trusted["status"]} is not claude_<lane>_<rev>_screen.status')
    rev = m_rev.group(1)
    lines = open(status_path, 'rb').read().decode('utf-8')[:-1].split('\n')
    armed = [l for l in lines if re.fullmatch(rf'{rl.TS} {lane} armed \(pid \d+, launcher sha256 ([0-9a-f]{{64}})\): tree /root/claude-main-55 0c1e9965d2bba674eb8dd589365776ae94a3f1c8; waiting for the RELEASE token /root/claude_{lane}_{rev}\.RELEASE, then the host lock', l)]
    if len(armed) != 1:
        refuse(f'{len(armed)} armed lines (want one)')
    got = re.search(r'launcher sha256 ([0-9a-f]{64})', armed[0]).group(1)
    if got != trusted['launcher_sha256']:
        refuse(f'the armed line names launcher sha {got}, the trusted one is {trusted["launcher_sha256"]}')
    res = [re.fullmatch(rf'{rl.TS} {lane} resume attempt (\d+): previous status moved to {re.escape(trusted["root"])}/diag/(status\.attempt\d+) \(sha256 ([0-9a-f]{{64}})\); token /root/claude_{lane}_{rev}\.RESUME\.\d+', l) for l in lines]
    res = [m for m in res if m]
    if len(res) > 1:
        refuse(f'{len(res)} resume lines (at most one per status: each attempt has its own status file)')
    resumed = None
    if res:
        n, prev, sha = int(res[0].group(1)), res[0].group(2), res[0].group(3)
        if prev != f'status.attempt{n - 1}':
            refuse(f'the resume line of attempt {n} names {prev}, not status.attempt{n - 1}')
        p = os.path.join(root, 'diag', prev)
        if not os.path.isfile(p) or os.path.islink(p) or rl.sha256_file(p) != sha:
            refuse(f'the previous status {p} named by the resume line is missing, a symlink or not sha256 {sha[:12]}')
        resumed = dict(attempt=n, previous_status=f'diag/{prev}', sha256=sha)
    ph = pins['phases']
    for name, p in ph.items():
        extra = ', --record-capsule' if p['record_capsule'] else ''
        tail = r'(; RESUME attempt \d+ \(--resume: completed shards verified and skipped\))?' if resumed else ''
        num = lambda x: re.escape(str(x)) + '0*'      # the launcher prints its constant's literal (0.20), the pin is a float (0.2): trailing zeros allowed
        start = (rf'{rl.TS} {lane} DEV start \[{name}\]: served {re.escape(pins["served_name"])} \({re.escape(POLICY_TEXT)}\) vs expert {re.escape(pins["expert_name"])} '
                 rf'\(cap {pins["expert_cap_secs"]:g} s\); deals {p["deals"]} seed0 {p["seed0"]} plan {pins["plan"]} in {p["shards"]} shards; labels: leads before trick {pins["late_trick"]} all, '
                 rf'late leads p {num(p["late_lead_prob"])}, follows p {num(p["prob_follow"])}{re.escape(extra)}; workers {pins["workers"]}; group KILL at \d+ s \(backstop \d+ s\){tail}')
        if sum(1 for l in lines if re.fullmatch(start, l)) != 1:
            refuse(f'DEV start [{name}] line absent or not the launcher text (names, policy text, window, shards, knobs)')
        ends = [l for l in lines if re.fullmatch(rf'{rl.TS} {lane} DEV END \[{name}\] rc=(\d+) wall_s=[0-9.]+ maxrss_kb=\d+', l)]
        if len(ends) != 1 or re.search(r'rc=(\d+)', ends[0]).group(1) != '0':
            refuse(f'DEV END [{name}] rc=0 line absent (found {ends})')
    sums = [l for l in lines if re.fullmatch(rf'{rl.TS} {lane} SHA256SUMS ([0-9a-f]{{64}}) \((\d+) files\)', l)]
    if len(sums) != 1:
        refuse('SHA256SUMS status line absent')
    m = re.search(r'SHA256SUMS ([0-9a-f]{64}) \((\d+) files\)', sums[0])
    return dict(armed_sha=got, rev=rev, resumed=resumed, sums_sha256=m.group(1), n_files=int(m.group(2)), lines=len(lines))


def check_sums(root, said):
    """Every regular file under the root is in SHA256SUMS with its sha (the seal the launcher wrote); the status names that file."""
    sums_path = os.path.join(root, 'SHA256SUMS')
    if not os.path.isfile(sums_path):
        refuse(f'{sums_path} missing: the output is not sealed')
    if rl.sha256_file(sums_path) != said['sums_sha256']:
        refuse(f'the status names SHA256SUMS {said["sums_sha256"][:12]}; the sealed file is {rl.sha256_file(sums_path)[:12]}')
    listed = {}
    for line in open(sums_path):
        line = line.rstrip('\n')
        if not line:
            continue
        m = re.fullmatch(r'([0-9a-f]{64}) [ *](.+)', line)
        if not m:
            refuse(f'malformed SHA256SUMS line: {line!r}')
        listed[os.path.normpath(m.group(2))] = m.group(1)
    if len(listed) != said['n_files']:
        refuse(f'SHA256SUMS lists {len(listed)} files, the status says {said["n_files"]}')
    on_disk = {}
    for here, _, names in os.walk(root):
        for n in names:
            p = os.path.join(here, n)
            if n != 'SHA256SUMS':
                on_disk[os.path.normpath(os.path.relpath(p, root))] = p
    if set(listed) != set(on_disk):
        refuse(f'SHA256SUMS lists {len(listed)} files, the root holds {len(on_disk)}: extra {sorted(set(on_disk) - set(listed))[:3]}, missing {sorted(set(listed) - set(on_disk))[:3]}')
    bad = [rel for rel, p in sorted(on_disk.items()) if rl.sha256_file(p) != listed[rel]]
    if bad:
        refuse(f'{len(bad)} file(s) differ from SHA256SUMS: {bad[:3]}')
    return listed


# ------------------------------------------------------------------ rows

def _t(x, kinds):
    return isinstance(x, kinds) and not (isinstance(x, bool) and bool not in (kinds if isinstance(kinds, tuple) else (kinds,)))


def check_record(rec, where):
    """A search or fallback record's shape (type-strict on the fields the guards read)."""
    for k in ('schema', 'worlds', 'belief_fallback', 'caps'):
        if k not in rec:
            refuse(f'{where}: record without {k}')
    if rec['schema'] not in (RECORD_SCHEMA, FALLBACK_SCHEMA):
        refuse(f'{where}: record schema {rec["schema"]!r}')
    if not isinstance(rec['caps'], dict):
        refuse(f'{where}: caps not a mapping')
    if rec['schema'] == RECORD_SCHEMA:
        if not _t(rec['worlds'], int):
            refuse(f'{where}: a search record without an integer world count (delivery unproven)')
        if not _t(rec.get('exact_lead_status'), str) and rec.get('exact_lead_status') is not None:
            refuse(f'{where}: exact_lead_status of the wrong type')


def load_phase(root, name, p, pins, listed, subset=None):
    per = p['deals'] // p['shards']
    pdir = os.path.join(root, name)
    if not os.path.isdir(pdir):
        refuse(f'{name}/ missing')
    entries = sorted(os.listdir(pdir))
    partial = [e for e in entries if e.endswith('.partial')]
    if partial:
        refuse(f'{name}/ holds incomplete shard(s) {partial[:3]} (a .partial is a killed worker\'s shard; the phase did not complete)')
    n_shards = p['shards'] if subset is None else subset
    want_dirs = {f'shard-{i:02d}' for i in range(n_shards)}
    others = [e for e in entries if e not in want_dirs and e not in ('summary.json', 'diag') and not re.fullmatch(r'probe\.(stdout|stderr|time)(\.attempt\d+)?', e)
              and not (pins.get('phase_extras') and re.fullmatch(pins['phase_extras'], e)) and not (subset is not None and re.fullmatch(r'shard-\d+', e))]
    if others:
        refuse(f'{name}/ holds unexpected entries {others[:3]}')
    shards = []
    for i in range(n_shards):
        d = os.path.join(pdir, f'shard-{i:02d}')
        mp = os.path.join(d, 'shard_manifest.json')
        if not os.path.isfile(mp):
            refuse(f'{name}/shard-{i:02d}/shard_manifest.json missing (not a completed shard)')
        m = json.load(open(mp))
        binding = dict(shard=i, seed0=p['seed0'] + i * per, deals=per, plan_base=i * per, plan=pins['plan'], schema=pins['schema'], probe_rev=pins['probe_rev'],
                       knobs=dict(late_trick=pins['late_trick'], late_lead_prob=p['late_lead_prob'], prob_follow=p['prob_follow'], expert_cap_secs=pins['expert_cap_secs'],
                                  record_capsule=p['record_capsule'], served_env=[list(x) for x in pins['served_env']], expert_env=[list(x) for x in pins['expert_env']]),
                       source_sha256=pins['source_sha256'], harness_sha256=pins['harness_sha256'])
        if 'served_base_sha256' in pins:
            binding['served_base_sha256'] = pins['served_base_sha256']
        if m.get('schema') != pins['shard_manifest_schema'] or m.get('binding') != binding:
            refuse(f'{name}/shard-{i:02d}: shard manifest schema / binding differ from the phase pins: {json.dumps(m.get("binding"))[:160]}')
        present = sorted(n for n in os.listdir(d) if n != 'shard_manifest.json')
        if present != sorted(m['files']):
            refuse(f'{name}/shard-{i:02d}: holds {present}, its manifest lists {sorted(m["files"])}')
        for n, sha in m['files'].items():
            rel = os.path.normpath(os.path.join(name, f'shard-{i:02d}', n))
            if listed.get(rel) != sha:
                refuse(f'{name}/shard-{i:02d}/{n}: the shard manifest sha differs from SHA256SUMS')
        pj = os.path.join(d, 'probe.jsonl')
        rows = []
        with open(pj, 'rb') as fh:
            for ln, raw in enumerate(fh):
                if not raw.endswith(b'\n'):
                    refuse(f'{name}/shard-{i:02d}: truncated last row')
                try:
                    rows.append(json.loads(raw))
                except ValueError:
                    refuse(f'{name}/shard-{i:02d}: unreadable row {ln}')
        if not rows or rows[0].get('row') != 'header' or rows[-1].get('row') != 'end':
            refuse(f'{name}/shard-{i:02d}: no header or no end row')
        end = rows[-1]
        if any(m['counts'].get(k) != end.get(k) for k in ('decisions', 'labelled', 'expert_dropped', 'self_rows', 'rows_expert', 'rows_self')):
            refuse(f'{name}/shard-{i:02d}: the shard manifest counts differ from the end row')
        shards.append(dict(index=i, dir=d, rows=rows, seed0=p['seed0'] + i * per, per=per, manifest=m))
    if subset is not None:
        return shards, None, per
    sp = os.path.join(pdir, 'summary.json')
    if not os.path.isfile(sp):
        refuse(f'{name}/summary.json missing')
    return shards, json.load(open(sp)), per


def check_identity(name, p, pins, summary, shards, resumed):
    want = dict(schema=pins['schema'] + '-summary', seed0=p['seed0'], deals=p['deals'], shards=p['shards'], workers=pins['workers'], served_name=pins['served_name'],
                expert_name=pins['expert_name'], served_env=pins['served_env'], expert_env=[list(x) for x in pins['expert_env']], expert_cap_secs=pins['expert_cap_secs'],
                late_trick=pins['late_trick'], late_lead_prob=p['late_lead_prob'], prob_follow=p['prob_follow'], record_capsule=p['record_capsule'],
                rows_units=pins['rows_units'], enc_version=pins['enc_version'], input_dim=pins['input_dim'], source_sha256=pins['source_sha256'], harness_sha256=pins['harness_sha256'])
    if 'served_base_sha256' in pins:
        want['served_base_sha256'] = pins['served_base_sha256']
    if pins['workers'] is None:
        del want['workers']
    for k, v in want.items():
        if summary is not None and summary.get(k) != v:
            refuse(f'{name}/summary.json {k} = {summary.get(k)!r}, pinned {v!r}')
    if summary is not None and (not _t(summary.get('resumed'), bool) or not _t(summary.get('shards_skipped'), int)):
        refuse(f'{name}/summary.json resumed / shards_skipped malformed')
    if summary is not None and summary['resumed'] and resumed is None:
        refuse(f'{name}/summary.json says resumed but the status has no resume line')
    for s in shards:
        h = s['rows'][0]
        hw = dict(schema=pins['schema'], probe_rev=pins['probe_rev'], lifted=pins['lifted'], shard=s['index'], seed0=s['seed0'], deals=s['per'], plan=pins['plan'],
                  served_name=pins['served_name'], expert_name=pins['expert_name'], served_env=pins['served_env'], expert_env=[list(x) for x in pins['expert_env']],
                  served_worlds=pins['served_worlds'], expert_worlds=pins['expert_worlds'], expert_cap_secs=pins['expert_cap_secs'], late_trick=pins['late_trick'],
                  late_lead_prob=p['late_lead_prob'], prob_follow=p['prob_follow'], record_capsule=p['record_capsule'], rows_units=pins['rows_units'],
                  enc_version=pins['enc_version'], input_dim=pins['input_dim'], fast='1', pv_sha256=pins['pv_sha256'], belief_sha256=pins['belief_sha256'],
                  source_sha256=pins['source_sha256'], harness_sha256=pins['harness_sha256'])
        if 'served_base_sha256' in pins:
            hw['served_base_sha256'] = pins['served_base_sha256']
        for k, v in hw.items():
            if h.get(k) != v:
                refuse(f'{name}/shard-{s["index"]:02d} header {k} = {h.get(k)!r}, pinned {v!r}')


def check_coverage(name, shards):
    """Every deal once, every decision once, the deal row's lists and counts the rows', its declare and bury records in shape."""
    deals = {}
    for s in shards:
        rows = s['rows'][1:-1]
        end = s['rows'][-1]
        by_deal = {}
        for r in rows:
            if r.get('row') not in ('decision', 'live', 'deal_done'):
                refuse(f'{name}/shard-{s["index"]:02d}: unknown row kind {r.get("row")!r}')
            if not _t(r.get('deal'), int):
                refuse(f'{name}/shard-{s["index"]:02d}: row without an integer deal')
            by_deal.setdefault(r['deal'], []).append(r)
        want = set(range(s['seed0'], s['seed0'] + s['per']))
        if set(by_deal) != want:
            refuse(f'{name}/shard-{s["index"]:02d}: deals {sorted(set(by_deal) ^ want)[:4]} missing or foreign (window {s["seed0"]}+{s["per"]})')
        for deal, rs_ in by_deal.items():
            dd = [r for r in rs_ if r['row'] == 'deal_done']
            if len(dd) != 1:
                refuse(f'{name} deal {deal}: {len(dd)} deal_done rows')
            dd = dd[0]
            recs = [r for r in rs_ if r['row'] in ('decision', 'live')]
            idx = sorted(r.get('index') for r in recs)
            if idx != list(range(len(recs))) or dd.get('decisions') != len(recs):
                refuse(f'{name} deal {deal}: decision indices are not 0..n-1 once each, or the deal row counts {dd.get("decisions")} against {len(recs)} records')
            dec = [r for r in recs if r['row'] == 'decision']
            if dd.get('labelled') != [r['index'] for r in sorted(dec, key=lambda r: r['index'])]:
                refuse(f'{name} deal {deal}: the deal row\'s labelled list differs from the decision rows')
            if dd.get('expert_dropped') != sum(1 for r in dec if r['expert'].get('dropped')):
                refuse(f'{name} deal {deal}: the deal row\'s drop count differs from the rows')
            if dd.get('self_rows') != sum(1 for r in recs if r['row'] == 'live' and r.get('self_row') is True):
                refuse(f'{name} deal {deal}: the deal row\'s self-row count differs from the live rows')
            if not (isinstance(dd.get('deal_key'), str) and dd['deal_key'].startswith('deck:') and len(dd['deal_key']) == 69):
                refuse(f'{name} deal {deal}: no deal_key')
            for k in ('attacker_points', 'kitty_bonus', 'winner_team', 'level_change'):
                if not _t(dd.get(k), int):
                    refuse(f'{name} deal {deal}: deal row without integer {k}')
            # the generating decisions' records: the live bots' declares and bury, in their configured shapes
            dr, br = dd.get('declare_recs'), dd.get('bury_rec')
            if not (isinstance(dr, dict) and set(dr) == {'live'} and isinstance(dr['live'], list)) or not (isinstance(br, dict) and set(br) == {'live'} and isinstance(br['live'], list)):
                refuse(f'{name} deal {deal}: declare_recs / bury_rec not the {{live: [...]}} form')
            try:
                if dr['live']:
                    rs.classify_rows([(f'{name} deal {deal} declare {j}', x) for j, x in enumerate(dr['live'])], DECLARE_SHAPES, label=f'{name} deal {deal} declare records', length=6, with_where=True)
                rs.classify_rows([(f'{name} deal {deal} bury', br['live'])], BURY_SHAPES, label=f'{name} deal {deal} bury record', length=4, with_where=True)
            except rs.RowSchemaRefusal as e:
                refuse(str(e))
            deals[deal] = dict(row=dd, dec=dec, recs=recs)
        tot = dict(decisions=sum(len(d['recs']) for dl, d in deals.items() if dl in by_deal), labelled=sum(len(d['dec']) for dl, d in deals.items() if dl in by_deal))
        if end.get('decisions') != tot['decisions'] or end.get('labelled') != tot['labelled'] or end.get('deals') != s['per']:
            refuse(f'{name}/shard-{s["index"]:02d}: end row counts {end.get("decisions")}/{end.get("labelled")}/{end.get("deals")} differ from the rows {tot}')
        if sorted(s['manifest']['deal_keys']) != sorted(deals[d]['row']['deal_key'] for d in by_deal):
            refuse(f'{name}/shard-{s["index"]:02d}: the shard manifest deal keys differ from the deal rows')
    return deals


def check_row_schema(name, deals):
    for deal, d in deals.items():
        for r in d['recs']:
            where = f'{name} deal {deal} index {r["index"]}'
            for k, kinds in (('seat', int), ('lead', bool), ('trick_no', int)):
                if not _t(r.get(k), kinds):
                    refuse(f'{where}: {k} missing or of the wrong type')
            if r['row'] == 'live':
                check_record(r, where + ' live')
                if not isinstance(r.get('cards'), list) or not _t(r.get('self_row'), bool):
                    refuse(f'{where}: live row without cards / self_row')
            else:
                for arm in ('expert', 'served', 'live'):
                    if not isinstance(r.get(arm), dict):
                        refuse(f'{where}: no {arm} record')
                    check_record(r[arm], f'{where} {arm}')
                e = r['expert']
                if not _t(e.get('dropped'), bool):
                    refuse(f'{where}: expert.dropped not a bool')
                if not e['dropped']:
                    for k in ('cards', 'admitted', 'value_means', 'policy_log_odds_admitted'):
                        if not isinstance(e.get(k), list) or not e[k]:
                            refuse(f'{where}: kept expert record without {k}')
                    if not (len(e['admitted']) == len(e['value_means']) == len(e['policy_log_odds_admitted']) >= 2):
                        refuse(f'{where}: expert ballot / means / log-odds lengths differ or < 2')
                    if sorted(e['cards']) not in [sorted(a) for a in e['admitted']]:
                        refuse(f'{where}: a_E not in B_E')
                    if e.get('action_type') not in ACTION_TYPES or not _t(r.get('expert_in_r48_ballot'), bool):
                        refuse(f'{where}: action_type / expert_in_r48_ballot tags malformed')
                    for k in ('expert_pref_rank_r48', 'expert_pref_rank_256'):
                        if r.get(k) is not None and not _t(r[k], int):
                            refuse(f'{where}: {k} not an int or null')
                wd = r.get('worlds_digest') or {}
                if not all(isinstance(wd.get(k), str) and len(wd[k]) == 64 for k in ('served', 'expert', 'expert_prefix')):
                    refuse(f'{where}: worlds_digest incomplete')
                if not isinstance(r.get('secs'), dict) or not _t(r['secs'].get('expert'), (int, float)):
                    refuse(f'{where}: secs.expert missing')


# ------------------------------------------------------------------ validity

def arm_records(deals):
    """(arm, record, where) over every decision: live (every decision's own record), served and expert (labelled decisions)."""
    for deal, d in deals.items():
        for r in d['recs']:
            where = f'deal {deal} index {r["index"]}'
            if r['row'] == 'live':
                yield 'live', r, where
            else:
                yield 'live', r['live'], where
                yield 'served', r['served'], where
                yield 'expert', r['expert'], where


def validity(name, p, pins, bar, deals):
    reasons, report = [], {}
    counts = {a: dict(decisions=0, play_fallback=0, search=0, belief_fallback=0) for a in ARMS}
    delivered = []
    caps_off = {a: 0 for a in ARMS}; stage = {a: 0 for a in ARMS}; expert_stages = {}
    want_w = dict(live=pins['served_worlds'], served=pins['served_worlds'], expert=pins['expert_worlds'])
    for arm, rec, where in arm_records(deals):
        c = counts[arm]
        c['decisions'] += 1
        search = rec.get('schema') == RECORD_SCHEMA
        if not search or (arm == 'expert' and rec.get('dropped')):
            c['play_fallback'] += 1
        if search:      # the belief draw exists only on a search record; a fallback record (a dropped expert decision, a search error) is a PLAY
            c['search'] += 1   # fallback counted above and carries no belief draw (its belief_fallback is None): validity.DENOMINATORS['belief_fallback'] = search
            if rec.get('belief_fallback') != 0:
                c['belief_fallback'] += 1
        delivered.append((f'{arm} {where}', arm, va.SEARCH if search else va.FALLBACK, rec.get('worlds') if search else None))
        if rec.get('caps') != (pins['expert_caps'] if arm == 'expert' else pins['lifted_caps']):
            caps_off[arm] += 1
        if search:
            f = stage_faults(rec, lifted=(arm != 'expert'))
            if arm == 'expert':
                for x in f:
                    expert_stages[x] = expert_stages.get(x, 0) + 1
            elif f:
                stage[arm] += 1
    # the generating decisions: the live bots' declares and bury per deal (the only arm that declares and buries)
    declares, gen = [], dict(live=dict(declares=0, declare_abandon=0, buries=0, bury_fallback=0))
    for deal, d in deals.items():
        for j, x in enumerate(d['row']['declare_recs']['live']):
            gen['live']['declares'] += 1
            if x[1] is not None or x[2] is not True:
                gen['live']['declare_abandon'] += 1
            declares.append(dict(where=f'deal {deal} declare {j}', arm='live', evaluated=x[2], worlds=x[3], completed=x[4]))
        gen['live']['buries'] += 1
        if d['row']['bury_rec']['live'][0] != BURY_SCHEMA:
            gen['live']['bury_fallback'] += 1
    checks = [va.arm_fault_ceilings(counts, bar['play_ceilings'], arms=ARMS, tier='DEV'),
              va.worlds_delivered(delivered, want_w, tier='DEV'),
              va.arm_fault_ceilings(gen, bar['generating_ceilings'], arms=('live',), tier='DEV'),
              va.completion_shape(declares, tier='DEV', expected_worlds_by_arm={'live': pins['declare_worlds']})]
    for ck in checks:
        reasons += [f"{ck['check']}: {r}" for r in ck['reasons']]
    for a in ARMS:
        if caps_off[a]:
            reasons.append(f'{a}: {caps_off[a]} record(s) with caps off the pin')
        if stage[a]:
            reasons.append(f'{a}: {stage[a]} record(s) with a stage effect on a lifted arm (a fired / abandoned stage, or a deadline field the runtime emits only when the stage is armed)')
    unpaired = sum(1 for d in deals.values() for r in d['dec'] if r['worlds_digest']['served'] != r['worlds_digest']['expert_prefix'])
    if unpaired:
        reasons.append(f'{unpaired} labelled decision(s) whose served worlds are not the expert draw\'s prefix')
    rules = pins.get('off_ballot_rules', ())
    served_cmp, skip_by, skip_bad = {}, {}, []
    for deal, d in deals.items():
        for r in d['dec']:
            _, _, why = served_comparison(r['served'], rules)
            served_cmp[why or 'on_ballot'] = served_cmp.get(why or 'on_ballot', 0) + 1
        skipped = [off_ballot_reason(r, rules) for r in d['recs'] if r['row'] == 'live' and r.get('self_row') is False]
        skipped = [x for x in skipped if x is not None]
        for x in skipped:
            skip_by[x] = skip_by.get(x, 0) + 1
        if not _t(d['row'].get('self_skipped'), int) or d['row']['self_skipped'] != len(skipped):
            skip_bad.append(deal)
    if served_cmp.get('unexplained'):
        reasons.append(f"{served_cmp['unexplained']} labelled decision(s) whose served search record has no ballot selection under no registered off-ballot rule")
    if skip_bad:
        reasons.append(f'{len(skip_bad)} deal(s) whose self_skipped is not the count of live rows skipped under a registered off-ballot rule (first {skip_bad[0]})')
    if rules:
        report['off_ballot'] = dict(rules=list(rules), served={k: served_cmp[k] for k in sorted(served_cmp)}, self_skipped_by_rule={k: skip_by[k] for k in sorted(skip_by)})
    kept = [r for d in deals.values() for r in d['dec'] if not r['expert']['dropped']]
    dropped = [r for d in deals.values() for r in d['dec'] if r['expert']['dropped']]
    leads = [r for r in kept if r['lead']]
    fl = bar['floors'].get(name, dict(kept_leads_min=0, deals_min=0))
    if len(leads) < fl['kept_leads_min']:
        reasons.append(f'kept lead labels {len(leads)} < {fl["kept_leads_min"]}')
    if len(deals) < fl['deals_min']:
        reasons.append(f'deals {len(deals)} < {fl["deals_min"]}')
    report.update(checks={c['check'] + ('' if c['check'] != 'arm_fault_ceilings' else f"[{','.join(c['detail'].get('arms', []))}]"): dict(verdict=c['verdict'], detail=c['detail']) for c in checks},
                  arms={a: dict(counts[a], caps_off=caps_off[a], stage_faults=stage[a]) for a in ARMS}, generating=gen['live'],
                  expert_stages_abandoned_or_fired=expert_stages, unpaired=unpaired,
                  deals=len(deals), decisions=sum(len(d['recs']) for d in deals.values()), labelled=len(kept) + len(dropped), kept=len(kept), dropped=len(dropped),
                  drop_rate=(len(dropped) / (len(kept) + len(dropped))) if kept or dropped else None,
                  dropped_by_reason={k: sum(1 for r in dropped if r['expert'].get('drop_reason') == k) for k in {r['expert'].get('drop_reason') for r in dropped}},
                  kept_leads=len(leads), kept_follows=len(kept) - len(leads),
                  labels_per_deal=dict(mean=len(kept) / len(deals) if deals else None, leads=len(leads) / len(deals) if deals else None),
                  self_rows=sum(d['row']['self_rows'] for d in deals.values()), skipped_single=sum(1 for d in deals.values() for r in d['recs'] if r['row'] == 'live' and r.get('skipped_single')))
    return reasons, report, kept


def check_rows(name, p, pins, shards, deals, kept, replay_make, replay_per_shard):
    """The training rows of every shard through the loader, one to one with the decision / live rows; the capsules (record_capsule phases)
    one to one with the kept decisions, their served record and digest the decision's, a sample replayed through the real served path."""
    import numpy as np
    sys.path.insert(0, os.environ.get('FIND_GAPS_SERVER') or os.getcwd())
    from shengji.train.data import deal_key as data_deal_key
    from shengji.train.policy_prior import CARD_INDEX
    from shengji.train.policy_rows import open_policy_rows
    spec = importlib.util.spec_from_file_location('expert_label_probe', os.path.join(HERE, 'expert_label_probe.py'))
    elp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(elp)
    reasons = []
    cards = sorted(CARD_INDEX, key=CARD_INDEX.get)
    key_of = {d: dd['row']['deal_key'] for d, dd in deals.items()}
    dec_by = {(r['deal'], r['index']): r for r in kept}
    live_by = {(r['deal'], r['index']): r for d in deals.values() for r in d['recs'] if r['row'] == 'live' and r.get('self_row') is True}
    tot = dict(rows_expert=0, rows_self=0, capsules=0, replayed=0, replay_ok=0, replay_max_abs_diff=0.0)
    tags = dict(action_type={t: 0 for t in ACTION_TYPES}, lead_action_type={t: 0 for t in ACTION_TYPES}, in_r48_ballot=0, rank_r48_le8=0, rank_r48_known=0, rank_r48_gt24=0, swapped=0)
    rules = pins.get('off_ballot_rules', ())
    if rules:
        tags['served_off_ballot'] = 0
    for s in shards:
        shard_deals = set(range(s['seed0'], s['seed0'] + s['per']))
        for which, index in (('rows_expert', dec_by), ('rows_self', live_by)):
            prefix = os.path.join(s['dir'], which)
            want = {k for k in index if k[0] in shard_deals}
            if not os.path.isfile(prefix + '.npz') or not os.path.isfile(prefix + '.meta.jsonl'):
                if want:
                    reasons.append(f'{name}/shard-{s["index"]:02d}: {which} files missing for {len(want)} rows')
                continue
            try:
                pr = open_policy_rows(prefix)
            except Exception as exc:   # the loader's refusal is the finding
                reasons.append(f'{name}/shard-{s["index"]:02d}: {which} does not load: {type(exc).__name__}: {str(exc)[:100]}')
                continue
            meta = [json.loads(l) for l in open(prefix + '.meta.jsonl')]
            if pr.n != len(meta) or pr.X.shape != (pr.n, pins['input_dim']) or pr.Y.shape != (pr.n, 54):
                reasons.append(f'{name}/shard-{s["index"]:02d}: {which} shapes {pr.X.shape} / {pr.Y.shape} / meta {len(meta)}')
                continue
            if int((pr.tgt >= 0).sum()) != pr.n:
                reasons.append(f'{name}/shard-{s["index"]:02d}: {which}: {pr.n - int((pr.tgt >= 0).sum())} row(s) whose taken action is not in the ballot')
            if pr.vals is None:
                reasons.append(f'{name}/shard-{s["index"]:02d}: {which}: no means carried')
            seen = set()
            ymh = np.zeros_like(pr.Y)
            for i, m in enumerate(meta):
                dl = next((d for d, kk in key_of.items() if kk == m.get('deal_key') and d in shard_deals), None)
                k = (dl, m.get('index'))
                if k not in index:
                    reasons.append(f'{name}/shard-{s["index"]:02d}: {which} row {i} ({k}) has no matching {"kept decision" if which == "rows_expert" else "self-flagged live"} row'); break
                seen.add(k)
                if not (isinstance(m.get('means'), list) and isinstance(m.get('prior_lo'), list) and len(m['means']) == len(m['ballot']) == len(m['prior_lo'])
                        and all(isinstance(x, (int, float)) and math.isfinite(x) for x in m['means'] + m['prior_lo'])):
                    reasons.append(f'{name}/shard-{s["index"]:02d}: {which} row {i}: means / prior_lo not ballot-long and finite'); break
                if m.get('units') != pins['rows_units'] or m.get('deal_key') != key_of.get(dl):
                    reasons.append(f'{name}/shard-{s["index"]:02d}: {which} row {i}: units {m.get("units")!r} or deal_key off the deal row'); break
                if m.get('action_type') not in ACTION_TYPES or m.get('label_kind') not in ('lead', 'follow') or m.get('source') != which.split('_')[1]:
                    reasons.append(f'{name}/shard-{s["index"]:02d}: {which} row {i}: tags malformed'); break
                for c in m['taken']:
                    ymh[i, c] = 1
                if which == 'rows_expert':
                    r = index[k]
                    if sorted(m['taken']) != sorted(CARD_INDEX[c] for c in r['expert']['cards']) or m.get('expert_in_r48_ballot') != r['expert_in_r48_ballot']:
                        reasons.append(f'{name}/shard-{s["index"]:02d}: rows_expert row {i}: taken / tags differ from the decision row'); break
                    sv_ok, sv_off = served_taken_matches(m, r['served'], rules, CARD_INDEX)
                    if not sv_ok:
                        reasons.append(f'{name}/shard-{s["index"]:02d}: rows_expert row {i}: served_taken differs from the decision\'s served selection'); break
                    if sv_off:
                        tags['served_off_ballot'] += 1
                    tags['action_type'][m['action_type']] += 1
                    if m['lead']:
                        tags['lead_action_type'][m['action_type']] += 1
                    tags['in_r48_ballot'] += int(bool(m['expert_in_r48_ballot']))
                    tags['swapped'] += int(bool(m.get('expert_swapped')))
                    rk = m.get('expert_pref_rank_r48')
                    if rk is not None:
                        tags['rank_r48_known'] += 1; tags['rank_r48_le8'] += int(rk < 8); tags['rank_r48_gt24'] += int(rk >= 24)
            else:
                if not np.array_equal(ymh, pr.Y):
                    reasons.append(f'{name}/shard-{s["index"]:02d}: {which}: Y is not the multi-hot of taken on every row')
                if seen != want:
                    reasons.append(f'{name}/shard-{s["index"]:02d}: {which} rows {len(seen)} do not cover the {len(want)} expected rows one to one')
                tot[which] += pr.n
        cp = os.path.join(s['dir'], 'capsule.jsonl.gz')
        if p['record_capsule']:
            if not os.path.isfile(cp):
                reasons.append(f'{name}/shard-{s["index"]:02d}: capsule.jsonl.gz missing'); continue
            seen, caps_ = set(), []
            for raw in gzip.open(cp, 'rt'):
                c = json.loads(raw)
                k = (c.get('deal'), c.get('index'))
                r = dec_by.get(k)
                if r is None:
                    reasons.append(f'{name}/shard-{s["index"]:02d}: capsule for {k} without a kept decision'); break
                ws = elp.worlds_from_indices(c['worlds'])
                sv = r['served']
                ok = (c.get('schema') == pins['capsule_schema'] and c.get('seat') == r['seat'] and c['snapshot'].get('turn') == r['seat'] and c['snapshot'].get('phase') == 'play'
                      and len(ws) == pins['served_worlds'] and worlds_digest(ws) == c.get('worlds_digest') == r['worlds_digest']['served']
                      and c['served'].get('admitted') == sv['admitted'] and c['served'].get('cards') == sv['cards'] and c['served'].get('value_means') == sv['value_means']
                      and c['served'].get('policy_log_odds_admitted') == sv['policy_log_odds_admitted']
                      and isinstance(c.get('deck'), list) and len(c['deck']) == 108 and len(set(c['deck'])) == 54 and data_deal_key([cards[i] for i in c['deck']]) == key_of[c['deal']] == c.get('deal_key')
                      and sorted(c['snapshot']['hands_by_seat'][r['seat']]) == c['snapshot']['hands_by_seat'][r['seat']] and len(c['snapshot']['hands_by_seat'][r['seat']]) == r['hand_size'])
                if not ok:
                    reasons.append(f'{name}/shard-{s["index"]:02d}: capsule for {k} does not match its decision row (schema / seat / worlds digest / served record / deck key / hand)'); break
                seen.add(k); caps_.append(c); tot['capsules'] += 1
            else:
                want = {k for k in dec_by if k[0] in shard_deals}
                if seen != want:
                    reasons.append(f'{name}/shard-{s["index"]:02d}: capsules cover {len(seen)} of {len(want)} kept decisions')
                for c in caps_[:replay_per_shard]:    # the real served path again, on the recorded root and worlds
                    tot['replayed'] += 1
                    try:
                        rp = elp.replay_capsule(c, replay_make)
                        # the discrete fields (ballot, selected action, pick, indices, worlds, digest, state) must be EXACT; the means and the prior
                        # log-odds within REPLAY_ATOL (a read on another host than the producing one differs in the last ulp: 2e-15 measured
                        # Mac arm64 vs cloud x86; on the producing host the difference is 0 and is reported)
                        same = {k: v for k, v in rp['same'].items() if k not in ('value_means', 'policy_log_odds_admitted')}
                        diffs = {}
                        for k in ('value_means', 'policy_log_odds_admitted'):
                            d = slot_diff(rp['got'][k], c['served'][k])
                            diffs[k] = d; same[k] = d <= REPLAY_ATOL
                        why = [k for k, v in same.items() if not v]
                        ok = all(same.values())
                        tot['replay_max_abs_diff'] = max(tot['replay_max_abs_diff'], max(diffs.values()))
                    except Exception as exc:      # the engine or the bot refusing the rebuilt root is a non-reproduction, named
                        why, ok = [f'{type(exc).__name__}: {str(exc)[:80]}'], False
                    tot['replay_ok'] += int(ok)
                    if not ok:
                        reasons.append(f"{name}/shard-{s['index']:02d}: capsule ({c['deal']}, {c['index']}) does not reproduce the recorded served decision through the registry bot: {why}")
        elif os.path.exists(cp):
            reasons.append(f'{name}/shard-{s["index"]:02d}: capsule.jsonl.gz present on a phase without --record-capsule')
    if tot['rows_expert'] != len(kept):
        reasons.append(f'{name}: rows_expert {tot["rows_expert"]} != kept decisions {len(kept)}')
    if tot['rows_self'] != len(live_by):
        reasons.append(f'{name}: rows_self {tot["rows_self"]} != self-flagged live rows {len(live_by)}')
    if p['record_capsule'] and replay_per_shard >= 1 and tot['replayed'] == 0 and kept:
        reasons.append(f'{name}: no capsule was replayed')
    return reasons, dict(rows=tot, tags=tags)


def timing(deals, shards):
    kept = [r for d in deals.values() for r in d['dec'] if not r['expert']['dropped']]
    es = [r['secs']['expert'] for r in kept]
    el = [r['secs']['expert'] for r in kept if r['lead']]
    ef = [r['secs']['expert'] for r in kept if not r['lead']]
    ss = [r['secs']['served'] for r in kept]
    ls = [r['live_secs'] for d in deals.values() for r in d['recs'] if 'live_secs' in r]
    walls = [s['rows'][-1].get('secs') for s in shards]
    return dict(expert_secs=dict(all=[q(es, .5), q(es, .95), max(es) if es else None], leads=[q(el, .5), q(el, .95), max(el) if el else None], follows=[q(ef, .5), q(ef, .95), max(ef) if ef else None]),
                served_secs=[q(ss, .5), q(ss, .95), max(ss) if ss else None], live_secs=[q(ls, .5), q(ls, .95), max(ls) if ls else None],
                shard_wall_secs=dict(mean=st.mean(walls) if walls else None, max=max(walls) if walls else None),
                per_deal_secs=(st.mean(walls) / shards[0]['per']) if walls and shards[0]['per'] else None)


# ------------------------------------------------------------------ driver

def analyze(root, *, status, reservation, manifest=None, manifest_sha256=None, trusted=TRUSTED, pins=PINS, bar=BAR, bench=False, replay_make=None, replay_per_shard=3):
    b = rl.bind_inputs(root, status, reservation, trusted=trusted, manifest=manifest, manifest_sha256=manifest_sha256)
    term = rl.terminal_line(b['status'], trusted['lane'], f"{trusted['lane']} {terminal(pins)}", tails=rl.NO_TAIL)
    said = check_status(b['status'], trusted, pins, b['root'])
    listed = check_sums(b['root'], said)
    diag = [k for k in listed if k.startswith('diag/') or '/diag/' in k or re.search(r'probe\.(stdout|stderr|time)\.attempt\d+$', k)]
    if diag and said['resumed'] is None:
        refuse(f'diag/ or attempt entries {diag[:3]} without a resume attempt on the status')
    if replay_make is None:
        import exploit_duel_s61 as duel    # the harness: served_env ran at import, the registry factory of fly.toml's SHENGJI_BOT
        replay_make = duel.variant_factory(())[1]
    result = dict(schema='m28lab-check-v2', lane=trusted['lane'], bench=bench, binding=b, terminal=term['line'], status=said, phases={}, validity=None, reasons=[])
    exposure, all_reasons = {}, []
    for name, p in pins['phases'].items():
        shards, summary, per = load_phase(b['root'], name, p, pins, listed)
        check_identity(name, p, pins, summary, shards, said['resumed'])
        deals = check_coverage(name, shards)
        check_row_schema(name, deals)
        reasons, report, kept = validity(name, p, pins, bar, deals)
        rr, rows_report = check_rows(name, p, pins, shards, deals, kept, replay_make, replay_per_shard)
        reasons += rr
        report.update(rows_report, timing=timing(deals, shards), summary_counts={k: summary.get(k) for k in ('decisions', 'labelled', 'expert_dropped', 'rows_expert', 'rows_self', 'wall_secs', 'resumed', 'shards_skipped')})
        if summary.get('rows_expert') != report['rows']['rows_expert'] or summary.get('labelled') != report['labelled'] or summary.get('expert_dropped') != report['dropped']:
            reasons.append(f'{name}: summary.json counts differ from the rows')
        result['phases'][name] = dict(reasons=reasons, report=report)
        keys = sorted(dd['row']['deal_key'] for dd in deals.values())
        exposure[name] = dict(seed0=p['seed0'], deals=p['deals'], deal_keys=keys, digest=hashlib.sha256('\n'.join(keys).encode()).hexdigest(), deal_key_schema='shengji-value-deal-key-v1')
        all_reasons += [f'{name}: {x}' for x in reasons]
    result['reasons'] = all_reasons
    result['validity'] = 'VALID' if not all_reasons else 'INVALID'
    result['exposure_digests'] = {k: v['digest'] for k, v in exposure.items()}
    result['note'] = ('timing evidence only (the bench copy)' if bench else 'rows validity only; no outcome, bar or strength is read at this stage')
    return result, exposure


def canonical_lines(res):
    out = [f"m28lab check: {res['validity']} ({res['lane']}; bound {res['binding']['mode']}; {res['note']}" + (f"; resumed attempt {res['status']['resumed']['attempt']}" if res['status'].get('resumed') else '') + ')']
    for name, ph in res['phases'].items():
        r = ph['report']
        out.append(f"  {name}: deals {r['deals']} decisions {r['decisions']} labelled {r['labelled']} kept {r['kept']} (leads {r['kept_leads']}, follows {r['kept_follows']}) dropped {r['dropped']} "
                   f"({(r['drop_rate'] or 0):.2%}; {r['dropped_by_reason']}) self rows {r['self_rows']} rows_expert {r['rows']['rows_expert']} rows_self {r['rows']['rows_self']} capsules {r['rows']['capsules']} replayed {r['rows']['replay_ok']}/{r['rows']['replayed']} (max |d means, log-odds| {r['rows']['replay_max_abs_diff']:.1e})")
        out.append(f"    arms: {r['arms']}; generating (live declares / bury): {r['generating']}; expert stages {r['expert_stages_abandoned_or_fired']}; unpaired {r['unpaired']}")
        t = r['timing']
        out.append(f"    expert secs leads p50/p95/max {t['expert_secs']['leads']} follows {t['expert_secs']['follows']}; served {t['served_secs']}; live {t['live_secs']}; shard wall mean/max {t['shard_wall_secs']}; per deal {t['per_deal_secs']}")
        out.append(f"    tags: action types {r['tags']['action_type']} (leads {r['tags']['lead_action_type']}); a_E in R48 ballot {r['tags']['in_r48_ballot']} of {r['kept']}; R48 rank known {r['tags']['rank_r48_known']}, < 8: {r['tags']['rank_r48_le8']}, >= 24: {r['tags']['rank_r48_gt24']}; swapped {r['tags']['swapped']}")
        if 'off_ballot' in r:
            ob = r['off_ballot']
            out.append(f"    off-ballot (valid rows, rules {ob['rules']}): served {ob['served']}; expert rows with an off-ballot served move {r['tags'].get('served_off_ballot')}; live self rows skipped {ob['self_skipped_by_rule']}")
        for x in ph['reasons']:
            out.append(f'    INVALID: {x}')
    return out


def shard_listing(root, name, n_shards):
    """{relative path: sha256 of the bytes on disk} of every file of shards 0..n-1 that its shard manifest lists (rows-only mode: each
    shard is checked against its own manifest; the lane's root seal is not read)."""
    listed = {}
    for i in range(n_shards):
        d = os.path.join(root, name, f'shard-{i:02d}')
        mp = os.path.join(d, 'shard_manifest.json')
        if not os.path.isfile(mp):
            refuse(f'{name}/shard-{i:02d}/shard_manifest.json missing (not a completed shard)')
        for n in json.load(open(mp)).get('files') or {}:
            p = os.path.join(d, n)
            if os.path.isfile(p) and not os.path.islink(p):
                listed[os.path.normpath(os.path.join(name, f'shard-{i:02d}', n))] = rl.sha256_file(p)
    return listed


def analyze_rows(root, *, phases, pins, bar=BAR, subset=None, replay_make=None, replay_per_shard=3, profile=None):
    """Rows-only mode: every check of `analyze` after the lane binding, per phase, on shards 0..subset-1 (all shards when None)."""
    no_replay = sorted(name for name, p in phases.items() if p['record_capsule'])
    if no_replay and replay_per_shard < 1:   # a capsule phase read without one replay would say VALID on no reproduction of the served path
        raise CheckRefusal(f'REFUSING: replay_per_shard {replay_per_shard} < 1 on capsule phase(s) {", ".join(no_replay)}; rows mode replays at least one capsule per shard')
    if replay_make is None and any(p['record_capsule'] for p in phases.values()) and replay_per_shard >= 1:
        import exploit_duel_s61 as duel
        replay_make = duel.variant_factory(())[1]
    pins = dict(pins, phases=phases)
    bar = dict(bar, floors={} if subset is not None else bar['floors'])
    result = dict(schema='expert-label-rows-check-v1', profile=profile, served_name=pins['served_name'], subset=subset, phases={}, validity=None, reasons=[])
    exposure, all_reasons = {}, []
    for name, p in phases.items():
        listed = shard_listing(root, name, p['shards'] if subset is None else subset)
        shards, summary, per = load_phase(root, name, p, pins, listed, subset=subset)
        check_identity(name, p, pins, summary, shards, None)
        deals = check_coverage(name, shards)
        check_row_schema(name, deals)
        reasons, report, kept = validity(name, p, pins, bar, deals)
        rr, rows_report = check_rows(name, p, pins, shards, deals, kept, replay_make, replay_per_shard)
        reasons += rr
        report.update(rows_report, timing=timing(deals, shards))
        if summary is not None:
            report['summary_counts'] = {k: summary.get(k) for k in ('decisions', 'labelled', 'expert_dropped', 'rows_expert', 'rows_self', 'wall_secs', 'resumed', 'shards_skipped')}
            if summary.get('rows_expert') != report['rows']['rows_expert'] or summary.get('labelled') != report['labelled'] or summary.get('expert_dropped') != report['dropped']:
                reasons.append(f'{name}: summary.json counts differ from the rows')
        result['phases'][name] = dict(reasons=reasons, report=report)
        keys = sorted(dd['row']['deal_key'] for dd in deals.values())
        exposure[name] = dict(seed0=p['seed0'], deals=len(keys), deal_keys=keys, digest=hashlib.sha256('\n'.join(keys).encode()).hexdigest(), deal_key_schema='shengji-value-deal-key-v1')
        all_reasons += [f'{name}: {x}' for x in reasons]
    result['reasons'] = all_reasons
    result['validity'] = 'VALID' if not all_reasons else 'INVALID'
    result['exposure_digests'] = {k: v['digest'] for k, v in exposure.items()}
    result['note'] = 'rows validity only (no lane binding' + (f'; shards 0..{subset - 1} of each phase, no summary or floors' if subset is not None else '') + '); no outcome, bar or strength is read'
    return result, exposure


def parse_phase(text):
    """NAME=SEED0,DEALS,SHARDS,LATE_LEAD_P,FOLLOW_P,CAPSULE (CAPSULE 0 or 1) -> (name, phase pins)."""
    m = re.fullmatch(r'([a-z]+)=(\d+),(\d+),(\d+),([0-9.]+),([0-9.]+),([01])', text)
    if not m:
        raise SystemExit(f'REFUSING: --phase {text!r} is not NAME=SEED0,DEALS,SHARDS,LATE_LEAD_P,FOLLOW_P,CAPSULE')
    seed0, deals, shards = int(m.group(2)), int(m.group(3)), int(m.group(4))
    if shards < 1 or deals % shards:
        raise SystemExit(f'REFUSING: --phase {text!r}: deals must be a multiple of shards')
    return m.group(1), dict(seed0=seed0, deals=deals, shards=shards, late_lead_prob=float(m.group(5)), prob_follow=float(m.group(6)), record_capsule=m.group(7) == '1')


def canonical_rows_lines(res):
    head = f"expert-label rows check: {res['validity']} (profile {res['profile']}; {res['note']})"
    return [head] + canonical_lines(dict(res, validity=res['validity'], lane='rows', binding=dict(mode='none'), status={}))[1:]


def main_rows(argv):
    ap = argparse.ArgumentParser(prog='m28lab_check.py rows', description='rows-only check of an expert-label output root')
    ap.add_argument('root'); ap.add_argument('out')
    ap.add_argument('--profile', choices=sorted(PROFILES), required=True)
    ap.add_argument('--phase', action='append', required=True, type=parse_phase)
    ap.add_argument('--subset', type=int, default=None, help='check shards 0..N-1 of each phase only (no summary.json, no floors)')
    ap.add_argument('--replay-per-shard', type=int, default=3)
    a = ap.parse_args(argv)
    if a.subset is not None and a.subset < 1:
        raise SystemExit('REFUSING: --subset must be >= 1')
    if os.path.exists(a.out):
        raise SystemExit(f'REFUSING: {a.out} exists')
    try:
        res, exposure = analyze_rows(a.root, phases=dict(a.phase), pins=PROFILES[a.profile], subset=a.subset, replay_per_shard=a.replay_per_shard, profile=a.profile)
    except rl.ReaderRefusal as exc:
        print(str(exc) if str(exc).startswith('REFUSING') else f'REFUSING: {exc}')
        raise SystemExit(3)
    with open(a.out, 'x') as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
    with open(a.out + '.exposure.json', 'x') as fh:
        json.dump(exposure, fh, indent=1, sort_keys=True)
    print('\n'.join(canonical_rows_lines(res)))
    return 0 if res['validity'] == 'VALID' else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ['rows']:
        return main_rows(argv[1:])
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('root'); ap.add_argument('status'); ap.add_argument('reservation'); ap.add_argument('out')
    ap.add_argument('--manifest'); ap.add_argument('--manifest-sha256')
    ap.add_argument('--lane', choices=['m28lab', 'm28labbench'], default='m28lab')
    ap.add_argument('--launcher-sha', default=None, help='the bench copy\'s launcher sha256 (required with --lane m28labbench)')
    ap.add_argument('--replay-per-shard', type=int, default=3, help='capsules replayed through the real served path per HELD-OUT shard (>= 1 on the real lane)')
    ap.add_argument('--no-floors', action='store_true', help='BENCH ONLY: row floors 0 (refused on the real lane)')
    a = ap.parse_args(argv)
    trusted, pins, bar = dict(TRUSTED), dict(PINS), dict(BAR)
    bench = a.lane == 'm28labbench'
    if bench:
        if not a.launcher_sha or not re.fullmatch(r'[0-9a-f]{64}', a.launcher_sha):
            raise SystemExit('REFUSING: --lane m28labbench needs --launcher-sha <64 hex>')
        trusted.update(lane='m28labbench', launcher_sha256=a.launcher_sha, root='/root/vol-bench-claude-m28labbench-r2c-r48-20261025',
                       status='/root/claude_m28labbench_r2c_screen.status', reservation='/root/claude_reservations/m28labbench_r2c.json')
        pins = dict(pins, phases=BENCH_PHASES)
        bar = dict(bar, floors={k: dict(kept_leads_min=0, deals_min=0) for k in pins['phases']})
    elif a.no_floors:
        raise SystemExit('REFUSING: --no-floors is refused on the real lane (the floors are predeclared); it exists for the bench copy only')
    if not bench and a.replay_per_shard < 1:
        raise SystemExit('REFUSING: the real lane replays at least one capsule per HELD-OUT shard')
    if os.path.exists(a.out):
        raise SystemExit(f'REFUSING: {a.out} exists')
    try:
        res, exposure = analyze(a.root, status=a.status, reservation=a.reservation, manifest=a.manifest, manifest_sha256=a.manifest_sha256,
                                trusted=trusted, pins=pins, bar=bar, bench=bench, replay_per_shard=a.replay_per_shard)
    except rl.ReaderRefusal as exc:
        print(str(exc) if str(exc).startswith('REFUSING') else f'REFUSING: {exc}')
        raise SystemExit(3)
    with open(a.out, 'x') as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
    with open(a.out + '.exposure.json', 'x') as fh:
        json.dump(exposure, fh, indent=1, sort_keys=True)
    print('\n'.join(canonical_lines(res)))
    summary = ', '.join('%s %d keys %s' % (k, len(v['deal_keys']), v['digest'][:12]) for k, v in exposure.items())
    print(f"exposure written: {a.out}.exposure.json ({summary})")
    return 0 if res['validity'] == 'VALID' else 1


if __name__ == '__main__':
    sys.exit(main())
