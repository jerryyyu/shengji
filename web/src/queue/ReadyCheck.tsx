import { useEffect } from "react";
import type { ReactNode } from "react";
import { effectiveName, useAuth } from "../auth";
import { clock, partnerName, queue, useNow, useQueue } from "./store";
import type { ReadyCheck as Check } from "./store";

type TileKind = "you" | "known" | "player" | "bot";
interface Tile { name: string; kind: TileKind }
interface Teams { mine: [Tile, Tile]; theirs: [Tile, Tile] }

const you: Tile = { name: "You", kind: "you" };
const bot: Tile = { name: "Bot", kind: "bot" };
const player = (name: string): Tile => ({ name, kind: "player" });
const known = (name: string): Tile => ({ name, kind: "known" });

/** Who sits on which side, as far as the client can tell. The server sends
 *  no seats before everyone accepts, then only the humans' names in seat
 *  order (team 0 at seats 0+2), so teams are exact without bots; with bots
 *  they follow the matcher's rules (a pair sits together, humans spread
 *  across both teams), and a side it cannot place is shown unnamed. */
function teams(check: Check, me: string, partner: string | null): Teams {
  const names = check.names;
  const others = names ? names.filter((n, i) => i !== names.indexOf(me) && n !== partner) : [];
  const other = (i: number, label: string) => (others[i] !== undefined ? known(others[i]) : player(label));
  if (names && check.bots === 0) {
    const i = names.indexOf(me);
    if (i >= 0) {
      const at = (k: number) => known(names[(i + k) % 4]);
      return { mine: [you, at(2)], theirs: [at(1), at(3)] };
    }
  }
  const mate = partner ? known(partner) : null;
  if (check.size === 2 && check.bots === 2) {
    return mate ? { mine: [you, mate], theirs: [bot, bot] } : { mine: [you, bot], theirs: [other(0, "Player"), bot] };
  }
  if (check.size === 3 && check.bots === 1 && mate) {
    return { mine: [you, mate], theirs: [other(0, "Player"), bot] };
  }
  return { mine: [you, mate ?? player("Teammate")], theirs: [player("Opponent"), player("Opponent")] };
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return (parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[1][0]).toUpperCase();
}

function TileView({ tile, team, me, ready }: { tile: Tile; team: 0 | 1; me: string; ready: boolean }) {
  const mark = tile.kind === "you" ? initials(me || "You") : tile.kind === "bot" ? "BOT"
    : tile.kind === "player" ? "?" : initials(tile.name);
  return (
    <div className={`q-rc-seat ${tile.kind}`}>
      <span className={`q-rc-av team${team}`} aria-hidden="true">{mark}</span>
      <span className="q-rc-name">{tile.name}</span>
      {ready ? <span className="q-rc-ok" aria-label="ready">✓</span> : null}
    </div>
  );
}

/** Your side, VS, the other side, each in its team's colour. Only your own
 *  accept is marked: the others' answers are counts, never who. */
function TeamsView({ check, me, partner }: { check: Check; me: string; partner: string | null }) {
  const t = teams(check, me, partner);
  const all = check.names !== null;
  const mineReady = all || check.mine === "accepted";
  return (
    <div className="q-rc-teams" aria-label="Teams">
      <div className="q-rc-side">
        {t.mine.map((tile, i) => (
          <TileView key={i} tile={tile} team={0} me={me} ready={tile.kind === "you" ? mineReady : all && tile.kind !== "bot"} />
        ))}
      </div>
      <span className="q-rc-vs">VS</span>
      <div className="q-rc-side">
        {t.theirs.map((tile, i) => (
          <TileView key={i} tile={tile} team={1} me={me} ready={all && tile.kind !== "bot"} />
        ))}
      </div>
    </div>
  );
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
  const secs = clock(Math.max(0, left), true);
  const fill = check.bots > 0;
  const partner = check.partyId ? partnerName(q.party) : null;
  const me = account.status === "in" && account.user ? effectiveName(account.user) : "";
  const bots = check.bots === 1 ? "1 bot" : `${check.bots} bots`;

  if (check.names) {
    const names = check.names.map((n) => (n === me ? "you" : n));
    if (check.bots) names.push(bots);
    return (
      <MatchSheet title="Ranked match found">
        <TeamsView check={check} me={me} partner={partner} />
        <div className="q-rc-names">{names.join(" · ")}</div>
        <button type="button" className="q-rc-accept" disabled>Starting…</button>
      </MatchSheet>
    );
  }
  if (check.mine === "accepted") {
    return (
      <MatchSheet title="Ranked match found">
        <TeamsView check={check} me={me} partner={partner} />
        <button type="button" className="q-rc-accept" disabled>{check.accepted} of {check.of} ready · {secs}</button>
        <button type="button" className="q-rc-plain" onClick={() => queue.decline()}>Cancel</button>
      </MatchSheet>
    );
  }
  return (
    <MatchSheet title="Ranked match found">
      <TeamsView check={check} me={me} partner={partner} />
      <button type="button" className="q-rc-accept" disabled={left <= 0} onClick={() => queue.accept()} autoFocus>
        Accept · {secs}
      </button>
      {fill ? (
        <button type="button" className="q-rc-plain" onClick={() => queue.keepWaiting()}>Keep waiting</button>
      ) : (
        <button type="button" className="q-rc-plain" onClick={() => queue.decline()}>Decline</button>
      )}
    </MatchSheet>
  );
}

/** The ready check: a bottom sheet on a phone, a centred dialog from 700px.
 *  No line under the title: the teams show who plays, bots included, and
 *  the button carries the deadline and the ready count. */
function MatchSheet({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="q-layer q-rc-layer">
      <div className="q-scrim" />
      <div className="q-rc" role="alertdialog" aria-modal="true" aria-label={title}>
        <span className="q-rc-grab" aria-hidden="true" />
        <h2>{title}</h2>
        {children}
      </div>
    </div>
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
    ? `${missed.by} didn't accept, so the pair is out of the queue for 30 seconds.`
    : "You didn't accept in time, so you're out of the queue for 30 seconds.";
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
