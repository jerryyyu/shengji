# Player flows and UI decisions

This is the source of truth for how a player moves through the app: what each surface shows, which
path reaches a table, how leaving works, and the copy rule. The drawn mock of every flow is
`docs/design/mocks/core.py` (`python3 docs/design/mocks/core.py` writes `core.html` beside it);
`docs/design/mocks/build.py` draws the per-decision record (`unify.html`) and regenerates
`docs/design/COPY_CUTS.md`. Where this file and a mock disagree, this file wins.

A reversal edits the old line in place (say what it now is and when it changed); it never appends a
second, contradicting line further down. Paths below that point outside the repo are where these
files were drafted; the repo copies above are the live ones.

# Unification build spec (Jerry decisions 2026-11-14)

This spec is the source of truth for the build agents. The visuals are the mock page
`/Users/jerryyu/Projects/shengji/logs/mocks/unify/build.py`. Each section has a function there (`s1_seats`,
`one_table_ui`, `s2_bots`, `s3_leave`, `s4_connection`, `s5_tabs`, `s6_settings`, `s7_guest`, `s9_timers`), and
each one's caption, frames and decisions spell out the design and cite file:line for today's code. It is
rendered as `unify.html` (published as artifact YDdcNosqL3uYpMCwMYsHGX). Where this spec and the mock disagree,
this spec wins.

## Approved

**Section 1, one table UI for Play tables and rooms.**
- A room is a `room` kind of the existing green panel (`web/src/queue/TablePanel.tsx`), inline on the Play
  tab in Play's place. On desktop and iPad it sits in the Ranked card's place with the mini table.
- The full-screen Room lobby (`Room.tsx`) and the join-by-code seat picker (`Lobby.tsx:350-397`) are removed.
- Anyone at the table may move to an empty seat until they tap Start.
- Everyone taps Start ("N of M ready"). The opener gets Start now after 30 s.
- Starting level is the opener's only. When the opener leaves, their controls pass to the next person and
  the table stays open.
- A room adds three rows: the code with Invite link, Starting level, and the Ranked and Allow joiners switches.
  Joiners see these as one summary line.
- **Allow joiners defaults to ON** for created rooms (a reversal of 11-13).
- **Chat:** every table has chat from the moment you sit. A chat row in the panel opens the table's chat
  sheet, quick phrases first, and the same log carries into the game. Play tables before the game need a new
  queue chat message.
- A room link opened while you sit at another table shows the leave sheet first.
- Play tables get no code or Invite link yet.

**Section 2, Play bots folded into Play.**
- A Ranked / Casual switch above Play, remembered per device. Guests see both, and ranked guests are a fixed
  1000 and unsaved, as today.
- Play joins a table of the chosen mode first, else opens your own table in that mode.
- Casual Play never seats you at a ranked table.
- A casual room with Allow joiners on and a person present is an open table.
- **Presence line:** keep today's metadata (tables with a seat, people playing, people waiting / "players
  online"). Split by mode only when both have tables: "3 tables have a seat · 2 ranked, 1 casual · 5 playing",
  with the selected mode highlighted. Otherwise "2 ranked tables have a seat · 3 playing", or "Nobody is
  playing right now…".
- The "Play bots" row is replaced by Casual Play. Create room stays the way to get a code for friends.

**Section 3, one Leave sheet everywhere.** It has a one-line consequence per context and the same buttons.
The host role passes on, and a ranked leave keeps "at best a draw".
- **Relaxed join rule** (Jerry: "relax the 5 min rule"; values chosen by Claude, Jerry may adjust):
  - leaving a table you joined *during the round you joined* costs a **1-minute** wait (was 5);
  - leaving at a round end, or from a **casual** table, is free;
  - the "never offered that table again" bar stays;
  - copy: "Stay until this round ends, or wait 1 minute to play again."

**Section 4, connection.** One "Reconnecting…" pill, Retry after 10 s, a full-screen state after 60 s, and a
bad code shown inline under the code box. One wording.

**Section 5, tabs.** The same three tabs (Play / Leaderboard / Me) on phone, iPad and desktop. Stats and
Games become a switch inside Me.

**Section 6, settings.** One settings list (Coach, Sound, Haptics on native only, How to play) in both Me and
the ⋯ menu. "Kitty 8 cards" moves out of ⋯.

**Section 7, guest name.** One name control: the chip opens the same edit sheet on every tab. Me shows the
guest's name and initial with "Guest · not ranked".

**Section 9, timers.** One ring component with one rule, including a thin ring on other players' turns.
**The ring shows the seconds left as a number** (Jerry). Your own ring runs the whole move time. The queue strip
shows the bots' countdown, not elapsed time.

## Not decided (do not build)
- Section 8, game over / Next game.

## Offline (Jerry 2026-11-14: "we should just keep offline, dont go online")
- With no connection, Play opens your table with 3 bots on the device: the same panel, "Offline · not rated", Casual only (Ranked disabled with "Ranked needs a connection"). Duo, rooms and chat are disabled with a one-line reason.
- The presence line becomes a grey "Offline · you'll play the bots on this device".
- **An offline game stays offline.** When the connection returns there is no automatic switch and no mid-game prompt. The game continues on the device. Today's `offlineGame.goOnline()` on reconnect (`offline/server/ui.tsx:51-56`) must not move an ongoing offline game. After you leave the offline table, Play is online again as normal.
- The section 4 full-screen connection state offers "Play offline with the bots" next to Retry, replacing today's silent switch inside "Play bots" (`Lobby.tsx:244-247`).
- Offline games in local stats: not decided.
- Offline games do NOT count in Me's stats (Jerry 2026-11-14).
- The iOS app with no network at launch opens the Play tab's offline state, not a separate start screen (Jerry 2026-11-14: yes).
- Timer rings: the seconds number must not touch or overlap the ring stroke (Jerry 2026-11-14).

