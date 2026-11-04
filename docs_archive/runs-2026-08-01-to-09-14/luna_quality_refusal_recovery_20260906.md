# Fresh independent-position diagnostic: retain refusals and continue

## Narrow change

The reviewed #261 caller stopped the whole 52-deal/208-position panel after
one provider refusal. The installed-runtime attempt MJWX36 answered its
first compact1 request, then its second request timed out at 90 seconds.
Neither arm has a meaningful quality result. Both call records are retained.

`--continue-independent-refusals` is opt-in, leaving default behavior and
CLI budgets unchanged. It retains failed calls and all failed batch slots,
then visits the next position in the original deterministic schedule. It
does not repeat a request, replace a deal, change either teacher, or convert
a refusal into an accepted answer. Completed processing with refusals has
its own status; accepted/refused arm-position counts and known/unknown call
counts accompany every interpretation. There are 208 unique positions and
up to 416 arm-position answers, clustered into at most 52 deals.

Token/wall exhaustion and unexpected exceptions still stop new admission.
Known refusals and unsettled reservations remain charged. The #262 analyzer
reports paired missingness; neither complete-case results nor an absence of
a significant difference establish quality equivalence. Full-game collection
is untouched: a failed turn cannot be skipped inside a game's trajectory.

## Exact continuation plan (after consolidated review)

Jerry approved the previously proposed total ceiling of 6M tokens and three
hours directly in this thread on September 6. The original absolute deadline
is 2026-09-06 17:22:45 UTC. No reset or increased allowance is proposed.

- PT7u0N and qYM6l4 failed locally before Codex provider dispatch: the shared
  virtualenv's editable package lacked the watchdog module. Both attempted
  calls/logs remain intact and their 30k reservations remain charged: 60k.
- MJWX36 used the correct installed source and native CLI0.149.0; its first
  answer costs 10,065 reported tokens and its timeout reserves another30k.
- A new output directory will copy those two MJWX36 call JSON files exactly,
  with both originals, their hashes and the original config identity recorded
  in a small parent-provenance receipt. The original configs are not edited.
  The existing Pilot cache path checks packet hashes and reuses both rows
  without dispatch; the refused row remains refused.
- The new output's ceiling is 5,940,000 including the imported40,065. Together
  with the external60k reservations, the cumulative ceiling remains6M.
  Its wall allowance is only the remaining time until the original deadline.
- Same52 roots, same208 positions, same compact1/batch4 stage/arm schedule,
  model/medium/prompt/play-only tools and90s per call. One provider process on
  Mini, low-priority local CPU, no change to Claude's MPS training.
- Use `uv sync --frozen` in this exact checkout's server directory and its
  own `.venv/bin/python`. The watchdog intentionally removes PYTHONPATH;
  borrowing another checkout's editable environment is not supported.
- No automatic retry loop, no new population, no outcome-based selection,
  no production deployment. If the original deadline passes before review,
  do not launch or silently extend it; preserve the packet for a later explicit
  scheduling decision.

The saved-call analyzer remains the previously reviewed #262 code and will
run only in a free CPU window; it must not compete with Mini model training.

## Load-bearing checks

Default-stop and fixed-schedule continuation tests; failed-batch whole-slot
accounting; actual `Pilot.call` and `configure` paths with saved refusal and
unsettled reservation, forbidden provider dispatch, exact once charging and
unchanged saved bytes; existing packet/ballot pairing and analyzer tests.
This requests one source-plus-bounded-continuation review, not another freeze
or capacity review.
