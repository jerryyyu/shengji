# PT0 natural-endgame packet

Status: source/design draft. This file authorizes no execution, test opening,
merge, training, gameplay, strength claim, promotion or deployment.

## Question

On naturally reached late-game decisions, does an actor-legal action selected
by exact perfect-information continuation values averaged over compatible
hidden worlds outperform the current production decision on an independent
set of compatible worlds?

This is a bounded endgame-headroom question. It is not a whole-game strength
claim and it does not establish that a learned privileged policy beats
production. A positive result would justify the separately reviewed PT1
three-arm teacher-acquisition screen; a negative result would identify where
the current PT target or world distribution needs work before that expense.

## Natural state population

The packet drives exact engine rounds chronologically with the named
`mc-s0-report-lcb` production policy. Trump rank and banker are inputs fixed
before play; deals, policy RNG streams and retry order are derived from the
packet identity. Each rank/banker cell domain-separates its deal seed, so the
balanced grid does not replay one hidden deal under 26 public configurations.
A 256-bit capture secret is generated before review; only its SHA-256
commitment enters the public design. The secret is a mode-0600, single-link
freeze input and never enters result bytes. This prevents the result's public
state/value hashes from serving as an oracle over an enumerable seed list.
Independent reopening receives controlled read access to the committed secret;
it is not published or admitted to any actor/model input.
A state is eligible without examining its hidden strength,
future result, action values or a baseline choice:

- the round is in `play` and the actor is on turn;
- the largest remaining hand has exactly two or exactly three cards;
- the actor is in the requested banker-team or attacker-team role; and
- exhaustive legal enumeration exposes at least two root actions.

For the first packet the proposed closed grid is all 13 trump ranks, banker
seats 0 and 1, both roles and both remaining-hand horizons: 104 states. For
each rank/banker cell the first chronological eligible state is retained in
each role/horizon bucket. A fixed per-cell attempt cap refuses an incomplete
grid; no sparse bucket may be silently dropped or replaced after values are
seen.

These are realistic conditional round states: every deal, declaration, bury,
play and public deduction is produced by the exact engine and current policy.
Rank/banker balancing is deliberate diagnostic stratification rather than the
natural production frequency, so aggregate and natural-frequency claims must
not be conflated. Hand-built PT0 fixtures remain tests only.

## Compatible-world and evaluation split

For each state, `Memory(round, actor)` is constructed only from the actor's
hand and public history. The current MCBot sampler runs with strict observed
void enforcement and reconstructs complete engine-valid worlds. Every world
must:

- pass exact card conservation and hand-size checks;
- reproduce the state's derived actor-visible SHA-256;
- have a unique canonical hidden-world SHA-256; and
- be sampled without selecting or specially weighting the actual true deal.

Worlds are domain-separated before sampling into two disjoint cohorts:

1. **proposal worlds** select the canonical PT action from exact averaged
   signed-level values; and
2. **evaluation worlds** measure that already-selected action against each
   frozen baseline action.

The first packet proposes 16 unique proposal and 16 unique evaluation worlds
per state. Cross-cohort hash overlap, short population, relaxed-void world or
public-state drift refuses the state. Using the proposal worlds for both
selection and evaluation is forbidden because the resulting nonnegative
"regret" would be an in-sample tautology rather than evidence.

## Frozen comparisons and outputs

Every legal action is forced and continued to `round_end` by the existing
bounded exact-world session. The proposal action is the lexicographically
first member of the proposal cohort's exact information-set argmax. Baselines
are `heuristic`, `smart` and exact registry policy `mc-s0-report-lcb`; the
production policy is evaluated under four fixed, domain-separated seeds per
state so one lucky search stream is not the estimand.

For every state publish only actor-safe evidence:

- public-state SHA-256, trump rank, role, horizon and selection order;
- proposal/evaluation world-population SHA-256 and counts, never hidden hands;
- proposal argmax, per-action mean/variance and proposal/evaluation ranking
  stability;
- held-out signed-level delta
  `Q_eval(proposal_action) - Q_eval(baseline_action)` for every baseline seed;
- exact nodes/cache hits; the separate operational receipt reports elapsed
  time, percent complete and deadline headroom without entering deterministic
  scientific result bytes; and
- an all-false authority map.

The terminal summary reports the equal-state-weight mean held-out delta,
positive/zero/negative state counts, natural decision-flip dose, rank/role/
horizon slices and a 5,000-replicate fixed-seed state-cluster percentile
bootstrap interval. A truncated grid is descriptive only and emits no
bootstrap interval. Human states
are not part of this first packet; a later descriptive transfer packet may use
only human logs with complete server-side hidden truth and the same actor
information contract.

## Recovery, limits and interpretation

Capture proceeds one rank/banker cell at a time, checking the deadline before
every new engine round. Each scored state seals independently with its exact
inputs, proposal and evaluation world hashes, target, baseline choices, work
and source identity. Before importing any Shengji module, the runner requires
isolated `-P -B` Python, refuses `PYTHONPATH` and import shadows, and verifies
the exact clean Git head; the imported core must then resolve to that checkout.
Resume replays the committed secret and independently recomputes the entire
completed state prefix before trusting its bytes. That replay can repeat more
than the interrupted state and must be included in any future resume resource
budget. A deadline seals a valid `truncated_by_deadline=true` scored prefix and
cannot masquerade as a complete grid; expiry is honored only after the durable
prefix has been re-established, so no completed state is discarded.

The immutable packet review must bind the final source head, design bytes,
seed derivations, population size, strict sampler mode, world counts, exact
node bound, baseline identities/seeds, runtime/native hashes, wall/memory
caps, progress contract, output manifest and all-false authority map. Source,
population and freeze are reviewed together once. A PASS authorizes one
score-free Mini execution only. The first freeze must use `Restart=no` and say
explicitly whether any manual resume is authorized; runner support alone is no
resume authority.

A positive held-out endgame delta establishes realistic local policy
headroom, not that a privileged teacher wins whole games. The subsequent PT1
screen still requires three arms: production public information/current
policy, true hidden state/current policy, and true hidden state/improved
teacher. Only the last two contrasts separate value of information from
policy improvement.
