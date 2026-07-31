import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { GameState, RoomMsg } from "./protocol";
import type { ConnStatus } from "./ws";
import { conn, saveRoom } from "./ws";
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

  useEffect(() => {
    const showToast = (message: string) => {
      setToast(message);
      if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
      toastTimer.current = window.setTimeout(() => {
        toastTimer.current = null;
        setToast(null);
      }, TOAST_MS);
    };

    const unsubStatus = conn.subscribeStatus(setStatus);
    const unsubMsg = conn.subscribe((msg) => {
      switch (msg.type) {
        case "room":
          setRoom(msg);
          saveRoom(msg.room);
          break;
        case "state":
          setGame(msg);
          break;
        case "error":
          showToast(msg.message);
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
    screen = <Lobby status={status} error={toast} />;
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
