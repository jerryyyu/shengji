# Lifecycle checklist

Reviews of server, room and Nearby changes keep finding bugs in these transitions.
A change that touches one names it in the PR and drives it in a test through the
listed helper (bare file names are in `server/tests/`); steady state is not enough.

## 1. Cancel mid-search or mid-deal

A task cancelled at an await (bot search, ratings read, queue search) commits
nothing, sends no later frame and drains its worker.

- `test_bot_scheduler.py`: `_blocking_deal_room` and `_patch_deal`, as in
  `test_cancelling_the_deal_during_a_bot_search_stops_it` (#1776).
- `test_matchmaking.py`: the `wsenv` fixture and its `Clock`, as in
  `test_ws_a_guest_who_signs_in_while_searching_alone_leaves_the_queue`.

## 2. Round replaced during an await

After any `await` the round, seat holders or level may have changed. Re-check
them under `room.lock` before committing; on a mismatch, discard or redo.

- `test_bot_scheduler.py`: `test_a_replaced_round_sees_nothing_of_the_old_deal`
  and `_paced_deal` (a virtual clock over the real `run_deal`) (#1776).
- `test_ranked_bots.py`:
  `test_a_handover_between_search_and_commit_replays_the_turn_at_advanced` and
  `test_a_seat_that_changes_during_the_settling_read_is_read_again` (#1781);
  for a later round's level rise, `test_a_round_replaced_during_the_rise_read_changes_nothing`
  and `test_a_seat_that_changes_during_the_rise_read_is_read_again`.

## 3. Seat or identity change mid-game

A handover from the open table or queue, a mid-round claim, or a resume as a
different account changes who holds a seat. Every per-seat decision cached at
round or game start is checked against the new holder.

- `test_ratings.py`: `Table` (four assigned seats played in-process), as in
  `test_a_mid_round_claimant_does_not_change_the_round_for_the_others`.
- `test_ranked_bots.py`: `test_a_guest_seat_resumed_as_a_1200_account_promotes`
  and `test_a_guest_who_signs_in_during_the_opening_deal_is_read_as_the_account` (#1781);
  a holder check overlapping a later round's rise read, in both completion orders:
  `test_the_rise_settle_is_authoritative_over_an_overlapping_seat_check`.

## 4. Old and new peers

A Nearby host and joiner, or the app and the server, can run different builds.
A new field is optional both ways, an older peer ignores it, and the new peer
still behaves correctly without it.

- `web/src/nearbyRestart.test.ts`: `phone(t, { oldHost: true })`, as in the
  "an older host" cases (#1769).

## 5. Crash or retry before confirmation

A once-only step (storage or cookie move, schema migration, marker write) is
marked done only once confirmed: a kill, timeout or offline launch before then
offers it again, and a repeat after an unconfirmed success writes nothing new.

- `test_device_accounts.py`: `test_a_fresh_database_matches_a_migrated_one`.
- #1790 (the iOS origin move): a pure `OriginMoveLedger` driven through interrupted
  launches in `web/ios/App/AppChecks/OriginMove/main.swift`, on that PR's branch.

## 6. Frame ordering and client-visible state

Each change a client can see gets its own frame, in commit order; coalescing
two changes into one later frame hides the first from the seated players.

- `test_bot_scheduler.py`: `_seated_deal` and `_declarations_shown`, as in
  `test_a_bot_declaration_reaches_the_seated_player_before_the_next_card` and
  `test_a_human_declaration_during_a_bot_search_is_ordered_first` (#1776).
- `test_ranked_bots.py`: `_frames`, as in
  `test_no_frame_differs_between_a_standard_and_an_advanced_ranked_table` (#1781).

## 7. Reconnect with a stale or kept token

A reconnect may carry a token for a seat another link, phone or account now
holds, or none after a lost Leave. One person never gets two seats, and a stale
link never detaches a newer one.

- `test_server_ws.py`: `test_stale_socket_cannot_detach_a_newer_connection` and
  `test_claiming_a_seat_rotates_its_token`.
- `web/src/offline/server/nearby/oneSeat.test.ts`: `seatedAt3`;
  `web/src/nearbyRestart.test.ts`: `forgetKeptSeat` (#1769).
- `web/src/nearbyChaosPage.test.ts`: the seed-30050 replays (#1770), `KeptToken`.
