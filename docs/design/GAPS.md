# Core-flow mock vs main (ui14, 95982736): gaps

Flow numbers follow the mock as I first read it: 1 first open, 2 join, 3 own table, 4 invite, 5 in game, 6 leave, 7 connection, 8 offline, 9 Me, 10 game over. The mock has since added a Duo flow after invite (core.py:463-497), which shifts the later flows by one in core.html. Its rows are labelled "Duo".

Sources: mock `logs/mocks/unify/core.py` (helpers in `build.py`), spec `SPEC.md` (which wins where they disagree; it now also has a "Duo is a table" section). All client paths are under `web/src/`, and line numbers are at 95982736.

How the live app was checked: I built main with vite into `audit/dist`, served it with `vite preview` behind a scripted fake socket, and drove it with playwright-core. The script is `audit/shots.mjs` and the 15 screenshots are in `audit/shots/`. The preview server has been stopped. I did not render the 60 s full-screen connection state or the declare and bury frames; those rows rely on reading the code.

## In progress (separate PR; not re-derived)
- The art is hidden when the panel is up, so the panel is no longer cut off. My screenshot `audit/shots/f3_phone_own_ranked.png` shows the panel cut by the tab bar on main.
- The idle art is bigger.
- Countdown rings on Start with bots, Join and Start now. Join already carries a ring on main (`queue/TablePanel.tsx:209-210`).
- The "Your table" title (main says "Waiting for players", `queue/TablePanel.tsx:230`) and the Us/Them heads (main says "Your team" / "Opponents", `queue/TablePanel.tsx:149-151`).
- No "Free." line on the Leave sheet (`components/leaveCopy.ts:71,74,76-77,81`). The mock still draws "Free." (core.py:333,340); the newer decision wins.
- A visible Play offline link.

## Known deferred (not listed below)
- Taking back a Start tap.
- Quick chat phrases first in the chat sheet.
- The opener moving other people.
- The table code changing when its opener leaves a three-person table.

## Gap table

