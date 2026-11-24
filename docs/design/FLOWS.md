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
- At a waiting table, anyone may move to an empty seat until they tap Start.
- Everyone taps Start ("N of M ready"). The opener gets Start now after 30 s.
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
  - copy: "Stay until this round ends, or wait 1 minute to play again."

**Section 4, connection.** One "Reconnecting…" pill, Retry after 10 s, a full-screen state after 30 s (when the bot takes a dropped seat), and a
bad code shown inline under the code box. One wording. The same pill, in the same place, says "A bot holds your
seat · I'm back" once the socket is open again while a bot still plays your seat (simplification 4, below).
The pill shows at a table or in a game. On the Play tab with no table the presence line is the one status:
"Connecting…" until the socket opens, then the counts, or "Offline" once the app's Play plays on this device
(a browser stays on "Connecting…"); the 30 s full screen still comes (Jerry 11-15).
Leave game while the socket is down, or one whose socket closes before the server's answer, goes to Play at once;
the next socket takes this page's own seat back by its token and leaves it (`ws.ts`, no new send site, up to three
sockets, also after a reload or relaunch within 90 s),
so the bot covers the seat at once instead of after a dropped seat's 30 s and a ranked Leave counts as one.

**Section 5, tabs.** The same three tabs (Play / Leaderboard / Me) on phone, iPad and desktop. Stats and
Games become a switch inside Me. The Leaderboard is the phone's column at every width, centred and capped like
Me; your own row keeps "(you)" in view when a long name truncates (Jerry 11-15).
It opens on This week, or on All time when nobody has played a ranked round this week yet, until the viewer
picks a period (Jerry 2026-11-24: "default to global when it's empty"; no extra Play button). On This week each
row ends in the week's movement (▲18 green, ▼6 red, a dash for none; figures only, read as "up 18 this week"),
and the top three's ranks sit on gold, silver and bronze discs on both periods (Jerry 2026-11-24).
A page is one layer on the page background at every width: no raised card behind How to play (which keeps its
two columns from 900px, a sideways phone excepted), Support, Privacy or Terms of use. Real surfaces keep theirs: the table panel, sheets and dialogs,
grouped list rows, Me's stat tiles and How to play's diagrams (Jerry 11-15).
The phone lobby is portrait (Jerry 2026-11-15: "Yes let's lock lobby to portrait"): the app locks every lobby
screen (Play and its panels and sheets, Leaderboard, Me, How to play, saved games, Support, Privacy, Terms of use) to portrait
on an iPhone and the table to both landscapes; the web cannot lock, so a phone held sideways (under 501px tall)
shows the same portrait column, centred under a capped tab bar, and scrolls. The lobby has no sideways design
of its own; the table keeps its landscape layout.

