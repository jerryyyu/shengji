// What offline mode shows before its table: nothing to choose. Offline there
// is no chat, no sign-in, no saved games and no ratings, so it starts the one
// game it has, against three SmartBot seats, as soon as the in-page server
// answers. Lazy-loaded with the rest of offline play.
import { useEffect, useRef, useState } from "react";
import type { ConnStatus } from "../../ws";
import { clearSavedRoom, conn, getSavedName } from "../../ws";
import "./offline.css";

interface OfflineStartProps {
  status: ConnStatus;
  error: string | null;
  /** Arm App's fill-with-bots-then-start chain before creating the room. */
  onArmAutoFill: () => void;
}

/** Creates a room under the saved name and lets App fill it with bots and
 *  start it. Shown again after a game is left, it starts the next one. A
 *  failed start waits for Try again rather than retrying in a loop. */
export function OfflineStart({ status, error, onArmAutoFill }: OfflineStartProps) {
  const sent = useRef(false);
  // the toast that carries an error goes after a while; the failure stays until Try again
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => { if (error) setFailed(error); }, [error]);
  const start = () => {
    if (status !== "open") return;
    sent.current = true;
    setFailed(null);
    clearSavedRoom();
    onArmAutoFill();
    conn.send({ type: "create_room", name: getSavedName().trim() || "Player" });
  };
  useEffect(() => {
    if (status === "open" && !sent.current) start();
  });
  return (
    <div className="screen offline-start" aria-busy={!failed || undefined}>
      {failed ? (
        <div className="offline-start-error" role="alert">
          <p>{failed}</p>
          <button className="btn gold" onClick={start}>Try again</button>
        </div>
      ) : null}
    </div>
  );
}
