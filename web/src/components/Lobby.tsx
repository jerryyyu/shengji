import { useEffect, useRef, useState } from "react";
import type { ConnStatus } from "../ws";
import { clearSavedRoom, conn, getSavedName, saveName } from "../ws";

interface LobbyProps {
  status: ConnStatus;
  error: string | null;
  /** Arm App's fill-with-bots-then-start orchestration before creating a room. */
  onArmAutoFill: () => void;
}

const STATUS_LABEL: Record<ConnStatus, string> = {
  connecting: "Connecting…",
  open: "Connected",
  closed: "Disconnected — retrying…",
};

export default function Lobby({ status, error, onArmAutoFill }: LobbyProps) {
  const [name, setName] = useState(getSavedName());
  const [roomCode, setRoomCode] = useState(
    () => new URLSearchParams(window.location.search).get("room")?.toUpperCase() ?? ""
  );
  // Invite links: /?room=HPMK auto-joins once a name is known, so a shared
  // link drops you straight into the table (Jerry, 2026-08-03).
  const autoJoined = useRef(false);

  const ready = status === "open" && name.trim().length > 0;

  const create = () => {
    if (!ready) return;
    const trimmed = name.trim();
    saveName(trimmed);
    clearSavedRoom(); // don't auto-rejoin an old room while creating a new one
    conn.send({ type: "create_room", name: trimmed });
  };

  const playBots = () => {
    if (status !== "open") return;
    const trimmed = name.trim() || "Player";
    saveName(trimmed);
    clearSavedRoom();
    onArmAutoFill();
    conn.send({ type: "create_room", name: trimmed });
  };

  const join = () => {
    const code = roomCode.trim().toUpperCase();
    if (!ready || code.length !== 4) return;
    const trimmed = name.trim();
    saveName(trimmed);
    conn.send({ type: "join_room", room: code, name: trimmed });
  };

  // Auto-join from an invite link once the socket is ready and we have a
  // name. Fires once; if the name is blank the user just clicks Join.
  useEffect(() => {
    if (autoJoined.current || !ready) return;
    const invited = new URLSearchParams(window.location.search).get("room");
    if (!invited || invited.length !== 4 || !name.trim()) return;
    autoJoined.current = true;
    saveName(name.trim());
    conn.send({ type: "join_room", room: invited.toUpperCase(), name: name.trim() });
  }, [ready, name, conn]);

  return (
    <div className="screen lobby-screen">
      <div className="panel lobby-panel">
        <h1 className="game-title">
          升级 <span className="game-title-en">Sheng Ji</span>
        </h1>
        <p className="game-subtitle">Tractor · two decks · first to Ace</p>

        <label className="field">
          <span className="field-label">Your name</span>
          <input
            value={name}
            maxLength={20}
            placeholder="e.g. Jerry"
            onChange={(e) => setName(e.target.value)}
          />
        </label>

        <button className="btn gold big" disabled={status !== "open"} onClick={playBots}>
          Play vs bots
        </button>

        <button className="btn primary big" disabled={!ready} onClick={create}>
          Create room
        </button>

        <div className="divider">
          <span>or join</span>
        </div>

        <div className="join-row">
          <input
            className="room-input"
            value={roomCode}
            maxLength={4}
            placeholder="CODE"
            onChange={(e) => setRoomCode(e.target.value.toUpperCase())}
            onKeyDown={(e) => {
              if (e.key === "Enter") join();
            }}
          />
          <button
            className="btn"
            disabled={!ready || roomCode.trim().length !== 4}
            onClick={join}
          >
            Join
          </button>
        </div>

        {error ? <div className="lobby-error">{error}</div> : null}

        <div className={`conn-status ${status}`}>
          <span className="conn-dot" />
          {STATUS_LABEL[status]}
        </div>
      </div>
    </div>
  );
}