**Section 6, settings.** One settings list (Coach, Sound, Haptics on native only, How to play) in both Me and
the ⋯ menu. "Kitty 8 cards" moves out of ⋯. Me alone adds a Language row before How to play: its value is
the choice, and a tap opens the choices in place under it, as Edit name opens its field (the app: Follow
system, English, 中文; the website, which stays English unless asked: English, 中文). No sheet, no new surface.

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
- **Host.** Off is today's solo table. On: the first time, the iOS Local Network alert (the audit's `NSLocalNetworkUsageDescription`); then the panel is the nearby lobby (`nearbyRoomModel`): the three bot seats become open seats, a code row with the 5-character code and no Invite link, the Bots row (the host picks Standard or Advanced with the same select, from the level the solo table had; joiners read it; the bots that fill the open seats at Start, or cover a dropped seat, play at it), no Chat row (nearby tables have no chat). Off again (before anyone has joined) is the solo table; once someone has joined the switch is locked and Leave ends the table for everyone. Don't Allow: the switch falls back off and the panel's one status line reads "Nearby tables need Local Network access. Open Settings" (the link opens the app's page in Settings).
- **Start = wait for ready, as a shared online table.** Each person's Start is their ready ("n of m ready", "Waiting for Mei"); the host alone starts at once. From the moment a second person sits, the bots' ring runs 60 s (matchmaking.py `BOT_FILL_SECS`); when everyone is ready or the ring runs out, bots take the open seats. The host alone has no ring: the table waits for people, as the online Wait for people does.
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
- **Never online.** Nearby frames go phone to phone only; telemetry is off during a nearby session (`NEARBY_SESSION`), and the page does not switch online while one is live.

## Copy rule (Jerry 2026-11-14: "i dont think we need the metadata in play page … take a pass to minimize the metadata / subtexts")
- Switches and rows take a label only, with no sub-line: "Ranked", "Allow joiners", not "Rates signed-in players" or "On by default: …".
- No explanatory notes under controls on the Play page. At most one short status line per panel, and only when it changes what the player does next (a timer, "1 of 2 ready", the leave cost).
- Drop kickers, hints and repeated context where the layout already says it (e.g. "Tap a green seat to move" once at most, "Others can join as they arrive" not at all).
- Explanations belong in How to play and the coach, not under controls.
- Jerry's examples of too much subtext (cut entirely): "Tap a green seat to move", "Jerry opened this table", "Invite by link or code", "Bots sit in empty seats". A panel is its title + seats + at most one live status (a timer / "1 of 2 ready") + buttons.

## Every table has a code (Jerry 2026-11-14: "for Play → your own table on ranked, i think we can also show the room code and the create room settings similar to what we do for casual rooms")
- When Play opens your own table (ranked or casual), it gets a code with Invite link and the same table settings a created room has (the Allow joiners switch; Starting level for the opener). This reverses section 1's "no code for Play tables yet". Since 2026-11-22 (Jerry, the "Your table" declutter, option B: "table settings sounds good - B lets do it") the code and its Invite are one control in the panel: the code on the left, a share mark and "Invite" on the right, one tap shares the link (or copies it, then reads "Link copied"); the ⋯ menu keeps "Invite link". A nearby table's code stays the code alone.
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
- **Bots: Standard / Advanced (Jerry 2026-11-20: "Maybe a dropdown for bot level - standard, advanced"; "im good with standard / advanced"):** a casual table has a "Bots" row after Starting level in the table's settings rows, inside Table settings since 2026-11-22 (`TablePanel.tsx` `TableRows`; no new surface; it followed Allow joiners until then), the same select as Starting level: the opener picks Standard or Advanced, everyone else reads the value. Label and the two option names only. Standard is the relaxed level: the served declare and bury, card play by the S136 search-free scorer with near-best noise (Jerry 2026-11-20: "Ok move scorer and noise then"). Advanced is the served bot. A new casual table starts at Standard (one constant, `CASUAL_BOT_LEVEL`). It is set before the game and fixed once the game starts (a room refuses it, as Starting level). A ranked table has no row and the server refuses a change; its level follows the people's ratings, unseen (Jerry 2026-11-23): the two bots opposing the people play Standard when every person at the table rates 1000 or less (a new account starts at 1000, a guest counts 1000), Advanced otherwise, and a person's partner bot is always Advanced, so people on both teams meet Advanced everywhere. It is chosen when the game starts and again at each new game at the table (after a point is scored), from the ratings after the last round's rating write, and never changes mid-game for a rating change. Inside a game it only rises: a newcomer who takes a Standard seat makes that team Advanced, and a new person or a different account on the people's team (a handover, a claim, a resume as another account) rated above 1000 makes the table Advanced for the rest of the game; a reconnect by the same account keeps it. No frame, label or setting shows it; rounds against Standard are rated at Standard's own lower anchor (`ratings.STANDARD_BOT_RATING`). The offline table has the same row (Jerry 2026-11-21: Standard by default offline and at Nearby tables, the host can switch): you pick until Start, it is the only settings row there (`offlineModel`), the next offline table opens at the level picked last, and the app's offline bot plays it (`web/ios/pybot/offline_bot.py`, the server's two room bots). Casual default Standard, both levels offered (Jerry 2026-11-20: "standard default in casual and standard can be in offers"): Play seats strangers at, and offers open tables of, either level exactly as Allow joiners says; a stranger seated at a waiting table plays at that table's level, the opener's, as for Starting level. This replaces the "Relaxed bots" switch (off by default) of the same day.

