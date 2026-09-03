# PT-Luna play-only acquisition — simplified redesign

Status: implemented predecessor plus proposed resilient-acquisition amendment.
Section 10 supersedes the conflicting stderr, queue-cancellation, lineage, and
review statements below. This document authorizes no formal capacity run,
scientific collection, outcome opening, Value label, gameplay
claim, merge, promotion, retry of a spent namespace, or deployment. It
supersedes the model-interaction and capacity portions of
`PRIVILEGED_TEACHER_LUNA_SELFPLAY_DESIGN.md`; the fresh population, mirrored
assignments, private/public boundary, Value-use restriction, and all-false
authority remain unchanged.

Jerry separately authorizes the bounded casual probes in section 7 after this
design receives an independent review. Those probes are non-scientific, use
fresh casual namespaces, and cannot satisfy capacity or enter a training or
evaluation corpus.

## 1. Why the previous lane closed

The reviewed `d402bcb7` capacity attempt is terminally sealed at:

```text
/Users/jerryyu/.shengji-runs/pt-luna-rpc-d402bcb7-ladder-r1/capacity.json
file sha256: ceb91adf217c2f4f1ff059cae856e6137a5d647358d9dab9d2662746aaa0e052
receipt sha256: f8a899c90cc5556b362f4ec9aa796464a1cd36b0f9f27dc73f490304d02327a2
route: REFUSE_RESOURCE_OR_PROVIDER
```

The one-worker health arm completed 2/2 games. The four-worker arm completed
only 4/8 games. Two calls were rejected because a zero-exit Codex process
emitted nonempty stderr; one lacked the exact required completion telemetry;
and one public `journal-io` label was a wrapper-classification defect. Source
inspection proves that `FileTurnJournal.call()` caught a non-`TurnRPCError`
from dispatch/transport, sealed its original disposition privately, then
raised `TurnJournalError("planner transport exception")`. Capacity snapshotted
the wrapper rather than `pending_refusal_failure_disposition()` and deleted the
temporary journal, so the underlying exception is unknowable. This is an
observability defect, not evidence of filesystem corruption.

Reliability is not the only failure. Arm-four p95 game wall was 1,199.406
seconds. A four-worker 104-game run needs p95 at or below 886.154 seconds to
fit 26 batches plus 25% headroom inside 28,800 seconds. The measured projection
is 38,980.684 seconds (10.83 hours). Raw concurrency was healthy: four active
RPCs, 3.363 effective workers, 0.824 scaling efficiency, no swap, and passing
mechanics/RSS checks. More workers alone do not repair slow individual games.

The arm-four record contains 671 RPCs, 529 committed plays, and 138 successful
rollout-phase RPCs. Optional model-directed rollout phases therefore consumed
about 20.6% of observed calls. This redesign removes them from acquisition
rather than raising the wall cap to fit the failed recipe.

## 2. Narrow purpose

This lane collects fresh, full-information, whole-round PT-Luna trajectories
for later engine relabeling in Value-Afterstate V2. It tests whether a
reasoning policy supplies a useful, diverse state source. It is not itself a
value, policy-strength, or belief experiment.

The lane no longer promises a rollout-work atlas. If model-directed rollout
allocation is studied again, it uses a separate small development experiment;
it cannot block or contaminate state-source acquisition.

## 3. Play-only supervisor contract

The supervisor owns the engine, legality, state progression, private team
memories, deadlines, journaling, and sealing. Two logical `gpt-5.6-luna`
planners at medium reasoning control opposing partnerships. At most one RPC is
in flight per game; independent games may run concurrently.

Forced single-candidate moves advance mechanically with no model call. At each
contested decision, the acting planner receives the same canonical
full-information state, public history, private team memory, legal candidates,
production-prior index, identity hashes, and remaining budgets already defined
by the predecessor design. It returns exactly one closed object using the
existing nested production provider schema:

```json
{
  "schema": "pt-luna-provider-intent-v2",
  "decision_sha256": "...",
  "action": {
    "kind": "play",
    "candidate_index": 0,
    "confidence": "low|medium|high",
    "planning_note": "at most 2048 UTF-8 bytes"
  }
}
```

The supervisor binds the request to `intent_output_schema(packet,
allowed_kinds=("play",))`; the nested action is the production parser's only
permitted variant for this mode.

