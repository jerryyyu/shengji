# Archived: Codex re-audit round 13 (2026-08-03 23:57) — RESOLVED

Every item closed by 06:10 on 08-04; the reply summarising the outcomes
stays live in HANDOFF_REVIEW.md. Kept verbatim because the two public-wire
reproductions and the seeding diagnosis are the valuable part.

## Codex re-audit — 2026-08-03 23:57 EDT (`1ea1b56`): frontend NO-GO; MC blocks not seeded

I reran the advertised gate: pure pytest 99/99, fast pytest 99/99, Vitest 7/7,
lint exit 0 (five Fast Refresh warnings), and production build green. The
green suite is real, but the conclusion that all eight frontend P0s are closed
is not. Two public-wire reproductions fail outside the tests:

```text
CREATE_REFRESH_NO_TOKEN {'you': 1, 'seat_count': 2, 'creator_gen': 0}
BEFORE_STALE_LEAVE {'connected': True, 'gen': 1, 'room_exists': True}
AFTER_STALE_LEAVE {'connected': False, 'seat_count': None, 'room_exists': False}
```

### Frontend/lifecycle blockers

1. **`create_room` still bypasses `_attach`.** It manually installs a queue and
   writer at `server.py:724-732`, never increments `gen`, and never sends the
   `resume` token. Consequently a normal creator has no token in localStorage.
   Refresh while the old socket is open appends the same person as seat 1 in a
   pre-game lobby; the reproduction above used only real TestClient sockets.
   Route creation through `_attach` and test create -> receive wire token ->
   overlapping refresh through the exact client message path.
2. **A displaced socket is still authorised.** `_attach` cancels its writer but
   does not close it or reject inbound messages whose `my_gen != me.gen`.
   `leave_room` calls `_detach(me, room)` without the socket generation. In the
   second reproduction, the old socket sent `leave_room` after a successful
   token resume; it detached the new connection and deleted the lobby room.
   The old socket can also submit game actions. Generation-check every inbound
   member action, pass `my_gen` on explicit detach, and close/reject the stale
   endpoint. Test stale `play`, `chat`, and `leave_room`, not a direct helper
   call.
3. **The 25x race test does not exercise either bug.** It reads `seat.token`
   directly from server memory (instead of receiving it after creation), calls
   `_detach` directly, and never makes the stale socket send a message. Worse,
   `test_resume_token_beats_name_identity` says an impostor “must not seize” a
   seat, then line 464 asserts that the impostor *does* get seat 1. Name fallback
   still grants the actual token to anyone using the disconnected owner's
   case-folded name, contradicting “names are not identity.”
4. **Ownership transfer does not rotate the token.** Taking a dropped human's
   seat changes `name`/`is_bot` but leaves `Seat.token` intact. The former owner
   can later present the old token and displace the new connected owner. Rotate
   on any true ownership transfer; retain only on a resume by the same owner.
5. **The declared bot-cover contract was not implemented.** Every disconnected
   human is immediately `claimable`, yet their bot waits 30 seconds before its
   first action; `reserved_for` is the owner's display name, not a reservation
   deadline. Either explicitly adopt that house rule or implement the ship
   gate contract (bot controller promptly, owner exclusively reserved for the
   grace interval, generally claimable afterward). Do not mark this checkbox
   closed while behavior and criterion differ.
6. **P0-6/P0-7 coverage is incomplete.** The sole “connection intent” test only
   proves that `ws.ts` sends nothing on open; it never renders `App` or tests
   invite > explicit pending action > saved resume. There is no explicit
   pending-action state today. The protocol is also not actually exhaustive:
   `ErrorCode` is declared but `ErrorMsg.code` remains `string`; `controller`
   remains `string`; `ws.ts` retains `any[]` and `msg as any`; Lobby uses
   `Record<string, any>`; and App's switch has no exhaustive `never` branch.

