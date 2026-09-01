# PT-Luna Self-Play — fresh full-round state-source acquisition

Status: repaired design work only. This packet authorizes no Mini execution,
model call, value label, strength claim, gameplay change, merge, promotion,
retry, or deployment. It supersedes only the model-interaction contract of the
failed concurrent collector; the population, mirrors, Value-use boundary, and
all-false authority remain unchanged.

## 0. Failure evidence and redesign ruling

The exact `50d8a8c` capacity attempt failed before gameplay. Its sealed public
failure receipt (`37400c17bc6fb1fb24aa8cf8abf631e12c3eb0da52c35faecb25f8df335b6d63`)
records that the initial team-0 Luna process
was real, exited zero, and published a final message, but emitted only two
`agent_message` items and zero engine-tool operations. The peer was cancelled
before launch. Therefore peer waiting, turn alternation, mailbox concurrency,
and shared-game coordination were never exercised; serializing the same
model-authored tool loop would not repair the observed failure.

The prior `2394140b` PT-Luna0 run completed 52/52 roles because one Luna
process controlled one partnership while the engine automatically advanced
production opponents. It also pinned Codex `0.149.0`, whereas the failed route
ran under the current `0.150.1` Luna `code_mode_only` / `unified_exec` catalog.
The evidence does not identify how much of the regression is model behavior
versus runtime/catalog drift. No scientific run should be spent answering that
historical question.

The repaired contract instead makes a model message the intended interface.
Luna never owns engine progress and is never asked to invoke a local command.
The supervisor constructs the observation, executes bounded rollouts, commits
the selected legal candidate, journals the transition, and invokes at most one
model call at a time per game.

## 1. Purpose

PT-Luna self-play collects fresh, complete, full-information Shengji
trajectories for two bounded uses:

1. a state/proposal source for later engine relabeling in Value V2; and
2. an opened-development atlas of where a reasoning planner spends rollout
   work or chooses outside the production ballot.

It is not a value experiment. Luna outcomes, prose, confidence, and chosen
actions are never scalar value truth. A later Value consumer chooses at most
one state per independent deal using the shared outcome-blind selector and
relabels every candidate successor under one frozen engine continuation
policy.

This lane covers whole rounds from the first play through round end. It does
not substitute late-endgame states for full-game evidence.

## 2. Supervisor-owned turn RPC contract

Each played game has one engine-owned `Round` and two logical
`gpt-5.6-luna` planners at high reasoning effort. Agent A controls both seats
of one partnership and agent B controls both seats of the other. They are
identities and private memory streams, not concurrently running processes.

At each contested decision the supervisor invokes only the acting team's
planner. Forced single-candidate moves advance mechanically with zero model
calls. A model receives a canonical decision packet containing:

- coordinate, mirror, agent/team, acting seat, decision index and decision
  SHA-256;
- the exact perfect-information engine snapshot, public play history, team-
  relative utility sign, legal candidate list, and production-prior index;
- remaining per-decision, per-round, token, and wall budgets; and
- that team's last committed strategy memory, never its peer's memory,
  requests, usage, rollout choices, or output.

The state snapshot includes all hands, burial, trump, current score,
completed/current tricks, and turn state. It is Markov-sufficient. Cross-turn
memory is only a bounded planning aid:

```json
{"schema":"pt-luna-team-memory-v1","team":0,"revision":7,
 "bound_after_state_sha256":"...","strategy_note":"at most 2048 UTF-8 bytes"}
```

The note is private to one partnership, untrusted, and never legality or state
authority. A proposed update is staged during planning and becomes durable
only with a validated, committed play. Each next call receives the canonical
state again; raw chain-of-thought and a natural-language conversation are
neither required nor replayed.

### 2.1 Bounded message loop

The model returns one strict intent object echoing the decision hash:

```json
{"schema":"pt-luna-intent-v1","decision_sha256":"...","kind":"rollout",
 "candidate_indices":[0,1],"continuations":["smart-all","team-smart"],
 "planning_note":"..."}
```

or:

