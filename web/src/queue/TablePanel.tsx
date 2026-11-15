import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import { effectiveName, useAuth } from "../auth";
import ChatPanel from "../components/ChatPanel";
import { useGuestName } from "../guestName";
import { TimerRing } from "../components/MoveClock";
import LeaveSheet from "../components/LeaveSheet";
import { useAnyTapIsBack } from "../components/seatHeld";
import type { LeaveContext } from "../components/leaveCopy";
import { seatPos } from "../components/TrickArea";
import { codeLink } from "../codes";
import type { ChatMsg, Rank, RoomMsg, ServerMsg } from "../protocol";
import { RANKS } from "../protocol";
import { onRoomLeaveAsk } from "../roomBack";
import { conn } from "../ws";
import { useInlineQueue } from "./QueueBar";
import { BOTS_WARN_MS, BOT_FILL_MS, movedNote, partnerName, queue, tableDuo, useNow } from "./store";
import type { OfferView, QueueView, TableView } from "./store";
import {
  JUST_JOINED_MS, OFFER_CLOCK_MS, OFFER_SECS, START_NOW_SECS, announcement, duoStartLabel, joinLabel, joinTitle,
  moveQuestion, moveTargets, ownBotsAt, ownTitle,
  panelKind, roomReadyLine, roomTitle, roomWaitingLabel, sharedStatusLine, sharedTitle, shortName, startLabel,
  stillHereLine,
} from "./tableText";
import type { PanelKind } from "./tableText";
import "./tablePanel.css";

/** One seat as the panel draws it, on a phone's team columns or on the
 *  wide screens' mini table. The seats carry names and live status only;
 *  which seat is your partner's the layout already shows. */
export interface SeatItem {
  at: number;
  /** `held`: an empty seat kept for a Duo opener's friend. */
  look: "you" | "friend" | "person" | "open" | "held" | "bot";
  name: string;
  sub: string;
  /** Read by a screen reader: the full name and the seat's team. */
  label: string;
  tick?: boolean;
  /** An open seat you may take: tapping it picks it. */
  pick?: () => void;
  busy?: boolean;
  /** The person the opener tapped to move: the next empty seat tapped is
   *  where they go. */
  picked?: boolean;
}

const teamWord = (ours: boolean) => (ours ? "your team" : "other team");

/** The seats of the table an offer would sit you at, you in the picked seat. */
function offerSeats(o: OfferView, busy: boolean): SeatItem[] {
  return o.seats.map((s, at) => {
    const ours = (at - o.pick + 4) % 2 === 0;
    if (at === o.pick) return { at, look: "you", name: "You", sub: "", label: `You, ${teamWord(true)}` };
    if (o.partner && at === o.partner.seat) {
      return { at, look: "friend", name: shortName(o.partner.name), sub: "",
               label: `${o.partner.name}, your Duo partner` };
    }
    if (s.open && !o.partner) {
      // whose seat it was is the screen reader's only; the seat shows a name alone
      const away = s.bot ? "" : `, ${s.name} is away`;
      return { at, look: "open", name: "Open seat", sub: "", busy,
               label: `Open seat, ${teamWord(ours)}${away}. Sit here`, pick: () => queue.offerPick(at) };
    }
    if (s.bot || s.open) return { at, look: "bot", name: "Bot", sub: "", label: `Bot, ${teamWord(ours)}` };
    return { at, look: "person", name: shortName(s.name), sub: "", label: `${s.name}, playing, ${teamWord(ours)}` };
  });
}

/** The held seat: "Partner" across from you, the friend a Duo waits for. */
function heldSeat(at: number, ours: boolean): SeatItem {
  return { at, look: "held", name: "Partner", sub: "",
           label: ours ? "Partner seat, held for your friend" : `Partner seat, held, ${teamWord(false)}` };
}

/** Your own table, drawn from the lone queue entry: the server keeps no
 *  table for one, so you sit at the bottom and a Duo partner, or the seat
 *  held for one, across. In a Duo made there each member's Start shows. */
