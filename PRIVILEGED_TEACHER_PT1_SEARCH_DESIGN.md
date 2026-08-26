# Privileged Teacher PT1 — exact-world search acquisition

Status: proposed score-free design. This file grants no execution, merge,
gameplay, strength, promotion or deployment authority.

## Decision and scope

PT0 proved a small natural late-endgame ceiling over `heuristic` and `smart`,
but its production-MC contrast was inconclusive: mean `35/1664` signed levels
with a clustered 95% interval spanning zero. PT1 therefore has one primary
question:

> On fresh natural endgames, can a policy that uses the complete hidden world
> and exact team-optimal continuation select actions with higher held-out
> whole-round signed-level value than production `mc-s0-report-lcb` given that
> same complete world?

PT1 is search-first. The proposal permits acquiring a teacher by training or
search. This first step uses the already reviewed exact endgame solver rather
than another neural oracle. It does not reuse or extend the closed Suphx O0 or
O0-v2 scalar/margin recipes.

PT1 remains an offline teacher-acquisition screen. It does not create a
runtime-safe public policy. Information-set aggregation, public-student
training, gameplay search and whole-game strength remain later gates.

## Three arms and causal contrasts

Every arm starts from the same exact `Round`, acting seat, legal ballot and
root-policy seed. Every selected action is evaluated by forcing it in the same
true world and solving the remaining game with the same exact solver and
signed-level conversion.

1. **A — public production.** Unmodified `mc-s0-report-lcb` selects from the
   actor-visible state using its production constraint-consistent sampler.
2. **B — true-world production.** The same production decision machinery,
   `N=30`, `R=300`, ballot and policy RNG stream is used, but every accepted
   determinization is the exact true hidden world. No extra action, node or
   rollout budget is granted. This measures what the present policy can do
   when uncertainty is removed without changing its continuation logic.
3. **C — exact privileged teacher.** The complete true world is marked as a
   determinized world. `ExactWorldSession` enumerates every legal root action
   and solves the continuation with team-minimax signed-level utility. C chooses
   the canonical action with maximum exact value, using a shared transposition
   table and a frozen `250,000`-node cap per state.

The primary contrast is **C−B**, policy improvement after both policies receive
the same perfect information. **B−A** is the value of information under the
current policy. **C−A** is the combined offline ceiling. These contrasts must
never be pooled or substituted for one another.

C is deliberately best-affordable rather than work-matched: an offline teacher
may spend more work than production. PT1 nevertheless reports action count,
nodes, cache hits, wall time and exact production search counts per arm. A and
B are exact same-work controls. Later distillation or gameplay gates must price
the teacher's cost separately.

## Natural population

PT0 record bytes are not training or evaluation inputs. PT1 captures a fresh,
domain-separated population with a new committed secret and seed namespace.

The target population is **416 states**:

```text
13 trump ranks × 2 banker-seat rotation representatives
               × 2 actor roles (banker team / attacker team)
               × 2 remaining-hand thresholds (3 / 4)
               × 4 independent state replicates = 416
```

Each retained state comes from a distinct engine round seed and therefore a
distinct inference cluster. Capture walks the natural production policy until
the first ordinary-play decision satisfying its exact cell, exposing at least
two exhaustive legal actions, and reaching production's actual multi-candidate
MC search route. Tractor-locked leads and production ballots with at most one
candidate are structurally ineligible because they produce no A/B search work
receipt and therefore cannot answer the frozen teacher-versus-search estimand.
This predicate uses only the actor-visible Round and production candidate
generation; it runs no rollout and reads no arm outcome. Capture may not select
or drop a state based on an arm action, exact value, regret, solver work or
terminal result. Missing cells or an exact-solver budget refusal are explicit
run outcomes, never silent drops.

Four fixed, domain-separated production-policy seeds are evaluated per state.
C is deterministic and repeated only for paired accounting. Inference first
averages the four seed-level contrasts within a state, then treats the 416
states as independent bootstrap units. No seed or state can be promoted,
retried or excluded by result.

The 416-state choice is a power repair, not arbitrary scaling. PT0 had only 29
capture-round clusters for 104 records and its approximately `+0.021`
production-MC mean was not distinguishable from zero. Four fresh independent
states per cell materially increase between-state information; merely drawing
more compatible worlds inside the same 29 clusters would not.

## Exact mechanics and evaluation

For each state and policy seed:

1. freeze the exact public-state hash, true-world hash and canonical legal
   action population;
2. select A without allowing any true-world object into the public sampler;
3. select B through the same production route with a true-world-only sampler;
4. select C by exact enumeration in the true world;
5. force each selected action into an independent clone and obtain final
   attacker points from the same `ExactWorldSession` semantics;
6. convert points to whole-round signed levels from the acting team; and
7. publish only hashes, actions, exact utilities, work counters and grouping
   tokens. Hidden hands, burial, raw deal seeds and the capture secret remain
   outside the result packet.

