import type { RoomSeats, ServerMsg } from "../protocol";
import { openHowto } from "../howto/route";
import { prefersReducedMotion } from "../motion";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { ConnStatus } from "../ws";
import { clearSavedRoom, conn, getResumeToken, getSavedName, saveName } from "../ws";
import { createRoomPayload } from "../testPolicy";
import { needsSeatPicker } from "../seatPicker";
import { effectiveName, useAuth } from "../auth";
import { randomName } from "../randomName";
import AccountChip from "./AccountChip";
import GoogleSignIn from "./GoogleSignIn";

interface LobbyProps {
  status: ConnStatus;
  error: string | null;
  /** Arm App's fill-with-bots-then-start orchestration before creating a room. */
  onArmAutoFill: () => void;
}

// Signed-out visitors see a few seconds of real play under the title. The box
// keeps the clip's 1200:630 shape before it loads, so nothing below it moves;
// reduced motion gets the still frame instead.
function PreviewVideo() {
  // React leaves the muted attribute unset on first render, and iOS autoplays only a muted clip, so the
  // clip is muted and started here. When the browser still refuses (iOS Low Power Mode blocks every
  // autoplay), the still frame replaces it rather than leaving the system play button over the box.
  const ref = useRef<HTMLVideoElement>(null);
  const [still, setStill] = useState(prefersReducedMotion());
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    v.muted = true;
    v.defaultMuted = true;
    const start = () => {
      const started = v.play();
      if (started && typeof started.catch === "function") started.catch(() => setStill(true));
    };
    start();
    // iOS pauses a page's video when the app goes to the background and does not resume it, and a
    // looped clip can freeze at the seam in a web view: restart it on return and loop it here.
    const onVisible = () => { if (document.visibilityState === "visible" && v.paused) start(); };
    const onEnded = () => { v.currentTime = 0; start(); };
    document.addEventListener("visibilitychange", onVisible);
    v.addEventListener("ended", onEnded);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      v.removeEventListener("ended", onEnded);
    };
  }, []);
  return still ? (
    <img className="lobby-preview" src="/og/preview.jpg" alt="" aria-hidden="true" />
  ) : (
    <video
      ref={ref}
      className="lobby-preview"
      muted
      playsInline
      autoPlay
      preload="auto"
      poster="/og/preview.jpg"
      src="/og/preview.mp4"
      aria-hidden="true"
    />
  );
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
  // A signed-in player plays under their account name, the one the account
  // pill shows and its Edit name changes; the lobby has no name field for
  // them. It is sent explicitly because the socket's own default is read
  // once at its handshake and would miss a rename made since.
  // A guest names themselves in the field: it starts as the name they used
  // last time, saved on Play, Create or Join, or else a random one.
  const playerName = signedIn ? accountName : name.trim();
  // The random fill happens once, as soon as the page knows the visitor is
  // not signed in; a field the guest has typed into, or cleared afterwards,
  // is left alone.
  const autoFilled = useRef(false);
  useEffect(() => {
    if (autoFilled.current || (account.status !== "out" && account.status !== "off")) return;
    autoFilled.current = true;
    if (!name.trim() && !getSavedName().trim()) setName(randomName());
  }, [account.status, name]);
  const reroll = () => setName(randomName(name));
  const nameId = useId();
  // Only a guest's own name is remembered; an account name lives on the account.
  const rememberName = useCallback((trimmed: string) => {
    if (!signedIn && trimmed) saveName(trimmed);
  }, [signedIn]);
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
    const trimmed = playerName;
    rememberName(trimmed);
    clearInvite();
    setSeatChoice(null);
    const token = getResumeToken();
    conn.send({ type: "join_room", room: target, name: trimmed, seat,
                ...(token ? { token } : {}) });
  }, [playerName, roomCode, rememberName]);

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
  }), [joinSeat]);

  const ready = status === "open" && playerName.length > 0;
  const testReady = !w32Selected || testAccessKey.trim().length > 0;

  const create = () => {
    if (!ready || !testReady) return;
    const trimmed = playerName;
    const payload = createRoomPayload(trimmed, w32Selected, testAccessKey);
    if (!payload) return;
    rememberName(trimmed);
    clearInvite();
    clearSavedRoom(); // don't auto-rejoin an old room while creating a new one
    conn.send(payload);
  };

  const playBots = () => {
    if (status !== "open" || !testReady) return;
    const trimmed = playerName || randomName();
    const payload = createRoomPayload(trimmed, w32Selected, testAccessKey);
    if (!payload) return;
    rememberName(trimmed);
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
  // an explicit choice by whoever built the link; a signed-in player still
  // joins under their account name.
  const invited = new URLSearchParams(window.location.search).get("room");
  const invitedName = new URLSearchParams(window.location.search).get("name");
  useEffect(() => {
    if (autoJoined.current || !ready || !invited || invited.length !== 4) return;
    if (invitedName && invitedName.trim()) {
      autoJoined.current = true;
      const joinAs = signedIn ? accountName : invitedName.trim();
      if (!signedIn) saveName(joinAs);
      clearInvite();
      conn.send({ type: "join_room", room: invited.toUpperCase(), name: joinAs });
    } else {
      nameRef.current?.focus();
      nameRef.current?.select();
    }
  }, [ready, invited, invitedName, signedIn, accountName]);

  if (seatChoice) {
    const you = playerName || "You";
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
        <p className="game-subtitle">Tractor · two decks</p>
        <PreviewVideo />

        {account.status === "in" && account.user ? (
          <AccountChip user={account.user} />
        ) : null}

        {signedIn ? null : (
          <div className="field">
            <label className="field-label" htmlFor={nameId}>Your name</label>
            <div className="name-input">
              <input
                id={nameId}
                ref={nameRef}
                value={name}
                maxLength={20}
                placeholder="e.g. Jerry"
                autoComplete="nickname"
                autoCorrect="off"
                onChange={(e) => setName(e.target.value)}
              />
              <button type="button" className="name-reroll" aria-label="Random name"
                      title="Random name" onClick={reroll}>
                <span aria-hidden="true">🎲</span>
              </button>
            </div>
          </div>
        )}

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
            <p className="signin-upsell">Sign in to save your games.</p>
            <GoogleSignIn clientId={account.clientId} />
          </>
        ) : null}

        <p className="howto-entry">
          New to Sheng Ji?{" "}
          <button className="howto-link" onClick={() => openHowto()}>How to play</button>
        </p>

        <div className={`conn-status ${status}`}>
          <span className="conn-dot" />
          {STATUS_LABEL[status]}
        </div>
      </div>
    </div>
  );
}