| # | flow | mock frame | what the mock shows | what main does (file:line) | gap | effort |
|---|---|---|---|---|---|---|
| 1 | 1 | First open, guest | Chip, Ranked/Casual, Play + Duo, presence line, code box. No other text. | Adds the line "Playing as a guest · Sign in to be ranked" (`queue/Ranked.tsx:61-79`, mounted at `:226`) and a "How to play" link (`components/Lobby.tsx:484-486`). The copy rule cuts notes under controls, and How to play lives in Me and ⋯. | different | S |
| 2 | 1 | First open (presence) | "2 tables · **1 ranked**, 1 casual · 3 playing". The spec keeps "N tables have a seat … · 5 playing". | "2 tables have a seat · 1 ranked, 1 casual · 3 people playing" (`queue/tableText.ts:170-177`). Only "people" differs from the spec. The "have a seat" wording is a mock/spec conflict, and the spec wins. | cosmetic | S |
| 3 | 1 | Desktop / iPad | The top bar carries the 升级 SHENG JI wordmark, the three tabs and the chip. | On Play the top bar drops the wordmark, and the title sits over the art (`home/HomeShell.tsx:131-136`, `components/Lobby.tsx:396-401`). See `audit/shots/f1_desktop_idle.png`. | cosmetic | S |
| 4 | 1–4 | Any frame with a panel up | Chip, mode switch and panel only. The code box is gone while you sit at a table. | The code box and Join stay under the queue panel; they hide only for a room (`components/Lobby.tsx:449`). See `audit/shots/f3_desktop_own_ranked.png`. | different | S |
| 5 | 2 | Tap Play (Join panel) | Seats carry names only. | An open seat held by an away player reads "Mei · away", and a Duo partner reads "your Duo partner" (`queue/TablePanel.tsx:48,52,69,101`). The copy rule cuts seat sub-lines. | cosmetic | S |
| 6 | 2 | Tap Join (in game) | The pill says "Joining after this trick" with Leave. | Adds the sub-line "A bot plays your seat until then" (`components/Table.tsx:705-708`). See `audit/shots/f2_land_joining_after_trick.png`. | cosmetic | S |
| 7 | 3 | Tap Play (own table, alone) | No status line; the bots' timer is only the ring on Start with bots. | Status line "Bots in 0:38" (`queue/TablePanel.tsx:215,230`, `queue/tableText.ts:64-68`). Check whether the rings PR removes it. | different | S |
| 8 | 3 | Tap Play (own table, alone) | Rows: code, Allow joiners, Wait for people, chat. | Can add a "1 table has a seat · View" row (`queue/TablePanel.tsx:220-224`), which the mock does not have. | different | S |
| 9 | 3, 4 | Own and shared panels | Secondary button reads "Leave". | Reads "Leave table" (`queue/TablePanel.tsx:200`). The room panel and the offline panel already say "Leave" (`:553`, `components/OfflinePlay.tsx:45`). | cosmetic | S |
| 10 | 3 | Alice presses Play (shared) | One status, "0 of 2 ready". The timer is the ring on Start now. | "0 of 2 ready · Bots in 0:31" (`queue/tableText.ts:73-78`, `queue/TablePanel.tsx:262`). | different | S |
| 11 | 3, 4 | Shared table with no timer | Not in the mock. | Shows an "Add bots in 1:00" button row (`queue/TablePanel.tsx:242-246`). See `audit/shots/f4_phone_joiner_casual.png`. | different | S |
| 12 | 4 | The app opens on Play (Alice, joiner) | "Allow joiners is Jerry's": a joiner sees the code and the level, but no switch. | Every party leader at the table sees and can flip Allow joiners (`queue/TablePanel.tsx:467` uses `q.leader`, not `q.opener`). The server allows anyone seated (`server/shengji/api/matchmaking.py:1232-1247`). | different | M |
| 13 | 4 | Alice taps Start | A joiner's button is "Start". On a room, the opener gets Start now after 30 s (spec §1). | A queue table labels everyone's button "Start now" (`queue/tableText.ts:121-122`). Only the room panel has Start → Start now after 30 s (`queue/TablePanel.tsx:526-533`). | different | S |
| 14 | 4 | Alice taps the link | The app opens straight on Play with the panel. | A first-time guest gets the name sheet first (`components/Lobby.tsx:342-345`). | different | S |
| 15 | 4 | Tap Invite link | Link text "…/?room=4N5Z". | `?code=` (`codes.ts:15`). The share title "Join my table · 4N5Z" matches (`queue/TablePanel.tsx:397`). | cosmetic | S |
| 16 | 4 | Casual panel | A "CASUAL" mode tag above the title, and "OFFLINE" offline. | No mode tag on the panel (`queue/TablePanel.tsx:310-312`). Casual is shown only by the switch above. | cosmetic | S |
| 17 | 1, 4 | Spec §1 (join-by-code) | A code opens the same panel; the seat picker is removed. | The `SeatTakeover` picker for dropped seats and the full-screen "Table is full" card remain (`components/Lobby.tsx:442-446,363-373`). | different | M |
| 18 | 4, 5 | Jerry taps Start (casual game) | The HUD mode chip says "Casual". | A casual (non-ranked) game shows no mode chip (`components/Hud.tsx:229-246`). See `audit/shots/f5_land_casual_hud.png`. | missing | S |
| 19 | 2, 5 | Guest at a ranked table | The HUD shows a "Ranked" chip. | Hidden for guests (`components/Hud.tsx:327`). | cosmetic | S |
| 20 | 5 | Round ends | "You & Alice win the round". One line: "Them took 35 of 80. Us go up 1, to 3. Next banker: Alice." Next round (ring) and Leave game side by side. | Per-team lines with role and outcome, "Levels now …", next banker, rating line, a Details disclosure, an "N/M ready" line, and Leave game stacked below (`components/RoundEndModal.tsx:155-173,176,178-243,264-272`). | different | M |
| 21 | 6 | Tap Leave game (ranked) | "This round counts as at best a draw." | "A bot takes your seat. This round counts as at best a draw for you." (`components/leaveCopy.ts:84`). | cosmetic | S |
| 22 | 6 | …in a round you joined | "Wait 1 minute to play again." The spec text is "Stay until this round ends, or wait 1 minute to play again." (mock/spec conflict; the spec wins). | "You'll wait 1 minute to play again." (`components/leaveCopy.ts:82`). | cosmetic | S |
| 23 | 6 | Between rounds and casual tables: free | A casual table mid-round is free. | A casual mid-round leave reads "A bot takes your seat and the others keep playing." (`components/leaveCopy.ts:86`). | cosmetic | S |
| 24 | 6 | The one leave sheet | Title "Leave the table?" everywhere before a game. | A room says "Leave the room?" (`components/leaveCopy.ts:74,78`). Rooms are now test-only. | cosmetic | S |
| 25 | 7 | Still gone after 60 s (at the table) | "No connection", "A bot holds your seat.", Retry, **Play offline with the bots**. | The body copy is longer (`components/ConnectionPill.tsx:135-137`). The offline button is hidden whenever `inRoom` (`:140-144`), so a drop at the table never offers offline. | missing | S |
| 26 | 7 | Full screen (label) | "Play offline with the bots". | "Play offline" (`components/ConnectionPill.tsx:142`). This may overlap the in-progress "Play offline link". | cosmetic | S |
| 27 | 8 | No network / Tap Play | Offline panel with a greyed Chat row. | The offline table has no chat row (`components/OfflinePlay.tsx:36-47`). The spec wants chat disabled with a reason. | missing | S |
| 28 | 8 | No network | Presence "Offline", Ranked struck through. The spec says "Offline · you'll play the bots on this device", "Ranked needs a connection", and a reason for Duo (mock/spec conflict). | Has "Offline" and the struck-through Ranked, matching the mock (`components/OfflinePlay.tsx:126-150`, `components/OfflinePlay.css:26-30`). None of the spec's reason lines exist. The later copy rule favours the mock; Jerry should confirm. | cosmetic | S |
| 29 | 8 | Tap Play (offline panel) | An "OFFLINE" tag above the title "You and 3 bots". | "Offline" is a status line under the title (`components/OfflinePlay.tsx:37-38`). | cosmetic | S |
| 30 | 10 | Us defend at A | Crown, "You & Alice win the game!", "Games: Us 1 · Them 0", Next game and Leave in a row. No ring on Next game. | The same core, plus a rating line, Details, "0/2 ready", "Leave game" stacked, and a ring on Next game (`components/RoundEndModal.tsx:141-153,176,256-272`). See `audit/shots/f10_land_game_won.png`. The mock still tags flow 10 "not decided", but the spec's final decisions settled it (core.py:456, SPEC "Final decisions"). | cosmetic | S |
| 31 | 3, 6 | At the table: ⋯, Allow joiners | Every table has Allow joiners, so ⋯ has it at any table. | ⋯ offers it only on matched or ranked tables (`components/Hud.tsx:338`). A non-matched casual game gets no row. | different | S |
| 32 | Duo | Tap Duo | Duo opens "Your Duo": your own table with a held "Partner" seat, its code and Invite link, Start with bots (ring), and Leave. There is no Duo code, no Duo bar and no popup. | Duo opens `queue/PartySheet.tsx` (a popup) with its own Duo code. A `PartyChip` showing "Duo code X" or "You + Sam · you lead · Leave" sits above the panel (`queue/Ranked.tsx:29-56,193,206,213`). | missing | L |
| 33 | Duo | Alice opens the link | The link puts her in the held partner seat, giving one table, one code and one Leave. | A table code joins through `queue.join(code)` as a stranger seat (`components/Lobby.tsx:289-292,350-355`). Only a Duo code pairs (`queue/PartySheet.tsx`). There is no held seat on the own table (`queue/TablePanel.tsx:64-74` draws a partner only when `q.partyId` is set). | missing | M |
| 34 | Duo | Both tap Start | "2 of 2 ready", then "Finding a table" with a ring: the pair searches together, and bots fill when the ring ends. | Has no paired-search state after Start. A shared table's Start starts that table (`queue/TablePanel.tsx:264-265`, `queue/tableText.ts:121-127`). Pairs are matched today only from a party queue entry. | missing | M |
| 35 | Duo | A table with two open seats | "Join Mei & Sam" with Join (ring) and Keep looking. The pair joins together. | Exists, labelled "Join together" (`queue/tableText.ts:58-60`), with "your Duo partner" sub-lines (`queue/TablePanel.tsx:48`). | cosmetic | S |
| 36 | Duo | Before the game: tap Leave | Sheet "Leave the Duo?" / "Alice keeps the table." | There is no Duo context in the leave copy; the queue sheet says "Leave the table?" (`components/leaveCopy.ts:14-23,68-72`). The party chip has its own instant Leave with no sheet (`queue/Ranked.tsx:40,53`). | missing | S |

