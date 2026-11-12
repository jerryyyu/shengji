import type { ReactNode } from "react";
import { useAuth } from "../auth";
import { openTab } from "../home/route";
import { clock, partnerName, queue, useNow, useQueue } from "./store";
import Sheet from "./Sheet";

/** "● 3 in queue", hidden below one. */
function CountLine({ count }: { count: number }) {
  if (count < 1) return null;
  return (
    <span className="q-find-sub"><span className="q-dot" aria-hidden="true" />{count} in queue</span>
  );
}

/** The pair above Find a game: "You + Sam · you lead · Leave", or the code
 *  still waiting for a friend. */
export function PartyChip() {
  const q = useQueue();
  const p = q.party;
  if (!p) return null;
  const other = partnerName(p);
  if (p.members.length < 2 || !other) {
    return (
      <div className="q-party-chip waiting">
        <button type="button" className="q-party-main" onClick={() => queue.openParty()}>
          Pair code <b>{p.code}</b><span className="q-party-sub">· waiting for a friend</span>
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

/** Play's one gold action. Signed in, it asks Solo or With a friend (or
 *  queues a formed pair at once); a guest is offered bots now or sign-in. */
export default function FindGame({ ready, onPlayBots, botsBusy }: {
  /** The socket is open and no other start is waiting. */
  ready: boolean;
  /** Today's unrated you + 3 bots game, for a guest. */
  onPlayBots: () => void;
  botsBusy: boolean;
}) {
  const q = useQueue();
  const account = useAuth();
  const signedIn = account.status === "in";
  const cooling = q.cooldownUntil !== null && !q.queued;
  const now = useNow(cooling, 250);
  const coolLeft = cooling ? q.cooldownUntil! - now : 0;
  const pair = signedIn && q.party && q.party.members.length === 2 ? q.party : null;
  const searching = q.queued || q.pending === "join";

  let label = pair ? "Find a game as a pair" : "Find a game";
  let sub: ReactNode = <CountLine count={q.count} />;
  let disabled = !ready;
  if (botsBusy) { label = "Starting…"; disabled = true; }
  else if (searching) { label = "Finding a game…"; disabled = true; }
  else if (signedIn && coolLeft > 0) {
    label = `Queue again in ${clock(coolLeft, true)}`;
    sub = null;
    disabled = true;
  }
  else if (pair && !pair.you_lead) {
    disabled = true;
    sub = <span className="q-find-sub">{partnerName(pair)} starts the search</span>;
  }

  const tap = () => {
    if (disabled) return;
    if (!signedIn) queue.openSheet("guest");
    else if (pair) queue.join();
    else queue.openSheet("solo");
  };

  return (
    <>
      {signedIn ? <PartyChip /> : null}
      <button type="button" className={`btn gold big q-find${searching ? " searching" : ""}`}
              disabled={disabled} onClick={tap} aria-busy={botsBusy || searching || undefined}>
        <span>{label}</span>
        {sub}
      </button>
      {q.sheet === "guest" ? (
        <Sheet title="Find a game" onClose={() => queue.closeSheet()}>
          <div className="q-sheet-pad">
            <button type="button" className="btn gold big q-find" disabled={!ready}
                    onClick={() => { queue.closeSheet(); onPlayBots(); }}>
              <span>Play vs bots now</span>
              <span className="q-find-sub">unrated · you + 3 bots · starts now</span>
            </button>
            {account.status === "out" ? (
              <button type="button" className="btn big q-ghost"
                      onClick={() => { queue.findAfterSignIn = true; queue.closeSheet(); openTab("me"); }}>
                Sign in to play people
              </button>
            ) : null}
          </div>
          {account.status === "out" ? (
            <p className="q-foot q-center">
              Rated games with people need an account. Google now; Apple is coming soon. You come back to this choice after signing in.
            </p>
          ) : null}
        </Sheet>
      ) : null}
    </>
  );
}
