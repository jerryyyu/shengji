import { useState } from "react";
import { useAuth } from "../auth";
import { guestName } from "../guestName";
import LeaveSheet from "../components/LeaveSheet";
import type { RoomMsg } from "../protocol";
import type { QueueMode } from "./messages";
import TablePanel, { RoomPanel, TableAnnouncer } from "./TablePanel";
import { useKindGuard } from "./useKindGuard";
import { panelKind, presenceParts, shortName } from "./tableText";
import "./playLines.css";
import { clock, queue, useNow, useQueue } from "./store";

/** The ranked mark: a trophy. */
export function TrophyIcon() {
  return (
    <svg className="trophy" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8 4h8v5a4 4 0 0 1-8 0z" />
      <path d="M8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4M12 13v4M9 20h6" />
    </svg>
  );
}

/** The line under a guest's Play: they queue like everyone, unrated, and
 *  Sign in opens the identity sheet. Without sign-in on this server the line
 *  says only that they play as a guest. */
function GuestLine({ online }: { online: boolean }) {
  const account = useAuth();
  const clientId = account.status === "out" ? account.clientId : null;
  return (
    <p className="play-guest-line">
      Playing as a guest
      {clientId ? (
        <>
          {" · "}
          <button type="button" className="play-guest-signin" disabled={!online}
                  onClick={() => guestName.open()}>Sign in</button>
          {" to be ranked"}
        </>
      ) : null}
    </p>
  );
}

/** The counts under Play and Duo: who is about, never a button. When both
 *  modes have tables, the selected mode's count is lit. */
function PresenceLine({ q }: { q: ReturnType<typeof useQueue> }) {
  return (
    <p className="play-presence">
      <span className="play-presence-dot" aria-hidden="true" />
      <span>
        {presenceParts(q.presence, q.playMode).map((part, i) => (
          part.hl ? <b key={i} className="play-presence-hl">{part.text}</b> : <span key={i}>{part.text}</span>
        ))}
      </span>
    </p>
  );
}

const MODES: { mode: QueueMode; label: string }[] = [{ mode: "ranked", label: "Ranked" }, { mode: "casual", label: "Casual" }];

/** Ranked / Casual above Play, remembered on this device. At a table it
 *  shows that table's mode and holds still. */
function ModeSwitch({ value, disabled }: { value: QueueMode; disabled: boolean }) {
  return (
    <div className="play-mode" role="group" aria-label="Mode">
      {MODES.map(({ mode, label }) => (
        <button key={mode} type="button" className={`play-mode-opt${value === mode ? " on" : ""}`}
                aria-pressed={value === mode} disabled={disabled}
                onClick={() => queue.setPlayMode(mode)}>
          {label}
        </button>
      ))}
    </div>
  );
}

/** Play refused because this account already plays a ranked game: the
 *  server's words in Play's place, with the way back when there is one. */
function InGameBlock({ message, canReturn, online }: { message: string; canReturn: boolean; online: boolean }) {
  return (
    <div className="play-in-game">
      <p className="play-in-game-line" role="status">{message}</p>
      <div className="play-ranked-row">
        {canReturn ? (
          <button type="button" className="btn gold play-main" disabled={!online} onClick={() => queue.returnToGame()}>
            I’m back
          </button>
        ) : null}
        <button type="button" className={canReturn ? "btn play-duo" : "btn play-main"}
                onClick={() => queue.dismissInGame()}>
          OK
        </button>
      </div>
    </div>
  );
}

/** A formed pair between games, for either member: who the Duo is with and
 *  a Leave that ends it (party_leave, never a search). Leave waits for the
 *  socket, and a send that fails keeps the sheet up. */
function PairRow({ partner, online }: { partner: string; online: boolean }) {
  const [asking, setAsking] = useState(false);
  return (
    <div className="play-ranked-row play-pair-row">
      <span className="play-pair-label">Duo with {shortName(partner)}</span>
      <button type="button" className="btn play-duo play-pair-leave" disabled={!online}
              onClick={() => setAsking(true)}>Leave</button>
      {asking ? (
        <LeaveSheet context={{ kind: "duo", partner, opener: false }}
                    onStay={() => setAsking(false)}
                    onLeave={() => { if (queue.leaveParty()) setAsking(false); }} />
      ) : null}
    </div>
  );
}