There is no `rollout` intent, continuation choice, second planning phase, or
model-owned engine tool. Candidate zero remains the production prior but is
not a fallback: invalid, late, stale, tool-bearing, or illegal output refuses
the game without mutating engine state or team memory.

One game refusal makes the terminal population incomplete but is local to that
schedule item. The supervisor continues the already-fixed schedule so later
independent games can finish and seal. It must not set the shared
controller-stop event or terminate active provider processes for a game
deadline. Controller death and exhaustion of the shared population budget
remain population-wide aborts.

All model calls use the reviewed supervisor-owned Codex transport. Exact model,
reasoning effort, CLI/catalog, schema, prompt template, environment, sandbox,
and parser are source-bound before formal capacity. A direct Responses API
adapter is out of scope.

## 4. Narrow availability redispatch

The scientific no-retry rule remains the default. A packet may be redispatched
only for exact Codex completion-envelope telemetry drift, before any engine or
memory commit.

A zero-exit provider process with a schema-valid final response, complete
usage, zero tool events, and intact identity bindings is accepted even when it
emits bounded stderr. Stderr is diagnostic evidence: its exact bytes and hash
are sealed privately, never exposed to the decision model, and never used as
decision authority. Stderr above the fixed 1 MiB evidence bound refuses.

At most two redispatches of the identical immutable decision packet are
allowed, for at most three total attempts. Every attempt has a unique ordinal,
retains its private trace hash and public typed disposition, and is charged to
the shared wall/token ledgers. No prompt, state, memory, candidate order,
deadline, model parameter, or parser byte may change between attempts.

The following are never redispatchable: nonzero exit, missing or malformed
model intent, tool event, illegal candidate, stale/binding mismatch, engine or
privacy failure, journal/seal failure, resource-meter failure, per-call or
game deadline, or any unknown exception. An exhausted eligible packet refuses
the game. There is no game replacement or seed replacement.

The journal must preserve the original sealed disposition when dispatch or
transport raises a non-`TurnRPCError`. A production-altitude witness injects
such an exception and requires the public metric to retain its original stage,
kind, type, and sanitized message hash after temporary-journal cleanup.

## 5. Population and outcome-blind routes

The full population remains 52 fresh deal clusters x two mirrored team
assignments = 104 whole games, with the same domain separation, all five trump
modes, all 13 trump ranks, both banker partnerships, and mirror-root identity
defined by the predecessor design.

The first 16 smallest pre-play cluster hashes remain the only PT-Luna clusters
eligible for the Value V2 D512 diverse-fit source. Capacity may select one of
three routes using resource/reliability measurements only, before any
scientific action or outcome is opened:

- `FULL_104_ELIGIBLE`: run all 52 clusters x two mirrors.
- `PILOT_32_ELIGIBLE`: run only the predeclared first 16 clusters x two
  mirrors. This is a D512-oriented state-source pilot, not a complete atlas and
  cannot later be described as the 104-game lane.
- `REFUSE_RESOURCE_OR_PROVIDER`: run neither population.

The route cannot depend on actions, outcomes, teacher advantage, Value
performance, or post-capacity operator choice. A separate immutable launch
freeze is still required after a passing capacity route.

## 6. Formal canary and capacity gate

One formal score-free attempt, in a fresh namespace, performs:

1. a natural contested-decision boundary canary proving one validated play,
   exact engine transition, private-memory isolation, zero tools, complete
   usage, and no pre-validation mutation;
2. a one-worker health arm with two complete play-only games; and
3. a four-worker arm with eight complete play-only games.

The arm-four run is selectable only when all eight games independently reopen,
no availability packet exhausts its redispatches, no non-availability failure
occurs, mechanics/privacy/RSS/swap checks pass, observed parallelism is at
least 2.8, and scaling efficiency relative to arm one is at least 0.70.

Capacity records per-attempt and per-game wall/tokens, first-attempt failure
incidence by the two eligible classes, redispatch count, exhausted count,
process-tree RSS, swap, CPU, active RPCs, provider/tool/schema counts, and exact
typed failures. It discards actions, outcomes, model prose, and trajectories.

Route selection then uses nearest-rank p95 complete-game wall (therefore the
maximum at n=8) with 25% headroom. All comparisons use integer nanoseconds;
the equations below are explanatory rather than a floating-point
implementation:

```text
full_projection_seconds = ceil(104 / 4) * p95_game_seconds * 1.25
pilot_projection_seconds = ceil(32 / 4) * p95_game_seconds * 1.25
```

