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
- A room has no panel before its game (Jerry 2026-11-14: "We can remove it"): every created room starts at once
  with bots, a stale page's plain create included, so the green panel's pre-game `room` kind is removed and the
  panel is the waiting (queue) table's only. A room is joined only once its game is on, through a bot's seat.
- The full-screen Room lobby (`Room.tsx`) and the join-by-code seat picker (`Lobby.tsx:350-397`) are removed.
- At a waiting table, a joiner may move to an empty seat until it taps Ready; the opener, until the table starts. The seats stay drawn where they were while you move, so you land in the cell you tapped and Us follows your column (Jerry 2026-11-27: the table redrew around the new seat, so a tap seemed to land in another cell); another table draws around your seat again.
- The owner starts; a joiner's Ready is a signal (Jerry 2026-11-26: "same for any lobby joining — it can just have a start button for the owner, but for joiners it can be ready. Duo can follow that logic", then "the owner should be able to start even if people don't mark ready" (option A: Ready is a signal; Start takes everyone seated), then "I like the Ready button for joiners even though it's not necessary"; this replaces the same day's first version, where the owner's button read "Waiting for Alice" until every joiner was Ready, which itself replaced "Everyone taps Start, and the opener gets Start now after 30 s"). The opener (a Duo's leader) has no Ready, only Start with bots, always enabled, the same button and ring as alone, which fills the empty seats; its one status line counts the joiners' Ready ("1 of 2 ready"). Everyone else, a Duo opener's partner included, has a Ready toggle beside Leave: one tap puts the ✓ on its seat for everyone (the button stays "Ready", drawn quiet and pressed), a second takes it back; its one status line reads "Waiting for Jerry to start". The owner's Start takes everyone seated and connected, Ready or not; a joiner whose socket is gone leaves when the table starts (its seat a bot's); the owner's own Duo partner must be connected, since the pair moves as one ("Your partner is not in the lobby."). Nothing starts by itself but the bots' ring: not every Ready in, not four people (who started at once until 2026-11-26). Everyone seated, owner or joiner, Ready or not, has the same 2-minute idle check (Jerry 2026-11-26: "It's fine that joiners time out now"; asked "still here?" first at a table with no timer); any tap (Ready, chat, a move) resets the clock, and one promoted to owner starts its clock then. A Ready sent just before its sender became the owner is never a Start (the panel sequence, and untagged within 5 s of the change). The ranked queue has no ready check. Server: `matchmaking.py` `_table_start_now`, `_start_bots`, `_due`, `_check_panel`.
- Starting level is the opener's only. When the opener leaves, their controls pass to the next person and
  the table stays open.
- A created room has no Ranked switch: ranked play is the queue's, and Continue on a saved ranked game's.
- The created room's lobby controls are retired (Jerry 2026-11-14): Add bot, Remove bot, Remove player, the
  host's seat swap, the room's Start taps and Start now, and the room's Starting level after creation. An
  out-of-date page that sends one is refused as out of date. A refused start returns the creator to Play.
