import { useEffect, useId, useRef } from "react";
import type { ReactNode, RefObject } from "react";
import { useAuth } from "../auth";
import { seatPos } from "../components/TrickArea";
import { useInlineQueue } from "./QueueBar";
import { BOTS_WARN_MS, partnerName, queue, useNow } from "./store";
import type { OfferView, QueueView, TableView } from "./store";
import {
  JUST_JOINED_MS, OFFER_CLOCK_MS, announcement, joinLabel, joinLines, joinTitle, ownTimerLine, panelKind,
  sharedTimerLine, sharedTitle, shortName, startLabel, stillHereLine,
} from "./tableText";
import type { PanelKind } from "./tableText";

/** One seat as the panel draws it, on a phone's team columns or on the
 *  wide screens' mini table. */
interface SeatItem {
  at: number;
  look: "you" | "friend" | "person" | "open" | "bot";
  name: string;
  sub: string;
  /** Read by a screen reader: the full name and the seat's team. */
  label: string;
  tick?: boolean;
  /** An open seat you may take: tapping it picks it. */
  pick?: () => void;
  busy?: boolean;
}

const teamWord = (ours: boolean) => (ours ? "your team" : "other team");

/** The seats of the table an offer would sit you at, you in the picked seat. */
function offerSeats(o: OfferView, busy: boolean): SeatItem[] {
  return o.seats.map((s, at) => {
    const ours = (at - o.pick + 4) % 2 === 0;
    const partnerSeat = o.seats[(o.pick + 2) % 4];
    if (at === o.pick) {
      const with_ = partnerSeat && !partnerSeat.bot && !partnerSeat.open && !o.partner
        ? `${shortName(partnerSeat.name)}'s partner` : "";
      return { at, look: "you", name: "You", sub: with_, label: `You, ${teamWord(true)}` };
    }
    if (o.partner && at === o.partner.seat) {
      return { at, look: "friend", name: shortName(o.partner.name), sub: "your Duo partner",
               label: `${o.partner.name}, your Duo partner` };
    }
    if (s.open && !o.partner) {
      const holder = s.bot ? "a bot holds it" : `${shortName(s.name)} · away`;
      const away = s.bot ? "" : `, ${s.name} is away`;
      return { at, look: "open", name: "Open seat", sub: holder, busy,
               label: `Open seat, ${teamWord(ours)}${away}. Sit here`, pick: () => queue.offerPick(at) };
    }
    if (s.bot || s.open) return { at, look: "bot", name: "Bot", sub: "a bot plays", label: `Bot, ${teamWord(ours)}` };
    return { at, look: "person", name: shortName(s.name), sub: "playing", label: `${s.name}, playing, ${teamWord(ours)}` };
  });
}

/** Your own table, drawn from the lone queue entry: the server keeps no
 *  table for one, so you sit at the bottom and a Duo partner across. */
function ownSeats(q: QueueView): SeatItem[] {
  const partner = q.partyId ? partnerName(q.party) : null;
  return [0, 1, 2, 3].map((at): SeatItem => {
    if (at === 0) return { at, look: "you", name: "You", sub: "", label: "You, your team" };
    if (at === 2 && partner) {
      return { at, look: "friend", name: shortName(partner), sub: "your Duo partner", label: `${partner}, your Duo partner` };
    }
    const ours = at === 2;
    return { at, look: "open", name: "Open seat", sub: ours ? "partner" : "", label: `Open seat, ${teamWord(ours)}` };
  });
}

/** Whether you may move seats: a single, before your Start, with someone
 *  else at the table. A Duo's seats stay together. */
function canMove(q: QueueView): boolean {
  const t = q.table;
  return !!t && !q.partyId && !t.youReady && t.of >= 2 && q.stillHereUntil === null;
}

/** A shared table's seats; with `move`, an empty seat is a button that
 *  moves you there. */
