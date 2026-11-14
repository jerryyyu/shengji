import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { GameState, RoomMsg } from "./protocol";
import { decideIntent, intentToJoin } from "./intent";
import type { ConnStatus } from "./ws";
import { OFFLINE, clearSavedRoom, conn, getResumeToken, getSavedName, getSavedRoom, saveRoom } from "./ws";
import { announceState, prewarmAudio, resetAnnouncer } from "./audio";
import { auth } from "./auth";
import Lobby from "./components/Lobby";
import Room from "./components/Room";
import Table from "./components/Table";
import GamesList from "./components/GamesList";
import { useGamesRoute } from "./replay/route";
import { setContinueHandler } from "./replay/continueGame";
import HowTo from "./howto/HowTo";
import { useHowtoRoute } from "./howto/route";
import SupportPage from "./support/SupportPage";
import PrivacyPage from "./support/PrivacyPage";
import { useInfoRoute } from "./support/route";
import Leaderboard from "./components/Leaderboard";
import MePage from "./components/MePage";
import HomeShell from "./home/HomeShell";
import { openTab, useHomeRoute } from "./home/route";
import { haptic, hideSplash, lockFor, setBackGesture, setGameMode, startShell } from "./native";
import { usePhoneLayout } from "./phoneLayout";
import { TOAST_MS, makeToast } from "./toast";
import type { Toast } from "./toast";
import ToastView from "./components/ToastView";
import ConnectionPill from "./components/ConnectionPill";
import QueueLayer from "./queue/QueueLayer";
import { firstJoinerText } from "./queue/tableText";
import { askRoomLeave, useRoomBack } from "./roomBack";

// Offline play (no game server): its Play tab loads with the local server.
const OfflineHome = lazy(() => import("./offline/server/ui").then((m) => ({ default: m.OfflineHome })));

