import type { RoomSeats, ServerMsg } from "../protocol";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ConnStatus } from "../ws";
import { clearSavedRoom, conn, getResumeToken, getSavedName, saveName } from "../ws";

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
  const lastPeek = useRef<string | null>(null);
  const peekGen = useRef<number | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  // Mid-game joins pick their seat: partner choice matters (0&2 vs 1&3).
  const [seatChoice, setSeatChoice] = useState<RoomSeats | null>(null);
  // Declared before the subscriber and memoised so the effect can list it as
  // a dependency instead of silencing the warning: it closes over `name` and
  // `roomCode`, and a stale copy would join with the wrong name.
  const joinSeat = useCallback((seat: number | undefined, code?: string) => {
    const target = (code ?? roomCode).trim().toUpperCase();
    const trimmed = name.trim();
    saveName(trimmed);
    clearInvite();
    setSeatChoice(null);
    const token = getResumeToken();
    conn.send({ type: "join_room", room: target, name: trimmed, seat,
                ...(token ? { token } : {}) });
  }, [name, roomCode]);

  useEffect(() => conn.subscribe((msg: ServerMsg) => {
    const m = msg;
    // Ignore anything answering a transaction from a previous socket.
    if (peekGen.current !== null && peekGen.current !== conn.generation) {
      peekGen.current = null;
      setSeatChoice(null);
      return;
    }
    if (m?.type === "room_seats") {
      const seats = m.seats;
      const open = seats.filter((sd) => sd.claimable);
      const bots = seats.filter((sd) => sd.is_bot);
      // Offer the picker whenever more than one seat is open, or when the
      // only open seat belongs to a dropped human — taking someone's seat
      // should always be deliberate.
      // NOT conditioned on in_game: a FULL PRE-GAME lobby with one dropped
      // player also needs the picker, or the server answers choose_seat and
      // the client has nothing to show — a deadlock (Codex ship gate P0-4).
      if (open.length > 1 || (open.length === 1 && !bots.length)) {
        setSeatChoice(m);
      } else {
        joinSeat(undefined, m.room);       // nothing to choose
      }
      return;
    }
    // Someone took the seat between our peek and our join: reopen the
    // picker with fresh occupancy rather than leaving a dead-end toast.
    if (m?.type === "error"
        && (m.code === "seat_unavailable" || m.code === "choose_seat")
        && lastPeek.current) {
      conn.send({ type: "peek_room", room: lastPeek.current });
    }
  }), [name, joinSeat]);

  const ready = status === "open" && name.trim().length > 0;

  const create = () => {
    if (!ready) return;
    const trimmed = name.trim();
    saveName(trimmed);
    clearInvite();
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


  // Drop the invite param once the user acts: otherwise a stale ?room=
  // keeps steering later flows (including starting a fresh game) and the
  // name field looks "stuck" on whatever the link implied.
  const clearInvite = () => {
    if (window.location.search) {
      window.history.replaceState({}, "", window.location.pathname);
    }
  };

  const join = () => {
    const code = roomCode.trim().toUpperCase();
    if (!ready || code.length !== 4) return;
    // Ask who's sitting where first; the subscriber either shows a picker
    // (game in progress, >1 bot) or joins straight through.
    lastPeek.current = code;
    peekGen.current = conn.generation;   // this transaction belongs to this socket
    conn.send({ type: "peek_room", room: code });
  };

  // Invite links prefill the room code and focus the NAME field — they do
  // not auto-submit, because a returning player has a saved name and would
  // otherwise be thrown into the room before they could change it (Jerry,
  // 2026-08-03). Auto-join only when the link carries a name too, which is
  // an explicit choice by whoever built the link.
  const invited = new URLSearchParams(window.location.search).get("room");
  const invitedName = new URLSearchParams(window.location.search).get("name");
  useEffect(() => {
    if (autoJoined.current || !ready || !invited || invited.length !== 4) return;
    if (invitedName && invitedName.trim()) {
      autoJoined.current = true;
      saveName(invitedName.trim());
      clearInvite();
      conn.send({ type: "join_room", room: invited.toUpperCase(),
                  name: invitedName.trim() });
    } else {
      nameRef.current?.focus();
      nameRef.current?.select();
    }
  }, [ready, invited, invitedName]);

  if (seatChoice) {
    const you = name.trim() || "You";
    return (
      <div className="screen lobby-screen">
        <div className="lobby-card">
          <h2>Take a seat in {seatChoice.room}</h2>
          <p className="seat-hint">
            Game in progress — pick a seat to take. Seats 0 &amp; 2 are one
            team, 1 &amp; 3 the other. A seat whose player has gone offline can
            be taken over too; a bot is playing it in the meantime.
          </p>
          <div className="seat-grid">
            {seatChoice.seats.map((sd: RoomSeats["seats"][number]) => (
              <button
                key={sd.seat}
                className={"seat-option team" + sd.team + (sd.claimable ? "" : " taken")}
                disabled={!sd.claimable}
                onClick={() => joinSeat(sd.seat)}
              >
                <span className="seat-num">Seat {sd.seat}</span>
                <span className="seat-who">
                  {sd.is_bot ? `${sd.name} (bot)`
                    : sd.connected ? sd.name
                    : sd.reserved_secs != null
                      ? `${sd.name} (held ${Math.ceil(sd.reserved_secs)}s)`
                      : `${sd.name} (offline)`}
                </span>
                <span className="seat-team">Team {sd.team === 0 ? "A" : "B"}</span>
                {sd.claimable && (
                  <span className="seat-take">
                    {sd.is_bot ? `${you} sits here` : `${you} takes over`}
                  </span>
                )}
              </button>
            ))}
          </div>
          <button className="btn" onClick={() => setSeatChoice(null)}>Cancel</button>
        </div>
      </div>
    );
  }

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
            ref={nameRef}
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
