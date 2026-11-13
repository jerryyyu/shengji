import { useState } from "react";
import { useAuth } from "../auth";
import { clock, partnerName, queue, useNow, useQueue } from "./store";
import Sheet from "./Sheet";
import { codes, useCodes } from "../codeJoin";
import { codeLink } from "../codes";
import { RankedChip } from "./Ranked";

function UsersIcon() {
  return (
    <svg className="q-users" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 19c0-3.4 2.9-5.5 6.5-5.5s6.5 2.1 6.5 5.5" />
      <circle cx="17" cy="9" r="2.6" />
      <path d="M16 13.6c3 .2 5.5 2 5.5 5" />
    </svg>
  );
}

/** Signed in, the Ranked sheet asks: Solo queues now, With a friend… makes a
 *  pair code to share. */
export function SoloSheet() {
  return (
    <Sheet title="Ranked" onClose={() => queue.closeSheet()}>
      <div className="q-sheet-pad">
        <button type="button" className="btn gold big q-find" onClick={() => queue.join()}>Solo</button>
      </div>
      <ul className="grp q-grp">
        <li>
          <button type="button" className="grp-row q-friend-row" onClick={() => queue.openParty()}>
            <UsersIcon />
            <span className="grp-label">With a friend…</span>
            <span className="grp-value chev" />
          </button>
        </li>
      </ul>
    </Sheet>
  );
}

function JoinByCode() {
  const q = useQueue();
  const waiting = useCodes().pending?.from === "pair";
  return (
    // A pair code joins the pair; a game code closes the sheet and opens
    // that room as the Play box would.
    <form className="q-join" onSubmit={(e) => { e.preventDefault(); if (!waiting) codes.lookup(q.joinCode, "pair"); }}>
      <label className="q-join-label" htmlFor="q-join-code">
        Join with a code
      </label>
      <div className="join-row">
        <input id="q-join-code" className="room-input" value={q.joinCode} maxLength={4} placeholder="CODE"
               aria-label="Duo or game code" autoCapitalize="characters" autoCorrect="off" spellCheck={false}
               onChange={(e) => queue.setJoinCode(e.target.value)} />
        <button type="submit" className="btn" disabled={waiting || q.joinCode.length !== 4}
                aria-busy={waiting || undefined}>
          {waiting ? "Joining…" : "Join"}
        </button>
      </div>
    </form>
  );
}

/** Duo: ranked play with a friend as your partner. Your pair code and link,
 *  or a friend's code to join; once the friend is in, the pair queues from
 *  here or from Play. */
export function PartySheet() {
  const q = useQueue();
  const guest = useAuth().status !== "in";
  const now = useNow(q.cooldownUntil !== null, 500);
  const cooling = q.cooldownUntil !== null && q.cooldownUntil > now;
  const [copied, setCopied] = useState<string | null>(null);
  const p = q.party;
  const other = partnerName(p);
  const copy = (text: string, what: string) => {
    navigator.clipboard?.writeText(text).then(() => setCopied(what)).catch(() => { /* clipboard blocked */ });
  };
  const share = (code: string) => {
    const url = codeLink(code);
    if (typeof navigator.share === "function") {
      navigator.share({ title: "Sheng Ji", text: `Queue with me in Sheng Ji: Duo code ${code}`, url })
        .catch(() => { /* share sheet dismissed */ });
    } else {
      copy(url, "link");
    }
  };

  let body;
  if (p && p.members.length === 2 && other) {
    body = (
      <>
        <div className="q-codebox"><small>Your Duo</small><b className="q-pair-names">You + {other}</b></div>
        <div className="q-sheet-pad">
          {p.you_lead ? (
            <button type="button" className="btn gold big q-find" disabled={q.queued || cooling}
                    onClick={() => queue.join()}>
              {cooling && q.cooldownUntil !== null ? `Play in ${clock(q.cooldownUntil - now, true)}` : "Play"}
            </button>
          ) : (
            <button type="button" className="btn big q-dis" disabled>{other} starts the search</button>
          )}
          <button type="button" className="btn big q-ghost" onClick={() => queue.leaveParty()}>Leave Duo</button>
        </div>
      </>
    );
  } else if (p) {
    body = (
      <>
        <div className="q-codebox"><small>Code</small><b>{p.code}</b></div>
        <div className="q-sheet-pad">
          <button type="button" className="btn gold big" onClick={() => share(p.code)}>
            {copied === "link" ? "Link copied" : "Invite partner"}
          </button>
          <button type="button" className="btn big q-ghost" onClick={() => copy(p.code, "code")}>
            {copied === "code" ? "Code copied" : "Copy code"}
          </button>
        </div>
        <JoinByCode />
      </>
    );
  } else {
    body = (
      <>
        {q.joinCode ? null : <div className="q-codebox"><small>Code</small><b>····</b></div>}
        {q.joinCode ? (
          <div className="q-sheet-pad">
            <button type="button" className="btn big q-ghost" onClick={() => queue.makeCode()}>
              New code
            </button>
          </div>
        ) : null}
        <JoinByCode />
      </>
    );
  }
  return (
    <Sheet title="Duo" onClose={() => queue.closeSheet()}>
      {/* a guest is never rated: its Duo is not marked Ranked */}
      {guest ? null : <div className="q-ranked-row"><RankedChip /></div>}
      {body}
      {q.partyError ? <p className="q-error" role="alert">{q.partyError}</p> : null}
    </Sheet>
  );
}