## Duo is a table (Jerry 2026-11-14: "it's awk to be in a duo room and play room at the same time"; "A duo should be paired"; panel, not popup)
- Duo opens your own table (the same inline panel as Play), with the partner seat held for your friend. There is no separate Duo code or Duo bar: the table's code and Invite link are the Duo invite, and a code joiner takes the held partner seat first.
- A Duo stays paired. After Start, or when Play matches you, the pair moves and is matched as one, as Duo is today, and a ranked Duo is rated as a pair. One Leave, on the panel, ends the Duo for you; your partner keeps the table.
- The table is an inline panel, not a popup. Popups are only for decisions (Leave, take a seat, a Duo invite).
- Built (client): the Duo sheet, the Duo chip and the separate party code are removed (`?party=` links read as `?code=`). Between games a formed pair shows one row, "Duo with <partner>" and Leave (`party_leave`), to both members; the leader keeps Play and Duo under it.

## Decisions 2026-11-14 morning (Jerry)
1. Duo flow as mocked (core.html section 5, "Duo: one table, paired"): approved, build it.
2. Allow joiners is the opener's switch only (server and client); others see nothing (copy rule).
3. Offline copy: plain "Offline" (cut the subtext); "Offline · you'll play the bots on this device" and "Ranked needs a connection" are dropped.
4. Round end: the top stays minimal (result line + buttons in a row), and a collapsed Details holds the kitty (cards, points, multiplier) and the last trick played. Keep that detail. A guest at a ranked table reads "Sign in to be ranked ›" under the result line, the same words as a link that opens the one identity sheet, drawn inside the round-end dialog (Jerry 11-20 plain text; a link since 11-22, so guests at a table reach sign-in; the "Guest" box stays gone; an account, one signed in on this round end too, sees no line); a seat taken mid-round reads "Unranked · joined mid-round" in the same place, because each explains the missing number (Jerry 11-15).
5. The guest line "Playing as a guest · Sign in to be ranked" stays on the website. In the iOS app with device
   accounts on it does not show (2026-11-22); with them off on the server, it stays.

