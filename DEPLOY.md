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
  Fly configuration selects release 37 (release 36's model: release 29's search recipe with the #607 bury fix on the gen-5 SMV3 outcome head; release 37 is a phone-HUD CSS fix only), the policy/value search with hybrid bury
  `pv-search-491ee4bf-w64-k8-r4a09aef5-bury-hybrid-355958b4db25` (`SHENGJI_PV_*`;
  `/healthz` reports it under `pv_search`). The release-28 shortlist keys stay in
  `fly.toml` so the rollback is one line. A deploy that binds the policy prior
  (`SHENGJI_CWV_PRIOR_CKPT`, optional `_SHA256` pin, `_THRESHOLD`, `_TOP`;
  #435) serves a name ending `-prior-<sha8>` and reports the prior's SHA256
  under `prior` in `/healthz`; prior-only rollback removes the four
  `SHENGJI_CWV_PRIOR_*` settings and restores the prior-less name, and
  `/healthz` must then show `"prior": null`. `mc-s0-report-lcb` is the broader W32
  play-policy rollback; `smart` and `heuristic`
  are cheaper difficulty choices, not strength-equivalent replacements. See
  `docs_archive/w32-fly-serving-through-2026-09-22.md` (archived) for the rollout boundary through release 28 and `AI_POLICIES.md` for evidence.

## Current production: release 37 — the phone top bar is one strip again (#671), deployed 2026-10-01 01:1x ET

Release **37**, image `registry.fly.io/shengji:deployment-01M3TXZ85YHJM108TBPWKN8BB2` (digest
`sha256:8fabbe4441c564b58d6d4a9af7acce7d6c639b9562682db164a6c152b7126ffd`), deployed with
`fly deploy --ha=false` from main `12f20305` (#671) on machine `48e7e35a9597e8`, 0 rooms at deploy
time, on Jerry's word 2026-10-01 ("Pls fix ui top bar" with a screenshot; "671 passed").

**NO model, package or configuration change.** Same `fly.toml`, package (`smv3out-491ee4bf.npz`),
prior and served name as release 36; every screen still compares against release 36. Web only, one
CSS rule in the landscape-phone media block: the points chip was a `flex-direction: column` inside
the 999px-radius chip pill, so the number, the `/ 80` target and the points bar stacked into three
rows and rendered as a tall egg that stretched the whole HUD band; it is now a two-row grid (number
and target side by side, the bar beneath, radius 10 px) the height of the level strip. Desktop
untouched.

Preconditions as met: Codex PASS on #671 at the exact head `fc260ec6`; CI 5/5; serving smoke on the
MERGED tree against the SHA-verified volume packages (`491ee4bf…`, `0d17fd03…`) — PASS, 40 server
turns through `_paced_bot_step` / `_commit_bot_turn`, bury 0.129 s; `/healthz` after the deploy
unchanged from release 36 (bot, `pv_search.sha256` `491ee4bf…`, prior `0d17fd03…`), rooms 0; the
served CSS bundle (`assets/index-1BVBTamK.css`) carries the `.points-chip{…display:grid}` rule; live
room-level acceptance without starting a game (host sets, joiner sees, joiner and unknown level
refused) PASS.

Rollback: the release-36 image (`deployment-01M3SG9NVC1AC3PNPEH5Y34N0D`), a pure code rollback.

## Release 36 — the gen-5 SMV3 outcome head in the release-30 search (#666, #663), deployed 2026-09-30 11:53 ET; superseded by release 37 (same name, same package)

Release **36**, image `registry.fly.io/shengji:deployment-01M3SG9NVC1AC3PNPEH5Y34N0D` (digest
`sha256:064d73f54f77d0996baa8a1ab11d1530724d8f57e23c4e4667a175e37362f76b`), deployed with
`fly deploy --ha=false` from main `30318531` (#666) on machine `48e7e35a9597e8`, 0 rooms at deploy
time, on Jerry's word 2026-09-30 11:4x ET ("Let's deploy").

**THE FIRST MODEL CHANGE SINCE RELEASE 30.** Served bot
`pv-search-491ee4bf-w64-k8-r4a09aef5-bury-hybrid-355958b4db25`: the gen-5 SMV3 **outcome** head
(run `GEN5-PROD-SOFT-allPV-plusMCLCB-496k-SMV3`, checkpoint 3e89e86f: arm F's recipe with ONE
change, the search-mean sidecar v3 of #658, so the auxiliary search-mean head trained on 48.85M rows
instead of 24.2M) exported as ONE NumPy package `/data/models/smv3out-491ee4bf.npz` (sha256
`491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670`, schema v2 with the policy head,
verified on the volume). The search, bury, budgets and prior are release 30's: 64 worlds, 8 admitted
candidates, 3 s play budget, hybrid bury at 2 s, JS-M1 prior `0d17fd03…`. The value function is still
the game-outcome head; the search-mean head served as the value function read NEGATIVE (v36b) and is
not shipped.

Evidence (#663; Atlas v2): the SMV3 outcome head as served vs release 30 as served, each vs the common
MC-LCB control on five 520-cluster mirrored windows, DL random effects — v36a (Perf, seeds
31960910..32360910) **+0.0361 [+0.0015, +0.0707]**, 5/5 windows positive; the PREDECLARED fresh
confirmation v36a2 (seeds 33660910..34060910, the read of record alone) **+0.0393 [+0.0033, +0.0752]**,
5/5 positive. Package-level common-control evidence, not a paired duel; sign established, size
uncertain at MDE80 ≈ 0.05. Policy head alone vs SmartBot on 8,000 mirrored deals: +0.3157 (release-30
head +0.1006). Offline (rank regret on the fixed holdouts, SMV3 vs arm F): roomlog 0.0655 / 0.0683,
pt1 0.0337 / 0.0409, luna 0.0855 / 0.0868, highn 0.1054 / 0.1032.

Preconditions as met: Codex PASS on #666 at the exact head `373361a7` (code/package-binding review; the
required package tests 22 passed against the release asset); CI 5/5 (the #654 package gate repinned
to `smv3out-491ee4bf.npz` on the `serving-packages` release); package on the volume, sha256 verified
on the machine; serving smoke on the MERGED tree `30318531` against the SHA-verified volume packages
(`491ee4bf…`, `0d17fd03…`) — PASS, 40 server turns through `_paced_bot_step` / `_commit_bot_turn`,
bury 0.123 s, plays 0.02–0.08 s, receipt `smoke-release36.json`; `/healthz` after the deploy: `bot`
the name above, `pv_search.sha256` `491ee4bf…`, worlds 64, candidates 8, budgets 3 / 2, prior
`0d17fd03…`, rooms 0; live acceptance without starting a game (room-level flow: host sets, joiner
sees, joiner and unknown level refused) PASS.

Rollback (one line, keeps the model choice explicit): in `fly.toml` restore the three release-30 lines
kept as the comment directly above (`SHENGJI_BOT` `pv-search-ccade130-w64-k8-r8bc573be-bury-hybrid-4f003f41e23e`,
`SHENGJI_PV_CKPT` `/data/models/soft-8ecd4fea.npz`, `SHENGJI_PV_SHA256` `ccade130…`; the package stays on
the volume) and `fly deploy --ha=false`; or the release-35 image `deployment-01M3K8WQX7EXB3CYDMNGJ8MQHN`
(same three settings baked in). Every screen from here compares against **release 36**; screens
predeclared against release 30 before this deploy (v36c) read out as declared.

Watch list: `pv-search-fallback-v1` records, stale-turn discards, decision wall p50/p95, bury seconds;
the first live room's log.

First live rooms on this package (read 2026-10-01 09:2x ET from the log cache; three rooms LKMU, CDCE,
KHPX played 2026-09-30 12:0x–20:3x ET, 76–100 bot play searches each, 57–93 bot-mode plus takeover
plays): play wall p50 0.23–0.25 s, p95 0.35–0.37 s, max 0.42 s; bury 0.57–0.65 s, hybrid arm, search
status complete, no fallback reason; `stale_discarded` false on every decision; zero fallback records.
Same shape as release 29's first live room (p50 0.24 s).

## Release 35 — the phone table's overflow menu and points bar (#653, #651), deployed 2026-09-28 01:49 ET; superseded by release 36 (new package)

Release **35**, image `registry.fly.io/shengji:deployment-01M3K8WQX7EXB3CYDMNGJ8MQHN` (digest
`sha256:d94f79cc8653252c2e4820b814bf21d82f1d12b40c9b797100e2c675b26fae03`), deployed with
`fly deploy --ha=false` from main `b6b510e6` (#653) on machine `48e7e35a9597e8`, 0 rooms at deploy
time, on Jerry's word 2026-09-28 ("Yes ship phone table pass").

**NO model, package or configuration change.** Same `fly.toml`, package, prior and served name as
releases 29–34; every screen still compares against release 30. Web only: no server change.

What changed on a landscape phone: kitty count, sound, invite link and leave live under one `…`
button (`HudMenu`; leave keeps its two-tap confirm and an armed leave holds the menu open); the
points chip carries a thin bar toward 80. Mute state now has ONE source of truth (`audio.ts`
publishes changes; a shared `useMuted()` hook feeds the HUD chip, the phone menu and the Room
screen's toggle) — Codex's review caught that two mounted controls each kept a private snapshot,
so rotating a phone after muting showed the wrong state and the first tap was a no-op. Desktop
keeps every chip; the menu and bar are hidden there.

Preconditions as met: Codex PASS on #653 at the exact head `39793d45` (one round: the shared mute
state); CI 5/5; serving smoke on the MERGED tree against the SHA-verified volume packages
(`ccade130…`, `0d17fd03…`) — PASS, 40 server turns, bury 0.119 s; `/healthz` after the deploy
unchanged from release 30, rooms 0; live acceptance without starting a game: the served JS bundle
carries `hud-more-btn`, the CSS bundle carries the `hud-menu` rules, and the room-level flow
(host sets, joiner sees, joiner and unknown level refused) still passes.

Rollback: the release-34 image (`deployment-01M3JP62AR34FH5929FQC9GK7P`), a pure code rollback.

## Release 34 — a quieter phone table (#652, #651), deployed 2026-09-27 20:22 ET; superseded by release 35 (same name, same package)

Release **34**, image `registry.fly.io/shengji:deployment-01M3JP62AR34FH5929FQC9GK7P` (digest
`sha256:896c13bdf61074fc20873db841b526d15162f272fb3489c8d023ea8265094591`), deployed with
`fly deploy --ha=false` from main `eaea3a80` (#652) on machine `48e7e35a9597e8`, 0 rooms at deploy
time, on Jerry's word 2026-09-27 ("can you apply a few options? i think the card layout is fine btw
its busy with all the bots on the board and stuff").

**NO model, package or configuration change.** Same `fly.toml`, package, prior and served name as
releases 29–33; every screen still compares against release 30. No server change at all: the diff
is phone-only CSS inside the existing `@media (max-height: 500px)` branch of `web/src/index.css`.

What changed on a landscape phone: each opponent is one lozenge (name, `· count`, badges; team
colour as a left rule; card-back stacks, the BOT tag, the banter line and the progress bar hidden;
the seat on turn gets a gold ring); the level/trump/level chips read as one strip and the kitty chip
is hidden; the "Player" tagline shows only while it says something (your turn / ready); a disabled
Clear is hidden; the HUD message is a toast over the felt that fades after ~3 s. The mute toggle
STAYS (Codex's review: it is the only way to silence announcements on a phone). Desktop untouched.

Preconditions as met: Codex PASS on #652 at the exact head `799eafac` (one round: the first cut hid
the mute toggle); CI 5/5; serving smoke on the MERGED tree against the SHA-verified volume packages
(`ccade130…`, `0d17fd03…`) — PASS, 40 server turns, bury 0.118 s; `/healthz` after the deploy
unchanged from release 30, rooms 0; live acceptance without starting a game: the served CSS bundle
carries the new `hud-message-pass` rule, and the room-level flow (host sets, joiner sees, joiner and
unknown level refused) still passes.

Rollback: the release-33 image (`deployment-01M3F6FPRBXCK5Q4BDA0CET5A8`), a pure code rollback.

## Release 33 — the starting level moves into the room screen (#646), deployed 2026-09-26 11:50 ET; superseded by release 34 (same name, same package)

Release **33**, image `registry.fly.io/shengji:deployment-01M3F6FPRBXCK5Q4BDA0CET5A8` (digest
`sha256:1ff39d9c57d667a01b7de7ded27d64bcf29d94afce308ea9d7d0c7d809f44315`), deployed with
`fly deploy --ha=false` from main `681431e6` (#646) on machine `48e7e35a9597e8`, 0 rooms at deploy
time, on Jerry's word 2026-09-26 ("start level selector should be in the room screen, not Home Screen").

**NO model, package or configuration change.** Same `fly.toml`, package, prior and served name as
releases 29–32 (`pv-search-ccade130-w64-k8-r8bc573be-bury-hybrid-4f003f41e23e`); the strength
evidence carries over and every screen still compares against release 30.

What changed: the **Starting level** dropdown left the lobby's create-room form and lives in the
room screen. A new `set_start_level` message is host-only, validated against `RANKS` (an unknown
rank is refused with "Unknown starting level."), and refused once `room.game` exists — `Game()`
reads the level exactly once at `start_game`, so a later change would make the HUD lie for the rest
of the session. Joiners see the chosen level as a "Starts at" chip. `create_room` still accepts
`start_level` (the protocol is unchanged); the web client simply no longer sends it.

Preconditions as they were met: Codex PASS on #646 at the exact head `6fd1d822` (a re-review — the
first PASS at `0135d9a4` was voided by a test-only fix for a CI timing assumption: the refusal is
queued behind the card-by-card deal broadcasts, and the test's 40-message window was too small on a
loaded runner); CI 5/5; serving smoke on the MERGED tree against the SHA-verified volume packages
(`soft-8ecd4fea.npz` `ccade130…`, `js-m1-0d17fd03.npz` `0d17fd03…`) — PASS, 40 server turns
through `_paced_bot_step` / `_commit_bot_turn`, bury 0.131 s, plays 0.028–0.082 s, receipt
`passed: true`. `/healthz` after the deploy: bot name, prior SHA and every `pv_search` field
UNCHANGED from release 30, rooms 0.

Live acceptance against production, deliberately WITHOUT starting a game (no `round_start` is
written, so the human corpus stays clean): the host created a room at the default `"2"`, set `"10"`
and the room frame echoed `"10"`; a joiner's room frame carried `"10"` and its own `set_start_level`
was refused ("Only the host can set the starting level."); the host's `"1"` was refused ("Unknown
starting level."). Both sockets left; the room expires on `ROOM_TTL`.

Rollback: the release-32 image (`deployment-01M3F1Q968BKYT8CD9GGE7XYMX`, `fly deploy --image …`), a
pure code rollback — package, prior and every `SHENGJI_*` key are identical on both sides. Note that
rolling back past release 32 also reverts the Ace rule below.

## Release 32 — a table plays on past Ace (#644), deployed 2026-09-26 10:2x ET; superseded by release 33 (same name, same package)

Image `registry.fly.io/shengji:deployment-01M3F1Q968BKYT8CD9GGE7XYMX`, `fly deploy --ha=false` from
main `38441557` (#644 plus the diagnostic-only #640–#643 and #645), 0 rooms at deploy time, on
Jerry's word 2026-09-26 ("Deploy 644"). **NO model, package or configuration change.**

The rule change (Jerry: "after ace, it should go up one point and continue back to 2"): a team that
successfully defends at A now scores a **game** — `games_won` is tallied, both team levels reset to
the room's starting level, and the table plays on. Rooms run with `games_to_win=None` (open-ended);
the engine default stays `1`, so `play_game` and every offline harness still stop at the first game
exactly as before. `round_result` carries `games_won` and `point_scored`; the round-end modal says
"wins the game" and shows the tally; the HUD shows ★ games won. Also in this release: the
create-room selector lost its hint text and labels the default plainly as "2".

Preconditions as met: Codex PASS on #644 at its exact head; CI 5/5; serving smoke on the merged tree
against the SHA-verified volume packages — PASS, 40 server turns, bury 0.117 s, plays 0.024–0.075 s;
`/healthz` unchanged from release 30, rooms 0; live acceptance without starting a game.

Rollback: the release-31 image (`deployment-01M3CQK3KMH55NDZRED6PDJ6XW`) — a code rollback that also
restores the one-game-and-stop behaviour.

## Release 31 — the create-room starting level (#638), deployed 2026-09-25 12:51 ET; superseded by release 32 (same name, same package)

Release **31**, image `registry.fly.io/shengji:deployment-01M3CQK3KMH55NDZRED6PDJ6XW` (digest
`sha256:cfef8361237bc39f42abdee9915f9d47d84f8731709147848972c4e267a7e663`), deployed with
`fly deploy --ha=false` from main `8a6e55f1` (#638) on machine `48e7e35a9597e8`, 0 rooms at deploy
time, on Jerry's word 2026-09-25 12:3x ET ("can you get start level reviewed in PR and then deploy?").

**NO model, package or configuration change.** Same `fly.toml`, same package, same prior, same served
name as releases 29 and 30 (`pv-search-ccade130-w64-k8-r8bc573be-bury-hybrid-4f003f41e23e`). Release
30's strength evidence carries over unaltered and there is no new screen, because nothing the search
does changed.

What changed: `create_room` accepts an optional `start_level`, so the room's creator picks the rank
BOTH teams begin at. The victory condition is untouched — a team still wins by successfully DEFENDING
at A — so a higher start level is simply a shorter game. The lobby offers a **Starting level**
dropdown and the room screen shows a chip when it is not the default.

The load-bearing part is not the option. `Game.start_round` takes the trump rank from the banker's
team level, but round 1 has no banker yet and fell back to `RANKS[0]`. Setting the team levels alone
would therefore have DEALT every first round at rank 2 while the HUD, the lobby chip and the
`round_start` log record all advertised the chosen level. The fallback now follows `level_idx` and is
bit-identical at the default. An unrecognised `start_level` is REFUSED with a new `bad_start_level`
error rather than coerced to 2, so a client cannot be handed a game its own UI misdescribes.

Preconditions as they were met: Codex PASS on #638 at the exact head `63504087`; CI 5/5; serving smoke
run on the MERGED tree against the real volume packages — `soft-8ecd4fea.npz` (`ccade130…`) and
`js-m1-0d17fd03.npz` (`0d17fd03…`) both fetched from the Fly volume and SHA-verified against
`fly.toml` — PASS with 40 server turns through `_paced_bot_step` / `_commit_bot_turn`, bury 0.122 s,
plays 0.025–0.078 s, receipt `passed: true`. That witness was run specifically because this change
touches `Game.start_round`, which is on the live serving path. Deploy; `/healthz` then showed the bot
name, prior SHA and every `pv_search` field UNCHANGED from release 30, rooms 0.

Live acceptance against production, deliberately WITHOUT starting a game (so no `round_start` is
written and the human corpus is not contaminated): a create at level 10 echoed `start_level` `"10"`;
an ordinary create echoed `"2"`; a create at `"1"` was refused with `bad_start_level`.

Rollback: the release-30 image (`deployment-01M34KWRW4XWJWC6DCCYENFXTF`, `fly deploy --image …`).
Because no serving configuration changed, that rollback is purely a code rollback; the package, prior
and every `SHENGJI_*` key are identical on both sides.

## Release 30 — release 29 + the hybrid-bury fix (#607), deployed 2026-09-22 09:13 ET; superseded by release 31 (same name, same package)

Release **30**, image `registry.fly.io/shengji:deployment-01M34KWRW4XWJWC6DCCYENFXTF` (digest
`sha256:ea40b4d44b3fd74f6baf7f3178005973711a86eba075caecf9f1d3c2e117b0c0`), deployed with
`fly deploy --ha=false` from main `4e006561` (#607) on machine `48e7e35a9597e8`, on Jerry's word
2026-09-22 09:0x ET ("Yes let's release as 30 for the fix"; one idle room dropped on his word).
Same `fly.toml`, same package, same served name as release 29
(`pv-search-ccade130-w64-k8-r8bc573be-bury-hybrid-4f003f41e23e`; the bury identity digest is
config-only). What changed: `CWVBuryMixin._bury_candidates` keeps the heuristic incumbent once and
drops the candidate generator's copy of it instead of raising `bury candidate generator duplicated
incumbent` (#606) — on the diagnostic capture set 6% of banker burys hit that refusal, which under the
2 s bury budget was a silent heuristic fallback (`cwv-bury-fallback-v1` / `search-error`) in releases
27–29 and, with budgets unset, the hard failure that stopped data generation runPV1. The candidate set
the value head scores is unchanged on every other deal.

Preconditions as they were met: serving smoke on the exact package with this `fly.toml` on the fixed
tree (40 server turns through `_paced_bot_step` / `_commit_bot_turn`, bury 0.14 s, plays 0.04–0.09 s,
receipt `release30/smoke-release30.json`); Codex PASS on #607 at 74303cd6; CI 5/5; deploy; `/healthz`
shows the name above, `pv_search` = {sha256 ccade130…, worlds 64, candidates 8, budget 3, bury hybrid,
bury budget 2}, rooms 0. Strength evidence is release 29's (below); no new screen for the fix itself.

Rollback: the release-29 image (`deployment-01M33NZERJS18A0G2NNG7S5FJ8`, `fly deploy --image …`),
then release 28 by the one-line `SHENGJI_BOT` change. Watch: `cwv-bury-fallback-v1` records — the expectation to check is that their reason is
`budget` only; any `search-error` reason (an unrelated exception still takes the generic fallback) is a finding to
investigate; `pv-search-fallback-v1`, stale-turn discards, decision wall p50/p95.

## Release 29 — the policy/value search with the soft head (pv-search W64/K8 + hybrid bury), deployed 2026-09-22 00:29 ET; superseded by release 30 (same name, same package)

Release **29**, image `registry.fly.io/shengji:deployment-01M33NZERJS18A0G2NNG7S5FJ8` (digest
`sha256:e3ddf6cd62c9da582086bb8171a79d30eb2c2c4df85b0c965a26b972d2f159b0`), deployed with
`fly deploy --ha=false` from main `292ee6e6` (#588) on machine `48e7e35a9597e8`, 0 rooms at deploy
time, on Jerry's word 2026-09-22 00:2x ET ("yea lets deploy 29"; W64 kept after the W64/128/256 ladder's
pre-registered contrasts both spanned zero).

Served bot `pv-search-ccade130-w64-k8-r8bc573be-bury-hybrid-4f003f41e23e`: the soft-action head
8ecd4fea (gen-3-warm's recipe with the search's values as the policy target) exported as ONE NumPy
package `/data/models/soft-8ecd4fea.npz` (sha256 `ccade130f34ae61def540441ef997e8d41cef9df96f9683406bbba59ae4ccc75`,
schema v2 with the policy head, verified on the volume). Per play decision: heuristic anchor; 64 sampled
worlds through production's sampler; the policy head ranks the capped legal set (4,000) and admits 8 with
the anchor pinned; the value head prices each admitted action's afterstate in every world; the highest
mean plays. No playouts. 3 s cooperative play budget (heuristic anchor on expiry, `pv-search-fallback-v1`).
Heuristic declare. Bury: release 27/28's value-guided HYBRID arm on this package's value head
(`PVSearchBuryBot`; 32/32/32/4; 2 s budget, heuristic fallback). Release-28 env keys retained.

Live health after the deploy (`/healthz`): `bot` = the name above, `rooms` 0,
`pv_search` = {sha256 ccade130…, worlds 64, candidates 8, budget_seconds 3, bury_arm hybrid,
bury_budget_seconds 2}. First live room AFBZ (opened 04:30:42Z with three bots, host seat taken over):
round complete at 04:32:41Z, 126 s; bot bury at seat 1 (0.64 s); 70 bot play searches completed,
p50 0.24 s / p90 0.35 s / max 0.38 s; 69 `pv-search-decision-v1` records; 0 fallbacks, 0 deadline
timeouts, 0 stale discards; attackers 15, banker team won. Release 28's live numbers were 0.9 / 1.7 s.

Evidence (all on the search atlas and the scaling page): card play vs the release-28 package, 800
matched deals, one pre-registered primary **+0.086 [+0.042, +0.131]** (#553; row 45); the same search on
fresh deals +0.122 [+0.079, +0.164] (#589 ladder base arm; W128−W64 +0.024 [−0.034, +0.083] and
W256−W64 +0.024 [−0.033, +0.081], neither clear of zero: nothing above 64 worlds is shown to help);
the four-model family at W64 (#583): no head superior, soft the largest point; **the served bot vs
release 28 as served (lane v34pv, Perf, five clean 520-cluster windows, 300 s cap): +0.049
[+0.003, +0.095]**, clears zero narrowly (DL random effects, I² 49%; one window inside a training corpus
excluded and reported at −0.006). No strength claim beyond those intervals.

Preconditions as they were met: package exported and SHA256-verified on the volume (09-21); smoke on
the exact package through `_paced_bot_step` / `_commit_bot_turn` (40 turns, PASS, `release29/`);
confirmation screen (v34pv) sealed 09-22 02:10Z; Jerry's go; deploy; `/healthz`; first live room.

Rollback (one line): `SHENGJI_BOT` back to
`mc-shortlist-0d17fd03-w32-r0d610b62-prior-0d17fd03-bury-hybrid-003c2abe49ff` (release 28; its keys
are still in `fly.toml`), then `fly deploy --ha=false`; release 27 next; image rollback below.

Watch list: `pv-search-fallback-v1` records (budget or search-error), stale-turn discards, decision wall
p50/p95; the run-4 head served the same way (lane v34r4) reads out 2026-09-22 ~01:50 ET.

## Release 28 — JS-M1, the from-scratch joint net, as ONE package (#425 / #435), deployed 2026-09-16 00:5x ET; the one-line rollback for release 29

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

## The `pv-search` bot mode (policy/value search) — production since release 29

The head-driven search that beat the deployed package in card play (soft 8ecd4fea head, W64/K8,
+0.086 [+0.042, +0.131] on 800 matched deals, 2026-09-21; atlas row 45) is the production bot
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
sampler (void-checked); the policy head ranks the capped legal listing (cap 4,000, the anchor forced in) and admits K with the anchor
pinned; the value head scores each admitted action's afterstate (current trick finished
heuristically) in every world; the highest mean plays. Declare is the heuristic; bury is the release-27/28 value-guided hybrid arm on the same package
(`SHENGJI_PV_BURY_ARM`, `SHENGJI_PV_BURY_*`, `SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS`; `PVSearchBuryBot`). On budget expiry or any search error the sampler RNG is restored and the anchor
plays with a `pv-search-fallback-v1` record; otherwise the record is `pv-search-decision-v1`
(carries `played`, the admitted indices, value means, work counts).

The release gate for this mode (package on the volume, smoke on the exact package, the served-bot
confirmation screen, Jerry's go, `/healthz` and the first live room) was met for release 29; see the
record above. A future head in this mode repeats the same gate with its own package.

## Releases 22–28 records (archived 2026-10-01)

The records for releases 25–28 (the release-28 plan as approved, release 27, the release-26 image
rollback, release 25 and its plan) and the release-22 "current production and rollback boundary"
section (hybrid bury on W32, the September-8 W32 rollout, the release-19/18 boundaries) moved verbatim
to [docs_archive/w32-fly-serving-through-2026-09-22.md](docs_archive/w32-fly-serving-through-2026-09-22.md)
(heading "Moved from DEPLOY.md on 2026-10-01"). Release 28 itself, the rollback for release 29, stays above.

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