function ownSeats(q: QueueView): SeatItem[] {
  const partner = q.partyId ? partnerName(q.party) : null;
  const duo = tableDuo(q);
  const partnerReady = duo && (q.duoReady ?? 0) - (q.youReady ? 1 : 0) > 0;
  return [0, 1, 2, 3].map((at): SeatItem => {
    if (at === 0) {
      return { at, look: "you", name: "You", sub: "", tick: duo && q.youReady,
               label: duo && q.youReady ? "You, ready" : "You, your team" };
    }
    if (at === 2 && partner) {
      return { at, look: "friend", name: shortName(partner), sub: "", tick: partnerReady,
               label: [partner, partnerReady ? "ready" : null, "your Duo partner"].filter(Boolean).join(", ") };
    }
    if (at === 2 && q.heldSeat === 2) return heldSeat(at, true);
    const ours = at === 2;
    return { at, look: "open", name: "Open seat", sub: "", label: `Open seat, ${teamWord(ours)}` };
  });
}

/** Whether you may move seats: a single, before your Start, with someone
 *  else at the table. A Duo's seats stay together. */
function canMove(q: QueueView): boolean {
  const t = q.table;
  return !!t && !q.partyId && !t.youReady && t.of >= 2 && q.stillHereUntil === null;
}

/** The opener's move of someone else: the seat tapped (`picked`), a tap on
 *  a person to pick them, and a tap on a seat they may go to. */
interface OpenerMove {
  picked: number | null;
  pick: (at: number) => void;
  to: (at: number) => void;
}

/** A shared table's seats; with `move`, an empty seat is a button that
 *  moves you there; with `other`, the opener taps another person, then a
 *  seat for them. */
function sharedSeats(t: TableView, now: number, move: boolean, busy: boolean, other?: OpenerMove): SeatItem[] {
  const targets = other && other.picked !== null ? moveTargets(t.seats, t.heldSeats, other.picked) : null;
  return [0, 1, 2, 3].map((at): SeatItem => {
    const s = t.seats[at] ?? null;
    const ours = (at - t.you + 4) % 2 === 0;
    if (!s && t.heldSeats.includes(at)) return heldSeat(at, ours);
    if (!s && other && targets) {
      const name = t.seats[other.picked!]?.name ?? "";
      return targets.includes(at)
        ? { at, look: "open", name: "Open seat", sub: "", busy,
            label: `Open seat, ${teamWord(ours)}. Move ${name} here`, pick: () => other.to(at) }
        : { at, look: "open", name: "Open seat", sub: "", label: `Open seat, ${teamWord(ours)}` };
    }
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
    const partner = s.pair && ours;
    const item: SeatItem = {
      at, look: partner ? "friend" : "person", name: shortName(s.name), sub: status, tick: s.ready,
      label: [s.name, s.ready ? "ready" : null, status || null, partner ? "your Duo partner" : teamWord(ours)]
        .filter(Boolean).join(", "),
    };
    if (!other || partner) return item;
    const picked = other.picked === at;
    return { ...item, picked, busy, pick: () => other.pick(at),
             label: `${item.label}. ${picked ? "Moving; tap again to cancel" : "Move"}` };
  });
}

/** The initial of the name you play under: the account's, or a guest's own. */
function useMyInitial(): string {
  const account = useAuth();
  const guest = useGuestName();
  const name = account.status === "in" && account.user ? effectiveName(account.user) : guest.name.trim();
  return name.slice(0, 1).toUpperCase();
}

function SeatBody({ s }: { s: SeatItem }) {
  const mine = useMyInitial();
  const av = s.look === "open" ? "+" : s.look === "bot" || s.look === "held" ? "·"
    : s.look === "you" ? mine || "·" : s.name.slice(0, 2).toUpperCase();
  return (
    <>
      <span className="tp-av" aria-hidden="true">{av}</span>
      <span className="tp-seat-text" aria-hidden="true">
        <span className="tp-seat-name">{s.name}{s.tick ? <span className="tp-tick"> ✓</span> : null}</span>
        {s.sub ? <span className="tp-seat-sub">{s.sub}</span> : null}
      </span>
    </>
  );
}

function Seat({ s, team, cls = "" }: { s: SeatItem; team: 0 | 1; cls?: string }) {
  const className = `tp-seat ${s.look} team${team}${s.picked ? " picked" : ""}${cls}`;
  if (s.pick) {
    return (
      <button type="button" className={className} aria-label={s.label} aria-pressed={s.picked}
              disabled={s.busy} onClick={s.pick}>
        <SeatBody s={s} />
      </button>
    );
  }
  return <div className={className} role="group" aria-label={s.label}><SeatBody s={s} /></div>;
}

/** A phone's seats: your team on the left, partner above you, the other
 *  team on the right. */