Rows checked and matching main (no gap):
- three tabs on phone and wide (`home/HomeShell.tsx:64-67,137-140`);
- the Stats/Games switch inside Me (`components/MePage.tsx:24-27,382`);
- one settings list in Me and ⋯ (`components/SettingsList.tsx:23-34`, `components/HudMenu.tsx:118-133`);
- guest Me with "Guest" and Edit name opening the shared sheet (`components/MePage.tsx:278-313`);
- Me stats exclude offline games: they are server-only (`ratings/api` fetch) and the offline server writes no stats;
- reconnecting pill, Retry at 10 s, full screen at 60 s (`components/ConnectionPill.tsx:9-11,52-60`);
- an offline game stays offline (`components/OfflinePlay.tsx:92-106`);
- offline leave "This offline game ends." (`components/leaveCopy.ts:80`) and the "Offline" HUD chip (`components/Hud.tsx:242-243`);
- "Games 1–0" HUD chip after the first game won (`components/Hud.tsx:158-165,300`);
- game-over card removed;
- timer rings with seconds, thin ring on others' pills (`components/MoveClock.tsx:7-19`, `components/Table.tsx:174,543,573`);
- the queue strip shows the bots' countdown ring (`queue/QueueBar.tsx:17-24`);
- table code, Invite link and Allow joiners on every Play table (`queue/TablePanel.tsx:435-469`);
- ranked has no Starting level row (`:442`);
- chat row on Play tables (`:226,247`);
- seat moving before Start (`:78-81`);
- the "1 of 2 ready" / "Waiting for Alice" button (`queue/tableText.ts:121-127`);
- Last trick "wins · N pts" (`components/LastTrickPanel.tsx:18-19`);
- "Bury 8 cards (n/8)" (`components/Table.tsx:580`).