## Simplifications approved (Jerry 2026-11-14, "Yes for all the simplification paths")
1. **One invite path.** One link kind, `?code=`, opens Play with the Join panel for that table, and so
   does every code typed in the code box (Jerry 2026-11-15), a game in progress too: its title
   ("Join Jerry"), the seats with yours glowing, Join and Not now. You glow in the seat Join takes: in a
   room the first bot seat (else a dropped player's), and tapping another bot seat moves you there; at a
   queued Play table the seat its rule gives a code join (a Duo's held seat, else the first open seat,
   partner first), which no tap moves. The rest show as they stand (names with their Start, open seats, a
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
   - One step: the page peeks a code directly (`table_peek`; the old `code_lookup` → `code_kind` is
     retired), and the store in `codeJoin.ts` holds the whole join as one value.
   - The Join panel is a kind of the one panel (`join-code`): `fromCode` in `queue/tableModel.ts` builds it
     and `TablePanel.tsx` draws it, with the CASUAL tag on a casual table (the one queue-side panel that keeps
     its tag, since the Ranked / Casual switch shows your choice, not that table's mode) and Enter pressing Join.
3. **One identity sheet.** The name chip is the only identity control. A guest's chip opens one sheet
   (`IdentitySheet` in `components/GuestChip.tsx`, mounted once by App): "Your name" with the field and its
   dice, then the sign-in buttons with one line under them, "By signing in you agree to the Terms of use."
   (the sheet's only copy; App Store guideline 1.2, Jerry 2026-11-16), then Done. Every Sign in opens that same sheet: the Play tab's guest line
   ("Playing as a guest · Sign in to be ranked", which stays), a guest's one name row on Me, the
   Leaderboard's one row "Sign in to be ranked ›", a guest's round-end line at a ranked table (same words) (its card and its sentence on ratings are gone; saying
   what ranked means in How to play is a follow-up) and a lapsed session's "Sign in to see your saved games." The top bar's separate Sign in
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
   one showing, gone after 4 s. It has one spot per layout: at the top of the page off the table, and at the
   table centred under the top seat, just under the header. An error is red and read at once
   (`aria-live="assertive"`); a notice is gold-outlined and read politely. Its sources: the server's errors
   and notices, a link's table that is gone or a code that names nothing (the lobby's error box and the line
   under the code box are gone), the queue's notices (`q-toast` is gone), a failed throw (the header notice
   and its close are gone), the engine's table messages (a declaration is not one: its tag under the
   declared cards tells it), a newcomer joining ("Mei joins next trick", once per join; the corner line is
   gone) and Coach on/off.
   - At the table, exactly one line stands between the trick and your hand (`components/HandLine.tsx`),
     highest first: why Play is disabled (a refused tap, or a play that does not follow), else the phase's
     help (declaring, burying), else the newcomer coach's cue. The phase's help and the cue are teaching and
     show only while the coach shows (the Coach switch on, or a newcomer on auto); the reason shows always.
     The coach points and never chooses: no card is selected for you, and no card in the hand is dimmed, legal
     or not; an idle cue pulses the cards that follow the lead (Jerry's no-dimming rule, 11-12).
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
     either side is kept across the switch.
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
- **Take back a Start.** At a waiting table, your Start is in until you tap the button
  again: "Waiting for Alice" (a quiet button) becomes "Start", and the "N of M ready" count drops. Each Duo member
  takes back its own tap. The server's `table_start {on: false}` does it.
- **Quick chat phrases.** The chat sheet shows one row of phrases first ("Hi!", "GG", "Nice!", "One more?",
  "Brb"), then the field. All five fit one row of the narrowest chat (a 390 px phone, the in-game panel), so the
  row never scrolls or wraps. A tap sends the phrase as an ordinary line, through the same validated, rate-limited
  path; nothing new is logged. On the Play tab the table panel's Chat row opens chat in the shared `Sheet`
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
- A touch screen at least 810×740 (an iPad sideways, mini included, and 11" and 13" upright; the root class
  `tablet-table` from `phoneLayout.ts`) draws the wide table sized to the screen. Below that the cross could not
  keep a six-card trick's cards at the wide table's 52 px. A sideways touch window under 740 px tall (Split View,
  Safari with its toolbar on a mini) gets the phone table instead, whose cross fits a short screen; one under 810 px
  wide and upright (an iPad mini or 10.2" upright) keeps the wide table's fixed sizes, as before. Seat panels, your name, the controls and the tags grow
  with one size token from the screen's shorter side (1 at 880×640, at most 1.5); text never drops below the reader's
  size; buttons stay at least 48 px tall.
- The hand runs edge to edge: its card comes from the screen's width (126 px on a 13" iPad sideways) and the pitch
  closes up only when the row would not fit. The banker's 33 keep one row; the card narrows until a "10" index
  clears the card over it.
- The trick cross takes its card from the hand's (91 px on a 13" iPad sideways), fitted between the top seat (with
  its "their turn" line) and your row; the side seats stand level with its centre. A play longer than four cards
  packs tighter so it never spans more than four would. Seat panels keep their card counts; a side seat ends before
  its trick slot, and a long name there ends in an ellipsis, shown whole on a long press as on the phone.
- The round's result dialog grows with the screen, whole (×1.15 from 1100×700, ×1.35 on a 13" iPad).
- A laptop or desktop browser (a mouse, not a finger) keeps the wide table at its fixed sizes.

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
  account shows it; a random fill, or a name refused or taken, gets a server-drawn name instead, with no message.
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
- **Control sizes.** Actions are 52 tall and switches 44, radius 14, from the `--ctl-*` tokens; a new control uses them (`polishCss.test.ts`).

Findings use Severity / Location / Before / After / Why; the review also lists candidates it rejected, with the reason, and what it did not check on a device.
