# Deploying Sheng Ji

The operator runbook: what is serving now, how to roll it back, and how to ship the next release.
Policy evidence lives in `AI_POLICIES.md` (the ladder table); measurement rules live in `RL_PLAN.md`.
Release records through release 46 in full: [docs_archive/deploy-through-2026-10-16.md](docs_archive/deploy-through-2026-10-16.md).

## Terms

| term | meaning |
|---|---|
| served name | the `SHENGJI_BOT` value; the registry derives it from the `fly.toml` env, and `/healthz` reports it as `bot` |
| play package | the NumPy value net (the evaluator at every stage): G3 Stage A's `g3a-e04-f4f4127e.npz` in release 50; `smv3out-491ee4bf.npz` in releases 36–49, where it was also the card-play policy head |
| card-play prior | the policy net that admits the card-play candidates, under `SHENGJI_PV_PRIOR_*`: FT1's `p0-ft1-1fa201b2.npz` in release 50 (releases 36–49 used the play package's own head) |
| prior (`/healthz` `prior`) | the JS-M1 package `js-m1-0d17fd03.npz`, kept under the `SHENGJI_CWV_PRIOR_*` keys for the release-28 rollback; the served `pv-search` bot does not consult it |
| belief package | the hidden-hand model: B1a's `b1a-028131a0.npz` in release 50; S58's `s58-e6-42444515.npz` in releases 48 and 49; S17's `s17long-e2-763b5e05.npz` in release 46 |
| volume | the Fly volume mounted at `/data`; packages in `/data/models`, room logs in `/data/logs` |
| image | `registry.fly.io/shengji:<image>`; Fly numbers each deploy `vNN` |
| smoke | a run of the served bot through the server path (`_paced_bot_step` / `_commit_bot_turn`) |
| first-room reader | the Python snippet in step 9 of the Release checklist, run once on the first live room's log |

Every deploy so far ran on machine `48e7e35a9597e8`, app `shengji`.

## Release 52 (prepared for deploy)

**Release 52** (prepared): release 51 with the combo51 search rules. The exact lead keeps the baseline lead unless the exact
pass is strictly better (`elt`), solves its own first trick by full minimax (`elm`) and stops at 1.6 s
(`els1600`); the play worlds keep every earlier accepted throw legal (`wht`); refusals are recorded from every
committed play (`rcec`). Same packages, same stage table (`server/releases/r52.json`), and sc8, lcc off, every other
rule, every budget and the latency switches are release 51's. Prepared for deploy; until `/healthz` shows the name
below, production is release 51 ("Current production", below), served by Fly v63. At the deploy, this section
becomes "Current production" and release 51's moves under "Rollback" (Release checklist, step 11).