export function TeamColumns({ seats, you }: { seats: SeatItem[]; you: number }) {
  const ours = [(you + 2) % 4, you].map((at) => seats[at]);
  const theirs = [(you + 1) % 4, (you + 3) % 4].map((at) => seats[at]);
  return (
    <div className="tp-teams">
      <span className="tp-team-label ours" aria-hidden="true">Us</span>
      <span aria-hidden="true" />
      <span className="tp-team-label theirs" aria-hidden="true">Them</span>
      <div className="tp-col">{ours.map((s) => <Seat key={s.at} s={s} team={0} />)}</div>
      <span className="tp-vs" aria-hidden="true">VS</span>
      <div className="tp-col">{theirs.map((s) => <Seat key={s.at} s={s} team={1} />)}</div>
    </div>
  );
}

/** Wide screens: the seats around a green table, you at the bottom. */
export function MiniTable({ seats, you }: { seats: SeatItem[]; you: number }) {
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

/** A panel is its title, its seats, at most one live status line and its
 *  buttons; explanations live in How to play and the coach. */
interface PanelParts {
  /** The mode tag above the title: "Casual" or "Offline"; a ranked table has none. */
  tag?: "Casual" | "Offline";
  title: string;
  status?: { text: string; warn?: boolean };
  seats: SeatItem[] | null;
  you: number;
  extra?: ReactNode;
  /** `waiting`: your Start is in, and a tap takes it back. */
  primary: {
    label: string; disabled: boolean; onClick: () => void; ring?: ReactNode; searching?: boolean; waiting?: boolean;
  } | null;
  secondary: { label: string; disabled: boolean; onClick: () => void } | null;
  /** A Duo's other member: who presses the buttons instead. */
  led?: string;
}

/** The bots' countdown as the ring on a table's primary button, while it
 *  runs: the panel's only timer. */
function botsRing(at: number | null, now: number): ReactNode {
  if (at === null || at - now <= 0) return null;
  return <TimerRing left={(at - now) / 1000} total={BOT_FILL_MS / 1000} />;
}

function parts(q: QueueView, kind: PanelKind, now: number, askLeave: () => void, other?: OpenerMove): PanelParts | null {
  const partner = q.partyId ? partnerName(q.party) : null;
  // a Duo made at a table has no leader to press for it: each member taps
  const led = q.leader || tableDuo(q) ? undefined : `${shortName(partner ?? "Your partner")} leads`;
  const leave = { label: "Leave", disabled: q.pending === "leave", onClick: askLeave };
  if (kind === "join" && q.offer) {
    const o = q.offer;
    const busy = q.pending !== null;
    const seats = offerSeats(o, busy);
    return {
      title: joinTitle(o), seats, you: o.pick,
      primary: { label: q.pending === "offer" ? "Joining…" : joinLabel(o), disabled: busy,
                 onClick: () => queue.offerJoin(),
                 ring: q.pending === "offer" ? null
                   : <TimerRing left={Math.max(0, o.expiresAt - now) / 1000} total={OFFER_SECS} /> },
      secondary: { label: "Keep looking", disabled: busy, onClick: () => queue.offerWait() },
    };
  }
  if (kind === "own") {
    const extra = (
      <>
        <QueueTableRows q={q} />
        {q.leader ? <WaitSwitch q={q} /> : null}
        <ChatRow messages={q.tableChat} you={q.leader ? 0 : 2} onSend={(text) => queue.tableChat(text)} />
      </>
    );
    const ring = botsRing(ownBotsAt(q), now);
    if (tableDuo(q) && partner) {
      // the pair's own table: both tap Start, then it searches as one
      return {
        title: ownTitle(q, partner), status: { text: `${q.duoReady ?? 0} of 2 ready` },
        seats: ownSeats(q), you: 0, extra,
        primary: { label: q.pending === "start" ? "Starting…" : duoStartLabel(q, partner),
                   disabled: q.pending !== null,
                   onClick: () => (q.youReady ? queue.tableUnready() : queue.tableStart()),
                   ring: q.pending === "start" ? null : ring,
                   searching: q.youReady && (q.duoReady ?? 0) >= 2, waiting: q.youReady },
        secondary: leave,
      };
    }
    return {
      title: ownTitle(q, partner),
      seats: ownSeats(q), you: 0, extra, led,
      primary: { label: q.pending === "bots" ? "Starting…" : "Start with bots", disabled: q.pending !== null,
                 onClick: () => queue.startBots(),
                 ring: q.pending === "bots" ? null : ring },
      secondary: leave,
    };
  }
  if (kind === "shared" && q.table) {
    const t = q.table;
    const extra = (
      <>
        <QueueTableRows q={q} />
        <ChatRow messages={q.tableChat} you={t.you} onSend={(text) => queue.tableChat(text)} />
      </>
    );
    const move = canMove(q);
    const seats = sharedSeats(t, now, move, q.pending !== null, q.opener && q.stillHereUntil === null ? other : undefined);
    if (q.stillHereUntil !== null) {
      // a table with no timer asks before it drops a seat nobody is at; the
      // same I’m back as a game's held seat, and any tap counts
      return {
        title: sharedTitle(t), status: { text: stillHereLine(q.stillHereUntil, now), warn: true },
        seats, you: t.you,
        primary: { label: "I’m back", disabled: false, onClick: () => queue.here() },
        secondary: leave,
      };
    }
    const ring = q.pending === "start" ? null : botsRing(t.timer?.at ?? null, now);
    // the opener's Start now, 30 s after the latest arrival, as in a room;
    // everyone else's button stays Start
    const startNow = q.opener && t.startNowAt !== null && now >= t.startNowAt;
    return {
      title: sharedTitle(t), status: { text: sharedStatusLine(t) },
      seats, you: t.you, extra, led,
      primary: startNow
        ? { label: q.pending === "start" ? "Starting…" : "Start now", disabled: q.pending !== null,
            onClick: () => queue.tableStartNow(), ring }
        : { label: q.pending === "start" ? "Starting…" : startLabel(t),
            disabled: q.pending !== null || (t.youReady && t.waitingFor.length === 0),
            onClick: () => (t.youReady ? queue.tableUnready() : queue.tableStart()), ring,
            waiting: t.youReady },
      secondary: leave,
    };
  }
  if (kind === "elsewhere") {
    return {
      title: "Your table is open on another device.", seats: null, you: 0,
      primary: { label: "I’m back", disabled: q.pending !== null, onClick: () => queue.join() },
      secondary: q.leader ? leave : null,
    };
  }
  return null;
}

/** Enter presses the primary button while focus is on nothing else that
 *  takes it (a button, a field, an open sheet). Escape does nothing: the
 *  panel is part of the page, and leaving is only ever Leave. */
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

/** The small mode tag above a panel's title, set in capitals by CSS. */
export function ModeTag({ tag }: { tag: "Casual" | "Offline" }) {
  return <p className="tp-tag">{tag}</p>;
}

/** The panel's frame, the same for every kind: the title, at most one
 *  status line, the seats (team columns on a phone, the mini table on wide
 *  screens), extra rows, the buttons, and the leave sheet when it is up. */
function PanelView({ p, kind, guarded, sheet }: { p: PanelParts; kind: string; guarded: boolean; sheet?: ReactNode }) {
  const wide = useInlineQueue();
  const titleId = useId();
  const primaryRef = useRef<HTMLButtonElement | null>(null);
  const box = useRef<HTMLElement | null>(null);
  useEnterIsPrimary(primaryRef, box);
  return (
    <section ref={box} className={`tp tp-${kind}${wide ? " tp-wide" : ""}`} aria-labelledby={titleId}>
      {p.tag ? <ModeTag tag={p.tag} /> : null}
      <h2 className="tp-title" id={titleId}>{p.title}</h2>
      {p.status ? <p className={`tp-line${p.status.warn ? " warn" : ""}`}>{p.status.text}</p> : null}
      {p.seats ? (wide ? <MiniTable seats={p.seats} you={p.you} /> : <TeamColumns seats={p.seats} you={p.you} />) : null}
      {p.extra}
      {p.led ? <p className="tp-led">{p.primary?.ring}{p.led}</p> : (
        <div className="tp-acts">
          {p.primary ? (
            <button ref={primaryRef} type="button"
                    className={`tp-primary${p.primary.searching ? " searching" : ""}${p.primary.waiting ? " waiting" : ""}`}
                    disabled={p.primary.disabled || guarded} onClick={p.primary.onClick}>
              {p.primary.ring}
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
      {sheet}
    </section>
  );
}

/** The table you are at, in Play's place: Join (a game in progress has a
 *  seat), your own table (alone, drawn by the app), or a shared table (two
 *  or three people waiting). Inline and non-modal on every screen. */
export default function TablePanel({ q, guarded }: { q: QueueView; guarded: boolean }) {
  const kind = panelKind(q);
  const now = useNow(kind !== "play" && kind !== "elsewhere", 250);
  const [asking, setAsking] = useState(false);
  // "still here?": any tap or key on the page answers it, as at a held seat
  useAnyTapIsBack(kind === "shared" && q.stillHereUntil !== null, () => queue.here());
  const seats = q.table?.seats ?? null;
  const mover = useOpenerMove(seats, (from, to, sit) => { if (sit) queue.tableMoveOther(from, to, sit); });
  const base = parts(q, kind, now, () => setAsking(true), mover.move);
  if (!base) return null;
  const casual = (q.queueMode ?? q.playMode) === "casual" && kind !== "elsewhere";
  const p: PanelParts = casual ? { ...base, tag: "Casual" } : base;
  // the people a shared table keeps when you go; your own table has nobody
  // else, but for a Duo partner, who keeps it
  const others = kind === "shared" && q.table
    ? q.table.seats.flatMap((s) => (s && !s.you ? [s.name] : [])) : [];
  const partner = tableDuo(q) ? partnerName(q.party) : null;
  const context: LeaveContext = partner ? { kind: "duo", partner, opener: q.opener } : { kind: "queue", others };
  const sheet = asking ? (
    <LeaveSheet context={context}
                onStay={() => setAsking(false)}
                onLeave={() => { setAsking(false); queue.leave(); }} />
  ) : mover.sheet;
  return <PanelView p={p} kind={kind} guarded={guarded} sheet={sheet} />;
}

/** The opener's move of someone else, for a table's seats (`name`, the
 *  sitting token `sit` where the server gives one, and a Duo's `pair` per
 *  seat, null for empty): the person tapped, then the seat, then one
 *  confirm, which `send`s it with the sitting picked. A picked seat that
 *  empties or changes hands drops the pick and its confirm. */
function useOpenerMove(seats: ({ name: string; sit?: string | null; pair?: boolean } | null)[] | null,
                       send: (from: number, to: number, sit: string | null) => void) {
  const [picked, setPicked] = useState<{ at: number; name: string; sit: string | null } | null>(null);
  const [ask, setAsk] = useState<{ from: number; to: number; names: string[]; sit: string | null } | null>(null);
  const now = picked !== null ? seats?.[picked.at] : null;
  const still = !!now && now.name === picked!.name && (now.sit ?? null) === picked!.sit;
  useEffect(() => { if (picked && !still) { setPicked(null); setAsk(null); } }, [picked, still]);
  const move: OpenerMove = {
    picked: still ? picked!.at : null,
    pick: (at) => setPicked((was) => (was?.at === at || !seats?.[at] ? null
                                      : { at, name: seats[at]!.name, sit: seats[at]!.sit ?? null })),
    to: (to) => {
      if (!picked || !seats) return;
      const s = seats[picked.at];
      const mate = s?.pair ? seats[(picked.at + 2) % 4] : null;
      setAsk({ from: picked.at, to, names: [picked.name, ...(mate ? [mate.name] : [])], sit: picked.sit });
    },
  };
  const sheet = ask ? (
    <MoveConfirm names={ask.names}
                 onMove={() => { send(ask.from, ask.to, ask.sit); setAsk(null); setPicked(null); }}
                 onCancel={() => setAsk(null)} />
  ) : null;
  return { move, sheet };
}

/** The one confirm before the opener moves someone: "Move Alice here?",
 *  then Cancel and Move. A modal dialog; Cancel is focused first and
 *  Escape cancels. */
function MoveConfirm({ names, onMove, onCancel }: { names: string[]; onMove: () => void; onCancel: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current!;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    cancelRef.current?.focus();
    return () => {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    };
  }, []);
  return (
    <dialog ref={ref} className="modal-backdrop leave-sheet-backdrop leave-sheet-bottom" role="alertdialog"
            aria-modal="true" aria-labelledby={titleId}
            onCancel={(e) => { e.preventDefault(); onCancel(); }}
            onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (e.key === "Escape") { e.preventDefault(); onCancel(); }
            }}>
      <div className="leave-sheet">
        <div className="leave-sheet-text">
          <h2 id={titleId} className="leave-sheet-title">{moveQuestion(names)}</h2>
        </div>
        <div className="leave-sheet-actions">
          <button ref={cancelRef} type="button" className="leave-sheet-stay" onClick={onCancel}>Cancel</button>
          <button type="button" className="leave-sheet-leave tp-move-confirm" onClick={onMove}>Move</button>
        </div>
      </div>
    </dialog>
  );
}

/** The chat log of the room this socket sits in, as the connection keeps
 *  it: the lines from before the panel mounted are already there. */
function useRoomChat(): ChatMsg[] {
  const [chat, setChat] = useState<ChatMsg[]>(() => conn.chatHistory());
  useEffect(() => conn.subscribe((msg: ServerMsg) => {
    if (msg.type === "chat" || msg.type === "chat_history") setChat(conn.chatHistory());
  }), []);
  return chat;
}

/** The table's chat row: the last line and an unread count, and a tap
 *  opens the chat sheet. The same log carries into the game, because the
 *  server turns it into the room's scrollback. */
export function ChatRow({ messages, you, onSend }: {
  messages: ChatMsg[]; you: number; onSend: (text: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState(() => messages[messages.length - 1]?.id ?? -1);
  const lastId = messages[messages.length - 1]?.id ?? -1;
  useEffect(() => { if (open) setSeen(lastId); }, [open, lastId]);
  const unread = messages.filter((m) => m.id > seen && m.seat !== you && m.seat !== -1).length;
  const last = [...messages].reverse().find((m) => m.seat !== -1);
  return (
    <>
      <button type="button" className="tp-chat" aria-expanded={open} onClick={() => setOpen((o) => !o)}
              aria-label={unread ? `Chat, ${unread} new` : "Chat"}>
        <span className="tp-chat-label" aria-hidden="true">Chat</span>
        <span className="tp-chat-last" aria-hidden="true">{last ? `${shortName(last.name)}: ${last.text}` : ""}</span>
        {unread ? <span className="tp-chat-badge" aria-hidden="true">{unread}</span> : null}
      </button>
      <ChatPanel messages={messages} you={you} open={open} onClose={() => setOpen(false)} onSend={onSend} />
    </>
  );
}

/** A table's invite: the system share sheet where there is one, else the
 *  link on the clipboard. Resolves true when the link was copied. */
function shareInvite(code: string): Promise<boolean> {
  const url = codeLink(code);
  if (typeof navigator.share === "function") {
    return navigator.share({ title: "Sheng Ji", text: `Join my table · ${code}`, url })
      .then(() => false, () => false);   // a dismissed share sheet is not an error
  }
  if (!navigator.clipboard) return Promise.resolve(false);
  return navigator.clipboard.writeText(url).then(() => true, () => false);
}

/** The code with its Invite link: the share sheet, or a copy. */
function CodeRow({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const invite = () => {
    void shareInvite(code).then((didCopy) => {
      if (!didCopy) return;
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    });
  };
  return (
    <div className="tp-code-row">
      <span className="tp-code" aria-label={`Table code ${code.split("").join(" ")}`}>{code}</span>
      <button type="button" className="tp-invite" onClick={invite}>{copied ? "Link copied" : "Invite link"}</button>
    </div>
  );
}

/** A labelled switch row, label only. */
function SwitchRow({ label, on, onToggle }: { label: string; on: boolean; onToggle: () => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} className="q-wait tp-switch" onClick={onToggle}>
      <span className="q-wait-label">{label}</span>
      <span className="q-switch" aria-hidden="true" />
    </button>
  );
}

/** Every table's settings rows, labels only: the code with its Invite link,
 *  Starting level on a casual table (the opener picks it, others read it; a
 *  ranked table starts at 2 and has no row), and Allow joiners when
 *  ``joiners`` is set (the opener's switch; others see no row). */
function TableRows({ code, ranked, opener, level, onLevel, joiners, onJoiners }: {
  code: string | null; ranked: boolean; opener: boolean; level: string;
  onLevel: (level: Rank) => void; joiners: boolean | undefined; onJoiners: (on: boolean) => void;
}) {
  return (
    <>
      {code ? <CodeRow code={code} /> : null}
      {ranked ? null : opener ? (
        <label className="tp-set">
          <span>Starting level</span>
          <select aria-label="Starting level" value={level} onChange={(e) => onLevel(e.target.value as Rank)}>
            {RANKS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
      ) : (
        <div className="tp-set" role="group" aria-label={`Starting level ${level}`}>
          <span aria-hidden="true">Starting level</span>
          <span className="tp-set-val" aria-hidden="true">{level}</span>
        </div>
      )}
      {joiners !== undefined ? (
        <SwitchRow label="Allow joiners" on={joiners} onToggle={() => onJoiners(!joiners)} />
      ) : null}
    </>
  );
}

/** A Play table's settings rows, from the queue's state. Allow joiners is
 *  the table opener's switch (``queue_state.opener``: its leader's), so
 *  nobody else is shown one. */
function QueueTableRows({ q }: { q: QueueView }) {
  return (
    <TableRows code={q.tableCode} ranked={(q.queueMode ?? q.playMode) === "ranked"} opener={q.opener}
               level={q.startLevel} onLevel={(l) => queue.setStartLevel(l)}
               joiners={q.opener ? q.allowJoiners : undefined} onJoiners={(on) => queue.setAllowJoiners(on)} />
  );
}

/** A room's seats from its frame. Before your Start an empty seat is a
 *  button that moves you there; the server refuses it once you tapped.
 *  With `other`, the opener taps another person, then an empty seat. */
function roomSeats(room: RoomMsg, ready: Set<number>, move: boolean, other?: OpenerMove,
                   onOwnMove?: () => void): SeatItem[] {
  const me = room.players.find((pl) => pl.seat === room.you);
  const picked = other?.picked ?? null;
  return [0, 1, 2, 3].map((at): SeatItem => {
    const pl = room.players.find((x) => x.seat === at);
    const ours = (at - room.you + 4) % 2 === 0;
    if (!pl && other && picked !== null) {
      const name = room.players.find((x) => x.seat === picked)?.name ?? "";
      return { at, look: "open", name: "Open seat", sub: "",
               label: `Open seat, ${teamWord(ours)}. Move ${name} here`, pick: () => other.to(at) };
    }
    if (!pl) {
      if (move && me) {
        return { at, look: "open", name: "Open seat", sub: "",
                 label: `Open seat, ${teamWord(ours)}. Move here`,
                 pick: () => {
                   onOwnMove?.();
                   conn.send({ type: "table_move", seat: at,
                               expect: [{ name: me.name, is_bot: me.is_bot }, null] });
                 } };
      }
      return { at, look: "open", name: "Open seat", sub: "", label: `Open seat, ${teamWord(ours)}` };
    }
    const tick = ready.has(at);
    if (at === room.you) {
      return { at, look: "you", name: "You", sub: "", tick, label: ["You", tick ? "ready" : null].filter(Boolean).join(", ") };
    }
    if (pl.is_bot) return { at, look: "bot", name: shortName(pl.name), sub: "", label: `${pl.name}, bot, ${teamWord(ours)}` };
    const sub = pl.connected ? "" : "Reconnecting";
    const item: SeatItem = { at, look: "person", name: shortName(pl.name), sub, tick,
                             label: [pl.name, tick ? "ready" : null, sub || null, teamWord(ours)].filter(Boolean).join(", ") };
    if (!other) return item;
    return { ...item, picked: picked === at, pick: () => other.pick(at),
             label: `${item.label}. ${picked === at ? "Moving; tap again to cancel" : "Move"}` };
  });
}

/** The queue's notice (the one toast) when the opener moved you in a
 *  room: the frame's `you` changed with no move of your own in flight. */
function useMovedByOpener(room: RoomMsg, ownMove: RefObject<boolean>) {
  const was = useRef(room.you);
  useEffect(() => {
    if (room.you === was.current) return;
    const before = was.current;
    was.current = room.you;
    if (ownMove.current) {
      ownMove.current = false;
      return;
    }
    const by = room.players.find((pl) => pl.seat === (room.opener ?? room.host))?.name;
    if (!by) return;
    queue.notify(movedNote({ type: "table_moved", name: "", seat: room.you, your_team: true, by: shortName(by),
                             you: true, team_changed: before % 2 !== room.you % 2 }));
  }, [room, ownMove]);
}

/** The people who stay when you leave the room, in seat order: the first
 *  of them takes the opener's controls, as the server hands them on. */
function staying(room: RoomMsg): string[] {
  return room.players.filter((p) => !p.is_bot && p.seat !== room.you)
    .sort((a, b) => a.seat - b.seat).map((p) => p.name);
}

/** A room before its game, as a kind of the same panel: the table's rows,
 *  the chat row, the seats, and Start for everyone. Once others sit, the
 *  opener also gets Start now when `start_now_in` runs out. Leave, and the
 *  back gesture, ask through the leave sheet. */
export function RoomPanel({ room }: { room: RoomMsg }) {
  const opener = (room.opener ?? room.host) === room.you;
  const ranked = !!(room.matched || room.ranked);
  const ready = new Set(room.ready ?? []);
  const youReady = ready.has(room.you);
  const others = room.players.filter((pl) => !pl.is_bot && pl.seat !== room.you);
  const [asking, setAsking] = useState(false);
  useEffect(() => onRoomLeaveAsk(() => setAsking(true)), []);
  // The frame's countdown, as a local deadline: each frame restarts it.
  const startNowAt = useMemo(
    () => (room.start_now_in !== undefined ? Date.now() + room.start_now_in * 1000 : null), [room]);
  const counting = opener && others.length > 0 && startNowAt !== null;
  const now = useNow(counting, 250);
  const chat = useRoomChat();
  const left = counting ? Math.max(0, startNowAt! - now) : null;
  const ownMove = useRef(false);
  useMovedByOpener(room, ownMove);
  const roomPeople = [0, 1, 2, 3].map((at) => {
    const pl = room.players.find((x) => x.seat === at && !x.is_bot && at !== room.you);
    return pl ? { name: pl.name } : room.players.some((x) => x.seat === at) ? { name: "" } : null;
  });
  const mover = useOpenerMove(roomPeople, (from, to) => {
    const pl = room.players.find((x) => x.seat === from);
    if (!pl) return;
    conn.send({ type: "table_move", seat: to, from, expect: [{ name: pl.name, is_bot: pl.is_bot }, null] });
  });

  let primary: PanelParts["primary"];
  if (left !== null && left <= 0) {
    primary = { label: "Start now", disabled: false, onClick: () => conn.send({ type: "table_start_now" }) };
  } else if (!youReady) {
    primary = { label: others.length ? "Start" : "Start with bots", disabled: false,
                onClick: () => conn.send({ type: "table_start", on: true }) };
  } else if (left !== null) {
    primary = { label: "Start now", disabled: true, onClick: () => {},
                ring: <TimerRing left={left / 1000} total={START_NOW_SECS} /> };
  } else {
    const label = roomWaitingLabel(room);
    primary = { label, disabled: label === "Starting…", waiting: true,
                onClick: () => conn.send({ type: "table_start", on: false }) };
  }
  const readyLine = roomReadyLine(room);
  const extra = (
    <>
      <TableRows code={room.room} ranked={ranked} opener={opener} level={room.start_level}
                 onLevel={(l) => conn.send({ type: "table_start_level", start_level: l })}
                 joiners={room.allow_joiners} onJoiners={(on) => conn.send({ type: "table_allow_joiners", on })} />
      <ChatRow messages={chat} you={room.you} onSend={(text) => conn.send({ type: "table_chat", text })} />
    </>
  );
  const p: PanelParts = {
    tag: ranked ? undefined : "Casual",
    title: roomTitle(room),
    status: readyLine ? { text: readyLine } : undefined,
    seats: roomSeats(room, ready, !youReady, opener ? mover.move : undefined, () => { ownMove.current = true; }),
    you: room.you,
    extra,
    primary,
    secondary: { label: "Leave", disabled: false, onClick: () => setAsking(true) },
  };
  const sheet = asking ? (
    <LeaveSheet context={{ kind: "room", others: staying(room), host: opener }}
                onStay={() => setAsking(false)}
                onLeave={() => { conn.send({ type: "table_leave" }); setAsking(false); }} />
  ) : mover.sheet;
  return <PanelView p={p} kind="room" guarded={false} sheet={sheet} />;
}

/** The one polite announcement per change of state, and one when ten
 *  seconds are left; the ticking clocks themselves are not read. */
export function TableAnnouncer({ q }: { q: QueueView }) {
  const kind = panelKind(q);
  const now = useNow(kind === "join" || kind === "own" || kind === "shared", 500);
  const base = announcement(q);
  let soon = "";
  if (kind === "join" && q.offer && q.offer.expiresAt - now <= OFFER_CLOCK_MS) soon = " 10 seconds left to join.";
  const botsAt = kind === "own" && !q.waitPlayers ? q.botsAt : kind === "shared" ? q.table?.timer?.at ?? null : null;
  if (botsAt !== null && botsAt - now <= BOTS_WARN_MS && botsAt > now) soon = " Bots fill the empty seats in 10 seconds.";
  return <div className="sr-only" role="status" aria-live="polite">{base ? base + soon : ""}</div>;
}
