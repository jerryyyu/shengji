import { useState } from "react";
import { partnerName, queue, useQueue } from "./store";
import Sheet from "./Sheet";

function inviteLink(code: string): string {
  return `${window.location.origin}/?party=${code}`;
}

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

/** Signed in, Find a game asks: Solo queues now, With a friend… makes a
 *  pair code to share. */
export function SoloSheet() {
  return (
    <Sheet title="Find a game" onClose={() => queue.closeSheet()}>
      <div className="q-sheet-pad">
        <button type="button" className="btn gold big q-find" onClick={() => queue.join()}>Solo</button>
      </div>
      <ul className="grp q-grp">
        <li>
          <button type="button" className="grp-row q-friend-row" onClick={() => queue.openParty()}>
            <UsersIcon />
            <span className="grp-label">With a friend…<small>Invite by code or link; you are always partners</small></span>
            <span className="grp-value chev" />
          </button>
        </li>
      </ul>
    </Sheet>
  );
}

function JoinByCode() {
  const q = useQueue();
  return (
    <form className="q-join" onSubmit={(e) => { e.preventDefault(); queue.joinParty(q.joinCode); }}>
      <label className="q-join-label" htmlFor="q-join-code">Got a code from a friend?</label>
      <div className="join-row">
        <input id="q-join-code" className="room-input" value={q.joinCode} maxLength={4} placeholder="CODE"
               aria-label="Pair code" autoCapitalize="characters" autoCorrect="off" spellCheck={false}
               onChange={(e) => queue.setJoinCode(e.target.value)} />
        <button type="submit" className="btn" disabled={q.joinCode.length !== 4}>Join</button>
      </div>
    </form>
  );
}

/** Queue with a friend: your pair code and link, or a friend's code to join;
 *  once the friend is in, the pair queues from here or from Play. */
export function PartySheet() {
  const q = useQueue();
  const [copied, setCopied] = useState<string | null>(null);
  const p = q.party;
  const other = partnerName(p);
  const copy = (text: string, what: string) => {
    navigator.clipboard?.writeText(text).then(() => setCopied(what)).catch(() => { /* clipboard blocked */ });
  };
  const share = (code: string) => {
    const url = inviteLink(code);
    if (typeof navigator.share === "function") {
      navigator.share({ title: "Sheng Ji", text: `Queue with me in Sheng Ji: pair code ${code}`, url })
        .catch(() => { /* share sheet dismissed */ });
    } else {
      copy(url, "link");
    }
  };

  let body;
  if (p && p.members.length === 2 && other) {
    body = (
      <>
        <div className="q-codebox"><small>Your pair</small><b className="q-pair-names">You + {other}</b></div>
        <div className="q-sheet-pad">
          {p.you_lead ? (
            <button type="button" className="btn gold big q-find" disabled={q.queued}
                    onClick={() => queue.join()}>Find a game as a pair</button>
          ) : (
            <button type="button" className="btn big q-dis" disabled>{other} starts the search</button>
          )}
          <button type="button" className="btn big q-ghost" onClick={() => queue.leaveParty()}>Leave pair</button>
        </div>
      </>
    );
  } else if (p) {
    body = (
      <>
        <div className="q-codebox"><small>Pair code · share it or the link</small><b>{p.code}</b></div>
        <div className="q-sheet-pad">
          <button type="button" className="btn gold big" onClick={() => share(p.code)}>
            {copied === "link" ? "Link copied" : "Share invite link"}
          </button>
          <button type="button" className="btn big q-ghost" onClick={() => copy(p.code, "code")}>
            {copied === "code" ? "Code copied" : "Copy code"}
          </button>
        </div>
        <p className="q-foot">
          Your friend must be signed in. When they join you queue together and are always partners; your pair is
          matched on your average rating.
        </p>
        <JoinByCode />
      </>
    );
  } else {
    body = (
      <>
        {q.joinCode ? null : <div className="q-codebox"><small>Pair code</small><b>····</b></div>}
        {q.joinCode ? (
          <div className="q-sheet-pad">
            <button type="button" className="btn big q-ghost" onClick={() => queue.makeCode()}>
              Make my own code instead
            </button>
          </div>
        ) : null}
        <JoinByCode />
      </>
    );
  }
  return (
    <Sheet title="Queue with a friend" onClose={() => queue.closeSheet()}>
      {body}
      {q.partyError ? <p className="q-error" role="alert">{q.partyError}</p> : null}
    </Sheet>
  );
}
