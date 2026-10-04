# AI_POLICIES.md release sections, through release 38

Archived 2026-10-04 from `AI_POLICIES.md`, unchanged: the release-38 production contract as written (environment and rollback chain), its per-release subsections (policy prior admission, the soft head, JS-M1, serving qualification, hybrid bury integration, `mc-s0-report-lcb`), "The shortlist era, condensed" and "Retired BELIEF policy boundary". The ladder table stays in `AI_POLICIES.md`; release records and rollbacks are in `DEPLOY.md`.

## Production contract (as of release 38)

**Release 38** (deployed 2026-10-03 09:41 ET; Jerry approved promotion and the deploy 2026-10-03; #698 at main
`c8d487a6`; image `deployment-01M40ZWSAHNX4782CGKJ615YF7`). It keeps release 36's package, search, bury and budgets:
the policy head admits 8 of the legal actions over 64 sampled worlds, the value head prices them, no playouts;
value-guided hybrid bury on the same package; budgets 3 s / 2 s; the JS-M1 prior keys retained. It adds four search
rules, off by default in source and on in release 38:

- **Admission diversity `div`** (#680): at most 2 admitted actions per structural key; near-duplicates sharing all
  but one card are skipped; back-fill when short.
- **Refusal-constraint sampling `rc`** (#689): sampled worlds must make this round's refused throws refusable with
  the same forced component.
- **Tie-break by points `tb`** (#682): among candidates within 0.02 level of the best mean, the most root-team points
  from the current trick under the search's own trick finisher.
- **Lead-anchor `la`** (#694): on a lead whose heuristic anchor is a non-trump single that is not the top live card,
  slot 0 becomes the highest plain pair/tractor, else the policy's top action.

Without the rules (releases 36 and 37) slot 0 was always the heuristic play, the seven best-scored actions were
admitted unfiltered, and the highest mean played. Play has a 3 s cooperative budget; on expiry the bot plays the
heuristic anchor.

Evidence: ladder row 10 (#676). Further detail: the combination's first ten windows read +0.0175
[−0.0020, +0.0370]; the lead-anchor-alone read is issuecomment-5963796858; play latency on the same 808 states was
p50 0.119 s vs release 36's 0.107 s.

The selection (gate and rollback environments are in `DEPLOY.md`):

```toml
SHENGJI_BOT = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-r7092480e-bury-hybrid-5517ddbd7457"
SHENGJI_PV_CKPT = "/data/models/smv3out-491ee4bf.npz"
SHENGJI_PV_SHA256 = "491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670"
SHENGJI_PV_WORLDS = "64"
SHENGJI_PV_CANDIDATES = "8"
SHENGJI_PV_CAP = "4000"
SHENGJI_PV_BATCH_SIZE = "128"
SHENGJI_PV_SERVING_BUDGET_SECONDS = "3"
SHENGJI_PV_BURY_ARM = "hybrid"
SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS = "2"
SHENGJI_PV_ADMISSION_DIVERSITY = "1"
SHENGJI_PV_REFUSAL_CONSTRAINTS = "1"
SHENGJI_PV_TIEBREAK_POINTS = "1"
SHENGJI_PV_LEAD_ANCHOR = "1"
SHENGJI_FAST = "1"
```

The registry derives the name from that environment (package SHA256; the W64/K8 recipe digest of worlds,
candidates, cap 4,000, batch and budget; bury identity). It is never hand-written. `/healthz` reports the name and,
under `pv_search`, the package's on-disk SHA256, worlds, candidates, budgets and bury arm. Its `prior` block belongs
to the retained release-28 keys, not the active decision path. Without `SHENGJI_BOT` the server falls back to `mc`.
Changing the package, world count, admitted-candidate count, cap, sampler or bury arm makes a new policy and needs
fresh evidence.

**Earlier releases and rollbacks, nearest first.** Release records, images and exact environments are in
`DEPLOY.md`; for runtime regressions use its image rollback.

1. **Release 37** (2026-10-01 01:1x ET, #671): a phone-HUD CSS fix on release 36's bot; NO model, package or
   serving change. Rolling back release 38 to its image `deployment-01M3TXZ85YHJM108TBPWKN8BB2` is one option.
2. **Release 36** (2026-09-30 11:53 ET, #666): the first model change since release 30, **the gen-5 SMV3 checkpoint
   3e89e86f's OUTCOME head as ONE package** (`smv3out-491ee4bf.npz`; arm F's recipe plus the search-mean sidecar
   v3, #658) inside release 30's search unchanged. Evidence: ladder row 9. Rollback of release 38: delete the four
   `SHENGJI_PV_*` rule lines, restore the release-36 `SHENGJI_BOT` kept as a comment in `fly.toml`, then
   `fly deploy --ha=false`.
3. **Releases 29–35** served the soft head 8ecd4fea (`soft-8ecd4fea.npz`, sha ccade130…); release 30 (2026-09-22
   09:13 ET) added the hybrid-bury fix #607. Release 30 is the immediate rollback for releases 36/37: the three
   release-30 lines kept as a comment in `fly.toml` (the package stays on the volume) and `fly deploy --ha=false`,
   or the release-35 image.
4. **Release 28**: JS-M1 as one package inside the MC shortlist. Its keys (`SHENGJI_CWV_SHORTLIST_CKPT`,
   `SHENGJI_CWV_PRIOR_*`, `SHENGJI_CWV_BURY_*`) stay in `fly.toml`, so setting `SHENGJI_BOT` back to
   `mc-shortlist-0d17fd03-w32-r0d610b62-prior-0d17fd03-bury-hybrid-003c2abe49ff` is the whole rollback.
5. **Release 27**: M1 + separate prior v2.
6. **Release 24**: `fd6bb411` + hybrid bury.
7. `mc-s0-report-lcb`: the deep policy rollback.

The subsections below are records of earlier decision paths, kept because they are the rollback contracts and
because parts of them are still served. Policy prior admission and JS-M1 describe the release-27/28 shortlist path
(the release-28 rollback's contract). The soft head describes release 29's package, which releases 29–35 served.
Serving qualification and hybrid bury still apply to release 38. `mc-s0-report-lcb` is the deep rollback.

### Policy prior admission — deployed (releases 27 and 28)

Below 1,000 legal actions the value net ranks every legal action, as in the original W32 design. Above 1,000:

- the policy prior runs once per sampled world, on a root clone of that world (never the true hidden hands);
- each world's top 256 actions are unioned with production's own anchor candidates (median pool about 600 of a
  bound 8,192, roughly 5% of the legal set);
- only that pool is ranked.

The final shortlist (incumbent plus four alternatives) and the MC selection/report stages are unchanged. The
policy name binds every recipe field (`cwv_shortlist.PRIOR_RECIPE_FIELDS`); the admission trace records union size,
anchors and pool size per decision; the 300 s total play deadline is the backstop.

Evidence (2026-09-15, capped screens; the release 24 recipe is the control):

- Prior vs M1, paired on ten shared seeds: `−0.0003 [−0.0017, +0.0012]`. No resolved difference; a paired estimate,
  not an equivalence test.
- M1 + prior on ten fresh windows: `+0.0073 [−0.0087, +0.0233]` (MDE80 0.023), at 0.79× the release 24 recipe's
  decision wall. 0 decisions over 60 s and 0 cap hits in 365,414 (release 24 recipe on the same deals: 161 and 7).
- Threshold 1,000 vs 10,000, paired: `−0.0006 [−0.0026, +0.0014]` (no resolved difference), at 0.72× that arm's
  wall, with no decision over 9.9 s in those five windows.
- Twenty fresh windows of the M1 family, pooled against release 24: `+0.0140 [+0.0026, +0.0254]`.

### The soft head in the policy/value search (release 29)

![Release 29: the policy/value search as one package](../docs/visuals/pv-search-one-package.svg)

`8ecd4fea` is gen-3-warm's recipe (JS-M1 warm-started on the 256k afterstate corpus, residual trunk, outcome +
search-mean + points heads), but its policy target is the SEARCH'S PER-CANDIDATE VALUES (soft targets, T=1.0,
w=1.0), not the played action. One NumPy package (`soft-8ecd4fea.npz`, sha256 ccade130…) is both the admission
policy and the value evaluator of the W64/K8 search (`train/pv_search_policy.py`).

Evidence, in the order it was gathered (ladder row 7 has the caveats):

- Head alone vs SmartBot under public information: +0.052 [+0.039, +0.067].
- Whole search vs MC-LCB in the ladder: wins at W16, W32 and W64 (W64/K8 +0.187 [+0.144, +0.231]); W4 loses.
- Vs the release-28 package in card play: +0.086 [+0.042, +0.131] on 800 matched deals; +0.122 [+0.079, +0.164] on
  fresh deals.
- More worlds beyond 64 not shown to help (see "Not taken" under the ladder).
- No head in the W64 family (JS-M1, JS-G1, gen-4 run 1, gen-3-warm) shown superior to it or to each other.
- Served with hybrid bury vs release 28 as served (five clean windows, 300 s cap): +0.049 [+0.003, +0.095], clear of
  zero narrowly; I² 49%. Released 2026-09-22 on that read.

### JS-M1 — the joint model (release 28)

![Release 28: one JS-M1 package proposes inside the MC shortlist](../docs/visuals/js-m1-one-package.svg)

`a5248cc5` is M1's recipe (residual d4 trunk, 176k afterstate corpus, outcome + search-mean + points heads) trained
from scratch for 20 epochs, with a 54-card policy head at weight 0.2 and one root batch per value batch from the full
root-row cache (20.3M mover-encoded root decisions on the 140,800 fit deals).

- Offline: val CE 0.5957 (M1 0.5975), regret@4 0.0306, holdouts at or better than M1.
- Policy head on the 15,517 common test-deal rows: listwise CE 0.858 (prior v3 0.975). Top-64 recall is
  non-inferior to the separate prior on four of five strata and better on the two wide partial strata; the 10k+
  stratum (67 deals) is unresolved.
- In play as one net (five capped windows, seeds 13260910..13660910): `+0.0239 [+0.0005, +0.0472]` vs the release
  24 recipe (nominal, shared-control seeds); paired `+0.0057 [−0.0163, +0.0277]` vs release 27 at the same decision
  wall (no resolved difference, not an equivalence result); 0 decisions over 60 s in those windows.

Served as one NumPy package (schema v2 with the policy head, `server/shengji/ai/cwv_numpy.py`); the prior admission
loads the same file as kind `joint-numpy`. Earlier joint attempts from M1 on 1.0M root rows (J1 weight 1, J2 weight
0.2, J3 stop-gradient) all trailed the separate prior offline; training from scratch on all root rows closed that
gap.

What was read afterwards (the scaling log, `docs/scaling_log/models.py`, rows JS-M1, JS-G1 and gen-1):

- The owed fresh-seed read (lane v24, 2026-09-17, five fresh windows 16260910..16660910, paired against release 27
  at the same admission threshold): `−0.0159 [−0.0383, +0.0065]`, inconclusive with a negative point. The nominal
  `+0.0239` did not confirm, so release 28 carries no strength claim (ladder row 6). The scaling log records no
  ten-window read of JS-M1.
- JS-G1 (the grid trunk on the same data, sealed 2026-09-16): `+0.0184 [−0.0056, +0.0425]` against the capped
  control on five windows, and `−0.0051 [−0.0286, +0.0184]` paired against JS-M1; both inconclusive, at 1.32× the
  decision wall of M1 + prior at the same threshold. Not promoted.
- The JS-M1-teacher corpus runJS1 completed (16,000 clusters) and went into gen-1, which was inconclusive in play
  (`+0.0136 [−0.0085, +0.0357]`, five windows).

### Serving qualification — every deploy

For the `pv-search` mode (production since release 29; the gate as `DEPLOY.md` records it for releases 29–38):

1. Package on the volume, SHA256-verified. CI also fetches the pinned production package and loads it on the tree
   (`.github/workflows/pr-checks.yml`), and `server/tests/test_bury_fly_config.py` pins the served name that the
   `fly.toml` environment derives.
2. Server-path smoke (`server/scripts/cwv_serving_smoke.py`, which also builds the `pv-search` bot when
   `SHENGJI_PV_CKPT` is set): build the bot from the `fly.toml` environment exactly as the server does and play
   bury and play turns through `_paced_bot_step` / `_commit_bot_turn`, on the merged tree against the exact
   package. Release 25 passed the decision-identity gate yet stalled every live bot turn because nothing took
   this path.
3. For a strength change, the served-bot screen against the current production release.
4. Jerry's go; then `/healthz` (the name and the `pv_search` block) and a live room's log showing a bot bury and
   bot plays completing.

For a shortlist package (releases 22–28, now the rollback path) there is one more step before the smoke: the
decision-identity gate (`server/scripts/cwv_serving_gate.py --serving --threshold 1000`). The NumPy packages must
reproduce the Torch checkpoints' decisions (action, RNG state, shortlist and means, admission trace) on 60 rounds
at the serving recipe, prior exercised. Near-tie reorders with the same play are reported separately, never folded
into "identical". Its serving scope is the W32/N30 shortlist recipe; it last ran for release 28 and `DEPLOY.md`
records no run of it for a `pv-search` release.

### Hybrid bury integration — deployed

PR [#323](https://github.com/jerryyyu/shengji/pull/323) merged at `ec7f27ad`. Historical: it first shipped in the
shortlist era as `mc-shortlist-fd6bb411-w32-r55d379a3-bury-hybrid-c93a9877ae6a`: unchanged compact package
`fd6bb411` / source `3cd27716`, plus a 2-second cooperative deadline and heuristic fallback that the research
recipe did not have. The same bury arm is still served. In release 38 the `pv-search` bot runs it
(`PVSearchBuryBot` in `server/shengji/train/pv_search_policy.py`, which reuses `CWVBuryMixin` from
`cwv_bury_policy.py`) on the production package's value head: `SHENGJI_PV_BURY_ARM = "hybrid"` with the 2-second
budget, the `-bury-hybrid-5517ddbd7457` part of the served name, including the release-30 fix (#607).
Exact numbers behind ladder row 3 (1,976 fixed deals, hybrid vs heuristic): `+0.03644` utility
`[+0.01164,+0.06024]`, `+1.62` pp win rate `[+0.56,+2.68]`. Kitty bonus of at least 80 occurred 4 times for hybrid
vs 0 for heuristic. [Final bury report](value-guided-bury-dev-2026-09-08.md).

### `mc-s0-report-lcb`

The former live champion, now the rollback/reference policy, in two independent search stages:

1. the complete `mc-strong` N=30 ballot/search nominates one challenger to the heuristic incumbent; and
2. the fixed pair is compared on R=300 fresh shared hidden worlds.

The challenger replaces the incumbent only when the one-sided paired lower confidence bound is at least zero
(equality accepted); short or invalid report folds fall back to the incumbent. Exact numbers behind ladder row 1:
`+0.338379 +/- 0.067706` signed levels vs `mc-strong` on 2,048 fresh clusters; collision-free matched extra-work null
`-0.019043 +/- 0.068270`. This establishes the registered one-round policy, not arbitrary extra search, as the source
of that gain. It was the first confirmed and deployed strength gain; ladder rows 2, 3, 4, 7, 9 and 10 record the
later ones.

## The shortlist era, condensed (releases 22–28)

**Design.** The model chose which moves deserved expensive search; the search decided. The value net ranked the
exhaustive legal set over 32 constrained sampled worlds; four alternatives plus the heuristic incumbent went to
production's N30/R300 Monte Carlo search (heuristic rollouts, paired-LCB report rule). Release 27 added a policy prior
that pruned positions above 1,000 legal actions to the union of per-world top-256; from release 28 one joint package
(JS-M1) was both prior and value net. Hybrid bury (heuristic candidates, model-scored, MC selection, 2 s budget)
shipped with release 22 and is still served in release 38 (with the release-30 fix, #607).

**What it measured** (signed levels per round, 95% paired-deal intervals):

| result | value | reading |
|---|---:|---|
| W32/K4 vs production N30/R300, 256 rank-2 deals | **+0.139 [+0.065, +0.217]** | the first learned win; 3.53× wall after decision-preserving engineering (2.849×, bit-identical) |
| K8 − K4, same deals | −0.057 [−0.113, −0.004] | keep K4 |
| W64 − W32; N60/R600 − N30/R300 | −0.043; −0.018, both crossing zero | more worlds or rollouts did not add |
| 13-rank check, 260 deals | +0.062 [−0.006, +0.135] | inconclusive across ranks |
| adaptive allocation; one extra guided trick; double shortlist; points leaf | all cross zero | depth and allocation inside the shortlist did not add |
| M1 (two heads, d4) on fresh deals | +0.021 [+0.004, +0.039] | the one confirmed model gain of the era |
| prior v2 paired vs M1; JS-M1 paired vs M1 + prior | −0.0003; +0.006, both null | releases 27 and 28 were cost and maintainability, not strength |
| warm generations 1–4 as packages | null (v33: −0.007 [−0.038, +0.024]) | 54–62% of deals tie: the instrument cannot resolve small heads |

Original readouts: `server/runs/cwv_full_legal_shortlist_dev_20260905.md` and the linked run records; scaling page
rows 22–38; atlas rows 6–38. No number here is a current production claim.

## Retired BELIEF policy boundary

BELIEF R4/R5 is closed (2026-08-31; reasons in the conclusions table). Any separately justified re-entry keeps this
contract:

- training may use true hidden hands as separately sealed privileged labels;
- runtime input is only what the acting seat can see;
- hidden-world twins with identical actor observations must produce identical runtime input;
- deductions and behavioral probabilities stay distinct;
- per-card marginals must be projected into legal, correlated complete worlds before search consumes them;
- the search remains final action authority.

An offline calibration result never authorizes a policy or a deployment. Design set and artifact inventory:
`docs_archive/BELIEF_V1_*.md`, `docs_archive/rl-plan-through-2026-08-15.md`, issue #217.