- `FULL_104_ELIGIBLE` requires
  `p95_game_wall_ns <= 886153846153` and full projection <= 28,800 seconds.
- Otherwise, `PILOT_32_ELIGIBLE` requires p95 <= 1,200 seconds and pilot
  projection <= 12,000 seconds.
- Otherwise capacity refuses.

Neither route permits increasing worker count, wall/token caps, retry count,
or population after seeing the receipt. The pilot cannot be extended to the
remaining clusters under the same admission.

The scientific freeze derives its per-call token reserve from 125% of the
largest independently reopened capacity attempt and binds the measured
first-attempt/redispatch accounting. The full route retains the existing
28,800-second population wall. The pilot route binds a separate 12,000-second
population wall. Both retain the existing memory/swap constraints and publish
visible completed-games, cluster, elapsed, ETA, active-worker/RPC, token,
failure, and deadline-headroom progress.

The 1,200-second number above remains the outcome-blind p95 *admission gate*;
it is not the scientific game's hard deadline. The final pilot freezes a
1,800-second hard per-game deadline, a 50% tail margin over that gate. This is
also 65% above the largest completed Pilot-2 provider wall (~1,090 seconds)
and gives the healthy 78-decision tail that reached 1,200 seconds time to
finish. The population wall remains exactly 12,000 seconds and the scientific
token ceiling is the already-measured 25%-headroom pilot projection,
26,404,925 tokens. The earlier Pilot-2 freeze incorrectly copied the generic
1,000,000,000-token capacity ceiling despite Jerry approving 26.4M; its early
deadline refusal limited actual spend to 3.52M and masked the overly broad
guard. The resilient-acquisition route carries the same intended
26,404,925-token ceiling, so the transport and scheduling repairs do not
increase the per-route exposure. The per-call transport ceiling is unchanged.

## 7. Authorized casual probes after design review

These probes answer design questions only. They use fixed fresh packets or
roots outside formal schedules, `scientific:false`, aggregate
transport/resource reports, and no later source selection from actions or
outcomes.

### 7.1 Availability and concurrency probe

Run 24 fixed play-only decision packets once serially and once at concurrency
four. For the two eligible availability failures only, allow at most two
same-packet redispatches. Stop at 600 seconds, 650,000 charged tokens, three
first-attempt failures, any exhausted packet, tool event, identity drift, or
engine mutation.

This asks whether the observed provider failures concentrate under concurrency
and whether they are transient. Zero failures is non-reproduction, not a
formal reliability proof.

### 7.2 Play-only whole-game falsification

After the source implements sections 3-4 and passes focused tests, run two
fresh casual deal clusters with both mirrors: four concurrent whole games,
medium reasoning, and the proposed availability redispatch contract. Stop on
any exhausted packet, tool/privacy/mechanics failure, any game above 886
seconds, 4,000,000 charged tokens, or 2,400 seconds total.

The full-104 route remains plausible only if 4/4 games complete, maximum game
wall is at most 800 seconds, and no packet exhausts its redispatches. A game
above 886 seconds kills the full route at worker four; it does not authorize a
cap increase.

### 7.3 Conditional probes

Only if play-only is reliable but remains too slow may one paired low/medium
packet-timing probe run on 24 fixed packets. Low effort is retained only with
at least 20% lower p95 call wall and no additional refusal. Worker six is not
probed unless worker four is reliable and lands in the 800-900-second marginal
band; it must reach effective parallelism >=4.2, scaling efficiency >=0.70,
and no more than 10% p95 RPC degradation. Either change requires a new formal
source/capacity review.

## 8. Fault tolerance and stop rule

The predecessor write-ahead journal, per-game sealed artifacts, shared atomic
budget ledger, restart-safe publication, exact-byte reopening, and no duplicate
provider dispatch after a known response remain in force. A process death with
unknown call disposition seals that game incomplete; it does not use the new
availability redispatch path.

Two 32-game pilot attempts are already spent and are part of the next freeze:

- Pilot 1: terminal file
  `2e72102914bcf1e9ff262756aa33fad45a03f6213098a1982680ebc67f8fe7b6`,
  receipt
  `4a53e4d28a4ffcc8230a88db95510265f493665627b0084a374e99fe8a319766`,
  3,674,786
  ledger tokens, four completed games.
