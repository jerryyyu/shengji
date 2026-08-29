# Privileged Teacher Agent1 — efficient planner benchmark and fresh confirmation

Status: Luna0 source-and-launch design plus a non-executable Sol1 follow-up
proposal. This change implements only Lane L. It grants no execution, merge,
gameplay, training, strength, promotion, or deployment authority.

## Motivation and prior evidence

PT-Sol0 completed 52 role-rounds over 26 open-development roots. Its sealed
means in signed promotion levels were Sol minus public production A `17/26`,
Sol minus true-world production B `37/52`, and Sol minus fixed privileged
consumer C0-S `23/26`. At the paired-root level Sol minus A was positive,
negative, or zero on `21/1/4` roots; Sol minus B was `20/2/4`. Both role means
were positive for every contrast.

Those are large mechanism effects, but PT-Sol0 was an opened-development
diagnostic rather than a preregistered confirmation. Its sealed public report
contains model wall time but no independently reviewable token receipt. Agent1
therefore makes no token-efficiency comparison or candidate claim. A future
token census would need its own privacy-safe, hash-bound receipt design; no
prompt, hidden card, model text, or completion-token byte may enter a public
artifact.

Agent1 therefore separates two questions and two populations:

1. **Luna0 efficiency benchmark:** can a lower-cost planner retain useful
   privileged-play value under the exact already-open PT-Sol0 roots and tool
   contract?
2. **Sol1 confirmation:** does the Sol effect reproduce on a fresh,
   preregistered root population?

Luna0 may inform later model choice, but it cannot alter Sol1's population,
gate, prompt, budget, sample size, or primary estimator.

## Lane L — Luna0 matched opened-development benchmark

Luna0 reuses all 26 already-open PT-Sol0 roots and both treatment roles, for
52 paired role-rounds. It uses the exact same:

- hidden roots and A/B/C0-S parent records;
- expanded legal ballot and candidate-zero production prior;
- five exact-world continuation names;
- two rollout calls per decision, 16 new evaluations per call, 32 per
  decision, and 1,024 per round;
- 1,200-second role-round deadline;
- byte-identical planner prompt and tool instructions; and
- engine, native binary, Python, Codex binary, and tool protocol.

The only treatment difference is planner model identity:
`gpt-5.6-luna` at reasoning effort `high` instead of `gpt-5.6-sol` at `high`.
The frozen design binds the exact model token, effort, prompt SHA-256, Codex
version and binary SHA-256. A model substitution or inherited user config
refuses before a root is opened.

This lane is descriptive and uses no fresh scientific population. It reports:

- Luna minus Sol, A, B, and C0-S signed-level utility by paired root and role;
- completion and refusal counts;
- wall milliseconds, rollout/tool counts, action flips,
  outside-production-ballot selections, and confidence counts;
- raw model wall measurements and their descriptive cross-run ratio, explicitly
  labelled as confounded by host load and co-tenancy; and
- rank/role distributions without separate pass claims.

The report seals even when incomplete. An incomplete role retains only
outcome-free failure/work telemetry and never disappears. No retry or record
replacement is permitted. Because the Sol0 public parent has no reviewable
token field, Luna0 publishes no efficiency-candidate verdict; utility and wall
time remain separate descriptive measurements. It grants no authority and
cannot change Sol1.

## Lane S — Sol1 fresh confirmation

Lane S is a design-only successor and is not part of the Luna0 implementation,
launch packet, or review authority. It requires its own implementation and
future review after the descriptive Luna0 result is read.

Sol1 uses 52 fresh independent roots and both treatment roles, for 104
role-rounds:

```text
13 trump ranks × 2 banker-seat representatives × 2 fresh replicates
               = 52 root clusters
52 roots × 2 treatment roles = 104 role-rounds
```

