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
- Health check: `GET /healthz`. Its `activity` block counts, since the process started: rooms created,
  games started, rounds recorded (a `round_start` record reached disk), records written, record write
  failures, the last successful write (ISO UTC) and the last failure's exception class and errno.
  `games_started` ahead of `rounds_recorded` is a room-log write failure; everything at zero for days is
  inactivity. The counters observe the room path and never gate it; none carries a room code, path or
  payload, so the endpoint stays unauthenticated.
- Pick the bot with `SHENGJI_BOT`. The source fallback is `mc` (N=10); Fly configuration
  selects the served bot named under "Current production" below (`SHENGJI_PV_*`; `/healthz`
  reports it under `pv_search`). The release-28 shortlist keys stay in `fly.toml` so that
  rollback is one line. A deploy that binds the policy prior (`SHENGJI_CWV_PRIOR_CKPT`,
  optional `_SHA256` pin, `_THRESHOLD`, `_TOP`; #435) serves a name ending `-prior-<sha8>` and
  reports the prior's SHA256 under `prior` in `/healthz`; prior-only rollback removes the four
  `SHENGJI_CWV_PRIOR_*` settings and restores the prior-less name, and `/healthz` must then show
  `"prior": null`. `mc-s0-report-lcb` is the broader W32 play-policy rollback; `smart` and
  `heuristic` are cheaper difficulty choices, not strength-equivalent replacements. See
  `docs_archive/w32-fly-serving-through-2026-09-22.md` (archived) for the rollout boundary through
  release 28 and `AI_POLICIES.md` for evidence.

## Release checklist

Preconditions, every release (the gate `AI_POLICIES.md` called "serving qualification"; it has held
for releases 29–38 and 42–45):

1. A non-author PASS on the PR at its exact head, and all CI checks green. CI fetches the pinned
   production package and loads it on the tree (`.github/workflows/pr-checks.yml`);
   `server/tests/test_bury_fly_config.py` pins the served name that the `fly.toml` environment derives, and
   `server/tests/test_release46_fly_config.py` builds the served bot from that environment on the pinned
   production and belief packages under the package gate (name, every combo knob, the bound belief model, the
   compiled compact solver, one served play through the server path with the belief proposal and no fallback).
2. For a package change: the package on the volume, SHA256-verified against `fly.toml`.
3. Serving smoke on the MERGED tree against the SHA-verified packages
   (`server/scripts/cwv_serving_smoke.py`, which builds the `pv-search` bot when `SHENGJI_PV_CKPT` is
   set): the bot built from the `fly.toml` environment exactly as the server does, bury and play turns
   through `_paced_bot_step` / `_commit_bot_turn`. Release 25 passed the decision-identity gate yet
   stalled every live bot turn because nothing took this path.
4. For a strength change: the served-bot screen against the current production release, read out
   before the deploy (the evidence for each change is the ladder table in `AI_POLICIES.md`).
5. Jerry's word, in session.

Deploy with `fly deploy --ha=false` (one machine; see Option A) when the room count is 0 or on
Jerry's word to drop idle rooms.

Completion criterion: `/healthz` reports the expected `bot`, `pv_search.sha256` and `prior`, and the
first live room completes a game without `pv-search-fallback-v1` records. Then add the row to the
Releases table and update the Current-production block below. A shortlist package (releases 22–28,
now the rollback path) also needs the decision-identity gate before the smoke
(`server/scripts/cwv_serving_gate.py --serving --threshold 1000`; it last ran for release 28 and has
never run for a `pv-search` release).

## Releases

Full records for releases 28–38 (evidence, preconditions as met, live acceptance, first-room
latency): [docs_archive/deploy-releases-28-38.md](docs_archive/deploy-releases-28-38.md). Every image
is `registry.fly.io/shengji:<image>`; every deploy was `fly deploy --ha=false` on machine
`48e7e35a9597e8`. "Package/bot change?" is whether the served package or bot name changed.

| release | deployed (ET) | what changed | package/bot change? | PR(s) | image / rollback |
|---:|---|---|---|---|---|
| 46 | PENDING (not deployed; deployment id and time TBD; see "Release 46" below) | The combo screened as v92combo45, as twelve `fly.toml` lines on release 45's environment: history-legal, belief-proposed play worlds (`SHENGJI_PV_WORLD_HISTORY_LEGAL = '1'`, `SHENGJI_PV_WORLD_HISTORY_DRAW = '1'`, `SHENGJI_PV_BELIEF_WORLDS = '1'`, `SHENGJI_PV_BELIEF_CKPT = '/data/models/s17long-e2-763b5e05.npz'`, `SHENGJI_PV_BELIEF_SHA256 = '763b5e05…4343'`; tokens `whl whd bw`), the exact endgame search at 7 cards (`SHENGJI_PV_EXACT_LEAD_ENDGAME = '1'`, `SHENGJI_PV_EXACT_DEEP_CARDS = '7'`, `SHENGJI_PV_EXACT_FOLLOW = '1'`, `SHENGJI_PV_EXACT_FOLLOW_SOLVER = 'compact-level'`, `SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS = '7'`, `SHENGJI_PV_EXACT_FOLLOW_MAX_NODES = '50000000'`; tokens `ele ed7 xf7 xfcompactlevel`) and the value-guided declaration at every first-round declare chance (`SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST = '1'`; token `vdef`). Play, bury and declaration budgets, play package, worlds and candidates are release 45's. Evidence v92combo45 +0.2167 [+0.1923, +0.2412] vs release 45 as served, first-round deals, POSITIVE; confirmation v92c PENDING; latency packet PENDING. | new BELIEF package on the volume (`s17long-e2-763b5e05.npz`, sha256 `763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343`); new served name `pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-vd-vdef-ed7-xf7-xfcompactlevel-r73993d62-bury-hybrid-bwv-cf77a93949b0`; same play package `491ee4bf…`, same prior `0d17fd03…` | release PR (evidence #707 issuecomment-6216352632; source #1066 and the belief log) | PENDING (image TBD, digest TBD). Rollback: delete the twelve release-46 lines, restore the release-45 `SHENGJI_BOT` kept as the comment above it, redeploy; or the release-45 image `deployment-01M4T9AVEVK51WP2GG8J34NRC9`. The belief package may stay on the volume. |
| 45 | 2026-10-13 05:27 | The wide value-only bury on, as two `fly.toml` lines: `SHENGJI_PV_BURY_WIDE_VALUE = '1'` and `SHENGJI_PV_BURY_WIDE_K = '64'` (#974, token `bwv`): the bury candidates widen to 64 and the value head alone picks the bury, no MC stage; same 2 s bury budget and heuristic fallback. Play, declaration, package and other budgets are release 44's (the play digest is unchanged; only the bury digest moves). Built from main, so it also ships main since `8ac9543e`: #972 policy-head first trick, #973 whole-hand lead admission, #975 oracle-worlds diagnostic (all flag-gated off; #975 screen harness only), #955 lead-admission diagnostic, #977 harvest, #984 two-card bury swaps (flag-gated off), the round-end "Buried by <banker> · N pts" row #982, tests and Atlas. Evidence v76bwv44 +0.0488 [+0.0286, +0.0690] vs release 44 as served, first-round deals, POSITIVE, 10/10 windows positive. | flag only; new served name `pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv-7a73e8fbf1a8`; same package `491ee4bf…`, same prior `0d17fd03…` | #983 (evidence #707 issuecomment-6136852119; authority 6137203703; rule #974) | `deployment-01M4T9AVEVK51WP2GG8J34NRC9` (Fly v45), digest `sha256:6194eb27e62efab5f0e9218f453e730e7733fcacdeaf4996eef249718389dbcb`, from main `1ca97051`. Merged-tree smoke: bury p50/p90/max 0.218/0.226/0.234 s, 64 candidates, 0 fallbacks, 160 plays max 0.093 s. Rollback: delete the two `SHENGJI_PV_BURY_WIDE_*` lines, restore the release-44 `SHENGJI_BOT` kept as the comment above it, redeploy; or the release-44 image. |
| 44 | 2026-10-11 17:05 | The value-guided trump declaration on, as one `fly.toml` flag: `SHENGJI_PV_VALUE_DECLARE` (#952, token `vd`): at each gated declare chance every option plus PASS is scored by the value head over 64 sampled completions and the heuristic's choice is replaced only when beaten; served off the event loop with stale guards and the heuristic as fallback (#959, #958, #965's gate fix). Package, width, other rules, bury and budgets are release 43's. Evidence v70vd43 +0.0497 [+0.0379, +0.0615] (first-round deals) and v71vd43lr +0.0352 [+0.0233, +0.0471] (later-round deals), both POSITIVE vs release 43 as served, 20/20 windows positive. | flag only; new served name `pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-6c1fb26b80e6`; same package `491ee4bf…`, same prior `0d17fd03…` | #963 (evidence #707 issuecomment-6103734355 and 6110908081; rule #952; serving #959/#958/#965) | `deployment-01M4PC7724HSXC27PCEEREZWY4` (Fly v44), digest `sha256:d618f2371cd75fe31aad44a1e711cc5a8f13c517ad45ad93bc700d4bacc0abff`, from main `8ac9543e`. Rollback: delete the `SHENGJI_PV_VALUE_DECLARE` line, restore the release-43 `SHENGJI_BOT` kept as the comment above it, redeploy; or the release-43 image. |
| 43 | 2026-10-09 15:46 | The doomed-throw re-select replaces the swap, as one `fly.toml` flag: `SHENGJI_PV_DOOMED_THROW_RESELECT` (#946, token `dtr`) instead of `SHENGJI_PV_DOOMED_THROW_SWAP`. When re-selection completes with an eligible alternative, a doomed throw and its forced component are excluded and the bot re-selects among its remaining admitted leads (reviewed fallbacks: budget abandonment keeps the first selection; all-excluded plays the forced component). A functional correctness fix (YJQJ round 1), no strength claim. Package, width, other rules, bury and budgets are release 42's. Built from main, so it also ships main since `e3aa1724`: the experimental rules adaptive worlds #936, its leads-only scope #944, wide lead admission #945 and value declare #952, all flag-gated off; #949's behaviour-preserving OptionalStage guard refactor, which is active through the re-select; tests/CI; Atlas. Evidence v67dtrg −0.0004 [−0.0122, +0.0114] vs release 42, INCONCLUSIVE, DEPLOY-ELIGIBLE (not noninferiority). | flag only; new served name `pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-r91979586-bury-hybrid-28570365d86b`; same package `491ee4bf…`, same prior `0d17fd03…` | #953 (evidence v67dtrg, #707 issuecomment-6080113005; rule #946) | `deployment-01M4H37RYNM42YHH6ZPEC6GKCK` (Fly v43), digest `sha256:2c0d94e2c263e94cf0cdc8b9cf3fce9c5c14d81d646a400b4db813ff0577eb7a`, from main `6b385b55`. Rollback: replace the `SHENGJI_PV_DOOMED_THROW_RESELECT` line with `SHENGJI_PV_DOOMED_THROW_SWAP = '1'`, restore the release-42 `SHENGJI_BOT` kept as the comment above it, redeploy; or the release-42 image. |
| 42 | 2026-10-06 19:08 | The doomed-throw swap on, as one `fly.toml` flag: `SHENGJI_PV_DOOMED_THROW_SWAP` (#830, token `dts`): on a lead whose throw the engine refuses in every sampled world with the same forced component, play that component instead. Package, width, rules, bury and budgets are release 38's. A backend release from main (normal Dockerfile; supersedes the release 39–41 overlay recipe), so it also ships the decision-preserving engine/heuristic perf PRs since release 38's image `c8d487a6` (#736, #772, #773, #798, #825, #836, #896, #897, #898), flag-gated-off #777 and #716, the error-report fix #800, and main's web (release 41 UI #845 + #854). Evidence v57dts −0.000150 [−0.010232, +0.009931] vs release 38, INCONCLUSIVE, DEPLOY-ELIGIBLE (not noninferiority); failed throws −64%. | flag only; new served name `pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-r0f40c8b5-bury-hybrid-273fed4cd40d`; same package `491ee4bf…`, same prior `0d17fd03…` | #918 (evidence v57dts, #707 issuecomment-6026001554; swap #830) | `deployment-01M49QGK2ZP18P143S8BXVW28X` (Fly v42), digest `sha256:05d8b84fdbff096a1622e9913cedf9a3b7652d8aebe97829dea1f29d50a6c8af`, from main `e3aa1724`. Rollback: delete the `SHENGJI_PV_DOOMED_THROW_SWAP` line, restore the release-38 `SHENGJI_BOT` kept as the comment above it, redeploy; or the release-41 image. |
| 41 | 2026-10-05 21:40 | Web performance: in-app Back to lobby, memoized hand cards, static first paint, composited thinking pulse. Frontend-only overlay on the immutable release-38 image (release-39 recipe). | none | #845 ([release record](https://github.com/jerryyyu/shengji/pull/845#issuecomment-6007495036)) | digest `sha256:4d1e796f7f2dd2c2ff337c05b09b2ebdf672c43ecf7232d2f5954b796c7b52ee` (label `release41-ui`, Fly v41); web source `ef920afc`. Rollback: release-40 digest `sha256:2b24572af11b7098c32f4033956f5dde4ce39eeb6e2f95bba0b7f25d24fb6736`. |
| 40 | 2026-10-05 11:34 | Mobile landscape layout: the trick area stays clear of the turn pill, Play button and hand; declare/bury keep a one-row action bar; throw-failed banner floats. Frontend-only overlay on the immutable release-38 image (release-39 recipe). | none | #829 | digest `sha256:2b24572af11b7098c32f4033956f5dde4ce39eeb6e2f95bba0b7f25d24fb6736` (label `release40-ui`); web source `0663c4c0`. Rollback: release-39 digest `sha256:bfd4b192e82e71e2b05d7ad612e4cf3a15491ac5890bc99cd8b6fe1b90bf759e`. Health/assets verified at 0 rooms; real-phone landscape acceptance pending. |
| 39 | 2026-10-05 01:47 | Mobile UI, touch controls and accessibility. Frontend-only overlay on the immutable release-38 image; no intervening backend/search changes shipped. | none | #778 | `deployment-01M459KDH29EQFN9SDRH7P4GQ2`, digest `sha256:bfd4b192e82e71e2b05d7ad612e4cf3a15491ac5890bc99cd8b6fe1b90bf759e`; web source `0a1f4e3a`. Rollback: release-38 image. Health/assets verified; first real-phone room and complete-game acceptance pending. |
| 38 | 2026-10-03 09:41 | Four search rules on, as `fly.toml` flags: `SHENGJI_PV_ADMISSION_DIVERSITY`, `SHENGJI_PV_REFUSAL_CONSTRAINTS`, `SHENGJI_PV_TIEBREAK_POINTS`, `SHENGJI_PV_LEAD_ANCHOR`. Package, width, bury and budgets are release 36's. | flags only; new served name `pv-search-491ee4bf-w64-k8-div-rc-tb-la-r7092480e-bury-hybrid-5517ddbd7457`; same package `491ee4bf…`, same prior `0d17fd03…` | #698 (evidence #676; rules #680, #689, #682, #694) | `deployment-01M40ZWSAHNX4782CGKJ615YF7` from main `c8d487a6`. Rollback: delete the four rule lines, restore the release-36 `SHENGJI_BOT` kept as the comment above them, redeploy; or the release-37 image. |
| 37 | 2026-10-01 01:1x | Phone top bar one strip again: one CSS rule in the landscape-phone block (points chip a two-row grid). | none | #671 | `deployment-01M3TXZ85YHJM108TBPWKN8BB2` from main `12f20305`. Rollback: release-36 image. |
| 36 | 2026-09-30 11:53 | THE FIRST MODEL CHANGE SINCE RELEASE 30: the gen-5 SMV3 outcome head (checkpoint 3e89e86f) as one package `smv3out-491ee4bf.npz`; search, bury, budgets and prior unchanged. | new package `491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670`; served name `pv-search-491ee4bf-w64-k8-r4a09aef5-bury-hybrid-355958b4db25` | #666 (evidence #663; sidecar #658) | `deployment-01M3SG9NVC1AC3PNPEH5Y34N0D` from main `30318531`. Rollback: restore the three release-30 lines kept as the comment above (`SHENGJI_BOT`, `SHENGJI_PV_CKPT`, `SHENGJI_PV_SHA256`), redeploy; or the release-35 image. |
| 35 | 2026-09-28 01:49 | Phone overflow menu (`HudMenu`), points bar, one source of truth for mute state (`useMuted()`). Web only. | none | #653 (#651) | `deployment-01M3K8WQX7EXB3CYDMNGJ8MQHN` from main `b6b510e6`. Rollback: release-34 image. |
| 34 | 2026-09-27 20:22 | Quieter phone table: phone-only CSS in the `@media (max-height: 500px)` branch. No server change. | none | #652 (#651) | `deployment-01M3JP62AR34FH5929FQC9GK7P` from main `eaea3a80`. Rollback: release-33 image. |
| 33 | 2026-09-26 11:50 | Starting level moves into the room screen: host-only `set_start_level`, refused once `room.game` exists. | none | #646 | `deployment-01M3F6FPRBXCK5Q4BDA0CET5A8` from main `681431e6`. Rollback: release-32 image (rolling back past 32 also reverts the Ace rule). |
| 32 | 2026-09-26 10:2x | A table plays on past Ace: a successful defence at A scores a game, levels reset, `games_to_win=None` in rooms. | none | #644 (with diagnostic-only #640–#643, #645) | `deployment-01M3F1Q968BKYT8CD9GGE7XYMX` from main `38441557`. Rollback: release-31 image (restores one-game-and-stop). |
| 31 | 2026-09-25 12:51 | `create_room` accepts `start_level`; round-1 trump-rank fallback follows `level_idx`; unknown level refused with `bad_start_level`. | none | #638 | `deployment-01M3CQK3KMH55NDZRED6PDJ6XW` from main `8a6e55f1`. Rollback: release-30 image. |
| 30 | 2026-09-22 09:13 | Hybrid-bury fix: `_bury_candidates` keeps the heuristic incumbent once instead of raising on the duplicate (on the diagnostic capture set 6% of banker burys hit that refusal, a silent heuristic fallback in releases 27–29). | none (same package and name as 29) | #607 (#606) | `deployment-01M34KWRW4XWJWC6DCCYENFXTF` from main `4e006561`. Rollback: release-29 image, then release 28 by the one-line `SHENGJI_BOT` change. |
| 29 | 2026-09-22 00:29 | The policy/value search (`pv-search` W64/K8, no playouts, 3 s budget) with hybrid bury (2 s) on the soft head 8ecd4fea. | new mode and package `soft-8ecd4fea.npz` (`ccade130f34ae61def540441ef997e8d41cef9df96f9683406bbba59ae4ccc75`); served name `pv-search-ccade130-w64-k8-r8bc573be-bury-hybrid-4f003f41e23e` | #588 (evidence #553, #589, #583) | `deployment-01M33NZERJS18A0G2NNG7S5FJ8` from main `292ee6e6`. Rollback: `SHENGJI_BOT` back to the release-28 name (its keys stay in `fly.toml`), redeploy; release 27 next. |
| 28 | 2026-09-16 00:5x | JS-M1, the from-scratch joint net, as ONE package (value and prior) inside the MC shortlist. | new package `0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747`; served name `mc-shortlist-0d17fd03-w32-r0d610b62-prior-0d17fd03-bury-hybrid-003c2abe49ff` | #425 / #435 (#455, #457) | `deployment-01M2M90VYR34R7CWKTTEA4C57V` from main `bf7fde5e`. Rollback: release 27 (`deployment-01M2M1B48P44H5HJXEP6ETYQXE`) or release 24 (`deployment-01M2BGBXE7JXWYBEVWNMG2YM5A`); prior-only rollback removes the four `SHENGJI_CWV_PRIOR_*` settings. |
| 22–27 | — | The release-28 plan as approved, release 27, the release-26 image rollback, release 25 and its plan, and the release-22 boundary (hybrid bury on W32, the September-8 W32 rollout, the release-19/18 boundaries). | see the archive | — | [docs_archive/w32-fly-serving-through-2026-09-22.md](docs_archive/w32-fly-serving-through-2026-09-22.md), heading "Moved from DEPLOY.md on 2026-10-01". |

## Release 46 (prepared, NOT deployed; release 45 plus the v92 combo)

Prepared so that, once the gates below read, only Jerry's word and the deploy remain. Nothing in this section
is a deploy record; the "Current production" block below stays release 45 until the deploy record exists.
Jerry chose this release in session on 2026-10-16 ("Ok I want to ship v92 as next release"); the deploy itself
is still his word. The D6 + X6-only release (draft #1065) is the fallback if the combo's gates fail.

- **What changes.** Twelve `fly.toml` lines on release 45's environment, every other line byte-identical, and
  `SHENGJI_BOT` becomes the name the registry derives from them,
  `pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-vd-vdef-ed7-xf7-xfcompactlevel-r73993d62-bury-hybrid-bwv-cf77a93949b0`,
  exactly the candidate v92combo45 screened (its launcher exported these twelve keys, the belief package at the
  screen host's path with the same sha256):
  - **Play worlds** (`SHENGJI_PV_WORLD_HISTORY_LEGAL`, `SHENGJI_PV_WORLD_HISTORY_DRAW`, `SHENGJI_PV_BELIEF_WORLDS`,
    `SHENGJI_PV_BELIEF_CKPT = '/data/models/s17long-e2-763b5e05.npz'`, `SHENGJI_PV_BELIEF_SHA256`): every sampled
    world must be history-legal, the draw honours the pair obligation, and the hidden hands are proposed by the
    S17 belief model, a NumPy package (`ai/belief_numpy`, `shengji-belief-numpy-v1`; no torch) loaded once per
    process and sha-verified against `SHENGJI_PV_BELIEF_SHA256` when the policy registers. A belief error,
    including a preparation over `belief_numpy.PREP_SECONDS` (0.25 s), falls back for that decision to the
    history-legal production draw and is recorded (`belief_fallback`, `belief_error`). The belief log is on by
    default (`SHENGJI_PV_BELIEF_LOG` unset): each decision record gains `belief_seed`, a uint8 marginal snapshot
    and its summary; `server/scripts/belief_debug.py` replays a logged decision's worlds. No name, digest or
    decision depends on the log.
  - **Exact endgame at 7 cards** (`SHENGJI_PV_EXACT_LEAD_ENDGAME`, `SHENGJI_PV_EXACT_DEEP_CARDS = '7'`,
    `SHENGJI_PV_EXACT_FOLLOW`, `_SOLVER = 'compact-level'`, `_MAX_CARDS = '7'`, `_MAX_NODES = '50000000'`): a LEAD
    where every hand holds ≤ 7 cards and more than one candidate is admitted is re-scored by exact level-mode
    minimax in each sampled world after the first-trick leaf; a FOLLOW at ≤ 7 cards with more than one admitted
    candidate is re-ranked by exact play on the compact-level solver. Both inside the unchanged 3 s play budget;
    on budget expiry or any solver error the finalized baseline plays and the record says so
    (`exact_lead_status` `abandoned`/`skipped_budget`, `exact_follow_abandoned`).
  - **Declaration** (`SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST`): in the first round (no fixed banker) the
    value-guided declaration's gate admits every declare chance with an option, not only the heuristic's; the
    candidates, worlds, margin and every fallback are release 44's (`pv-declare-serving-fallback-v1`). Its record
    carries `gate` (`every_first` counts the chances this flag added).
  - Bury, budgets, play package, worlds and candidates are release 45's; the play digest moves (`r73993d62`)
    and the bury suffix digests the play identity with it.
  - Built from main plus the combo source, it also ships main since release 45's `1ca97051`: the consolidated
    combo source (#1066: the belief stack and the optimized compact solver), the belief log, #1039 (the exact
    stages), the `/healthz` `activity` counters (#1055; the "Next deploy" check in the release-45 block applies
    to this deploy), the X-ray explanation of pv-search decisions (#1051), the stale-bot-play guard (#1050),
    room-log failure reporting (#1043), per-room bot seeds (#1037), the duplicate-pin fix (#1035), training and
    screen-harness changes and Atlas rows.
- **Dependencies of the served path.** The belief path imports only NumPy and the standard library
  (`ai/belief_numpy.py` and the featurizer modules it imports lazily; torch appears only inside training and
  export functions that serving never calls); the image installs `uv sync --no-dev` (FastAPI, NumPy, Uvicorn),
  and a full round of the served combo ran with `torch`, `scipy`, `pytest` and `Cython` blocked from import.
  The compact solver is `ai/_endgame_fast`, built in the Dockerfile's `fastbuild` stage (its `ls` fails the
  build if a `.so` is missing) and copied into the runtime stage; `fly.toml` sets `SHENGJI_FAST = '1'`;
  `.dockerignore` keeps a local Darwin `_endgame_fast*.so` out of the build context. The pure-Python twin
  returns identical results, only slower: a `python` backend in production is a latency regression, not a
  wrong play.
- **Evidence (ladder row 15 in `AI_POLICIES.md`).** v92combo45, ten first-round windows 126060910…126960910 vs
  release 45 as served on cloud, **+0.2167 [+0.1923, +0.2412] POSITIVE**, MDE80 0.035 (#707
  issuecomment-6216352632; archive `readouts/v92combo45-combo-vs-r45/`, result `f81f642b…`). Belief fallbacks 0
  of 356,238 records; history-fallback worlds 0.1%; exact stages on 8.11 eligible decisions per arm-round,
  abandons within the cap, 0 play fallbacks; bury unchanged. Banker share 71.4% vs 51.9% (vdef declares at every
  first-round chance), so the points margin is role-confounded. Components alone, never pooled: v86bw45 belief
  +0.1165, v89 D7 + X7 +0.0439, v85c vdef +0.0421 (confirmed). First-round deals only.
  **Confirmation v92c: PENDING** (the same lane byte for byte on ten new seeds, cloud, launcher `bb7d995d…`;
  packet ask #707 issuecomment-6216714001). Record its primary and verdict here when read; a non-POSITIVE read
  parks this release.
- **Latency gate: PENDING.** The whole-decision latency packet for the combo (#707 issuecomment-6217944669):
  on perf, release 45 as served vs this name, ABBA, through the real server path, per decision kind (leads,
  follows including 7-card exact roots, bury, declaration), p95 and p99 per kind against release 45's on the
  same host, with the Fly-equivalence note (perf cores vs the Fly machine). The predeclared bars and the read
  go here; the deploy waits for them. The belief proposal adds a featurizer, a model forward and a constrained
  draw to every play decision (screen-host `belief_ms` p50/p90 11.6/18.8 ms under 14 workers; DEV estimate of
  the whole decision p95 0.46 s), which a screen host does not qualify for Fly.
- **Preconditions as they must be met** (the Release checklist): (1) a non-author PASS on the release PR at its
  exact head and all CI checks green, including the package-gate step, which fetches BOTH pinned packages from
  the `serving-packages` release (`smv3out-491ee4bf.npz`, `s17long-e2-763b5e05.npz`, each sha256-verified) and
  runs `tests/test_release46_fly_config.py`; the combo source (#1066) and the belief log reviewed and merged on
  main first; (2) the belief package on the volume, sha-verified, BEFORE the deploy (below): the policy
  registers at server import and refuses a missing or mismatched belief file, so a deploy without it does not
  boot the served bot; (3) the server-path smoke on the MERGED tree in full-round mode, so the 7-card endgames
  and the belief proposal run through the server path:
  `SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python scripts/smoke_release45_bury.py --fly-toml ../fly.toml --map /data/models/smv3out-491ee4bf.npz=<local> --map /data/models/js-m1-0d17fd03.npz=<local> --map /data/models/s17long-e2-763b5e05.npz=<local> --rounds 10 --full-round --receipt smoke46.jsonl`
  (validator PASS, the receipt's `bot.files` lists the belief package at `763b5e05…`; then the reader below
  over `smoke46.jsonl.logs/*.jsonl`: belief fallbacks 0, exact-eligible decisions > 0, abandons 0, fallbacks
  0, p95 and max recorded); (4) v92c POSITIVE and the latency packet read; (5) Jerry's word, in session. Deploy
  with `fly deploy --ha=false` from a clean worktree at the merge commit, at 0 rooms.
- **Belief package upload, before the deploy** (the play package and prior do not move):
  1. Upload the asset to the volume through the running release-45 machine (it does not read the file):
     `fly ssh sftp shell -a shengji`, then `put <local>/s17long-e2-763b5e05.npz /data/models/s17long-e2-763b5e05.npz`
     (the local copy first verified with `shasum -a 256` against `763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343`,
     or fetched from the `serving-packages` release asset of the same name).
  2. Verify on the volume:
     `fly ssh console -a shengji -C "sha256sum /data/models/s17long-e2-763b5e05.npz"` must print
     `763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343`. Only then deploy the new `fly.toml`
     (the switch of `SHENGJI_BOT`).
- **Fly serving-budget check, after the deploy** (the combo adds the belief proposal to every play decision and
  solver time to endgame decisions; the screen and the smoke run on faster hosts than Fly's shared CPU):
  1. `/healthz`: `bot` is the name above, `fast: true`, `pv_search.sha256` `491ee4bf…`, `prior` `0d17fd03…`,
     `budget_seconds "3"`, `bury_arm hybrid`, `bury_budget_seconds "2"`; and the `activity` block as the
     release-45 "Next deploy" item describes. `/healthz` does not report the belief package; that the served bot
     registered at all is the evidence its sha matched (registration refuses a mismatch).
  2. The compiled solver and the belief package in the image and on the volume, one read-only line in the
     machine (not the serving process; the same image and interpreter):
     `fly ssh console -a shengji -C "sh -c 'cd /app/server && SHENGJI_FAST=1 .venv/bin/python -c \"import sys; from shengji.ai.endgame_compact import HAVE_FAST, default_backend; from shengji.ai.belief_numpy import load_belief_numpy; m = load_belief_numpy(sys.argv[1], sys.argv[2]); print(HAVE_FAST, default_backend(), m.package_sha256[:8])\" /data/models/s17long-e2-763b5e05.npz 763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343'"`
     must print `True compiled 763b5e05`. `False python` means `_endgame_fast` did not ship or does not import:
     roll back (the latency gate did not qualify the pure twin).
  3. The first live room's log, read once from the log cache (`server/scripts/fetch_fly_logs.sh`, then
     `logs/<CODE>.jsonl`; read-only). Over its `play` events that carry a `decision`:
     ```
     python3 - logs/<CODE>.jsonl <<'EOF'
     import json, sys
     rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
     d = [r["decision"] for r in rows if r.get("e") == "play" and r.get("decision")]
     bw = [x for x in d if "belief_fallback" in x]
     bfb = [x for x in bw if x["belief_fallback"]]
     leads = [x for x in d if x.get("exact_lead_status", "ineligible") != "ineligible"]
     follows = [x for x in d if x.get("exact_follow_attempted")]
     ab = [x for x in leads if x["exact_lead_status"] in ("abandoned", "skipped_budget")] + \
          [x for x in follows if x.get("exact_follow_abandoned")]
     fb = [x for x in d if x.get("schema") == "pv-search-fallback-v1" or not x.get("work_complete", True)]
     q = lambda xs, p: sorted(xs)[min(len(xs) - 1, int(round(p * (len(xs) - 1))))] if xs else None
     secs = [x["seconds"] for x in d if "seconds" in x]
     endg = [x["seconds"] for x in leads + follows if "seconds" in x]
     bms = [x["belief_ms"] for x in bw if "belief_ms" in x]
     print(f"plays {len(d)} belief-drawn {len(bw)} belief fallbacks {len(bfb)} {sorted({x.get('belief_error') for x in bfb})}")
     print(f"exact-eligible leads {len(leads)} follows {len(follows)} abandons {len(ab)} fallbacks {len(fb)}")
     print(f"decision s all p50 {q(secs,.5)} p95 {q(secs,.95)} max {max(secs) if secs else None}; endgame p50 {q(endg,.5)} p95 {q(endg,.95)} max {max(endg) if endg else None}; belief_ms p50 {q(bms,.5)} p95 {q(bms,.95)}")
     EOF
     ```
     The `bot_timing` events with `phase == "play"` give the same decisions' server-side wall
     (`compute_seconds`, snapshot plus off-loop compute; `pacing_seconds` is the 0.7 s floor, not search), and the
     `model_search` events their queue/run stages; the `declare_decision` records show `gate`. Record the lines
     here with the room code. Rollback triggers: any `pv-search-fallback-v1` (budget) record; belief fallbacks
     above 1% of belief-drawn decisions (the screen had 0); exact abandons above 2% of eligible decisions; or a
     whole-decision p95 that the latency packet's bar does not admit; until that bar is on this page, a
     whole-decision p95 above 1.5 s or any decision at the 3 s budget is the trigger. One belief fallback on the
     first decision after a boot (a cold preparation over 0.25 s) is recorded, not a trigger by itself.
- **Rollback.** In `fly.toml` delete the twelve release-46 lines (`SHENGJI_PV_WORLD_HISTORY_LEGAL`,
  `SHENGJI_PV_WORLD_HISTORY_DRAW`, `SHENGJI_PV_BELIEF_WORLDS`, `SHENGJI_PV_BELIEF_CKPT`, `SHENGJI_PV_BELIEF_SHA256`,
  the six `SHENGJI_PV_EXACT_*`, `SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST`) and restore the release-45 `SHENGJI_BOT`
  kept as the comment directly above it
  (`pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv-7a73e8fbf1a8`), then
  `fly deploy --ha=false`; or redeploy the release-45 image:
  `flyctl deploy --app shengji --ha=false --image registry.fly.io/shengji:deployment-01M4T9AVEVK51WP2GG8J34NRC9`
  (Fly v45). The belief package may stay on the volume (release 45 does not read it).
  `tests/test_bury_fly_config.py` and `tests/test_release46_fly_config.py` pin that the env without the twelve
  lines derives release 45's name. Deeper rollbacks are release 45's below.
- **On deploy**, move this section's facts into the Releases-table row 46 (image, digest, deploy time, authority
  comment), rewrite "Current production" for release 46 and record the checks above with their numbers.

## Current production (release 45; release 44 plus the wide value-only bury)

- Release 45 is a normal backend release built from main `1ca97051` (#983, squash at the reviewed head
  `2a2d7844`) with main's Dockerfile; Fly version v45, image `deployment-01M4T9AVEVK51WP2GG8J34NRC9`,
  digest `sha256:6194eb27e62efab5f0e9218f453e730e7733fcacdeaf4996eef249718389dbcb`, machine
  `48e7e35a9597e8`, deployed 2026-10-13 05:27 ET (09:27Z) on Jerry's in-session word ("Wide bury", "Smoke test,
  then ship"; #707 issuecomment-6137203703), 0 rooms at deploy
  ([deploy record](https://github.com/jerryyyu/shengji/issues/707#issuecomment-6142519054)). Built from main, it
  also ships main's changes since release 44's `8ac9543e`: the round-end "Buried by <banker> · N pts" row (#982,
  live); policy-head first trick #972, whole-hand lead admission #973, the oracle-worlds diagnostic #975 (screen
  harness only) and two-card bury swaps #984, all flag-gated off; the lead-admission diagnostic #955, the #977
  harvest fix, tests and Atlas.
- Served bot: `pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv-7a73e8fbf1a8`, exactly the
  name v76bwv44 screened, derived by the registry from the `fly.toml` env and pinned by
  `tests/test_bury_fly_config.py`.
- Package: `smv3out-491ee4bf.npz`, sha256
  `491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670` (`/healthz` `pv_search.sha256`);
  prior `0d17fd03…` under `prior` (the retained release-28 keys; threshold 1000, top 256). 64 worlds,
  8 admitted candidates, 3 s play budget, hybrid bury at 2 s. Package, prior, widths and budgets unchanged from
  release 38.
- Search-rule flags, each `'1'`: `SHENGJI_PV_ADMISSION_DIVERSITY`, `SHENGJI_PV_REFUSAL_CONSTRAINTS`,
  `SHENGJI_PV_TIEBREAK_POINTS`, `SHENGJI_PV_LEAD_ANCHOR` (release 38), `SHENGJI_PV_DOOMED_THROW_RESELECT`
  (release 43), `SHENGJI_PV_VALUE_DECLARE` (release 44, #952; served off the event loop through #959, heuristic
  on expiry or error, `pv-declare-serving-fallback-v1`), and since release 45 the wide value-only bury
  `SHENGJI_PV_BURY_WIDE_VALUE = '1'` with `SHENGJI_PV_BURY_WIDE_K = '64'` (#974, token `bwv`): the bury
  candidate set widens to 64 (the hybrid ballot plus the heuristic incumbent's single-card swaps) and the value
  head's mean over 32 model worlds picks the bury, with no MC stage; the 2 s bury budget and heuristic fallback
  are unchanged. Play and declaration are release 44's (the play digest is unchanged; only the bury digest moves).
- Evidence (ladder row 14 in `AI_POLICIES.md`): v76bwv44, ten fresh first-round windows vs release 44 as served,
  +0.048824 [+0.028614, +0.069034] POSITIVE, 10/10 windows positive; points +1.309 [+0.877, +1.741]. Not
  confirmed on fresh seeds, and the arm changes width and chooser together, so the gain is not attributed to
  either. Gates as met: Codex PASS at the exact head `2a2d7844` and CI 8/8; validated server-path smoke on the
  merged tree `1ca97051` (`scripts/smoke_release45_bury.py` with its receipt validator, compiled engine, single-thread BLAS, the production packages; receipt sha256
  `d6d8685be812474376dd23f9707f9aa6c4beef09cd1315ecdfd4081e4c7c77ac`): 40 rounds, 40 buries through `_paced_bot_step` / `_commit_bot_turn`, p50 0.218 / p90 0.226 / max 0.234 s, 64 candidates each (legal pool ≥ 155), 0 fallbacks, 40/40 committed exactly once; 160 play turns, p50 0.061 / max 0.093 s; 129 value-declare decisions, search max 0.059 s; validator PASS; `/healthz` after deploy
  reports the name above, `fast: true`, bury arm hybrid at 2 s, 64 worlds, 8 candidates, and the unchanged
  package and prior. The smoke ran on the Mini; Fly's shared CPU is slower, and the first live rooms' `bury`
  timings are the check.
- Rollback: in `fly.toml` delete the two `SHENGJI_PV_BURY_WIDE_*` lines and restore the release-44
  `SHENGJI_BOT` kept as the comment directly above it
  (`pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-6c1fb26b80e6`), then
  `fly deploy --ha=false`; or redeploy the release-44 image:
  `flyctl deploy --app shengji --ha=false --image registry.fly.io/shengji:deployment-01M4PC7724HSXC27PCEEREZWY4`
  (Fly v44). No package moves either way. Deeper: release 43 by deleting the `SHENGJI_PV_VALUE_DECLARE` line too
  (image `deployment-01M4H37RYNM42YHH6ZPEC6GKCK`); release 42 by swapping the re-select line for the swap line;
  release 38 by deleting both; release 36 by deleting the four release-38 rule lines as well.
- Comparator: new screens compare against release 45 as served (Jerry, in-session 2026-10-13: "Yes change to
  45", recorded on #988 issuecomment-6142666693). Confirmations keep their parent's comparator; screens already read
  against earlier releases (v75lpft44, v76bwv44 vs release 44) keep their declared comparator.
- Watch list: `/healthz` bot is the name above; `bury` and `model_search` `phase=bury` timings and any
  `cwv-bury-fallback-v1` record (a budget fallback rate above a few percent is the rollback trigger); the
  release-44 declare records (`declare_decision`, `pv-declare-serving-fallback-v1`); decision wall p50/p95; the
  first live room's log. Live acceptance pending: the first live room completing a game without fallback records.
- Next deploy (the first to ship the `/healthz` `activity` counters; board #707 row D4): the deciding test is a
  real game. Production wrote no room log between 2026-10-09 19:04Z and at least 10-15, and nothing could tell
  inactivity from a silent write failure. After the deploy the game must create `/data/logs/<CODE>.jsonl` at its
  `round_start` (read-only: `fly ssh console -a shengji -C "ls -lt /data/logs" | head -3`) and move the counters:
  `rooms_created`, `games_started`, `rounds_recorded` and `records_written` all at least 1,
  `record_write_failures` 0, `last_record_write` at the game's time. `games_started` moving while
  `rounds_recorded` stays 0 is a write failure, named by `last_record_failure` and by the one warning line
  `room <CODE> event logging failed (<class> errno=<name>)`. Whether to play that game deliberately is Jerry's call.
- Earlier records: releases 28–38 in
  [docs_archive/deploy-releases-28-38.md](docs_archive/deploy-releases-28-38.md); the release 39–41
  overlay recipe in the [#778 release record](https://github.com/jerryyyu/shengji/pull/778#issuecomment-5988860620)
  (do not replace main's normal Dockerfile with it).

## The `pv-search` bot mode (policy/value search) — production since release 29

The head-driven search that beat the deployed package in card play (soft 8ecd4fea head, W64/K8,
+0.086 [+0.042, +0.131] on 800 matched deals, 2026-09-21; atlas row 45) is the production bot
mode: `train/pv_search_policy.py`, registered when `SHENGJI_PV_CKPT` is set (the mode refuses a package
without its `SHENGJI_PV_SHA256` pin). It is the screened design (`train/policy_value_search.py`),
served from ONE NumPy package as both value evaluator and policy prior, without Torch. The served env
and bot name are in `fly.toml` and "Current production" above.

What it does per card-play decision: heuristic anchor first; W sampled worlds through production's
sampler (void-checked); the policy head ranks the capped legal listing (cap 4,000, the anchor forced in) and admits K with the anchor
pinned; the value head scores each admitted action's afterstate (current trick finished
heuristically) in every world; the highest mean plays. Declare is the heuristic through release 43 and, since release
44, the value-guided declaration (`SHENGJI_PV_VALUE_DECLARE`; fallback record `pv-declare-serving-fallback-v1`). Bury
is the release-27/28 value-guided hybrid arm on the same package (`SHENGJI_PV_BURY_ARM`, `SHENGJI_PV_BURY_*`,
`SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS`; `PVSearchBuryBot`), since release 45 with the wide value-only chooser
(`SHENGJI_PV_BURY_WIDE_VALUE`, `SHENGJI_PV_BURY_WIDE_K`; fallback record `cwv-bury-fallback-v1`). Release 46 draws the
play worlds history-legal and belief-proposed (`SHENGJI_PV_WORLD_HISTORY_LEGAL`, `SHENGJI_PV_WORLD_HISTORY_DRAW`,
`SHENGJI_PV_BELIEF_WORLDS` with the hash-pinned `SHENGJI_PV_BELIEF_CKPT`; `ai/history_legality`, `ai/belief_numpy`;
the record carries `history_*`, `belief_fallback`, `belief_proposed`, `belief_ms` and the belief log), adds the exact
endgame stages on the play decision (`SHENGJI_PV_EXACT_LEAD_ENDGAME`, `SHENGJI_PV_EXACT_DEEP_CARDS`,
`SHENGJI_PV_EXACT_FOLLOW` and its solver/max-cards/nodes knobs; `pv_exact_deep`, `pv_exact_follow`,
`ai/endgame_compact` on the compiled `_endgame_fast`; the record carries `exact_lead_status`, `exact_lead_seconds`
and the `exact_follow_*` fields, and a stage that does not complete leaves the finalized baseline choice) and opens
the value declaration at every first-round chance (`SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST`; record `gate`). On budget expiry or any search error the sampler RNG is restored and the anchor
plays with a `pv-search-fallback-v1` record; otherwise the record is `pv-search-decision-v1`
(carries `played`, the admitted indices, value means, work counts).

The release gate for this mode is the Release checklist above; each new package repeats it.

## Releases 22–28 records (archived 2026-10-01)

The records for releases 25–28 (the release-28 plan as approved, release 27, the release-26 image
rollback, release 25 and its plan) and the release-22 "current production and rollback boundary"
section (hybrid bury on W32, the September-8 W32 rollout, the release-19/18 boundaries) moved verbatim
to [docs_archive/w32-fly-serving-through-2026-09-22.md](docs_archive/w32-fly-serving-through-2026-09-22.md)
(heading "Moved from DEPLOY.md on 2026-10-01"). Release 28 itself, the rollback for release 29, is a row in the
Releases table above and a section of [docs_archive/deploy-releases-28-38.md](docs_archive/deploy-releases-28-38.md).

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
Live Fly time is workload-dependent; the served policy's measured play and
bury latency is in the merged-tree smoke under "Current production" above (earlier releases: `docs_archive/deploy-releases-28-38.md`). Off-loop execution hides event-loop blocking and overlaps
the 0.7s pacing floor; it does **not** make search free or let a worker react
before the latest play. Each turn snapshots only after that play, computes,
then revalidates before commit. Load-test the chosen policy and concurrent room
mix before advertising capacity. Memory per room is small; scaling beyond one
process would require external state and room-affinity routing.
