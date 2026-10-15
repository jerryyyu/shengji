# find_gaps: exploit duels against the served bot

DEV diagnostics. Nothing here is a screen, a strength claim or a served path.

## exploit_duel.py

Seats an exploiter partnership against two copies of the served bot (fly.toml's `SHENGJI_BOT` and
env, rebuilt from the repo's `fly.toml`; `SHENGJI_CWV_*` rollback keys are skipped). Each deal is a
first-round deal played twice with the teams swapped.

Every seat starts as the served bot with a seed that depends only on the deal and the seat, never on
the arm or the mirror. The served bot is deterministic given its seed, so served-bot x4 plays the same
round in both mirrors and its mirrored margin is exactly 0. An arm's mirrored margin is therefore its
paired difference against served-bot x4 on the same deal. `--arm identity` (the exploiter wrapper with
no override) must read 0 on every deal; check it on any new host or tree.

The unit is the exploiter team's signed levels per round. The CI is a 95% bootstrap over deals. The
points margin is role-confounded whenever an arm changes who becomes banker.

```
cd server
SHENGJI_FAST=1 nice -n 10 .venv/bin/python scripts/find_gaps/exploit_duel.py \
    --arm declare-asap --seed0 71000000 --deals 200 --workers 2 --history --out OUT/declare-asap.jsonl
.venv/bin/python scripts/find_gaps/exploit_duel.py --summarize OUT/*.jsonl
.venv/bin/python scripts/find_gaps/exploit_duel.py --list
```

- `--defender-env SHENGJI_PV_X=V` / `--exploiter-env SHENGJI_PV_X=V` (repeatable; an empty `V` removes
  the key) build a variant of the served recipe for the victim seats or for the exploiter's base bot.
  Example: `--defender-env SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST=1`.
- Output is resumable: a rerun with the same `--out` plays only the missing deals. Never run two
  processes on the same output file.
- To run from a frozen copy of these scripts against another tree, set `FIND_GAPS_SERVER=<tree>/server`
  (the tree's parent must hold its `fly.toml`) and `FIND_GAPS_PKG=<package .npz>`.
- Check seeds with `scripts/seed_windows.py check SEED0 N --purpose screen` before a run.
- Each record carries `telemetry` (budget/search-error fallbacks per side, exact-lead status counts),
  so a loaded host that trips the 3 s serving budget shows up instead of silently adding noise.

## hypotheses.py

One class per hypothesis, registered by name. A hypothesis may override `declare`, `bury` or `play`.
A `play` hook that consults the served bot itself must return `(cards, overrode)`, so the bot is never
asked twice. Names starting with `cheat-` see hidden information. They are calibration bounds, not
exploits.

## Other tools

- `role_decompose.py IDENTITY.jsonl ARM.jsonl`: splits an arm's margin by banker transition (the role
  the exploiter seats would have had under served-bot x4 versus the role they had in the arm).
- `r45_profile.py OUT.jsonl --mirror 0`: the served bot's declaration, bury, kitty, throw and ruff
  profile from `--history` records.
- `human_loss_attribution.py`: replays production room logs and attributes the bots' losses to humans
  by phase and role against perfect-information yardsticks (exact endgame minimax; heuristic
  rollouts on the true deal). Pass `--logs` and `--out`; the defaults point at one local machine.
