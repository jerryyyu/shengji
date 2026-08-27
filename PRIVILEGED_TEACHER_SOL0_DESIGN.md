# Privileged Teacher Sol0 — adaptive full-information planning diagnostic

Status: open-DEV mechanism design. This document grants no scientific,
strength, gameplay, training, promotion, deployment or merge authority.

## Question

PT-Full and C0 separated hidden-state quality from the policy that consumes it.
The exact hidden world repaired the deliberately collapsed single-world
control, but neither the unchanged production search nor C0's fixed
production/wide/Smart continuation recipes beat public production. C0-S was
the least-bad consumer and improved on C0-H, especially for the attacker role,
while banker-role planning remained materially negative.

Sol0 asks the next, narrower question:

> Can a reasoning planner that sees the exact world choose its own bounded
> engine experiments and convert that evidence into stronger full-round play?

It is a teacher-ceiling diagnostic. It does not put privileged information,
an external model, or this policy into production.

## Population and anchors

Sol0 reuses the already-open 26 PT-Full/C0 DEV roots. Every root is played in
both treatment roles, producing 52 Sol0 rounds. The immutable C0 report
supplies public-production **A**, exact-production **B**, and fixed-continuation
**C0-S** anchors. The runner also reopens the PT-Full parent and reconstructs
each root from the mode-0600 seed secret before any Sol0 play.

This reuse cannot support a strength claim or held-out confirmation. It exists
to compare consumer mechanisms without selecting another population.

## Planner and engine responsibilities

One ephemeral `gpt-5.6-sol` Codex session controls both seats of the treatment
partnership for one complete play-phase round. The session receives no direct
filesystem representation of the mutable Round. It interacts through a
mode-0700 canonical-JSON file mailbox inside its isolated writable workspace;
the local engine controller exposes three operations:

1. `observe` returns the exact current state, the bounded C0-H action ballot,
   prior public play history, remaining hands, burial and search budget;
2. `rollout` evaluates selected action/continuation pairs in the exact world;
3. `play` commits one candidate after normal engine legality checks.

The controller automatically plays production-policy opponents and forced
one-candidate treatment decisions. Sol decides whether another rollout is
useful, which actions to compare, which named continuation assumptions to use,
and when to stop searching. Production's candidate zero always remains on the
ballot and Sol may explicitly fall back to it.

The named continuations deliberately vary future-policy assumptions rather
than repeating an identical world:

- `heuristic-all`: current deterministic heuristic at all future seats;
- `smart-all`: current memory-aware SmartBot at all future seats;
- `team-smart`: SmartBot for the treatment partnership and HeuristicBot for
  opponents;
- `opponent-smart`: the reverse stress case; and
- `exact-endgame-smart`: SmartBot plus the existing bounded exact-endgame
  solver when the state is eligible.

An action/continuation pair is evaluated at most once per decision. Repeated
requests return the cached result and consume no additional rollout. This is
the central C0 correction: a known world creates no value from repeated
identical deterministic simulations.

## Budgets, stopping and fallback

The first DEV design freezes:

- at most 16 new action/continuation evaluations per tool call;
- at most two rollout calls and 32 unique evaluations per contested decision;
- at most 1,024 unique evaluations per round;
- at most 20 minutes of Sol wall time per role-round (the first sandboxed
  engineering handshake reached 26 contested plays in 10 minutes, so this is
  a pre-freeze measured completion bound rather than an outcome-dependent cap);
- exactly one external-model attempt per role-round; and
- at most two roots concurrently on Mini.

The session must finish the engine round. A malformed or over-budget tool
request is refused without changing the Round, logged as a rejected call, and
may be corrected by Sol. A timeout, model-process failure, controller invariant
failure, or unfinished round marks that record incomplete; it cannot be
silently converted to a completed production fallback or retried under the
same admission. Successfully choosing candidate zero is an ordinary, measured
abstention.

## Privacy and evidence

Sol is intentionally privileged during this teacher diagnostic. Exact hands,
burial, action cards, rollout values and model text remain in a mode-0600
private transcript tree. Public progress and the final report contain only:

- root/parent/model/prompt/runtime hashes;
- aggregate call, action-change, fallback, continuation and work counts;
- transcript and external-process-output SHA-256 bindings;
- terminal attacker points and signed-level contrasts; and
- all-false authority.

The Codex invocation is ephemeral, runs in an isolated temporary workspace,
and receives only the controller command. A one-time completion token is
returned only after the final legal engine play, so a model-authored
`complete` string cannot forge completion. Every successful or failed external
attempt seals the model output and controller transcript as private evidence.
The runner records the exact Codex
binary hash/version, model name, reasoning effort, prompt hash, source Git,
native binary and host. No raw hidden state or model response may enter the
public report or Git.

## Interpretation

The DEV ladder has three outcomes:

- positive mean Sol0 contrast against A, B and C0-S with nonzero planner dose:
  prepare a fresh 128-root balanced confirmation design;
- improvement over C0-S but not both A and B: retain the mechanism evidence,
  refine the planner/search interface on open DEV only; or
- no improvement over C0-S: close this Sol0 recipe and use its private
  transcripts to identify whether proposals, continuation assumptions,
  rollout discrimination or banker planning failed.

No result authorizes deployment or belief integration. A future public-belief
consumer must receive actor-visible state only and must be evaluated
separately. Sol0 exists to establish whether a strong privileged teacher is
available before attempting to distill one.

If Sol0 establishes a positive ceiling, a later PT-PlannerBench may replay the
same open-DEV protocol with Luna, Terra and Claude. That comparison must keep
the roots, ballot, engine tools, budgets and anchors fixed, and report quality,
completion rate, wall time and cost. It is not part of this first run.

## Review and execution

One consolidated source review covers the parent/root bindings, controller
state ownership, exact-state privacy, legal ballot, rollout/cache accounting,
budgets, one-attempt semantics, Codex invocation, private transcript modes,
public report closure and can-fail tests. If it passes, it may authorize one
26-root open-DEV Mini run. There is no rehearsal-review ladder and no fresh
population opening.
