import { useId, useState } from "react";
import { useAuth } from "../auth";
import GoogleSignIn from "../components/GoogleSignIn";
import TablePanel, { TableAnnouncer } from "./TablePanel";
import { useKindGuard } from "./useKindGuard";
import { panelKind, presenceLine } from "./tableText";
import "./playLines.css";
import { clock, partnerName, queue, useNow, useQueue } from "./store";

/** The ranked mark: a trophy. */
export function TrophyIcon() {
  return (
    <svg className="trophy" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8 4h8v5a4 4 0 0 1-8 0z" />
      <path d="M8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4M12 13v4M9 20h6" />
    </svg>
  );
}

/** "RANKED" with its trophy, as a small gold chip. */
export function RankedChip() {
  return <span className="ranked-chip"><TrophyIcon />Ranked</span>;
}

/** The pair above Play: "You + Sam · you lead · Leave", or the code still
 *  waiting for a friend. */
export function PartyChip() {
  const q = useQueue();
  const p = q.party;
  if (!p) return null;
  const other = partnerName(p);
  if (p.members.length < 2 || !other) {
    return (
      <div className="q-party-chip waiting">
        <button type="button" className="q-party-main" onClick={() => queue.openParty()}>
          Duo code <b>{p.code}</b>
        </button>
        <button type="button" className="q-party-leave" onClick={() => queue.leaveParty()}>Leave</button>
      </div>
    );
  }
  const leader = p.members.find((m) => m.leader);
  return (
    <div className="q-party-chip">
      <span className="q-party-main">
        <span className="q-av" aria-hidden="true">{(p.members.find((m) => m.you)?.name ?? "Y").slice(0, 1)}</span>
        <span className="q-av q-av2" aria-hidden="true">{other.slice(0, 1)}</span>
        You + {other}
        <span className="q-party-sub">· {p.you_lead ? "you lead" : `${leader?.name ?? other} leads`}</span>
      </span>
      <button type="button" className="q-party-leave" onClick={() => queue.leaveParty()}>Leave</button>
    </div>
  );
}

/** The line under a guest's Play: they queue like everyone, unrated, and
 *  Sign in shows the sign-in buttons in the line's place. Without sign-in on
 *  this server the line says only that they play as a guest. */
function GuestLine({ online }: { online: boolean }) {
  const account = useAuth();
  const [signingIn, setSigningIn] = useState(false);
  const clientId = account.status === "out" ? account.clientId : null;
  if (clientId && signingIn && online) return <GoogleSignIn clientId={clientId} />;
  return (
    <p className="play-guest-line">
      Playing as a guest
      {clientId ? (
        <>
          {" · "}
          <button type="button" className="play-guest-signin" disabled={!online}
                  onClick={() => setSigningIn(true)}>Sign in</button>
          {" to be ranked"}
        </>
      ) : null}
    </p>
  );
}

/** The counts under Play and Duo: who is about, never a button. */
function PresenceLine({ q }: { q: ReturnType<typeof useQueue> }) {
  return (
    <p className="play-presence">
      <span className="play-presence-dot" aria-hidden="true" />
      <span>{presenceLine(q.presence)}</span>
    </p>
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
            Return to your game
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

/** Play's queue block, the same for guests and accounts: a wide gold Play
 *  that joins the queue at once (as the pair when one is formed and you lead
 *  it) and Duo, which opens the pair sheet. An account sees it under a Ranked
 *  heading; a guest, whose rounds are not rated, sees no heading and a line
 *  under the buttons that offers sign-in. While queued, the table panel takes
 *  the buttons' place on every screen. While sign-in is still loading nothing
 *  shows. */
export function RankedSection({ online }: {
  /** The socket is open; without it every queue control is disabled. */
  online: boolean;
}) {
  const q = useQueue();
  const account = useAuth();
  const labelId = useId();
  const kind = panelKind(q);
  // "I'm here" and Start share the primary place: the guard covers each swap
  const guarded = useKindGuard(kind === "shared" && q.stillHereUntil !== null ? "still_here" : kind);
  const now = useNow(q.cooldownUntil !== null, 500);
  if (account.status === "loading" || account.status === "error") return null;
  const guest = account.status !== "in";

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
  // first in every branch, so the live region stays mounted as the panel changes kind
  const announcer = <TableAnnouncer q={q} />;
  if (kind !== "play") {
    return (
      <>
        {announcer}
        <div className="play-section play-table">
          <PartyChip />
          <TablePanel q={q} guarded={guarded} />
        </div>
      </>
    );
  }
  const body = q.inGame ? (
    <>
      <PartyChip />
      <InGameBlock message={q.inGame.message} canReturn={q.inGame.canReturn} online={online} />
    </>
  ) : (
    <>
      <PartyChip />
      {cooling && !q.cooldownTold ? <p className="play-cool-line">You left a table you joined.</p> : null}
      <div className="play-ranked-row">
        <button type="button" className={`btn gold play-main q-find${joining ? " searching" : ""}`}
                disabled={disabled} aria-busy={joining || undefined} onClick={() => queue.join()}>
          {label}
        </button>
        <button type="button" className="btn play-duo" disabled={!online || cooling} onClick={() => queue.openParty()}>
          Duo
        </button>
      </div>
      {online && !cooling ? <PresenceLine q={q} /> : null}
    </>
  );
  if (guest) {
    return (
      <>
        {announcer}
        <section className="play-section play-guest" aria-label="Play">
          {body}
          <GuestLine online={online} />
        </section>
      </>
    );
  }
  return (
    <>
      {announcer}
      <section className="play-section" aria-labelledby={labelId}>
        <h2 className="play-label ranked" id={labelId}><TrophyIcon />Ranked</h2>
        {body}
      </section>
    </>
  );
}
