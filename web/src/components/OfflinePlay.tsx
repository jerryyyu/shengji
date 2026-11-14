// The Play tab with no game server: the same page, Casual the only mode, and
// a Play that opens your table with three bots on this device. Ranked, Duo
// and the code box need the server, so they stay in their places, disabled.
import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import type { ConnStatus } from "../ws";
import { clearSavedRoom, conn, getSavedName } from "../ws";
import { openHowto } from "../howto/route";
import { effectiveName, useAuth } from "../auth";
import { useOnline } from "../useOnline";
import { useInlineQueue } from "../queue/QueueBar";
import { MiniTable, TeamColumns } from "../queue/TablePanel";
import type { SeatItem } from "../queue/TablePanel";
import AccountChip from "./AccountChip";
import GuestChip, { GuestNameSheet } from "./GuestChip";
import LobbyPreview from "./LobbyPreview";
import { offlineGame } from "./offlineGame";
import "./OfflinePlay.css";

/** You at the bottom, Bot 2 across as your partner, Bots 1 and 3 opposite,
 *  as the offline server seats them. */
const SEATS: SeatItem[] = [
  { at: 0, look: "you", name: "You", sub: "", label: "You, your team" },
  { at: 1, look: "bot", name: "Bot 1", sub: "", label: "Bot 1, other team" },
  { at: 2, look: "bot", name: "Bot 2", sub: "", label: "Bot 2, your team" },
  { at: 3, look: "bot", name: "Bot 3", sub: "", label: "Bot 3, other team" },
];

/** Your offline table in Play's place: the queue's green panel, its one
 *  line saying Offline. Start deals at once; Leave puts Play back. */
function OfflineTable({ ready, starting, onStart, onLeave }: {
  ready: boolean; starting: boolean; onStart: () => void; onLeave: () => void;
}) {
  const wide = useInlineQueue();
  const titleId = useId();
  return (
    <section className={`tp tp-offline${wide ? " tp-wide" : ""}`} aria-labelledby={titleId}>
      <h2 className="tp-title" id={titleId}>You and 3 bots</h2>
      <p className="tp-line">Offline</p>
      {wide ? <MiniTable seats={SEATS} you={0} /> : <TeamColumns seats={SEATS} you={0} />}
      {/* the table's chat row in its place, greyed: chat needs the server */}
      <button type="button" className="tp-chat" disabled aria-label="Chat needs a connection">
        <span className="tp-chat-label" aria-hidden="true">Chat</span>
      </button>
      <div className="tp-acts">
        <button type="button" className="tp-primary" disabled={!ready || starting}
                aria-busy={starting || undefined} onClick={onStart}>
          {starting ? "Starting…" : "Start"}
        </button>
        <button type="button" className="tp-secondary" onClick={onLeave}>Leave</button>
      </div>
    </section>
  );
}

interface OfflineControlsProps {
  /** This page plays on the device (offline mode). Without it the page still
   *  belongs to the game server, which cannot be reached, and Play reloads
   *  the page in offline mode with the table open. */
  local: boolean;
  status: ConnStatus;
  error?: string | null;
  /** The room Start made, while bots fill it and the deal starts. */
  room?: string | null;
  /** Arm App's fill-with-bots-then-start chain before creating the room. */
  onArmAutoFill?: () => void;
}

/** Whether the offline table is up on this page's Play tab. */
function useOfflineTable(local: boolean): boolean {
  const table = useSyncExternalStore((l) => offlineGame.subscribe(l), () => offlineGame.tableOpen);
  return local && table;
}

/** The Play tab's controls with no connection, between the name chip and How
 *  to play: the mode switch, then Play, Duo, the presence line and the code
 *  box, or the offline table in their place. The online Play tab shows these
 *  in place of its own, so what surrounds them stays mounted. */