```json
{"schema":"pt-luna-intent-v1","decision_sha256":"...","kind":"play",
 "candidate_index":0,"confidence":"medium","planning_note":"..."}
```

Phase 1 permits `play` or one bounded rollout batch. The supervisor validates
and executes requested candidate/continuation pairs, then supplies the exact
results in a fresh call. Phase 2 again permits `play` or a second and final
new rollout batch. After that batch, phase 3 permits only `play`. Luna returns
candidate indices, never cards or mutations. Candidate zero remains the
production prior. The continuation names, maximum 16 new evaluations per
batch, two-batch decision limit, 32-evaluation decision limit, and 1,024-
evaluation round limit match PT-Luna0.

### 2.2 Current transport

The first implementation pins the ChatGPT-authenticated Codex CLI at `0.149.0`
and uses it as a message transport, not as an engine agent:

- one `codex exec --ephemeral --output-schema` call per RPC phase;
- model `gpt-5.6-luna`, high reasoning, ignored user/rule configuration;
- a fresh empty read-only workspace with no mailbox, engine tool, repo, peer
  path, hook, writable state, or world artifact;
- the complete decision packet supplied in the prompt; and
- acceptance only of one schema-valid final agent message.

Any command/tool event is a typed refusal even if the final message is valid.
The supervisor never parses a command result and exposes no engine capability
to the model process. The source review must bind the exact Codex catalog,
command, JSON schema, environment, output parser, and OS sandbox. A future
direct Responses API adapter may set an empty tool list and `tool_choice=none`,
but it is out of this implementation until API credentials, SDK/runtime,
model availability, pricing, and rate limits are separately measured and
reviewed. They are not assumed by this design.

With every tool-bearing feature disabled, this pinned CLI emits exactly one
pre-turn runtime diagnostic stating that Code Mode is disabled and will fail
closed. That item is not a model command/tool call. The parser requires the
exact diagnostic exactly once before `turn.started`; absence, changed text,
changed ordering, a second diagnostic, or any command/MCP/other item is a
typed refusal. The private JSONL evidence and its hash retain that proof for
independent reopening.

The current Codex structured-output subset requires one root object with every
property required. The transport therefore uses a closed provider-only object
(`pt-luna-provider-intent-v1`) containing both play and rollout fields. For a
play, the rollout arrays must be empty; for a rollout, `candidate_index=-1`
and `confidence="none"`. The supervisor validates those sentinels and
normalizes the provider object into the smaller logical intent above before
the engine can act. To make the 16-evaluation cap structurally reachable, the
provider schema admits at most four candidate indices and four continuation
names per batch. Duplicate values remain a local typed refusal; they are never
silently deduplicated. The source canary proved that `uniqueItems` itself is
not supported by this Codex schema path, so it is not falsely claimed as a
provider-side guard.

The supervisor may run independent games concurrently after capacity selects
a worker count, but at most one model RPC is in flight per game. No model-call
retry, game replacement, or partial-record deletion is allowed in the
scientific namespace.

The official canary and capacity census re-attest the exact runtime immediately
before publishing their final receipts, after all model work has completed.
Scientific collection performs the same live-runtime check before each game
manifest and before terminal publication. A changed source tree, Codex binary,
tool catalog, boot identity, or runtime receipt therefore cannot be represented
by stale opening-time provenance.

## 3. Fresh population and mirrors

The acquisition population is exactly 52 fresh deal clusters:

```text
13 trump ranks x 2 banker-seat representatives x 2 replicates = 52 deals
52 deals x 2 mirrored agent/team assignments = 104 played games
```

Mirror 0 assigns agent identity A to team 0 and B to team 1. Mirror 1 swaps
those identities while preserving the exact root. The two mirrors share one
`deal_cluster_sha256`; inference and all population counts treat them as one
cluster, never as two independent deals.

