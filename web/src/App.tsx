import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { GameState, RoomMsg } from "./protocol";
import { routeOf } from "./errorCodes";
import { decideIntent, intentToJoin } from "./intent";
import type { ConnStatus } from "./ws";
import { OFFLINE, useOffline } from "./offlineMode";
import { clearSavedRoom, conn, getResumeToken, getSavedName, getSavedRoom, saveRoom } from "./ws";
import { announceState, prewarmAudio, resetAnnouncer } from "./audio";
import { auth, useAuth } from "./auth";
import { guestName } from "./guestName";
import { takeMovedSignIn } from "./originMove";
import Lobby from "./components/Lobby";
import LeaveSheet from "./components/LeaveSheet";
import type { LeaveContext } from "./components/leaveCopy";
import Table from "./components/Table";
import GamesList from "./components/GamesList";
import { useGamesRoute } from "./replay/route";
import { setContinueHandler } from "./replay/continueGame";
import HowTo from "./howto/HowTo";
import { closeHowto, useHowtoRoute } from "./howto/route";
import { randomName } from "./randomName";
import SupportPage from "./support/SupportPage";
import PrivacyPage from "./support/PrivacyPage";
import TermsPage from "./support/TermsPage";
import { useInfoRoute } from "./support/route";
import Leaderboard from "./components/Leaderboard";
import MePage from "./components/MePage";
import HomeShell from "./home/HomeShell";
import CollectionPage from "./components/CollectionPage";
import { IdentitySheet } from "./components/GuestChip";
import { openTab, useHomeRoute } from "./home/route";
import { noteReceipt } from "./stateReceipt";
import { haptic, hideSplash, lockFor, setBackGesture, setGameMode, startShell } from "./native";
import { usePhoneLayout } from "./phoneLayout";
import { showToast as toastShow } from "./toast";
import Toast from "./components/Toast";
import ConnectionPill from "./components/ConnectionPill";
import QueueLayer from "./queue/QueueLayer";
import { queue, useQueue } from "./queue/store";
import type { QueueView } from "./queue/store";
import { queueLeaveContext } from "./queue/tableModel";
import { firstJoinerText } from "./queue/tableText";
import { offlineGame, startName } from "./components/offlineGame";
import { codes, useCodes } from "./codeJoin";
import { isZh, t, tIn, useLocale } from "./i18n";
import type { MessageKey } from "./i18n";
import { MESSAGES } from "./i18n/messages";
import { useNearbyHostLeft, useNearbyUi } from "./nearbyGate";
import { setSeatSafe, startReloadGate } from "./reloadGate";
import { rounds } from "./roundTelemetry";
import WatchScreen from "./watch/WatchScreen";
import { watch, useWatching } from "./watch/store";
import { useCollection } from "./companion/feature";

/** What leaving the seat you hold costs, for the sheet a link to another
 *  table opens: the game in play, else the Play table as its panel says it. */
function linkLeaveContext(game: GameState | null, q: QueueView): LeaveContext {
  if (game) return { kind: "game", ranked: !!game.matched, guest: game.guest === true,
                     betweenRounds: game.phase === "round_end" };
  return queueLeaveContext(q);
}

/** The server's fixed refusals and notices by their English: each has a zh
 *  twin in the table. A text with a name or a number in it has none and
 *  stays the server's. */
const SERVER_TEXT = new Map((Object.keys(MESSAGES) as MessageKey[])
  .filter((k) => k.startsWith("roundend.srv")).map((k) => [tIn("en", k), k]));

/** A server's text in the current language: English is always the
 *  server's own words. */
function serverText(message: string): string {
  const key = isZh() ? SERVER_TEXT.get(message) : undefined;
  return key ? t(key) : message;
}

/** A `left` frame's text: a nearby host's own leave by its reason, which
 *  the joiner says in its own language, else the server's. */
function leftText(reason: string, message: string): string {
  return reason === "host_left" ? t("nearby.hostLeft") : serverText(message);
}

