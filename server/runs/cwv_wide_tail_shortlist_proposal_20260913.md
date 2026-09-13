# Wide-tail shortlist: coarse-to-fine ranking

Proposal for #397, linked to general performance #208 and model-to-play #389.
Design only: no current job, production default, or gameplay result changes.

Companion #396 proposes timeout-to-heuristic fallback. Keep that separate:
this proposal uses a deterministic public action-count trigger to reduce work
before timeout. A wall-triggered fallback varies with host contention; applying
it on both sides does not by itself preserve the original policy or pairing.
Neither a confidence interval crossing zero nor rare activation proves safety.

## Why isolate the tail?

The five-window census on #208 reports 866 of 268,184 decisions (0.32%) with
more than 10,000 legal actions consumed 26,737 of 92,572 seconds (29%) of
shortlist-ranking wall. That is not 29% of total screen time. One position
scored 379,753 actions on 32 worlds (12,152,096 rows), taking 4,822 seconds.
The retained snapshot for seed 13561373 / mirror 1 / seat 3 is a seven-card
FOLLOW after two plays, not an opening lead. Both leads and follows need study.

The source currently builds a finished-trick afterstate for every action/world
in `CWVShortlistBot._means`. Existing prepared-lead and successor/tensor caches
already handle reusable leaves; do not count those savings again. A prefix
profile was encoding-dominated while the later live stack was in trick
completion: sample multiple action/world blocks before claiming one cause.

## One initial arm, not a sweep

| Setting | First DEV recipe |
|---|---|
| Trigger | Exhaustive legal count strictly greater than 10,000 |
| Coarse worlds | First 2 of the ordinary 32 shared admission worlds |
| Coarse pool | Best 256 legal actions, plus every old MC-ballot action |
| Refined worlds | All 32, reusing survivors' first-2 sums |
| Final shortlist | Existing incumbent + 4 alternatives |
| MC selection / report | Unchanged 30-world selection / 300-world LCB |

For ordinary decisions, call the old path unchanged. For triggered decisions:

1. Exhaustively enumerate and deduplicate the same legal actions; retain their
   original indices. Generate the same admission-world RNG stream as W32.
2. Score **all** actions on the first two shared worlds. Rank by descending
   mean with original legal index as tie-break. Keep the top 256 and union the
   old MC ballot (including the incumbent), in original legal order.
3. Score only that pool on the remaining 30 worlds. Combine retained prefix
   sums with those scores; use the existing incumbent and alternative-selection
   rules on the refined means. Do not append anchors to the final five: they
   are protected from coarse pruning, not granted final admission.
4. Run unchanged MC selection and independent report. No throw-component,
   corrected-rollout, tie-rule or checkpoint change in this first comparison.

This costs `2*A + 30*P` model rows instead of `32*A`, where P is the union pool
size. For A=379,753 and P=256, rows fall about 15.8x; that is arithmetic, not
a measured wall speedup. Enumeration, sampling and MC still cost time.
Two-world pruning can discard a strong action; this is a policy approximation,
not an unbiased estimator or a decision-preserving optimization.

## Implementation and witnesses

Use an opt-in selector/config in the existing shortlist screen, not a new
runner. A small shared scoring helper may expose accumulated sums, but the
default call order/batch shape/RNG/output must remain unchanged. Bind trigger,
coarse-world count, pool size and anchor rule into the recipe identity.

Retain original legal indices, coarse/full world counts, retained pool, final
shortlist, per-phase model rows/walls and activation. Never publish two-world
discarded scores as full-32-world labels: full-score capture must carry explicit
per-action counts/partial markers or refuse this recipe. Preserve full legal
enumeration errors; do not silently substitute an iterator prefix.

Tests must witness unchanged default/below-threshold decisions, exact trigger
boundary, anchor retention, deterministic ties, survivor score arithmetic,
actual batch/rollout accounting and unchanged independent report. Also include
a fixture where the coarse pass misses the full-W32 winner: honest diagnostics
must expose loss, not only perfect synthetic examples. Do not use true hidden
cards to select candidates, worlds, or the trigger.

## Smallest useful qualification path

1. Reuse existing retained states/checkpoint and exact W32 admission seeds.
   Start with 8 distinct-deal tail roots, chosen by a fixed hash of public
   identifiers, round-robin across lead/follow and 10k–100k/>100k strata.
   Publish availability/selection before scoring; empty strata stay disclosed.
   The notorious saved root is a separate debugging case, not a hand-picked
   positive test. Reuse existing full-W32 scores if their source/model/worlds
   match; otherwise retain each completed reference once.
2. Compare final-shortlist coverage of W32 alternatives, final MC challenger
   changes, and shared fresh-report utility gaps. W32 is a reference policy,
   not ground truth. Record activation count, leaf/encoding cost, peak memory
   and per-root wall. Expand the state sample only if it informs a specific
   remaining question; do not spend days establishing exact reference ranks.
3. If no implementation defect appears, run one exploratory 64-deal fresh
   mirrored screen versus unchanged W32, plus up to 16 distinct tail-containing
   deals selected from the census without looking at outcomes. Report these
   populations separately; they are not a pooled population-strength estimate.
   Use the same fd6bb411 model and full-completion hybrid bury on both sides.
   This differs from Fly's timed burial fallback. Preserve the existing final
   gameplay metric: acting-team signed levels per round, uncertainty clustered
   by deal. A small null does not establish non-inferiority.

Run independent pairs/roots on available cores, one numerical thread per
worker. Queue after already committed #390/#395 work, or on a separately idle
host after coordination. Reuse existing atomic per-pair results and config-bound
resume; no new capacity ceremony or duplicate integrity passes. Initial 2-hour
cap per diagnostic/gameplay stage, no automatic extension/retry; publish partial
results and state what is missing. ETA must be updated from actual tail pace;
no defensible new-arm ETA exists yet. The reference itself may dominate cost.

Success means useful measured wall/makespan savings with no clear strength
regression in these screens; it permits a larger confirmation, not shipping.
Report p95/p99/max and worker idle tail as well as total wall: p99 alone can
miss the rarest expensive decisions. Exact engine/encoding work remains a
separate parity-tested track; do not mix it into this policy ablation.

## Review ask

Review the algorithm, partial-label contract and bounded qualification plan
together. Flag actionable defects or better cheaper comparisons. A design PASS
guides implementation; it is not a launch or production approval. Follow with
one consolidated implementation+screen review, not separate reviews for every
fixture or measurement. No changes to live windows.