Chat snapshot/id ordering looks sound, and the NPZ production parity work is
good. A concurrent soak is **not** the next gate: fix these deterministic
public-path failures first, then add a small multi-tab soak.

### ML/evaluation blocker — the seeding bug is still present

The urgent factory note was archived but never fixed. Exact current public-path
probe:

```text
mc_factory = lambda **kw: make_bot("mc")
MC_FACTORY_REPRODUCES False       # two `_seeded(factory, 123456)` RNG states
GATE_RECEIVED_SEED None
```

`_seeded()` calls `make(seed=s)`, but both duel scripts use `lambda **k:
make_bot(...)`; those lambdas accept and discard `seed`, so `_seeded` never
enters its TypeError fallback. `make_bot()` still accepts no kwargs. Therefore:

- every MC opponent in all `v11_extend.py ... mc` blocks is OS-seeded;
- the gated side's internal MCBot and its MC opponent are both OS-seeded;
- JOBS' claim that block 6 is deterministic and machine-independent is false.

The v11-vs-Smart result remains valid because SmartBot is deterministic. The
2,880-round vs-MC aggregate is useful exploratory evidence that v11 is close
to MC, but it is not the claimed reproducible seeded confirmation and must not
be promoted as such. Block 6 completed during this audit at 607-593 (50.6%);
**void it for the declared seeded protocol and do not pool it as confirmation**.
Forward kwargs (or pass registry factories directly), add a test through each
exact script factory, and rerun a preregistered confirmation.

The gated 55%-wall-clock claim also repeats the measurement issue already
raised: `gate_duel.py` times a mixed gated-vs-MC table, then runs a shorter
all-MC table later on different seeds and extrapolates it 4x. It records no
gate/MC call counts, policy-local latency, per-seed/flip data, or level utility,
and Wilson treats correlated mirrored rounds as independent. Keep 160-140 as
an encouraging screen, not a settled strength/latency result. Re-run with
fixed seeds, interleaved or in-round timing, matched MC-call-rate ablations,
and clustered records before claiming a Pareto improvement.

Finally, quarantine the still-registered `mc-vleaf-v11pair`: the measured 32.5%
is a predictable consequence of an invalid cross-state use of a pairwise head,
not evidence against learned leaves. `JOBS.md` also now contains three repeated
`## RUNNING`/malformed `## NOTES` blocks, so clean it after resolving the active
job; the monitor should have one authoritative running section.

## Jerry's tonight decision — 2026-08-04 00:12 EDT

I rewrote the canonical `RL_PLAN.md` roadmap into T0–T4 gates. The short
version: **no training or bulk data generation tonight.** The only long run
that may launch is a 1,000-cluster confirmation of v11 stakes-gated MC, and it
earns that run only after:

1. exact script factories reproduce with strict sampling;
2. a manifest/JSONL evaluator records paired level utility, policy-local
   timing/calls, and clustered uncertainty;
3. on untouched offline B, the v11 gate beats random and candidate-count gates
   at the same MC-call rate by >=15% missed-opportunity reduction, consistently
   across three blocks; and
4. a 150-cluster/arm online screen clears the prewritten strength, latency, and
   fallback bars.

If any gate fails, leave the machine idle. Do not substitute more v11 epochs,
a wider corpus, AWAC, PUCT, belief weighting, or another full v11-vs-MC block.

One correction to the current uncommitted seeding fix: wrapping
`factory(**kw)` in `except TypeError` is unsafe because it also catches a real
`TypeError` raised inside the constructor, retries `factory()` and can turn a
bot bug into another plausible fallback. Standardise/adapt the factory
signature explicitly. The test must repeat a complete small pairing through
the exact script lambda, not only compare two initial RNG states.

After tonight, the priority is: deployment Pareto table -> small controlled
representation diagnostic -> active high-N labelling -> root racing -> exact
belief sampler -> separate bracket-distribution V -> AWAC. The standalone line
is paused until the representation test moves untouched high-N regret.

---
