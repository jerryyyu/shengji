# Tactical regression fixtures (diagnostic, not a gate)

Issue #677 strategy 4 ("add tactical regression cases"), examples from the
10-01 mistake survey #676.  Each fixture is one position where the served bot
made a concrete bad decision, stored with the information the acting seat had
AT THE TIME, the action it took, and a predicate for an acceptable action.
The set runs the real `pv-search` bot through the real `decide_play` entry
point on the real serving package, built from a fly.toml-shaped environment
exactly as the server registers it (`pv_env_recipe` -> `pv_registry_entries`).

**It is not a gate.**  The production bot (release 36,
`pv-search-491ee4bf-w64-k8-r4a09aef5-bury-hybrid-355958b4db25`) fails 21 of
the 22 fixtures; those are `xfail(strict=False)` in the pytest module, so the
suite is green and informative.  Its purpose is to show what MOVED when an
admission or tie-break change (#676 A/C/E, #680) is screened: run
`scripts/tactical_report.py` against the candidate and read the per-fixture
table against the recorded production verdicts (`current_bot`).

## The "information available at the time" rule

A fixture stores:

- the public setup: trump rank/suit, banker, the declaration sequence;
- the public play history: the ENGINE's cards for every play, plus
  `attempted` where a throw was refused (the refusal notice is shown to the
  whole table, so it is public);
- the acting seat's own hand at the decision, and its own burial when it is
  the banker.

It never stores the other hands or a non-banker's view of the kitty.
`shengji.eval.tactical.public_round` rebuilds an engine `Round` at the decision
by filling the unseen pool into PLACEHOLDER hidden hands (deterministic, seeded,
with publicly shown declaration cards pinned to their declarer) and replaying
the public history without the validators that read other hands.  The bot then
samples its own worlds from the public state -- `Memory` reads only the seat's
hand, the play history and the declaration -- so the placeholder never reaches
a value or a prior.  `test_decision_is_invariant_to_the_placeholder_fill`
proves it: a fresh bot with the same seed plays the same cards, admits the same
ballot and prices it identically on two different fills.

Predicates judge with the same information:

| predicate | judged on | category |
|---|---|---|
| `not_a_doomed_throw(max_fail_fraction=0.5)` | the bot's OWN 64 sampled worlds (captured, not re-drawn): the action is not a multi-component lead that the engine's `validate_lead` refuses in more than half of them | doomed-throw, repeated-failed-throw |
| `not_a_throw_refuted_by_public_refusal(suit, pair_len, top, refusal_index)` | the public refusal history only: after the seat's throw was forced down to a component, the table knows a higher structure in that suit is out; a new throw with a component of that suit, pair length and no higher top is refuted unless a beating structure was played since (then the inference is void and the fixture passes) | repeated-failed-throw |
| `no_point_donation_when_zero_point_alternative_exists` | last position (trick outcome exact): opponents win whatever we play, we played points, a zero-point legal action existed | point-donation |
| `wins_point_trick_when_available(min_points=10)` | last position: at least `min_points` on the table, some legal action wins the trick for our team, we did not | missed-point-win |
| `structured_lead_admitted(actions)` | the search record: one of `actions` is in the admitted ballot | shortlist-miss |
| `admitted_ballot_not_crowded(max_same_suit_throws=4)` | the search record: at most N of the admitted candidates are throws in one effective suit | shortlist-miss |

Every predicate is a heuristic for "acceptable", not hindsight truth: winning a
10-point trick may cost a card worth more later; a throw refused in 60% of the
bot's worlds may still be the best lead.  The thresholds are visible arguments
and the detail string says what was measured, so a screen reads the movement
and the reader decides what it means.  The two search-record predicates need a
`pv-search`-shaped `last_decision_record`; a heuristic bot fails them with
"no complete search record".

## Files

- `fixtures.jsonl` -- the set, one `tactical-fixture-v1` row per line (schema
  below).  Never hand-edit a position: rebuild from the source.
- `sources.sh` -- rebuilds `fixtures.jsonl` from its sources with
  `scripts/tactical_fixture_from_source.py` (sources are machine-local: the
  Fly log cache `logs/<ROOM>.jsonl` and the runPVR shards on the SSD).
- `shengji/eval/tactical.py` -- loader, public rebuild, predicates, runner,
  table formatter, env -> bot.
- `tests/test_tactical_fixtures.py` -- the pytest module (package-free checks of
  the set + the xfail-tolerant bot run).
- `scripts/tactical_report.py` -- the screen tool: any env / package / registry
  bot, prints the table, `--json`, `--stamp`.

### Fixture schema

```
id, category, source{kind,path,line|source_ref,round|run}, seat, trick (0-based),
position (0 = lead .. 3 = last), setup{trump_rank, trump_suit, trump_is_nt,
banker, declarations[{seat,cards}], buried|null}, plays[{seat, cards[, attempted]}],
hand, observed{action, engine_play, admitted, value_means, ...}, predicate{name,
args}, why, current_bot ("pass"|"fail"|null, recorded for the production bot),
notes
```

## Running

```
cd server
# the served package, local copy (read-only), production knobs by default
export SHENGJI_PV_CKPT=/path/smv3out-491ee4bf.npz
export SHENGJI_PV_SHA256=491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670
SHENGJI_FAST=1 uv run python -m pytest tests/test_tactical_fixtures.py -q -rxXs
# -> xfailed = known production failures, XPASS = a fixture that started passing;
#    the per-fixture report path is printed at the end (TACTICAL_REPORT=path to pin it)

# the screen tool: production recipe on a package
uv run python scripts/tactical_report.py --ckpt $SHENGJI_PV_CKPT --sha256 $SHENGJI_PV_SHA256
# a candidate recipe: override knobs, or hand it the full env
uv run python scripts/tactical_report.py --ckpt ... --sha256 ... --env-override SHENGJI_PV_CANDIDATES=16
SHENGJI_PV_CKPT=... SHENGJI_PV_SHA256=... SHENGJI_PV_CANDIDATES=16 uv run python scripts/tactical_report.py --from-env
# any registry bot
uv run python scripts/tactical_report.py --bot smart
```

Without the package the bot tests skip (shown under `-rs`) and the set checks
still run.  One fresh bot per fixture (`--seed`, default 0), so a verdict is a
function of the fixture and the seed alone, never of the order of the set; the
production verdicts are identical at seeds 0 and 1.  A decision takes ~0.1 s.

## Adding a fixture

1. Find the decision.
   - Room log: the 1-based line of the `play` event in `logs/<ROOM>.jsonl`
     (bot plays carry the `decision` blob; a refused throw carries
     `attempted_cards` + `engine_resolution`).
   - Self-play shard: the record's `source_ref` suffix
     `:<shard>:<round>:<seat>:<ply>` in `runPVR*/shards/cluster-<shard>.jsonl`
     (the survey script in #676 prints keys in this form).
2. Add a line to `sources.sh` naming the id, category, predicate (+ args), and
   a one-line `why` that states the observed mistake.  For
   `not_a_throw_refuted_by_public_refusal` leave the args empty: they are
   derived from the last public refusal of that seat in the history.
3. `sh tests/tactical/sources.sh > tests/tactical/fixtures.jsonl` (the builder
   rebuilds the FULL deal from the source, strips it to the public view, and
   refuses if the public view does not replay to the same trick state), then
   `scripts/tactical_report.py --ckpt <production package> ... --stamp` to
   record `current_bot`.
4. `pytest tests/test_tactical_fixtures.py` without the package: the set checks
   must pass (the predicate must judge the OBSERVED action as a failure and an
   obvious alternative as a pass).

Ids are `<room>-r<round>-s<seat>-t<trick>-<tag>` or `pvr<run>-<key>-<tag>`.

## Caveats

- The production bot reproduces the observed action on 18 of the 22 fixtures
  at seed 0; on two positions (`cdce-r1-s1-t1-*`, `pvr1-0-0-3-48-throw`) it
  picks a sibling variant of the same throw, and on `pvr1-3952-1-1-16-lead` the
  observed action was an exploration draw the production recipe never admits.
  This is the position, not the production RNG state, so a seed can differ.
- `pvr1-3952-1-1-16-lead` asks whether admission reaches the lead the value
  head preferred (+0.133) when it was drawn by exploration; that lead was itself
  refused by the engine in the real deal (forced S9).  It measures admission
  coverage, not whether the lead was right.
- Room-log positions: the deal is the log's `round_start.deck`, declarations
  and bury are the log's events, plays are the log's engine cards (the harvest
  extractor's path, `rl.replay_log.rebuild_round`).  Shard positions:
  `harvest.rebuild.state_for_record`.  A kitty-flipped trump (no declaration)
  is not supported by the public rebuild.
