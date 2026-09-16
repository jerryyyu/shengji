# Bounded PUCT expansion storage

Opt-in `--compact-expansions`, stacked on #461. No production default or live
ladder change. The control and fixed bury evaluator are unchanged; the flag is
bound into the paired-screen recipe.

For a fresh tree with S sweeps, any node has at most S-1 visits before a
selection. Thus progressive widening can access at most
`ceil(widening * S ** widening_power)` actions. Preserve exhaustive enumeration,
the stable full sort, and the FULL softmax denominator, but retain only this
reachable prefix in each node. This is not a top-K renormalized policy.
Logical legal counts still report the exhaustive population.

The bound does **not** cover warmup-seeded or persistent trees. Combining with
#459 requires accounting for its additional visits and preserving warmup actions;
do not blindly carry this bound across that integration.

Validation: 43 kernel/adapter/factory/runner tests pass, including exact output
equality under uniform and non-uniform tied priors, widening powers .5/1,
S1/S8/S16, root reuse on/off, unchanged baseline, and recipe-resume refusal.

Real M1 fixture root0, W32/S32/D8, seed616092026, prior-v2, root reuse ON for
both arms; local Mac with peer work active. ABBA full/compact/compact/full:

| Pass | Search seconds | Retained node action entries |
|---|---:|---:|
| full | 30.4724 | 6,315,133 |
| compact | 28.4978 | 4,563 |
| compact | 28.9266 | 4,563 |
| full | 31.9383 | 6,315,133 |

All four complete result dictionaries agree after removing timing and storage
telemetry. Root has55,307 actions, retained width12; all legal counts, selected
actions, visits, values, leaf counts and prior-coverage diagnostics agree.
World digest `e3bffe83638fc077103b27bd5d6fc7d7b5fb6792572ed8139a6dee25e54ecfb2`.

This measures retained entries, **not peak RSS**: exhaustive enumeration,
temporary logits/sort/multiplicity arrays, and the root legality cache still
exist. Average time ratio is1.087x in this non-isolated diagnostic, not a fleet
throughput claim. Enumeration remains20.9–23.7s per pass versus leaf inference
about0.19–0.20s. No strength claim; fixed simulation semantics are unchanged,
but reduced runtime can change fallback incidence under a wall cap.

Reproduce with `server/scripts/cwv_puct_reuse_benchmark.py --optimization compact`
and the same checkpoint/prior/fixture arguments used for #458, adding
`--state 0 --sweeps 32`. The benchmark refuses complete-result drift.

## Fresh-process RSS follow-up

Same fixture/model/world digest and S32 recipe, one fresh process each using
`--passes off` then `--passes on`:

| Mode | Peak process RSS bytes | Search seconds |
|---|---:|---:|
| full | 918,880,256 | 30.6670 |
| compact | 427,343,872 | 28.5024 |

This is a measured53.5% process peak-RSS reduction on this saved state, including
model loading. It is not a universal memory ratio or a cloud worker-capacity
grant. Both processes used root reuse; no concurrent benchmark arms. Other Mac
work remains active. The single-pass receipts correctly report `exact_equal=null`
because they do not compare results in-process; the preceding ABBA test provides
the exactness evidence. The RSS field on multi-pass runs is explicitly a process
lifetime high-water mark and must not be interpreted as per-pass memory.