Deal/setup/policy/model namespaces are domain-separated from every PT, Value,
BELIEF, human, and strength population. Every coordinate has exactly one
domain-separated root seed; there is no rejection sampling, replacement, or
post-deal seed choice. Before any model process opens, a score-free root census
builds all 52 deal/declaration/bury roots and seals coordinate, trump
suit/no-trump, and root hash. The census must contain all five trump modes,
all 13 trump ranks, both banker partnerships, 52 unique root hashes, and exact
mirror root identity. Failure refuses the population before a model call and
requires a separately reviewed namespace/schedule; it may not search this
namespace for a passing replacement.

The population report stratifies trump rank, plain-suit/no-trump mode, banker
partnership, acting partnership, lead/follow, and early/middle/late round. It
does not make a separate strength claim in any stratum.

## 4. Private trajectory and public receipt

The private per-game evidence has two hash-bound parts. The state/proposal
trajectory binds:

- the complete initial world and burial;
- every pre-action engine state, acting seat, legal ballot, production prior,
  selected action, and post-action state;
- every decision packet, schema-valid planner intent, provider usage receipt,
  strategy-memory transition, rollout allocation/result, continuation
  identity, confidence, and process completion binding; and
- engine, source, native, Python, Codex, model/config, prompt, seed namespace,
  root, mirror, and agent/team identities.

Current `attacker_points`, kitty bonus, trick points, and winners are state,
not value labels, and must be present or mechanically derivable at every
decision. A separate terminal receipt binds final attacker points and signed
level outcome for corpus completeness and descriptive source auditing. It is
not part of the trajectory, is inaccessible to Value state selection, and
carries `value_label_authorized: false`; Value V2 relabels every selected
state under its one frozen engine continuation instead.

The bounded strategy note is a private future model input but never a numeric
target. Other private model prose, if any, is invalid under the response schema
and cannot support acceptance. The public receipt contains hashes and bounded
work, completion, failure, progress, resource, and stratum counts only. Public
bytes must reject hands, burial, candidate cards, prompts, strategy notes,
model text, response bodies, raw seeds, and world-generating metadata.

The first 16 smallest pre-play cluster hashes are the only Luna clusters
eligible for the D512 Value V2 diverse-fit slots; the first 32 are the only
ones eligible for D1024. Eligibility is frozen before play. Every required
mirror of an eligible cluster must complete and reopen. An incomplete cluster
is preserved but not replaced; it makes the corresponding Value tier
ineligible rather than silently selecting a different source.

## 5. Score-free Mini capacity census

Capacity is separate from the 52 scientific source clusters and cannot use
their namespace. Before the progressive census, one real nonterminal boundary
canary must open a natural state with more than one legal candidate, obtain a
schema-valid rollout intent, execute and return its results, obtain a legal
play intent, and commit exactly one engine transition. It must observe zero
model tool events, complete provider usage, unchanged engine bytes before the
validated commit, and exact decision/transition hashes. A deterministic
alternation canary must then complete at least four contested decisions across
both team identities with no peer-memory exposure and at most one in-flight
RPC per game. Neither canary retains outcomes or authorizes collection.

Only then may capacity run progressive game-worker arms `1, 2, 4, 6, 8`, with
exactly two complete capture-only games per worker at each reached arm. It
retains only completion and verification status, per-game and per-RPC wall
time, busy CPU, process-tree peak RSS, swap, actual process/schema/tool-event
counts, token-rate telemetry, prompt-cache telemetry when supplied by the
provider, and mechanics hashes. Outcomes, actions, trajectories, strategy
notes, response bodies, and caller-asserted provider capacity are discarded
and cannot choose the arm.

### 5.1 Pre-review casual transport measurements

These measurements are non-scientific implementation probes authorized only
after the design PASS. They carry no outcome or launch authority:

- under the exact pinned `0.149.0` runtime, the sealed real-state canary
  (`receipt_sha256=5d5ac97d...b71789c`) completed one rollout-then-play
  transition and four further contested plays across team identities
  `[1,0,1,0]`; all ten Luna RPCs emitted zero model tool events, changed no
  engine bytes before validated play, and reopened against the exact runtime;
  the first transition used 20,558 input plus 980 output tokens in 23.721
  seconds, while the four-decision check used 82,102 input plus 5,679 output
  tokens in 133.133 seconds;

