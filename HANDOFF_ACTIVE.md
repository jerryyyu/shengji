# Active Claude/Codex handoff

> Current operational truth and review queue only. Historical reviews belong
> in `HANDOFF_REVIEW.md` and Git history. A request not listed here is not
> active.

Last reconciled: 2026-08-22 04:45 EDT.

## Immediate objective

Carry BELIEF V2/R4 to one independently reviewed scientific terminal result:
does the learned ownership model measurably improve held-out calibration over
REF-C? Offline evidence cannot authorize a sampler, gameplay/strength claim,
promotion or deployment.

## Live state — exact freeze review is the only launch blocker

| field | current binding |
|---|---|
| source | draft PR #123, exact head `d2d466f161eb8e55daf26677bfed361ad4110d7c` |
| source review | PASS marker introduced by `1b276b90ddb2fb3fd51f6e2b6c484d557fb556f3` |
| source ancestry | sole parent `55f50432c1dabe563cbd5dd0c1983815d65656a6`; reviewed cumulative delta base `656e6d0018a007f32f6b7a5f7bc113ca32dae6ce` |
| host | `shengji-cloud` / `ubuntu-32gb-hel1-1`, 16 logical CPUs |
| freeze | `/opt/belief-r4-freeze-d2d466f-r1.json`, SHA-256 `573fcade25d985f58c0d179a581a40619b5745fc2152c52f4740e1355ae1fc16` |
| review packet | `/opt/belief-r4-d2d466f-freeze-inputs-r1/freeze-review-packet.json`, SHA-256 `9c799bc9d6319adf034614e715da9bdf1b86979ae98a62a20677ae4a30eb8447` |
| scientific run | not initialized; evidence and ops namespaces absent; no scientific test split opened |

The source/design review is complete. The marker at `HANDOFF_REVIEW.md:3006`
authorizes fresh score-free receipts and one immutable freeze only. Fresh H0,
seed, capacity and deadline receipts were generated on the exact reviewed
checkout in the new `d2d466f-r1` namespace. Every input and the freeze is
root-owned, mode `0400`, link count 1.

Key closed values:

- H0 inventory/split SHA-256: `f1ddcd617dc9743d9d1357f09440c40fbf2eef29fc75ff7a8f00b41143a62071` / `f29dea82f4497ffe6ad0fea9ed1c143c4d4c9864bd8890e664cceb49ca3b72fd`;
- seed scan/registry SHA-256: `2f501d29bd963ded550be6e429e25822f2ff9495ba7defa9e833f2e8ca3211bf` / `eb86b594c85489f3614ea7b95ff7c30660f8b04adce5a027c27ab4cd238840ec`; 5,553 candidates, 31 populations, zero collisions;
- capacity/deadline SHA-256: `412ef67840d31fddb9420618382d3b9e55c134ce87357ed9461e62a6fbaccfc0` / `502c316dc1c5ebe6ad77db9a0ee2400b5f8523d4743eb533b0b2000127aaa1cf`;
- one mechanical caps file SHA-256: `7e59aa6cb8b199947963d9d2af9ff6d7060b1ab4c71c8d4528d0e71e0becc420`; measured capture projects to 63.48 core-hours and therefore derives cap 64, without an alternate cap file;
- expected review claim SHA-256: `9de3a91caeecfbfce24e799cee6e1e8f5d953618cbfab5b1e2ab3a10c0e16407`;
- supervisor summary SHA-256: `58dc98f9bcf51cec4ba9f394adb6301338c5669edb71d34047292b3cba99b218`;
- supervisor execution-plan SHA-256: `8ec0a642def62fd606092ff3c6557ac92872f87a6777210ab92eb52ec6d103b2`.

## Review queue — exactly one review before launch

### BELIEF V2/R4 exact immutable freeze — active now

Review exact source `d2d466f161eb8e55daf26677bfed361ad4110d7c`,
freeze `573fcade25d985f58c0d179a581a40619b5745fc2152c52f4740e1355ae1fc16`,
and packet `9c799bc9d6319adf034614e715da9bdf1b86979ae98a62a20677ae4a30eb8447`
on `shengji-cloud`. This is the only requested review. Do not reopen PR #123,
request another rehearsal, merge, initialize or execute.

Verify in one pass:

1. Reopen every packet input and the freeze byte-exactly; bind source-review
   commit `1b276b9`, H0 inventory/split, seed scan/registry, fresh capacity and
   deadline receipts, the single mechanical caps file, runtime/native/Python/
   Torch/NumPy/boot identities, and unused evidence root
   `/opt/belief-r4-evidence-d2d466f-r1`.
2. Recompute the capture cap with the fixed 1.25 rule: measured projection is
   below 64 core-hours, lane p95 plus reserve is below 18,000 seconds, and four
   training epochs plus reserve are below 172,800 seconds. Refuse any moved or
   alternate cap.
3. Recompute `expected_execution_review_claim`, the exact marker bytes, and the
   supervisor plan. `--validate-plan-only` must reproduce summary SHA
   `58dc98f9bcf51cec4ba9f394adb6301338c5669edb71d34047292b3cba99b218`
   without creating evidence or ops state.
4. Confirm prior spent R4 roots are disclosed and contain initialization only;
   no prior scientific stage artifacts are reused, and the new evidence/ops
   namespaces remain absent.
5. Return one PASS or HOLD containing all blockers. On PASS append exactly one
   `BELIEF_V1_V2_OFFLINE_EXECUTION_V1_REVIEW` marker for this freeze. The marker
   may authorize only the bounded offline pipeline and one test opening; retry,
   sampler/gameplay/strength/promotion/deployment and PR merges remain false.

On PASS, Codex launches the exact systemd/supervisor plan already bound in the
packet. The user has already requested launch; no additional routine approval
round is needed.

## Next operator sequence

1. Claude performs the one exact-freeze review above.
2. On PASS, Codex initializes the unused namespace and launches immediately.
3. Codex monitors outcome-blind percentage progress and resource/deadline state.
4. One terminal/reproducibility review follows completion; PR merge decisions
   remain separate.
