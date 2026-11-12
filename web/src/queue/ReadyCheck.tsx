import { useEffect } from "react";
import type { ReactNode } from "react";
import { effectiveName, useAuth } from "../auth";
import { clock, partnerName, queue, useNow, useQueue } from "./store";
import type { ReadyCheck as Check } from "./store";

const BOT_SEATS: Record<number, string> = {
  1: "A bot takes the empty seat", 2: "Two bots take the empty seats", 3: "Three bots take the empty seats",
};

const R = 42;
const CIRC = 2 * Math.PI * R;

function Ring({ label, frac, done }: { label: string; frac: number; done?: boolean }) {
  return (
    <div className={`q-ring${done ? " done" : ""}`} aria-hidden="true">
      <svg viewBox="0 0 96 96">
        <circle cx="48" cy="48" r={R} className="q-ring-track" />
        <circle cx="48" cy="48" r={R} className="q-ring-arc"
                strokeDasharray={`${(CIRC * Math.max(0, Math.min(1, frac))).toFixed(1)} ${CIRC.toFixed(1)}`} />
      </svg>
      <span className="q-ring-n">{label}</span>
    </div>
  );
}

/** One pip per seat: the humans who accepted (counts only, never who), the
 *  ones still to answer, and the bots. */
function Pips({ check }: { check: Check }) {
  const pips = [];
  for (let i = 0; i < check.size; i += 1) {
    const ok = i < check.accepted;
    pips.push(<i key={`h${i}`} className={ok ? "ok" : ""}>{ok ? "✓" : ""}</i>);
  }
  for (let i = 0; i < check.bots; i += 1) pips.push(<i key={`b${i}`} className="bot">BOT</i>);
  return <div className="q-pips" aria-label={`${check.accepted} of ${check.of} ready`}>{pips}</div>;
}

/** While a ready check waits on a desktop player in another tab, the tab's
 *  title says so. */
function useTitleFlash(active: boolean) {
  useEffect(() => {
    if (!active) return;
    const base = document.title;
    let on = false;
    const t = window.setInterval(() => {
      on = document.hidden ? !on : false;
      document.title = on ? "Match found!" : base;
    }, 1000);
    return () => { window.clearInterval(t); document.title = base; };
  }, [active]);
}

function CheckDialog({ check }: { check: Check }) {
  const q = useQueue();
  const account = useAuth();
  const now = useNow(true, 200);
  useTitleFlash(check.mine === "pending");
  const left = check.deadline - now;
  const frac = left / check.window;
  const secs = String(Math.max(0, Math.ceil(left / 1000)));
  const fill = check.bots > 0;
  const partner = check.partyId ? partnerName(q.party) : null;
  const me = account.status === "in" && account.user ? effectiveName(account.user) : "";

  if (check.names) {
    const names = check.names.map((n) => (n === me ? "you" : n));
    if (check.bots) names.push(check.bots === 1 ? "1 bot" : `${check.bots} bots`);
    return (
      <Dialog title="Match found" big="Starting…">
        <Ring label="✓" frac={1} done />
        <p>Everyone accepted. Dealing in a moment.</p>
        <Pips check={{ ...check, accepted: check.size }} />
        <div className="q-dlg-b"><div className="btn gold q-names">{names.join(" · ")}</div></div>
      </Dialog>
    );
  }
  if (check.mine === "accepted") {
    return (
      <Dialog title="Match found" big="You're ready">
        <Ring label={secs} frac={frac} />
        <p>{partner && check.accepted < 2 ? `Waiting for ${partner}…` : "Waiting for the others…"}</p>
        <Pips check={check} />
        <div className="q-dlg-b">
          <button type="button" className="btn q-ghost" onClick={() => queue.decline()}>Cancel</button>
          <button type="button" className="btn q-dis" disabled>{check.accepted} of {check.of} ready</button>
        </div>
        <div className="q-sub">Names are shown when everyone has accepted.</div>
      </Dialog>
    );
  }
  const bots = check.bots === 1 ? "1 bot" : `${check.bots} bots`;
  const big = fill ? `Starting with ${bots}` : partner ? "Ready? Both of you" : "Ready?";
  const text = fill
    ? `A minute with no full table. ${BOT_SEATS[check.bots] ?? `${bots} take the empty seats`}; the game is rated and bots count as 1000.`
    : partner ? `${partner} must accept too. If either of you misses it, the pair is out for 30 s.`
    : "Four players found. Accept within 10 s or you go back to the lobby.";
  return (
    <Dialog title={fill ? "Not enough players" : "Match found"} big={big}>
      <Ring label={secs} frac={frac} />
      <p>{text}</p>
      <Pips check={check} />
      <div className="q-dlg-b">
        {fill ? (
          <button type="button" className="btn q-ghost" onClick={() => queue.keepWaiting()}>Keep waiting</button>
        ) : (
          <button type="button" className="btn q-ghost" onClick={() => queue.decline()}>Decline</button>
        )}
        <button type="button" className="btn gold" disabled={left <= 0} onClick={() => queue.accept()} autoFocus>
          Accept
        </button>
      </div>
    </Dialog>
  );
}

function MissedDialog() {
  const q = useQueue();
  const missed = q.missed!;
  const now = useNow(true, 250);
  const left = q.cooldownUntil !== null ? q.cooldownUntil - now : 0;
  const pair = q.party && q.party.members.length === 2 ? q.party : null;
  const verb = missed.reason === "declined" ? "declined" : "missed it";
  const big = missed.by ? `${missed.by} ${verb}` : "You missed it";
  const text = missed.by
    ? `${missed.by} didn't accept, so the pair is out of the queue for 30 seconds. The others kept their place.`
    : "You didn't accept in time, so you're out of the queue for 30 seconds. The other players kept their place.";
  const waitingOnLeader = pair !== null && !pair.you_lead;
  return (
    <Dialog title="Ready check" big={big}>
      <p className="q-gap">{text}</p>
      <div className="q-dlg-b">
        <button type="button" className="btn q-ghost" onClick={() => queue.dismissMissed()}>Not now</button>
        {left > 0 ? (
          <button type="button" className="btn q-dis" disabled>Queue again in {clock(left, true)}</button>
        ) : waitingOnLeader ? (
          <button type="button" className="btn q-dis" disabled>{partnerName(pair)} leads</button>
        ) : (
          <button type="button" className="btn gold" onClick={() => queue.join()}>Queue again</button>
        )}
      </div>
    </Dialog>
  );
}

function Dialog({ title, big, children }: { title: string; big: string; children: ReactNode }) {
  return (
    <div className="q-layer q-center-layer">
      <div className="q-scrim" />
      <div className="q-dlg" role="alertdialog" aria-modal="true" aria-label={`${title}: ${big}`}>
        <h3>{title}</h3>
        <div className="q-big">{big}</div>
        {children}
      </div>
    </div>
  );
}

/** The ready check, or what happened when it was missed. */
export default function ReadyCheck() {
  const q = useQueue();
  if (q.check) return <CheckDialog check={q.check} />;
  if (q.missed) return <MissedDialog />;
  return null;
}