- one real 27-candidate phase-3 decision with two engine-owned rollout batches
  returned one legal play, emitted zero tool events, changed exactly one live
  engine state, and used 10,581 uncached input plus 636 output tokens in 14.469
  seconds;
- the exact phase-1 rollout -> engine result -> phase-2 play path then passed
  with zero tool events and the durable three-stage journal, using 21,322
  uncached input plus 504 output tokens in 14.918 seconds across two calls;
- before that pass, casual attempts correctly refused an over-budget rollout,
  a rollout form violating the nonempty/unique candidate contract, and the
  unsupported `uniqueItems` schema before any engine play; and
- deterministic candidate-zero completion over all 52 schedule coordinates
  requires 3,189 contested decisions in one mirror (38 minimum, 61 median,
  74 maximum), hence at least 6,378 model RPCs for 104 full games before any
  optional rollout phase.

The capacity projection must use its measured full-game distribution, not
extrapolate a passing token/wall budget from one short canary. The figures
above make repeated scaffold cost a first-class kill condition rather than a
surprise during collection.

Stop before a larger arm at the first reached arm with any of:

- swap or actual process error;
- peak process-tree RSS above 85% of Mini physical memory;
- mechanics or sealed-byte drift;
- less than 25% deadline headroom at p95 game wall; or
- less than 70% scaling efficiency relative to the preceding arm; or
- measured concurrency below 70% of the requested arm (the receipt computes
  `observed_parallelism_milli = sum(completed game wall nanoseconds) * 1000 /
  arm wall nanoseconds`) or any expected subprocess/result is incomplete or
  unverified; or
- any tool event, schema/usage refusal, stale decision response, peer-memory
  exposure, or pre-validation engine mutation; or
- a 104-game projection with 25% headroom outside frozen wall or token budgets.
  A future separately admitted billed-API adapter must also freeze pricing and
  pass the same projection against a dollar-cost cap.

An arm is selectable only when the next larger tested arm also passes the
empirical concurrency/completeness rule. The final tested arm is never
selected: if arm 8 passes, selection can be at most arm 6. The scientific
worker count is the fastest eligible passing arm, not automatically the
largest. It is frozen before the 52-cluster namespace opens. Capacity has its
own hard wall/token budget and may stop early while preserving every reached
arm.

Each arm also publishes its largest independently reopened per-RPC token use.
The scientific `per_call_token_reserve` is fixed to 125% of that maximum from
the selected arm; it is not an operator-entered estimate. Before any provider
dispatch, a shared atomic ledger durably reserves that amount plus the frozen
per-call wall allowance. Its immutable genesis binds the Mini boot, runtime,
capacity receipt, output namespace, monotonic start, scientific wall/token
caps, and both per-call reserves. Reopening with any different value refuses.
Ledger event elapsed times must be nondecreasing.

## 6. Progress, durability, and terminal routes

At least once per completed or failed game, publish:

```text
completed_games / 104
completed_deal_clusters / 52
percent_basis_points
elapsed_seconds
recent_throughput
eta_seconds
active_game_workers
active_model_rpcs
failure_count
```

Progress is operational telemetry, not evidence. Each game writes to a unique
partial directory, fsyncs its attempt before the first model call, seals its
private record independently, then contributes only its hash to the terminal
manifest. A controller death preserves sealed game records and publishes the
exact incomplete index set; it does not authorize retry under the same
admission.

Every immutable file uses one shared same-directory staged-write protocol:
write and fsync a hidden partial, hard-link it atomically into the final name,
fsync the directory, then remove the partial. Thus the final name is either
absent or contains all reviewed bytes. A complete staged journal record is
validated and promoted on restart; an incomplete staged journal record refuses
before another provider call. Deterministic terminal/progress bytes may repair
an incomplete stage, but no provider response is reconstructed or retried.
Death after the hard-link but before partial-name cleanup may leave both names
for the same inode. Restart accepts only that exact two-link, same-owner,
same-mode, byte-identical state, removes the partial name, fsyncs the directory,
and reopens a one-link final file. The same recovery applies to every global
budget-ledger reserve and settlement event: a complete pre-link partial is
promoted, the exact post-link two-name state is finished, and a truncated or
unrelated partial refuses. Tests kill both before and after the link for
terminal, journal-response, reserve, and settlement publication and require
zero duplicate provider dispatches and exact reopened accounting.

