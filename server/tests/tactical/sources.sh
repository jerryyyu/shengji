#!/bin/sh
# Rebuilds tests/tactical/fixtures.jsonl from its sources (all machine-local:
# the Fly room-log cache logs/<ROOM>.jsonl and the runPVR self-play shards).
# Each line below is one observed mistake; see README.md for the rule and the
# predicates.  Run from server/:  sh tests/tactical/sources.sh > tests/tactical/fixtures.jsonl
# (then stamp current_bot with scripts/tactical_report.py --stamp).
set -e
LOGS=${SHENGJI_ROOM_LOGS:-../logs}
PVR1=${SHENGJI_RUNPVR1:-/Users/jerryyu/shengji-ssd/shengji-pvr/runPVR1/shards}
PVR4=${SHENGJI_RUNPVR4:-/Users/jerryyu/shengji-ssd/shengji-pvr/runPVR4/shards}
PY=${PYTHON:-.venv/bin/python}
F="$PY scripts/tactical_fixture_from_source.py"

# ---- doomed-throw: a multi-component lead the bot's own sampled worlds refuse
$F room-log --log $LOGS/CDCE.jsonl --line 33 --id cdce-r1-s1-t1-throw --category doomed-throw \
  --predicate not_a_doomed_throw \
  --why "banker (trump S/2) led D2+S2+S2+SQ at trick 1; engine forced SQ. Every admitted candidate but HA+HA was a variant of the same trump throw and no plain single was admitted (#676 ex.1)."
$F room-log --log $LOGS/KHPX.jsonl --line 446 --id khpx-r2-s2-t9-throw --category doomed-throw \
  --predicate not_a_doomed_throw \
  --why "7 of 8 admitted candidates were diamond-throw variants; attempted D4+D7+D7+D9+D9, forced to D4 (#677 ex.1)."
$F room-log --log $LOGS/LKMU.jsonl --line 12 --id lkmu-r1-s2-t0-throw --category doomed-throw \
  --predicate not_a_doomed_throw \
  --why "first lead of the round: C2+C2+C6+C6+C7 (trump C/2) forced to C7; the 7 throw variants admitted all tied at -0.3126."
$F room-log --log $LOGS/CDCE.jsonl --line 117 --id cdce-r1-s2-t5-throw --category doomed-throw \
  --predicate not_a_doomed_throw \
  --why "attacker led D6+D6+DK+DK+DQ (two pairs plus a queen); forced to DQ, the pairs then exposed."
$F shard --shard $PVR1/cluster-000000.jsonl --key :0:0:3:48 --id pvr1-0-0-3-48-throw --category doomed-throw \
  --predicate not_a_doomed_throw \
  --why "attacker led C4+C7+CJ at trick 12 (1.0521 vs 1.0498 for C7+CJ and 1.0391 for C4 alone); forced to C4 (#676 key :0:0:3:48)."

# ---- repeated-failed-throw: the second/third attempt after a public refusal
$F room-log --log $LOGS/CDCE.jsonl --line 75 --id cdce-r1-s1-t3-rethrow --category repeated-failed-throw \
  --predicate not_a_doomed_throw \
  --why "same banker, two tricks after the trick-1 refusal: D2+S2+S2 forced to D2; the refusal notice is UI-only (#621), so the search re-throws blind."
$F room-log --log $LOGS/CDCE.jsonl --line 96 --id cdce-r1-s1-t4-rethrow --category repeated-failed-throw \
  --predicate not_a_throw_refuted_by_public_refusal \
  --why "third attempt: H2+S2+S2 forced to H2. The trick-3 refusal already proved a trump single above D2 (same level as H2) is out, so this throw was refuted by public information."
$F room-log --log $LOGS/LKMU.jsonl --line 159 --id lkmu-r1-s2-t7-rethrow --category repeated-failed-throw \
  --predicate not_a_throw_refuted_by_public_refusal \
  --why "7-card trump throw forced to C8 one trick after the same seat's 7-card throw was forced to D2 (a higher single): the C8 component was refuted by the public refusal."
$F room-log --log $LOGS/LKMU.jsonl --line 201 --id lkmu-r1-s2-t9-rethrow --category repeated-failed-throw \
  --predicate not_a_throw_refuted_by_public_refusal \
  --why "third refusal of the series: C10+C10+C2+C2+C3+C6+C6 forced to C3 after C8 had been forced two tricks earlier."
$F room-log --log $LOGS/KHPX.jsonl --line 467 --id khpx-r2-s2-t10-rethrow --category repeated-failed-throw \
  --predicate not_a_doomed_throw \
  --why "one trick after D4+D7+D7+D9+D9 was forced to D4, the same seat threw D7+D7+D9+D9+DQ and was forced to DQ."