function sharedSeats(t: TableView, now: number, move: boolean, busy: boolean): SeatItem[] {
  return [0, 1, 2, 3].map((at): SeatItem => {
    const s = t.seats[at] ?? null;
    const ours = (at - t.you + 4) % 2 === 0;
    if (!s && move) {
      return { at, look: "open", name: "Open seat", sub: "", busy,
               label: `Open seat, ${teamWord(ours)}. Move here`, pick: () => queue.tableMove(at) };
    }
    if (!s) return { at, look: "open", name: "Open seat", sub: "", label: `Open seat, ${teamWord(ours)}` };
    const status = s.reconnecting ? "Reconnecting"
      : !s.you && !s.ready && s.since !== null && now - s.since < JUST_JOINED_MS ? "Just joined"
      : "";
    if (s.you) {
      return { at, look: "you", name: "You", sub: status, tick: s.ready,
               label: ["You", s.ready ? "ready" : null, status || null].filter(Boolean).join(", ") };
    }
    const role = s.pair ? "your Duo partner" : ours ? "your partner" : "";
    const sub = status || role;
    return { at, look: s.pair ? "friend" : "person", name: shortName(s.name), sub, tick: s.ready,
             label: [s.name, s.ready ? "ready" : null, sub || null, teamWord(ours)].filter(Boolean).join(", ") };
  });
}

function SeatBody({ s }: { s: SeatItem }) {
  return (
    <>
      <span className="tp-av" aria-hidden="true">{s.look === "open" ? "+" : s.look === "bot" ? "·" : s.name.slice(0, 2).toUpperCase()}</span>
      <span className="tp-seat-text" aria-hidden="true">
        <span className="tp-seat-name">{s.name}{s.tick ? <span className="tp-tick"> ✓</span> : null}</span>
        {s.sub ? <span className="tp-seat-sub">{s.sub}</span> : null}
      </span>
    </>
  );
}

function Seat({ s, team, cls = "" }: { s: SeatItem; team: 0 | 1; cls?: string }) {
  const className = `tp-seat ${s.look} team${team}${cls}`;
  if (s.pick) {
    return (
      <button type="button" className={className} aria-label={s.label} disabled={s.busy} onClick={s.pick}>
        <SeatBody s={s} />
      </button>
    );
  }
  return <div className={className} role="group" aria-label={s.label}><SeatBody s={s} /></div>;
}

/** A phone's seats: your team on the left, partner above you, the other
 *  team on the right. */
function TeamColumns({ seats, you }: { seats: SeatItem[]; you: number }) {
  const ours = [(you + 2) % 4, you].map((at) => seats[at]);
  const theirs = [(you + 1) % 4, (you + 3) % 4].map((at) => seats[at]);
  return (
    <div className="tp-teams">
      <span className="tp-team-label ours" aria-hidden="true">Your team</span>
      <span aria-hidden="true" />
      <span className="tp-team-label theirs" aria-hidden="true">Opponents</span>
      <div className="tp-col">{ours.map((s) => <Seat key={s.at} s={s} team={0} />)}</div>
      <span className="tp-vs" aria-hidden="true">VS</span>
      <div className="tp-col">{theirs.map((s) => <Seat key={s.at} s={s} team={1} />)}</div>
    </div>
  );
}

/** Wide screens: the seats around a green table, you at the bottom. */
function MiniTable({ seats, you }: { seats: SeatItem[]; you: number }) {
  return (
    <div className="seat-clock still tp-clock">
      {seats.map((s) => (
        <Seat key={s.at} s={s} team={(s.at - you + 4) % 2 === 0 ? 0 : 1} cls={` pos-${seatPos(s.at, you)}`} />
      ))}
    </div>
  );
}

/** The leader's switch on your own table: on, your timer never starts a
 *  bot game alone; off, the bot countdown runs. */
function WaitSwitch({ q }: { q: QueueView }) {
  return (
    <button type="button" role="switch" aria-checked={q.waitPlayers} className="q-wait tp-switch"
            disabled={q.pending !== null}
            onClick={() => (q.waitPlayers ? queue.allowBots() : queue.waitForPlayers())}>
      <span className="q-wait-label">Wait for people</span>
      <span className="q-switch" aria-hidden="true" />
    </button>
  );
}

