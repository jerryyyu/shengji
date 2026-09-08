# v3 turn-cursor ablation — not a new production model

Baseline: A+C+D+E+F2 value checkpoint `3cd27716`, encoder v2.
The first isolated feature is the next actor relative to the evaluating seat.
Empty-trick afterstates can have the same hand/point summaries but a different
team holding the lead. An MLP should not have to infer that from missing history.
This is a feature hypothesis, not an established cause of a gameplay loss.

## Source change

- Observation v3 is v2's 560 columns plus four next-actor one-hot columns.
  Complete-world public width is565, including the existing terminal flag.
- Live play uses `(round.turn - root_seat) % 4`; terminal states use four zeros.
  It adds no hidden information to the public plane. World inputs are unchanged.
- Reference/static paths, raw-record bridge, cache packing, and model loaders
  support v3. v1/v2 layouts, checkpoint identities and defaults stay unchanged.
- v3 cache/checkpoint identity additionally binds the versioned feature builders
  and legal helpers. Archived v1/v2 identities retain their narrower historical
  closure; accepting them is not permission to change their feature arithmetic.
- Existing v2 caches cannot supply the cursor. Rebuild from raw trajectories.

Validation: 80 focused tests passed on compiled engine, including a synthetic
raw store → cache → one-epoch CPU training → saved checkpoint → static inference,
whole-round reference/static parity, hidden-twin public identity, changed-turn
positive control, source-drift refusal, and legacy encoder/checkpoint tests.
Independent source review: PASS. This is mechanics evidence, not model quality.

## Cheap controlled comparison to prepare next

Use only deals from the baseline checkpoint's recorded **fit** population.
No existing validation/test or external Luna/human evaluation deals enter fit.
Select outcome-blind within sources; initial target768 distinct deals with
A/C/D/E/F2 counts64/256/256/128/64, preserving the baseline source proportions.
If availability differs, report it before changing the counts.

Both models start from scratch on exactly the same curated raw shards, local
deal split and seed1. MLP512→256, dropout0.1, AdamW lr0.0003, weight decay0.0001,
batch1024, auxiliary points weight1, validation CE selection, patience3,
maximum12epochs. Hold optimizer and target recipe fixed: only encoder differs.
These sub-splits are exploratory subdivisions of previously used fit data;
do not describe them as an independent confirmation of the baseline model.

Prepare data with bounded parallel workers; use Mini MPS for model training
after checking occupancy. Retain all epoch/checkpoint/corpus receipts. Do not
launch a broad retrain or reopen external holdouts for this first ablation.
Report measured prep/epoch times and ETA before expanding the experiment.

Read out validation CE **and** action-ranking regret/top-k coverage on shared
saved states/worlds, including empty-trick versus mid-trick strata. If the
feature shows diagnostic promise, compare the matched v2/v3 models in the
unchanged W32 consumer on opened DEV deals. Neither lower CE alone nor this
small dataset qualifies a model to replace `3cd27716` on Fly.
