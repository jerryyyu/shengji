import { useCallback, useEffect, useState } from "react";
import type { ConnStatus } from "../ws";
import { conn } from "../ws";
import { offlineGame } from "./offlineGame";

/** A short blip reconnects on its own; Retry joins the pill only after this. */
export const RETRY_AFTER_MS = 10_000;
/** Long enough that a tunnel or a lift does not trigger the full screen. */
export const LOST_AFTER_MS = 60_000;

export type ConnPhase = "open" | "waiting" | "retry" | "lost";

/** How long the socket has been short of "open", as a phase, and a retry
 *  that reconnects at once and starts the wait over. The socket's own
 *  backoff keeps reconnecting underneath; this only decides what is shown. */
function useConnPhase(status: ConnStatus): [ConnPhase, () => void] {
  const open = status === "open";
  const [phase, setPhase] = useState<ConnPhase>(open ? "open" : "waiting");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (open) { setPhase("open"); return; }
    setPhase("waiting");
    const retry = window.setTimeout(() => setPhase("retry"), RETRY_AFTER_MS);
    const lost = window.setTimeout(() => setPhase("lost"), LOST_AFTER_MS);
    return () => { window.clearTimeout(retry); window.clearTimeout(lost); };
  }, [open, attempt]);
  const retry = useCallback(() => {
    setAttempt((n) => n + 1);
    conn.reconnect();
  }, []);
  return [open ? "open" : phase, retry];
}

interface Props {
  status: ConnStatus;
  /** In a room or a game: the pill sits below the table's header. */
  inRoom: boolean;
  /** A game in progress, which a bot plays on while this device is away. */
  inGame: boolean;
}

/** The one connection surface, in the lobby and at the table alike: a pill
 *  while the socket is down, with Retry after RETRY_AFTER_MS, and one full
 *  screen after LOST_AFTER_MS. Nothing shows while the socket is open. */
export default function ConnectionPill({ status, inRoom, inGame }: Props) {
  const [phase, retry] = useConnPhase(status);
  if (phase === "open") return null;
  if (phase === "lost") {
    return (
      <div className="conn-lost" role="alertdialog" aria-modal="true" aria-labelledby="conn-lost-title"
           aria-describedby="conn-lost-body">
        <div className="conn-lost-mark" aria-hidden="true">!</div>
        <h1 className="conn-lost-title" id="conn-lost-title">No connection</h1>
        <p className="conn-lost-body" id="conn-lost-body">
          {inGame
            ? "Your game goes on with a bot in your seat. You return to it when you are back online."
            : "The server cannot be reached. It keeps trying in the background."}
        </p>
        <button type="button" className="btn gold conn-lost-retry" onClick={retry}>Retry</button>
        {inRoom ? null : (
          <button type="button" className="btn conn-lost-bots" onClick={() => offlineGame.start()}>
            Play bots on this device
          </button>
        )}
      </div>
    );
  }
  // the first connect of a page load is not a drop: no socket has opened yet
  const label = conn.generation > 0 ? "Reconnecting…" : "Connecting…";
  return (
    <div className={`reconnect-banner${inRoom ? "" : " at-home"}${phase === "retry" ? " with-retry" : ""}`}
         role="status">
      <span className="conn-dot" />
      <span className="reconnect-text">{label}</span>
      {phase === "retry" ? (
        <button type="button" className="reconnect-retry" onClick={retry}>Retry</button>
      ) : null}
    </div>
  );
}