Within a game, every contested decision uses a three-state write-ahead
journal:

1. `decision-open`;
2. `model-response-sealed`; and
3. `transition-committed`.

A crash after step 2 replays the already-sealed response without another model
call. A crash after step 3 reopens the committed transition and continues. A
crash with a model call in flight and unknown disposition seals the game
incomplete; it does not issue a second scientific call. Invalid schema,
timeout, non-zero process status, missing usage, tool event, illegal intent, or
stale hash leaves engine state and team memory unchanged and seals a typed
failure. There is no silent candidate-zero fallback.

When a rejected provider result contains parseable usage, its bounded raw
private trace, exact usage, tool count, and closed failure disposition are
sealed and the global ledger charges the actual tokens. When no response
usage is available, the full pre-dispatch reservation remains charged. A
restart replays that same disposition; it may not reclassify a provider or
privacy failure by inspecting a new exception message.

Terminal routes are:

- `COMPLETE_STATE_SOURCE_ACQUISITION`: all 104 games and 52 clusters reopen;
- `INCOMPLETE_STATE_SOURCE_ACQUISITION`: at least one planned game is missing
  or failed, with completed artifacts preserved;
- `REFUSE_MECHANICS_OR_PRIVACY`: any engine, hidden/public, identity, schema,
  or reconstruction invariant fails; and
- `REFUSE_RESOURCE_OR_PROVIDER`: a frozen wall, memory, token, provider, or
  capacity condition fails.

All routes carry an all-false authority map. None is a gameplay, value,
strength, promotion, or deployment verdict.

## 7. Review economy

This repaired design receives one design-only review before implementation.
After that, use exactly two execution review moments:

1. one source review of the supervisor-owned RPC driver, schemas, runner,
   capacity command, and can-fail tests; and
2. after the score-free capacity receipt, one narrow immutable population +
   runtime + launch-freeze review.

The official canary and capacity commands must each authenticate the same
append-only source-review marker from canonical `main` before creating their
work namespace. Both receipts bind that marker and the exact source-set hash.
The freeze builder reauthenticates it from the canonical remote and refuses a
capacity receipt from any other reviewed head. Scientific execution likewise
authenticates the exact freeze marker before opening its namespace.

Do not add a separate rehearsal after the capacity census. The source review
must include a bounded synthetic two-team end-to-end test that exercises both
logical planner identities with fake structured responders, forced and
contested actions, both rollout phases, round completion, every journal crash
boundary, sealing, reopening, progress, and terminal routing. Mutation tests
must make wrong team/decision/memory hashes, invalid candidate indices,
duplicate or excess rollouts, missing usage, double commit, opponent-memory
injection, and any tool event turn red. The launch review binds exact Git,
source hashes, Mini boot/runtime, native/Codex/model/catalog identities, root
commitment, worker arm, budgets, output namespace, and all-false authority
bytes.

The formal collection CLI enters through `run_population`; it cannot inject a
runner or ledger. The complete-schedule wiring witness executes all 104 slots
with internally owned execution objects, publishes one terminal, and reopens it
from a fresh instance with zero additional provider dispatches. Scientific lock
acquisition occurs in `run()`, after construction validation, so a rejected
constructor cannot strand the namespace. One supervisor instance admits at
most one active run and a formal instance is one-shot; restart uses a fresh
authenticated instance over the sealed artifacts.

This collector is a new planner arm. Its outcomes, wall time, and token use may
not be pooled with or described as policy-comparable to PT-Luna0 at
`2394140b` or the failed concurrent route. Within one fresh freeze, the 52
roots, two mirrors, agent/team swaps, ballot, continuation set, rollout limits,
and engine version remain internally paired and comparable.
