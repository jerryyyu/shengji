# Deploying Sheng Ji

The server is a **single stateful process**: rooms and games live in memory,
clients hold WebSockets to it. That drives every deployment rule below.

## Ground rules (any host)

- **Exactly one instance.** No replicas, no autoscaling, no serverless. Two
  instances would each hold half the rooms.
- A restart drops in-progress games (players see "That game has ended.").
  Deploy when it's quiet.
- TLS is handled by the platform/proxy; the frontend auto-selects `wss://`
  on https pages (same-origin), no config needed.
- Health check: `GET /healthz`.
- Pick the bot with `SHENGJI_BOT`. The source fallback is `mc` (N=10), while
  Fly configuration selects W32 play plus hybrid bury
  `mc-shortlist-fd6bb411-w32-r55d379a3-bury-hybrid-c93a9877ae6a`, using the
  A+C+D+E+F2 v2 model with N=30 selection and R=300 report checking.
  Bury-only rollback restores `mc-shortlist-fd6bb411-w32-r55d379a3` and removes
  the two `SHENGJI_CWV_BURY_*` settings. A deploy that binds the policy prior
  (`SHENGJI_CWV_PRIOR_CKPT`, optional `_SHA256` pin, `_THRESHOLD`, `_TOP`;
  #435) serves a name ending `-prior-<sha8>` and reports the prior's SHA256
  under `prior` in `/healthz`; prior-only rollback removes the four
  `SHENGJI_CWV_PRIOR_*` settings and restores the prior-less name, and
  `/healthz` must then show `"prior": null`. `mc-s0-report-lcb` is the broader W32
  play-policy rollback; `smart` and `heuristic`
  are cheaper difficulty choices, not strength-equivalent replacements. See
  `docs_archive/w32-fly-serving-through-2026-09-22.md` (archived) for the rollout boundary through release 28 and `AI_POLICIES.md` for evidence.

## Release 29 plan — the policy/value search with the soft head (pv-search, #585), Jerry's go 2026-09-21 ~17:4x ET

Jerry: "I'm good to launch soft with w64 to prod." Served bot `pv-search-ccade130-w64-k8-r8bc573be`:
the soft-action head 8ecd4fea (gen-3-warm's recipe with the search's values as the policy target)
exported as ONE NumPy package `/data/models/soft-8ecd4fea.npz` (sha256 `ccade130f34ae61def540441ef997e8d41cef9df96f9683406bbba59ae4ccc75`; schema v2 with
the policy head), 64 sampled worlds, 8 admitted candidates, value head in place of playouts,
cap 4,000, batch 128, a 3 s cooperative play budget (heuristic anchor on expiry), heuristic
declare, and release 27/28's value-guided HYBRID bury on this package's value head
(`pv_search_policy.PVSearchBuryBot`, the same `CWVBuryMixin` the shortlist ships; 32/32/32/4,
2 s bury budget; Jerry: "we should use value guided hybrid"). Served name
`pv-search-ccade130-w64-k8-r8bc573be-bury-hybrid-4f003f41e23e`. Release-28 env keys are retained
so the rollback is one line: `SHENGJI_BOT` back to
`mc-shortlist-0d17fd03-w32-r0d610b62-prior-0d17fd03-bury-hybrid-003c2abe49ff`.

Evidence: vs the release-28 package in card play, 800 matched deals, one pre-registered primary,
**+0.086 [+0.042, +0.131]** (#553, 2026-09-21, atlas row 45); world scaling W16/W32/W64 vs MC-LCB
+0.123/+0.158/+0.187 with W64−W16 positive (#555); the four-model family at W64 (#583) showed
no head superior to another, soft holding the largest point estimate. Not measured: the
served bot vs release 28 as deployed — Jerry (2026-09-21 ~18:0x ET): "You can do a new screen if
needed vs prod with bury" → lane v34pv on Perf: the shortlist screen's new `--arm policy`
(`cwv_shortlist_screen`/`cwv_screen_queue`) runs the SERVED bot by registry name — both
sides exactly as the fly.toml registers them (pv-search + hybrid bury; release 28 + hybrid
bury) — against the same MC control on five fresh windows, paired per seed.

Preconditions, in order:
1. #585 merged (511ee670) and this release PR merged: smoke extended to the mode, `/healthz`
   `pv_search` block, fly.toml env.
2. `scripts/cwv_serving_smoke.py` PASS on the exact package with this fly.toml — DONE
   2026-09-21 ~18:0x ET on the Mini: 40 server turns (1 bury, 39 plays) through
   `_paced_bot_step` / `_commit_bot_turn`, `PVSearchBot`, play turns 0.063 s mean / 0.088 s
   max single-threaded (receipt `release29/smoke-release29.json`; files ccade130 / 0d17fd03).
3. Package SHA256-verified on the volume (`sha256sum /data/models/soft-8ecd4fea.npz`).
4. `fly deploy --ha=false`; `/healthz` shows `bot` = the pv-search name and `pv_search.sha256`
   = the package hash; then the first live room's log must show a bot `bury` event and
   `model_search` `completed` events with `pv-search-decision-v1` records (`/healthz` cannot
   see a bot-turn failure — release 25).
5. Watch: `pv-search-fallback-v1` records (budget or search-error), stale-turn discards, decision
   wall p50/p95 vs release 28's 0.9 / 1.7 s.

## Current production: release 28 — JS-M1, the from-scratch joint net, as ONE package (#425 / #435), deployed 2026-09-16 00:5x ET

Release **28**, image `registry.fly.io/shengji:deployment-01M2M90VYR34R7CWKTTEA4C57V`
(digest `sha256:c6927dbafb81d55ce823070b6df7ceea4ddfce8a07992139b46afe9f098866ff`), deployed
with `fly deploy --ha=false` from main `bf7fde5e` on machine `48e7e35a9597e8`, 0 rooms at
deploy time. Live health after the deploy:

```
{"ok":true,"rooms":0,"bot":"mc-shortlist-0d17fd03-w32-r0d610b62-prior-0d17fd03-bury-hybrid-003c2abe49ff","fast":true,"prior":{"sha256":"0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747","threshold":1000,"top":256}}
```

Preconditions met, in order: #455 (joint head in the NumPy package) and #457 (this
config) merged; decision-identity gate at threshold 1,000 on the exact package as value
AND prior: 2,207/2,208 identical, one near-tie same-play (same action and RNG, a 1e-7
mean tie ordered differently), prior fired 141× (`scripts/cwv_serving_gate.py`);
`scripts/cwv_serving_smoke.py` PASS from a clean checkout of `bf7fde5e` (40 server turns);
package SHA256-verified on the volume; live room VEZV played a full bot-driven round on
the new policy (bury 0.7 s after the trump call, 69 searches p50 0.6 s / p90 1.6 s /
max 2.7 s, no fallbacks). Jerry's go: 2026-09-15 23:4x ET.

**Rollback.** Release **27** (M1 + policy prior v2, image
`registry.fly.io/shengji:deployment-01M2M1B48P44H5HJXEP6ETYQXE`, its `fly.toml` as of
main `d31bd428`) or release **24** (image `deployment-01M2BGBXE7JXWYBEVWNMG2YM5A`, release
24's `fly.toml`); every package stays on the volume. Prior-only rollback: remove the four
`SHENGJI_CWV_PRIOR_*` settings and set `SHENGJI_BOT` to the prior-less JS-M1 name the
registry prints; `/healthz` must then show `"prior": null`.

## Prepared, NOT deployed: the `pv-search` bot mode (policy/value search, #553 evidence)

The head-driven search that beat the deployed package in card play (soft 8ecd4fea head, W64/K8,
+0.086 [+0.042, +0.131] on 800 matched deals, 2026-09-21; atlas row 45) exists as a production bot
mode: `train/pv_search_policy.py`, registered as `pv-search-<ckpt8>-w<W>-k<K>-r<recipe8>` when
`SHENGJI_PV_CKPT` is set. It is the screened design unchanged (`train/policy_value_search.py`),
served from ONE NumPy package as both value evaluator and policy prior, without Torch.

Env (all under `[env]`, alongside — not replacing — the release-28 keys until a release swaps `SHENGJI_BOT`):

    SHENGJI_PV_CKPT = '/data/models/<package>.npz'   # value + policy head (v2 schema, policy_head)
    SHENGJI_PV_SHA256 = '<full sha256>'              # required; the mode refuses an unpinned package
    SHENGJI_PV_WORLDS = '64'  SHENGJI_PV_CANDIDATES = '8'  SHENGJI_PV_CAP = '4000'
    SHENGJI_PV_BATCH_SIZE = '128'  SHENGJI_PV_SEED = '0'
    SHENGJI_PV_SERVING_BUDGET_SECONDS = '<seconds>'  # cooperative play budget; expiry plays the heuristic anchor

What it does per card-play decision: heuristic anchor first; W sampled worlds through production's
sampler (void-checked); the policy head ranks every legal action and admits K with the anchor
pinned; the value head scores each admitted action's afterstate (current trick finished
heuristically) in every world; the highest mean plays. Declare and bury are the heuristic, as in
every screen that measured this design — the release-27/28 value-guided hybrid bury is NOT
composed here yet. On budget expiry or any search error the sampler RNG is restored and the anchor
plays with a `pv-search-fallback-v1` record; otherwise the record is `pv-search-decision-v1`
(carries `played`, the admitted indices, value means, work counts).

Before any release of this mode, in order (none done yet):
1. A package for the served head exported with `scripts/export_cwv_numpy.py` and SHA256-verified on the volume.
2. Latency on the Fly machine class (shared-cpu-1x, 512 MB): W64 measured 186 ms mean / 337 ms p95 a
   decision on a 16-core box; the served number is unknown until measured — set the budget from it.
3. `scripts/cwv_serving_smoke.py` extended to build this mode from the fly.toml env and driven
   through `_paced_bot_step` / `_commit_bot_turn` (the release-25 rule; `tests/test_pv_search_serving.py`
   does this on a tiny package, the smoke must do it on the real one).
4. The five-window package screen of the served bot against release 28 on fresh seeds (the
   confirmation), then Jerry's explicit go; rollback is `SHENGJI_BOT` back to the release-28 name.

## Release 28 plan as approved (kept for the record)

Play policy `mc-shortlist-0d17fd03-w32-r0d610b62-prior-0d17fd03-bury-hybrid-003c2abe49ff`: JS-M1 (`a5248cc5`, M1's recipe from scratch with a policy head trained on all
20.3M root rows) served as a single NumPy package `/data/models/js-m1-0d17fd03.npz`
(SHA256 `0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747`, schema v2 with the policy head, PR #455). The package is the value net
AND, above 1,000 legal actions with top 256 per sampled world, its own policy head is the
admission prior (`SHENGJI_CWV_PRIOR_CKPT` names the same file; prior kind `joint-numpy`).
Hybrid bury and the 2-second bury budget unchanged (JS-M1 scores bury candidates).
Evidence: offline, val_ce 0.5957 (M1 0.5975) and a policy head non-inferior to prior v3 on
four of five strata (widest unresolved); in play (cloud lane v22, five capped windows),
+0.0239 [+0.0005, +0.0472] vs the release 24 recipe (nominal, shared-control seeds) and
paired +0.0057 [−0.0163, +0.0277] vs the release 27 recipe at the same decision wall with
0 decisions over 60 s in 182,096 — no ten-window or fresh-seed read yet. Preconditions
before `fly deploy --ha=false`: #455 merged; decision-identity gate PASS at threshold
1,000 on this exact package as value and prior (`scripts/cwv_serving_gate.py --serving
--threshold 1000`); `scripts/cwv_serving_smoke.py` PASS from a clean checkout of main with
this fly.toml; the package SHA256-verified on the volume; a live room's log showing a bot
bury and bot plays completing. Prior-only rollback: remove the four `SHENGJI_CWV_PRIOR_*`
settings and set `SHENGJI_BOT` to the prior-less JS-M1 name the registry prints. Full
rollback: release 27 (M1 + prior v2, its fly.toml) or release 24.

## Release 27 — M1 + policy prior v2 (#435), redeployed 2026-09-15 22:0x ET

Release **27**, image `registry.fly.io/shengji:deployment-01M2M1B48P44H5HJXEP6ETYQXE` (digest
`sha256:ff1b78f900f141315582d770ef2232da8d1999d65e6e7a63e22e8d52c0a62993`), deployed with
`fly deploy --ha=false` from main `383c8dc8` (the release 25 recipe plus the
`CWVNumpyPrior.__deepcopy__` fix from #451/#452) on machine `48e7e35a9597e8`, 0 rooms at
deploy time. Live health after the deploy:

```
{"ok":true,"rooms":0,"bot":"mc-shortlist-12ce4415-w32-r45b303c2-prior-b9ff76c9-bury-hybrid-3ba49886a78f","fast":true,"prior":{"sha256":"b9ff76c9038630ae80bd396f4565574c549a55e385ffd729c2521905b76f0e6c","threshold":1000,"top":256}}
```

Preconditions met, in order: fix merged; `scripts/cwv_serving_smoke.py` PASS from a clean
checkout of that main on the exact packages with this fly.toml (40 server turns through
`_paced_bot_step` / `_commit_bot_turn`); decision-identity gate PASS at threshold 1,000
(2,222/2,222 identical, prior fired 139×); packages SHA256-verified on the volume.
`/healthz` cannot see a bot-turn failure (release 25 reported ok while every bot turn
raised), so the first live room's log is the completion check: a bot `bury` event and
`model_search` `completed` events must appear.

**Rollback** is unchanged: release 24 image
`registry.fly.io/shengji:deployment-01M2BGBXE7JXWYBEVWNMG2YM5A` with release 24's
`fly.toml` (as done for release 26 at 20:55 ET); prior-only rollback as described below.

## Release 26 = the release 24 image (rollback), 2026-09-15 20:55 ET → superseded by release 27

Release 25 (below) stalled every bot turn in its first live room (KXXD): the server
deep-copies the bot into a turn snapshot before any search, and the NumPy prior's
read-only weight mapping could not be pickled, so the snapshot raised before the bury
budget began. The in-process decision-identity gate could not catch it (it never takes
the server's snapshot path). Rolled back with
`fly deploy --image registry.fly.io/shengji:deployment-01M2BGBXE7JXWYBEVWNMG2YM5A --ha=false`
and release 24's `fly.toml` → release **26**, `/healthz`
`{"ok":true,"rooms":0,"bot":"mc-shortlist-fd6bb411-w32-r55d379a3-bury-hybrid-c93a9877ae6a","fast":true}`.
The two new packages stay on the volume. Redeploy of the release 25 recipe requires:
PR #451 (`CWVNumpyPrior.__deepcopy__`) merged, `scripts/cwv_serving_smoke.py` PASS on the
real packages from the fixed tree (it builds the bot from `fly.toml` and plays a bury and
play turns through the server's own bot-turn path), and Jerry's word.

## Release 25 — M1 + policy prior v2 (#435), deployed 2026-09-15 19:54 ET, rolled back 20:55 ET

Release **25**, image `registry.fly.io/shengji:deployment-01M2KQVJVPC6WD85RQD59SYG38`
(digest `sha256:4ed088a25eef1244818bbce6dc3e9742ade8f913679a70ebf2a62def1b3af189`), deployed
with `fly deploy --ha=false` from main `55f0029c` on machine `48e7e35a9597e8`
(1/1 health passing, 0 rooms at deploy time). Live health after the deploy:

```
{"ok":true,"rooms":0,"bot":"mc-shortlist-12ce4415-w32-r45b303c2-prior-b9ff76c9-bury-hybrid-3ba49886a78f","fast":true,"prior":{"sha256":"b9ff76c9038630ae80bd396f4565574c549a55e385ffd729c2521905b76f0e6c","threshold":1000,"top":256}}
```

Preconditions that were met, in order: serving gate merged (#445), config merged (#448),
the serving-scope gate on the exact packages at threshold 1,000 PASS (2,222/2,222 decisions
identical, prior fired 139×; receipt archived under `~/shengji-archive/2026-09-15/release25/`
with the 10k run, the deploy log and this health response), both packages SHA256-verified on
the volume. Jerry's go: 18:2x ET (M1 + prior v2), 19:2x ET (threshold 1,000).

**Rollback.** Full: release **24**, image
`registry.fly.io/shengji:deployment-01M2BGBXE7JXWYBEVWNMG2YM5A` (fd6bb411 + hybrid bury,
`SHENGJI_BOT=mc-shortlist-fd6bb411-w32-r55d379a3-bury-hybrid-c93a9877ae6a`,
`SHENGJI_CWV_SHORTLIST_CKPT=/data/models/w32-fd6bb411.npz`, no `SHENGJI_CWV_PRIOR_*`); the
release 24 package stays on the volume. Prior-only: remove the four `SHENGJI_CWV_PRIOR_*`
settings and set `SHENGJI_BOT` to the registry's prior-less M1 name; `/healthz` must then
show `"prior": null`. Machine and volume `vol_rkgj0xeg8ejy1kw4` are unchanged; logs and
model packages must be preserved.

## Release 25 plan as approved (kept for the record)

Play policy `mc-shortlist-12ce4415-w32-r45b303c2-prior-b9ff76c9-bury-hybrid-3ba49886a78f`:
M1 (`3cb9cd62`) served as NumPy package `/data/models/m1-12ce4415.npz`
(SHA256 `12ce4415a65c479b03d52a08574e14a5909b09435c1d8dddeab1726fbc1d4d4f`),
policy prior v2 (`b6d928c5`) as `/data/models/prior-v2-b9ff76c9.npz`
(SHA256 `b9ff76c9038630ae80bd396f4565574c549a55e385ffd729c2521905b76f0e6c`, pinned by
`SHENGJI_CWV_PRIOR_SHA256`), applied above 1,000 legal actions with top 256 per
sampled world (Jerry accepted 1,000 over the originally approved 10,000 on
2026-09-15 19:2x ET: on five paired capped windows threshold 1,000 is outcome-identical
to 10,000, −0.0006 [−0.0026, +0.0014], at 0.72× its decision wall and 0.60× the
previous recipe's, longest decision 9.9 s vs 57.6 s); hybrid bury and the 2-second
bury budget unchanged. Evidence: twenty
fresh windows of the M1 family +0.0140 [+0.0026, +0.0254] vs the previous recipe;
the prior arm is outcome-identical to M1 (paired −0.0003 [−0.0017, +0.0012]) at
0.79× the previous decision wall with 0 decisions over 60 s and 0 cap hits in
365,414 (previous recipe: 161 and 7). Preconditions before `fly deploy --ha=false`:
both packages on the volume with matching SHA256, the in-repo serving gate
(`scripts/cwv_serving_gate.py --serving --threshold 1000`) PASS with
`qualifies_serving` on these exact files at this threshold, `/healthz` after deploy showing the policy name and `"prior"` with the
prior SHA. Prior-only rollback: remove the four `SHENGJI_CWV_PRIOR_*` settings and set
`SHENGJI_BOT` to the prior-less M1 name the registry prints; full rollback: release
24 (below) with its environment. The release number, image and health response are
recorded above.

## Current production and rollback boundary

Previous production (superseded by release 25 above): release **22** deployed September 9 at approximately 20:51 ET, image
`registry.fly.io/shengji@sha256:b5dc327f79d8804d2a9f79bcddbb6bea1740b71547937ce1be1c08661030c82d`.
Live health reports the exact hybrid policy and native engine. An isolated
functional probe verified the literal model path and SHA, encoder bytes,
legal eight-card bury, unchanged play RNG and no Torch import; it completed
in 0.803s without fallback. This is one smoke observation, not a latency SLA.
The existing engineering-room gate and checkpoint were preserved using deploy
overrides `SHENGJI_W32_TEST_ROOMS=1` and
`SHENGJI_W32_TEST_CKPT=/data/models/w32-fd6bb411.npz`; retain those overrides
on a later deploy if the engineering gate is to remain available. Ordinary
rooms use the default policy without an access code.

Jerry authorized shipping hybrid bury on September 9 after PR #323's fixed
1,976-deal all-rank confirmation and consumer review. The shipping config uses
32 candidates / 32 model worlds / 32 MC worlds, incumbent plus four alternatives,
and a **2-second cooperative search budget**. Expiry or search error returns
the legal heuristic incumbent without advancing the play RNG. Queue wait,
model loading and an in-flight operation are not bounded by that deadline.
The existing W32 play recipe, compact model, one search worker and 512MiB VM
remain unchanged. Consult `/healthz` for the live policy; configuration in Git
is not itself proof of deployment.

Pre-bury rollback release: **21**, image
`registry.fly.io/shengji@sha256:4a68a54058d028dd2444270d1f83b51dcc8623c627043e68ea8058594d41f54b`.
Machine `48e7e35a9597e8`, volume `vol_rkgj0xeg8ejy1kw4`, existing model package
and logs must be preserved. Bury-only policy rollback on the new image restores
the base W32 name and removes bury registration/budget together; do not select
an unregistered bury name. Reverting the image also requires restoring its
compatible environment. Do not interrupt occupied rooms without scoped consent.

Monitor queue/search/request latency separately, fallback reasons, stale-turn
discards, OOM/crash, legality and kitty-loss incidents. Roll back immediately on
illegal action, RNG/isolation violation or crash/OOM. Investigate repeated
2-second expiries or new queue stalls; do not silently raise the budget. Live
traffic is not a powered strength trial. Large kitty losses are a known tradeoff:
the confirmation saw four 80+ bonuses versus zero for heuristic, despite better
average results. See the [bury report](docs_archive/value-guided-bury-dev-2026-09-08.md).
For tail monitoring, count `round_end.kitty_points >= 80` among completed
bot-banker rounds using this policy, with the completed-round denominator;
separate successful hybrid decisions from logged heuristic fallbacks. This
field is the awarded kitty bonus, not raw buried-card points. Preserve failed
and unfinished rounds separately rather than silently excluding operational
failures. These observational counts are not a causal comparison with old traffic.

### Historical W32 rollout (September 8)

On September 8, Fly release **20** deployed the reviewed opt-in W32 room gate
from PR #310, image
`registry.fly.io/shengji@sha256:b8f48f41149d8a27225e7a44260b72b03475dbdf99ba7398c56167682afd19e5`.
The single 512 MB / shared-CPU-1x machine `48e7e35a9597e8` and its volume are
unchanged. At **19:53 UTC September 8**, after Jerry explicitly authorized
all-user rollout and health showed zero rooms, an environment-only update on
this same image made W32 the ordinary-room default. No access code is needed.
The loaded NumPy package was verified as `fd6bb411` (source `3cd27716`, encoder
v2), with no Torch import; public health passed with the exact W32 policy.
Explicit engineering rooms still require a creator access code and remain
excluded from ordinary training logs.
See `docs_archive/w32-fly-serving-through-2026-09-22.md` (archived 2026-09-22) for the measured latency and test status through release 28.

The pre-deploy **release 19** rollback image is
`registry.fly.io/shengji:deployment-01M0P8VNX2C49XMVHFWFNNAPC2`, manifest
`sha256:38c40bb675b2a330e845168ed3f63089279cff764bdcb7fea4908578721045dc`.
This is the rollback image for the gated-W32 deployment; retain its
machine configuration and volume. Health must report
`{"bot":"mc-s0-report-lcb","fast":true}`. The earlier release-18 boundary
below is historical, not the current release number.

The decision runtime moves an isolated bot/round snapshot into
a worker, overlaps the existing 0.7-second pacing floor, and commits the action
only if the live room, round, phase, turn and controller still match. Claims,
reconnects and X-ray therefore remain responsive; a stale search is discarded
with its cloned RNG/counters.

For the original W32 rollout, **policy rollback was `SHENGJI_BOT=mc-s0-report-lcb`**
on the same image; retain both model packages and the volume. The global model
registration can remain present when MC-LCB is selected. A normal-room
constructor and health were checked, not a many-room concurrency benchmark;
one model-search worker bounds CPU use but concurrent players can queue.

Historical release-18 rollback decisions (not the current W32 rollback):

1. **Release/runtime rollback:** Fly release 17 / image
   `latency-cd6789e`. Use this for a release-18 availability or kitty-X-ray
   regression while keeping the report-LCB policy and release-17 scheduler
   decision separate. It does not undo a defect shared with release 17. The
   release-17 manifest SHA-256 is
   `047bcfe4d4573961734a5536ad549605fd0df5e1477d7480cdf322282955b300`.
2. **Policy rollback:** `SHENGJI_BOT=mc-strong`. Use this for a report-LCB
   decision-semantics/correctness problem; it gives up the confirmed strength
   gain and is not the response to a generic server/runtime issue.

The project owner (Jerry) is the production deploy and rollback decider.
Before a planned deploy or policy change, inspect room occupancy and obtain
scoped authorization before interrupting games. Record the old release, exact
image/manifest, health response, reason and rollback target. Do not treat an
empty room as permission to change the production policy.

## Option A: Fly.io (recommended)

```bash
brew install flyctl && fly auth login
fly launch --copy-config --no-deploy   # uses fly.toml; pick an app name
fly volumes create shengji_data --size 1   # ONE volume (see below)
fly deploy --ha=false                      # ONE machine (see below)
```

`fly.toml` pins an always-on 512MiB machine with `auto_stop_machines = "off"`
so idle games aren't killed. Bounded model-serving probes fit this allocation;
that is not an unrestricted concurrency or worst-case memory guarantee.
Custom domain: `fly certs add yourdomain.com` + a CNAME.

Two Fly defaults to override (learned the hard way):
- **`--ha=false` is required**: plain `fly deploy` creates TWO machines for
  "high availability", but rooms live in one machine's memory — the proxy
  would route players randomly between machines and rooms would appear
  missing. If you end up with two, `fly machine destroy <id> --force` one.
- **Ignore the volume redundancy warning** (`-n 2`): one machine means one
  volume. Extra volumes get claimed by phantom machines and wedge deploys
  ("volume already claimed" / "needs an unattached volume") — destroy
  extras with `fly volumes destroy <vol_id>`.

## Option B: any VPS with Docker

```bash
docker build -t shengji .
docker run -d --restart unless-stopped -p 127.0.0.1:8000:8000 shengji
```

Put Caddy in front for TLS (Caddyfile: `yourdomain.com { reverse_proxy
localhost:8000 }`) — Caddy proxies WebSockets automatically.

## Option C: zero-deploy for friends

Tailscale (invite friends to your tailnet, run the server locally) or a
Cloudflare Tunnel. No code or config changes needed.

## Capacity

Policy cost, not the rules engine, sets CPU capacity. On the measured mini,
SmartBot is p50 0.05ms / p95 0.13ms, direct v11pair is 0.25ms / 0.52ms on the
numpy path, base N=10 MC is 77ms / 150ms, and an earlier matched benchmark put
the production report-LCB decision at 0.390s versus 0.127s for `mc-strong`.
Live Fly time is workload-dependent: after release 17, the first ordinary
human room's 195 searched turns measured p50/p95/max
0.896/1.714/1.906s. Off-loop execution hides event-loop blocking and overlaps
the 0.7s pacing floor; it does **not** make search free or let a worker react
before the latest play. Each turn snapshots only after that play, computes,
then revalidates before commit. Load-test the chosen policy and concurrent room
mix before advertising capacity. Memory per room is small; scaling beyond one
process would require external state and room-affinity routing.
