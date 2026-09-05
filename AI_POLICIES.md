# AI policy ledger

Last reconciled: **2026-09-04**. This file defines the current callable-policy
contract and the scientific conclusions that constrain policy work. It is not
a run log or policy registry duplicate.

- Exact policy implementations and names: `server/shengji/ai/registry.py`
- Production selection: `fly.toml`
- Current priorities and review gates: `BACKLOG.md` and `HANDOFF_ACTIVE.md`
- Research architecture and model lineage: `RL_PLAN.md`
- Immutable verdicts, hashes, and reviewer corrections: `HANDOFF_REVIEW.md`
- Engine and sampler contracts: `CORRECTNESS.md`
- Runtime performance and deployment: `PERF.md` and `DEPLOY.md`

Historical detail remains in Git history and `docs_archive/`. Do not append
dated status blocks here.

## Production contract

Production explicitly sets:

```toml
SHENGJI_BOT = "mc-s0-report-lcb"
SHENGJI_FAST = "1"
```

The server source fallback is `mc` when `SHENGJI_BOT` is absent. The named
production rollback is `mc-strong`; changing the default, rollback, N/R work,
ballot, sampler, continuation, or confidence rule is a new policy and needs
fresh evidence.

### `mc-s0-report-lcb`

The live champion uses two independent search stages:

1. the complete `mc-strong` N=30 ballot/search nominates one challenger to the
   heuristic incumbent; and
2. the fixed pair is compared on R=300 fresh shared hidden worlds.

The challenger replaces the incumbent only when the one-sided paired lower
confidence bound is positive. Short or invalid report folds fail back to the
incumbent. The fresh 2,048-cluster confirmation measured
`+0.338379 +/- 0.067706` signed levels against `mc-strong`; its collision-free
matched extra-work null was `-0.019043 +/- 0.068270`. This establishes the
registered one-round policy—not arbitrary extra search—as the only confirmed
and deployed strength gain.

## Callable policy families

`server/shengji/ai/registry.py` is authoritative when this summary and source
ever differ.

| family | intended use | current status |
|---|---|---|
| `heuristic` | Stateless legal baseline and stable Elo anchor. | Supported baseline, not production. |
| `smart`, `smart-v1`, `smart-v2` | Public-memory heuristics: card counting, boss/void inference, point flow, safe throws, ruff risk, bury and endgame rules. | Supported baselines and rollout policies. Exact lineage stays source-bound. |
| `mc`, `mc-lite`, `mc-strong`, `mc-vstrong` | Determinized Monte Carlo at named work levels. `mc` is the source fallback; `mc-strong` is N=30 and the production rollback. | Supported. A legal sampler is not a calibrated belief model. |
| `mc-s0-*`, nulls, prefix policies | Frozen search/report experiments and matched controls. | Experiment/reproduction only unless `fly.toml` names one. |
| structured-bury, exact-endgame, point-banking, pair/throw and ballot variants | Mechanism-specific experimental constructors. Some intentionally remain outside the global registry to preserve evidence identity. | No production authority. |
| learned checkpoint policies (`rl`, V11, teacher, Direct-Q and successors) | Offline diagnostics, bounded proposals/rankers, or explicitly reviewed experiments. | Lazy/opt-in only. No learned checkpoint is production-authorized. |
| `mc-cwv-<ckpt8>-w<W>`, `mc-cwv-prior-<ckpt8>-w<W>` | One-ply search whose ENTIRE evaluator is the complete-world value net (`ai/cwv_policy.py`): production's ballot and sampler, W sampled worlds, every (candidate, world) afterstate scored in one batch, argmax of the mean. The `prior` twin is the no-learning control (same positions, the training receipt's stratified prior as the value, in the prior's own utility scale -- PT0 integer levels for the training build's `baselines` prior, with exact terminals converted to match). Registered by `register_cwv_policies` or `SHENGJI_CWV_CKPT`; the checkpoint id is part of the name and a checkpoint whose encoder identity differs from `value_afterstate`'s is refused. | Dev screen only (`scripts/cwv_duel.py`, budget ladder 1x/3x/10x of production's wall). No strength claim; no production authority. |
| `mc-s0-report-lcb-x3`, `-x10` | Production with its selection and report doses scaled together (N=90/R=900, N=300/R=3000): production's own compute curve, the bar a learned arm must beat at each budget. | Reference arms for the ladder only. |

Example local selection:

```bash
SHENGJI_BOT=smart uv run shengji-server
```

Programmatic construction should always pass a deterministic policy seed:

```python
from shengji.ai.registry import make_bot

bot = make_bot("mc-strong", seed=1234)
```

## Search and heuristic behavior that survives