| field | value |
|---|---|
| deployed | pending deploy (fill in: ET and Z time, room count). Jerry's word: in session 2026-11-09, "I'm good to release it" |
| Fly version | pending deploy (rollback: v63 for release 51 with the current web client; v61 for release 51's original deploy) |
| image | pending deploy |
| source | the release-52 branch head, release 51's `1490b72b` server (below), deployed from a clean worktree at that commit |
| evidence | combo51 SCREEN_PASS and combo51C CONFIRMED against release 51, Fly v61's bot (Evidence, below) |
| deploy record | pending deploy |
| comparator | release 51 as served until the deploy[^cmp]; after it, release 52 as served |

**Source.** The release tree is release 51's commit `1490b72bf186180b1480c95ed825d1d3e7696737` with three
changes: `fly.toml` gains the five lines below and the release-52 name; `web/` is main's (the client Fly v63
serves); the tests, the manifest `server/releases/r52.json` and the docs record the release. `server/shengji/`,
`server/scripts/`, the build files and `Dockerfile` are `1490b72b`'s byte for byte: combo51 and combo51C cloned and
built exactly that commit on the M5 Ultra (`src-1490b72b`; their status lines record the tree sha). Main's later
bot-path commits (#1314, #1316, #1325) are not in the screened tree and do not ship in release 52.

Served name:

```
pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-rcec-whl-whd-wht-bw-tb-ele-elt-elm-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-els1600-xf7-xfcompactlevel-r12e81e0c-bury-hybrid-bwv-bbw-7a9a430fe690-sc8
```

The registry derives it from the `fly.toml` env: the five lines add `-rcec`, `-wht`, `-elt -elm` and `-els1600` to
the play token, and the play digest (`r30ff6f0f` → `r12e81e0c`) and the bury suffix (`73a716a9bf72` → `7a9a430fe690`)
move with the play identity. It is byte for byte the exploiter name combo51 and combo51C duelled against release 51
(`test_release52_fly_config.py` derives it from the `/data/models/` paths and builds it on the pinned packages).

### Packages

Release 50's, unchanged; nothing to upload.

### `fly.toml` keys

| change | `fly.toml` | name token |
|---|---|---|
| exact lead keeps the baseline on ties | `SHENGJI_PV_EXACT_LEAD_TIE_BASELINE = '1'` | `-elt` |
| exact lead solves its first trick by full minimax | `SHENGJI_PV_EXACT_LEAD_FULL_MINIMAX = '1'` | `-elm` |
| exact lead cap 1.6 s (default 2.25 s) | `SHENGJI_PV_EXACT_LEAD_MAX_SECONDS = '1.6'` | `-els1600` |
| history-legal throws in the play worlds | `SHENGJI_PV_WORLD_HISTORY_THROWS = '1'` | `-wht` |
| event-complete refusals | `SHENGJI_PV_REFUSAL_EVENT_COMPLETE = '1'` | `-rcec` |

Every other line is byte-identical to release 51's. `server/tests/test_release52_fly_config.py` builds the served
bot from this env on the three pinned release-50 packages as the server does, checks the name, that exactly these
five config fields move against release 51, and plays two leads through the server path (one above the exact bound,
one at SDUS round 2 trick 14 inside it, where the exact stage completes with the minimax first trick); it also
builds the release-51 rollback. `test_release_manifests.py` checks that `fly.toml` equals `r52.json`'s env and that
release 52 differs from release 51 only in these lines and the name.

### What changes at serving time

- **Exact leads (7 cards or fewer).** The exact stage plays each candidate's own first trick by minimax instead of
  finishing it with the heuristic; it replaces the searched lead only when the exact mean is strictly higher; and it
  stops at 1.6 s (release 51: 2.25 s), keeping the searched lead when it runs out. On the duel host the combo
  abandoned 1.6% of the exact-lead stages it started, every one at the 1.6 s cap.
- **World sampling.** A sampled world is rejected when it would have refused an earlier throw that stood (`wht`).
- **Refusals.** The server's room bot records each refused throw after every committed play
  (`api.server._observe_committed_play`), not only on its own turns, so the refusal constraint (`rc`) misses none.
- **Follows, declaration, bury.** Unchanged.

### Evidence

Paired, seat-swapped head-to-head duels on the M5 Ultra, release 51 + the five lines against release 51 (the Fly v61
bot, lcc off on both sides), at the 3 s play and 2 s bury budgets, under the two-stage duel bar. Each read is judged
alone, never pooled.

| read | deals | result (release 52 − release 51) | verdict | pointer |
|---|---|---|---|---|
| combo51 (screen) | 3,920 fresh deals from 248310910 | +0.0418 [+0.0332, +0.0506]; one-sided 80% lower bound +0.0381 | SCREEN_PASS | [#1313 issuecomment-6683910756](https://github.com/jerryyyu/shengji/pull/1313#issuecomment-6683910756), `readouts/combo51/` (reader `3557a655`) |
| combo51C (confirmation) | 7,840 fresh deals from 248410910 | **+0.0438 [+0.0381, +0.0497]**; one-sided 95% lower bound +0.0389 | CONFIRMED | [#1315 issuecomment-6687062999](https://github.com/jerryyyu/shengji/pull/1315#issuecomment-6687062999), `readouts/combo51C/` (reader `4d190a77`) |

Validity on both sides in both reads: 0 play, belief and bury fallbacks, 0 declare abandons. combo51C's
first-divergence locator finds its three largest gain cells at leads in tricks 11 and later (the exact stage's
range), +0.0249 of the +0.0438 together. These are
duel-host reads; **the strength and the latency of release 52 on Fly are not measured.**

### Latency

| read | what | result | pointer |
|---|---|---|---|
| combo51C (M5 Ultra duel host, descriptive) | exact-lead stage, combo vs release 51 | stage seconds p50/p95/p99/max 0.013/0.685/1.6/1.601 vs 0.014/0.206/0.486/2.25; abandoned 532 of 33,184 started (1.6%, all at the cap) vs 5 of 31,356; lead decision p99 0.858 vs 0.367 s; mean decision time ratio 1.059 | `readouts/combo51C/` |
| Fly timing | the exact-lead tail on the production machine at 0 rooms | **pending** (a packet is in preparation) | — |

The exact-lead tail is the release's cost: leads that reach the stage can now run to the 1.6 s cap where release 51
mostly finished under 0.5 s. A Fly core is slower than the duel host, so the share of stages that hit the cap is
expected to be higher on Fly; the Fly timing read measures it before the deploy.

### Pre-deploy smoke (release tree, this host)

`smoke_release45_bury.py --rounds 10 --full-round` on the release branch (commit `fa190d03`, clean; `fly.toml`,
`server/` and `Dockerfile` as in the PR head) with sha-verified local packages (the three release-50
`serving-packages` assets and JS-M1), Mac mini M4, compiled engine, run 2026-11-09 15:36–15:41Z while an X4
data-generation leg held 8 of the host's 10 cores (load 11–18), so the timings below are contended M4 timings, not
Fly's. Archived in `~/shengji-archive/2026-11-09-r52-smoke/` with `SHA256SUMS` (`e67df960…`; receipts `smoke52.jsonl`
`5c31623b…`, `smoke52b.jsonl` `cb544640…`). Every receipt's bot is the
release-52 name above, class `SingletonChallengerBuryBot`, `bot.files` value `f4f4127e`, prior `1fa201b2`, belief
`028131a0`, JS-M1 `0d17fd03`, compiled engine.

| run | validator | buries (belief worlds, bury-belief fallbacks) | plays, belief fallbacks | exact-eligible leads + follows, abandons, fallbacks | exact-lead stage s p50/p95/p99/max | decision s p95/max |
|---|---|---|---|---|---|---|
| smoke52 | PASS | 10 (10, **1**: the first bury's cold belief preparation, 338 ms over the 0.25 s limit) | 696, 0 | 55 + 101, 1 (`soft_budget` at 1.6 s), 0 | 0.020/0.755/1.600/1.600 | 0.566/1.634 |
| smoke52b (repeat) | PASS | 10 (10, 0) | 696, 0 | 55 + 100, 1 (`soft_budget` at 1.6 s), 0 | 0.022/0.706/1.600/1.600 | 0.621/1.627 |
| smoke51ctl (release 51's `fly.toml`, same tree and host) | PASS | 10 (10, 0) | 704, 0 | 57 + 102, 0, 0 | 0.020/0.285/0.562/0.562 | 0.512/1.014 |

Both release-52 runs: no `lcc` status on any record; `sc8` applied on 46–47 leads; every started exact lead used the
minimax first trick (49 of 49) and the tie rule kept the baseline on 31–32; 0 decisions at 3 s. The one exact-lead
abandon per run is the same lead, at the designed 1.6 s cap, and plays the searched lead, as on the duel host. The
first-bury fallback in smoke52 did not repeat in smoke52b (first bury 19.7 ms) or the control: it is the documented
cold-boot case (Release checklist, step 9), on a contended host.

### Watch list

Release 51's rows of the first-room rollback triggers (Release checklist, step 9). New for release 52: the
exact-lead tail. Record the share of started exact-lead stages that abandon (`exact_lead_status == "abandoned"`,
reason `soft_budget` at the cap) and the exact-lead decision p95/max; any other abandon reason is a defect.

### Release note: what a player will notice

- **Stronger endgame leads.** With 7 or fewer cards the bot leads after solving the whole trick, not a heuristic
  guess of it, and keeps its searched lead unless the solve finds a strictly better one.
- **Slower endgame leads, sometimes.** Those leads can take up to about 1.6 s of thinking.
- **Fewer impossible card reads.** The bot no longer imagines hands that contradict a throw that stood.

### Rollback to release 51

Release 51 as served before release 52: Fly v63 (web-only redeploy of release 51 with main's client, tree
`claude/deploy-r51-web-ios` at `ae1ef0abfb41ad63cf6c987d8ffd30f55722696c`), whose bot is the one Fly v61 first
served from main `1490b72b`. Its packages are release 52's. Release 51's served name:

```
pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-r30ff6f0f-bury-hybrid-bwv-bbw-73a716a9bf72-sc8
```

**Option 1, restore v63's image and configuration** (no build). An image-only deploy still applies the
caller's `fly.toml`; it would leave the release-52 flags enabled. Prepare this rollback pair before deploying
release 52, from a clean release worktree with its Python environment installed:

```bash
rollback_dir=$(mktemp -d "$HOME/shengji-archive/r51-rollback.XXXXXX")
rollback_config="$rollback_dir/fly.toml"
rollback_image='registry.fly.io/shengji:deployment-01M7059VAETQFCMM6Z3ADYKRPM'
git show ae1ef0abfb41ad63cf6c987d8ffd30f55722696c:fly.toml > "$rollback_config"
PYTHONPATH=server server/.venv/bin/python - "$rollback_config" <<'PY'
import hashlib
import sys
from pathlib import Path
from shengji import releases

config = Path(sys.argv[1])
assert hashlib.sha256(config.read_bytes()).hexdigest() == (
    "217f40e70604157f882f00212e5cb4ec05fed188df2e66923f91c1bead16a0dd"
)
env = releases.fly_env(config)
r51 = releases.load(51)
assert env == r51["env"]
assert env["SHENGJI_BOT"] == r51["bot_name"]
assert not any(key in env for key in (
    "SHENGJI_PV_EXACT_LEAD_TIE_BASELINE", "SHENGJI_PV_EXACT_LEAD_FULL_MINIMAX",
    "SHENGJI_PV_EXACT_LEAD_MAX_SECONDS", "SHENGJI_PV_WORLD_HISTORY_THROWS",
    "SHENGJI_PV_REFUSAL_EVENT_COMPLETE",
))
print("Verified release-51 rollback configuration:", config.resolve())
PY
```

Stop if extraction or verification fails. Confirm the recorded v63 image against `fly releases -a shengji --image`
and preserve the absolute config path and image in the deploy record. If that image is unavailable, stop and
prepare a separately reviewed replacement; do not substitute main's config. Keep the rollback directory with the
release evidence. When resuming in a new shell, recover the recorded absolute path and image and verify again.

Only on Jerry's rollback decision, at 0 rooms (or his explicit instruction to drop idle rooms), execute the paired
rollback; this command is not part of preparation:

```bash
flyctl deploy --app shengji --ha=false --config "$rollback_config" --image "$rollback_image"
```

Afterward `/healthz` must be healthy, compiled and show the exact release-51 name above, with the unchanged pinned
packages. Record the new Fly version and both the image and config used; no automatic rollback or retry is implied.

**Option 2, rebuild the release-51 source:** use a clean worktree at
`ae1ef0abfb41ad63cf6c987d8ffd30f55722696c`, including its `fly.toml`, to retain v63's web client. Run the release-51
qualification checks there before any authorized deploy. Editing only release 52's `fly.toml` does not switch
`test_release_manifests.py` to r51: that test explicitly loads r52. The explicit r51 manifest comparison above
validates the rollback configuration without changing the release-52 manifest or its tests.

## Current production

**Release 51**: release 50 with the held-out lead confirmation off (`SHENGJI_PV_LEAD_CONFIRM = '0'`; `lcc32`
leaves the name). Same packages, same stage table (`server/releases/r51.json`), and sc8, every other rule, every
budget and the latency switches are release 50's. Deployed 2026-11-06 as Fly v61; release 50 (its record is under
"Rollback") is the rollback target.

| field | value |
|---|---|
| deployed | 2026-11-06 02:10 EST (~07:10Z) at 0 rooms. Jerry's word: in session 2026-11-06 ~03:35Z, knowing lccC's measured cost, "im good to turn off lcc, bc for new data gens, etc it will be cheaper" |
| Fly version | v61 (rollback v60: release 50 + web #1305/#1306) |
| image | `registry.fly.io/shengji:deployment-01M6QW43KBFT3ZDDZWM298WPM3` (main `1490b72b`) |
| source | main `1490b72bf186180b1480c95ed825d1d3e7696737` (#1312), deployed from a clean worktree at that commit |
| evidence | `AI_POLICIES.md` ladder row 20 (lccC KEEP_LCC on cloud; loo DROP_SAFE on the M5 Ultra; S91 Fly CPU) |
| deploy record | [#1312 issuecomment-6679669956](https://github.com/jerryyyu/shengji/pull/1312#issuecomment-6679669956): `/healthz` release-51 name, `fast: true`, value `f4f4127e…`, budget 3 s; in-machine `True compiled 028131a0`; first-room reader pending the first live room |
| comparator | release 50 as served until the deploy[^cmp]; after it, release 51 as served (lcc off on both sides of future duels and screens, per Jerry's 2026-11-06 word) |

Served name:

```
pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-r30ff6f0f-bury-hybrid-bwv-bbw-73a716a9bf72-sc8
```

The registry derives it from the `fly.toml` env: with the lead confirmation at 0, `-lcc32` leaves the play token,
and the play digest (`rb3477266` → `r30ff6f0f`) and the bury suffix (`b6262940978b` → `73a716a9bf72`) move with the
play identity. It is byte for byte the lcc-off arm lccC and loo duelled against release 50
(`test_release51_fly_config.py` derives it from the `/data/models/` paths).

### Packages

Release 50's, unchanged; nothing to upload. Keep every release-50 and release-49 package on the volume.

### `fly.toml` keys

| change | `fly.toml` | name token |
|---|---|---|
| lead confirmation off | `SHENGJI_PV_LEAD_CONFIRM = '0'` (release 50: `'32'`) | `-lcc32` removed; play and bury digests move |

Every other line is byte-identical to release 50's. `server/tests/test_release51_fly_config.py` builds the served
bot from this env on the three pinned release-50 packages as the server does, checks the name and
`lead_confirm == 0`, and plays one lead through the server path with sc8 probing and no lead-confirmation stage; it
also builds the release-50 rollback (lcc32 back on). `test_release_manifests.py` checks that `fly.toml` equals
`r51.json`'s env and that release 51 differs from release 50 only in this line and the name.
`server/scripts/y_trajectory.py`, the served-recipe data runner, now requires the lead confirmation off, so new
served-budget self-play data is generated without lcc32.

### What changes at serving time

- **Leads.** On a lead with no exact stage, release 50 screened up to 32 of the policy's next actions on 32 base
  worlds and re-priced up to two challengers on fresh worlds before keeping or replacing the searched lead. Release
  51 skips that stage: the lead is the 64-world search's choice (after sc8, `dtr` and the exact endgame stages, as
  in release 50). Decision records carry no `lead_confirm_*` fields.
- **Follows, declaration, bury.** Unchanged (the stage ran only on leads).
- **CPU.** On Fly, lcc-off plays took 0.55× the CPU per play of lcc-on (S91, below); data generation on the served
  recipe is cheaper by about the same share.

### Evidence

Paired, seat-swapped head-to-head duels inside release 50, its stack with lcc32 off against the same stack with
lcc32 on, at the 3 s play and 2 s bury budgets.
Each read is judged alone, never pooled.

| read | host, deals | result (lcc32 off − on) | verdict | pointer |
|---|---|---|---|---|
| lccC (confirmation) | cloud, 7,840 fresh deals from 247410910 | **−0.0133 [−0.0232, −0.0033]** | KEEP_LCC: turning lcc32 off costs strength on this host | `readouts/lccC/` (reader `dc4d8a81`) |
| loo (leave-one-out) | M5 Ultra, 3,920 deals from 247110910 | +0.0079 [−0.0069, +0.0221] | DROP_SAFE (non-inferiority bar about −0.010) | `readouts/loo/` |

The two reads disagree; release 51 does not claim zero strength cost. On cloud (lccC) the stage applied on 14.7% of
searched leads (19.9% of early ones) and abandoned on 0.14% of the stages it started; lccC's first-divergence locator puts −0.0124 of the −0.0133 at leads, most of it in
tricks 1–5. On Fly the stage rarely completes: in S91 (below) it applied on 1 of 47 and 1 of 137 non-exact leads
(1–2%), and most stages abandoned on the 2 s finish deadline or the budget; in the live rooms UXVG and TBTH it
abandoned in all 57 runs where it ran. **The strength effect of release 51 on Fly is not measured**; it is
expected to be smaller than lccC's cloud cost because the stage rarely changes a Fly lead. Jerry chose release 51
with lccC's cost in view, for the CPU (serving and data generation).

**S91 (Fly, production machine at 0 rooms, two drain runs, k=1 and k=2 concurrent bot rooms).** Unthrottled CPU per
play: lcc off 0.2592 s (650 plays) against lcc on 0.4692 s (508 plays), ratio 0.552. Unthrottled single-room
decision p95: lcc off 0.84–0.91 s, lcc on 2.01–2.02 s. Both arms reached the CPU-credit throttle at minute 16
of a two-room drain; throttled, lcc off had 30 of 170 play-budget fallbacks against 40 of 153 for lcc on, and belief
fallbacks 40 of 170 against 26 of 153. The Codex saved-result audit
([#1263 issuecomment-6673552894](https://github.com/jerryyyu/shengji/issues/1263#issuecomment-6673552894)): lcc off
cuts CPU but does not fix throttled serving; these are descriptive rates (rows share rooms and credit history).
`readouts/S91-fly-lccoff/`.

### Latency

| read | what | result | pointer |
|---|---|---|---|
| S91 (Fly, unthrottled k=1) | lcc off vs on, same release-50 packages | CPU per play ×0.552; decision p95 0.84–0.91 s off vs 2.01–2.02 s on; 0 play-budget, belief and bury fallbacks in both unthrottled single-room cells | `readouts/S91-fly-lccoff/` |
| loo (M5 Ultra duel host, descriptive) | lcc off vs on | lead p95 0.305 s off vs 0.830 s on; decide_play p95 0.272 vs 0.702 s; mean decision time ratio 0.567 | `readouts/loo/` |

### Pre-deploy smoke (release tree, this host)

`smoke_release45_bury.py --rounds 10 --full-round` on the release branch (head `71865ee7`, clean) with sha-verified
local packages (the three release-50 `serving-packages` assets and JS-M1), Mac mini M4, compiled engine, run
2026-11-06 06:02Z after the host's screen ended, under the host lock (receipt `smoke51.jsonl`, sha256
`e9a3a96d…0657`, archived in `~/shengji-archive/2026-11-06-r51-smoke/` with `SHA256SUMS`): validator **PASS**; the
receipt's bot is the release-51 name above, class `SingletonChallengerBuryBot`, `bot.files` value `f4f4127e`, prior
`1fa201b2`, belief `028131a0`, JS-M1 `0d17fd03`, all nine latency switches on. Bury: 10 of 10 committed once, 64
candidates, 0 fallbacks, all 10 on belief worlds with 0 bury-belief fallbacks, wall max 0.221 s; 33 value
declarations. First-room reader over its 10 room logs: 704 plays, 704 belief-drawn, **0 belief fallbacks**;
exact-eligible 57 leads + 102 follows, **0 abandons, 0 fallbacks**; decision p50 0.028 / p95 0.176 / max 0.454 s;
**no `lcc` status on any record**; `sc8` probed 119 leads and applied 47; 0 decisions at 3 s. Split by trick
position: leads (176) p50 0.152 / p95 0.217 / max 0.454 s (release 50's smoke: `lcc` leads p95 0.507 s), follows
(528) p95 0.098 s. A niced test process shared the host during the smoke. These are M4 timings, not Fly's. Re-run
on the merged tree before the deploy (Release checklist, step 3).

### Watch list

Release 50's rows of the first-room rollback triggers (Release checklist, step 9), with every decision p95
against the 1.5 s row (no `lcc` leads remain); no record carries `lead_confirm_status` (any one means the stage
ran: examine); bury-belief fallbacks; the `/healthz` `activity` counters (step 10).

### Release note: what a player will notice

- **Faster leads.** Early leads no longer spend up to 2 s on the confirmation stage; on Fly most such stages
  were abandoned anyway.
- **Rarely a different lead.** Where the stage completed and replaced the lead (about 1–2% of Fly's non-exact
  leads in S91), release 51 plays the search's own choice.

## Rollback

### To release 50 (the rollback target)

Release 50 as served before release 51: Fly v59, image `deployment-01M6NVJGMKP9G0AKFPY9MZ8668`, main `26924ef7`
(the release-50 recipe of #1260 with later decision-identical deploys of main). Its packages are release 51's.
Release 50's served name:

```
pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-lcc32-rb3477266-bury-hybrid-bwv-bbw-b6262940978b-sc8
```

**Option 1, redeploy the image that served release 50** (no build). Before the release-51 deploy, confirm the image
of the release then live with `fly releases -a shengji --image` (v59 above unless a later deploy replaced it) and
write it into the deploy record. Then:

```bash
flyctl deploy --app shengji --ha=false --image registry.fly.io/shengji:<the release-50 image>
```

**Option 2, edit `fly.toml`:** set `SHENGJI_PV_LEAD_CONFIRM = '32'` and `SHENGJI_BOT` to the release-50 name kept in
the comment above it, then `fly deploy --ha=false`; `/healthz` must show the release-50 name. Rolling back also rolls
the manifest check back: `test_release_manifests.py` then compares `fly.toml` with `server/releases/r50.json`.
`test_release51_fly_config.py` builds this rollback env on the release-50 packages with `lead_confirm == 32`.

#### Release 50 record

**Release 50** (the cbaC stack): release 49 with new packages and belief bury worlds. The value package is G3 Stage
A's (`g3a-e04-f4f4127e`), the card-play prior is FT1's (`p0-ft1-1fa201b2`), the belief package is B1a's
(`b1a-028131a0`, in place of S58), and the wide value-only bury scores its candidates on belief-drawn worlds
(`bbw`). lcc32, sc8, every other rule, every budget and the latency switches are release 49's. Production from
2026-11-04 15:24 EST (Fly v57) until release 51's deploy; v58 (main `90f850ee`: #1259 native reply counts, X-ray,
saved games phase 1) and v59 (main `26924ef7`: web) redeployed it from main with the same served name and
decisions.

| field | value |
|---|---|
| deployed | 2026-11-04 15:24 EST (20:24Z) at 0 rooms; Jerry's word: in session 2026-11-04 ~14:05 ET, "I'm good to ship and we can manage what to do with lcc after" |
| Fly version | v57 |
| image | `registry.fly.io/shengji:deployment-01M6M3PX2A43CPZ65RBQPRY8AB` (`sha256:92badd5749996c0a2423b1ff2c6f7a4d0d492bfd68df06ba93d9162903895bec`) |
| source | main `db3a5c6d8c6b5f32e2055d042333a3e843e8a659` (#1260), deployed from a clean worktree at that commit |
| evidence | `AI_POLICIES.md` ladder row 19 (cbaC CONFIRMED; cbaf arm a SCREEN_PASS; rtF red team; latency: the R50 speed profile, Fly timing pending) |
| deploy record | [#1260 issuecomment-6641264830](https://github.com/jerryyyu/shengji/pull/1260#issuecomment-6641264830): `/healthz` bot, `fast: true`, value `f4f4127e…`, budgets 3 s / bury 2 s, latency switches as `fly.toml`; in-machine `True compiled 028131a0`; first-room reader and room-log write check pending the first live room |
| comparator | release 50 as served for new duels and screens (Jerry, in session 2026-11-04: "Yes move comparator")[^cmp] |

Served name:

```
pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-lcc32-rb3477266-bury-hybrid-bwv-bbw-b6262940978b-sc8
```

The registry derives it from the `fly.toml` env. The value package's hash heads the name (`f4f4127e`), the separate
prior adds `-prior-1fa201b2`, the value and belief hashes are in the play digest (`rb3477266`), and
`SHENGJI_PV_BURY_BELIEF_WORLDS = '1'` adds `-bbw` to the bury token (its digest `b6262940978b` moves with the play
identity); `-sc8` is release 49's. Package paths do not enter the name: it is the name cbaC confirmed, which its
host derived from packages under `/root/claude-cbaC/`, byte for byte (`test_release50_fly_config.py` derives it
from the `/data/models/` paths).

##### Packages

Three new packages, all assets of the `serving-packages` GitHub release under the same file names; upload them before
the `fly.toml` switch (Release checklist, step 2). Keep every release-49 package on the volume for the rollback.

| package | path on the volume | sha256 | `/healthz` field |
|---|---|---|---|
| value (G3 Stage A, EMA export of epoch 4, `epoch-04.avg.pt` `a09cef7c`) | `/data/models/g3a-e04-f4f4127e.npz` | `f4f4127ec0c8821b4aa07f7d651a4258c696f97a874707da2c78ad26c0c9b9fd` | `pv_search.sha256` |
| card-play prior (FT1) | `/data/models/p0-ft1-1fa201b2.npz` | `1fa201b288e78b3072979f55030aae44711ee214b50a14e155d0bbe11b6bb1bf` | not reported[^pvprior] |
| belief (B1a, stored temperature 1.0190) | `/data/models/b1a-028131a0.npz` | `028131a03de0c69b5164cdd0f65369950340f58fe226f75d6d877aeda2ca8fc8` | not reported[^belief] |
| JS-M1 (release-28 rollback keys, unchanged) | `/data/models/js-m1-0d17fd03.npz` | `0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747` | `prior` |
| value and policy (releases 36–49, kept for the rollback) | `/data/models/smv3out-491ee4bf.npz` | `491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670` | — |
| belief (S58, releases 48–49, kept for the rollback) | `/data/models/s58-e6-42444515.npz` | `424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e` | — |
| belief (S17, release 46, kept for its rollback) | `/data/models/s17long-e2-763b5e05.npz` | `763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343` | — |

##### `fly.toml` keys

What release 50 changes in release 49's environment (with `SHENGJI_BOT`; every other line byte-identical):

| change | `fly.toml` | name token |
|---|---|---|
| value package (changed) | `SHENGJI_PV_CKPT = '/data/models/g3a-e04-f4f4127e.npz'`, `SHENGJI_PV_SHA256 = 'f4f4127e…'` | `pv-search-f4f4127e` |
| card-play prior (added) | `SHENGJI_PV_PRIOR_CKPT = '/data/models/p0-ft1-1fa201b2.npz'`, `SHENGJI_PV_PRIOR_SHA256 = '1fa201b2…'` | `-prior-1fa201b2` |
| belief package (changed) | `SHENGJI_PV_BELIEF_CKPT = '/data/models/b1a-028131a0.npz'`, `SHENGJI_PV_BELIEF_SHA256 = '028131a0…'` | the play digest moves |
| belief bury worlds (added) | `SHENGJI_PV_BURY_BELIEF_WORLDS = '1'` | `-bbw` after `-bwv` |

`server/releases/r50.json` is this env with its stage table: G3 A is the value at every stage, FT1 the prior at
lead, follow and endgame, B1a the worlds at bury, lead, follow and endgame, and declare keeps its uniform deals.
`server/tests/test_release_manifests.py` checks that `fly.toml` equals that env and that the served bot's forwards
and samplers match the table on a seeded round.

`server/tests/test_release50_fly_config.py` builds the served bot from this env on the three pinned packages as the
server does (the registry's import-time registration, then `make_bot(SHENGJI_BOT)`), checks every knob and each
package's sha, plays one lead through the server path and decides one bury on B1a's worlds with no fallback; it also
builds the release-49 rollback on its own packages. `test_release49_fly_config.py`, `test_release48_fly_config.py`
and `test_release46_fly_config.py` build releases 49, 48 and 46 from the rolled-back env, and
`test_bury_fly_config.py` pins the name chain 50 → 49 → 48 → 46 → 45 and the deeper rollbacks.

##### What changes at serving time

- **Value.** Every value forward (declare, bury, play, the lcc and sc8 stages) runs on G3 Stage A's package, an
  EMA export of epoch 4 of the unified retrain on all Y data. Its policy head is not consulted for card play.
- **Prior.** The card-play policy rows (admission, `div`, `la`, the lcc pool, sc8's ballot and the greedy-finish
  replies) come from FT1's package, `p0-ft1-1fa201b2`. Declaration and bury call no policy head (the `lpft` rule is
  off).
- **Belief.** B1a (S58 fine-tuned on all four Y stores) proposes the hidden hands at its stored temperature;
  the runtime and the fallback to the history-legal draw are release 48's.
- **Bury worlds (`bbw`).** The wide value-only bury's 32 model worlds are drawn by the belief package on the bury
  state's trick-1 twin (the banker's first lead after burying the heuristic incumbent) instead of the split
  sampler. The draw has its own seed stream and runs inside the 2 s bury budget; any draw error falls back for that
  decision to the split sampler's worlds and is recorded as `bury_belief_fallbacks` 1 with `bury_belief_error`.
  Records gain `bury_belief_worlds`, `bury_belief_fallbacks`, `bury_belief_error` and `bury_belief_ms`.
- Everything else is release 49's: `sc8`, `lcc32`, exact endgame at 7 cards, `dtrx`, `lgf lgfx lgfd2000`, the value
  declaration, the latency switches. The lcc decision is open: Jerry ships release 50 with lcc32 on and decides
  lcc afterwards ("we can manage what to do with lcc after"; loo below).

##### Evidence

Paired, seat-swapped head-to-head duels against release 49 as it was then served (Y: S58 belief, no bbw), served budgets, r2
rank-mixed round plan per deal, the two-stage bar (screen: mean ≥ +0.005 and one-sided 80% lower bound > 0;
confirmation: mean ≥ +0.005 and 95% lower bound > 0, on fresh deals). Each read is judged alone, never pooled.

| read | what | result | validity | pointer |
|---|---|---|---|---|
| cbaC (stage-2 confirmation, cloud, 7,840 fresh deals from 246710910) | the full release-50 stack vs release 49 | **+0.0618 [+0.0507, +0.0729]**, CONFIRMED | VALID; 0 play fallbacks of 517,390 decisions per side, 0 belief fallbacks, 0 bury fallbacks and 0 bury-belief fallbacks of 7,832 buries, 0 declare abandons; 130 lcc abandons, all `leaf_deadline` | readout [#1171 issuecomment-6629156672](https://github.com/jerryyyu/shengji/pull/1171#issuecomment-6629156672); Codex saved-result audit [#1171 issuecomment-6629239690](https://github.com/jerryyyu/shengji/pull/1171#issuecomment-6629239690); `readouts/cbaC/` |
| cbaf arm a (stage-1 screen, M5 Ultra, 3,920 deals) | the same stack | **+0.0695**, one-sided 80% lower bound +0.0631, SCREEN_PASS | VALID; 0 play, belief, bury fallbacks | [#1171 issuecomment-6637319197](https://github.com/jerryyyu/shengji/pull/1171#issuecomment-6637319197); `readouts/cbaf/` |
| cbaf contrast a − s (paired on cbaf's deals) | B1a against S58 on this stack (both with bbw) | **+0.0228**, 97.5% CI [+0.0010, +0.0448], B1A_ADDS | same run | as above |
| cbaf contrast f − a | FT2X4 in place of FT1 | +0.0047, 97.5% CI [−0.0149, +0.0239], UNRESOLVED (FT2X4 not shipped) | same run | as above |

cbaC's margin belongs to the four changes together; it has no attribution among them. Its descriptive splits: first
round +0.0512, fixed banker +0.0689; rank 2 +0.0480, rank ≠ 2 +0.0729. The first-divergence locator puts the largest
cells at the bury (+0.0354 of the +0.0618) and the declaration (+0.0147); a locator, not a causal decomposition.
cbaf was an independent run on another host and is not pooled with cbaC.

**Red team (rtF, cloud, 600 deals from 247010910).** An expert-budget search (Y at W256 / K32 / exact 8, 60 s a
decision, not servable) against the full release-50 stack: **−0.0433 [−0.0842, −0.0042]**, DEFENDER_AHEAD (the
release-50 stack ahead); `readouts/rtF/`. A diagnostic of where the stack loses, not a strength claim for any served
bot.

**lcc (loo, M5 Ultra, 3,920 deals from 247110910).** The release-50 stack with lcc32 off against the same stack with
it on: **+0.0079 [−0.0069, +0.0221]**, DROP_SAFE (the predeclared non-inferiority bar: dropping lcc32 costs at most
about 0.010 levels/round on this host). Release 50 keeps lcc32 on; the lcc decision is Jerry's, after the deploy.
`readouts/loo/`.

**Half budget (hb50, cloud, 3,920 fresh deals from 247310910).** The release-50 stack against release 49 as then
served, both at half the served budgets (play 1.5 s, lgfd 1000 ms, bury 1 s), a cloud-core proxy for the full
budget on an unthrottled Fly CPU: **+0.0520 [+0.0362, +0.0679]**, one-sided 80% lower bound +0.0453,
HALF_BUDGET_PASS; 0 budget fallbacks of 260,644 decisions per side, 0 belief and 0 bury-belief fallbacks. Not a Fly
measurement and not modelling Fly's throttling. Readout
[#1171 issuecomment-6641693008](https://github.com/jerryyyu/shengji/pull/1171#issuecomment-6641693008);
`readouts/hb50/`.

##### Latency

| read | what | result | pointer |
|---|---|---|---|
| R50 speed profile | release 50's stack vs Y, served budgets, one pinned cloud core each, 30 games × 2 rounds per bot (not deal-paired) | Bot compute per round 16.17 s vs 15.94 s (×1.014). Play p50 0.066 / p95 1.054 / p99 1.262 / max 1.671 s (Y 0.064 / 1.031 / 1.208 / 2.400); leads p95 1.236 s (Y 1.185); bury p95 0.383 s (Y 0.384), bbw belief draw p50 7.7 ms; 0 play fallbacks, 0 belief fallbacks (play and bury), 0 lcc abandons of 990 leads, 0 plays ≥ 3 s | `~/shengji-archive/2026-11-04-r50-speed-profile/README.md` |
| cbaC (duel host, descriptive) | the release-50 stack vs Y | decide_play p95 1.084 vs 1.077 s, max 2.429 vs 2.421 s; bury seconds p95 0.415 s, bury-belief draw p95 9.3 ms | `readouts/cbaC/` |
| hb50 (cloud duel host at half budget, descriptive) | the release-50 stack vs Y, both at play 1.5 s / lgfd 1000 ms / bury 1 s | decide_play p95 1.005 / max 1.23 s (Y 1.006 / 1.22 s); 0 budget fallbacks; lcc32 abandoned 15,061 of 64,548 search leads (23%, all `leaf_deadline`), against 0 of 990 leads at the full budget in the R50 speed profile; bury seconds p95 0.407 s | `readouts/hb50/` |
| loo (M5 Ultra duel host, descriptive) | the release-50 stack with lcc32 off vs on | lead p95 0.305 s off vs 0.830 s on; decide_play p95 0.272 vs 0.702 s; mean decision time ratio 0.567 | `readouts/loo/` |

**Not measured: release 50 on Fly** (S79, pending). The speed profile's Fly projection (assuming unthrottled Fly at
×2 a cloud core, uniform across components) puts play p99 at about 2.5 s against the 3 s budget, with about a third
of lcc leads reaching the 2 s greedy-finish cut and abandoning (the designed `leaf_deadline` cut, which plays the
base lead). That projection holds for release 49 alike: release 50's extra cost over release 49 is about +1.4% per
round on a cloud core. Throttled (×5 or more), about 18% of plays would pass the 3 s budget for either release;
s71fly found 14 of 16 timed blocks throttled on Fly, at about 8% of a core (CPU/wall about 0.08).
Release 49's first-room triggers (Release checklist, step 9) apply unchanged.

##### Pre-deploy smoke (release tree, this host)

`smoke_release45_bury.py --rounds 10 --full-round` on the release branch with sha-verified local packages (the three
`serving-packages` assets and JS-M1), Mac mini M4, compiled engine (receipt `smoke50.jsonl`, sha256
`1c93b4c0…`): validator **PASS**; `bot.files` value `f4f4127e`, prior `1fa201b2`, belief `028131a0`, JS-M1
`0d17fd03`; bot class `SingletonChallengerBuryBot`, all nine latency switches on. Bury: 10 of 10 committed once, 64
candidates, 0 fallbacks, all 10 on belief worlds with 0 bury-belief fallbacks (belief draw 3.5–8.6 ms), wall max
0.208 s; 33 value declarations. First-room reader over its 10 room logs: 712 plays, 712 belief-drawn, **0 belief
fallbacks**; exact-eligible 55 leads + 100 follows, **0 abandons, 0 fallbacks**; decision p50 0.026 / p95 0.436 /
max 1.004 s; `lcc` leads p50 0.348 / p95 0.507 / max 1.004 s; other decisions p95 0.087 s; 0 decisions at 3 s;
belief_ms p95 8.9. `lcc` on 178 leads: applied 21, rejected 17, no_challenger 85, no_pool 9, exact 46, abandoned 0.
`sc8` probed 123 leads and applied 50. The smoke writes no `bot_timing` events, so the reader's bury line reads 0
there; the receipt carries the bury counts. These are M4 timings, not Fly's. Re-run on the merged tree before
the deploy (Release checklist, step 3).

##### Watch list

Release 49's rows of the first-room rollback triggers (Release checklist, step 9); the bury's `bury_belief_fallbacks`
(any is a trigger to examine) and bury seconds against the 2 s budget; the `lcc` status mix on Fly; belief fallbacks
and `belief_ms` with B1a; any `pv-search-fallback-v1`, `cwv-bury-fallback-v1` or `pv-declare-serving-fallback-v1`
record; the `/healthz` `activity` counters (step 10).

##### Release note: what a player will notice

- **Different burying and declaring.** cbaC's largest first-divergence cells are the bury and the declaration; the
  bury now reasons over hidden hands drawn by the belief model. The effect on human opponents is not measured.
- **Lead timing as release 49.** The new packages add about 1–2% to the play tails on a cloud core.

### To release 49

Release 49 as served before release 50: Fly v56, image `deployment-01M6AX9WCDG3YMGWZPDE9PSM12`, main `d2a6346a`
(#1194), and later deploys of main that change no served decision. Its packages stay on the volume. Release 49's
served name:

```
pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-lcc32-r9f8f5c05-bury-hybrid-bwv-d12d7acfc860-sc8
```

**Option 1, redeploy the image that served release 49** (no build). Before the release-50 deploy, confirm the image
of the release then live with `fly releases -a shengji --image` (v56 above unless a later deploy of main replaced
it) and write it into the deploy record. Then:

```bash
flyctl deploy --app shengji --ha=false --image registry.fly.io/shengji:<the release-49 image>
```

**Option 2, edit `fly.toml`** (from release 51, first set `SHENGJI_PV_LEAD_CONFIRM` back to `'32'`):

1. Delete the three release-50 lines, `SHENGJI_PV_PRIOR_CKPT`, `SHENGJI_PV_PRIOR_SHA256` and
   `SHENGJI_PV_BURY_BELIEF_WORLDS` (and their comments).
2. Restore the release-49 value and belief pairs:
   ```
   SHENGJI_PV_CKPT = '/data/models/smv3out-491ee4bf.npz'
   SHENGJI_PV_SHA256 = '491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670'
   SHENGJI_PV_BELIEF_CKPT = '/data/models/s58-e6-42444515.npz'
   SHENGJI_PV_BELIEF_SHA256 = '424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e'
   ```
3. Set `SHENGJI_BOT` to the release-49 name kept in the comment above it.
4. Run `fly deploy --ha=false`; `/healthz` must show the release-49 name, `pv_search.sha256` `491ee4bf…` and all nine
   latency switches true, and the step-8 line with the S58 path and sha must print `True compiled 42444515`.

`test_release50_fly_config.py`, `test_release49_fly_config.py` and `test_bury_fly_config.py` check that this env
derives release 49's name and builds `SingletonChallengerBuryBot` on `491ee4bf` with no separate prior, S58 and
`bury_belief_worlds` off. Rolling back also rolls the manifest check back: `server/releases/r49.json` is release
49's env, and `test_release_manifests.py` compares `fly.toml` with the current release's manifest.

#### Release 49 record

**Release 49** (board combo3 arm Y): release 48 plus two lead rules, the singleton challenger (`sc8`) and the
held-out lead confirmation at 32 (`lcc32`). Production from 2026-11-01 until release 50's deploy.

| field | value |
|---|---|
| deployed | 2026-11-01 01:39 EST (06:39Z), at 0 rooms, on Jerry's in-session word (2026-10-31: "Yea ship Y") |
| Fly version | v56 |
| image | `deployment-01M6AX9WCDG3YMGWZPDE9PSM12` |
| source | main `d2a6346ab137c4a57f5caaf5a74b4bcffa0f5123` (#1194; Codex PASS at `1bad9a2d`) |
| evidence | `AI_POLICIES.md` ladder row 18 (combo3y DEV_PASS, confirmed combo3yc; latency s71fly and v107sc8lat) |
| deploy record | [#1075 issuecomment-6554545362](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6554545362); `/healthz` showed the name below and the in-machine check printed `True compiled 42444515` |
| first live room | pending: `/healthz` activity counters observed at 0 rooms created and 0 rounds recorded at 2026-11-01 16:54Z; the first-room reader (Release checklist, step 9) and the room-log write check (step 10) run on the first one |
| comparator | release 49 as served is the comparator of release 50's evidence (Jerry 2026-11-01)[^cmp] |

Served name:

```
pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-lcc32-r9f8f5c05-bury-hybrid-bwv-d12d7acfc860-sc8
```

The registry derives it from the `fly.toml` env: `lcc32` enters the play recipe (its digest `r9f8f5c05` and the bury
suffix `d12d7acfc860` move), and `SHENGJI_PV_SINGLETON_CHALLENGER = '1'` registers that recipe a second time under
the `-sc8` suffix with the challenger bot class. It is byte for byte the arm-Y name combo3y and combo3yc screened.

##### Packages

Unchanged from release 48; nothing to upload.

| package | path on the volume | sha256 | `/healthz` field |
|---|---|---|---|
| play | `/data/models/smv3out-491ee4bf.npz` | `491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670` | `pv_search.sha256` |
| prior | `/data/models/js-m1-0d17fd03.npz` | `0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747` | `prior` |
| belief | `/data/models/s58-e6-42444515.npz` | `424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e` | not reported[^belief] |
| belief (release 46, kept for its rollback) | `/data/models/s17long-e2-763b5e05.npz` | `763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343` | — |

##### `fly.toml` keys

The two lines release 49 adds to release 48's environment (with `SHENGJI_BOT`; every other line byte-identical):

| change | `fly.toml` | name token |
|---|---|---|
| singleton challenger (sc8) | `SHENGJI_PV_SINGLETON_CHALLENGER = '1'` | `-sc8` suffix |
| held-out lead confirmation at 32 | `SHENGJI_PV_LEAD_CONFIRM = '32'` | `lcc32` (the play digest moves) |

Release 48's keys, including its belief pair, `dtrx`, the greedy finish and all nine latency switches, are
unchanged; release 48's record under "Rollback" lists them.

`server/tests/test_release49_fly_config.py` builds the served bot from this env on the pinned packages as the
server does (the registry's import-time registration, then `make_bot(SHENGJI_BOT)`), checks every knob, and plays
one lead through the server path with both rules running; it also builds the release-48 rollback.
`server/tests/test_release48_fly_config.py` and `test_release46_fly_config.py` build releases 48 and 46 from the
rolled-back env. `server/tests/test_bury_fly_config.py` pins the name chain 49 → 48 → 46 → 45 and the deeper
rollbacks.

##### What the two rules do at serving time

- **Singleton challenger (`sc8`).** On a lead where some hand still holds more than 7 cards, the singles the policy
  left off the 8-candidate ballot are priced on the first 8 sampled worlds with heuristic-finished leaves. The best
  one replaces the ballot's last slot only when it beats every admitted candidate on that proxy; the full 64-world
  search still chooses the move. Record fields: `singleton_challenger_applied`, `singleton_probe_margin`,
  `singleton_challenger_added`, `singleton_challenger_removed`.
- **Lead confirmation (`lcc32`).** On a lead with no exact stage, after the base decision is final, the policy's
  next actions up to 32 are priced on 32 of the base worlds; at most 2 that beat the served lead are priced again on
  two fresh 64-world draws, and one replaces the served lead only when its paired margin exceeds one standard
  error. The stage starts only before 40% of the 3 s budget and stops at 80%; a greedy finish cut by its 2 s
  deadline abandons the stage, and any abandon plays the base lead. Record: `lead_confirm_status` (`applied`,
  `rejected`, `no_challenger`, `no_pool`, `skipped_budget`, `abandoned`, `exact`, `override`), `lead_confirm_seconds`
  and, on an abandon, `lead_confirm_abandon_reason` (`leaf_deadline` is the designed cut; anything else is an error).
- Everything else is release 48's: belief worlds on S58, exact endgame at 7 cards, `dtrx`, `lgf lgfx lgfd2000`,
  the value declaration, the wide value-only bury, the latency switches.

##### Evidence

Both reads are paired, seat-swapped head-to-head duels of Y against release 48 (then production), at the served budgets,
3,920 fresh deals each on cloud (r2 rank-mixed round plan). This is a different instrument from the MC-LCB
common-control screens of earlier rows.

| read | seeds | result [95% CI] | validity | splits (descriptive) | pointer |
|---|---|---|---|---|---|
| combo3y (DEV, bar: mean ≥ +0.015 and CI lower > 0) | 245530910.. | **+0.0270 [+0.0135, +0.0408]**, DEV_PASS | VALID; 0 play, belief, bury fallbacks of 257,496 decisions per side; 51 lcc abandons, all the designed deadline cut | first round +0.0354, fixed banker +0.0215; rank 2 +0.0383, rank ≠ 2 +0.0180 | [#1075 issuecomment-6475680068](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6475680068) |
| combo3yc (fresh-seed confirmation, bar: mean ≥ +0.010 and CI lower > 0) | 245550910.. | **+0.0306 [+0.0167, +0.0441]**, CONFIRMED, judged alone | VALID; 0 play, belief, bury, declare fallbacks; 36 lcc abandons, all the designed cut | first round +0.0261, fixed banker +0.0336; rank 2 +0.0266, rank ≠ 2 +0.0338 | [#1075 issuecomment-6479431994](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6479431994) |

Codex's saved-result audit of combo3yc ([issuecomment-6480355443](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6480355443))
reproduced the verdict from the archived result (sha256 `487e8afc…`). It also reports that the increment over
`lcc32` alone (s71duel, independent runs) is +0.0102 [−0.0086, +0.0291]: sc8's own contribution is unresolved.
Mechanics in combo3yc: `lcc` started on 68.7% of search leads and replaced the served lead on 13.3%; a singleton
entered the ballot on 26.9% of search leads and was played on 9.7%. On the duel host, leads cost ×2.6 at p50 and
×2.9 at p95 (lead p95 1.24 s vs 0.43 s); follows were unchanged. Archive:
`~/shengji-archive/2026-09-13/readouts/{combo3y,combo3yc}/`.

##### Latency

| read | what | result | pointer |
|---|---|---|---|
| v107sc8lat | sc8 alone vs release 48, one pinned perf core, one room, ABBA 4 × 100 full rounds | QUALIFIED, bars B1–B9 PASS: play p50 0.113 / p95 0.700 / p99 0.892 / max 2.41 s (release 48 0.111 / 0.669 / 0.861 / 2.41) over 13,032 plays; 0 budget fallbacks, 0 plays ≥ 3 s, 0 belief fallbacks, exact abandons 3 / 2871 | `~/shengji-archive/2026-09-13/readouts/v107sc8lat/` |
| s71fly | lcc32 alone vs release 48 (then production) in the production machine at 0 rooms, `/tmp` only, 40-turn blocks | Unthrottled blocks (lcc32 2, release 48 1): play p95 2.01 vs 0.75 s; leads p50 1.97 / p95 2.01 / max 2.02 s over 20 (release 48 0.65 / 0.96 / 0.96 s over 10); 7 of the 20 stages cut by the 2 s finish deadline. After about 3 min of sustained play the shared CPU throttles to ~8% of a core: over all 8 pairs lead mean 2.63 vs 2.60 s (ratio 1.01), `lcc` `skipped_budget` on 26 of 72 leads and applied on 4 (0 of 32 early leads), and release 48 itself expires its budget on 20 of 72 leads | [#1075 issuecomment-6469399580](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6469399580); `readouts/s71fly/` |

**Not measured:** sc8 and lcc32 together on Fly. s71fly timed lcc32 without sc8 and v107sc8lat timed sc8 on perf.
On the duel host Y's leads cost what lcc32's alone did within 2% (lead ratio to release 48 at p50 / p95: Y 2.57 /
2.89, s71duel 2.54 / 2.87), and sc8's probe checks the play budget between batches, but the Fly cost of the pair
is an inference. Two consequences follow from s71fly. On Fly, `lcc` is cut by
its deadline far more often than on the duel host (7 of 20 unthrottled leads vs 0.1%), so the served gain is
bounded above by the duel reads. Leads also take about 2 s on an unthrottled machine, which is why release 49 has
its own latency triggers (Release checklist, step 9).

##### Pre-deploy smoke (merged tree, this host)

`smoke_release45_bury.py --rounds 10 --full-round` on the release tree with sha-verified local packages, Mac mini
M4, compiled engine (receipt `smoke49.jsonl`, sha256 `e9b87235…`): validator **PASS**; `bot.files` play
`491ee4bf`, prior `0d17fd03`, S58 `42444515`; bot class `SingletonChallengerBuryBot`, all nine latency switches on.
First-room reader over its 10 room logs: 660 plays, 660 belief-drawn, **0 belief fallbacks**; exact-eligible 45
leads + 91 follows, **0 abandons, 0 fallbacks**; decision p50 0.043 / p95 0.610 / max 0.876 s; leads p50 0.485 /
p95 0.730 / max 0.876 s; other decisions p95 0.127 s; 0 decisions at 3 s; belief_ms p95 16. `lcc` on 165 leads:
applied 20, rejected 19, no_challenger 81, no_pool 8, exact 37, abandoned 0. `sc8` probed 120 leads and applied
39. Bury: 10 of 10 committed once, 64 candidates, max 0.33 s; 34 value declarations. These are M4 timings, not Fly's.

##### Watch list

The release-49 rows of the first-room rollback triggers (Release checklist, step 9); the `lcc` status mix on Fly
(how many leads are `applied` against `abandoned`/`skipped_budget`); `sc8` applied counts; lead p95 against
release 48's first-room numbers; any `pv-search-fallback-v1`, `cwv-bury-fallback-v1` or
`pv-declare-serving-fallback-v1` record; the `/healthz` `activity` counters (step 10). Release 48's watch items
(belief_ms, failed throws per round, `leaf_greedy_deadline_fired`) stay.

##### Release note: what a player noticed

- **Slower early leads.** On an unthrottled machine the bot's leads take about 1–2 s where release 48 took about
  0.6 s (the 0.7 s pacing floor still applies to every turn). Follows are unchanged.
- **More single-card leads** early in a hand (sc8 played a singleton the ballot had left out on about 10% of
  search leads in the duels). Their effect on human opponents is not measured.


### To release 48

Release 48 as served before release 49 (from release 50, first apply the release-49 steps above): the release-48 recipe deployed 2026-10-24 (Fly v47, image
`deployment-01M5Q4ACYEJ901SQB3BNMPC55A`, main `f14ace15`), plus the six native latency switches deployed
2026-10-27 from main `329ae08f` (#1165; decisions identical, [#1075 issuecomment-6432593573](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6432593573)),
and later deploys of main that change no served decision (main `4e75266a` on 2026-10-28, before s71fly). Same
packages as release 49. Release 48's served name:

```
pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-rc252e656-bury-hybrid-bwv-cd6dd3d2b02a
```

**Option 1, redeploy the image that served release 48** (no build): Fly v55, image
`deployment-01M616V35HQ3H509RPA3C8PS31` (deployed 2026-10-28 12:14Z; release 48 with the native latency switches),
the release before v56.

```bash
flyctl deploy --app shengji --ha=false --image registry.fly.io/shengji:deployment-01M616V35HQ3H509RPA3C8PS31
```

**Option 2, edit `fly.toml`:**

1. Delete the two release-49 lines, `SHENGJI_PV_SINGLETON_CHALLENGER` and `SHENGJI_PV_LEAD_CONFIRM` (and their
   comment).
2. Set `SHENGJI_BOT` to the release-48 name kept in the comment above it.
3. Run `fly deploy --ha=false`; `/healthz` must show the release-48 name and all nine latency switches true.

`test_release49_fly_config.py`, `test_release48_fly_config.py` and `test_bury_fly_config.py` check that this env
derives release 48's name and builds the plain `PVSearchBuryBot` with `lead_confirm` 0.

#### Release 48 record

**Release 48** (release 46 with the S58 belief package, `dtrx`, the guarded greedy-finished value leaf
`lgf lgfx lgfd2000`, and three latency switches).

| field | value |
|---|---|
| deployed | 2026-10-24 10:18 ET (14:18Z), at 0 rooms, on Jerry's in-session word |
| Fly version | v47 |
| image | `deployment-01M5Q4ACYEJ901SQB3BNMPC55A` |
| source | main `f14ace152b5491be53b5a1088728f47f6755f393` (#1147; Codex PASS at `0c1e9965`) |
| evidence | `AI_POLICIES.md` ladder row 17 (r48cloud, confirmed r48confirm, latency v105lat QUALIFIED) |
| deploy record | [#1075 issuecomment-6385303349](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6385303349) |
| comparator | screens compared against release 48 as served from 2026-10-24 until 2026-11-01[^cmp] |

Served name:

```
pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-rc252e656-bury-hybrid-bwv-cd6dd3d2b02a
```

#### Packages

| package | path on the volume | sha256 | `/healthz` field |
|---|---|---|---|
| play | `/data/models/smv3out-491ee4bf.npz` | `491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670` | `pv_search.sha256` |
| prior | `/data/models/js-m1-0d17fd03.npz` | `0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747` | `prior` |
| belief (new in 48) | `/data/models/s58-e6-42444515.npz` | `424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e` | not reported[^belief] |
| belief (release 46, kept for the rollback) | `/data/models/s17long-e2-763b5e05.npz` | `763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343` | — |

S58 (d192, 4 + 4 layers) is served at its stored temperature 1.0129. Both belief packages are also assets of the
`serving-packages` GitHub release.

#### `fly.toml` keys

The lines release 48 added to or changed in release 46's environment (every other line byte-identical):

| change | `fly.toml` | name token |
|---|---|---|
| belief package: S58 replaces S17 e2 | `SHENGJI_PV_BELIEF_CKPT = '/data/models/s58-e6-42444515.npz'`, `SHENGJI_PV_BELIEF_SHA256 = '424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e'` | none (the play digest moves) |
| dtrx (#1120) | `SHENGJI_PV_DOOMED_THROW_RESELECT_EXACT_GUARD = '1'` | `dtrx` |
| greedy-finished value leaf (S33) | `SHENGJI_PV_LEAF_GREEDY_FINISH = '1'` | `lgf` |
| its exact-stage yield | `SHENGJI_PV_LEAF_GREEDY_FINISH_EXACT_SKIP = '1'` | `lgfx` |
| its deadline | `SHENGJI_PV_LEAF_GREEDY_DEADLINE = '2'` | `lgfd2000` |
| latency switches (no name, payload or digest) | `SHENGJI_PV_ENCODE_PREFIX_CACHE = '1'`, `SHENGJI_PV_LEAF_GREEDY_STREAM = '1'`, `SHENGJI_PV_ENCODE_BATCH_FAST = '1'` | none |

Inherited from release 46, unchanged except the belief package above:

| group | keys | name token |
|---|---|---|
| play worlds | `SHENGJI_PV_WORLD_HISTORY_LEGAL = '1'`, `SHENGJI_PV_WORLD_HISTORY_DRAW = '1'`, `SHENGJI_PV_BELIEF_WORLDS = '1'` | `whl whd bw` |
| exact endgame | `SHENGJI_PV_EXACT_LEAD_ENDGAME = '1'`, `SHENGJI_PV_EXACT_DEEP_CARDS = '7'` | `ele ed7` |
| exact follow | `SHENGJI_PV_EXACT_FOLLOW = '1'`, `SHENGJI_PV_EXACT_FOLLOW_SOLVER = 'compact-level'`, `SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS = '7'`, `SHENGJI_PV_EXACT_FOLLOW_MAX_NODES = '50000000'` | `xf7 xfcompactlevel` |
| declaration | `SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST = '1'` | `vdef` |

Inherited from release 45 and earlier, unchanged:

| what | keys |
|---|---|
| search rules, each `'1'` | `SHENGJI_PV_ADMISSION_DIVERSITY`, `SHENGJI_PV_REFUSAL_CONSTRAINTS`, `SHENGJI_PV_TIEBREAK_POINTS`, `SHENGJI_PV_LEAD_ANCHOR` (r38), `SHENGJI_PV_DOOMED_THROW_RESELECT` (r43), `SHENGJI_PV_VALUE_DECLARE` (r44) |
| search width and budget | `SHENGJI_PV_WORLDS = '64'`, `SHENGJI_PV_CANDIDATES = '8'`, `SHENGJI_PV_CAP = '4000'`, `SHENGJI_PV_SERVING_BUDGET_SECONDS = '3'` |
| bury | `SHENGJI_PV_BURY_ARM = 'hybrid'`, `SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS = '2'`, `SHENGJI_PV_BURY_WIDE_VALUE = '1'`, `SHENGJI_PV_BURY_WIDE_K = '64'` (r45) |
| packages | `SHENGJI_PV_CKPT`, `SHENGJI_PV_SHA256`; prior `SHENGJI_CWV_PRIOR_CKPT`, `_SHA256`, `_THRESHOLD = '1000'`, `_TOP = '256'` |
| engine and logs | `SHENGJI_FAST = '1'` (compiled engine and solver), `SHENGJI_LOG_DIR = '/data/logs'` |

`server/tests/test_release48_fly_config.py` builds the served bot from this env (production's with release 49's
two lines removed) on the pinned packages, with the env
exported into the process as Fly does, and plays one turn through the server path; it also builds the release-46
rollback on S17's package. `server/tests/test_bury_fly_config.py` pins the name chain 48 → 46 → 45 and the deeper
rollbacks.

#### What the recipe does at serving time

- **Belief worlds.** Each sampled world is history-legal and its hidden hands come from the belief package (S58
  since release 48). A belief error, including a preparation over 0.25 s, falls back to the history-legal draw for
  that decision and is recorded (`belief_fallback`, `belief_error`).
- **Belief log** (on by default). Each sampled decision record gains `belief_seed` and a marginal snapshot;
  `server/scripts/belief_debug.py` replays it. No decision depends on the log.
- **Exact endgame.** At ≤ 7 cards a LEAD is re-scored by exact minimax per world and a FOLLOW is re-ranked on the
  compiled solver, inside the 3 s budget. A stage that does not finish plays the baseline and says so
  (`exact_lead_status` `abandoned`/`skipped_budget`, `exact_follow_abandoned`).
- **dtrx.** The doomed-throw re-select never overrides a complete exact lead stage.
- **Greedy-finished leaf.** Before the value pass, each candidate's trick is finished with greedy replies (`lgf`).
  On decisions an exact stage is eligible for, the plain leaf is used instead (`lgfx`). Past 2 s into a decision
  the finish stops and every remaining leaf is the plain one (`lgfd2000`; record `leaf_greedy_deadline_fired`).
- **Latency switches.** Prefix-cached and batched encoding and a streamed greedy finish; on completed decisions
  the cards played are the switch-off ones. They are read from the process environment where the bot is built, so
  `/healthz` reports them as `pv_search.latency_switches`.
- **Declaration.** In the first round the value declaration is consulted at every declare chance (record
  `gate`, `every_first`).
- **Dependencies.** Serving imports only NumPy and the standard library. The solver `ai/_endgame_fast` is built
  in the Dockerfile's `fastbuild` stage[^fast].

#### Evidence

Each read compares the candidate with release 46, production when it ran (paired common-control, ten 520-cluster
windows, r2 rank-mixed round plan: 4 first-round windows at rank 2 and 6 fixed-banker windows at ranks 2..A).

| read | host, seeds | result [95% CI] | validity | splits (descriptive) | pointer |
|---|---|---|---|---|---|
| r48cloud (guarded R48 screen) | cloud, 231060910 + 100000·i | **+0.0765 [+0.0571, +0.0958]**, POSITIVE; every window positive | VALID; 0 play and 0 belief fallbacks on both arms | rank 2 +0.0884, rank ≠ 2 +0.0661 | [#1075 issuecomment-6383298163](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6383298163) |
| r48confirm (fresh-seed confirmation) | perf, 232060910 + 100000·i | **+0.0843 [+0.0575, +0.1111]**, POSITIVE, judged alone | VALID; 0 play and 0 belief fallbacks | rank 2 +0.0909, rank ≠ 2 +0.0792 | [#1075 issuecomment-6384251320](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6384251320) |
| v105lat (latency and peak memory, the exact recipe) | one pinned cloud core, one room, ABBA 4 × 100 full rounds | QUALIFIED, bars B1–B9 PASS | 0 budget fallbacks, 0 plays ≥ 3 s, exact abandons 2 / 2920 (release 46 1 / 2837), 0 belief fallbacks over 12,692 | see below | [#1075 issuecomment-6384912469](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6384912469) |

v105lat, candidate vs release 46 on the same seeds: play wall p50 0.098 / p95 0.566 / p99 0.746 / max 2.408 s over
12,692 plays (release 46 0.096 / 0.155 / 0.319 / 2.407 s over 12,868); on plays where the finish ran, p95 0.598 s,
p99 0.835 s; the 2 s deadline fired on 14 of 12,692 decisions; belief_ms p95 25.8 (release 46 20.7); peak RSS
+26,792 kB. The Fly projection in that read is descriptive, not a measurement; the first-room read is the Fly check.

The unguarded S58 combo (without the deadline and the latency switches) read INVALID on play budget fallbacks
([readout](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6376318200)); the deadline and switches are
that read's repair. The screens measure the combined recipe: they do not attribute the gain among S58, dtrx and the
greedy finish. Archive: `~/shengji-archive/2026-09-13/readouts/{r48cloud,r48confirm,v105lat}/`.

#### Post-deploy checks as read

| check | result |
|---|---|
| `/healthz` | name above, `fast: true`, `pv_search.sha256` `491ee4bf…`, `prior` `0d17fd03…`, budget 3, bury `hybrid` at 2, `latency_switches` `{"encode_prefix_cache": true, "single_candidate_fast": false, "leaf_greedy_stream": true, "encode_batch_fast": true}` |
| in-machine compiled/belief line | printed `True compiled 42444515` |
| first live room **UBWB** | PARTIAL: the room stopped after 3 tricks (12 plays); read once |
| UBWB fallbacks | 0 `pv-search-fallback-v1`, 0 belief fallbacks |
| UBWB decision seconds | p95 1.35 / max 1.47; belief_ms p95 39 |
| verdict | no rollback trigger on the partial room; a complete first room is still to be read |

Preconditions as met: Codex PASS at `0c1e9965`, all ten CI checks green, squash-merged as `f14ace15` (the only commit
on main past #1147's base is #1148, web assets, so `server/` is the screened tree); S58 on the volume with in-machine
sha256 `424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e`, S17 kept; merged-tree full-round smoke
(10 rounds, server path) validator PASS with `bot.files` S58 `42444515`, play `491ee4bf`, prior `0d17fd03` and the
latency switches as set: 692 plays, 50 + 96 exact-eligible decisions, 0 abandons, 0 fallbacks, decision p95 0.256 s,
max 1.62 s, belief_ms p95 13 ms, and 1 belief fallback (play 1 of the first room, a cold `BeliefNumpyError`
preparation at 823 ms, the documented boot case); r48cloud and r48confirm POSITIVE; v105lat QUALIFIED; Jerry's word
in session.

**Watch list:** the first-room rollback triggers (Release checklist, step 9) on the first complete room; its
whole-decision p95 on Fly's shared CPU (UBWB's 1.35 s over 12 plays is near the 1.5 s trigger), belief_ms p95, failed
throws per round and the `leaf_greedy_deadline_fired` count; any `cwv-bury-fallback-v1` or
`pv-declare-serving-fallback-v1` record; the `/healthz` `activity` counters (step 10).

#### Release note: what a player will notice

- **More failed throws.** dtrx keeps an exact-stage throw the engine will refuse unless another lead's exact
  mean is at least as high, so the bot shows more public failed-throw notices than release 46 (R47's v97dtrx
  measured about a third more). Its effect on human opponents is not measured.
- **Belief package.** S58 is trained on bot self-play plus a small human-log stream. Watch the first human
  room's belief and history fallback counts.

### To release 46

Release 46: Fly v46, image `deployment-01M530R14ARM0669QNJBW2RGTG`, main `ab6fd1b2`, digest
`sha256:0d2d92e5d85948309741a8486f739a751537b13d36c622a266fc33b4809c2d4a`. Same play package and prior; it reads
`/data/models/s17long-e2-763b5e05.npz`, which stays on the volume. Release 46's served name:

```
pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-vd-vdef-ed7-xf7-xfcompactlevel-r73993d62-bury-hybrid-bwv-cf77a93949b0
```

**Option 1, redeploy the release-46 image** (no build):

```bash
flyctl deploy --app shengji --ha=false --image registry.fly.io/shengji:deployment-01M530R14ARM0669QNJBW2RGTG
```

**Option 2, edit `fly.toml`:**

1. From release 48's env (after the release-48 steps above), delete the thirteen lines release 48 and the
   native-switch deploy added: `SHENGJI_PV_DOOMED_THROW_RESELECT_EXACT_GUARD`, `SHENGJI_PV_LEAF_GREEDY_FINISH`,
   `SHENGJI_PV_LEAF_GREEDY_FINISH_EXACT_SKIP`, `SHENGJI_PV_LEAF_GREEDY_DEADLINE` and the nine latency switches
   (`SHENGJI_PV_ENCODE_PREFIX_CACHE`, `SHENGJI_PV_LEAF_GREEDY_STREAM`, `SHENGJI_PV_ENCODE_BATCH_FAST` and the six
   native ones).
2. Restore `SHENGJI_PV_BELIEF_CKPT = '/data/models/s17long-e2-763b5e05.npz'` and
   `SHENGJI_PV_BELIEF_SHA256 = '763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343'`.
3. Set `SHENGJI_BOT` to the release-46 name kept in the comment above it.
4. Run `fly deploy --ha=false`; `/healthz` must show the release-46 name and every latency switch false.

`test_release48_fly_config.py` and `test_bury_fly_config.py` check that this env derives release 46's name.

### To release 45

Release 45: Fly v45, image `deployment-01M4T9AVEVK51WP2GG8J34NRC9`, main `1ca97051`, digest
`sha256:6194eb27e62efab5f0e9218f453e730e7733fcacdeaf4996eef249718389dbcb`. Same play package and prior; it
does not read a belief package, so both may stay on the volume.

**Option 1, redeploy the release-45 image** (no build):

```bash
flyctl deploy --app shengji --ha=false --image registry.fly.io/shengji:deployment-01M4T9AVEVK51WP2GG8J34NRC9
```

**Option 2, edit `fly.toml`** (from release 46's env, after the release-46 steps above):

1. Delete the twelve release-46 lines (`SHENGJI_PV_WORLD_HISTORY_LEGAL`, `SHENGJI_PV_WORLD_HISTORY_DRAW`,
   `SHENGJI_PV_BELIEF_WORLDS`, `SHENGJI_PV_BELIEF_CKPT`, `SHENGJI_PV_BELIEF_SHA256`, the six `SHENGJI_PV_EXACT_*`,
   `SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST`).
2. Set `SHENGJI_BOT` to the release-45 name, kept as the comment directly above it:
   ```
   SHENGJI_BOT = 'pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv-7a73e8fbf1a8'
   ```
   Release 45's own additions stay: `SHENGJI_PV_BURY_WIDE_VALUE = '1'` and `SHENGJI_PV_BURY_WIDE_K = '64'`.
3. Run `fly deploy --ha=false`, then check `/healthz` reports the release-45 name.

### Deeper rollbacks

Each step removes one more set of flag lines and restores the name kept as a `fly.toml` comment, or redeploys
the image with the same `flyctl deploy --app shengji --ha=false --image …` form. No package moves until release 36.

| to release | `fly.toml` change from the release above it | image |
|---:|---|---|
| 44 | delete the two `SHENGJI_PV_BURY_WIDE_*` lines; name `…bury-hybrid-6c1fb26b80e6` | `deployment-01M4PC7724HSXC27PCEEREZWY4` (v44) |
| 43 | also delete `SHENGJI_PV_VALUE_DECLARE` | `deployment-01M4H37RYNM42YHH6ZPEC6GKCK` (v43) |
| 42 | replace the re-select line with `SHENGJI_PV_DOOMED_THROW_SWAP = '1'` | `deployment-01M49QGK2ZP18P143S8BXVW28X` (v42) |
| 38 | delete the doomed-throw line | `deployment-01M40ZWSAHNX4782CGKJ615YF7` |
| 36 | also delete the four release-38 rule lines | `deployment-01M3SG9NVC1AC3PNPEH5Y34N0D` |
| 29/30 | restore the three release-30 lines (`SHENGJI_BOT`, `SHENGJI_PV_CKPT`, `SHENGJI_PV_SHA256`) | `deployment-01M34KWRW4XWJWC6DCCYENFXTF` (r30) |
| 28 | `SHENGJI_BOT` back to the release-28 name (its keys stay in `fly.toml`) | `deployment-01M2M90VYR34R7CWKTTEA4C57V` |

The release-44 image command, verbatim:
`flyctl deploy --app shengji --ha=false --image registry.fly.io/shengji:deployment-01M4PC7724HSXC27PCEEREZWY4`.

**Prior-only rollback:** remove the four `SHENGJI_CWV_PRIOR_*` settings and restore the prior-less name;
`/healthz` must then show `"prior": null`.

## Release checklist

The gate every release passes (called "serving qualification" in `AI_POLICIES.md`); it held for releases 29–38
and 42–48. Release 49 completed the pre-deploy and deploy gates; its first-live-room checks (steps 9 and 10) are pending.
Commands below are release 50's; substitute the new release's package names and receipt. Release 51 changes one
`fly.toml` value and no package: step 2's upload is skipped (its in-machine sha check still holds), its smoke
receipt is `smoke51.jsonl`, and its records carry no `lcc` statuses. Release 52 adds five `fly.toml` lines and no
package: step 2's upload is skipped, its smoke receipt is `smoke52.jsonl`, step 1 adds
`test_release52_fly_config.py`, and in step 3 an exact-lead abandon with reason `soft_budget` at the 1.6 s cap is
the designed stop (it plays the searched lead), not a failure; any other abandon reason fails the smoke.

**Before the deploy**

1. **Review and CI.** A non-author PASS on the release PR at its exact head, and all CI checks green. The
   package-gate step fetches the pinned packages from the `serving-packages` release, sha256-verifies them, and
   runs `server/tests/test_release51_fly_config.py` and `test_release50_fly_config.py` (`test_release49_fly_config.py`, `test_release48_fly_config.py`
   and `test_release46_fly_config.py` for the rollbacks), which builds the served bot from the `fly.toml` env through
   the server path (name, every knob, the value, prior and belief packages, compiled solver, latency switches, one
   play and one bury with no fallback), and the release manifest's wiring witness (`test_release_manifests.py`).
   `server/tests/test_bury_fly_config.py` pins the served name.
2. **Package upload, before the `fly.toml` switch.** The policy registers at server import and refuses a missing
   or mismatched package, so a deploy without it does not boot the served bot. The running machine does not read
   the new file. Release 50 uploads three packages, each an asset of the `serving-packages` release:

   | file | sha256 |
   |---|---|
   | `g3a-e04-f4f4127e.npz` | `f4f4127ec0c8821b4aa07f7d651a4258c696f97a874707da2c78ad26c0c9b9fd` |
   | `p0-ft1-1fa201b2.npz` | `1fa201b288e78b3072979f55030aae44711ee214b50a14e155d0bbe11b6bb1bf` |
   | `b1a-028131a0.npz` | `028131a03de0c69b5164cdd0f65369950340f58fe226f75d6d877aeda2ca8fc8` |

   1. Verify each local copy with `shasum -a 256 g3a-e04-f4f4127e.npz p0-ft1-1fa201b2.npz b1a-028131a0.npz` against
      the table (or fetch them from the release assets of the same names, e.g.
      `gh release download serving-packages -R jerryyyu/shengji -p 'g3a-e04-f4f4127e.npz' -p 'p0-ft1-1fa201b2.npz' -p 'b1a-028131a0.npz'`).
   2. Upload: `fly ssh sftp shell -a shengji`, then
      `put <local>/g3a-e04-f4f4127e.npz /data/models/g3a-e04-f4f4127e.npz`,
      `put <local>/p0-ft1-1fa201b2.npz /data/models/p0-ft1-1fa201b2.npz` and
      `put <local>/b1a-028131a0.npz /data/models/b1a-028131a0.npz`.
   3. Verify in the machine:
      `fly ssh console -a shengji -C "sha256sum /data/models/g3a-e04-f4f4127e.npz /data/models/p0-ft1-1fa201b2.npz /data/models/b1a-028131a0.npz"`
      must print the three hashes of the table.
   Keep the previous release's packages on the volume (`smv3out-491ee4bf.npz`, `s58-e6-42444515.npz`); its rollback
   reads them.
3. **Merged-tree full-round smoke**, against the sha-verified packages, from `server/`:
   ```
   SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python scripts/smoke_release45_bury.py --fly-toml ../fly.toml --map /data/models/g3a-e04-f4f4127e.npz=<local> --map /data/models/p0-ft1-1fa201b2.npz=<local> --map /data/models/b1a-028131a0.npz=<local> --map /data/models/js-m1-0d17fd03.npz=<local> --rounds 10 --full-round --receipt smoke50.jsonl
   ```
   Pass: validator PASS; the receipt's `bot.files` lists each package at its sha; the first-room reader (step 9)
   over `smoke50.jsonl.logs/*.jsonl` shows belief fallbacks 0, exact-eligible decisions > 0, abandons 0,
   fallbacks 0, with p95 and max recorded; `lcc` statuses with `applied` > 0 and `sc8` applied > 0 (both rules
   ran; release 51: `sc8` applied > 0 and no `lcc` status); for release 50 also every bury on belief worlds with `bury_belief_fallbacks` 0. The smoke must take the server path: release 25 passed the
   decision-identity gate yet stalled every live bot turn[^smoke].
4. **Evidence.** For a strength change, the served-bot screen against the current production release, read out
   (the ladder table in `AI_POLICIES.md`), plus any confirmation and latency packet the change requires.
5. **Jerry's word, in session.**

**Deploy**

6. From a clean worktree at the merge commit, when the room count is 0 (or on Jerry's word to drop idle rooms):
   `fly deploy --ha=false`. Release 52 deploys from the release PR's reviewed head instead: its base is release
   51's `1490b72b`, so main's merge commit would also carry main's later, unscreened bot-path commits (Current
   production, Source).

**After the deploy**

7. **`/healthz`.** `bot` is the new served name, `fast: true`, `pv_search.sha256` `f4f4127e…`, `prior`
   `0d17fd03…` (the JS-M1 rollback key; the card-play prior shows in the name), `budget_seconds "3"`, `bury_arm hybrid`, `bury_budget_seconds "2"`, and `latency_switches` as
   the release's `fly.toml` sets them. `/healthz` does not report the belief package; the bot registering at all
   shows its sha matched.
8. **In-machine compiled/belief check** (read-only, same image and interpreter as the server):
   ```
   fly ssh console -a shengji -C "sh -c 'cd /app/server && SHENGJI_FAST=1 .venv/bin/python -c \"import sys; from shengji.ai.endgame_compact import HAVE_FAST, default_backend; from shengji.ai.belief_numpy import load_belief_numpy; m = load_belief_numpy(sys.argv[1], sys.argv[2]); print(HAVE_FAST, default_backend(), m.package_sha256[:8])\" /data/models/b1a-028131a0.npz 028131a03de0c69b5164cdd0f65369950340f58fe226f75d6d877aeda2ca8fc8'"
   ```
   Must print `True compiled 028131a0`. `False python` means `_endgame_fast` did not ship or does not import:
   roll back (the latency gate did not qualify the pure twin).
9. **First-room reader.** Fetch the log cache with `server/scripts/fetch_fly_logs.sh`, then read
   `logs/<CODE>.jsonl` once (read-only), over its `play` events that carry a `decision`:
   ```
   python3 - logs/<CODE>.jsonl <<'EOF'
   import collections, json, sys
   rows = [json.loads(l) for p in sys.argv[1:] for l in open(p) if l.strip()]
   d = [r["decision"] for r in rows if r.get("e") == "play" and r.get("decision")]
   bw = [x for x in d if "belief_fallback" in x]
   bfb = [x for x in bw if x.get("belief_fallback_any", 0) or x["belief_fallback"]]
   leads = [x for x in d if x.get("exact_lead_status", "ineligible") != "ineligible"]
   follows = [x for x in d if x.get("exact_follow_attempted")]
   ab = [x for x in leads if x["exact_lead_status"] in ("abandoned", "skipped_budget")] + \
        [x for x in follows if x.get("exact_follow_abandoned")]
   fb = [x for x in d if x.get("schema") == "pv-search-fallback-v1" or not x.get("work_complete", True)]
   q = lambda xs, p: sorted(xs)[min(len(xs) - 1, int(round(p * (len(xs) - 1))))] if xs else None
   secs = [x["seconds"] for x in d if "seconds" in x]
   endg = [x["seconds"] for x in leads + follows if "seconds" in x]
   bms = [x["belief_ms"] for x in bw if "belief_ms" in x]
   print(f"plays {len(d)} belief-drawn {len(bw)} belief fallbacks {len(bfb)} {sorted({x['belief_error'] for x in bfb if x.get('belief_error')})}")
   coverage = sum("belief_fallback_any" in x for x in bw)
   print(f"belief all-draw coverage {coverage}/{len(bw)}; legacy base-only {len(bw) - coverage}")
   print(f"exact-eligible leads {len(leads)} follows {len(follows)} abandons {len(ab)} fallbacks {len(fb)}")
   print(f"decision s all p50 {q(secs,.5)} p95 {q(secs,.95)} max {max(secs) if secs else None}; endgame p50 {q(endg,.5)} p95 {q(endg,.95)} max {max(endg) if endg else None}; belief_ms p50 {q(bms,.5)} p95 {q(bms,.95)}")
   # release 49: the lead confirmation (lcc32) and the singleton challenger (sc8)
   lcc = [x for x in d if "lead_confirm_status" in x]
   st = collections.Counter(x["lead_confirm_status"] for x in lcc)
   why = collections.Counter(x.get("lead_confirm_abandon_reason") for x in lcc if x["lead_confirm_status"] == "abandoned")
   sc = [x for x in d if "singleton_challenger_applied" in x]
   lead_s = [x["seconds"] for x in lcc if "seconds" in x]
   rest_s = [x["seconds"] for x in d if "lead_confirm_status" not in x and "seconds" in x]
   print(f"lcc leads {len(lcc)} {dict(st)} abandon reasons {dict(why)}; sc8 probed {sum('singleton_probe_margin' in x for x in sc)} applied {sum(bool(x['singleton_challenger_applied']) for x in sc)}")
   print(f"lead s p50 {q(lead_s,.5)} p95 {q(lead_s,.95)} max {max(lead_s) if lead_s else None}; other s p50 {q(rest_s,.5)} p95 {q(rest_s,.95)} max {max(rest_s) if rest_s else None}; at >= 3 s {sum(s >= 3 for s in secs)}")
   # release 50: the bury's belief worlds (bbw), from the bury bot_timing events
   bt = [r for r in rows if r.get("e") == "bot_timing" and r.get("phase") == "bury"]
   print(f"buries {len(bt)} bbw {sum('bury_belief_fallbacks' in r for r in bt)} bury-belief fallbacks {sum(r.get('bury_belief_fallbacks') or 0 for r in bt)} bury fallbacks {sum(r.get('bury_search_status') == 'fallback' for r in bt)}")
   EOF
   ```
   Belief fallbacks count decisions with any failed draw, including lead-confirmation and adaptive draws,
   once per decision. Legacy records without `belief_fallback_any` expose only the base draw; zero
   fallbacks in those records cannot establish that later draws succeeded.
   Record the lines under "Current production" with the room code. Server-side wall per decision is in the
   `bot_timing` events with `phase == "play"` (`compute_seconds`; `pacing_seconds` is the 0.7 s floor, not
   search); `model_search` events give queue/run stages; `declare_decision` records show `gate`.

   | rollback trigger | threshold |
   |---|---|
   | budget fallback | any `pv-search-fallback-v1` record |
   | belief fallbacks | above 1% of belief-drawn decisions |
   | exact abandons | above 2% of eligible decisions |
   | decision p95, other than `lcc` leads | above 1.5 s (release 48 and earlier: every decision) |
   | decision p95, `lcc` leads (releases 49–50) | above 2.5 s |
   | `lcc` abandons with a reason other than `leaf_deadline` (releases 49–50) | any (examine each) |
| any `lead_confirm_status` record (release 51) | any (the stage is off; examine) |
   | bury-belief fallbacks (release 50) | any (examine each; the bury then used the split sampler's worlds) |
   | decisions at the 3 s budget | two or more in the first room (examine any one) |
   | bury budget fallbacks | `cwv-bury-fallback-v1` above a few percent |

   Release 49 splits the old whole-decision p95 trigger (above 1.5 s) because `lcc32` spends up to its 2 s
   finish deadline on early leads by design: in the production machine, unthrottled, lcc32's leads ran p50 1.97 /
   p95 2.01 / max 2.02 s and every decision p95 2.01 s, against release 48's 0.75 s (s71fly), so the old trigger
   would fire on a healthy room. Follows are unchanged by release 49 (duel-host ratio 0.97–1.00), so the 1.5 s
   threshold stays for them. 2.5 s for `lcc` leads is the measured 2.02 s maximum plus 0.5 s, below the 3 s
   budget; the stage itself stops at 80% of it (2.4 s) and, past 2 s, any greedy-finished leaf it needs cuts the
   stage. A `leaf_deadline` abandon is that designed cut and plays the base lead; any other reason is a defect. On a
   throttled machine both release 48 and release 49 run near the 3 s budget (s71fly), so the budget-fallback and
   3 s rows, unchanged, are the throttle's triggers for both.

   One belief fallback on the first decision after a boot (a cold preparation over 0.25 s) is recorded, not a
   trigger by itself.
10. **Room-log write check.** The first real game must create `/data/logs/<CODE>.jsonl` at its `round_start`
    (read-only: `fly ssh console -a shengji -C "ls -lt /data/logs" | head -3`) and move the `/healthz` `activity`
    counters: `rooms_created`, `games_started`, `rounds_recorded` and `records_written` all at least 1,
    `record_write_failures` 0, `last_record_write` at the game's time[^activity].
11. **Records.** Add the row to the Releases table and rewrite "Current production" and "Rollback".

**Completion criterion:** `/healthz` reports the expected `bot`, `pv_search.sha256` and `prior`, and the first
live room completes a game with no rollback trigger.

A shortlist package (releases 22–28, now only a rollback path) also needs the decision-identity gate before the
smoke: `server/scripts/cwv_serving_gate.py --serving --threshold 1000` (last run for release 28; never run for a
`pv-search` release). The older generic smoke is `server/scripts/cwv_serving_smoke.py`.

## Releases

Every deploy was `fly deploy --ha=false` on machine `48e7e35a9597e8`. Full per-release notes (served names,
evidence, smoke numbers, what else shipped from main): [docs_archive/deploy-through-2026-10-16.md](docs_archive/deploy-through-2026-10-16.md)
for releases 39–46, [docs_archive/deploy-releases-28-38.md](docs_archive/deploy-releases-28-38.md) for 28–38.

| release | deployed (ET) | what changed | bot or package | PR | image (Fly) |
|---:|---|---|---|---|---|
| 51 | 2026-11-06 (Fly v61) | release 50 with the held-out lead confirmation off (`SHENGJI_PV_LEAD_CONFIRM = '0'`); lccC (off − on) −0.0133 [−0.0232, −0.0033] on cloud, loo +0.0079 [−0.0069, +0.0221]; S91: CPU per play ×0.55 on Fly | flag | this PR | `deployment-01M6QW43KBFT3ZDDZWM298WPM3` (v61) |
| 50 | 2026-11-04 15:24 EST | the cbaC stack: G3 Stage A value + FT1 card-play prior + B1a belief + belief bury worlds (`bbw`) on release 49; evidence [cbaC](https://github.com/jerryyyu/shengji/pull/1171#issuecomment-6629156672) (audit [6629239690](https://github.com/jerryyyu/shengji/pull/1171#issuecomment-6629239690)), [cbaf](https://github.com/jerryyyu/shengji/pull/1171#issuecomment-6637319197), rtF; latency: the R50 speed profile, Fly timing pending | new value `f4f4127e…`, prior `1fa201b2…`, belief `028131a0…` | #1260 | v57, `deployment-01M6M3PX2A43CPZ65RBQPRY8AB` |
| 49 | 2026-11-01 01:39 EST | board combo3 arm Y: singleton challenger (`sc8`) + held-out lead confirmation (`lcc32`) on release 48; evidence [combo3y](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6475680068), [combo3yc](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6479431994), latency s71fly + v107sc8lat | flags | #1194 | `deployment-01M6AX9WCDG3YMGWZPDE9PSM12` (v56), main `d2a6346a` |
| 48 | 2026-10-24 10:18 | S58 belief package + `dtrx` + guarded greedy finish (`lgf lgfx lgfd2000`) + latency switches; evidence [r48cloud](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6383298163), [r48confirm](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6384251320), [v105lat](https://github.com/jerryyyu/shengji/issues/1075#issuecomment-6384912469) | new belief package `42444515…` | #1147 | `deployment-01M5Q4ACYEJ901SQB3BNMPC55A` (v47), main `f14ace15` |
| 46 | 2026-10-16 14:49 | v92 combo: belief worlds, exact endgame at 7, `vdef` | new belief package `763b5e05…` | #1072 | `deployment-01M530R14ARM0669QNJBW2RGTG` (v46), main `ab6fd1b2` |
| 45 | 2026-10-13 05:27 | wide value-only bury (`bwv`, K 64) | flag | #983 | `deployment-01M4T9AVEVK51WP2GG8J34NRC9` (v45), main `1ca97051` |
| 44 | 2026-10-11 17:05 | value-guided trump declaration (`vd`) | flag | #963 | `deployment-01M4PC7724HSXC27PCEEREZWY4` (v44), main `8ac9543e` |
| 43 | 2026-10-09 15:46 | doomed-throw re-select replaces the swap (`dtr`); correctness fix | flag | #953 | `deployment-01M4H37RYNM42YHH6ZPEC6GKCK` (v43), main `6b385b55` |
| 42 | 2026-10-06 19:08 | doomed-throw swap (`dts`); backend from main again | flag | #918 | `deployment-01M49QGK2ZP18P143S8BXVW28X` (v42), main `e3aa1724` |
| 41 | 2026-10-05 21:40 | web performance; frontend overlay[^overlay] | none | #845 | digest `sha256:4d1e796f7f2dd2c2ff337c05b09b2ebdf672c43ecf7232d2f5954b796c7b52ee` (v41) |
| 40 | 2026-10-05 11:34 | mobile landscape layout; frontend overlay | none | #829 | digest `sha256:2b24572af11b7098c32f4033956f5dde4ce39eeb6e2f95bba0b7f25d24fb6736` |
| 39 | 2026-10-05 01:47 | mobile UI, touch, accessibility; frontend overlay | none | #778 | `deployment-01M459KDH29EQFN9SDRH7P4GQ2` |
| 38 | 2026-10-03 09:41 | four search rules (`div rc tb la`) | flags | #698 | `deployment-01M40ZWSAHNX4782CGKJ615YF7` |
| 37 | 2026-10-01 01:1x | phone top bar one strip | none | #671 | `deployment-01M3TXZ85YHJM108TBPWKN8BB2` |
| 36 | 2026-09-30 11:53 | gen-5 SMV3 outcome head | play package `491ee4bf…` | #666 | `deployment-01M3SG9NVC1AC3PNPEH5Y34N0D` |
| 35 | 2026-09-28 01:49 | phone overflow menu, points bar | none | #653 | `deployment-01M3K8WQX7EXB3CYDMNGJ8MQHN` |
| 34 | 2026-09-27 20:22 | quieter phone table | none | #652 | `deployment-01M3JP62AR34FH5929FQC9GK7P` |
| 33 | 2026-09-26 11:50 | starting level in the room screen | none | #646 | `deployment-01M3F6FPRBXCK5Q4BDA0CET5A8` |
| 32 | 2026-09-26 10:2x | play on past Ace[^ace] | none | #644 | `deployment-01M3F1Q968BKYT8CD9GGE7XYMX` |
| 31 | 2026-09-25 12:51 | `create_room` accepts `start_level` | none | #638 | `deployment-01M3CQK3KMH55NDZRED6PDJ6XW` |
| 30 | 2026-09-22 09:13 | hybrid-bury duplicate fix | none | #607 | `deployment-01M34KWRW4XWJWC6DCCYENFXTF` |
| 29 | 2026-09-22 00:29 | `pv-search` W64/K8, soft head | package `ccade130…` | #588 | `deployment-01M33NZERJS18A0G2NNG7S5FJ8` |
| 28 | 2026-09-16 00:5x | JS-M1 joint net in the MC shortlist | package `0d17fd03…` | #425 / #435 | `deployment-01M2M90VYR34R7CWKTTEA4C57V` |
| 22–27 | — | W32 and shortlist era | see archive | — | [w32-fly-serving-through-2026-09-22.md](docs_archive/w32-fly-serving-through-2026-09-22.md)[^r22] |

## Infrastructure

### Ground rules (any host)

The server is a **single stateful process**: rooms and games live in memory, and clients hold WebSockets to it.

| rule | why |
|---|---|
| exactly one instance: no replicas, autoscaling or serverless | two instances would each hold half the rooms |
| deploy when quiet (0 rooms) | a restart drops games ("That game has ended.") |
| TLS at the platform or proxy | the frontend picks `wss://` on https pages itself |
| bot chosen by `SHENGJI_BOT` | source fallback is `mc` (N=10); Fly sets the served name |

`smart` and `heuristic` are cheaper difficulty choices, not strength-equivalent replacements;
`mc-s0-report-lcb` (MC-LCB, the pre-release-22 production policy) is the deep play-policy rollback; the W32
shortlist packages (releases 22–28) are the registered rollbacks between it and pv-search
(`docs_archive/w32-fly-serving-through-2026-09-22.md`).

**Health check `GET /healthz`.** Reports `bot`, `fast`, `pv_search` (sha256, budgets, bury arm) and `prior`. Its
`activity` block counts, since the process started: rooms created, games started, rounds recorded (a
`round_start` record reached disk), records written, write failures, the last successful write (ISO UTC) and the
last failure's exception class and errno. `games_started` ahead of `rounds_recorded` is a room-log write failure;
all zeros for days is inactivity. The counters never gate the room path and carry no room code, path or payload,
so the endpoint stays unauthenticated.

**The `pv-search` mode** (production since release 29) is `train/pv_search_policy.py`, registered when
`SHENGJI_PV_CKPT` is set and refusing a package without its `SHENGJI_PV_SHA256` pin. Per play: a heuristic anchor,
W belief-proposed worlds, K candidates admitted by the card-play prior, each scored by the value package, then
the rule stages the env turns on (exact endgame, the greedy-finished leaf, sc8, lcc32, and the rest).
`AI_POLICIES.md` "Production contract" lists each stage. On budget
expiry or error the anchor plays with a `pv-search-fallback-v1` record; otherwise the record is
`pv-search-decision-v1`.

### Option A: Fly.io (recommended)

```bash
brew install flyctl && fly auth login
fly launch --copy-config --no-deploy   # uses fly.toml; pick an app name
fly volumes create shengji_data --size 1   # ONE volume (see below)
fly deploy --ha=false                      # ONE machine (see below)
```

`fly.toml` pins an always-on 512MiB machine with `auto_stop_machines = "off"` so idle games are not killed.
Custom domain: `fly certs add yourdomain.com` + a CNAME.

Two Fly defaults to override:
- **`--ha=false` is required.** Plain `fly deploy` creates TWO machines; the proxy would split players between
  them and rooms would appear missing. If you end up with two, `fly machine destroy <id> --force` one.
- **Ignore the volume redundancy warning** (`-n 2`). Extra volumes get claimed by phantom machines and wedge
  deploys ("volume already claimed" / "needs an unattached volume"); destroy extras with
  `fly volumes destroy <vol_id>`.

### Option B: any VPS with Docker

```bash
docker build -t shengji .
docker run -d --restart unless-stopped -p 127.0.0.1:8000:8000 shengji
```

Put Caddy in front for TLS (Caddyfile: `yourdomain.com { reverse_proxy
localhost:8000 }`); Caddy proxies WebSockets automatically.

### Option C: zero-deploy for friends

Tailscale (invite friends to your tailnet, run the server locally) or a Cloudflare Tunnel. No changes needed.

### Capacity

Policy cost, not the rules engine, sets CPU capacity.

| policy (measured on the Mini) | decision p50 / p95 |
|---|---|
| SmartBot | 0.05 ms / 0.13 ms |
| direct v11pair (NumPy) | 0.25 ms / 0.52 ms |
| `mc` (N=10) | 77 ms / 150 ms |
| production report-LCB vs `mc-strong` (earlier matched benchmark) | 0.390 s vs 0.127 s |
| release 50 play, one pinned cloud core (R50 speed profile) | p95 1.054 s, p99 1.262 s, max 1.671 s; release 49 on the same profile p95 1.031 s, p99 1.208 s, max 2.400 s; leads are 72% of bot compute and lcc32 alone 43% of release 49's play compute |
| release 48 play, one pinned cloud core (v105lat) | p95 0.566 s, p99 0.746 s, max 2.408 s; peak RSS +26,792 kB over release 46 |
| release 46 combo play, one perf core (v93lat) | p95 0.187 s, p99 0.400 s, max 2.404 s; peak RSS +48 MiB over release 45 |

- Fly's shared-cpu-1x is slower and shared: about ×2 a cloud core unthrottled (v104fly), and about 8% of a core
  once throttled (s71fly). Release 50 at half budget on a cloud core (hb50) had 0 budget fallbacks, but lcc32
  abandoned 23% of its leads at the cut. Throttled, releases 48 and 49 ran near the 3 s budget (s71fly), and the
  R50 speed profile projects the same for release 50. The first-room reader (Release checklist, step 9) checks
  that on Fly.
- The 512MiB machine fits bounded serving probes; that is not a concurrency or worst-case memory guarantee.
- Off-loop execution hides event-loop blocking and overlaps the 0.7 s pacing floor; it does not make search free.
  Each turn snapshots after the latest play, computes, then revalidates before commit.
- Load-test the chosen policy and room mix before advertising capacity. Memory per room is small; more than one
  process would need external state and room-affinity routing.

[^cmp]: Jerry, in session 2026-11-04 ("Yes move comparator"): duels and screens move to release 50 as served. Before that, release 49 (Y; Jerry, in session 2026-11-01), release 48
    (Jerry, in session 2026-10-24: "Yes screens should compare vs our prod policy of r48"), release 46
    (Jerry 2026-10-16, #707 issuecomment-6223485189), and before that release 45 (Jerry 2026-10-13, #988 issuecomment-6142666693). Confirmations keep their parent's comparator.
[^belief]: Registration refuses a missing or mismatched belief file, so a served bot at all means the sha matched;
    the in-machine line (Release checklist, step 8) prints its first eight hex digits.
[^pvprior]: `/healthz` `prior` is the JS-M1 rollback key (`SHENGJI_CWV_PRIOR_*`), not the card-play prior.
    Registration refuses a `SHENGJI_PV_PRIOR_CKPT` file whose hash is not `SHENGJI_PV_PRIOR_SHA256`, and the served
    name carries its first eight hex digits (`-prior-1fa201b2`), so the name on `/healthz` shows the sha matched.
[^fast]: Its `ls` fails the build if a `.so` is missing; `.dockerignore` keeps a local Darwin `_endgame_fast*.so`
    out of the build context. The pure-Python twin returns identical results, only slower: a `python` backend in
    production is a latency regression, not a wrong play.
[^smoke]: `server/scripts/cwv_serving_smoke.py` builds the `pv-search` bot when `SHENGJI_PV_CKPT` is set; the
    full-round smoke runs the 7-card endgames and the belief proposal through the server path.
[^activity]: Production wrote no room log between 2026-10-09 19:04Z and at least 10-15, and nothing could tell
    inactivity from a silent write failure; release 46 is the first deploy with the counters. `games_started`
    moving while `rounds_recorded` stays 0 is a write failure, named by `last_record_failure` and the warning line
    `room <CODE> event logging failed (<class> errno=<name>)`. Whether to play that game deliberately is Jerry's call.
[^overlay]: Releases 39–41 were frontend-only overlays on the immutable release-38 image; the recipe is in the
    [#778 release record](https://github.com/jerryyyu/shengji/pull/778#issuecomment-5988860620). Do not replace
    main's normal Dockerfile with it. Release 42 superseded the recipe.
[^ace]: Rolling back past release 32 reverts the Ace rule (restores one-game-and-stop).
[^r22]: Heading "Moved from DEPLOY.md on 2026-10-01": the release-28 plan as approved, release 27
    (`deployment-01M2M1B48P44H5HJXEP6ETYQXE`), the release-26 image rollback, release 25, and the release-22
    boundary. Release 24's image is `deployment-01M2BGBXE7JXWYBEVWNMG2YM5A`.
