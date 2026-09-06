# Fresh matched PT-Luna quality experiment

Tracks the teacher-efficiency work separately from shortlist strength. This
is exploratory data/quality work, not a promotion or a retrospective claim
about the historical rollout-enabled teacher.

## Data first

Prepare 52 fresh production-played deals: 13 trump ranks, two banker seats,
two replicates. Secret material is SHA-256 of
`teacher-quality-matched-panel-2026-09-06-v1`, fixed before generation. Check
the derived deal seeds against the committed seed-window registry before
capture. Replicate 0 is fit; replicate 1 is validation. All descendants stay
with their originating deal. No replacement of failed or uninteresting roots.

Capture contested decision ordinals 0, 12, 24 and 36 using the existing wide
ballot, before the production action. Retain missing stages explicitly; at
most 208 positions does not mean 208 independent games. Production remains
the literal `mc-s0-report-lcb` continuation. Save private roots, snapshots,
ballots and complete engine trajectories; attempted throws and actually
accepted cards are distinct. Terminal outcomes may appear in the trajectory
but never select states. No LLM call is part of preparation.

Coordinate capture uses bounded CPU processes, one native numerical thread
each, progress per finished deal, and private atomic per-deal shards.
Completed shards reopen rather than replay. Failed shards remain visible
evidence; an interrupted, unpublished deal can be retried under this DEV
recipe. No one-shot test population or multi-pass reconstruction.

## Matched prompt comparison

Compare compact single-decision calls with batches of up to four independent
deals through the same `CompactBatchTransport`: same model, effort, prompt
template, information, ballot, and play-only tools. Group by stage; alternate
arm order. Each saved position starts with the same empty team memory. This
isolates batching; it is not an evaluation of game-long memory or planning.

Reuse the existing pilot's durable calls, pending reservations, cost accounting
and no-redispatch handling. Preserve every usable response and provenance,
including failures. Initial comparison bound: 6M reported/reserved tokens and
three hours; retained outputs remain useful at interruption. These are safety
bounds, not predicted spend or a scientific failure threshold.

The previous four-deal decision panel was too small: compact batch4-minus-1
per-deal proxy differences were 0, 0, -0.25, 0 (sample SD 0.125). At 52 deals
the plug-in standard error would be about 0.017, but four historical deals
cannot reliably establish population variance. Report actual game-clustered
uncertainty, missingness and continuation sensitivity; do not count stages or
rollout replicas as independent games. Use a bounded Monte Carlo bootstrap,
not the old four-game exhaustive Cartesian bootstrap.

## What remains required

Saved calls can be analyzed without contacting the provider:

```sh
python -B scripts/luna_quality_analyze.py --panel-root PRIVATE_PANEL \
  --calls-root SAVED_CALLS --out NEW_PRIVATE_ANALYSIS --workers 4 --max-seconds 120
```

The analyzer verifies the saved packet/action mapping, then evaluates the two
teacher choices and the recorded production choice in the same known world.
It uses `smart-all` as the primary fixed continuation and `heuristic-all` as a
separate sensitivity, never an average of the two. Each deal contributes one
mean difference regardless of how many captured positions survived. The
10,000-replicate deal bootstrap reports fit and validation separately, and is
independent of worker completion order. These are proxy diagnostics, not
optimal-action labels or gameplay results.

Each completed position is retained in a private shard. The wall setting is a
soft admission deadline: stop admitting work, drain already submitted finite
positions, and leave pending positions for the identical recipe's resume.
Progress reports missing, failed and completed positions; partial processing
does not publish a final manifest. Completed analysis reopens its shards
instead of repeating engine continuations. A final manifest describes the
saved-call population, not proof that every requested teacher call succeeded;
reported missing/refused counts must accompany any quality interpretation.

Decision agreement and continuation-based value comparisons are diagnostics,
not a substitute for paired gameplay. A separate rollout-enabled teacher arm
must measure the tool/planning gap without confounding the batching contrast.
The next gameplay comparison should use the same fresh deals, literal MC
opponents, both team mirrors, and retained journal recovery. Publish its
measured token/wall budget before expanding beyond this decision panel.

Retain all usable data, not just wins. Source states are production-played;
teacher choices are relabels, not Luna-played trajectories. Any later value
targets require a named common continuation rather than mixing arm outcomes.