## Copy rule (Jerry 2026-11-14: "i dont think we need the metadata in play page … take a pass to minimize the metadata / subtexts")
- Switches and rows take a label only, with no sub-line: "Ranked", "Allow joiners", not "Rates signed-in players" or "On by default: …".
- No explanatory notes under controls on the Play page. At most one short status line per panel, and only when it changes what the player does next (a timer, "1 of 2 ready", the leave cost).
- Drop kickers, hints and repeated context where the layout already says it (e.g. "Tap a green seat to move" once at most, "Others can join as they arrive" not at all).
- Explanations belong in How to play and the coach, not under controls.
- Jerry's examples of too much subtext (cut entirely): "Tap a green seat to move", "Jerry opened this table", "Invite by link or code", "Bots sit in empty seats". A panel is its title + seats + at most one live status (a timer / "1 of 2 ready") + buttons.

## Every table has a code (Jerry 2026-11-14: "for Play → your own table on ranked, i think we can also show the room code and the create room settings similar to what we do for casual rooms")
- When Play opens your own table (ranked or casual), it gets a code with Invite link and the same table settings a created room has (the Allow joiners switch; Starting level for the opener). This reverses section 1's "no code for Play tables yet".
- A table is a table: "Create room" is no longer a separate path, because Play gives you a table with a code. Keep "Create room" only if Jerry wants it.
- Ranked tables: Starting level is fixed at 2 for rating fairness (Claude's assumption; confirm with Jerry).
- Server: a lone queue entry's own table must become a real table with a code. Today a lone entry has no server table (matchmaking.py, table created at 2 entries), so this is a follow-up to the room-table-server PR.

## Final decisions (Jerry 2026-11-14)
- **Game over:** keep games endless. When a team wins a game, the round end says so ("You & Alice win the game"), with Next game / Leave; the HUD shows the games score (e.g. "Games 1–0") after the first game won; delete the unreachable game-over card (`RoundEndModal.tsx:131-150`).
- **Join panel:** drop the leave-cost line entirely. The cost appears only in the Leave sheet.
- **Create room:** dropped entirely. Every table Play opens has a code with Invite link and Allow joiners; the Create room row and flow are removed.
- **Ranked tables:** start at level 2, fixed, with no starting-level row. Casual tables keep the opener's Starting level.

## Duo is a table (Jerry 2026-11-14: "it's awk to be in a duo room and play room at the same time"; "A duo should be paired"; panel, not popup)
- Duo opens your own table (the same inline panel as Play), with the partner seat held for your friend. There is no separate Duo code or Duo bar: the table's code and Invite link are the Duo invite, and a code joiner takes the held partner seat first.
- A Duo stays paired. After Start, or when Play matches you, the pair moves and is matched as one, as Duo is today, and a ranked Duo is rated as a pair. One Leave, on the panel, ends the Duo for you; your partner keeps the table.
- The table is an inline panel, not a popup. Popups are only for decisions (Leave, take a seat, a Duo invite).
- Built (client): the Duo sheet, the Duo chip and the separate party code are removed (`?party=` links read as `?code=`). Between games a formed pair shows one row, "Duo with <partner>" and Leave (`party_leave`), to both members; the leader keeps Play and Duo under it.

## Decisions 2026-11-14 morning (Jerry)
1. Duo flow as mocked (core.html section 5, "Duo: one table, paired"): approved, build it.
2. Allow joiners is the opener's switch only (server and client); others see nothing (copy rule).
3. Offline copy: plain "Offline" (cut the subtext); "Offline · you'll play the bots on this device" and "Ranked needs a connection" are dropped.
4. Round end: the top stays minimal (result line + buttons in a row), and a collapsed Details holds the kitty (cards, points, multiplier) and the last trick played. Keep that detail.
5. The guest line "Playing as a guest · Sign in to be ranked" stays.

## Grammar: Us/Them are labels, sentences say we/they (Jerry 2026-11-14)
- "Us" and "Them" are labels only: team heads, HUD chips, "Them 15 / 80", "Games: Us 1 · Them 0".
- In a sentence the team is "we" or "they": "They took 35 of 80. We go up 1, to 3.", "They won the last trick: ×2, +30". A round title names the players ("You & Alice win the round"), and with no names it says "We" or "They".

## Decisions 2026-11-14 afternoon (Jerry, on the UX retro)
- Guardrails: yes, all of them. That includes moving this spec and the mocks into the repo (`docs/design/`).
- Duo: the Duo button stays and holds a partner seat; otherwise the panel is the same as Play's.
- In-game: mute, Coach and Leave live only in the overflow menu. The icon is ⋯ (decided 2026-11-14 on the simplify mock, "Yes for all the simplification paths").
  - The header, phone and desktop alike, holds game state only: Us / trump / Them levels, the points, the mode chip, then Chat and ⋯. No mute, Coach, Leave, code, phase or kitty chip.
  - ⋯ opens one menu (`HudMenu.tsx`) in this order: the code with Invite link, Allow joiners (the opener's seat only, from the state's `opener`), then Coach, Sound, How to play, then a red Leave game that opens the one Leave sheet. The opener's controls pass to the next person when the opener leaves, in the lobby or mid-game.
- Server merge (one Table object): yes, planned after Duo lands.
- Start rule (no auto-start alone): Jerry asked for more explanation. It goes to a mock with both variants before any decision.
