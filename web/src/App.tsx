import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { GameState, RoomMsg } from "./protocol";
import type { ConnStatus } from "./ws";
import { clearSavedRoom, conn, getResumeToken, getSavedName, getSavedRoom, saveRoom } from "./ws";
import { announceState, resetAnnouncer } from "./audio";
import Lobby from "./components/Lobby";
import Room from "./components/Room";
import Table from "./components/Table";

const TOAST_MS = 4000;

export default function App() {
  const [status, setStatus] = useState<ConnStatus>("closed");
  const [room, setRoom] = useState<RoomMsg | null>(null);
  const [game, setGame] = useState<GameState | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | null>(null);
  // Single-player orchestration: when armed (via Lobby's "Play vs bots"),
  // each lobby `room` message advances the fill-with-bots-then-start chain.
  const autoFill = useRef(false);
  // Whether the announcer has been seeded with a first game state.
  const seededRef = useRef(false);

  useEffect(() => {
    const showToast = (message: string) => {
      setToast(message);
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

    // Single owner of connection intent, in precedence order:
    //   invite link > explicit action already in flight > saved session.
    // An invite must never be overridden by whatever room we were last in.
    const unsubStatus = conn.subscribeStatus((s) => {
      setStatus(s);
      if (s !== "open") return;
      const invited = new URLSearchParams(window.location.search).get("room");
      if (invited) return;              // Lobby owns the invite flow
      const room = getSavedRoom();
      const name = getSavedName();
      if (room && name) {
        const token = getResumeToken();
        conn.send({ type: "join_room", room, name, ...(token ? { token } : {}) });
      }
    });
    const unsubMsg = conn.subscribe((msg) => {
      switch (msg.type) {
        case "room":
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
          announceState(msg, !seededRef.current);
          seededRef.current = true;
          setGame(msg);
          break;
        case "error":
          autoFill.current = false; // abort single-player orchestration
          if (msg.code === "room_not_found") {
            // The room no longer exists (server restart / expiry). Stop
            // retrying it on reconnect and return to the lobby (name kept).
            resetToLobby();
            showToast("That game has ended.");
          } else {
            showToast(msg.message);
          }
          break;
        case "left":
          // Intentional exit confirmed: forget the room (name kept) so
          // reconnects don't auto-rejoin, and route back to the lobby.
          resetToLobby();
          break;
        case "event":
          // Optional animation hints; safe to ignore.
          break;
      }
    });
    conn.start();
    return () => {
      unsubStatus();
      unsubMsg();
      if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    };
  }, []);

  let screen: ReactNode;
  if (game) {
    screen = <Table state={game} />;
  } else if (room) {
    screen = <Room room={room} />;
  } else {
    screen = (
      <Lobby
        status={status}
        error={toast}
        onArmAutoFill={() => {
          autoFill.current = true;
        }}
      />
    );
  }

  const inRoom = room !== null || game !== null;

  return (
    <div className="app">
      {screen}
      {status !== "open" && inRoom ? (
        <div className="reconnect-banner">
          <span className="conn-dot" /> Reconnecting…
        </div>
      ) : null}
      {toast && inRoom ? (
        <div className="toast" key={toast}>
          {toast}
        </div>
      ) : null}
      <div className="rotate-hint" aria-hidden="true">
        <div className="rotate-icon">📱</div>
        <div>Rotate your phone to play</div>
      </div>
    </div>
  );
}
