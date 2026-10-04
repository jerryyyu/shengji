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
for releases 29–38):

1. A non-author PASS on the PR at its exact head, and all CI checks green. CI fetches the pinned
   production package and loads it on the tree (`.github/workflows/pr-checks.yml`);
   `server/tests/test_bury_fly_config.py` pins the served name that the `fly.toml` environment derives.
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

## Current production (release 38)

- Served bot: `pv-search-491ee4bf-w64-k8-div-rc-tb-la-r7092480e-bury-hybrid-5517ddbd7457`, derived by
  the registry from the `fly.toml` env and pinned by `tests/test_bury_fly_config.py`.
- Package: `smv3out-491ee4bf.npz`, sha256
  `491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670` (`/healthz` `pv_search.sha256`);
  prior `0d17fd03…` under `prior` (the retained release-28 keys). 64 worlds, 8 admitted candidates,
  3 s play budget, hybrid bury at 2 s.
- Search-rule flags, each `'1'`: `SHENGJI_PV_ADMISSION_DIVERSITY`, `SHENGJI_PV_REFUSAL_CONSTRAINTS`,
  `SHENGJI_PV_TIEBREAK_POINTS`, `SHENGJI_PV_LEAD_ANCHOR`.
- Rollback: in `fly.toml` delete the four `SHENGJI_PV_*` rule lines and restore the release-36
  `SHENGJI_BOT` kept as the comment directly above them
  (`pv-search-491ee4bf-w64-k8-r4a09aef5-bury-hybrid-355958b4db25`), then `fly deploy --ha=false`; or
  redeploy the release-37 image `deployment-01M3TXZ85YHJM108TBPWKN8BB2`. No package moves either way.
  Deeper: release 30 by its three commented lines; release 28 by `SHENGJI_BOT` alone.
- **Every NEW screen compares against release 38 as served** (Jerry, 2026-10-03). Screens already
  read against release 36 or the combo keep their declared comparator.
- Watch list: `/healthz` bot is the name above; `pv-search-fallback-v1` records, decision wall
  p50/p95, bury seconds; the first live room's log.
- Full record (evidence, preconditions as met, latency):
  [docs_archive/deploy-releases-28-38.md](docs_archive/deploy-releases-28-38.md).

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
heuristically) in every world; the highest mean plays. Declare is the heuristic; bury is the release-27/28 value-guided hybrid arm on the same package
(`SHENGJI_PV_BURY_ARM`, `SHENGJI_PV_BURY_*`, `SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS`; `PVSearchBuryBot`). On budget expiry or any search error the sampler RNG is restored and the anchor
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
bury latency is in the release-38 record in `docs_archive/deploy-releases-28-38.md`. Off-loop execution hides event-loop blocking and overlaps
the 0.7s pacing floor; it does **not** make search free or let a worker react
before the latest play. Each turn snapshots only after that play, computes,
then revalidates before commit. Load-test the chosen policy and concurrent room
mix before advertising capacity. Memory per room is small; scaling beyond one
process would require external state and room-affinity routing.