export default function App() {
  // a language change in Me redraws the whole app in place, game included
  useLocale();
  const [status, setStatus] = useState<ConnStatus>("closed");
  const [room, setRoom] = useState<RoomMsg | null>(null);
  const [game, setGame] = useState<GameState | null>(null);
  // Whether the announcer has been seeded with a first game state.
  const seededRef = useRef(false);
  // True from an automatic resume of the saved room until the server answers it.
  const resumingRef = useRef(false);
  // A refused move already asked for the seat back once since the last state.
  const reaskedRef = useRef(false);
  // A saved game and its replays, How to play, the info pages and the
  // Leaderboard and Me tabs are routes that sit over whatever screen is
  // live; the socket and any game in progress keep running underneath.
  // `#/games` (the list) is the Games tab, or Me's Games section on a phone.
  const gamesPage = useGamesRoute();
  const gamesRoute = gamesPage && gamesPage.page !== "list" ? gamesPage : null;
  const howtoRoute = useHowtoRoute();
  const infoRoute = useInfoRoute();
  // the Collection's hash opens Play for a viewer it is not shown to
  const routed = useHomeRoute();
  const collection = useCollection();
  const homeRoute = routed?.tab === "collection" && !collection ? null : routed;

  useEffect(() => {
    const showToast = (message: string, info = false) => {
      toastShow(message, { info });
      haptic(info ? "declare" : "error");
    };

    // Common teardown when leaving a game: drop game state, reset the
    // announcer, and (unless staying in the room) forget the room entirely.
    const resetToLobby = (opts?: { keepRoom?: boolean }) => {
      if (!opts?.keepRoom) {
        clearSavedRoom();
        setRoom(null);
        conn.clearChat();   // next room starts with an empty log
        // the table a link's question was about is gone: the link goes ahead
        codes.release();
      }
      setGame(null);
      seededRef.current = false;
      resetAnnouncer();
    };

    // Ask for the saved seat back; false when nothing is saved.
    const resumeSaved = (): boolean => {
      const join = intentToJoin(decideIntent({
        savedRoom: getSavedRoom(), savedName: getSavedName() || "Player", savedToken: getResumeToken(),
      }));
      if (!join) return false;
      resumingRef.current = true;
      conn.send(join);
      return true;
    };

    const unsubStatus = conn.subscribeStatus((s) => {
      setStatus(s);
      if (s !== "open") return;
      // the on-device server knows no saved room and no link: Play starts there
      if (OFFLINE) return;
      // the app's Play offline must work once the network has gone: its server loads now
      offlineGame.prefetch();
      // this socket is leaving the page's last table: no saved seat is resumed on it
      if (conn.deliversOwedLeave()) return;
      // ONE decision, made in intent.ts and unit-tested there. An invite opens
      // the Lobby's Join panel and never joins by itself, so the only thing to
      // act on here is a saved resume.
      const params = new URLSearchParams(window.location.search);
      // One link kind: an older ?room= or ?party= link already reads as ?code=.
      const link = params.get("code")?.toUpperCase() ?? null;
      // A link while this device holds a room seat goes back to that seat
      // first: its own table's link is that seat, and the code store asks
      // before leaving it for another table's.
      const saved = getSavedRoom()?.toUpperCase() ?? null;
      const intent = decideIntent({
        invite: link && saved === null ? { room: link } : null,
        savedRoom: getSavedRoom(),
        // A signed-in player keeps no name on the device, and a socket that
        // has just signed out must still ask for its seat back, so the server
        // can say what holds it; the server names an account itself.
        savedName: getSavedName() || "Player",
        savedToken: getResumeToken(),
      });
      if (intent.kind !== "resume") return;   // Lobby owns invite + pending
      const join = intentToJoin(intent);
      if (join) { resumingRef.current = true; conn.send(join); }
    });
    const unsubMsg = conn.subscribe((msg) => {
      switch (msg.type) {
        case "room":
          resumingRef.current = false;
          setRoom(msg);
          // "room" comes once, as the room's game starts and ahead of its
          // first state, so any game still rendered is an older one
          resetToLobby({ keepRoom: true });
          saveRoom(msg.room);
          break;
        case "state":
          resumingRef.current = false;
          reaskedRef.current = false;
          // A seat taken in a game already on gets no "room" frame: its first
          // state is what the device remembers it by, so a reconnect resumes it.
          if (!OFFLINE && !msg.joining_you && msg.room && getSavedRoom() !== msg.room) saveRoom(msg.room);
          announceState(msg, !seededRef.current);
          seededRef.current = true;
          // the socket that sent it, for the round end's live check
          noteReceipt(msg, conn.generation);
          setGame(msg);
          break;
        case "error": {
          // a peek's refusal is the code store's to say, and answers no resume
          if (msg.peek !== undefined) break;
          // a move refused while a resume is in flight is not the resume's
          // answer: the flag stays up until that answer arrives
          if (msg.code === "no_room" && resumingRef.current) break;
          const wasResuming = resumingRef.current;
          resumingRef.current = false;
          // a link to the seat this answer refused goes on to its peek
          if (wasResuming) codes.resumeRefused();
          // the one ask for a lost seat was refused: the table it showed is
          // gone, so it goes now, not on the next refused move
          if (wasResuming && reaskedRef.current && msg.code !== "ranked_queue_only") {
            reaskedRef.current = false;
            resetToLobby();
            showToast(t("roundend.toastNoTable"));
            break;
          }
          // the queue and Join panels say their own codes: one status, not two
          const says = routeOf(msg).says;
          if (says !== "toast" && says !== "app") break;
          if (msg.code === "no_room") {
            // A move answered "not in a room" while a table is shown: the
            // socket lost its seat. Ask for it back once, else go to Play.
            if (!seededRef.current) { showToast(serverText(msg.message)); break; }
            if (!reaskedRef.current) {
              reaskedRef.current = true;
              if (resumeSaved()) break;
            }
            resetToLobby();
            showToast(t("roundend.toastNoTable"));
          } else if (msg.code === "start_failed") {
            // a queue game with bots that failed to start was unwound on the server
            resetToLobby();
            showToast(serverText(msg.message));
          } else if (msg.code === "room_not_found") {
            // The room no longer exists (server restart / expiry). Stop
            // retrying it on reconnect and return to the lobby (name kept).
            resetToLobby();
            // A silent resume of a room that expired or was dropped by a restart is not news to the
            // player; only a join they asked for gets told.
            if (!wasResuming) showToast(t("roundend.toastGameEnded"));
            resumingRef.current = false;
          } else if (msg.code === "ranked_queue_only" && wasResuming) {
            // A saved ranked seat belongs to an account; this socket is a guest
            // (signed out mid-game). The table goes for Play, and the saved
            // room stays so signing back in returns there.
            setRoom(null);
            setGame(null);
            seededRef.current = false;
            resetAnnouncer();
            openTab("play");
            showToast(t("roundend.toastSignInAgain"));
          } else {
            showToast(serverText(msg.message));
          }
          break;
        }
        case "first_joiner":
          // a game started alone turns shared: said once, politely
          showToast(firstJoinerText(msg), true);
          break;
        case "report_received":
          showToast(msg.message);
          break;
        case "left":
          // Intentional exit confirmed: forget the room (name kept) so
          // reconnects don't auto-rejoin, and route back to the lobby.
          resetToLobby();
          if (msg.reason === "removed") {
            openTab("play");
            showToast(msg.message !== undefined ? serverText(msg.message) : t("roundend.toastRemoved"));
          } else if (msg.reason && msg.message) {
            // an open-table seat that went back to its owner, or to a newcomer
            openTab("play");
            showToast(leftText(msg.reason, msg.message));
          }
          break;
        case "event":
          // Optional animation hints; safe to ignore.
          break;
        case "match_cancelled":
          // A matched room that failed to start was unwound on the server,
          // even if its frames already arrived: back to the lobby, queued.
          if (msg.reason === "server_error") resetToLobby();
          break;
      }
    });
    conn.start();
    return () => {
      unsubStatus();
      unsubMsg();
    };
  }, []);

  // The iOS app keeps lobby screens portrait and the table landscape on an
  // iPhone; everywhere else these are no-ops.
  // watching a table draws a table too, from the Play tab with no game
  const watching = useWatching();
  const watchShown = watching !== null && game === null && room === null
    && !gamesRoute && !howtoRoute && !infoRoute && !homeRoute;
  // a seat anywhere ends watching: the table you sit at is the one shown
  useEffect(() => { if (watching && (game !== null || room !== null)) watch.close(); }, [watching, game, room]);
  const atTable =
    (game !== null && !gamesRoute && !howtoRoute && !infoRoute && !homeRoute) || watchShown;
  useEffect(() => { void lockFor(atTable ? "game" : "lobby"); }, [atTable]);
  // the app's edge swipe back is off at the table, so a live game is never
  // covered by an earlier page by accident
  useEffect(() => { void setBackGesture(!atTable); }, [atTable]);
  // the screen stays awake and the home gesture needs a second swipe at the table
  useEffect(() => { void setGameMode(atTable); }, [atTable]);
  // a portrait phone browser gets the table turned sideways instead
  const { rotated } = usePhoneLayout(atTable);
  // the launch splash covers the WebView until the first screen has painted
  useEffect(() => { requestAnimationFrame(() => hideSplash()); }, []);
  useEffect(() => startReloadGate(), []);
  // keyboard accessory bar off, keyboard-open class, status-bar tap to top
  useEffect(() => { startShell(); }, []);
  // the audio context costs a long task to create: make it before any tap
  useEffect(() => { prewarmAudio(); }, []);
  // Offline is a state of this page: the socket swaps servers in place.
  const offline = useOffline();
  // one config + me round trip, once the page is online; a server without
  // sign-in answers "off"
  useEffect(() => { if (!offline) void auth.init(); }, [offline]);
  // a session the app's move to its own domain did not carry asks for sign-in once
  useEffect(() => {
    if (offline) return;
    void auth.init().then(() => auth.settled()).then(() => {
      if (takeMovedSignIn(auth.state?.status)) guestName.open("moved");
    });
  }, [offline]);

  const inRoom = room !== null || game !== null;
  // every state and room frame, shown or not, for the round telemetry
  useEffect(() => { rounds.noteRoom(room); }, [room]);
  useEffect(() => { rounds.observe(game); }, [game]);
  const q = useQueue();
  const account = useAuth();
  const seatedAnywhere = inRoom || q.queued;
  // a newer page build loads only off every table and queue: a closed
  // socket at a round's end leaves the ready quorum, and the next round can
  // start without this player
  const seatSafe = !seatedAnywhere;
  useEffect(() => { setSeatSafe(seatSafe); }, [seatSafe]);
  // a link to another table while you sit at one asks first
  const link = useCodes();
  // a nearby joiner whose host stayed away past its window
  const nearbyUi = useNearbyUi();
  const hostLeft = useNearbyHostLeft();
  const linkPrompt = link?.step === "ask" ? link.code : null;
  // Continue on a saved game: a new room with bots in the other seats, which
  // the server starts at once. Only from outside a room, so no game in
  // progress is left by a tap.
  useEffect(() => {
    setContinueHandler((gameId) => {
      rounds.noteEntry("friend");
      conn.send({ type: "create_room", name: getSavedName(), resume_from: gameId, start: true });
      openTab("play");
    }, status === "open" && !inRoom && !offline);
    return () => setContinueHandler(null, false);
  }, [status, inRoom, offline]);
  // How to play's last step deals a practice round: a created room against
  // Beginner bots, as Play offline's Start makes one (casual, no move
  // timer). Only from outside every table and queue, so nothing is left by
  // a tap.
  const canPractice = status === "open" && !seatedAnywhere;
  const practice = () => {
    if (!guestName.name.trim() && account.status !== "in") guestName.fill(randomName());
    // Offline the game stays on this device, as the offline table's Start's
    // does; the table itself is not opened, so the Play tab that shows while
    // the deal is on its way does not take it for a table already played and
    // left (OfflinePlay.tsx).
    if (offline) clearSavedRoom();
    else rounds.noteEntry("queue");
    conn.send({ type: "create_room", name: startName(account), start: true, bot_level: "beginner" });
    closeHowto();
  };
  // The tabs' pages keep the tab bars over a game too; the Your table pill
  // on them leads back to the game.
  const tabPage = homeRoute === null ? null
    : homeRoute.tab === "leaderboard" ? <Leaderboard />
    : homeRoute.tab === "collection" ? <CollectionPage kind={homeRoute.kind ?? null} />
    : <MePage section={homeRoute.section} />;

  let screen: ReactNode;
  // Play with no table: its presence line is the connection status, not the
  // pill. A sign-in server that could not be reached leaves Play without that
  // line, so the pill stays.
  let playNoTable = false;
  // exactly one toast is mounted: the table's, else this one at the page's top
  let screenIsTable = false;
  if (infoRoute) {
    screen = infoRoute === "support" ? <SupportPage /> : infoRoute === "terms" ? <TermsPage /> : <PrivacyPage />;
  } else if (howtoRoute) {
    screen = <HowTo route={howtoRoute} game={game} onPractice={canPractice ? practice : null} />;
  } else if (gamesRoute) {
    screen = <GamesList route={gamesRoute} />;
  } else if (homeRoute) {
    screen = (
      <HomeShell active={homeRoute.tab} section={homeRoute.tab === "me" ? homeRoute.section : undefined}
                 seatedAt={game ? "game" : null}>
        {tabPage}
      </HomeShell>
    );
  } else if (watchShown && watching) {
    screen = <WatchScreen mode={watching.mode} />;
  } else if (game) {
    // the table draws the one toast in its own spot (Toast.tsx)
    screenIsTable = true;
    screen = <Table state={game} />;
  } else {
    // offline, the same Play tab: its table's room is filled with bots and dealt from there
    playNoTable = !seatedAnywhere && account.status !== "error";
    screen = (
      <HomeShell active="play">
        <Lobby status={status} room={room} />
      </HomeShell>
    );
  }

  return (
    <div className={`app${rotated ? " rotated" : ""}${offline ? " offline" : ""}`}>
      {screen}
      {hostLeft && nearbyUi ? (
        <ConnectionPill status={status} inRoom={inRoom} inGame={false}
                        ended={{ title: nearbyUi.NEARBY_COPY.hostLeft, onLeave: () => nearbyUi.nearbyJoin.cancel() }} />
      ) : offline && !inRoom ? null : <ConnectionPill status={status} inRoom={inRoom} inGame={game !== null} pill={!playNoTable} />}
      {screenIsTable ? null : <Toast />}
      {/* the one identity sheet: a guest's chip, Edit name and every Sign in */}
      <IdentitySheet />
      {linkPrompt && status === "open" && seatedAnywhere ? (
        // a link to another table while seated: the leave sheet, asked about the link
        <LeaveSheet context={linkLeaveContext(game, q)} title={t("roundend.leaveToJoin", { code: linkPrompt })}
                    onLeave={() => {
                      if (room === null && game === null) queue.leave();
                      else {
                        if (game) rounds.left();
                        conn.send({ type: "table_leave" });
                      }
                      codes.leaving();
                    }}
                    onStay={() => codes.cancel()} />
      ) : null}
      <QueueLayer />
    </div>
  );
}