## Counts
36 gaps: **7 missing** (#18, 25, 27, 32, 33, 34, 36), **12 different** (#1, 4, 7, 8, 10, 11, 12, 13, 14, 17, 20, 31), **17 cosmetic** (#2, 3, 5, 6, 9, 15, 16, 19, 21–24, 26, 28–30, 35).

## Build next (ranked)
1. **#32–34, #36 Duo is a table.** Held partner seat, link into the held seat, paired search after Start, and the "Leave the Duo?" sheet. It is the newest spec decision, needs server work, and is the only L.
2. **#12 Allow joiners for the opener only.** Change both the client gate and the server rule, then show joiners a summary line.
3. **#25 Offline button at the table.** Show "Play offline with the bots" on the 60 s screen in a game too, and shorten the body (also fixes #26).
4. **#7, #10, #11 One status line.** Drop "Bots in" from the status lines and the "Add bots in 1:00" row, leaving the ring as the timer. Coordinate with the rings PR.
5. **#4 Hide the code box while seated** (phone and wide).
6. **#13 Start labels.** Use "Start" for everyone, with Start now as the opener's after 30 s on queue tables as on rooms.
7. **#18 "Casual" HUD chip** (and #19 Ranked for guests).
8. **#27 Greyed Chat row** on the offline panel.
9. **#1 Remove the guest line and the How to play link** from Play (copy rule).
10. **#20 Round-end card copy and layout** to the mock's one line with buttons in a row (also covers #30).
11. **#17 Remove SeatTakeover and "Table is full"** in favour of the Join panel.
12. Copy batch: #5, 6, 9, 15, 16, 21–24, 29 (one S PR).
