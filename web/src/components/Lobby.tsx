import type { RoomMsg, RoomSeats, ServerMsg } from "../protocol";
import { openHowto } from "../howto/route";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { ConnStatus } from "../ws";
import { clearSavedRoom, conn, getResumeToken } from "../ws";
import { createRoomPayload } from "../testPolicy";
import { effectiveName, useAuth } from "../auth";
import { randomName } from "../randomName";
import AccountChip from "./AccountChip";
import GuestChip from "./GuestChip";
import LobbyPreview from "./LobbyPreview";
import { RankedSection, TrophyIcon } from "../queue/Ranked";
import { queue, useQueue } from "../queue/store";
import { guestName, useGuestName } from "../guestName";
import { OfflineControls } from "./OfflinePlay";
import { useOffline } from "../offlineMode";
import JoinPanel from "./JoinPanel";
import { joinSeat as plainSeat, tableFull, takeoverSeats } from "../joinSeats";
import { codes, useCodes } from "../codeJoin";
import type { TableKind } from "../codeJoin";
import { normalizeCode } from "../codes";
import { WIDE } from "../home/route";
import { useMediaQuery } from "../phoneLayout";
import { offlineGame, useOfflineTable } from "./offlineGame";
import { showToast } from "../toast";

interface LobbyProps {
  status: ConnStatus;
  /** The room this socket sits in before its game: its panel takes Play's place. */
  room?: RoomMsg | null;
  /** A link waits while App asks whether to leave the table you sit at. */
  holdInvite?: boolean;
  /** A link opened while you sit at another table: App asks to leave it first. */
  onSeatedInvite?: (code: string) => void;
  /** Counts the times that question was answered Stay: the link is dropped. */
  inviteDropped?: number;
}

/** After this long without a connection the Play tab shows its offline state. */
export const STALL_MS = 4000;

/** Whether `status` has stayed short of "open" for STALL_MS. */
function useStalled(status: ConnStatus): boolean {
  const [stalled, setStalled] = useState(false);
  const open = status === "open";
  useEffect(() => {
    setStalled(false);
    if (open) return;
    const t = window.setTimeout(() => setStalled(true), STALL_MS);
    return () => window.clearTimeout(t);
  }, [open]);
  return stalled && !open;
}

/** A start request the server has not answered yet. */
type Starting = { kind: "create" | "join"; generation: number };
/** If neither a room nor an error has come back by then, the buttons wake up again. */
export const START_TIMEOUT_MS = 15000;
const STARTING_LABEL: Record<Starting["kind"], string> = { create: "Creating…", join: "Joining…" };

/** The Join panel's table: the code, its kind, a room's seats once peeked,
 *  and whether no seat is left. */
interface JoinView { code: string; kind: TableKind; peek: RoomSeats | null; full: boolean }

/** Who asked for a table_peek: the Join panel (to show its seats) or the code
 *  box (to join at once when a plain seat is open). */
type PeekFor = "panel" | "box";
/** A table_peek sent and not yet answered. `live` goes false when the panel
 *  that asked is closed: its answer, when it comes, does nothing. */
interface PeekAsk { code: string; for: PeekFor; live: boolean; generation: number }

/** The Ranked block while the server cannot say whether sign-in exists:
 *  Play and Duo in their places, unavailable. */
function RankedUnavailable() {
  const labelId = useId();
  return (
    <section className="play-section" aria-labelledby={labelId} data-testid="ranked-unavailable">
      <h2 className="play-label ranked" id={labelId}><TrophyIcon />Ranked</h2>
      <div className="play-ranked-row">
        <button type="button" className="btn gold play-main q-find" disabled>Play</button>
        <button type="button" className="btn play-duo" disabled>Duo</button>
      </div>
    </section>
  );
}