These are governing conclusions, not an invitation to reproduce old toggle
grids in this document.

- N=30 Monte Carlo clearly improved on the smaller base search. Uniform N=60
  did not establish another gain.
- The conservative disjoint R=300 report fold is the confirmed improvement.
  Alternative confidence and adaptive-allocation recipes did not establish an
  additional winner.
- The heuristic incumbent must remain candidate zero. Tractor-lock,
  point-shy near-tie handling, deterministic ballot order, and exact work
  counters are policy identity.
- Public memory may use declarations, plays, voids, remaining-pair/run bounds,
  actor-private hand, and banker-private burial where applicable. It may not
  read other hidden hands or a non-banker burial.
- Safe-shuai, boss/pair/tractor, point-flow, ruff-risk, void-building, and
  endgame heuristics are useful parents and diagnostics. Their presence is not
  evidence that every fallback is strong; production-policy quality gaps must
  be replayed and attributed to legality, ballot, world sampling,
  continuation, or value before patching.

The old exhaustive toggle table is preserved in Git history. Source owns what
is currently enabled; old head-to-head rates are screening evidence, not
production claims.

## Current scientific conclusions

| lane | conclusion for policy work |
|---|---|
| **RLCB** | Confirmed and deployed. It is the literal parent all strength challengers must beat. |
| **Global learned rankers / V11 / Direct-Q / teacher direct play** | Better label fit or isolated proposal signal did not transport into a stronger whole-game policy. Keep learned scores bounded to their reviewed role. |
| **S4 point banking, S6 shuai sourcing, pair-aware continuations** | Mechanisms were plausible or locally positive but no registered whole-game successor cleared the required bar. Do not revive them as unchanged retries. |
| **T4 model proposal** | Selected none. The uninformed widening control was positive against champion but used 14.8% more accepted worlds and 80.9% more searches; it requires a three-arm compute/candidate attribution test. |
| **BELIEF R4/R5** | R4's preserved synthetic-primary cohort reduced held-out count Brier by 21.40% versus REF-C, but the permuted-label control also improved materially and failed on demand — a predictive channel, not behavioral belief learning. The opened-DEV consumer diagnostic then sealed `NO_PRIMARY_POLICY_SIGNAL` (ESS 97–99.5% of maximum, 1/104 flips, paired value exactly zero). R4 is terminal; no R5 compute proceeds unless a separate oracle-belief probe shows a gain worth reopening. No BELIEF sampler, candidate, or policy is registered or deployable. |
| **PT0** | Privileged late-endgame policy had a small edge over heuristic/smart and an inconclusive edge over production MC. |
| **PT1** | Clean negative despite high action-flip dose: exact teacher guidance did not produce the required utility improvement. |
| **PT-Full** | A single true-world collapse was bad; repeated true-world search recovered most of that loss but did not beat the public ensemble. |
| **C0** | Fixed perfect-information consumer variants all lost to both required parents; local bare-point symptom fixes did not transport. |
| **Value-Afterstate V0** | `REFUSE_MECHANICS_OR_NEGATIVE_CONTROL` (2026-08-28, source `d9ad99f6`, independently verified): the first afterstate value screen refused on its own mechanics/negative-control gates; no value signal was established. |
| **Value-Afterstate V1 P1** | `SELECT_NONE_NO_ACTION_ADVANTAGE` (2026-08-29, reproduced exactly): the natural arm was the worst of four, beaten by two of its own negative controls. A clean learning null that motivated the V2 absolute-leaf redesign. |
| **PT-Sol0 / PT-Luna0** | First reviewed flexible-planner milestone. On the same 26 full-round roots and 52 mirrored treatment roles, Sol beat exact production arm A by `+17/26` signed levels per role and Luna by `+5/13`; both also beat B and C0-S on average. Luna was `-7/26` versus Sol, so Sol remains the quality teacher while Luna is the cheaper scaling candidate. This is open-DEV privileged-information mechanism evidence—not a registered policy, fresh strength result, or deployment authority. |
| **PT-Luna isolated (b0b1bd95)** | First COMPLETE terminal of the teacher lane (ledger `6c71bee3`): 32/32 games, 16/16 clusters, 0 failed, 21,979,625 tokens, independently reconstructed. Readable only for the scoped teacher/value research; label ingestion and training are separate gates. Four predecessor routes (30 games, 24,749,862 tokens) are engineering-only. Its planned use is diagnostic (where the flexible planner beats production, by mechanism) and as a fine-tuning/evaluation value target — not action imitation. |
| **Value V2 D64 (2026-09)** | Sealed `D64_DEV_SEALED` at exact source `11c43839` after 12 training epochs. On 12 natural audit deals, outcome-distribution RPS improved by `+0.006400834` (90% deal-bootstrap interval `[+0.002789151,+0.010361512]`; 4/4 members positive), but expected-value absolute error worsened by `-0.178319` signed levels (`[-0.306394,-0.037274]`) and paired action-sensitivity error worsened by `-0.045395` (`[-0.058033,-0.032902]`). Selected-action utility was inconclusive at `+0.0625` (`[-0.21875,+0.375]`) with 91.7% action-change dose and worst-decile utility `-0.8125`. This is small-DEV evidence of distribution-shape learning without calibrated scalar/action value, not a usable consumer or strength result. The frozen 256-slot ledger and 255 realized shards are coverage-audit evidence only; no missing-slot completion or slot-targeted D256 training follows. |