interface PanelParts {
  kicker: string;
  title: string;
  lines: { text: string; warn?: boolean }[];
  seats: SeatItem[] | null;
  you: number;
  hint?: string;
  extra?: ReactNode;
  primary: { label: string; disabled: boolean; onClick: () => void } | null;
  secondary: { label: string; disabled: boolean; onClick: () => void } | null;
  /** A Duo's other member: who presses the buttons instead. */
  led?: string;
}

function parts(q: QueueView, kind: PanelKind, guest: boolean, now: number): PanelParts | null {
  const partner = q.partyId ? partnerName(q.party) : null;
  const led = q.leader ? undefined : `${shortName(partner ?? "Your partner")} leads`;
  const leave = { label: "Leave table", disabled: q.pending === "leave", onClick: () => queue.leave() };
  if (kind === "join" && q.offer) {
    const o = q.offer;
    const busy = q.pending !== null;
    const seats = offerSeats(o, busy);
    return {
      kicker: "Table with people", title: joinTitle(o), lines: joinLines(o, guest), seats, you: o.pick,
      hint: seats.some((s) => s.pick) ? "Tap a green seat to sit there" : undefined,
      primary: { label: q.pending === "offer" ? "Joining…" : joinLabel(o, now), disabled: busy,
                 onClick: () => queue.offerJoin() },
      secondary: { label: "Keep looking", disabled: busy, onClick: () => queue.offerWait() },
    };
  }
  if (kind === "own") {
    const duo = partner !== null;
    const timer = ownTimerLine(q, now);
    const lines = [{ text: duo ? "Two players or another Duo sit across." : "Anyone who presses Play can sit here." }];
    if (timer) lines.push({ text: timer });
    if (!duo && !q.waitPlayers) lines.push({ text: "Others can join as they arrive." });
    const n = q.openTables;
    const extra = (
      <>
        {n > 0 ? (
          <button type="button" className="tp-row" onClick={() => queue.offerShow()}>
            {n === 1 ? "1 table has a seat" : `${n} tables have a seat`} · <b>View</b>
          </button>
        ) : null}
        {q.leader ? <WaitSwitch q={q} /> : null}
      </>
    );
    return {
      kicker: duo ? "Your Duo's table" : "Your table", title: "Waiting for players", lines,
      seats: ownSeats(q), you: 0, extra, led,
      primary: { label: q.pending === "bots" ? "Starting…" : "Start with bots", disabled: q.pending !== null,
                 onClick: () => queue.startBots() },
      secondary: leave,
    };
  }
  if (kind === "shared" && q.table) {
    const t = q.table;
    const extra = !t.timer && q.leader ? (
      <button type="button" className="tp-row" disabled={q.pending !== null} onClick={() => queue.allowBots()}>
        Add bots in 1:00
      </button>
    ) : null;
    const move = canMove(q);
    const seats = sharedSeats(t, now, move, q.pending !== null);
    if (q.stillHereUntil !== null) {
      // a table with no timer asks before it drops a seat nobody is at
      return {
        kicker: "Table", title: sharedTitle(t),
        lines: [{ text: "Still here? Tap to stay at the table.", warn: true },
                { text: stillHereLine(q.stillHereUntil, now) }],
        seats, you: t.you,
        primary: { label: "I'm here", disabled: false, onClick: () => queue.here() },
        secondary: leave,
      };
    }
    return {
      kicker: "Table", title: sharedTitle(t),
      lines: [{ text: sharedTimerLine(t, now) }, { text: `${t.ready} of ${t.of} ready.` }],
      seats, you: t.you, extra, led,
      hint: move && seats.some((st) => st.pick) ? "Tap a green seat to move" : undefined,
      primary: { label: q.pending === "start" ? "Starting…" : startLabel(t),
                 disabled: t.youReady || q.pending !== null, onClick: () => queue.tableStart() },
      secondary: leave,
    };
  }
  if (kind === "elsewhere") {
    return {
      kicker: "Your table", title: "Your table is open on another device.", lines: [], seats: null, you: 0,
      primary: { label: "Move it here", disabled: q.pending !== null, onClick: () => queue.join() },
      secondary: q.leader ? leave : null,
    };
  }
  return null;
}

