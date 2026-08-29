# PT-Luna Self-Play — fresh full-round state-source acquisition

Status: design and implementation work only. This packet authorizes no Mini
execution, model call, value label, strength claim, gameplay change, merge,
promotion, retry, or deployment.

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

## 2. Two-agent game contract

Each played game has one engine-owned `Round` and two independent ephemeral
`gpt-5.6-luna` processes at high reasoning effort:

- agent A controls both seats of one partnership;
- agent B controls both seats of the other partnership;
- each process retains only its own within-game conversation and tool history;
- both receive the exact hidden world only through the bounded local tool;
- the engine owns legal candidates, rollouts, mutations, scoring, deadlines,
  and the final state;
- the non-acting agent blocks and cannot inspect or mutate an out-of-turn
  decision; and
- any process, deadline, tool, legality, or mechanics failure aborts the shared
  game, wakes both processes, and seals an incomplete record.

The runner starts both ephemeral Codex processes before the first contested
decision. Each has its own `codex exec --ephemeral` workspace, prompt, final-
message slot, and team-scoped file mailbox, with model `gpt-5.6-luna` and high
reasoning bound into the freeze. The two mailboxes share only the engine-owned
game coordinator. An out-of-turn `observe` returns `waiting`; a bounded
`wait` request blocks until that team acts, the round ends, or either process
fails. Neither process can read the other workspace, mailbox, transcript, or
memory. A synthetic source test must launch two fake planner processes
concurrently and prove turn alternation, failure wakeup, and one shared engine
mutation stream before the real Codex command is admitted.

Candidate zero is the production prior. The ballot, exact-world continuation
names, per-call limit, two-rollout-call decision limit, and round work limit
match PT-Luna0 unless the consolidated source review explicitly freezes a
smaller bound. Forced legal actions advance mechanically without an LLM call.
No process retries, game replacement, or partial-record deletion is allowed.

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
- planner/tool requests and responses, rollout allocations, continuation
  identities, confidence, and process completion binding; and
- engine, source, native, Python, Codex, model/config, prompt, seed namespace,
  root, mirror, and agent/team identities.

Current `attacker_points`, kitty bonus, trick points, and winners are state,
not value labels, and must be present or mechanically derivable at every
decision. A separate terminal receipt binds final attacker points and signed
level outcome for corpus completeness and descriptive source auditing. It is
not part of the trajectory, is inaccessible to Value state selection, and
carries `value_label_authorized: false`; Value V2 relabels every selected
state under its one frozen engine continuation instead.

Private model prose may support qualitative debugging but is never a model
input or numeric target. The public receipt contains hashes and bounded work,
completion, failure, progress, resource, and stratum counts only. Public bytes
must reject hands, burial, candidate cards, prompts, model text, completion
tokens, raw seeds, and world-generating metadata.

The first 16 smallest pre-play cluster hashes are the only Luna clusters
eligible for the D512 Value V2 diverse-fit slots; the first 32 are the only
ones eligible for D1024. Eligibility is frozen before play. Every required
mirror of an eligible cluster must complete and reopen. An incomplete cluster
is preserved but not replaced; it makes the corresponding Value tier
ineligible rather than silently selecting a different source.

## 5. Score-free Mini capacity census

Capacity is separate from the 52 scientific source clusters and cannot use
their namespace. It runs progressive game-worker arms `1, 2, 4, 6, 8`, with
exactly two complete capture-only games per worker at each reached arm. It
retains only completion, wall, busy CPU, process-tree peak RSS, swap,
provider refusal/rate-limit/error counts, tool calls, token-rate telemetry,
and mechanics hashes. Outcomes, actions, trajectories, and prose are discarded
and cannot choose the arm.

Stop before a larger arm at the first reached arm with any of:

- swap or provider/runtime error;
- peak process-tree RSS above 85% of Mini physical memory;
- mechanics or sealed-byte drift;
- less than 25% deadline headroom at p95 game wall; or
- less than 70% scaling efficiency relative to the preceding arm.

The capacity receipt must also demonstrate at least 2x provider-rate headroom.
The scientific worker count is the fastest passing arm, not automatically the
largest. It is frozen before the 52-cluster namespace opens. Capacity has its
own hard wall/token budget and may stop early while preserving every reached
arm.

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
active_model_processes
failure_count
```

Progress is operational telemetry, not evidence. Each game writes to a unique
partial directory, fsyncs its attempt before the first model call, seals its
private record independently, then contributes only its hash to the terminal
manifest. A controller death preserves sealed game records and publishes the
exact incomplete index set; it does not authorize retry under the same
admission.

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

Use two review moments:

1. one source review of the shared controller, schemas, runner, capacity
   command, and can-fail tests; and
2. after the score-free capacity receipt, one narrow immutable population +
   runtime + launch-freeze review.

Do not add a separate rehearsal after the capacity census. The source review
must include a bounded synthetic two-team end-to-end test that exercises both
model-process boundaries with fake planners, forced and contested actions,
round completion, failure wakeup, sealing, reopening, progress, and terminal
routing. The launch review binds exact Git, source hashes, Mini boot/runtime,
native/Codex/model identities, root commitment, worker arm, budgets, output
namespace, and all-false authority bytes.