The root secret, commitment, namespace, deal/setup streams and policy streams
are domain-separated from PT-Full, C0, PT-Sol0, Luna0, PT1 and every belief
population. The secret and raw seeds remain private. The public design contains
only the pre-execution commitment and derivation contract. Capture cannot
inspect an arm action, utility, rollout, token count, wall time, refusal, or
solver result when retaining a root.

Every root first produces fresh, common-root anchors:

- **A:** actor-visible production `mc-s0-report-lcb`;
- **B:** identical production machinery and work with every accepted world
  replaced by the exact true world; and
- **C0-S:** the frozen widened privileged ballot with SmartBot continuation.

Sol1 then uses the reviewed PT-Sol0 planner, model, prompt, tool contract and
budgets unchanged. All arms share the exact root and treatment role. Parent
generation and Sol execution are separate sealed stages; no Sol result can
change or regenerate an anchor.

The primary unit is one root: average the two role contrasts within the root,
then bootstrap the 52 roots. The confirmatory verdict is
`PASS_SOL1_PRIVILEGED_PLANNER_CONFIRMED` only when all conditions hold:

1. all 52 roots and 104 role-rounds complete with zero retry, replacement, or
   hidden drop;
2. mean Sol1-minus-B is at least `1/10` signed levels and its one-sided 95%
   root-bootstrap lower bound is strictly positive;
3. mean Sol1-minus-A is at least `1/10` signed levels and its one-sided 95%
   root-bootstrap lower bound is strictly positive;
4. both treatment-role means are nonnegative for both primary contrasts;
5. at least 13 of 52 roots have strictly positive Sol1-minus-B and at least 13
   have strictly positive Sol1-minus-A;
6. every parent, root, action, exact-world rollout, production-work receipt,
   model process, token receipt, summary, authority bit, and terminal byte
   independently reopens; and
7. no mechanics, privacy, population, native/runtime, deadline, or authority
   gate refuses.

If integrity holds but either efficacy contrast misses, the verdict is
`SELECT_NONE_SOL1_NOT_CONFIRMED`. Any incomplete record or integrity failure
routes to a named `REFUSE_*` verdict. Partial artifacts and completed private
receipts remain sealed for operational diagnosis, but no efficacy estimate
from an incomplete population can authorize another run or a claim.

Sol1 is still an offline privileged-teacher result. PASS proves that a bounded
reasoning consumer can exploit the true world better than production; it does
not prove a public policy, BELIEF integration, whole-game deployment strength,
or affordable inference. A later PT2 design must distill or approximate the
teacher under actor-visible information and must keep search as final
authority.

## Luna0 execution and review economy

Luna0 needs no separate scientific-capacity run. It reuses already-open DEV
roots, runs exactly two workers, and each of the 52 role-rounds has a hard
1,200-second model-process deadline. The mechanical upper bound is therefore
26 waves × 1,200 seconds = 31,200 seconds, plus bounded controller overhead.
An incomplete role is retained and the report seals `INCOMPLETE`; no retry or
replacement is allowed. This bound makes an additional outcome-blind rehearsal
less informative than launching the reviewed descriptive packet itself.

PT-Sol0 took 16,684.81 seconds at two workers for 52 role-rounds. At unchanged
per-role cost, Sol1's 104 role-rounds project to approximately 33,370 seconds
at the same two-worker topology; this is a sizing hypothesis, not a cap. Luna0
uses the identical two-worker topology and an independently measured deadline.
Because Sol0 and Luna0 execute at different times and Mini may have other work,
their raw wall ratio is descriptive and explicitly host-load-confounded. It is
not a model-efficiency claim or candidate gate.

Luna0 implementation, can-fail witnesses, its immutable design SHA, exact
parent/runtime/native/Codex identities, output namespace, two-worker topology,
deadline arithmetic, and all-false authority map enter one consolidated
source-and-launch review. There is no intermediate design or capacity review.
A PASS may authorize only the one non-retryable Luna0 execution. It cannot
authorize Sol1, another model, another population, replacement records, or a
strength claim.
