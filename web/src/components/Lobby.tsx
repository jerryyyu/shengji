import type { RoomSeats, ServerMsg } from "../protocol";
import { openHowto } from "../howto/route";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { ConnStatus } from "../ws";
import { clearSavedRoom, conn, getResumeToken, getSavedName, saveName } from "../ws";
import { createRoomPayload } from "../testPolicy";
import { needsSeatPicker } from "../seatPicker";
import { effectiveName, useAuth } from "../auth";
import { randomName } from "../randomName";
import AccountChip from "./AccountChip";
import LobbyPreview from "./LobbyPreview";
import { GuestDuoSheet, RankedSection } from "../queue/Ranked";
import { offlineGame } from "./offlineGame";
import { codes, useCodes } from "../codeJoin";
import { normalizeCode } from "../codes";

interface LobbyProps {
  status: ConnStatus;
  error: string | null;
  /** Arm App's fill-with-bots-then-start orchestration before creating a room. */
  onArmAutoFill: () => void;
}

/** After this long without a connection the lobby says so, Play bots plays
 *  on this device, and a tap on the notice retries at once. */
export const STALL_MS = 4000;

/** Whether `status` has stayed short of "open" for STALL_MS, and a retry
 *  that reconnects at once and starts the wait over. */
function useStalled(status: ConnStatus): [boolean, () => void] {
  const [stalled, setStalled] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const open = status === "open";
  useEffect(() => {
    setStalled(false);
    if (open) return;
    const t = window.setTimeout(() => setStalled(true), STALL_MS);
    return () => window.clearTimeout(t);
  }, [open, attempt]);
  const retry = useCallback(() => {
    setAttempt((n) => n + 1);
    conn.reconnect();
  }, []);
  return [stalled && !open, retry];
}

/** A start request the server has not answered yet. */
type Starting = { kind: "bots" | "create" | "join"; generation: number };
/** If neither a room nor an error has come back by then, the buttons wake up again. */
export const START_TIMEOUT_MS = 15000;
const STARTING_LABEL: Record<Starting["kind"], string> = { bots: "Starting…", create: "Creating…", join: "Joining…" };

