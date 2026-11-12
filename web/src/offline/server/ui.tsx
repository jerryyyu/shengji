// What offline mode shows before its table: nothing to choose. Offline there
// is no chat, no sign-in, no saved games and no ratings, so it starts the one
// game it has, against three SmartBot seats, as soon as the in-page server
// answers. Lazy-loaded with the rest of offline play.
import { useEffect, useRef, useState } from "react";
import type { ConnStatus } from "../../ws";
import { clearSavedRoom, conn, getSavedName } from "../../ws";
import { offlineGame } from "../../components/offlineGame";
import HomeShell from "../../home/HomeShell";
import Lobby from "../../components/Lobby";
import { useOnline } from "../../useOnline";
import "./offline.css";

/** Whether this page has started its game. Offline mode plays one game per
 *  load: back at the start screen after it (a Leave, Back to lobby), the
 *  player goes home instead of into a new deal. */
let startedThisLoad = false;

interface OfflineStartProps {
  status: ConnStatus;
  error: string | null;
  /** Arm App's fill-with-bots-then-start chain before creating the room. */
  onArmAutoFill: () => void;
}

/** Creates a room under the saved name and lets App fill it with bots and
 *  start it. Shown again after that game, it goes to the home Play tab. A
 *  failed start waits for Try again rather than retrying in a loop.
 *
 *  The app's bundled page cannot reach the live site with no network (the
 *  shell would bring this page back, and a new deal with it), so there the
 *  Play tab is drawn here in its no-connection state: Play bots reloads this
 *  page for a fresh game, and the live site loads once the network is back. */
export function OfflineStart({ status, error, onArmAutoFill }: OfflineStartProps) {
  const sent = useRef(false);
  const online = useOnline();
  const inApp = location.protocol === "capacitor:";
  const done = startedThisLoad && !sent.current;
  // the toast that carries an error goes after a while; the failure stays until Try again
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => { if (error) setFailed(error); }, [error]);
  const start = () => {
    if (status !== "open") return;
    sent.current = true;
    startedThisLoad = true;
    setFailed(null);
    clearSavedRoom();
    onArmAutoFill();
    conn.send({ type: "create_room", name: getSavedName().trim() || "Player" });
  };
  useEffect(() => {
    if (sent.current) return;
    if (done) {
      if (online || !inApp) offlineGame.goOnline();
      return;
    }
    if (status === "open") start();
  });
  if (done && inApp && !online) {
    return (
      <HomeShell active="play">
        <Lobby status="closed" error={null} onArmAutoFill={() => {}} />
      </HomeShell>
    );
  }
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
