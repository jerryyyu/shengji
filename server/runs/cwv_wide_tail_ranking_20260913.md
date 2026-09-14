# Wide-tail ranking implementation

Issue #397 / design review #398. Experimental, opt-in; not a production change.

The baseline remains W32: exhaustive legal actions, 32-world model ranking,
incumbent plus four alternatives, then MC selection and the report fold.
The new arm changes admission only when there are **more than 10,000** legal
actions. It scores every action on the first two sampled worlds, retains the
top 256 plus every original production-ballot anchor, and ranks that pool on
the remaining 30 worlds. Stable action keys break ties. No true hidden cards
are consulted. Normal-sized decisions retain the original ranking call.

## Deliberate refinement from the reviewed proposal

The final mean excludes the two coarse worlds. Reusing their scores after
selecting their winners would retain selection noise in the final ranking.
Remaining-world ranking does not fix model error or guarantee that a good
action survives the coarse pool; those are explicit strength risks to screen.
This is a policy experiment, **not** a bit-identical optimization.

Full-legal training-label capture is refused for this experiment: unrefined
actions do not have 30-world estimates. Per-decision receipts identify actual
coverage; no missing action is assigned a fabricated model label.

## Qualification and run order

1. Test actual candidate/factory wiring, unchanged small populations, disjoint
   world slices, anchor retention, finite receipts, and config reopening.
2. Review the source delta once. Profile saved outcome-blind wide positions
   (leads and follows separately), reporting ranking/total wall, CPU, model
   rows, memory, and shortlist overlap. The known 379,753-action follow is a
   debugging stress case, not an unbiased performance sample.
3. Run a fresh matched 64-pair screen versus flat W32 with the same checkpoint,
   bury policy, selection/report dose, and **300-second cap on both arms**.
   Report signed levels/round and paired uncertainty, total runtime, latency
   tails, cap incidence, and how frequently the wide path activates.
4. Only then consider controlled combinations with throw admission or
   corrected rollout. Include individual components; do not infer additivity.

Current corrected-rollout screens are unchanged uncapped runs and are not a
compatible control for the capped wide-tail experiment. Perf is reserved for
those runs followed by Claude's queued capped controls; do not overlap them.
No new scientific screen has been launched for this implementation.