/** Play's block, the same for guests and accounts: the Ranked / Casual
 *  switch, a wide gold Play that joins the queue in that mode (as the pair
 *  when one is formed and you lead it) and Duo, which opens your own table
 *  with the partner seat held; its code is the Duo's invite.
 *  At a table the panel takes the buttons' place on every screen: a room's
 *  (`room`, before its game) or the queue's. A guest sees a line under the
 *  buttons that offers sign-in. While sign-in is still loading nothing
 *  shows. With no connection for a while the Play tab shows its offline
 *  controls in this block's place. */
export function RankedSection({ online, room = null }: {
  /** The socket is open; without it every queue control is disabled. */
  online: boolean;
  /** The room this socket sits in before its game, if any. */
  room?: RoomMsg | null;
}) {
  const q = useQueue();
  const account = useAuth();
  const kind = panelKind(q);
  // "I’m back" and Start share the primary place: the guard covers each swap
  const guarded = useKindGuard(kind === "shared" && q.stillHereUntil !== null ? "still_here" : kind);
  const now = useNow(q.cooldownUntil !== null, 500);

  const pair = q.party && q.party.members.length === 2 ? q.party : null;
  const joining = q.pending === "join";
  const cooling = q.cooldownUntil !== null && q.cooldownUntil > now;
  let label = "Play";
  let disabled = !online || guarded;
  if (joining) disabled = true;
  else if (cooling) {
    // a table you joined and left: Play counts the queue cooldown down
    label = `Play in ${clock(q.cooldownUntil! - now, true)}`;
    disabled = true;
  } else if (pair && !pair.you_lead) disabled = true;
  // the switch shows the mode of the table you sit at, else your choice
  const tableMode: QueueMode | null = room ? (room.matched || room.ranked ? "ranked" : "casual")
    : kind !== "play" ? q.queueMode ?? q.playMode : null;
  const modes = <ModeSwitch value={tableMode ?? q.playMode} disabled={tableMode !== null || joining || !!q.inGame} />;
  // first in every branch, so the live region stays mounted as the panel changes kind
  const announcer = <TableAnnouncer q={q} />;
  // a room's panel needs no account: it shows while sign-in is still unknown
  if (room) {
    return (
      <>
        {announcer}
        <div className="play-section play-table">
          {modes}
          <RoomPanel room={room} />
        </div>
      </>
    );
  }
  if (account.status === "loading" || account.status === "error") return null;
  const guest = account.status !== "in";
  if (kind !== "play") {
    return (
      <>
        {announcer}
        <div className="play-section play-table">
          {modes}
          <TablePanel q={q} guarded={guarded} />
        </div>
      </>
    );
  }
  // the leader searches for the pair; the other member has only the row
  const partner = pair ? pair.members.find((m) => !m.you)?.name ?? null : null;
  const pairRow = partner ? <PairRow partner={partner} online={online} /> : null;
  const body = q.inGame ? (
    <InGameBlock message={q.inGame.message} canReturn={q.inGame.canReturn} online={online} />
  ) : pairRow && !pair!.you_lead ? pairRow : (
    <>
      {pairRow}
      {cooling && !q.cooldownTold ? <p className="play-cool-line">You left a table you joined.</p> : null}
      <div className="play-ranked-row">
        <button type="button" className={`btn gold play-main q-find${joining ? " searching" : ""}`}
                disabled={disabled} aria-busy={joining || undefined} onClick={() => queue.join()}>
          {label}
        </button>
        <button type="button" className="btn play-duo" disabled={disabled} onClick={() => queue.joinDuo()}>
          Duo
        </button>
      </div>
      {online && !cooling ? <PresenceLine q={q} /> : null}
    </>
  );
  return (
    <>
      {announcer}
      <section className={`play-section${guest ? " play-guest" : ""}`} aria-label="Play">
        {modes}
        {body}
        {guest ? <GuestLine online={online} /> : null}
      </section>
    </>
  );
}
