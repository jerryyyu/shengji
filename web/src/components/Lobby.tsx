import type { RoomSeats, ServerMsg } from "../protocol";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ConnStatus } from "../ws";
import { clearSavedRoom, conn, getResumeToken, getSavedName, saveName } from "../ws";
import { createRoomPayload } from "../testPolicy";
import { needsSeatPicker } from "../seatPicker";
import { auth, checkDisplayName, effectiveName, updateDisplayName, useAuth } from "../auth";
import { getNameSource, setNameSource } from "../nameSource";
import AccountChip from "./AccountChip";
import GoogleSignIn from "./GoogleSignIn";

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
  const account = useAuth();
  const signedIn = account.status === "in" && account.user ? account.user : null;
  const accountName = effectiveName(signedIn);
  // A signed-in player who never typed a name is called by their account
  // name (chosen display name, else first name); a name they did type (or
  // saved earlier as typed) is theirs and is left alone. When the account
  // name itself changes (the edit form, here or in-game before this mount),
  // a field still showing the old one follows it: either the name shown by
  // the previous render, or the saved name when it was itself an account
  // default rather than a typed one.
  const shownBefore = useRef("");
  useEffect(() => {
    if (!signedIn) return;
    setName((current) => {
      const trimmed = current.trim();
      if (!trimmed || trimmed === shownBefore.current) return accountName;
      if (getNameSource() === "account" && trimmed === getSavedName().trim()) return accountName;
      return current;
    });
    shownBefore.current = accountName;
  }, [signedIn, accountName]);
  // Save the room name with where it came from, so a later rename knows
  // whether the saved name was the account's default or the player's choice.
  const rememberName = useCallback((trimmed: string) => {
    saveName(trimmed);
    setNameSource(signedIn && trimmed === accountName ? "account" : "typed");
  }, [signedIn, accountName]);
  // A typed name that differs from the account's can be kept as the account
  // name too: off by default, one PATCH on create/join when ticked.
  const [saveAsMine, setSaveAsMine] = useState(false);
  const typedDiffers = signedIn !== null && name.trim().length > 0 && name.trim() !== accountName;
  const saveCheck = typedDiffers && saveAsMine ? checkDisplayName(name) : null;
  const saveDisplayName = useCallback(() => {
    if (!signedIn || !saveAsMine) return;
    const check = checkDisplayName(name);
    if (!check.ok || check.value === accountName) return;
    updateDisplayName(check.value)
      .then((next) => auth.updated(next))
      .catch(() => { /* the room keeps the typed name; the account keeps its old one */ });
  }, [signedIn, saveAsMine, name, accountName]);
  // The query gate is captured at mount. clearInvite() removes the URL query
  // after an action, but must not make an already-open test control disappear.
  const [testControlsVisible] = useState(
    () => new URLSearchParams(window.location.search).get("test_shortlist") === "1",
  );
  const [w32Selected, setW32Selected] = useState(false);
  const [testAccessKey, setTestAccessKey] = useState("");
  const [roomCode, setRoomCode] = useState(
    () => new URLSearchParams(window.location.search).get("room")?.toUpperCase() ?? ""
  );
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
    rememberName(trimmed);
    saveDisplayName();
    clearInvite();
    setSeatChoice(null);
    const token = getResumeToken();
    conn.send({ type: "join_room", room: target, name: trimmed, seat,
                ...(token ? { token } : {}) });
  }, [name, roomCode, saveDisplayName, rememberName]);

  useEffect(() => conn.subscribe((msg: ServerMsg) => {
    const m = msg;
    // Ignore anything answering a transaction from a previous socket.
    if (peekGen.current !== null && peekGen.current !== conn.generation) {
      peekGen.current = null;
      setSeatChoice(null);
      return;
    }
    if (m?.type === "room_seats") {
      if (needsSeatPicker(m.seats)) {
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
  const testReady = !w32Selected || testAccessKey.trim().length > 0;

  const create = () => {
    if (!ready || !testReady) return;
    const trimmed = name.trim();
    const payload = createRoomPayload(trimmed, w32Selected, testAccessKey);
    if (!payload) return;
    rememberName(trimmed);
    saveDisplayName();
    clearInvite();
    clearSavedRoom(); // don't auto-rejoin an old room while creating a new one
    conn.send(payload);
  };

  const playBots = () => {
    if (status !== "open" || !testReady) return;
    const trimmed = name.trim() || accountName || "Player";
    const payload = createRoomPayload(trimmed, w32Selected, testAccessKey);
    if (!payload) return;
    rememberName(trimmed);
    saveDisplayName();
    clearSavedRoom();
    onArmAutoFill();
    conn.send(payload);
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
    // Ask who's sitting where first; the subscriber shows a picker when
    // needsSeatPicker() says so, otherwise joins straight through.
    lastPeek.current = code;
    peekGen.current = conn.generation;   // this transaction belongs to this socket
    conn.send({ type: "peek_room", room: code });
  };

  // Invite links prefill the room code and focus the NAME field — they do
  // not auto-submit, because a returning player has a saved name and would
  // otherwise be thrown into the room before they could change it. Auto-join
  // only when the link carries a name too, which is
  // an explicit choice by whoever built the link.
  const invited = new URLSearchParams(window.location.search).get("room");
  const invitedName = new URLSearchParams(window.location.search).get("name");
  useEffect(() => {
    if (autoJoined.current || !ready || !invited || invited.length !== 4) return;
    if (invitedName && invitedName.trim()) {
      autoJoined.current = true;
      saveName(invitedName.trim());
      setNameSource("typed");     // a link-supplied name is someone's explicit choice
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

        {account.status === "in" && account.user ? (
          <AccountChip user={account.user} />
        ) : null}

        <label className="field">
          <span className="field-label">Your name</span>
          <input
            ref={nameRef}
            value={name}
            maxLength={20}
            placeholder="e.g. Jerry"
            autoComplete="nickname"
            autoCorrect="off"
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        {typedDiffers ? (
          <label className="save-name-row">
            <input
              type="checkbox"
              checked={saveAsMine}
              onChange={(e) => setSaveAsMine(e.target.checked)}
            />
            <span>Save as my name</span>
            {saveCheck && !saveCheck.ok ? (
              <span className="save-name-error" role="alert">{saveCheck.message}</span>
            ) : null}
          </label>
        ) : null}

        {testControlsVisible ? (
          <div className="experimental-controls">
            <label>
              <input
                type="checkbox"
                checked={w32Selected}
                onChange={(e) => setW32Selected(e.target.checked)}
              />{" "}
              experimental W32
            </label>
            {w32Selected ? (
              <label className="field">
                <input
                  type="password"
                  value={testAccessKey}
                  placeholder="Access code"
                  autoComplete="new-password"
                  onChange={(e) => setTestAccessKey(e.target.value)}
                />
                <span className="field-label">
                  Experimental wide moves may take ~30s; another test room can queue behind them.
                </span>
              </label>
            ) : null}
          </div>
        ) : null}

        <button className="btn gold big" disabled={!testReady || status !== "open"} onClick={playBots}>
          Play vs bots
        </button>

        <button className="btn primary big" disabled={!ready || !testReady} onClick={create}>
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
            aria-label="Room code"
            autoCapitalize="characters"
            autoCorrect="off"
            spellCheck={false}
            enterKeyHint="go"
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

        {account.status === "out" && account.clientId ? (
          <>
            <div className="divider">
              <span>or</span>
            </div>
            <GoogleSignIn clientId={account.clientId} />
          </>
        ) : null}

        <div className={`conn-status ${status}`}>
          <span className="conn-dot" />
          {STATUS_LABEL[status]}
        </div>
      </div>
    </div>
  );
}