The exact solver must prove C has zero regret on every completed state. A
negative C−A or C−B state value is a mechanics failure, not statistical noise.
Ties are retained as zero.

## Primary gate and diagnostics

The sealed result routes `PASS_TO_PT2_TEACHER_EVALUATION` only when all of the
following hold:

- the mean state-level **C−B** improvement is at least `1/100` signed levels;
- its one-sided 95% capture-state bootstrap lower bound is strictly positive;
- at least 24 of 416 states have strictly positive C−B value;
- C has zero exact regret and no negative C−B or C−A state;
- both actor-role means and both hand-threshold means for C−B are nonnegative;
- every arm, seed, action and work receipt reopens exactly; and
- every mechanics, leakage, population, deadline and authority check passes.

The `1/100` floor is below PT0's `35/1664` point estimate but prevents a
statistically detectable yet economically negligible teacher from advancing.
Rank-level values are reported with counts and intervals but are not thirteen
separate pass gates. B−A and C−A are descriptive causal contrasts and cannot
rescue a failed C−B gate.

The packet also reports action-flip dose, conditional value on flipped states,
terminal-point deltas, exact nodes/cache hits, public-versus-true-world action
agreement and per-rank/role/horizon distributions.

## Capacity, recovery and one-shot execution

Before a scientific freeze, Mini runs one score-free capacity packet over an
independent 416-state population with the exact scientific coordinate shape:
all 13 ranks × 2 banker representatives × 2 roles × 2 horizons × 4 replicates.
The distinct secret and selector namespace make those states disjoint from the
scientific population. The packet measures capture wall/CPU, all three
selection arms, exact evaluation nodes, peak RSS and artifact size while
retaining no action, score, point, hidden-world or raw-seed bytes. The immutable
wall, CPU, memory, node and byte caps derive from that receipt with a declared
reserve. A separate out-of-population
rehearsal must exercise one complete real process-pool wave through the natural
provider and evaluator while persisting only identity/resource receipts. Both
paths require `SHENGJI_FAST=1`, `SHENGJI_REQUIRE_VOIDS=1`, and successful
native activation; the presence of a native file alone is not runtime proof.

Before the one-shot namespace is initialized, the scientific capture secret is
used to freeze a complete 416-cell, score-free natural-population manifest.
The manifest binds every state key, round seed, capture cluster, public-state
hash, and true-world hash. Its exact canonical hash is carried by the freeze
and external review marker. Each scientific worker must reproduce its frozen
identity before any result group may seal.

The runner publishes a durable canonical record after every completed state,
plus percentage/ETA progress. Deadline expiry seals the completed prefix as
`truncated_by_deadline=true`; it cannot masquerade as a complete 416-state
result or pass the primary gate. A fresh freeze states whether manual resume is
authorized. `Restart=no` is mandatory for the first execution.
Any child or launcher failure instead publishes a sanitized immutable failure
receipt and changes progress to terminal `FAILED` before surfacing the error.
The receipt records the failed wave and durable prefix, contains no score,
action, or child-exception text, and permanently refuses resume under that
admission. A resource refusal additionally records every exceeded cap's name,
observed value, frozen cap and exact excess so a sizing defect cannot collapse
into an uninterpretable generic failure.

No R4 or R5 path, seed namespace, artifact, process, host lock or review marker
is imported. Mini is the only PT1 host. PT1 may run concurrently with R4 on
Strength Cloud and R5 preparation on Performance Cloud.

## Leakage and falsification requirements

The implementation review must include tests and removal mutations proving:

- changing hidden hands or burial cannot change A's selected-action bytes when
  the actor-visible state is held fixed;
- B and C do change on a legal hidden-world witness;
- A and B use identical production ballots, `N/R`, policy seeds, fixed search
  budgets and completed rollout counts. Sampler attempts and accepted-world
  counts are reported diagnostics, not parity gates, because public rejection
  sampling and the true-world sampler have structurally different attempt
  rates;
- a non-true determinization entering B is refused;
- C evaluates every legal action and an off-ballot action is refused;
- swapping A/B/C labels or signs changes a pinned result;
- the same exact evaluator scores all three selected actions;
- changing one completed record, checkpoint, population row, deadline receipt
  or manifest byte is refused;
- capture/result-dependent selection, state reuse and cross-split reuse are
  refused; and
- all gameplay, strength, promotion, deployment, retry and merge authorities
  remain false.

## Review and next decision

One consolidated source-and-freeze review binds the exact code head, this
design, population commitments, Mini runtime/native identity, capacity receipt,
caps, runner, progress/recovery contract, output manifest and all-false
authority map. No scientific run starts before that PASS.

A PT1 PASS authorizes only a separately reviewed PT2 evaluation of the accepted
privileged teacher against an incumbent/checkpoint mixture on fresh mirrored
deals. It does not authorize a public student. A PT1 null closes this bounded
exact-search acquisition recipe; it does not claim that all perfect-information
learning is impossible.
