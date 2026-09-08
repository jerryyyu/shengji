# CWV v2: keep MLP inference history-free

Status: isolated engineering candidate; no production/default-policy change,
training, live-screen modification or gameplay-strength claim.

## Finding and change

The v1 `mlp-static` adapter avoids constructing history that an MLP never
consumes. Version 2 instead called the full reference builder, including that
history, before `_stack(history_free=True)` discarded it. This is avoidable
inference cost, not evidence of incorrect v2 predictions.

The adapter now constructs its existing exact v1 MLP base and calls the
**canonical `value_afterstate_v2.widen`**. The resulting public tensor remains
561 floats: 531 v1 observation columns, all 29 v2 columns, then the terminal
flag. World and perspective tensors are unchanged. The fused builder itself
remains v1-only; a bare v1 tensor is still refused by a v2 model. Reference and
non-MLP routes retain full history. Frozen encoders, checkpoint identities,
training data and models are untouched.

The equivalence argument is structural: reference v2 is
`widen(reference_v1(rnd, seat), rnd, seat)`; static v2 is
`widen(static_v1(rnd, seat), rnd, seat)`. Canonical `widen` derives all 29
extra columns from the round, not the base tensor's history. Static v2 thus
**inherits the existing fused-v1 public/world/perspective parity guarantee**;
it does not establish a separate guarantee for that base. The existing v1
all-seat/depth/trump witness uses one deal seed (41). The new v2 parity tests
add three deal seeds, but neither finite fixture family proves all states.

## Actual-consumer measurement

The existing `cwv_prepared_lead_probe.py` supports `--optimization v2-static`.
Its baseline replaces only the v2 static call with the previous full-history
reference call. Both arms use the same checkpoint, W32 worlds, incumbent+4,
N30 selection, R300 LCB report, batch size 128 and successor reuse.

ACDEF-v2 checkpoint:
`3cd277160322b30e9a61d5d83cb7fb6bceac6887ab1e899b98a42f15b259d600`.

All 52 already-opened FIT roots were included, with two counterbalanced
repetitions. This is 104 paired decisions, not 104 independent games. No Luna
validation, new games, newly selected positions or changing checkpoint was
used. All score digests, batching, shortlisted actions, final actions, report
statistics, work counts, input state and RNG states matched exactly.
Because this consumer finishes the trick before scoring, its 16 trick-local
columns are boundary constants. This measurement cannot by itself rule out
mid-trick feature corruption; the canonical-widen argument above and separate
tensor parity witnesses support that claim.

| Total over the 104 decisions per arm | Prior v2 route | Static widening |
|---|---:|---:|
| Wall seconds | 22.3857 | 19.6837 |
| Process CPU seconds | 22.0314 | 19.4204 |

Observed wall throughput: **1.1373x**, or **12.1% less wall time**. The Mini
was contended by a five-worker gameplay screen and MPS training. This is a
fixed-state diagnostic, not an isolated whole-game benchmark or a universal
speedup guarantee. A preliminary encoding-only probe was 1.66x at roots and
2.17x at nonterminal finished states; those component ratios must not be
presented as end-to-end gains.

Evidence root:
`~/shengji-archive/2026-09-07/cwv-gameplay-precision.DE3xDH/`:
`v2-encoding-probe.json`, `v2-static-snapshots.json`, and the resumable
`v2-static-consumer/` with 208 atomic arm records and its summary. The adapter
and probe source hashes match the measured implementation. `cwv_policy.py`
received a docstring-only routing clarification during the probe; its loaded
executable behavior was unchanged. This is disclosed rather than rerunning
the experiment for a comment-only identity difference.

## Validation and use

100 focused native tests pass (82 existing regression tests and 18 new tests);
the new 18 and 50 core encoder/binding/fused tests also pass in pure mode.
Witnesses cover early/mid/late states, every actor seat, suited/NT modes,
invalid-state refusal, exact extra columns, full-history tripwires, actual
evaluator width refusal, actual LCB consumer outputs and non-MLP preservation.
The updated old routing test permits a fused **v1 base before widening**, not
a fused v1 row delivered as v2. Reference-context restoration is exercised at
the actual benchmark entry point.

The exported static builder is **MLP-only**, including v2. Its one-row zero
history passes structural tensor validation but is not a faithful history for
a sequential model. `CompleteWorldEvaluator.effective_encoding` keeps those
models on the reference route; direct callers must honor the same restriction.
Claude's independent source PASS at `eeb107ce` confirmed this composition and
requested these caveats; it did not rerun the benchmark or test suite.

Completed diagnostic arms reopen without replay; failures preserve completed
artifacts. No existing run should adopt this source halfway through. After
review, the change is suitable for future opt-in v2 MLP W32 evaluations or
data generation; it does not choose which model is strongest.
