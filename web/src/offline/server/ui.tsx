// What offline mode shows instead of the online lobby, and the table's
// "practice" badge. Lazy-loaded with the rest of offline play. Offline there
// is no chat, no sign-in, no saved games and no ratings: the lobby offers one
// thing, a game against three SmartBot seats.
import type { ConnStatus } from "../../ws";
import { clearSavedRoom, conn, getSavedName } from "../../ws";
import LobbyPreview from "../../components/LobbyPreview";
import { openHowto } from "../../howto/route";
import "./offline.css";

/** The live site, for the app's bundled page to try again when back online. */
const ONLINE_URL = "https://shengji.fly.dev/";

interface OfflineLobbyProps {
  status: ConnStatus;
  error: string | null;
  /** Arm App's fill-with-bots-then-start chain before creating the room. */
  onArmAutoFill: () => void;
}

export function OfflineLobby({ status, error, onArmAutoFill }: OfflineLobbyProps) {
  const ready = status === "open";
  const inApp = location.protocol === "capacitor:";
  const play = () => {
    if (!ready) return;
    clearSavedRoom();
    onArmAutoFill();
    conn.send({ type: "create_room", name: getSavedName().trim() || "Player" });
  };
  return (
    <div className="screen lobby-screen offline-lobby">
      <div className="panel lobby-panel">
        <h1 className="game-title">
          升级 <span className="game-title-en">Sheng Ji</span>
        </h1>
        <p className="game-subtitle">Tractor · two decks</p>
        <LobbyPreview />
        <p className="offline-note">You’re offline. Practice against three bots on this device.</p>
        <button className="btn gold big" disabled={!ready} onClick={play}>
          Play offline vs bots
        </button>
        {error ? <div className="lobby-error">{error}</div> : null}
        <p className="howto-entry">
          New to Sheng Ji?{" "}
          <button className="howto-link" onClick={() => openHowto()}>How to play</button>
        </p>
        <p className="offline-online">
          {inApp ? (
            <a href={ONLINE_URL}>Back online? Play with people</a>
          ) : (
            <a href="?offline=0">Back to online play</a>
          )}
        </p>
      </div>
    </div>
  );
}

export function OfflineBadge() {
  return (
    <div className="offline-badge" role="status">
      Offline · practice bots
    </div>
  );
}