# ---- point-donation: last to play, opponents winning, points played with a zero-point alternative
$F shard --shard $PVR4/cluster-000004.jsonl --key :4:0:0:63 --id pvr4-4-0-0-63-hk --category point-donation \
  --predicate no_point_donation_when_zero_point_alternative_exists \
  --why "held H7 H8 H5 HK, last to play into an opponent's winning trump; discarded HK over H7 by 0.000806 (#677 ex.2)."
$F shard --shard $PVR1/cluster-000212.jsonl --key :212:0:0:19 --id pvr1-212-0-0-19-sk --category point-donation \
  --predicate no_point_donation_when_zero_point_alternative_exists \
  --why "banker, last to play on a pointless diamond trick the opponents win: played C3+H3+SK, donating the king (#676 key :212:0:0:19; H4+LJ+LJ would even have won)."
$F shard --shard $PVR1/cluster-000000.jsonl --key :0:1:3:63 --id pvr1-0-1-3-63-c5d5 --category point-donation \
  --predicate no_point_donation_when_zero_point_alternative_exists \
  --why "attacker, last to play after the banker trumped: C5+D5 (10 points) over C4+H7 and other zero-point follows (#676 key :0:1:3:63)."
$F room-log --log $LOGS/LKMU.jsonl --line 363 --id lkmu-r1-s0-t16-d10 --category point-donation \
  --predicate no_point_donation_when_zero_point_alternative_exists \
  --why "online, last to play into a lost 15-point trick: D10+DA over DA+DJ (zero points), the whole ballot within 0.008."
$F room-log --log $LOGS/CDCE.jsonl --line 342 --id cdce-r1-s2-t15-d5 --category point-donation \
  --predicate no_point_donation_when_zero_point_alternative_exists \
  --why "online, last to play into a lost trick: D5 over C3/C4/C5, all four candidates within 0.024."

# ---- missed-point-win: last to play, >= 10 points on the table, a legal action wins the trick
$F shard --shard $PVR1/cluster-002567.jsonl --key :2567:1:0:35 --id pvr1-2567-1-0-35-c2 --category missed-point-win \
  --predicate wins_point_trick_when_available --args '{"min_points": 10}' \
  --why "banker, last to play with 10 on the table: C2 ties the led C2 and loses; H2 (the trump-suit rank card) wins the trick."
$F shard --shard $PVR1/cluster-004327.jsonl --key :4327:0:3:59 --id pvr1-4327-0-3-59-hj --category missed-point-win \
  --predicate wins_point_trick_when_available --args '{"min_points": 10}' \
  --why "banker, last to play on D2 H10 H9 (10 on the table): HJ loses to the led rank card; H2 wins."
$F shard --shard $PVR1/cluster-004007.jsonl --key :4007:0:2:55 --id pvr1-4007-0-2-55-hj --category missed-point-win \
  --predicate wins_point_trick_when_available --args '{"min_points": 10}' \
  --why "attacker, last to play on C7 CK D6 (trump D; 10 on the table): HJ discards; D9 over-trumps and takes the king."

# ---- shortlist-miss: admission coverage on multi-card leads
$F shard --shard $PVR1/cluster-003952.jsonl --key :3952:1:1:16 --id pvr1-3952-1-1-16-lead --category shortlist-miss \
  --predicate structured_lead_admitted --args '{"actions": [["S10","S9","SA"], ["S10","S9","SJ"]]}' \
  --notes "the exploration draw itself was refused by the engine (forced S9); the predicate asks only whether admission reaches the lead the value head preferred by +0.133 over the shortlist's best (#676 ex.2)" \
  --why "banker lead at trick 4: the 8 shortlisted candidates were SA and seven club variants; the random draws S10+S9+SA / S10+S9+SJ out-valued all of them."
$F room-log --log $LOGS/KHPX.jsonl --line 446 --id khpx-r2-s2-t9-crowded --category shortlist-miss \
  --predicate admitted_ballot_not_crowded --args '{"max_same_suit_throws": 4}' \
  --why "7 of 8 admitted candidates were variants of one diamond throw (#677 ex.1): the search budget spent on one plan."
$F room-log --log $LOGS/CDCE.jsonl --line 33 --id cdce-r1-s1-t1-crowded --category shortlist-miss \
  --predicate admitted_ballot_not_crowded --args '{"max_same_suit_throws": 4}' \
  --why "7 of 8 admitted candidates were variants of one trump throw; no plain single reached the value head."
$F room-log --log $LOGS/LKMU.jsonl --line 12 --id lkmu-r1-s2-t0-crowded --category shortlist-miss \
  --predicate admitted_ballot_not_crowded --args '{"max_same_suit_throws": 4}' \
  --why "7 of 8 admitted candidates were variants of one club throw, all valued identically."