- **Allow joiners defaults to ON** for created rooms (a reversal of 11-13), and on every table Play opens.
  **Wait for people defaults to OFF**, so the bots' ring runs (Jerry 2026-11-24 confirmed both defaults). Both
  are set by the server (`matchmaking.py`: `allow_joiners: bool = True`, a new table's `wait_players` false),
  and the client reads them from its frames.
- **Chat:** every table has chat from the moment you sit. A chat row in the panel opens the table's chat
  sheet, quick phrases first, and the same log carries into the game. Play tables before the game need a new
  queue chat message.
- A room link opened while you sit at another table shows the leave sheet first.
- Play tables get no code or Invite link yet.

**Section 2, Play bots folded into Play.**
- A Ranked / Casual switch above Play, remembered per device. Guests see both, and ranked guests are a fixed
  1000 and unsaved, as today (in the iOS app, since 2026-11-22, the first online Play makes the device's own
  account instead, rated and saved; see "One account in the iOS app").
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
  - no rating cost (Jerry 2026-11-27: "For joiners that come mid round, can we not punish them if they join a
    table that has bad cards?"): the round joined mid-way is unranked for the joiner, and leaving or abandoning
    it carries no leaver cap into their next rated round; from their first rated round on, the leaver rules
    apply as to anyone;
  - copy: "Stay until this round ends, or wait 1 minute to play again."
  - told at the seat (Jerry 2026-11-27, joiner mock option B: "Yes recommended is good"): the moment a seat
    becomes yours mid-round, one table toast names it, "You took Bot 2's seat · unranked this round" (a casual
    table: "You took Bot 2's seat"), the previous holder named as the table names them, held until you play
    your first card (at least 4 s); for that round the ⋯ menu's mode word reads "Unranked this round" in
    place of the gold "Ranked". The round end's "Unranked · joined mid-round" and the leave sheet's line are
    unchanged. The state frame's optional `took_seat` carries the name: the holder before you, from any
    mid-round claim (an open-table join, or a by-code take of a bot's or a dropped player's seat), sent only
    during that round. It is presentation only; `joined_round` alone sets the menu word and the rating and
    leave rules. The hold lives in the toast store, so How to play and back keeps it; the first card, the
    round end or leaving the table lets it go, and a newer toast supersedes it (the newest wins; the line
    is not brought back over or after it). No new surface or message.

**Section 4, connection.** One "Reconnecting…" pill, Retry after 10 s, a full-screen state after 30 s (when the bot takes a dropped seat), and a
bad code shown inline under the code box. The 30 s is one window on both sides (Jerry 2026-11-26, option B):
`LOST_AFTER_MS` in `ConnectionPill.tsx` equals the server's `TAKEOVER_AFTER`, pinned by
`server/tests/test_client_server_constants.py`. Each side counts from when it sees the drop; at a table this device
sees a silent drop within one missed pong (`TABLE_PING_MS` + `TABLE_PONG_MS`, 14 s at most), so the full screen
comes 30 to 44 s after the network goes. One wording. The same pill, in the same place, says "A bot holds your
seat · I'm back" once the socket is open again while a bot still plays your seat (simplification 4, below).
The pill shows at a table or in a game. On the Play tab with no table the presence line is the one status:
"Connecting…" until the socket opens, then the counts, or "Offline" once the app's Play plays on this device
(a browser stays on "Connecting…"); the 30 s full screen still comes (Jerry 11-15).
Leave game while the socket is down, or one whose socket closes before the server's answer, goes to Play at once;
the next socket takes this page's own seat back by its token and leaves it (`ws.ts`, no new send site, up to three
sockets, also after a reload or relaunch within 90 s),
so the bot covers the seat at once instead of after a dropped seat's 30 s and a ranked Leave counts as one.

**Section 5, tabs.** The same three tabs (Play / Leaderboard / Me) on phone, iPad and desktop; a viewer the
Collection is shown to has four, Collection third (Jerry 2026-11-26, below). Stats and
Games become a switch inside Me. The Leaderboard is the phone's column at every width, centred and capped like
Me; your own row keeps "(you)" in view when a long name truncates (Jerry 11-15).
The wide layout (700px and up) has no top bar strip: the tabs float as the glass pill group centred at the top
and the account chip at the top right, over the page background, and no tab shows a corner wordmark (Play's page
carries the 升级 SHENG JI title). Jerry 2026-11-26: "can we just remove the top bar entirely? and we can keep the pills".
It opens on This week, or on All time when nobody has played a ranked round this week yet, until the viewer
picks a period (Jerry 2026-11-24: "default to global when it's empty"; no extra Play button). Each row ends in
its rating on both periods, with no places moved this week (Jerry 2026-11-27: "The up down is not that
meaningful"), and the top three's ranks sit on gold, silver and bronze discs on both periods (Jerry 2026-11-24).
A page is one layer on the page background at every width: no raised card behind How to play (which keeps its
two columns from 900px, a sideways phone excepted), Support, Privacy or Terms of use. Real surfaces keep theirs: the table panel, sheets and dialogs,
grouped list rows, Me's stat tiles and How to play's diagrams (Jerry 11-15).
The phone lobby is portrait (Jerry 2026-11-15: "Yes let's lock lobby to portrait"): the app locks every lobby
screen (Play and its panels and sheets, Leaderboard, Me, How to play, saved games, Support, Privacy, Terms of use) to portrait
on an iPhone and the table to both landscapes; the web cannot lock, so a phone held sideways (under 501px tall)
shows the same portrait column, centred under a capped tab bar, and scrolls; the Play tab's preview gives way
there, so Play and Duo sit clear of the tab bar in the first view. The lobby has no sideways design
of its own; the table keeps its landscape layout.

**Section 6, settings.** One settings list (Coach, Sound, Haptics on native only, How to play) in both Me and
the ⋯ menu. "Kitty 8 cards" moves out of ⋯. Me alone adds a Language row before How to play: its value is
the choice, and a tap opens the choices in place under it, as Edit name opens its field (Follow system,
English, 简体中文, 繁體中文, in the app and on the website alike). Follow system is the default: a device or browser
whose first language is Chinese reads it in its script (Hant, TW, HK and MO read 繁體中文 in Taiwan usage, every
other Chinese tag 简体中文), every other reads English. No sheet, no new surface. For a viewer the Collection is
shown to, Me also adds **Show companions at the table** (牌桌上显示伙伴 / 牌桌上顯示夥伴) after the switches, before
Language (Jerry 2026-11-27: "i dont really like the show at table toggle in collection- should it be under settings?"
then "yea"); the ⋯ menu has neither row.

**Section 7, guest name.** One name control: the chip opens the same edit sheet on every tab. Me shows the
guest's name and initial with "Guest · not ranked" (cut to "Guest" by the copy rule; the iOS app's own account
reads "On this iPhone only" there, "On this iPad only" on an iPad, since 2026-11-22).

**Section 9, timers.** One ring component with one rule, including a thin ring on other players' turns.
**The ring shows the seconds left as a number** (Jerry). Your own ring runs the whole move time. The Your table
pill shows the bots' countdown, not elapsed time (the queue strip until 2026-11-14, simplification 6).

## Not decided (do not build)
- Section 8, game over / Next game.

## Offline (Jerry 2026-11-14: "we should just keep offline, dont go online")
- **App only** (Jerry 2026-11-16: "Let's remove it from web"). Every offline entry below shows only in the iOS app, detected by `isNative()` in `native.ts` through `offlineOffered()` in `components/offlineGame.ts`. A browser has no service worker, so its offline play worked only on a page already open, and against SmartBot rather than the app's release bot. In a browser the Play tab's line reads "How to play" alone, the full screen offers Retry alone, Play with no connection keeps its own controls disabled under "Connecting…", and the on-device server chunk is never fetched. `?offline=1` still opens a page offline (tests and development).
- With no connection, Play opens your table with 3 bots on the device: the same panel, "Offline · not rated", Casual only (Ranked disabled with "Ranked needs a connection"). Duo, rooms and chat are disabled with a one-line reason. The offline table is the panel's `offline` kind (`offlineModel` in `queue/tableModel.ts`, drawn by `TablePanel.tsx`), and the offline Play block draws the online Play controls (`ModeSwitch`, `PlayRow`, `PresenceLine` in `queue/Ranked.tsx`, `CodeRow` in `Lobby.tsx`) disabled.
- The presence line becomes a grey "Offline · you'll play the bots on this device".
- **An offline game stays offline.** When the connection returns there is no automatic switch and no mid-game prompt. The game continues on the device. `offlineGame.goOnline()` runs only once the offline table is left (`components/OfflinePlay.tsx`). After you leave the offline table, Play is online again as normal, in place (simplification 7).
- The section 4 full-screen connection state offers "Play offline with the bots" next to Retry, replacing today's silent switch inside "Play bots" (`Lobby.tsx:244-247`).
- Offline games in local stats: not decided.
- Offline games do NOT count in Me's stats (Jerry 2026-11-14).
- The iOS app with no network at launch opens the Play tab's offline state, not a separate start screen (Jerry 2026-11-14: yes).
- Timer rings: the seconds number must not touch or overlap the ring stroke (Jerry 2026-11-14).

## Play nearby (Jerry 2026-11-19: "the existing Play offline → the offline table panel … gets a Nearby switch"; 2026-11-20: "Let's build UI")
Behind the nearby flag (`offline/server/nearby/flag.ts`), decided at run time by the app binary alone (`nearbyGate.ts`): on only where the ShengjiNearby plugin is registered and its `capabilities()` say reviewed (the App Store build), Beta or the device test's Debug build. A browser sees none of it: the live site carries the code, but the nearby UI (`nearbyUi.tsx`) is imported only after that answer. The App Store build has Play nearby and none of the test tools below: its plugin reports no `logFile`, `chaos` or `debug`, its bundled page is built without them (`VITE_SHENGJI_APP_STORE=1`, `testTools.ts`), and `web/ios/flavor_guard.sh` refuses an App Store archive that has them. The device test's soak rows (Autoplay, Chaos, Clear log file, Upload log now, Copy soak summary) need the plugin's `logFile` as well. In the Beta all soak and log rows (Copy log, Clear log file, Upload log now, Autoplay, Chaos, Copy soak summary) are behind the hidden switch (five taps on the ⋯ menu's table code); while it is on, a dot after the code marks it (no text; its accessible name adds ", soak tools on"). The log file and its upload run wherever the plugin reports `logFile`, switch on or off; the first upload goes a minute after the page's start. While a soak runs, its controls (Autoplay, Chaos, Stop soak) are reachable from every page, not only the table's ⋯ menu: in the device test inside the existing Log pane, in the Beta behind a pill in the Log tab's corner (labelled Autoplay or Chaos, whichever runs) that shows only while the soak runs. Stop soak turns both off and drops the kept soak, so a relaunch does not resume it. The pill and its pane are the Log pane's own layer (`nearbyDebug.tsx`), not a new surface. App only.
- **Entry: Play offline, unchanged.** The offline table panel (`offlineModel`) gains one row, a **Nearby** switch in the setting-row style (`.q-wait.tp-switch`), label only. Surfaces added 0, removed 0. The tag stays OFFLINE.
- **Host.** Off is today's solo table. On: the first time, the iOS Local Network alert (the audit's `NSLocalNetworkUsageDescription`); then the panel is the nearby lobby (`nearbyRoomModel`): the three bot seats become open seats, a code row with the 5-character code and no Invite link, the Bots row (the host picks Beginner, Standard or Advanced with the same select, from the level the solo table had; joiners read it; the bots that fill the open seats at Start, or cover a dropped seat, play at it), no Chat row (nearby tables have no chat). Off again (before anyone has joined) is the solo table; once someone has joined the switch is locked and Leave ends the table for everyone. Don't Allow: the switch falls back off and the panel's one status line reads "Nearby tables need Local Network access. Open Settings" (the link opens the app's page in Settings).
- **The host starts; a guest's Ready is a signal, as at an online table (Jerry 2026-11-26, Section 1; this replaces "Start = wait for ready", where each person's Start was their ready and the table began once all were in).** The host has Start with bots (`table_start_now`), always enabled, and "n of m ready" over its guests once someone has joined; a guest has Ready (its ✓; a second tap takes it back) beside Leave, under "Waiting for Mei to start". The host's Start takes everyone seated, Ready or not; a guest whose link is down does not hold it (a bot covers its seat after its window and the guest can come back by token), and a seat whose hold ran out is free again. Nothing starts because every guest is Ready. From the moment a second person sits, the bots' ring runs 60 s (matchmaking.py `BOT_FILL_SECS`); when it runs out, bots take the open seats. The host alone has no ring: the table waits for people, as the online Wait for people does. There is no host migration (it would copy every hand to another phone), so a guest never becomes the host and its Ready can never become a Start.
- **Joiner.** The normal code box (online Play, or the offline Play state, where the box is live with nearby play) takes 5 characters only when nearby play is offered; Join enables at 4 (online) or 5 (nearby), and the nearby line under the box appears at the 5th character. Join → the alert (first time) → the existing join-code panel, tag OFFLINE, title "Join K7Q2M", one status line "Looking for the table…" → the seat picker (every open seat a pick, the host's partner seat first) → Join → the nearby lobby, ready as above. Not found (after one automatic retry): "No table nearby with that code" and the primary reads "Try again". Denied: back at the code box, code kept, with the denied line; coming back from Settings retries on its own. "Turn on Wi-Fi to play nearby" shows only on a real Wi-Fi failure; nothing checks Wi-Fi first.
- **Joining a game in progress, as the online by-code join.** With Allow joiners on, a look after the start lists the people and the seat picker offers every seat a bot plays (a dropped person's seat once its 60 s hold has run out, and a seat left by choice at once: the hold is for drops); Join takes it over at once, mid-round, with the seat's hand, and the bot stops playing it ("Mei took Bot 2's seat"). Its token resumes it like any nearby seat. Only the seat's token takes a held seat back; a join without it is a newcomer from whatever address it comes, so a phone that lost its token (after a Leave, or past its two hours) gets a bot's seat, or its own once that seat may be taken over, and nothing with Allow joiners off. No such seat, or Allow joiners off: "That table is full". A connected person's seat is never offered.
- **The ⋯ menu at a nearby table** shows the 5-character code in the online code row, without the Invite link, to the host and every joiner, so a phone that dropped out can come back by it; the host also has Allow joiners there.
- **The link dot.** At a nearby table only, a dot in the header's left group: green while linked (a joiner: its link is up and the host has answered its resume; the host: every person's seat connected), amber and pulsing while a link is made again (no pulse under reduced motion), grey once the host is gone. No text; its accessible name is the pill's words. A joiner's new link counts as connected (pill gone, moves enabled) only once the host has bound the seat and sent its state; when the phone's network comes back, a fresh attempt starts at once. A move's answer that takes a moment over the radio is not a stall: Play says Sending… only once the answer is 1.5 s late. With a Wi-Fi network joined the link uses only that network (peer-to-peer Wi-Fi stalls while the radio also serves it); with none joined (the subway, airplane mode with Wi-Fi on) it runs peer-to-peer. A peer-to-peer link keeps the joiner's browse running and, during a game, a tiny keepalive both ways every 250 ms, so it does not go silent between moves. Repeated taps of Next round send it once.
- **The one copy-rule exception**, listed in `queue/copyRule.test.tsx` (`UNDER_CONTROL_EXCEPTION`): under the code box, for a nearby code only, either "This is a nearby table. Sheng Ji will ask to use your local network to find it." (until iOS has asked once) or the denied line with its Open Settings link. Nothing else sits under a control.
- **The move clock, as a timed online room.** With two or more people at the table, a present player has 60 s for each bury, play and round-end Next; then the bot makes that one decision, and after two in a row (or three in a round) the seat is away until the player taps back (the existing ring, Away tag and held pill). A player whose link drops mid-decision finds the clock where it stood at the drop when they are back (time away counts for nothing, so no strike comes of it), with at least 15 s left. A pause of a phone's own page (its JS frozen, or in the background) is not counted against anyone: the host's pause stops every move clock, the declare window and a dropped seat's wait for its bot, and ends no link; a joiner's keeps its link, and the joiner's 65 s "host left" window counts only its own awake time. Alone with bots there is no clock.
- **Lobby seats.** A seat whose phone dropped in the lobby is held 30 s for its owner (longer than a stuck link takes to come back), then opened again; a phone back with its token resumes that seat; one back without it takes a free seat, and its old one opens after the 30 s. While a seat is held the table does not start without its person: a Start they tapped before the drop still counts, and otherwise the others wait for them or for the hold to end. A new seat (lobby or mid-game) whose phone never shows the host it has the seat's answer (its socket's next ping after the answer) within 20 s, the answer lost on the way, is given up as by a Leave once its link is gone, unless the phone took it back by its token: no seat is held for a phone that never had it. Leave closes the link only after the host has it: a Leave tapped while the link is down, or one whose link goes before the host's answer, goes out on the next link as it opens (for up to 30 s), so the seat gets the bot at once instead of a dropped seat's 60 s; the page stays in the lobby and never sees that link's frames.
- **Game end: none, as at an online table** (the final decision of 2026-11-14, "keep games endless"; server.py's tables and the nearby room both play with no games-to-win). A team holding A that wins its round wins a game: the round end says so, the HUD's games score counts it and the levels start over, and Next goes on. The table ends only by the host's Leave or the host's window, so the joiner's token is forgotten then, not at a game over.
- **Drops and the host away.** A joiner who drops rejoins by its resume token with backoff; meanwhile its seat shows Reconnecting and the bot covers it after 60 s (the existing flow). A joiner that stops answering the link's ping for 20 s counts as dropped. The host's app keeps its table while iOS allows in the background and advertises it again with the same code on return; joiners rejoin by token. After 60 s away the table ends for everyone, and a joiner sees "The host left. The game is over." on the existing full-screen connection state, with Leave in place of Retry.
- **A joiner's app restarted.** The seat token is kept on the phone by the table's code (`nearbyJoin.ts`, one per code, the newest four, two hours from its last write) and goes with the code box's Join of that code, so an app iOS ended in the background, or one reopened, types the code and takes its own seat and hand back when Join is tapped on the picker's first glow. That glow is the held seat: the peek carries the kept token, and the host answers that phone alone with the seat the token resumes (`held_seat`, or none when it does not know the token), never the token or anyone else's seat; the picker starts there, and an untapped Join resumes it. With no held seat it starts on the host's partner seat, else the first free one. An older host gives no `held_seat`: the picker starts on the seat kept with the token only while the peek shows it open (a listed seat is someone's, and a name cannot tell whose), else on the default open seat, and every Join with a token names the glowing seat as the choice, so the host resumes the token's seat when it glows and moves the phone to the glowing seat otherwise. Either way, what glows is where Join puts you. A seat the player taps is a choice: when it is free the held seat moves there (before the start) or is given up to its bot and the tapped seat taken over (in a game), so the phone plays one seat; a tapped seat no longer free resumes the held one. The picker draws the seats around its first glow while a tap moves you, so the tapped seat glows where it was tapped. It is forgotten on Leave, on the host's end of the table, after the host's window, and at game over; a token the table does not know joins as a newcomer, and the new seat's token replaces it. When every seat is taken (its own is held for it), the table answers full and the join sends the kept token once on a new link with no seat picked; the host seats it by the token, and a refusal is the full outcome and forgets the token. A seated phone's resume with a token the table no longer knows (its seat was taken over, or freed) is refused, never seated elsewhere: the phone forgets the token and shows the table's seats again, so the player picks one. A code is drawn at random for each table (about 1 in 33 million to repeat), so a kept token reaches another table only by that chance, and is a newcomer's there. Never in the log, never sent to the game server.
- **Reused, unchanged:** Play offline, the offline panel frame, the join-code panel and its seat picker, Reconnecting…, A bot holds your seat, the full-screen state. `flows.test.ts`: no new surface; the joiner's peek and join are sent from `nearbyJoin.ts`, the code box's nearby half, listed in JOIN_SITES beside `codeJoin.ts`; the leaves from `OfflinePlay.tsx` and `ws.ts` (LEAVE_SITES).
- **Accepted risk: a 5-character code** (Jerry 2026-11-20: "stakes are low for a friendly game, you don't get rating from this"). The code keys the link (PBKDF2-HMAC-SHA256, 150,000 iterations, per-table salt). 5 characters from the 32-character alphabet are 25 bits, under the audit's 30-bit floor. Estimate: an outsider who records a game's radio traffic could try every code offline in roughly 10 GPU-minutes (one high-end GPU; half that on average) and then read that recorded game's hands. Accepted because nearby play is unrated, casual and in person. Live play by the players is not affected; the risk is to a recording read afterwards.
- **Never online.** Nearby frames go phone to phone only; telemetry is off during a nearby session (`NEARBY_SESSION`), which only adds to the offline digest's counts, and the page does not switch online while one is live.

## Copy rule (Jerry 2026-11-14: "i dont think we need the metadata in play page … take a pass to minimize the metadata / subtexts")
- Switches and rows take a label only, with no sub-line: "Ranked", "Allow joiners", not "Rates signed-in players" or "On by default: …".
- No explanatory notes under controls on the Play page. At most one short status line per panel, and only when it changes what the player does next (a timer, "1 of 2 ready", the leave cost).
- Drop kickers, hints and repeated context where the layout already says it (e.g. "Tap a green seat to move" once at most, "Others can join as they arrive" not at all).
- Explanations belong in How to play and the coach, not under controls.
- **The panel title (Jerry 2026-11-26, decision mocks section 2).** Every panel you sit at is titled "Your table" (我的牌桌), a Duo, formed or still holding the partner seat, "Your Duo" (我的组队); this replaces "You and Alice" / "You, Alice and Li", which named the seated people the seats already name. The Join panel keeps "Join Alice", where the name is the news; the offline table keeps "You and 3 bots". The live region's sentence still names the people (`tableText.ts` `announcement`).
- Jerry's examples of too much subtext (cut entirely): "Tap a green seat to move", "Jerry opened this table", "Invite by link or code", "Bots sit in empty seats". A panel is its title + seats + at most one live status (a timer / "1 of 2 ready") + buttons.

## Every table has a code (Jerry 2026-11-14: "for Play → your own table on ranked, i think we can also show the room code and the create room settings similar to what we do for casual rooms")
- When Play opens your own table (ranked or casual), it gets a code with Invite link and the same table settings a created room has (the Allow joiners switch; Starting level for the opener). This reverses section 1's "no code for Play tables yet". Since 2026-11-22 (Jerry, the "Your table" declutter, option B: "table settings sounds good - B lets do it") the code and its Invite are one control in the panel: the code on the left, a share mark and "Invite" on the right, one tap shares the link (or copies it, then reads "Link copied"); the ⋯ menu keeps "Invite link". A nearby table's code stays the code alone.
- The invite's message says what the table needs, in the app's language, the link after it (Jerry 2026-11-25, "三缺一" option B): "We need a 4th for Tractor. Code FW4X" / "三缺一，来打升级！房间码 FW4X" with one open seat, then two open, three open ("Play Tractor with me?", also the plain ask), and "Be my partner" only from the Duo opener whose partner seat is held. Every seat shares the table's one code, whose join takes a held partner seat first, so the message counts what that join takes: a stranger at a Duo table sends the plain ask; the ⋯ menu mid-game sends the plain ask, since a bot's seat may not be open. The same Invite control and share sheet send it. The link's preview is the table's own while a join by that code can enter it: title "Table FW4X · 1 open seat" (牌桌 FW4X · 三缺一 for a Chinese asker), the message as its description, and a 1200 × 630 card of the felt, the code and four seats with initials only (a bot as the bot mark, a departed player's claimable seat as empty), the opener's team in blue, a seat the code's join takes a dashed +. A person the Collection is on for shows their companion's round portrait in the seat instead of initials (2026-11-27: "The invite didn't show the companion"; pre-rendered PNGs, one per look, in `server/shengji/api/portraits/`); a guest, a bot and a look with no portrait keep the initial. A full, closing or ended table, an unknown code and an image URL made for an earlier state keep the site's own preview.
- **"Your table" declutter (Jerry 2026-11-22, option B), on every panel kind built on `TablePanel.tsx`.** Two or more settings fold into one "Table settings" row (`TableRows`, in place in the panel: no new surface, closed until tapped, its chevron turning down while open). The row shows its current values at its end, dimmed, as a select shows its value ("Level 2 · Standard"; on the same line, not a sub-line under it). Open, it holds Starting level, Bots, Allow joiners, then Wait for people (selects, then the switches): the opener's controls, or the values read-only for everyone else. Since 2026-11-24 (Jerry, App Screens Review item 10: "OK as proposed") every switch folds the same way on Ranked and Casual: Wait for people joins the fold (it was its own row beside the ring), so a ranked opener's Allow joiners and Wait for people are one Table settings row with no values at its end. A panel with one setting shows that row itself (Bots offline and at a nearby table). The Chat row ends in the list chevron, so it reads as a row that opens, not a text field; Start and Leave are unchanged. The queue's panels (Join, own, shared) carry no mode tag, because the Ranked / Casual switch above them says it; the offline panels and a code's Join panel keep theirs. The VS between the team columns is gone (the gap divides them), and an open seat is its dashed box with one "+" (its label still reads "Open seat, your team"); a dropped player's seat in a Join panel keeps "Alice (away)".
- A table is a table: "Create room" is no longer a separate path, because Play gives you a table with a code. Keep "Create room" only if Jerry wants it.
- Ranked tables: Starting level is fixed at 2 for rating fairness (Claude's assumption; confirm with Jerry).
- Server: a lone queue entry's own table must become a real table with a code. Today a lone entry has no server table (matchmaking.py, table created at 2 entries), so this is a follow-up to the room-table-server PR.

## Final decisions (Jerry 2026-11-14)
- **Game over:** keep games endless. When a team wins a game, the round end says so ("You & Alice win the game"), with Next game / Leave; the HUD shows the games score (e.g. "Games 1–0") after the first game won; delete the unreachable game-over card (`RoundEndModal.tsx:131-150`).
  Since 2026-11-24 (Jerry, App Screens Review item 14) a game your team wins is felt apart from a won round: the
  success tap, then a medium impact (`haptic("game")`, off with the Haptics setting), and the round end's crown
  arrives once with a short flash when the result comes in live (a table opened onto a finished game, as on a
  reconnect, draws it still, and so does Reduce Motion). No new text.
- **Join panel:** drop the leave-cost line entirely. The cost appears only in the Leave sheet.
- **Create room:** dropped entirely. Every table Play opens has a code with Invite link and Allow joiners; the Create room row and flow are removed.
- **Ranked tables:** start at level 2, fixed, with no starting-level row. Casual tables keep the opener's Starting level.
- **Bots: Standard / Advanced (Jerry 2026-11-20: "Maybe a dropdown for bot level - standard, advanced"; "im good with standard / advanced"):** a casual table has a "Bots" row after Starting level in the table's settings rows, inside Table settings since 2026-11-22 (`TablePanel.tsx` `TableRows`; no new surface; it followed Allow joiners until then), the same select as Starting level: the opener picks Beginner, Standard or Advanced (in that order; Beginner added 2026-11-24, Jerry: one more option in the same select, no new surface), everyone else reads the value. Label and the three option names only ("Beginner" / 入门, "Standard" / 标准, "Advanced" / 高级). Standard is the relaxed level: the served declare and bury, card play by the S136 search-free scorer with near-best noise (Jerry 2026-11-20: "Ok move scorer and noise then"). Beginner is the same with wider near-best noise (`relaxed_play.build_beginner`, the same package). Advanced is the served bot. A new casual table starts at Standard (one constant, `CASUAL_BOT_LEVEL`). It is set before the game and fixed once the game starts (a room refuses it, as Starting level). A ranked table has no row and the server refuses a change; its level follows the people's ratings, unseen (Jerry 2026-11-23; Beginner 2026-11-24): the two bots opposing the people play Beginner when every person at the table rates 800 or less (a new account starts at 800 and a guest counts 800, Jerry 2026-11-24), Standard when every person rates 1000 or less and not all 800 or less, Advanced otherwise, and a person's partner bot is always Advanced, so people on both teams meet Advanced everywhere. Beginner is Standard with wider near-best noise in its card play (`relaxed_play.build_beginner`, the same S136 scorer package); it is a ranked-only level, never a casual table's Bots value. It is chosen when the game starts and again at each new game at the table (after a point is scored), from the ratings after the last round's rating write. Inside a game it only rises: each later round re-reads the people's ratings before its first card and plays the higher level once one has crossed its line (Jerry 2026-11-25: "let's recheck at boundary and fix bot to adapt strength"), never mid-round, and a rating that falls back does not lower it before the next game; a newcomer who takes a Standard seat makes that team Advanced, and a new person or a different account on the people's team (a handover, a claim, a resume as another account) rated above the table's line (800 at Beginner, 1000 at Standard) makes the table Advanced for the rest of the game; a reconnect by the same account keeps it. No frame, label or setting shows it; each bot seat is rated at its level's anchor (`ratings.BOT_ANCHORS`, Jerry 2026-11-24): Beginner and Standard 1000, Advanced 1059 as opponent and as partner (Standard plus the measured 0.47 levels/round gap at 125.5 Elo per level/round); a guest seat counts 800. The offline table has the same row (Jerry 2026-11-21: Standard by default offline and at Nearby tables, the host can switch): you pick until Start, it is the only settings row there (`offlineModel`), the next offline table opens at the level picked last, and the app's offline bot plays it (`web/ios/pybot/offline_bot.py`, the server's three room bots; Beginner there from build 11). Casual default Standard, both levels offered (Jerry 2026-11-20: "standard default in casual and standard can be in offers"): Play seats strangers at, and offers open tables of, either level exactly as Allow joiners says; a stranger seated at a waiting table plays at that table's level, the opener's, as for Starting level. This replaces the "Relaxed bots" switch (off by default) of the same day.

## Duo is a table (Jerry 2026-11-14: "it's awk to be in a duo room and play room at the same time"; "A duo should be paired"; panel, not popup)
- Duo opens your own table (the same inline panel as Play), with the partner seat held for your friend. There is no separate Duo code or Duo bar: the table's code and Invite link are the Duo invite, and a code joiner takes the held partner seat first.
- A Duo stays paired. After Start, or when Play matches you, the pair moves and is matched as one, as Duo is today, and a ranked Duo is rated as a pair. One Leave, on the panel, ends the Duo for you; your partner keeps the table.
- The table is an inline panel, not a popup. Popups are only for decisions (Leave, take a seat, a Duo invite).
- Built (client): the Duo sheet, the Duo chip and the separate party code are removed (`?party=` links read as `?code=`). Between games a formed pair shows one row, "Duo with <partner>" and Leave (`party_leave`), to both members; the leader keeps Play and Duo under it.
- Rejoin Duo (Jerry 2026-11-27: "When I left Duo accidentally, I had no control to rejoin"; then "It should just be 'rejoin duo' and 'leave duo' options in play. Not play / duo"; mock https://claude.ai/artifact/1CJkkWK9LuHrGSf2EAq27w): while you are in a Duo between games, Play's place holds one plain line, "Duo with Sk" (和 Sk 组队), then two buttons in place of Play and Duo. While the server keeps a Duo seat for you they are "Rejoin Duo" (gold; 回到搭档桌 / 回到搭檔桌), which takes that seat back in one tap, and "Leave Duo" (离开搭档 / 離開搭檔). With nothing kept, the leader's gold button is Play, which queues the pair as before, and the other member has Leave Duo alone. Leave Duo goes through the one Leave sheet and sends `party_leave`, which ends the pairing. The separate "Duo with Sk · Leave" row is removed. The Ranked / Casual switch, the presence line and the code box stay. Three kinds of seat are kept: your Duo table, left while still alone at it (Leave or a drop), held with its code, settings and chat for 5 minutes, the window an empty casual room keeps a seat (its code finds no table for anyone else meanwhile; Rejoin Duo and Leave Duo show with no line, and that Leave Duo's `table_leave` gives the table up); a partner's seat that the opener's table holds again; or, while the Duo stands, your seat in the Duo's casual room, left by choice (the seat-back rule; a ranked room keeps its bar). Rejoin Duo is its own reclaim (`table_join` with `rejoin`), never a plain join: it takes back that one seat in that one place, the room being the one this Duo last started together, and when the seat has gone (taken by someone else, even while the tap was on its way) it joins nothing and the Play tab quietly shows the Duo's Play again; a kept partner seat that someone else takes is withdrawn at once. Server: `matchmaking.py` `_keep`, `_back`, `_rejoin`, `_revalidate_kept`, `Party.room`, `server.room_back`. Client: `queue.rejoinDuo` (`queue/store.ts`), `DuoBlock` in `queue/Ranked.tsx`.
- The Duo's leader owns its table (2026-11-26, the owner-starts rule in Section 1, Ready a signal; this replaces the same day's "the leader's main button is Waiting for Alice until her Ready", which replaced "both tap Start, then the leader's Start with bots while the pair searches" of 2026-11-25): the partner has Ready (its ✓; a second tap takes it back) beside Leave under "Waiting for Jerry to start", and the leader's main button is Start with bots, always enabled, the same button and ring as a single at its own table, in ranked and casual (a ranked Duo gets its rating-matched bots). The pair is matched with strangers whether or not the partner is Ready, as before; there is no "Finding a table" state and no "N of 2 ready" line. Only the leader starts with bots; a partner who is reconnecting holds the leader's Start ("Your partner is not in the lobby."). Leave stays the way out.

## Decisions 2026-11-14 morning (Jerry)
1. Duo flow as mocked (core.html section 5, "Duo: one table, paired"): approved, build it.
2. Allow joiners is the opener's switch only (server and client); others see nothing (copy rule).
3. Offline copy: plain "Offline" (cut the subtext); "Offline · you'll play the bots on this device" and "Ranked needs a connection" are dropped.
4. Round end: the top stays minimal (the title, the ladder, one status line, buttons in a row), and Details holds the kitty (cards, points, multiplier) and the last trick played. Keep that detail. Since 2026-11-26 (Jerry, round-end mock D7) the row is Next round (widest, gold) · Details (compact, the raised neutral) · Leave game (red label); the centred "Details ⌄" toggle is gone. Details swaps the kitty and the last trick in for the two lanes, in the same cell, and the button reads Levels to swap back. Each view is as tall as its own content (Jerry 2026-11-26: "The end-of-round card doesn't need to be the same size for both views"), so the card grows or shrinks as it toggles, its height gliding over 180 ms (`--dur-resize`), at once under Reduce Motion; the view sits a little further under the title than the card's own gap (14 px on a phone; Jerry 2026-11-26 "just a bit more spacing between the levels and the title"), the same for both views, and the view, the points bar and the status line follow one another at the card's own gap, the Details content sits straight on the card like the lanes, with no box of its own, the Details/Levels button keeps one width, the whole card stays on screen sideways (844 × 390) with Details open at any card count, and the card no longer widens. The buttons sit the bar's 14 px rhythm below the status line. In Details the two labels share one line; the kitty and each seat's play are overlapped fans on one row, the seat's name under its fan and the winner's outlined; the card width and overlap step are solved at run time from the panel's measured width and the counts (cards a seat, kitty size), so 1 to 12 cards a seat never wrap or overflow: the step shrinks first, to the smallest that still shows each rank, then the card, then the step again at the smallest card. The bonus, when the attackers took the last trick, is one line across the panel showing its sum, "We won the last trick: 5 × 2 × 2 cards = +20" (the buried points × 2 × the cards counted, as the server scored it); where the sentence would not fit on one line it is the sum alone. The phone card is 440 wide to hold the three buttons and the row. A guest at a ranked table reads "Sign in to be ranked ›" under the result line, the same words as a link that opens the one identity sheet, drawn inside the round-end dialog (Jerry 11-20 plain text; a link since 11-22, so guests at a table reach sign-in; the "Guest" box stays gone; an account, one signed in on this round end too, sees no line); a seat taken mid-round reads "Unranked · joined mid-round" in the same place, because each explains the missing number (Jerry 11-15).
   Since 2026-11-24 (Jerry, App Screens Review item 3, design B: "B looks good for round end, replace text. We don't need level restart at 2") the result sentence ("They took 35 of 80. We go up 1, to 3.") is gone: a rank lane per team, 2 to A, labelled Us / Them in its team's colour, shows the old level outlined and the new one filled, and the attackers' points sit on a bar in their colour with the 80 mark. The status line is "Next banker: …" with a rated round's change. A won game's winners end past A on the crown and the button says Next game; "Levels restart at 2" is not said, and "Games: Us 1 · Them 0" counts the game. The new level fills in once (opacity and scale, `--dur-fast`) only when the result arrives live, and not under Reduce Motion. The result carries only the new levels, so the lanes read the old ones from the table's last state before the result; a table opened onto the result shows what the result implies (the bankers' trump rank, an unchanged level) and fills only the new level where the old one cannot be known. It fits an iPhone SE held sideways (667 × 375) without scrolling; in a landscape browser with its bars showing (about 326 tall) the ladder tightens and a won game keeps only the crown at the lane's end. In forced colours (high contrast) the ladder draws its own system colours: inactive ranks bare, the old rank in a thick dashed CanvasText frame, the new rank in Highlight; the track framed in CanvasText, its fill in Highlight, the 80 mark in CanvasText.
   The App Store rating ask (Jerry 2026-11-25, growth mocks section 1, option B): in the iOS app only, about 1.5 s after the round-end card of a round your team won appears, Apple's own rating sheet (StoreKit `requestReview`, through the shell's ShengjiReview plugin) is asked for at the 2nd ranked win or the 5th casual win (online casual, offline and nearby rounds are casual), whichever comes first; never in the app's first session (a session starts after 30 minutes away), never after a loss, never once the card is gone (Next dealt), and at most once per app version (`reviewPrompt.ts`, its counts in the native store that the hosted and bundled pages share). No prompt, text or control of ours comes before or with it (guideline 5.6.1); Apple may show nothing. No new surface: the sheet is Apple's.
5. The guest line "Playing as a guest · Sign in to be ranked" stays on the website. In the iOS app with device
   accounts on it does not show (2026-11-22); with them off on the server, it stays.

## Simplifications approved (Jerry 2026-11-14, "Yes for all the simplification paths")
1. **One invite path.** One link kind, `?code=`, opens Play with the Join panel for that table, and so
   does every code typed in the code box (Jerry 2026-11-15), a game in progress too: its title
   ("Join Jerry"), the seats with yours glowing, Join and Not now. You glow in the seat Join takes: in a
   room the first bot seat (else a dropped player's), and tapping another bot seat moves you there; at a
   queued Play table the seat its rule gives a code join (a Duo's held seat, else the first open seat,
   partner first), which no tap moves. The rest show as they stand (names with their Ready, open seats, a
   Duo's held seat as "Partner"). Nothing joins until Join is tapped. `?room=` and `?party=` links (and the iOS universal
   links) read as `?code=`; a `?name=` is dropped. A guest is never asked for a name: Join uses the random
   name the chip shows, editable there. A full table shows the same panel, "Table is full" and Join
   disabled. The seat picker (`SeatTakeover`) and the "Table is full" card are removed.
   - Taking a dropped player's seat stays an explicit choice: in the Join panel their seat reads
     "Alice (away)" (glowing when it is the seat chosen, which it is only while no bot seat is free), and
     Join on it opens the "Alice dropped out. Take their seat?" confirm first.
   - A link opened while you sit at another table shows the Leave sheet first; your own table's link
     changes nothing. The code box no longer joins a room at once: a code costs one more tap, Join, and
     you see who is there before you sit.
   - Return to your seat (Jerry 2026-11-26, flows audit simplification 1): your own table's link, its
     code typed again, or a reload takes you straight back to your seat with no Join panel, at a waiting
     table and in a game: a room seat by the device's resume token (the link waits for it; a refused
     resume goes on to the panel), a waiting-table seat by the device (its peek marks the seat `you`).
     A reload keeps the name the table shows, so nobody hears "X left the table." A Leave stays a leave:
     it forgets the seat, and a seat left by choice reads as the bot's seat in the panel, under the bot's
     name, never the leaver's.
   - Seat back after Leave (Jerry 2026-11-26, decision mocks section 4, option B): at a casual table
     reached by code or link, someone who tapped Leave gets the Join panel with their old seat glowing
     (the bot holds it meanwhile; the peek marks it `yours` and Join takes only that seat); one tap, Join,
     takes it back. Leaving was deliberate, so it is one tap, not a silent resume. Ranked tables and seats
     taken from an open table keep today's bar and cooldown: the ranked leaver's seat is not offered.
   - One step: the page peeks a code directly (`table_peek`; the old `code_lookup` → `code_kind` is
     retired), and the store in `codeJoin.ts` holds the whole join as one value.
   - An invite link pasted into the code box reads as its code (`codeFromLink` in `codes.ts`): the box holds
     four characters, so the link itself would keep only "HTTP".
   - A Join panel looks again when the page comes back (focus or visibility; a return while the socket is
     down looks once it is up): fresh seats, or, for a code that names nothing now, the panel closes with the
     one line "That game has ended." A table closed for a moment (its host claiming another seat) keeps the
     panel with Join disabled, looked at again every 2 s until it opens, when Join comes back.
   - The Join panel is a kind of the one panel (`join-code`): `fromCode` in `queue/tableModel.ts` builds it
     and `TablePanel.tsx` draws it, with the CASUAL tag on a casual table (the one queue-side panel that keeps
     its tag, since the Ranked / Casual switch shows your choice, not that table's mode) and Enter pressing Join.
3. **One identity sheet.** The name chip is the only identity control. A guest's chip opens one sheet
   (`IdentitySheet` in `components/GuestChip.tsx`, mounted once by App): "Your name" with the field and its
   dice (a new guest's name and the dice's draw are "Adjective Noun", or in a Chinese interface a mood and a
   game word, "淡定的庄家" / Traditional "機智的大王", at most six characters, `randomName.ts`; a name already
   given is never renamed when the language changes; Jerry 2026-11-26, decision mocks section 9 B), then the sign-in buttons with one line under them, "By signing in you agree to the Terms of use."
   (the sheet's only copy; App Store guideline 1.2, Jerry 2026-11-16), then Done. Every Sign in opens that same sheet: the Play tab's guest line
   ("Playing as a guest · Sign in to be ranked", which stays), a guest's one name row on Me, the
   Leaderboard's one row "Sign in to be ranked ›", a guest's round-end line at a ranked table (same words) (its card and its sentence on ratings are gone;
   How to play's last step says what ranked means) and a lapsed session's "Sign in to see your saved games." The top bar's separate Sign in
   is gone, and signing in closes the sheet. Over an open modal dialog (a round end, a confirm) the sheet
   is drawn inside the newest one (`modalHosts.ts`), since the browser blocks and hides anything outside
   a `showModal()` dialog; the connection notice stays above it. Signing in at a table keeps the seat: the
   socket is replaced and the seat moves to the account by its token, rated from the next round.
   - Sign in with Apple shows where it works today: the iOS app, when `nativeAuth` reports the Apple
     provider ready, above Google. The website shows Google only, until web Apple sign-in has its Services
     ID, return URL and server audience.
   - Terms of use is a page like Privacy (`support/TermsPage.tsx`, the real path `/terms`): Me lists
     "Terms of use" between Privacy policy and Support, and the sheet's line links it, keeping the typed
     name and closing the sheet. On the website Me ends that group with "On iPhone", a plain link to the
     app's App Store page (a row, not a new surface); the app does not list it. The website's Play tab
     ends, under How to play, with Apple's black "Download on the App Store" badge (Apple's artwork from
     its Marketing Tools, unmodified, 40px tall with its clear space, alt text its only copy; Jerry
     2026-11-23: "adding App Store link on site"), a plain link to the same page and gone while a table
     panel is the page; the /rules and /rules/zh footers carry the same link beside Play now (the Chinese page
     with Apple's Chinese badge). The app shows none of them. A tap is the `app_store_badge` tap event. Chat lines and guest names are masked by the server's word filter
     (`api/chat_filter.py`); an account's display name with a listed word is refused ("That name is not
     allowed.").
   - A signed-in player still edits their name inline in Me (`NameEditForm`, saved to the account); the
     sheet is a guest's, and since 2026-11-22 also the iOS app's own account's until it signs in (see "One
     account in the iOS app").
5. **One toast and one line above the hand.** Every message that comes and goes is the one toast
   (`components/Toast.tsx`, shown through `showToast` in `toast.ts`): one at a time, the newest replacing the
   one showing, gone after 4 s. It has one spot per layout: at the top of the page off the table; at a
   tablet or desktop table centred under the top seat, just under the header; at a phone table centred just
   above your action row, clear of the top seat's play (Jerry 2026-11-26, the 11-10 spot). An error is red and read at once
   (`aria-live="assertive"`); a notice is gold-outlined and read politely. Its sources: the server's errors
   and notices, a link's table that is gone or a code that names nothing (the lobby's error box and the line
   under the code box are gone), the queue's notices (`q-toast` is gone), a failed throw (the header notice
   and its close are gone), the engine's table messages (a declaration is not one: its tag under the
   declared cards tells it), a newcomer joining ("Mei joins next trick", once per join; the corner line is
   gone), the newcomer's own line when its seat is handed over mid-round ("You took Bot 2's seat · unranked
   this round", the one toast held until that seat's first card, then at least 4 s in all) and Coach on/off.
   - At the table, exactly one line stands between the trick and your hand (`components/HandLine.tsx`),
     highest first: why Play is disabled (a refused tap, or a play that does not follow), else the phase's
     help (declaring, burying), else the newcomer coach's cue. The phase's help and the cue are teaching and
     show only while the coach shows (the Coach switch on, or a newcomer on auto); the reason shows always.
     The coach points and never plays: no card in the hand is dimmed, legal or not; an idle cue pulses the
     cards that follow the lead (Jerry's no-dimming rule, 11-12). In a player's first game only (Jerry 2026-11-26,
     from the round-1 quit read: "bot move for player → no"), your own bury or play left 15 s with nothing
     chosen gets the served bot's choice selected for you, as if you had tapped those cards, and those cards
     alone are lit with the coach's gold ring (no pulse, no text, no new surface); you still press Play or Bury.
     A tap of yours during the turn stops it for that turn, a card you chose before the turn is kept, and it
     never runs on a declare, on another seat's turn or with the Coach switch off. Ranked tables count too: a
     new player's first game may be a matched one, and this is only a selection. The first game is every round of the
     first game you sit in, to the round a team passes A (`firstGame.ts`): a browser that has seen a game end
     keeps `shengji.firstGameDone`; a browser that made the coach's plays before the table is past it; a
     signed-in account counts only at a table it reached with no rounds played, held by its code so the
     game's later rounds still count. The bot (`hintPick.ts`, the offline SmartBot on what your seat can see,
     `frameView.ts`) loads by a dynamic import only when such a turn sits idle. Each preselect is one
     anonymous `hint_preselect` tap.
     The banker's bury hand is one plain hand: kitty cards carry no mark (Jerry 11-14). The status line in the button row ("Waiting
     for Li", "Dealing cards…") is gone: the seat on turn glows and says "their turn", and the hand fills
     as it is dealt.
     A bot on turn is its seat's gold edge and, on desktop, one plain line of banter; the "Considering the
     next play…" line and the progress bar are gone, and that status is read to screen readers only (Jerry 11-15).
     The bury button reads "Bury (3/8)"; "Burying 10 points" is teaching and shows only while the coach shows (Jerry 11-15).
7. **Offline without a reload** (app only). Offline is a state of the one Play page, not a page of its own. Play on
   the greyed Play tab (no connection), the Play offline link beside How to play, and the full-screen
   connection state's "Play offline with the bots" all swap the socket to the on-device server in place
   (`conn.useLocalServer()` in `ws.ts`, through `offlineGame.startFromPlay()`) and open the same offline
   table panel ("You and 3 bots", Start, Leave) on the same Play page. Leaving the table, or the game,
   swaps back to the game server in place (`conn.useGameServer()`) and the socket reconnects; with no
   network the Play tab stays offline until the network returns. Nothing reloads or navigates, except the
   app's bundled page (shown when the live site could not load at launch), which has no game server and
   loads the live site to go online.
   - The swap carries nothing across: the old socket's handlers are cut before it closes, its room,
     resume token, chat and any pending leave or reconnect are dropped (listeners get `left`), the queue
     store and the toast reset, and the on-device socket passes on only the messages its server answers
     (the queue, presence, telemetry and heartbeats go nowhere). App's fill-with-bots
     chain ends with that `left`, as does a Start cancelled before its room came back. Telemetry collects
     only online: an online page's buffered events go before it turns offline, and nothing buffered on
     either side is kept across the switch. The one exception is three counts (rounds started and
     finished on the device, and how many were nearby), kept in the app's native store and sent once
     as an `offline_digest` on the next online socket (`web/src/offlineDigest.ts`).
   - An online page in the app loads the on-device server once it is connected and idle, so Play offline
     still works after the network has gone; a browser never loads it. The separate offline page shell (`offline/server/ui.tsx`, OfflinePlay's
     whole-page component) and the `?offline=0` / `?offline=1&table=1` reloads are removed; `?offline=1`
     still opens a page offline (tests and development).

## Grammar: Us/Them are labels, sentences say we/they (Jerry 2026-11-14)
- "Us" and "Them" are labels only: team heads, HUD chips, "Them 15 / 80", "Games: Us 1 · Them 0".
- In a sentence the team is "we" or "they": "They took 35 of 80. We go up 1, to 3.", "They won the last trick: ×2, +30". A round title names the players ("You & Alice win the round"), and with no names it says "We" or "They".

## Decisions 2026-11-14 afternoon (Jerry, on the UX retro)
- Guardrails: yes, all of them. That includes moving this spec and the mocks into the repo (`docs/design/`).
- Duo: the Duo button stays and holds a partner seat; otherwise the panel is the same as Play's.
- In-game: mute, Coach and Leave live only in the overflow menu. The icon is ⋯ (decided 2026-11-14 on the simplify mock, "Yes for all the simplification paths").
  - The header, phone and desktop alike, holds game state only: Us / trump / Them levels and the points ("35/80" with a dot in the attackers' colour), then Chat and ⋯; the mode is a label at the top of ⋯. No mute, Coach, Leave, code, phase or kitty chip.
  - Partner seat on phones: in the header row's middle (Jerry 11-14, 'Player in header is fine'); a row of its own would shrink the trick cards; desktop/iPad below the header; side pills at the edges.
  - ⋯ opens one menu (`HudMenu.tsx`) in this order: the code with Invite link, Allow joiners (the opener's seat only, from the state's `opener`), then Coach, Sound, How to play, then a red Leave game that opens the one Leave sheet. The opener's controls pass to the next person when the opener leaves, in the lobby or mid-game.
- How to play's last step (Jerry 2026-11-26, decision mocks section 5 B): where you sit at no table and the socket is open, a gold "Play a practice round" deals a Casual round against Beginner bots (one `create_room` with `bot_level: "beginner"` and `start`, as Play offline's Start sends, under the same name; offline the game stays on this device) and Done goes back; anywhere else Done alone. No new game type, queue or join site.
- How to play's ten steps teach the game, in the table's own words and marks: the pictures' level chips read Us and Them as the top bar's do, the banker's team carries the crown, and an attackers' win makes them banker (no "the deal"). The app is named once, in the last step's caption: the games score, and that a full Ranked round counts toward a signed-in player's rating and Casual rounds do not (a guest and a mid-round joiner are not rated). Companions, the Collection and Watch are not in it. Step 4 names round one's banker as the engine does: the standing declaration's seat, or the first seat when no one declares. Each step is at most three sentences and fits a 375x667 phone with no scroll, the last step's two buttons included (`e2e/client.mjs` `howto-fit-*`); under 700px tall the text slots give up their fixed heights.
- How to play over a timed game (Jerry 2026-11-26, decision mocks section 10 B): the guide opens as before, the game runs on, and while a decision is yours its header shows your move timer's ring and "Your turn" between the title and the step count. No block, no pause; Back is the way to the table. Alone with bots there is no timer, so nothing shows.
- Way back to your table (simplification 6, approved on the simplify mock): one "Your table" pill on Leaderboard and Me, in the
  top bar's end on a wide layout and at the end of the large title's row on a phone. It shows while you are queued, at a waiting
  table, in a room's panel or in a game: a dot, "Your table" ("Your game" in a game), then the bots' ring while it runs; a tap
  opens Play, which holds the panel or the game. Nothing shows when you sit nowhere. It replaces the phone's strip above the tab
  bar, the top-bar pill, the sideways phone's chip strip and "‹ Back to game"; over a game the tab pages keep the tab bars.
- One "a bot holds your seat" state (simplification 4, approved on the simplify mock): one pill at the felt's top-left, the
  connection pill's place. A dropped or backgrounded player keeps the seat for the move timer's 60 s, in every room, before
  the bot plays for them (Leave hands it over at once). It reads "Reconnecting…" while the socket is down and "A bot holds
  your seat · I'm back" once it is open; any tap or key press counts as back and sends `im_back` (the server's away and the ranked leaver cap are
  unchanged). Before the game the panel's primary is "I'm back": at a shared table that asks "still here?" (any tap also
  answers it, sending `table_here`; the status line is the countdown, "You leave the table in 0:30."), for a table open on
  another device (was "Move it here"), and when Play is refused for a game on another device (was "Return to your game").
  It replaces the separate Away pill. "Joining after this trick" stays its own pill: you are joining, not held, and its
  Leave is the way out. The signed-out "Sign in again to return to your game." line stays as it is: no I'm back can work
  without the account.
- Server merge (one Table object): yes, planned after Duo lands.
- Start rule (no auto-start alone): Jerry asked for more explanation. It goes to a mock with both variants before any decision.

## Deferred mock items (Jerry 2026-11-14: "Yea do deferred mock questions")
- **Take back a Ready.** At a waiting table, a joiner's Ready is in until it taps the button
  again: the quiet, pressed "Ready" is gold again, its ✓ goes, and the owner's "N of M ready" count drops (2026-11-26: the button no longer reads "Waiting for Alice"; the line under the title says who starts). A Duo's partner
  takes back its own tap; the owner has none. The server's `table_start {on: false}` does it.
- **Quick chat phrases.** The chat sheet shows one row of phrases first ("Hi!", "GG", "Nice!", "One more?",
  "Brb", "Thanks!", "Sorry!", "Good luck!"), then the field. The row never wraps; on a 390 px phone the last
  two or three scroll sideways into view. A tap sends the phrase's id with its wording in the sender's language,
  through the same validated, rate-limited path as a typed line, and every player reads a known phrase in their
  own language (an older client shows the sender's wording); typed lines are never translated. Nothing new is
  logged: the round log keeps the text. On the Play tab the table panel's Chat row opens chat in the shared `Sheet`
  (a bottom sheet on a phone either way round, a centred dialog from 700px); in a game chat keeps its panel on the felt (Jerry 11-15).
- **The opener moves other people.** At a waiting table, the opener taps a person (the
  seat is outlined), then an empty seat, then confirms once ("Move Alice here?", Cancel / Move). A Duo moves as one
  to a whole free team and is never split; a held partner seat is never a destination. The move takes back the
  moved person's Start, and they hear it in the one toast ("Jerry moved you to the other team."). Anyone else's
  own move to an empty seat is unchanged.
- **A table keeps its code for life.** The code a table took from its opener stays when the opener leaves (the
  next person takes the opener's controls, not the code), so every invite link keeps working while the table
  exists, and the room starts on it. The last one left alone keeps the table's code as its own.

## The iPad table: Fill (Jerry 2026-11-17: picked option B of the three iPad table mocks)
- A screen at least 810×740, touch or mouse (an iPad sideways, mini included, and 11" and 13" upright, or a desktop window; the root class
  `tablet-table` from `phoneLayout.ts`) draws the wide table sized to the screen. Below that the cross could not
  keep a six-card trick's cards at the wide table's 52 px. A sideways touch window under 740 px tall (Split View,
  Safari with its toolbar on a mini) gets the phone table instead, whose cross fits a short screen. Upright, a touch
  screen at least 744×900 (every iPad, mini included) takes the tablet table too (below). Seat panels, your name, the controls and the tags grow
  with one size token from the screen's shorter side (1 at 880×640, at most 1.5); text never drops below the reader's
  size; buttons stay at least 48 px tall.
- The hand runs edge to edge: its card comes from the screen's width (126 px on a 13" iPad sideways) and the pitch
  closes up only when the row would not fit. The banker's 33 keep one row; the card narrows until a "10" index
  clears the card over it.
- The trick cross takes its card from the hand's (91 px on a 13" iPad sideways), fitted between the top seat (with
  its "their turn" line) and your row; the side seats stand level with its centre. A play longer than four cards
  packs tighter so it never spans more than four would. Seat panels keep their card counts; a side seat ends before
  its trick slot, and a long name there ends in an ellipsis, shown whole on a long press as on the phone.
- **One row above the hand, laid out as the phone's (L2; Jerry 2026-11-26, "Desktop / tablet — L2 looks good", decision mocks section 1;
  centred 2026-11-27, "why isnt play button centered on desktop like it is on mobile?").** The action (Play, Bury, or Declare's options
  and Pass) stands centred under the trick; Clear just right of Play, and your name pill (crown, name, YOUR TURN) and the move timer
  just left of the action, outside its column, so neither moves it; the pill keeps room for a few letters of your name (a long
  one ends in an ellipsis), and three or more declarations read "♠2", "♠2 pair", "NT" after one "Declare" label, wrapping to a
  second line in the middle column when they still do not fit. The hint (an error, the coach, the phase's help) stands centred
  just above the row, out of the flow, so showing it never moves a control. A desktop window too small for the tablet table keeps the
  same row at the wide table's fixed sizes. The card sizes are unchanged
  (sized as if your name still had a row of its own); the height the one row frees goes to the cross, which stretches down into it
  (at 1440×900 the top play to your play goes from 34 px to 87 px). "Joining after this trick" stands in that row. The phone table is unchanged.
- **An iPad held upright: each play in front of its seat (L1; Jerry 2026-11-26, decision mocks section 8, option B).** Each seat
  is a one-line tag (team dot or crown, name, card count; whose turn is its gold edge), and its play lands in front of it: the
  top seat's under its tag, a side seat's under its tag at the felt's edge, yours above your row, which is L2's one row.
  Trick cards are 80 px (as an 11" iPad draws them sideways; 93 px on a 13"), the hand's card is unchanged, and the plays
  fly in from the tags. Last trick stays the control in the corner. Sideways iPads and every desktop window keep L2.
- The round's result dialog grows with the screen, whole (×1.15 from 1100×700, ×1.35 on a 13" iPad).
- A laptop or desktop window takes the same rule (Jerry 2026-11-25, "do we want to apply the iPad view?"): from
  810×740 the tablet table, below it the wide table at its fixed sizes. A mouse clicks a card (no slide), and the
  hover lift grows with the selected card's.
- Off the table a large desktop window (a mouse; from 1600×900, ×1.25; from 2200×1200, ×1.4) draws every page, its
  top bar and each sheet or dialog over it larger, whole, as the phone column's design; a touch screen is never zoomed.

## Blocking a player (Jerry 2026-11-17: "Yes" to keeping a mute across games)
- A long press (or a right click) on another person's seat opens its options (`OpponentActions.tsx`): Block player
  (Unblock player once blocked), Report player, Cancel. Block replaces the per-game Mute chat: the server sends you none
  of that player's chat, in this game or any later one, and marks their seat blocked in your state; the blocked player
  is not told. Unblock is the same row when they sit with you again. There is no block list elsewhere, so no new surface.

## Audit decisions 2026-11-15 (Jerry)
- **One confirm sheet.** Every "are you sure" is one `ConfirmSheet` (`components/ConfirmSheet.tsx`): a title,
  at most one line, then the cancel (focused first; Escape and the scrim also cancel) and the confirm side by side,
  rising from the bottom of a phone, a centred card at the table. A confirm that undoes something is red; one that
  is not a way out is the panel's gold. It carries the Leave sheet (`LeaveSheet.tsx` is its copy lookup), the
  opener's move ("Move Alice here?", Cancel / Move), taking a dropped player's seat ("Alice dropped out. Take their
  seat?", Cancel / Take seat), Delete account ("Delete your account?", "Your rating and games are deleted.",
  Cancel / Delete; was an inline card) and removing a saved game ("Remove this game?", Cancel / Remove; was "Tap
  again to remove"). A link opened while you sit in a Duo asks with the panel's own Duo line.
- **Saved games: one place for Continue and Replay.** A list row is one tap target that opens the game: the
  teams ("You & Alice vs Bot Wei, Bot Li"; was the table code and the other three names), the time, rounds,
  levels and today's rating change, then ›. The game's page holds the one gold Continue and a Replay for each
  round; the game-level Replay is gone (it opened round 1, as round 1's Replay does). Replaying a round is
  Me → Games → game → round.
- **Continue keeps one game, ranked if it was ranked** (Jerry 2026-11-19: "If it's a ranked game, I think it
  should continue as ranked. It also made a separate game."). Continue opens a new table, you in your seat
  and bots in the others, that carries on the same saved game: its rounds number on from the game's latest
  finished round, and the game's row and page cover every round, the levels and the rating change at every
  table it was played at (was a new, separate game row, always unranked). A ranked game continues as a
  ranked table under the queue's rules: rated rounds and the round-end rating line, the move timer, the
  leaver rules and the bot anchor, joins through the queue, the same Ranked chip; it is refused while the
  account plays another ranked game or waits out a queue cooldown. A casual game continues casual. A game
  still being played at a table, its own or a continuation, cannot be continued. No new surface or string.
- **A guest's Me: one row for who you are.** The row is the name with a chevron and opens the identity sheet
  (the name, and Sign in where it works); it replaces the separate Edit name and Sign in rows. The settings stay
  where they are (Jerry: "keep settings under game"); a signed-in Me is unchanged. The iOS app's own account
  keeps that one name row in place of Edit name (2026-11-22).
  Since 2026-11-24 (Jerry, App Screens Review item 13) the header itself is that row: the avatar, the name and
  "Guest" with the chevron at its end, one tap target that opens the same sheet, so the name shows once (the
  separate name row under it is gone). Under it the three stat tiles a ranked round fills ("rounds won",
  "levels / round", "best streak"), each a dash for now; no new words.
- **Me's rating history (Jerry 2026-11-24, item 5):** above the stat tiles on Stats, a sparkline of the
  rating after each recent round (the stats call's `history`): one gold line, a faint fill, the latest point
  marked. No axis or visible text; its accessible name reads "Rating over your last N rounds, from A to B".
  Fewer than two rounds draw nothing.
  Since 2026-11-24 (Jerry: "make it click and draggable to see it over time") a press and a horizontal drag
  scrub it: a guide and the dot follow the finger and one readout floats just above the chart with that
  round's rating, its change (▲/▼) and its short date ("Today" for today). Letting go, Escape or leaving
  focus returns it to rest; at rest the readout is empty, so the panel keeps no status line. A vertical drag
  still scrolls (`touch-action: pan-y`). Focused, the arrow keys, Home and End step through the points and
  the readout is announced politely. The stats call sends the last 200 rounds (`history`) with one unix
  time per point (`history_at`). No range switch yet: the window is those 200 rounds.

## One account in the iOS app (Jerry 2026-11-22: "it should only be for iOS when it's tied to a device"; "Web guests should stay the same")
The website is unchanged. In the iOS app (`Capacitor.getPlatform() === "ios"`, with the Keychain plugin), the
first online Play, Duo or Join makes the device's own account, with no Apple or Google identity, before it asks
for the table (`deviceAccount.ts`): with a secret in the Keychain it signs in with it, otherwise it makes one
(`POST /api/auth/device`) and keeps the secret there. Every launch with a secret signs in again. A refused
secret (the account was deleted or purged) is cleared and that Play goes ahead as a guest; the server's switch
off, too many attempts or no connection leave a guest exactly as today. A launch that restores the account
replaces the socket before any Play goes, so a table is never asked for under the guest's handshake. One tap is
one attempt, and identity changes run one at a time; a further tap meanwhile does nothing, and a held Play
whose mode, tab or table changed does not fire. A Keychain that cannot be read makes no account (that Play is a
guest's). A new secret the Keychain will not keep, tried twice, leaves the account signed in on the cookie, with
nothing deleted and no message; the secret is held in memory only (never in the page's storage), offered to the
Keychain again at the next Play, and no other account is made while it is owed. Every sign-in and sign-out path
(the device's, Apple, Google, a launch's restore) takes turns through its request, cookie, state and socket, so the
one asked for last is the one everything carries; credential writes, revocation and removal run on one queue. Past 6 s the tap is given
up with nothing sent ("Couldn't open a table.", the line a lost Play already gets) while the sign-in finishes on
its own; the next tap waits for it. A sign-out in the app is done only once the secret is confirmed gone from the
Keychain and the server has ended the session; otherwise it says "Sign-out failed. Try again.", the account
stays signed in, and tapping again retries. A Play, Duo or Join waits behind any sign-in or sign-out under way, a
switch between accounts included, and goes once as whoever that leaves signed in. The mock is `account_frames` in
`docs/design/mocks/core.py`.
`/api/auth/config` says whether device accounts are on (`device_accounts`) and `/api/me` whether an account is
`linked`; with them off the app is today's guest, exactly.
- **Before the first Play:** the guest chip with the name alone (no "Guest", no rating) and no guest line.
  The account that Play makes keeps the name the guest chose when it passes the display-name checks and no
  account shows it; a random fill, or a name refused or taken, gets a server-drawn name instead, with no message
  (from the same Chinese lists when the app's interface is Chinese: the creation sends its `lang`).
- **Chip:** the name and the rating, with the guest chip's pencil; a tap opens the identity sheet.
- **Play tab:** no guest line; nothing else changes.
- **Round end:** the rating on the result line, as an account sees it; no "Sign in to be ranked".
- **Identity sheet:** the name (Done saves it on the account; a name another account shows is refused, "That
  name is taken."), one status line "On this iPhone only" ("On this iPad only" on an iPad, by the shell's device
  idiom), Sign in with Apple and Google, the Terms line, Done.
- **Me:** the header's line, the sheet's same "On this iPhone only" (or iPad), Stats and Games, the settings, the name row (opens the
  sheet), a "Sign in" row under it (the same sheet, at Sign in with Apple and Google, no keyboard; only when
  sign-in is configured), "Show me on the leaderboard", the help rows and Delete account; no Sign out, which would leave the
  account with no way back in. Delete clears the Keychain.
- **Leaderboard:** the signed-in board: the own row in rank order, or pinned with the "new" tag.
- **Signing in with an identity that has an account:** the one `ConfirmSheet`, as a centred card over the
  sheet: "Switch to Mei?", "This device's rating is replaced.", Cancel / Switch. Switch repeats the sign-in with
  `confirm`; the other account wins, this device's games move to it, and its new device secret replaces the old
  one in the Keychain. After the switch the chip reads that account's name and rating.
- **Linked:** an account with Apple or Google is a signed-in account as before (Edit name, Sign out). Its
  Sign out also sends and clears the device secret, so the next launch does not sign it back in.
- **Reinstall:** the Keychain keeps the secret, so the same account comes back; no message.
- **The app's own domain (build 11, Jerry 2026-11-24 "a gentle re-sign-in"):** the app loads playshengji.com;
  shengji.fly.dev keeps serving older builds, and invite links on either host open the app. At launch, until a
  page at the new origin confirms the import, the shell copies the old origin's cookies (the session among them)
  and hands that page its localStorage, written where a key is unset (`OriginMove.swift`, `originMove.ts`), so
  the name, settings and seats stay; no message. After the confirmation nothing is copied again.
  If the old origin was signed in and the app still settles signed out, the one identity sheet opens once at
  Sign in; no new surface or copy.

## Watching a table (Jerry 2026-11-26: "The spectate flow looks great in the video, let's build it")
Behind the server's `SPECTATE_ENABLED`, or for the accounts its `SPECTATE_ACCOUNTS` lists (a tester before
everyone; such an account may watch any live table); for anyone else nothing below shows. The way in is the Play tab's presence line: its
"N playing" part is a gold link with a chevron only when a live table can be watched, and one tap goes to a
table the server picks (the selected mode first, then the table furthest into its game), with no list. With no
live table to watch and a replay to show, the line says so: "Nobody is playing right now · Watch a replay ›"
(现在没人在玩 · 看回放 ›); "Nobody is playing" itself never opens a game. A replay (always a ranked round) names a player only if the leaderboard shows them (Jerry 2026-11-26: "For
ranked, we don't need to anonymize spectate", then "only if that player is shown on the leaderboard"); a guest or an
account not on it is Player 1–4 (玩家 1–4), and bots keep their names. Its strip says Replay (回放), not a round
number. A watcher sees the table's last FINISHED round, one round behind: it never opens the table's socket.
The top-left strip of a live table says so: "Round 4 · previous round" (第 4 局 · 上一局), after the eye and the
table's watcher count (watchers see a count, never names); a replay shows neither.

The players are told who watches (Jerry 2026-11-27, on the watchers mock: "Who's watching should be toast"). While
anyone watches, an eye with the count (👁 3, 3 watching / 3 人观战 / 3 人觀戰 to a screen reader) sits just left of ⋯
in the strip, phone and iPad alike, live with each state frame and gone at zero; it adds no line and no menu row.
As watchers start watching, the players get the one table toast: "Mei is watching" (Mei 在观战 / Mei 在觀戰) for a
leaderboard-listed account, "Someone is watching" (有人在观战 / 有人在觀戰) for a guest or an unlisted one; the
server tells at most one toast per table each 30 s, and the watchers who arrive in between come as one: "Mei and 2
others are watching" (Mei 等 3 人在观战), or "3 people are watching" (3 人在观战) with nobody listed. A tap on the eye
shows the same toast for who watches now. Nothing is told as watchers leave, and a toast told before the table was
on screen, or while a player's connection was away, is never told late. A watcher stays counted for as long as its
watch screen is in the foreground, reading the table every 15 s through the round's playback. A watcher is named only by the leaderboard rule a replay uses; its account id never
leaves the server, and what it sees is unchanged: the previous round only. A listed watcher's companion portrait leads
its toast while the player's Show companions at the table is on; with it off the words stay and no portrait shows.

Companions come along (Jerry 2026-11-27: "Do each companion is by hand and spectate brings theirs"). On the watch
screen each person's companion stands at their seat as at the table, in the look they wore as that round began; a
"Player N" seat of a replay is the default red Tractor, so a look never tells who a masked player is, and a bot has
none. Nobody there is tagged You, a tap on the felt walks nobody, and hops are skipped at 2× and on a step back or a
turn to another seat. The watcher's own companion stands in a gallery spot at the left end of the watcher's row,
tagged You (你), and cheers a trick worth 10 points or more as it plays, at most once each 4 s; it is drawn on the
watcher's screen only, never on the players' felt. Me → Settings → Show companions at the table off, or the
Collection off for the account, draws none of them. No surface, message type or string is added. The watch screen is the table (`watch/WatchScreen.tsx` draws the table's own seats,
trick and hand read-only), turned landscape as a game is: four tabs (team dot, crown, name, cards left; the
selected one filled) in table order from the seat it lands behind, the banker; a tab turns the table to that
player (cards and seats travel about 0.5 s, a fade under Reduce Motion) and docks their hand in the game's order.
The round opens with the banker's bury (the eight cards rise and leave into the kitty); the next play's cards rise
before they land, at a steady rhythm. The top-left strip is the game's own (round label, trump, points). At top right a live table keeps ⋯ with Next
table and Leave; a replay, which has only Leave there, draws one ✕ in its place instead (named Leave, 离开 / 離開),
and one tap leaves (Jerry 2026-11-27: "Spectate leave feels clunky"). Entering a watch adds one history entry at
the Play tab's own address, so the browser's back and the iOS app's left-edge swipe (on while watching, off only
at a game) leave it too, and so does Escape when nothing is open over the table (the menu, the kitty peek and the
round end card each close first). Every way out lands on the Play tab with its presence line; no surface is added. One row above the hand holds the transport pill (previous
trick, play/pause, next trick, speed 0.5×/1×/2×, remembered on this device; it steps whole tricks inside the
finished round only), the four tabs centred, and the kitty; the trick cross keeps clear of that row as it does of
a player's buttons, and the watcher's hand is drawn at the bury's size throughout, so nothing moves when the bury
ends. On the iPad the row and the hand stack, centred, the hand no wider than the screen. A small kitty stack
beside the tabs opens the kitty peek, the one surface added: the eight
buried cards, dismissed by a tap. The round end is the game's own card (Details shows the kitty and the last
trick) with the watcher's buttons: Take a seat (a casual table seating joiners: the code's own Join) or Play (a
ranked table: the queue's Play), and Leave; under it the one line "Round N in play" until that round finishes,
then its replay plays.

The watcher's round end closes from its backdrop (Jerry 2026-11-26, red team item 9: "tapping outside the card
closes it"): a tap outside the card, or Escape, takes it away so the transport is reachable and Previous trick
steps back into the last trick; the card comes back whenever playback reaches the round end again. Only the
watcher's card does this; a player's round end still waits for Next or Leave.

"Nobody is playing right now" is said only when the server says nobody is (its 404). A read it refuses (429), a
server error, no network or a round that cannot be drawn is tried once more after 1.5 s; a second failure lands on the Play tab with the one
toast "Couldn't open a table" (没能打开牌桌 / 沒能打開牌桌), and no surface is added. A Next table that fails
keeps the table on screen.

## Collection and companions (Jerry 2026-11-26: "I like the Collection tab. Can we first build it with the default Tractor… do the character building with the Tractor first, before the store"; "let's add more colour schemes for free too")

- **Behind an allowlist first** (Jerry 2026-11-26: he tries it before anyone else sees it): the Collection tab,
  its pill, every portrait, the companions at the table and the unlock dot draw only for a viewer whose
  `/api/me` says `features.collection` (an account listed in the `COLLECTION_ACCOUNTS` secret), or for everyone
  when `COLLECTION_ENABLED=1` (`/api/auth/config` `collection`). Everyone else, guests and offline/Nearby
  included, sees the three tabs and the initials. `PUT /api/me/look` is 404 for an account not shown it. The
  look still travels on seats and leaderboard rows, and only a viewer shown the Collection draws it.
- **A person's picture is their companion's portrait** wherever a person is shown: the leaderboard rows, the Me
  header, the account chip, the Me tab icon, the waiting-table seats, the seat labels at the table, the round-end
  title and chat lines. A bot keeps its initial (or no picture where it had none). No ring on a portrait: the ring
  is the move clock. The portrait replaces the Google picture too, so every player looks the same way to everyone.
- **The Collection tab** (伙伴 in Chinese; Jerry 2026-11-26 took the red team's call: 收藏 reads as Favourites,
  and the gamer words 装备 and 待机 are gone, the button reading 使用 / 使用中) is the third of four, its icon four
  small tiles with one filled when selected. It is one page (Jerry 2026-11-27: "clicking a character should just
  change the top character above the tiles instead of a new page"; before, design B's grid opened a separate
  character page). At the top, the **stage**: the selected character (the one in use until a tile is tapped) on
  a corner of felt, cycling through its moves by itself while on screen (idle, hop, cheer, its special, a short
  sleep, each move for its own animation's length; Jerry 2026-11-26: "all the animations there like the mock"), a
  tap playing its special from its start, still under Reduce Motion (a tap shows the special drawn still). Under
  it, one row of four chips (Jerry 2026-11-27: "yea lets add them", reversing the cut of state chips; then "I don't
  think we need Try on table. And we can have 1-2 rows of actions- we don't need all"): **Hop · Cheer · Big play ·
  the special by name** (跳一跳 · 欢呼 · 大牌; Wheelie, Steamer pop, Flutter, Loop; Horn butt and Bamboo bite for
  the store's). Big play is the table's two-bounce jump (see At the table below) with the figure cheering
  throughout, its jump, and on a stage shorter still its growth, lowered only as far as the stage's own height
  needs, Reduce Motion's still pose included. Each chip plays its move once before the cycle resumes, the special's
  chip the same as a tap on the figure (either ends a move still playing), each drawn still under Reduce Motion.
  The row is one line on every phone, the iPhone SE included; its chips are labels only. Sleep, Ready, Watch and
  Try on your table are cut from the stage (the table keeps its own Ready and Watch). Then its colour
  swatches (56 px, four in a row on a phone), one status line and the one button. The status line says how an
  owned look was got (Jerry 2026-11-27: "It should say how we got the skin like 'achieved through x ranked wins' or
  'purchased on x date'"): a Tractor colour won, the count that unlocked it ("Unlocked with 25 ranked rounds won",
  赢 25 局排位解锁); a store companion, the date it was bought in the viewer's own date format ("Purchased 27 Nov
  2026", 2026年11月27日购买; `/api/me` `purchased_on`, a date only). A look free from the start names what is
  shown ("Bun · Taro"), with no "Free": every free look in Yours is free, so the word adds nothing. A look worn from
  before its count was reached names it too. A locked look's line stays what unlocks it. Then **Yours** (the page has no switch; Show companions at the table is in Me's settings), the free companions and the ones bought, as tiles idling on felt
  with their names and a tick on the one in use, ordered by last use (Jerry 2026-11-27: "for yours, can we order by
  last used?"): the one in use first, then the others by when one of their looks was last put in use (the server
  keeps it per look, `/api/me` `recent_looks`), then those never used in Collection order; then, where the store can sell, **More companions**, the store's
  characters with StoreKit's own price or Soon for one not launched, and Restore purchases as the last, text, row;
  where it cannot, **Coming soon** (即将推出 / 即將推出; Jerry 2026-11-27: "show coming soon section? even if we dont
  say shop or have a price"), the store's characters not owned as muted tiles with no price, no Buy and no store
  wording, a selected one live on the stage (its moves cycle, a tap plays its special) with the one status line
  Coming soon and no button, no colours and no move chips. Two tiles across on a phone, three or four on a wide layout. A tap on a tile selects it into the stage in place:
  the stage crossfades to it (no motion under Reduce Motion), a gold ring marks the selected tile while the tick
  stays on the one in use, and on a phone the page scrolls back up to the stage, on every tap, the tile already selected included, after the stage has changed and with any fling stopped first (Jerry 2026-11-27: "sometimes clickign lower unit doesnt scroll to top"). There is no character page, no
  back and no edge swipe. A link to `#/collection/<kind>` selects that character and puts the plain address in
  its place (no history entry); while the account loads or the store's check is out for a store character it
  waits, and one the viewer may not see leaves the one in use on the stage; a store character the viewer cannot buy
  opens as Coming soon. A selected character that goes away gives the stage back to the one in use; a store
  character the viewer can no longer buy (a refund, another account, the store turned off) stays on the stage as
  Coming soon. Each character
  appears once: buying one sends its tile up into Yours. No Shop segment, button or page, no leaderboard row.
- **One rule for taps:** a tap on a companion or a colour only shows it (the gold ring is "looking at"); the one
  button puts it in use: Use, In use (inert), for a locked Tractor colour Use (inert, one size) with what unlocks
  it on the stage's status line ("Win 25 ranked rounds to unlock · 3 of 25", "Win a ranked round to unlock"), for
  a guest Sign in to use, which opens the
  identity sheet, and for a store character not owned Buy with StoreKit's price (Soon, inert, for one not
  launched). A tick marks the companion and the colour in use. A guest sees no counts.
- **The store** (store plumbing, behind `features.store`: the Collection allowlist plus `STORE_ENABLED=1`, or
  for testing purchases before launch, the accounts listed in the `STORE_ACCOUNTS` secret):
  More companions and Restore purchases show only in an app build with the StoreKit plugin, to an account the
  store is on for, off the China mainland storefront; elsewhere the grid is Yours then Coming soon, and a guest on
  the website also gets one Get the app row (the App Store link) under it. Buying and restoring need an Apple or Google
  sign-in (Jerry 2026-11-26): for the app's own device account a selected store character shows the price and a
  gold Sign in to buy in the button's place, and Restore purchases opens the same identity sheet; signing in links
  the device account (its rounds and looks carry over) and leaves the player on the same page, the same character selected, where Buy now buys.
  A purchase is Apple's sheet, then the server verifies Apple's signed transaction, bound before the sheet opens
  to the account that pays; success is the character's cheer and the success haptic, nothing written, and Use
  takes Buy's place. Waiting for approval (Ask to Buy) and a refused purchase use the stage's one status line, a
  failed restore the grid's. A transaction the server has not settled stays with the App Store and is delivered
  again when the Collection opens or the account signs in.
- **The store's characters**, each in its own art with four colours and its own signature reaction: on sale, the
  Spring Lamb 小羊 (a run-up, a leap and a horn butt in one big star and spring petals) and the Baby Panda 熊猫宝宝 / 熊貓寶寶
  (the bamboo bite); coming, shown as Soon tiles and, selected, on the stage in their idle art with no look id, so they cannot be put
  in use or bought, the Jade Rabbit 玉兔 (breaks a mooncake and holds half out), the Lucky Cat 招财猫 / 招財貓 (beckons
  and holds a big card up over its head that turns to a suit in a flash, a new suit each time and the joker about one
  time in twelve), the Fortune Fox 福狐 (tosses its red envelope overhead; three big coins burst out), the Dancing
  Lion 醒狮 / 醒獅 (its dance costume appears only for the dance) and the Little Dragon 小龙 / 小龍 (flies a loop and
  breathes fire). Jerry 2026-11-27 approved reworking the five that were faint or painted outside a special's room
  at the table: all seven now paint inside it, and the Lion's dance runs 2.5 s. The stage plays each reaction to its end. At the
  table they are drawn as the free companions are: still drawings on their team's pads that walk, hop, cheer and
  grow.
- **Show companions at the table** (Jerry 2026-11-26, finding 2: one labelled switch, on by default) replaces Team ·
  Individual · Off. It is stored where the mode was (the account's `companions`, a guest's device), so an older
  client keeps working: off is off, and an older Team or Individual reads as on. It is a row of Me's settings
  (Jerry 2026-11-27, see Section 6), shown wherever the Collection is; the Collection page has no switch.
- **A first look** (Jerry 2026-11-27: "can we initialize users to a random free companion", then "How about users
  use random companion at default color"): an account that has chosen none is given one on its first `/api/me` or
  socket, stored, so every device and its invite card show the same one: a free companion (Tractor, Bun, Chick or
  Sparrow) picked uniformly and seeded by the account id, always in its default colour, its first. A stored
  look is never replaced; a refunded companion's account is given a free one again. A guest's look is drawn the same
  way from its device key, so it stays the same on that device and the table shows it too; a guest still cannot
  change it (Sign in to use).
- **The companions** (Jerry 2026-11-26: "we can start with tractor, bun, chick, sparrow"), all free from the start:
  the Tractor, now with its rider (a farm kid in a straw hat at the cab window), the Bun 包子, the Chick 小鸡 and the
  Sparrow 麻雀, four colours each beside the Tractor's eight. Hop and cheer are two different moves: hop one small
  bounce, cheer a two-beat jump through confetti. Each has a signature reaction, drawn to read at table size (Jerry
  2026-11-27: "For the tractor special, it's a bit hard to see"; he picked the wheelie): the Tractor's wheelie in
  exhaust and dust, the Bun's pop out of its steamer, the Chick's high flutter in feathers, the Sparrow's loop. Each
  paints inside the box the table keeps for a special and moves at most five pieces besides the figure. Under Reduce Motion every pose is drawn still at its peak.
- **At the table** (Jerry 2026-11-26, finding 1: "yes, have it stand by the nameplate and randomly walk around")
  each person's companion stands by their nameplate: under a side seat's, to the right of your partner's, and
  yours over the left end of your hand on a phone (Jerry 2026-11-26: it had stood by the left seat's card; beside
  your name line on a tablet), tagged You 你. On a phone that is where a full hand starts, so it holds still while
  the hand is dealt (Jerry 2026-11-27: "the jumpy feeling is from zipping around during deals": no walk on its own
  clock and no step aside while the cards arrive and fly over it; one it must make waits for the deal to end, except off
  what does not fly: your name pill and your row's controls, Declare's options among them, it steps off at once, so a deal that brings up ten options never leaves it on your name), and the banker's crown chip does not move it. Every 8 to 15 s, on its own clock, it walks a few hopping steps,
  at the tapped walk's stroll (Jerry 2026-11-27: "the random movements are too fast; it should keep consistent
  speed": half a second a figure's width, so a short walk takes less time, never a faster pace), facing the way it goes, to another spot in a small zone by the nameplate that keeps clear of the cards played
  and their LEAD / WINS labels, the hand (and a chosen card's lift), every control of your row (the clock's ring,
  the crown, Declare and its options, Bury, Play, Clear, the turn pill, the hint line), the deck and its count, chat
  bubbles, an open menu, Chat or Last trick, the HUD, the nameplates and the other companions, and never goes under
  a notch or the Dynamic Island (the screen's safe-area insets); the zone is worked out again as cards set off
  (where they will land) and as anything appears, and a companion covered (Jerry 2026-11-27: "It's fine for
  elements to be on top of companion but companion should walk up"; or a layout that moves under it) hops quickly
  aside, upward first, 0.3 to 0.5 s from where it is drawn, never jumping; one whose whole zone is covered steps
  out to the nearest clear spot and comes back when there is room, never leaving the table. A figure that stepped
  out walks back 1 s after the way back opened (something appearing elsewhere does not restart the wait; the way
  home itself blocked pauses it), and where a side seat's played cards have landed at this window size (not a
  declaration, which is in the way only while it is shown) stays out of its zone for the rest of the table, so the left and right figures are not chased
  off and back by every card their person plays; only a
  figure drawn for the first time, a hidden page or Reduce Motion is placed at once. Where
  a corner is too cramped, its companion stands on another side of its nameplate, and failing that a step smaller. It wears its team's scarf (the Lamb's scarf, the Lucky Cat's collar, a kerchief on the others; the Tractor's stripe and its rider's band take the team colour) and is otherwise the figure every preview shows, curls, ridges and every texture of its colourway drawn at every size (Jerry 2026-11-27: "the lamb in game looks different from in store"; "in game we set a scarf maybe its best not to use scarf in preview"), so no preview (the stage, the tiles, the portraits, the watcher's figure) draws a scarf or collar, and a bell hangs at the neck without one; it stands on a soft ground
  shadow; there is no team pad under it (Jerry 2026-11-27: "not very intuitive for teams", removed at the table and
  in every preview). A team's companions grow an equal step a level from 2 to the seat cap at 6 (44 to 56 px
  on a phone, 3 px a level; 60 to 76 px on a tablet, 4 px a level; the same size from 6 to A; Jerry 2026-11-26: "a
  bit small"). A level gained
  (Jerry 2026-11-26, red team finding 7) shows only once the round-end sheet has closed and the page is in view,
  never behind the sheet: each of the climbing team's companions pops from its old size past its new one (0.5 s),
  cheers, and flashes the new level's rank in a gold badge by its head (the rank alone, no words); once per level
  gained, none for a team whose level held, and a new game's levels starting over shrink the figures with no move.
  A table opened onto a result draws the settled size. A team's companions hop
  (as high as about 28% of the figure where the room above it stays clear, lower where it is short; Jerry 2026-11-27: "the hop is a bit small")
  when it takes a trick, and cheer when the trick is worth 10 points or more (Jerry may tune
  this; a cheer rises no higher than its zone keeps room for); when your team wins the round, each of its
  companions plays its signature special once the round-end
  sheet has closed (after the level-up, when there is one). They answer the game (Jerry 2026-11-27: "Do all 3
  clips"; his worry was a table that reads flat). **Ready on your turn:** as the table waits on you (your play, or
  your bury as banker) yours jumps once, as high as stays clear (26% of its height, lower where the room above is
  short), lands 17% larger with its You tag riding up, bobs three times about a second apart, then holds that size
  with nothing running until you play, when it settles back; a turn that comes round within 8 s of the last jump
  (a fast table), or to a figure at 12 moves this minute, only grows, and a trick you take is hopped first.
  **Watches the play:** as a card lands each figure turns to the seat that played it: your team's turn to face it
  and lean in (up to 8°, the largest lean that stays clear), the other team's lean without turning round, a seat
  over a figure's head stretches it up, and its own person's card moves it not at all; it stands straight again as
  the trick is collected. A figure turns at most once in 4 s, never mid-move, mid-walk or while ready, and adds a
  turn or a walk of its own only while under its share of moves this minute (8 for yours, 4 for another), so yours
  makes 6 to 8 visible moves a minute at a person's pace. **Big plays:** a trick of 20 points or more is a
  two-bounce jump for its winners (the cheer where there is no room over it) and a droop, a squash and a tip held
  about a second, for the others; a tractor led is its team's two quick hops; these are 8 s apart at least (one
  sooner is the plain cheer, and no droop), and none starts behind the round-end sheet. A kitty taken on the last
  trick plays the takers' special once the sheet has closed, with a droop for the other team when it lost the
  round. Each is a transform of a box the figure already has, and none loops. A companion sleeps while its person is away, and
  between moves fidgets once every 6 to 10 s (its clocks, for walks and fidgets, run on through the hops and specials: one due mid-move waits for it to end): a sway, a blink, a small hop, in turn. Nothing moves while the page
  is hidden or under Reduce Motion (each stands on its home; ready is the larger size alone, watching the turn
  held, a big play the cheer drawn still, the droop held for a second, a tractor's hops nothing). A bot, and a seat its owner left, has none. They
  sit under the cards and controls.
- **Taps** (Jerry 2026-11-26: "If you tap on the board (outside of cards), the character walks there"): a tap on
  empty felt (not a card, a played trick, a seat, a button or any panel) walks your companion, facing its way, to
  the clear spot nearest the tap inside the safe area, at a stroll (Jerry 2026-11-27: "it's fun; make it go
  slower": about half a second a figure's width, 1.2 to 3 s, the pace of every walk it takes; a new tap turns it from where it is); it passes under the cards if they are in the way. That
  spot is its home for the rest of the table (Jerry 2026-11-26: "The companion shouldn't walk home, just try to
  stay in the safe zone where it was last clicked"): its walks are small ones round it, up to about a figure and a quarter either way (Jerry 2026-11-27: "i dont necessarily see the small fidgets or wander"), and when cards or a moved
  layout cover it, it hops to the nearest clear spot and that becomes its home. A new table starts it by your
  hand again. It never lands over another companion, and a walk whose straight way meets one goes round it in
  two legs; under Reduce Motion it stays at home. Taps are half a second apart at least, and a tap while the menu,
  Chat or Last trick is open (or the tap that closes one) is not one. A tap on your own companion plays its
  special, drawn up to 1.5 times larger for its length where that stays clear, at most once every 3 s; a tap in
  between answers with a small hop. Nothing else at the table changes with these taps. These two are shared
  with the table (Jerry 2026-11-27: "Yea special on tap and where I park it can be shared- yea it doesn't need to be
  perfect"): everyone else at the table sees yours play its special, and walk to the spot you parked it and stay
  there, mapped across each screen's own safe area and round its own companions, and a rejoin finds it parked
  there. Best effort, at most a special every 5 s and a parked spot a second; the idle walks, fidgets and the rest
  stay on your screen. A viewer with Show companions at the table off sees none of it, and Reduce Motion draws the
  still special and the parked spot at once.
- **Colours** are a palette swap of the one Tractor: Icon red (the default), Paddy green and Enamel blue from the
  start; the rest are won by ranked rounds won (Jerry 2026-11-26: "win 10/25/50/100", and Ink black the top;
  Jerry 2026-11-27: "it should be rounds won rather than full games won"): Imperial yellow at 10, Lantern orange
  at 25, Jade at 50, Blue and white at 100, Ink black at 1,000, the swatches in that order (a round won is a rated
  round your team won; games won count for nothing here). The server
  refuses a locked colour; a colour already in use stays in use though its count falls short, but once changed
  it is locked again until earned. A colour newly unlocked (Jerry 2026-11-26, red team finding 9) puts a small gold "New" 新 on its
  character's tile in the grid and on its swatch's top edge; selecting that character shows it on the stage. It is
  seen once its character is on the stage or the colour is put in use; the swatch keeps the mark for that visit
  until it is tapped, and an unlock a refresh brings while its character is on the stage is shown unless a colour
  there was tapped. Looks that came with a
  purchase are not marked (their tile arrives in Yours). The gold dot on the tab stays while any new colour is unseen. Seen colours are kept per account on this device;
  an account's first reading records what it has, so nothing it starts with is new.
- Offline and Nearby tables know no account, so they show the initials until the Collection is on for
  everyone; then every person there has the default portrait.
- Not yet: the store characters, the Shop, rating finishes.

## Polish checklist (UI review)
A UI review ask walks this list after the copy rule and the flow-map row. This file, `COPY_CUTS.md` and the felt (the hand and the table, where reading a card beats a uniform press) win over any item here. Adapted from `jakubkrehel/make-interfaces-feel-better` at `6d9f2f1df10e8ce2ae1708598a73b0506fb98794` (MIT, copyright Jakub Krehel); its framework snippets, image outlines, RTL rules and shadow-for-border swap do not apply here.

Tests hold the mechanical rules, so review does not restate them: `web/src/polishCss.test.ts` (no `transition: all`; every live number in its list has tabular digits; every control in its list has a press state; every listed control reaches 44px, drawn or with an inset extender, in every state its CSS draws, read from the style rules, except the named compact-chat quick phrases at about 35px), with `motionTokens.test.ts`, `chromeCss.test.ts` and `nativeFeelCss.test.ts`. A new live number or control joins that test's list. These are literal style guards; a rendered hit-test is a separate check, run in a browser when a tap area's reach is in doubt.

The reviewer judges:
- **Motion restraint.** An action repeated every trick or every few seconds gets little or no motion; motion marks a change the player would otherwise miss.
- **A static cue beside motion.** What motion shows is also visible at rest (the counter after the pop, the ring after the pulse), so a missed frame or Reduce Motion loses nothing.
- **Reduced motion.** Every animation has a `prefers-reduced-motion` rule that removes it or cuts it to a fade.
- **No motion on first render.** Opening the app or reconnecting into a live table draws the settled state; enter motion plays only on a change.
- **Enter and exit.** An exit is shorter and quieter than its enter (a fade or a small fixed shift, not the full travel); an open/close the player can reverse uses transitions that retarget mid-flight, not keyframes that restart.
- **Cheap loops.** A looping animation moves only `transform` or `opacity`; `will-change` lives only on an active gesture.
- **Concentric radii.** In a tight nesting, the outer radius is the inner radius plus the padding.
- **Optical alignment.** An icon beside text, a play triangle or a chevron sits where it looks centred, not where the box says.
- **Icons.** One stroke weight per control strip, matched to the adjacent text; one `currentColor` SVG recoloured per state; SVG, not emoji, on controls.
- **Text wrap.** `text-wrap: balance` on short centred titles, sheet lines and toasts; `pretty` on short body text; neither on long text.
- **One value per effect.** Press feedback reuses `.btn`'s scale or the existing dim list; durations come from the motion tokens.
- **Control sizes.** Actions are 52 tall and switches 44, radius 14, from the `--ctl-*` tokens; a new control uses them (`polishCss.test.ts`). A screen's main action is the one gold (`.btn.gold`, or a listed `.primary` main action); a second action is the raised neutral.

Findings use Severity / Location / Before / After / Why; the review also lists candidates it rejected, with the reason, and what it did not check on a device.

The declaration countdown updates inside its existing ring; passing removes it. The player move clock persists across phases and updates only its ring, low-time controls and round-end timer. Neither countdown rerenders the table or hand on each tick. Server state still resets deadlines and the move clock keeps its single five-second haptic. No surface or copy changes.