export default function App() {
  const [status, setStatus] = useState<ConnStatus>("closed");
  const [room, setRoom] = useState<RoomMsg | null>(null);
  const [game, setGame] = useState<GameState | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);
  const toastTimer = useRef<number | null>(null);
  // Single-player orchestration: when armed (via Lobby's "Play vs bots"),
  // each lobby `room` message advances the fill-with-bots-then-start chain.
  const autoFill = useRef(false);
  // Whether the announcer has been seeded with a first game state.
  const seededRef = useRef(false);
  // True from an automatic resume of the saved room until the server answers it.
  const resumingRef = useRef(false);
  // A saved game and its replays, How to play, the info pages and the
  // Leaderboard and Me tabs are routes that sit over whatever screen is
  // live; the socket and any game in progress keep running underneath.
  // `#/games` (the list) is the Games tab, or Me's Games section on a phone.
  const gamesPage = useGamesRoute();
  const gamesRoute = gamesPage && gamesPage.page !== "list" ? gamesPage : null;
  const howtoRoute = useHowtoRoute();
  const infoRoute = useInfoRoute();
  const homeRoute = useHomeRoute();

  useEffect(() => {
    const showToast = (message: string, info = false) => {
      // a fresh id per showing: the same error again is shown again
      setToast(makeToast(message, info));
      haptic(info ? "declare" : "error");
      if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
      toastTimer.current = window.setTimeout(() => {
        toastTimer.current = null;
        setToast(null);
      }, TOAST_MS);
    };

    // Common teardown when leaving a game: drop game state, reset the
    // announcer, and (unless staying in the room) forget the room entirely.
    const resetToLobby = (opts?: { keepRoom?: boolean }) => {
      if (!opts?.keepRoom) {
        clearSavedRoom();
        setRoom(null);
        conn.clearChat();   // next room starts with an empty log
      }
      setGame(null);
      seededRef.current = false;
      resetAnnouncer();
    };

    const unsubStatus = conn.subscribeStatus((s) => {
      setStatus(s);
      if (s !== "open") return;
      // ONE decision, made in intent.ts and unit-tested there. An invite is
      // handled by the Lobby (it must not auto-submit without a name), so the
      // only thing to act on here is a saved resume.
      const params = new URLSearchParams(window.location.search);
      // a ?code= link may name a room, so it outranks a saved room as ?room= does
      const inviteRoom = params.get("room") ?? params.get("code");
      const intent = decideIntent({
        invite: inviteRoom ? { room: inviteRoom,
                               name: params.get("name") ?? undefined } : null,
        savedRoom: getSavedRoom(),
        // A signed-in player keeps no name on the device, and a socket that
        // has just signed out must still ask for its seat back, so the server
        // can say what holds it; the server names an account itself.
        savedName: getSavedName() || "Player",
        savedToken: getResumeToken(),
      });
      if (intent.kind !== "resume") return;   // Lobby owns invite + pending
      const join = intentToJoin(intent);
      if (join) { resumingRef.current = true; conn.send(join as never); }
    });
    const unsubMsg = conn.subscribe((msg) => {
      switch (msg.type) {
        case "room":
          resumingRef.current = false;
          setRoom(msg);
          // "room" is only sent while the room is in lobby state, so any
          // previously rendered game is stale (e.g. rejoined after the game
          // ended) — drop it so we route to the Room screen.
          resetToLobby({ keepRoom: true });
          saveRoom(msg.room);
          // Auto-fill chain: one send per room broadcast, host only, so
          // there is never a double-send. Each add_bot triggers the next
          // room message; at 4 players start once and disarm.
          if (autoFill.current && msg.you === msg.host) {
            if (msg.players.length < 4) {
              conn.send({ type: "add_bot" });
            } else {
              autoFill.current = false;
              conn.send({ type: "start_game" });
            }
          }
          break;
        case "state":
          resumingRef.current = false;
          announceState(msg, !seededRef.current);
          seededRef.current = true;
          setGame(msg);
          break;
        case "error":
          const wasResuming = resumingRef.current;
          resumingRef.current = false;
          autoFill.current = false; // abort single-player orchestration
          if (msg.code === "not_in_party") {
            // a pair the server no longer holds: the queue store drops the chip
            break;
          }
          if (msg.code === "account_in_game" || msg.code === "panel_changed"
              || msg.code === "pair_seats_fixed" || msg.code === "already_ready") {
            // the queue panel says these in its own place, or (a panel that
            // changed under a tap) refreshes without a word
            break;
          }
          if (msg.code === "start_failed") {
            // a queue game with bots that failed to start was unwound on the server
            resetToLobby();
            showToast(msg.message);
          } else if (msg.code === "room_not_found") {
            // The room no longer exists (server restart / expiry). Stop
            // retrying it on reconnect and return to the lobby (name kept).
            resetToLobby();
            // A silent resume of a room that expired or was dropped by a restart is not news to the
            // player; only a join they asked for gets told.
            if (!wasResuming) showToast("That game has ended.");
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
            showToast("Sign in again to return to your game.");
          } else {
            showToast(msg.message);
          }
          break;
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
            showToast(msg.message ?? "The host removed you from the room.");
          } else if (msg.reason && msg.message) {
            // an open-table seat that went back to its owner, or to a newcomer
            openTab("play");
            showToast(msg.message);
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
    // one config + me round trip; a server without sign-in answers "off"
    if (!OFFLINE) void auth.init();
    return () => {
      unsubStatus();
      unsubMsg();
      if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    };
  }, []);

  // The iOS app keeps lobby screens portrait and the table landscape on an
  // iPhone; everywhere else these are no-ops.
  const atTable =
    game !== null && !gamesRoute && !howtoRoute && !infoRoute && !homeRoute;
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
  // keyboard accessory bar off, keyboard-open class, status-bar tap to top
  useEffect(() => { startShell(); }, []);
  // the audio context costs a long task to create: make it before any tap
  useEffect(() => { prewarmAudio(); }, []);

  const inRoom = room !== null || game !== null;
  // back (or the edge swipe) from the room screen asks to leave, as its Leave does
  const roomShowing =
    room !== null && game === null && !gamesRoute && !howtoRoute && !infoRoute && !homeRoute;
  useRoomBack(roomShowing, askRoomLeave);
  // Continue on a saved game: a new room with bots in the other seats, which
  // the auto-fill chain then starts (the server already filled it). Only
  // from outside a room, so no game in progress is left by a tap.
  useEffect(() => {
    setContinueHandler((gameId) => {
      autoFill.current = true;
      conn.send({ type: "create_room", name: getSavedName(), resume_from: gameId });
      openTab("play");
    }, status === "open" && !inRoom);
    return () => setContinueHandler(null, false);
  }, [status, inRoom]);
  // Over a room or a game the tabs' pages show without the tab bars and
  // with a way back; at home the bars frame them.
  const backToGame = inRoom ? () => openTab("play") : undefined;
  const tabPage = homeRoute === null ? null
    : homeRoute.tab === "leaderboard" ? <Leaderboard onBack={backToGame} />
    : <MePage section={homeRoute.section} onBack={backToGame} />;

  let screen: ReactNode;
  if (infoRoute) {
    screen = infoRoute === "support" ? <SupportPage /> : <PrivacyPage />;
  } else if (howtoRoute) {
    screen = <HowTo route={howtoRoute} />;
  } else if (gamesRoute) {
    screen = <GamesList route={gamesRoute} />;
  } else if (homeRoute && inRoom) {
    screen = tabPage;
  } else if (homeRoute) {
    screen = (
      <HomeShell active={homeRoute.tab} section={homeRoute.tab === "me" ? homeRoute.section : undefined}>
        {tabPage}
      </HomeShell>
    );
  } else if (game) {
    // at the table the toast is placed against the table's own rows
    screen = <Table state={game} toast={toast} />;
  } else if (OFFLINE) {
    // the offline table's room is filled with bots and dealt from the Play tab
    screen = (
      <Suspense fallback={null}>
        <OfflineHome status={status} error={toast?.text ?? null} room={room?.room ?? null}
                     onArmAutoFill={() => { autoFill.current = true; }} />
      </Suspense>
    );
  } else if (room) {
    screen = <Room room={room} />;
  } else {
    screen = (
      <HomeShell active="play">
        <Lobby
          status={status}
          error={toast?.text ?? null}
          onArmAutoFill={() => {
            autoFill.current = true;
          }}
        />
      </HomeShell>
    );
  }

  return (
    <div className={`app${rotated ? " rotated" : ""}${OFFLINE ? " offline" : ""}`}>
      {screen}
      {OFFLINE && !inRoom ? null : <ConnectionPill status={status} inRoom={inRoom} inGame={game !== null} />}
      {toast && inRoom && !atTable ? <ToastView key={toast.id} toast={toast} /> : null}
      <QueueLayer status={status} />
    </div>
  );
}