- Pilot 2: terminal file
  `d1cc5c135e6cbda02e58849e3cd420b10d34a42b3ef5a78498dca70bf2251f25`,
  receipt
  `c5034c2006f9f49355c29ee92debc6360a6f958cc23d573ecdf8dd95d43cad6c`,
  3,520,281
  ledger tokens, three completed games.
- Pilot 3: terminal file
  `eefa49c6031122822bfc4547206349972b7a33265a19ef2528fe67cf3efa3d53`,
  receipt
  `c76dedfc02de7001b791de77a1304303f82d97db25e03d51660063891153a7e9`,
  2,734,638 ledger tokens, three completed games. Its sole game refusal was a
  zero-exit, valid-final, zero-tool call accompanied by a model-registry
  refresh warning on stderr.

The exact combined accounting is 9,929,705 ledger tokens and ten completed
games. All three predecessor attempts are closed; there is no fourth attempt
under their lane.

The new route in section 10 is a source-defect repair with a fresh deterministic
population and namespace, not a retry or seed replacement under the closed
lane.

## 9. Review economy and authority

The resilient-acquisition route uses one consolidated exact-head source +
immutable-freeze review. It
carries forward only the exact sealed Pilot-2 capacity receipt
`1ba204ee855b0842a6388f243bb86a02eba6a22163b91cce9ac570b936470364`
from source `d126ad019e1175cd6fe7d0a296c911bf28ae8883`; its p95, route, workers, reserves, token
budget, and 12,000-second population wall do not change. No further canary,
capacity census, rehearsal, or separate integrity run is authorized or
needed. The consolidated review must witness the cascade wiring, deadline
separation, exact carry-forward receipt, closed-attempt lineage, bounded
diagnostic evidence, and independent-schedule continuation.

Do not add a separate formal rehearsal after capacity. Source tests must cover
play-only schema closure, forced/contested plays, both team memories, exact
redispatch eligibility, attempt charging, exhausted refusal, every forbidden
redispatch class, preserved underlying failure disposition, no commit before a
validated response, crash recovery, terminal routing, and complete schedule
wiring with fake responders.

Every capacity and collection terminal carries all gameplay-strength, Value
label, BELIEF integration, promotion, merge, deployment, and production
authorities false. A design PASS authorizes only the casual probes in section 7
under Jerry's separate authorization; it does not authorize implementation or
formal compute.

## 10. Resilient acquisition after the closed pilots

Pilot 3 established that the remaining stop was not a missing or invalid Luna
play: the provider exited zero, returned a valid final play, emitted complete
usage and no tools, and also wrote an unrelated model-registry refresh warning
to stderr. Treating every stderr byte as turn failure made a diagnostic channel
override stronger response evidence.

The new route makes two source changes:

1. bounded stderr is sealed as private diagnostic evidence but cannot veto an
   otherwise valid response; nonzero exit, timeout, missing or malformed final,
   tool use, identity drift, illegal play, and mechanics/privacy failures keep
   refusing exactly as before; and
2. a local game failure makes the terminal incomplete but does not cancel the
   rest of the predeclared independent schedule. Shared wall/token exhaustion
   still stops the population and terminates active calls.

The scientific ledger's `crossed` bit means only that the shared wall or token
budget was actually exhausted. A settled per-call, provider, schema,
mechanics, or game-local refusal remains charged and makes that game (and thus
the population result) incomplete, but it does not set `crossed`, reject new
packets from other predeclared games, or kill already-running peers. Terminal
ledger acceptance additionally requires that every availability refusal has a
later accepted redispatch and that no terminal refusal remains, so this
separation cannot turn an incomplete population into a successful one.

The route uses a fresh seed secret, census, 16-cluster/32-game mirrored
schedule, private/public roots, namespace, source claim, and freeze. It carries
the exact three closed predecessor terminal/receipt hashes and their cumulative
9,929,705-token/10-game accounting. `route_ordinal` is exactly 1,
`maximum_route_ordinal` is exactly 1, and
`retry_after_this_attempt_authorized` is false. No predecessor namespace or
partial game is resumed or selected.

The passed four-worker capacity receipt is carried only for worker, RSS, swap,
token-reserve, and wall bounds; the response-validity change does not add work.
One exact-head source+freeze review must verify the real warning witness, the
1 MiB stderr bound, every stronger refusal, the continue-after-local-failure
witness, the global-budget stop witness, fresh schedule identity, and the
closed predecessor lineage. On PASS, the route may execute once. There is no
extra rehearsal, census, or post-freeze review.