export default function Lobby({ status, error, onArmAutoFill }: LobbyProps) {
  const [stalled, retry] = useStalled(status);
  // Play vs bots, Create room and Join each send one request and then wait:
  // the button says so at once and every start button holds until the room
  // arrives (the lobby goes away), an error comes back, the connection the
  // request went out on is replaced, or START_TIMEOUT_MS passes. Any of the
  // last three leaves the buttons ready for a deliberate retry.
  const [starting, setStarting] = useState<Starting | null>(null);
  const begin = (kind: Starting["kind"]) => setStarting({ kind, generation: conn.generation });
  useEffect(() => {
    if (starting && (status !== "open" || conn.generation !== starting.generation)) setStarting(null);
  }, [status, starting]);
  useEffect(() => {
    if (!starting) return;
    const t = window.setTimeout(() => setStarting(null), START_TIMEOUT_MS);
    return () => window.clearTimeout(t);
  }, [starting]);
  useEffect(() => conn.subscribe((msg: ServerMsg) => {
    if (msg?.type === "error") setStarting(null);
  }), []);
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
  // A ?room= link, or a ?code= link (a room or a pair code), prefills the box.
  const [roomCode, setRoomCode] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return normalizeCode(params.get("room") ?? params.get("code") ?? "");
  });
  const codeView = useCodes();
  // A ?code= link that the lookup found to be a room: handled as ?room= is.
  const [linkRoom, setLinkRoom] = useState<string | null>(null);
  // A Play-box or link lookup still waiting for its answer holds Join.
  const looking = codeView.pending !== null && codeView.pending.from !== "pair";
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
    if (conn.send({ type: "join_room", room: target, name: trimmed, seat,
                    ...(token ? { token } : {}) })) {
      setStarting({ kind: "join", generation: conn.generation });
    }
  }, [playerName, roomCode, rememberName]);

  useEffect(() => conn.subscribe((msg: ServerMsg) => {
    const m = msg;
    // Ignore anything answering a transaction from a previous socket.
    if (peekGen.current !== null && peekGen.current !== conn.generation) {
      peekGen.current = null;
      setSeatChoice(null);
      return;
    }
    // a code that named a pair or nothing: the box is free again
    if (m?.type === "code_kind" && m.kind !== "room") {
      setStarting(null);
      return;
    }
    if (m?.type === "room_seats") {
      if (needsSeatPicker(m.seats)) {
        setStarting(null);                 // the answer is a choice to make
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

  // An empty name never blocks a start: Play vs bots, Create room and Join
  // each fill the field with a random name and go, the same as the dice.
  const ready = status === "open" && starting === null;
  const testReady = !w32Selected || testAccessKey.trim().length > 0;
  const nameOrRandom = () => {
    if (playerName) return playerName;
    const picked = randomName();
    setName(picked);
    return picked;
  };

  const create = () => {
    if (!ready || !testReady) return;
    const trimmed = nameOrRandom();
    const payload = createRoomPayload(trimmed, w32Selected, testAccessKey);
    if (!payload) return;
    rememberName(trimmed);
    clearInvite();
    clearSavedRoom(); // don't auto-rejoin an old room while creating a new one
    if (conn.send(payload)) begin("create");
  };

  const playBots = () => {
    if (stalled) {
      offlineGame.start();
      return;
    }
    if (!ready || !testReady) return;
    const trimmed = nameOrRandom();
    const payload = createRoomPayload(trimmed, w32Selected, testAccessKey);
    if (!payload) return;
    rememberName(trimmed);
    clearSavedRoom();
    onArmAutoFill();
    if (conn.send(payload)) begin("bots");
  };


  // Drop the invite param once the user acts: otherwise a stale ?room=
  // keeps steering later flows (including starting a fresh game) and the
  // name field looks "stuck" on whatever the link implied.
  const clearInvite = () => {
    if (window.location.search) {
      window.history.replaceState({}, "", window.location.pathname);
    }
  };

  // Ask who's sitting where first; the subscriber shows a picker when
  // needsSeatPicker() says so, otherwise joins straight through.
  const peek = useCallback((code: string) => {
    lastPeek.current = code;
    peekGen.current = conn.generation;   // this transaction belongs to this socket
    if (conn.send({ type: "peek_room", room: code })) {
      setStarting({ kind: "join", generation: conn.generation });
    }
  }, []);

  // The box takes a room code or a pair code: look it up, then a room is
  // peeked here (below) and a pair is joined by the queue.
  const join = () => {
    const code = normalizeCode(roomCode);
    if (!ready || looking || code.length !== 4) return;
    nameOrRandom();
    if (codes.lookup(code, "play")) begin("join");
  };

  // A room code from this box, the pair sheet's box or a ?code= link.
  useEffect(() => {
    if (!codeView.room || status !== "open") return;
    const r = codes.takeRoom();
    if (!r || Date.now() - r.at > START_TIMEOUT_MS) return;
    setRoomCode(r.code);
    if (r.from === "link") setLinkRoom(r.code);
    else peek(r.code);
  }, [codeView.room, status, peek]);

  // Invite links prefill the room code and focus the NAME field — they do
  // not auto-submit, because a returning player has a saved name and would
  // otherwise be thrown into the room before they could change it. Auto-join
  // only when the link carries a name too, which is
  // an explicit choice by whoever built the link; a signed-in player still
  // joins under their account name.
  const invited = new URLSearchParams(window.location.search).get("room") ?? linkRoom;
  const invitedName = new URLSearchParams(window.location.search).get("name");
  useEffect(() => {
    if (autoJoined.current || status !== "open" || !invited || invited.length !== 4) return;
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
  }, [status, invited, invitedName, signedIn, accountName]);

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
                disabled={!sd.claimable || starting !== null}
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

  // Play bots needs no server once the connection has been gone a while:
  // it then plays on this device. Everything else waits for the socket.
  const botsReady = stalled || (ready && testReady);
  const botsLabel = starting?.kind === "bots" ? STARTING_LABEL.bots : "Play bots";
  const createLabel = starting?.kind === "create" ? STARTING_LABEL.create : "Create room";
  // A guest, or anyone without a connection, has Play bots as the one gold
  // button; a signed-in player online has it as a row under Create room.
  const botsPrimary = !signedIn || stalled;
  const casual = (
    <section className="play-section" aria-labelledby={`${nameId}-casual`}>
      <h2 className="play-label" id={`${nameId}-casual`}>Casual</h2>
      {botsPrimary ? (
        <button type="button" className="btn gold play-main" disabled={!botsReady} onClick={playBots}
                aria-busy={starting?.kind === "bots" || undefined}>
          {botsLabel}
        </button>
      ) : null}
      <ul className="grp play-grp">
        <li>
          <button type="button" className="grp-row" disabled={!ready || !testReady} onClick={create}
                  aria-busy={starting?.kind === "create" || undefined}>
            <span className="grp-label">{createLabel}</span><span className="grp-value chev" />
          </button>
        </li>
        {botsPrimary ? null : (
          <li>
            <button type="button" className="grp-row" disabled={!botsReady} onClick={playBots}
                    aria-busy={starting?.kind === "bots" || undefined}>
              <span className="grp-label">{botsLabel}</span><span className="grp-value chev" />
            </button>
          </li>
        )}
      </ul>
    </section>
  );
  const ranked = <RankedSection online={status === "open"} />;

  return (
    <div className="screen lobby-screen play-tab">
      <div className="panel lobby-panel">
        {status === "open" ? null : stalled ? (
          <div role="status" className="play-conn-row">
            <button type="button" className="play-conn" onClick={retry} title="Retry now">
              <span className="conn-dot" />No connection · retrying
            </button>
          </div>
        ) : (
          <div role="status" className="play-conn-row">
            <span className="play-conn"><span className="conn-dot" />Connecting…</span>
          </div>
        )}
        <h1 className="game-title">
          升级 <span className="game-title-en">Sheng Ji</span>
        </h1>
        <LobbyPreview />
        {signedIn ? <AccountChip user={signedIn} /> : (
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
                autoCapitalize="words"
                spellCheck={false}
                enterKeyHint="done"
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  // "done" on the keyboard puts it away; joining stays a tap
                  if (e.key === "Enter" && !e.nativeEvent.isComposing) e.currentTarget.blur();
                }}
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

        {signedIn ? <>{ranked}{casual}</> : <>{casual}{ranked}</>}

        <div className="join-row">
          <input
            className="room-input"
            value={roomCode}
            maxLength={4}
            placeholder="CODE"
            aria-label="Room or duo code"
            disabled={status !== "open"}
            autoCapitalize="characters"
            autoCorrect="off"
            spellCheck={false}
            enterKeyHint="go"
            onChange={(e) => {
              setRoomCode(e.target.value.toUpperCase());
              codes.clearPlayError();
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") join();
            }}
          />
          <button
            className="btn"
            disabled={!ready || looking || roomCode.trim().length !== 4}
            onClick={join}
            aria-busy={starting?.kind === "join" || looking || undefined}
          >
            {starting?.kind === "join" || looking ? STARTING_LABEL.join : "Join"}
          </button>
        </div>

        {error || codeView.playError ? (
          <div className="lobby-error">{error ?? codeView.playError}</div>
        ) : null}

        <p className="howto-entry">
          <button className="howto-link" onClick={() => openHowto()}>How to play</button>
        </p>
      </div>
      <GuestDuoSheet />
    </div>
  );
}