export function OfflineControls({ local, status, error = null, room = null, onArmAutoFill }: OfflineControlsProps) {
  const showTable = useOfflineTable(local);
  const online = useOnline();
  const account = useAuth();
  const signedIn = account.status === "in" && account.user ? account.user : null;
  const [sent, setSent] = useState(false);
  useEffect(() => { if (error) setSent(false); }, [error]);
  const modeId = useId();

  // Back here after a game from this table: the table has been left.
  const left = useRef(false);
  useEffect(() => {
    if (!local || !offlineGame.played) return;
    offlineGame.played = false;
    left.current = true;
    offlineGame.setTable(false);
  }, [local]);

  // An offline game stays offline: nothing moves the page online while its
  // table is up or its game is on (this screen is not shown then). Once the
  // table is left, a page with a network goes online again. A browser tab has
  // no other way to get its online Play tab back, so it goes whenever it is
  // here with a network; the app's bundled page waits for the network to
  // return or the table to be left, since its shell brings this page back
  // whenever the live site cannot load.
  const inApp = typeof location !== "undefined" && location.protocol === "capacitor:";
  const wasOnline = useRef(online);
  useEffect(() => {
    const cameBack = online && !wasOnline.current;
    wasOnline.current = online;
    if (!local || showTable || !online) return;
    if (cameBack || left.current || !inApp) offlineGame.goOnline();
  }, [local, showTable, online, inApp]);

  const leave = () => {
    if (room) conn.send({ type: "leave_room" });
    setSent(false);
    offlineGame.played = false;
    left.current = true;
    offlineGame.setTable(false);
  };
  const start = () => {
    if (status !== "open" || sent) return;
    setSent(true);
    offlineGame.played = true;
    clearSavedRoom();
    onArmAutoFill?.();
    conn.send({ type: "create_room", name: (signedIn ? effectiveName(signedIn) : getSavedName()).trim() || "Player" });
  };

  return (
    <>
      <div className="play-mode" role="group" aria-labelledby={modeId}>
        <span className="sr-only" id={modeId}>Mode</span>
        <button type="button" className="play-mode-opt" aria-pressed={false} disabled>Ranked</button>
        <button type="button" className="play-mode-opt on" aria-pressed={true}>Casual</button>
      </div>

      {showTable ? (
        <OfflineTable ready={status === "open"} starting={sent || room !== null}
                      onStart={start} onLeave={leave} />
      ) : (
        <>
          <div className="play-ranked-row">
            <button type="button" className="btn gold play-main" onClick={() => offlineGame.startFromPlay()}>
              Play
            </button>
            <button type="button" className="btn play-duo" disabled>Duo</button>
          </div>
          <p className="play-presence offline" role="status">
            <span className="play-presence-dot" aria-hidden="true" />
            <span>Offline</span>
          </p>
          <div className="join-row">
            <input className="room-input" placeholder="CODE" aria-label="Room or duo code" disabled />
            <button className="btn" disabled>Join</button>
          </div>
        </>
      )}
    </>
  );
}

/** The whole Play tab of a page in offline mode. */
export default function OfflinePlay(props: OfflineControlsProps & { local: true }) {
  const { error = null } = props;
  const showTable = useOfflineTable(true);
  const account = useAuth();
  const signedIn = account.status === "in" && account.user ? account.user : null;
  return (
    <div className="screen lobby-screen play-tab play-offline">
      <div className="panel lobby-panel">
        {/* the table takes the picture's place, so Start is on screen without a scroll */}
        {showTable ? null : (
          <>
            <h1 className="game-title">
              升级 <span className="game-title-en">Sheng Ji</span>
            </h1>
            <LobbyPreview />
          </>
        )}
        {signedIn ? <AccountChip user={signedIn} /> : <GuestChip />}
        {error ? <div className="lobby-error" role="alert">{error}</div> : null}
        <OfflineControls {...props} />
        <p className="howto-entry">
          <button className="howto-link" onClick={() => openHowto()}>How to play</button>
        </p>
      </div>
      {signedIn ? null : <GuestNameSheet />}
    </div>
  );
}
