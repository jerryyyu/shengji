import { useId, useState } from "react";
import { useAuth } from "../auth";
import GoogleSignIn from "../components/GoogleSignIn";
import { partnerName, queue, useQueue } from "./store";
import Sheet from "./Sheet";

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

/** Play's Ranked block. Signed in: a wide gold Play that joins the ranked
 *  queue at once (as the pair when one is formed and you lead it) and Duo,
 *  which opens the pair sheet. Signed out: Sign in to play ranked, which
 *  shows the sign-in buttons in its place. With sign-in off or still
 *  loading there is no ranked play to offer and nothing shows. */
export function RankedSection({ online }: {
  /** The socket is open; without it every ranked control is disabled. */
  online: boolean;
}) {
  const q = useQueue();
  const account = useAuth();
  const [signingIn, setSigningIn] = useState(false);
  const labelId = useId();
  if (account.status !== "in" && account.status !== "out") return null;

  let body;
  if (account.status === "out") {
    if (!account.clientId) return null;
    body = signingIn && online ? <GoogleSignIn clientId={account.clientId} /> : (
      <button type="button" className="btn play-signin" disabled={!online} onClick={() => setSigningIn(true)}>
        Sign in to play ranked
      </button>
    );
  } else {
    const pair = q.party && q.party.members.length === 2 ? q.party : null;
    const searching = q.queued || q.pending === "join";
    let label = "Play";
    let disabled = !online;
    if (searching) { label = "Searching…"; disabled = true; }
    else if (pair && !pair.you_lead) disabled = true;
    body = (
      <>
        <PartyChip />
        <div className="play-ranked-row">
          <button type="button" className={`btn gold play-main q-find${searching ? " searching" : ""}`}
                  disabled={disabled} aria-busy={searching || undefined} onClick={() => queue.join()}>
            {label}
          </button>
          <button type="button" className="btn play-duo" disabled={!online} onClick={() => queue.openParty()}>
            Duo
          </button>
        </div>
      </>
    );
  }
  return (
    <section className="play-section" aria-labelledby={labelId}>
      <h2 className="play-label ranked" id={labelId}><TrophyIcon />Ranked</h2>
      {body}
    </section>
  );
}

/** A guest who entered a duo code (in the Play box or from an invite link):
 *  duos are for signed-in players, so the sheet offers sign-in, after which
 *  the pair sheet opens with the code. */
export function GuestDuoSheet() {
  const q = useQueue();
  const account = useAuth();
  if (q.sheet !== "guest" || account.status === "in") return null;
  return (
    <Sheet title="Duo" onClose={() => queue.closeSheet()}>
      <div className="q-sheet-pad">
        <p className="q-foot q-center">
          {q.joinCode ? `Sign in to join duo ${q.joinCode}.` : "Sign in to play Duo."}
        </p>
        {account.status === "out" && account.clientId ? <GoogleSignIn clientId={account.clientId} /> : null}
      </div>
    </Sheet>
  );
}