/** Enter presses the primary button while focus is on nothing else that
 *  takes it (a button, a field, an open sheet). Escape does nothing: the
 *  panel is part of the page, and leaving is only ever Leave table. */
function useEnterIsPrimary(primary: RefObject<HTMLButtonElement | null>, box: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Enter" || e.defaultPrevented || e.repeat) return;
      if (document.querySelector("[aria-modal='true']")) return;
      const at = document.activeElement;
      const free = !at || at === document.body || at === box.current
        || (box.current?.contains(at) && !at.matches("button, input, textarea, select, a, [role='switch']"));
      const btn = primary.current;
      if (!free || !btn || btn.disabled) return;
      e.preventDefault();
      btn.click();
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [primary, box]);
}

/** The table you are at, in Play's place: Join (a game in progress has a
 *  seat), your own table (alone, drawn by the app), or a shared table (two
 *  or three people waiting). Inline and non-modal on every screen. */
export default function TablePanel({ q, guarded }: { q: QueueView; guarded: boolean }) {
  const account = useAuth();
  const guest = account.status !== "in";
  const wide = useInlineQueue();
  const kind = panelKind(q);
  const now = useNow(kind !== "play" && kind !== "elsewhere", 250);
  const titleId = useId();
  const primaryRef = useRef<HTMLButtonElement | null>(null);
  const box = useRef<HTMLElement | null>(null);
  useEnterIsPrimary(primaryRef, box);
  const p = parts(q, kind, guest, now);
  if (!p) return null;
  return (
    <section ref={box} className={`tp tp-${kind}${wide ? " tp-wide" : ""}`} aria-labelledby={titleId}>
      <div className="tp-kicker">{p.kicker}</div>
      <h2 className="tp-title" id={titleId}>{p.title}</h2>
      {p.lines.length ? (
        <div className="tp-lines">
          {p.lines.map((l, i) => <p key={i} className={`tp-line${l.warn ? " warn" : ""}`}>{l.text}</p>)}
        </div>
      ) : null}
      {p.seats ? (wide ? <MiniTable seats={p.seats} you={p.you} /> : <TeamColumns seats={p.seats} you={p.you} />) : null}
      {p.hint ? <p className="tp-hint">{p.hint}</p> : null}
      {p.extra}
      {p.led ? <p className="tp-led">{p.led}</p> : (
        <div className="tp-acts">
          {p.primary ? (
            <button ref={primaryRef} type="button" className="tp-primary"
                    disabled={p.primary.disabled || guarded} onClick={p.primary.onClick}>
              {p.primary.label}
            </button>
          ) : null}
          {p.secondary ? (
            <button type="button" className="tp-secondary" disabled={p.secondary.disabled}
                    onClick={p.secondary.onClick}>
              {p.secondary.label}
            </button>
          ) : null}
        </div>
      )}
    </section>
  );
}

/** The one polite announcement per change of state, and one when ten
 *  seconds are left; the ticking clocks themselves are not read. */
export function TableAnnouncer({ q }: { q: QueueView }) {
  const guest = useAuth().status !== "in";
  const kind = panelKind(q);
  const now = useNow(kind === "join" || kind === "own" || kind === "shared", 500);
  const base = announcement(q, guest);
  let soon = "";
  if (kind === "join" && q.offer && q.offer.expiresAt - now <= OFFER_CLOCK_MS) soon = " 10 seconds left to join.";
  const botsAt = kind === "own" && !q.waitPlayers ? q.botsAt : kind === "shared" ? q.table?.timer?.at ?? null : null;
  if (botsAt !== null && botsAt - now <= BOTS_WARN_MS && botsAt > now) soon = " Bots fill the empty seats in 10 seconds.";
  return <div className="sr-only" role="status" aria-live="polite">{base ? base + soon : ""}</div>;
}