## BELIEF policy boundary

BELIEF is not a bot policy yet. Its current contract is:

- training may use true other hands and burial as separately sealed privileged
  labels;
- runtime input is limited to bytes legally visible to the acting seat;
- hidden-world twins with identical actor observations must produce identical
  runtime input;
- hard deductions and probabilistic behavioral evidence remain distinct;
- per-card marginals must be projected into physically legal, correlated
  complete worlds before search can consume them; and
- the first consumer reweights or samples worlds while the existing search
  remains final action authority.

An offline calibration result is only one prerequisite for a sampler
implementation review. A failed learning control blocks causal
interpretation even when the primary score improves. Neither result authorizes
a registered policy, whole-game strength claim, or deployment.

## Evaluation and identity rules

Every decision-bearing policy comparison binds:

1. exact source, policy names/classes, engine/native mode, and runtime;
2. ballot and incumbent identity;
3. sampler, continuation, objective, perspective, and deterministic seeds;
4. selection/report budgets and exact accepted-work counters;
5. mirrored roles/deals and the round/deal cluster as the uncertainty unit;
6. immutable population, split, artifact schemas, and terminal rule; and
7. a behavior/work-matched null that differs only on the proposed mechanism.

Elo pools, human agreement, individual decisions, offline loss, state regret,
and open-DEV screens prioritize hypotheses. Strength requires a fresh mirrored
whole-game comparison against the exact live champion, followed by confirmation
when the design calls for it.

## Correctness and runtime boundaries

- Tied effective cards retain physical identity; throws may be ruffed; failed
  throws force the engine-selected component; pair and follow obligations are
  engine facts, not heuristic preferences.
- The current sampler consumes public declarations, voids, remaining-pair/run
  bounds, hand sizes, and actor-known burial once. Strict validity/support on
  named reservoirs does not prove posterior calibration or globally complete
  constructive dealing.
- Banker declaration pins must allow a declared card to be in the hidden
  burial when the rules permit it. Public failed-throw content is limited to
  what the engine actually broadcasts.
- `SHENGJI_FAST=1` routes through reviewed native kernels. Pure/compiled parity
  and bit identity are correctness gates; a speedup is not strength evidence.
- Production does not enable experimental posterior-changing sampler flags.
- Factory seeds must reach every stochastic component; caches use canonical
  keys and defensive copies; short/zero-work evaluations refuse rather than
  silently fall back inside scientific packets.
- Encoder identity includes semantics and transitive source bytes. Assets with
  private-kitty or other actor-visibility drift remain quarantined even when
  their tensor dimensions match.

## Change and deployment rules

- Name the literal parent; “current,” “MC,” and “champion” are not identities.
- Review scientific source/freeze once as one packet. Add another review only
  when the first finds a load-bearing defect or reviewed bytes materially
  change.
- Never use a rehearsal outcome to tune a frozen population, threshold, seed,
  or terminal rule. Rehearsal proves the mechanics path only.
- Correctness fixes, throughput gains, larger corpora, or better training loss
  enable a policy experiment; none counts as an AI win.
- No result may implicitly authorize merge, promotion, deployment, retry, test
  opening, or a different policy. Those authorities are explicit and separate.
- `mc-strong` remains the immediate rollback for production health regressions.

## Durable pointers

| topic | source |
|---|---|
| current queue | `BACKLOG.md` |
| active fleet and exact review asks | `HANDOFF_ACTIVE.md` |
| callable code | `server/shengji/ai/registry.py` |
| production config | `fly.toml` |
| model/belief/teacher design | `RL_PLAN.md` |
| immutable evidence and review corrections | `HANDOFF_REVIEW.md` |
| engine/sampler contract | `CORRECTNESS.md` |
| performance and deployment | `PERF.md`, `DEPLOY.md` |
| old policy/toggle ledger | Git history and `docs_archive/` |