export default function Lobby({ status, room = null, holdInvite = false,
                                onSeatedInvite, inviteDropped = 0 }: LobbyProps) {
  const stalled = useStalled(status);
  // Offline, the socket talks to the on-device server: Play's controls are
  // the offline ones, and links, peeks and the Join panel wait for the game server.
  const offline = useOffline();
  const offlineTable = useOfflineTable(offline);
  // The test room's Create and Join each send one request and then wait:
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
  const { name } = useGuestName();
  const account = useAuth();
  const signedIn = account.status === "in" && account.user ? account.user : null;
  const accountName = effectiveName(signedIn);
  // A signed-in player plays under their account name, the one the account
  // pill shows and its Edit name changes. It is sent explicitly because the
  // socket's own default is read once at its handshake and would miss a
  // rename made since.
  // A guest's chip sits in the same place and opens their name editor: the
  // name starts as the one they used last time, saved on Play, Create, Join
  // or the editor's Done, or else a random one.
  const playerName = signedIn ? accountName : name.trim();
  // The random fill happens once, as soon as the page knows the visitor is
  // not signed in; a field the guest has typed into, or cleared afterwards,
  // is left alone. The store is the one name the chip shows and Join sends:
  // storage written since it loaded (another tab) does not stand in for it.
  const autoFilled = useRef(false);
  useEffect(() => {
    if (autoFilled.current || (account.status !== "out" && account.status !== "off" && account.status !== "error")) return;
    autoFilled.current = true;
    if (!guestName.name.trim()) guestName.fill(randomName());
  }, [account.status]);
  // Only a guest's own name is remembered; an account name lives on the account.
  const rememberName = useCallback((trimmed: string) => {
    if (!signedIn && trimmed) guestName.keep(trimmed);
  }, [signedIn]);
  // The query gate is captured at mount. clearInvite() removes the URL query
  // after an action, but must not make an already-open test control disappear.
  const [testControlsVisible] = useState(
    () => new URLSearchParams(window.location.search).get("test_shortlist") === "1",
  );
  const [w32Selected, setW32Selected] = useState(false);
  const [testAccessKey, setTestAccessKey] = useState("");
  // A ?code= link prefills the box (an older ?room= link reads as one).
  const [roomCode, setRoomCode] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return normalizeCode(params.get("code") ?? params.get("room") ?? "");
  });
  const codeView = useCodes();
  // A ?code= link that the lookup found to be a room or a Play table, and
  // which it was.
  const [linkRoom, setLinkRoom] = useState<string | null>(null);
  const [linkKind, setLinkKind] = useState<TableKind>("room");
  // A Play-box or link lookup still waiting for its answer holds Join.
  const looking = codeView.pending !== null;
  // The link has been opened (or dropped): it opens the panel once.
  const linkOpened = useRef(false);
  // The peeks waiting for their answers, oldest first: the server answers
  // them in the order they were sent, one reply each (room_seats, or
  // room_not_found), and an answer goes only to the ask it answers.
  const peeks = useRef<PeekAsk[]>([]);
  // The one invite path: a link's table, or a room the code box cannot seat
  // you at at once, shows the Join panel in Play's place. Join is the
  // player's tap; a dropped player's seat is taken only by tapping it and
  // confirming; a full table shows the same panel with Join disabled.
  const [joinView, setJoinViewState] = useState<JoinView | null>(null);
  const joinRef = useRef<JoinView | null>(null);
  const setJoinView = useCallback((v: JoinView | null) => {
    joinRef.current = v;
    setJoinViewState(v);
  }, []);
  // The table the last Join went to and who sent it, so a table_full answer
  // shows its panel and a choose_seat answer looks again for the same asker.
  const lastJoin = useRef<{ code: string; kind: TableKind; for: PeekFor } | null>(null);
  // Why a link's table could not be opened, said as the toast. It is said
  // after the message's other listeners have run, so it wins over App's
  // generic toast for the same error.
  const [inviteError, setInviteError] = useState<string | null>(null);
  useEffect(() => {
    if (inviteError === null) return;
    showToast(inviteError);
    setInviteError(null);
  }, [inviteError]);
  // A code that names nothing answers the Join tap: said as the toast, once.
  useEffect(() => {
    if (codeView.playError === null) return;
    showToast(codeView.playError);
    codes.clearPlayError();
  }, [codeView.playError]);
  const sendPeek = useCallback((code: string, asker: PeekFor): boolean => {
    if (!conn.send({ type: "table_peek", code })) return false;
    peeks.current.push({ code, for: asker, live: true, generation: conn.generation });
    return true;
  }, []);
  // Declared before the subscriber and memoised so the effect can list it as
  // a dependency instead of silencing the warning: it closes over `name` and
  // `roomCode`, and a stale copy would join with the wrong name.
  const joinSeat = useCallback((seat: number | undefined, code: string, asker: PeekFor, as?: string) => {
    const target = code.trim().toUpperCase();
    const trimmed = as ?? playerName;
    rememberName(trimmed);
    clearInvite();
    lastJoin.current = { code: target, kind: "room", for: asker };
    const token = getResumeToken();
    if (conn.send({ type: "join_room", room: target, name: trimmed, seat,
                    ...(token ? { token } : {}) })) {
      setStarting({ kind: "join", generation: conn.generation });
    }
  }, [playerName, rememberName]);

  useEffect(() => conn.subscribe((msg: ServerMsg) => {
    const m = msg;
    // a peek sent on an earlier socket has no answer coming
    peeks.current = peeks.current.filter((a) => a.generation === conn.generation);
    // a code that named nothing: the box is free again
    if (m?.type === "code_kind" && m.kind !== "room") {
      setStarting(null);
      return;
    }
    // A peek's one reply goes to the oldest ask; one whose panel was closed
    // (Not now), or for another code, does nothing.
    const peekReply = m?.type === "room_seats" || (m?.type === "error" && m.code === "room_not_found");
    const ask = peekReply ? peeks.current.shift() ?? null : null;
    if (m?.type === "room_seats") {
      if (!ask || !ask.live || ask.code !== m.room) return;
      setStarting(null);
      if (ask.for === "panel") {
        const open = joinRef.current;
        if (open && open.code === m.room) setJoinView({ ...open, peek: m, full: tableFull(m) });
        return;
      }
      if (tableFull(m) || takeoverSeats(m).length) {
        // the code box: no seat to give at once, so the panel says why
        setJoinView({ code: m.room, kind: "room", peek: m, full: tableFull(m) });
        return;
      }
      // the code box: the server seats you in the plain seat the peek showed,
      // a lobby's next seat or a game's first bot seat
      joinSeat(undefined, m.room, "box");
      return;
    }
    if (ask && !ask.live) return;
    if (ask?.for === "panel") {
      // the link's room is gone: Play says so
      setJoinView(null);
      clearInvite();
      setInviteError(`No room ${ask.code}. It may have closed.`);
      return;
    }
    // A join that needs a seat named (every open seat is a dropped
    // player's), or whose seat was just taken: look again and offer the
    // seats there are.
    if (m?.type === "error" && (m.code === "choose_seat" || m.code === "seat_unavailable")) {
      const again = lastJoin.current;
      if (again && again.kind === "room") {
        // the same asker looks again: the panel shows the away seats, and a
        // panel closed since asks nothing
        if (again.for === "box") sendPeek(again.code, "box");
        else {
          const open = joinRef.current;
          if (open && open.code === again.code) {
            setJoinView({ ...open, peek: null });
            sendPeek(again.code, "panel");
          }
        }
        return;
      }
    }
    if (m?.type === "error" && m.code === "table_full") {
      const open = joinRef.current;
      const last = lastJoin.current;
      if (open) setJoinView({ ...open, full: true });
      else if (last) setJoinView({ ...last, peek: null, full: true });
      return;
    }
    if (m?.type === "error" && joinRef.current?.kind === "table"
        && (m.code === "table_not_found" || m.code === "table_closed" || m.code === "own_table")) {
      setJoinView(null);
      if (m.code !== "table_closed") setInviteError(m.message);
      return;
    }
  }), [joinSeat, setJoinView, sendPeek]);

  // An empty name never blocks a start: the test room's Create and Join
  // each fill the field with a random name and go, the same as the dice.
  const ready = status === "open" && starting === null;
  const testReady = !w32Selected || testAccessKey.trim().length > 0;
  const nameOrRandom = () => {
    if (playerName) return playerName;
    const picked = randomName();
    guestName.fill(picked);
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
    if (sendPeek(code, "box")) setStarting({ kind: "join", generation: conn.generation });
  }, [sendPeek]);

  // The box takes a room or table code: look it up, then a room is peeked
  // here (below) and a table is joined by the queue.
  const join = () => {
    const code = normalizeCode(roomCode);
    if (!ready || looking || code.length !== 4) return;
    nameOrRandom();
    if (codes.lookup(code, "play")) begin("join");
  };

  // A room or table code from this box or a ?code= link. A link's answer
  // waits while a game is on (this screen is not up), for as long as the
  // address still holds the link.
  useEffect(() => {
    if (!codeView.room || status !== "open") return;
    const r = codes.takeRoom();
    if (!r) return;
    if (r.from === "link") {
      const still = normalizeCode(new URLSearchParams(window.location.search).get("code") ?? "");
      if (still !== r.code) return;
      setLinkRoom(r.code);
      setLinkKind(r.kind);
      return;
    }
    if (Date.now() - r.at > START_TIMEOUT_MS) return;
    setRoomCode(r.code);
    if (r.kind === "table") {
      // a friend's Play table: sit there through the queue
      setRoomCode("");
      lastJoin.current = { code: r.code, kind: "table", for: "box" };
      queue.join(r.code);
    } else peek(r.code);
  }, [codeView.room, status, peek]);

  // The panel opens on a code: a room's seats are peeked for it (the server
  // shows a Play table's seats once you sit).
  const openJoin = useCallback((code: string, kind: TableKind) => {
    setInviteError(null);
    setJoinView({ code, kind, peek: null, full: false });
    if (kind === "room") sendPeek(code, "panel");
  }, [setJoinView, sendPeek]);

  // Not now: the panel goes and the link with it; Play is back.
  const closeJoin = () => {
    setJoinView(null);
    setLinkRoom(null);
    setRoomCode("");
    // a peek still on its way answers nothing now
    for (const a of peeks.current) if (a.for === "panel") a.live = false;
    clearInvite();
  };

  // The panel's Join: under the name the chip shows (a guest's random one
  // until they edit it), a room by join_room, a Play table through the queue.
  const joinFromPanel = () => {
    const v = joinRef.current;
    if (!v || v.full) return;
    // a room's plain Join waits for its peek to show a plain seat: a seatless
    // join_room must never land in a dropped player's seat
    if (v.kind === "room" && (v.peek === null || plainSeat(v.peek) === null)) return;
    const as = nameOrRandom();
    if (v.kind === "table") {
      rememberName(as);
      clearInvite();
      setLinkRoom(null);
      lastJoin.current = { code: v.code, kind: "table", for: "panel" };
      queue.join(v.code);
      return;
    }
    joinSeat(undefined, v.code, "panel", as);
  };

  // A ?code= link opens the Join panel and never joins by itself: the
  // player taps Join, under the name the chip shows.
  useEffect(() => {
    if (inviteDropped === 0) return;
    linkOpened.current = true;
    setLinkRoom(null);
  }, [inviteDropped]);
  // Sitting at a table already (a room here, or the queue's) the link waits
  // for App's leave-first question; once that table is left, it goes on.
  const { queued, tableCode, pending: queuePending } = useQueue();
  const seated = room !== null || queued;
  const wide = useMediaQuery(WIDE);
  const screenRef = useRef<HTMLDivElement | null>(null);
  // a panel that opens puts the page back at its top, where the panel is
  const joinUp = joinView !== null && !seated && !offline;
  const panelUp = offline ? offlineTable : (seated || joinUp) && !stalled;
  useEffect(() => {
    if (panelUp && screenRef.current) screenRef.current.scrollTop = 0;
  }, [panelUp]);
  // A socket that drops takes its unanswered peeks with it; an open room
  // panel still without its seats asks again on the next one.
  useEffect(() => {
    if (status !== "open" || offline) {
      peeks.current = [];
      return;
    }
    const v = joinRef.current;
    if (v && v.kind === "room" && v.peek === null && !peeks.current.some((a) => a.live && a.for === "panel")) {
      sendPeek(v.code, "panel");
    }
  }, [status, offline, sendPeek]);
  // once you sit, the panel's job is done
  useEffect(() => {
    if (!seated) return;
    lastJoin.current = null;
    if (joinRef.current) setJoinView(null);
  }, [seated, setJoinView]);
  useEffect(() => {
    if (linkOpened.current || status !== "open" || offline || !linkRoom || holdInvite) return;
    if (seated) {
      // your own table's link changes nothing; another table's asks first
      if ((room?.room ?? tableCode) !== linkRoom) onSeatedInvite?.(linkRoom);
      else {
        clearInvite();
        setLinkRoom(null);
      }
      return;
    }
    linkOpened.current = true;
    openJoin(linkRoom, linkKind);
  }, [status, offline, linkRoom, linkKind, holdInvite, seated, room, tableCode, onSeatedInvite, openJoin]);

  // The test controls' room: a created room for the W32 policy, reached
  // only from ?test_shortlist=1. Every other table comes from Play.
  const createLabel = starting?.kind === "create" ? STARTING_LABEL.create : "Create test room";
  const testRoom = testControlsVisible ? (
    <ul className="grp play-grp">
      <li>
        <button type="button" className="grp-row" disabled={!ready || !testReady} onClick={create}
                aria-busy={starting?.kind === "create" || undefined}>
          <span className="grp-label">{createLabel}</span><span className="grp-value chev" />
        </button>
      </li>
    </ul>
  ) : null;
  // A phone's panel sits right under the chip and the mode switch, with the
  // art gone, so its buttons are on screen; wide screens keep the art beside it.
  const showArt = wide || !panelUp;
  const ranked = account.status === "error" && !room
    ? <RankedUnavailable /> : <RankedSection online={status === "open"} room={room} />;

  return (
    <div ref={screenRef} className={`screen lobby-screen play-tab${stalled || offline ? " play-offline" : ""}${panelUp ? " play-table-up" : ""}`}>
      <div className="panel lobby-panel">
        {/* one column on a phone; on desktop and iPad the controls and the
            table panel sit beside the art */}
        <div className="play-art">
          <h1 className="game-title">
            升级 <span className="game-title-en">Sheng Ji</span>
          </h1>
          {showArt ? <LobbyPreview /> : null}
        </div>
        <div className="play-side">
        {signedIn ? <AccountChip user={signedIn} /> : <GuestChip />}

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

        {/* With no connection Play plays on this device, and what needs the
            server waits; the chip, How to play and an open sheet stay put. */}
        {offline ? (
          <OfflineControls local status={status} room={room?.room ?? null} />
        ) : stalled && !room ? <OfflineControls local={false} status={status} /> : (
          <>
            {joinUp && joinView ? (
              <JoinPanel code={joinView.code} kind={joinView.kind} peek={joinView.peek} full={joinView.full}
                         busy={starting?.kind === "join" || queuePending === "join"}
                         onJoin={joinFromPanel} onCancel={closeJoin}
                         onTake={(seat) => joinSeat(seat, joinView.code, "panel", nameOrRandom())} />
            ) : ranked}
            {testRoom}

            {/* at a table the panel is the page: no code box until you leave it */}
            {seated || joinUp ? null : <div className="join-row">
              <input
                className="room-input"
                value={roomCode}
                maxLength={4}
                placeholder="CODE"
                aria-label="Table code"
                disabled={status !== "open"}
                autoCapitalize="characters"
                autoCorrect="off"
                spellCheck={false}
                enterKeyHint="go"
                onChange={(e) => {
                  setRoomCode(e.target.value.toUpperCase());
                  codes.clearPlayError();
                  setInviteError(null);
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
            </div>}
          </>
        )}

        <p className="howto-entry">
          <button className="howto-link" onClick={() => openHowto()}>How to play</button>
          {/* the bots on this device, on purpose: a game started here stays
              offline when the network comes back */}
          {stalled || offline || seated || joinUp ? null : (
            <>
              <span className="howto-sep" aria-hidden="true">·</span>
              <button className="howto-link" onClick={() => offlineGame.startFromPlay()}>Play offline</button>
            </>
          )}
        </p>
        </div>
      </div>
    </div>
  );
}
