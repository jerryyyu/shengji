import type { RoomMsg, ServerMsg } from "../protocol";
import { openHowto } from "../howto/route";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { ConnStatus } from "../ws";
import { clearSavedRoom, conn } from "../ws";
import { createRoomPayload } from "../testPolicy";
import { effectiveName, useAuth } from "../auth";
import { randomName } from "../randomName";
import AccountChip from "./AccountChip";
import GuestChip from "./GuestChip";
import LobbyPreview from "./LobbyPreview";
import { RankedSection, TrophyIcon } from "../queue/Ranked";
import { useQueue } from "../queue/store";
import { guestName, useGuestName } from "../guestName";
import { OfflineControls } from "./OfflinePlay";
import { useOffline } from "../offlineMode";
import JoinPanel from "./JoinPanel";
import { codes, panelShown, useCodes } from "../codeJoin";
import { normalizeCode } from "../codes";
import { WIDE } from "../home/route";
import { useMediaQuery } from "../phoneLayout";
import { offlineGame, useOfflineTable } from "./offlineGame";

interface LobbyProps {
  status: ConnStatus;
  /** The room this socket sits in before its game's first state. */
  room?: RoomMsg | null;
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

/** The test room's Create, sent and not answered yet. */
type Starting = { generation: number };
/** If neither a room nor an error has come back by then, the buttons wake up again. */
export const START_TIMEOUT_MS = 15000;

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

export default function Lobby({ status, room = null }: LobbyProps) {
  const stalled = useStalled(status);
  // Offline, the socket talks to the on-device server: Play's controls are
  // the offline ones, and links, peeks and the Join panel wait for the game server.
  const offline = useOffline();
  const offlineTable = useOfflineTable(offline);
  // The test room's Create sends one request and then waits: the button
  // says so at once and every start button holds until the game arrives
  // (the lobby goes away), an error comes back, the connection the request
  // went out on is replaced, or START_TIMEOUT_MS passes. Any of the last
  // three leaves the buttons ready for a deliberate retry.
  const [starting, setStarting] = useState<Starting | null>(null);
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
  // The one code path (codeJoin.ts): a code from this box or a ?code= link
  // opens the Join panel in Play's place, with you glowing in the seat Join
  // takes. Join is the player's tap; a full table shows the same panel with
  // Join disabled. This screen tells the store where it stands.
  const codeView = useCodes();
  const { queued, tableCode, pending: queuePending } = useQueue();
  const seated = room !== null || queued;
  const seatedAt = seated ? (room?.room ?? tableCode ?? "") : null;
  const ready = status === "open" && starting === null;
  useEffect(() => {
    codes.setPlace({ ready: status === "open" && !offline, seatedAt });
  }, [status, offline, seatedAt, codeView?.step]);
  // A code typed in the box waits for its seats before the panel opens.
  const looking = codeView?.step === "peek" && !panelShown(codeView);
  const testReady = !w32Selected || testAccessKey.trim().length > 0;
  // An empty name never blocks a start: the test room's Create and the
  // panel's Join each fill the field with a random name and go, the same as
  // the dice.
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
    if (conn.send(payload)) setStarting({ generation: conn.generation });
  };

  // Drop the invite param once the user acts: otherwise a stale ?room=
  // keeps steering later flows (including starting a fresh game) and the
  // name field looks "stuck" on whatever the link implied.
  const clearInvite = () => {
    if (window.location.search) {
      window.history.replaceState({}, "", window.location.pathname);
    }
  };

  // The box takes a room or table code: its peek opens the panel.
  const join = () => {
    if (!ready || looking || normalizeCode(roomCode).length !== 4) return;
    codes.open(roomCode);
  };

  // Not now: the panel goes and the link with it; Play is back.
  const closeJoin = () => {
    codes.cancel();
    setRoomCode("");
  };

  // The panel's Join, under the name the chip shows (a guest's random one
  // until they edit it).
  const joinFromPanel = () => {
    const as = nameOrRandom();
    rememberName(as);
    codes.join(as);
  };

  const wide = useMediaQuery(WIDE);
  const screenRef = useRef<HTMLDivElement | null>(null);
  // a panel that opens puts the page back at its top, where the panel is
  const joinUp = panelShown(codeView) && !seated && !offline;
  const panelUp = offline ? offlineTable : (queued || joinUp) && !stalled;
  useEffect(() => {
    if (panelUp && screenRef.current) screenRef.current.scrollTop = 0;
  }, [panelUp]);

  // The test controls' room: a created room for the W32 policy, reached
  // only from ?test_shortlist=1. Every other table comes from Play.
  const createLabel = starting ? "Creating…" : "Create test room";
  const testRoom = testControlsVisible ? (
    <ul className="grp play-grp">
      <li>
        <button type="button" className="grp-row" disabled={!ready || !testReady} onClick={create}
                aria-busy={starting !== null || undefined}>
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
        {/* one column at every width: the art, then the controls or the
            table panel */}
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
            {joinUp ? (
              <JoinPanel code={codeView.code} peek={codeView.peek} seat={codeView.seat} full={codeView.full}
                         busy={codeView.step === "joining" || (codeView.step === "peek" && codeView.peek !== null)
                               || queuePending === "join"}
                         onJoin={joinFromPanel} onCancel={closeJoin} onPick={(at) => codes.pick(at)} />
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
                onChange={(e) => setRoomCode(e.target.value.toUpperCase())}
                onKeyDown={(e) => {
                  if (e.key === "Enter") join();
                }}
              />
              <button
                className="btn"
                disabled={!ready || looking || roomCode.trim().length !== 4}
                onClick={join}
                aria-busy={looking || undefined}
              >
                {looking ? "Joining…" : "Join"}
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
