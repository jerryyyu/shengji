// The table panel's one model, from the queue's table (`fromQueue`), a
// code's peek (`fromCode`) or the offline table (`offlineModel`). The panel draws only the model and answers only
// `PanelAction`s; the queue's dispatcher turns a `TableAction` into its
// frame, with the table's sitting token added there.
import type { CodeJoin } from "../codeJoin";
import type { LeaveContext } from "../components/leaveCopy";
import { hostName, roomChoices, tableHostName, takeoverSeats } from "../joinSeats";
import type { ChatMsg, Rank, RoomSeats, TableSeats } from "../protocol";
import { BOT_FILL_MS, isOpener, namesAt, partnerName, queue, tableDuo, yourReady } from "./store";
import type { OfferView, QueueView, TableFrame } from "./store";
import type { BotLevel } from "./messages";
import {
  JUST_JOINED_MS, OFFER_SECS, duoStartLabel, joinTitle, moveTargets, ownBotsAt, ownTitle, panelKind,
  sharedStatusLine, sharedTitle, shortName, startLabel, stillHereLine,
} from "./tableText";
import type { PanelKind } from "./tableText";

/** One seat as the panel draws it in its team columns. The seats carry names and live status only;
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

/** Everything a table does. */
export type TableAction =
  | { type: "start" }
  | { type: "unready" }
  | { type: "start_now" }
  | { type: "start_bots" }
  | { type: "move"; seat: number }
  | { type: "move_other"; from: number; to: number; sit: string | null }
  | { type: "leave" }
  | { type: "chat"; text: string }
  | { type: "start_level"; level: Rank }
  | { type: "allow_joiners"; on: boolean }
  | { type: "bot_level"; level: BotLevel }
  | { type: "wait_players"; on: boolean }
  | { type: "here" }
  | { type: "reclaim" }
  | { type: "offer_join" }
  | { type: "offer_wait" }
  | { type: "offer_pick"; seat: number };

/** What a code's Join panel does: choose the seat Join takes, Join, Not now. */
export type CodeAction =
  | { type: "code_pick"; seat: number }
  | { type: "code_join" }
  | { type: "code_cancel" };

/** What the offline table does: Start deals at once; Leave puts Play back. */
export type OfflineAction = { type: "offline_start" } | { type: "offline_leave" };

/** What the panel answers itself: the leave sheet, and the opener's tap on
 *  a person and then on the seat they go to (one confirm sends the move);
 *  and a code's Join panel's actions. */
export type PanelAction =
  | TableAction
  | CodeAction
  | OfflineAction
  | { type: "ask_leave" }
  | { type: "pick_person"; at: number }
  | { type: "move_to"; at: number };

/** A seat in the model: a tap is an action, not a callback. */
export type ModelSeat = Omit<SeatItem, "pick"> & { act?: PanelAction };

/** A countdown drawn as the ring on a button. */
export interface Ring { left: number; total: number }

export interface TableButton {
  label: string;
  disabled: boolean;
  act?: PanelAction;
  ring?: Ring | null;
  searching?: boolean;
  /** Your Start is in, and a tap takes it back. */
  waiting?: boolean;
  /** Drawn as `aria-busy`: the press is on its way. */
  busy?: boolean;
}

/** The settings rows: the code with its Invite link, Starting level and
 *  Bots (when `bots` is set) on a casual table (the opener picks them,
 *  others read them), and Allow joiners when `joiners` is set. */
export interface TableRows {
  code: string | null;
  ranked: boolean;
  opener: boolean;
  level: string;
  joiners: boolean | undefined;
  bots: BotLevel | undefined;
}

/** The seats the opener's move reads: a name per seat (blank for one that
 *  cannot be moved), the sitting token where the server gives one, a Duo's
 *  `pair`; null for empty. */
export type MoverSeat = { name: string; sit?: string | null; pair?: boolean } | null;

/** A panel is its title, its seats, at most one live status line, its rows
 *  and its buttons; explanations live in How to play and the coach. */
export interface TableModel {
  /** Drawn as the class `tp-${kind}`. */
  kind: Exclude<PanelKind, "play"> | "join-code" | "offline";
  /** The mode tag above the title; a ranked table has none. */
  tag?: "Casual" | "Offline";
  title: string;
  status?: { text: string; warn?: boolean };
  seats: ModelSeat[] | null;
  you: number;
  rows: TableRows | null;
  /** The leader's Wait for people on your own table. */
  waitSwitch: { on: boolean; disabled: boolean } | null;
  /** The table's chat row; `disabled` draws it greyed, for a table with
   *  no server to chat through. */
  chat: { messages: ChatMsg[]; you: number } | { disabled: true } | null;
  primary: TableButton | null;
  secondary: TableButton | null;
  /** A Duo's other member: who presses the buttons instead. */
  led?: string;
  leave: LeaveContext;
}

/** The panel's own state the model reads: the clock, and the person the
 *  opener tapped to move (null for none). */
export interface PanelState { now: number; picked: number | null }

const teamWord = (ours: boolean) => (ours ? "your team" : "other team");

/** The seats of the table an offer would sit you at, you in the picked seat. */
function offerSeats(o: OfferView, busy: boolean): ModelSeat[] {
  return o.seats.map((s, at): ModelSeat => {
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
               label: `Open seat, ${teamWord(ours)}${away}. Sit here`, act: { type: "offer_pick", seat: at } };
    }
    if (s.bot || s.open) return { at, look: "bot", name: "Bot", sub: "", label: `Bot, ${teamWord(ours)}` };
    return { at, look: "person", name: shortName(s.name), sub: "", label: `${s.name}, playing, ${teamWord(ours)}` };
  });
}

/** The held seat: "Partner" across from you, the friend a Duo waits for. */
function heldSeat(at: number, ours: boolean): ModelSeat {
  return { at, look: "held", name: "Partner", sub: "",
           label: ours ? "Partner seat, held for your friend" : `Partner seat, held, ${teamWord(false)}` };
}

/** Whether you may move seats: a single, before your Start, with someone
 *  else at the table. A Duo's seats stay together. */
function canMove(q: QueueView, f: TableFrame): boolean {
  return !q.partyId && !f.your_ready && f.seats.filter((s) => s.state === "taken").length >= 2
    && q.stillHereUntil === null;
}

/** The seats of your table, from its frame. `alone`: your own table, where
 *  nobody else's status shows and your seat names your team. With `move`,
 *  an empty seat moves you there; with `opener`, the opener taps another
 *  person, then a seat for them (`picked`: the person tapped). */
function frameSeats(f: TableFrame, now: number, { alone = false, move = false, busy = false, opener = false,
                                                   picked = null }: {
  alone?: boolean; move?: boolean; busy?: boolean; opener?: boolean; picked?: number | null;
} = {}): ModelSeat[] {
  const held = f.seats.filter((s) => s.state === "held").map((s) => s.seat);
  const people = f.seats.map((s) => (s.state === "taken" ? s : null));
  const targets = opener && picked !== null ? moveTargets(people, held, picked) : null;
  return [0, 1, 2, 3].map((at): ModelSeat => {
    const s = people[at] ?? null;
    const ours = (at - f.you + 4) % 2 === 0;
    if (!s && held.includes(at)) return heldSeat(at, ours);
    if (!s && targets) {
      const name = people[picked!]?.name ?? "";
      return targets.includes(at)
        ? { at, look: "open", name: "Open seat", sub: "", busy,
            label: `Open seat, ${teamWord(ours)}. Move ${name} here`, act: { type: "move_to", at } }
        : { at, look: "open", name: "Open seat", sub: "", label: `Open seat, ${teamWord(ours)}` };
    }
    if (!s && move) {
      return { at, look: "open", name: "Open seat", sub: "", busy,
               label: `Open seat, ${teamWord(ours)}. Move here`, act: { type: "move", seat: at } };
    }
    if (!s) return { at, look: "open", name: "Open seat", sub: "", label: `Open seat, ${teamWord(ours)}` };
    const name = s.name ?? "";
    const ready = s.ready === true;
    const status = alone ? ""
      : s.reconnecting ? "Reconnecting"
      : !s.you && !ready && s.since !== null && now - s.since < JUST_JOINED_MS ? "Just joined"
      : "";
    if (s.you) {
      return { at, look: "you", name: "You", sub: status, tick: ready,
               label: alone && !ready ? "You, your team"
                 : ["You", ready ? "ready" : null, status || null].filter(Boolean).join(", ") };
    }
    const partner = s.pair && ours;
    const item: ModelSeat = {
      at, look: partner ? "friend" : "person", name: shortName(name), sub: status, tick: ready,
      label: [name, ready ? "ready" : null, status || null, partner ? "your Duo partner" : teamWord(ours)]
        .filter(Boolean).join(", "),
    };
    if (!opener || partner) return item;
    const on = picked === at;
    return { ...item, picked: on, busy, act: { type: "pick_person", at },
             label: `${item.label}. ${on ? "Moving; tap again to cancel" : "Move"}` };
  });
}

/** The bots' countdown as the ring on a table's primary button, while it
 *  runs: the panel's only timer. */
function botsRing(at: number | null, now: number): Ring | null {
  if (at === null || at - now <= 0) return null;
  return { left: (at - now) / 1000, total: BOT_FILL_MS / 1000 };
}

/** What leaving the Play table costs, for every sheet that asks: the
 *  panel's Leave and a link to another table. The people a shared table
 *  keeps when you go; your own table has nobody else, but for a Duo
 *  partner, who keeps it. */
export function queueLeaveContext(q: QueueView): LeaveContext {
  const others = panelKind(q) === "shared" ? namesAt(q.frame) : [];
  const duoPartner = tableDuo(q) ? partnerName(q.party) : null;
  return duoPartner ? { kind: "duo", partner: duoPartner, opener: isOpener(q) } : { kind: "queue", others };
}

/** The queue's table, by the kind its state calls for; null on Play. */
export function fromQueue(q: QueueView, { now, picked }: PanelState): TableModel | null {
  const kind = panelKind(q);
  const partner = q.partyId ? partnerName(q.party) : null;
  // a Duo made at a table has no leader to press for it: each member taps
  const led = q.leader || tableDuo(q) ? undefined : `${shortName(partner ?? "Your partner")} leads`;
  const leaveBtn: TableButton = { label: "Leave", disabled: q.pending === "leave", act: { type: "ask_leave" } };
  const ranked = (q.queueMode ?? q.playMode) === "ranked";
  const tag = (q.queueMode ?? q.playMode) === "casual" && kind !== "elsewhere" ? "Casual" as const : undefined;
  const f = q.frame;
  const opener = isOpener(q);
  const rows: TableRows = { code: f?.code ?? null, ranked, opener, level: f?.settings.start_level ?? "2",
                            joiners: opener ? f?.settings.allow_joiners !== false : undefined,
                            bots: ranked ? undefined : f?.settings.bot_level };
  const leave = queueLeaveContext(q);
  const base = { tag, leave, rows: null, waitSwitch: null, chat: null };
  if (kind === "join" && q.offer) {
    const o = q.offer;
    const busy = q.pending !== null;
    return {
      ...base, kind, title: joinTitle(o), seats: offerSeats(o, busy), you: o.pick,
      primary: { label: q.pending === "offer" ? "Joining…" : "Join", disabled: busy, act: { type: "offer_join" },
                 ring: q.pending === "offer" ? null : { left: Math.max(0, o.expiresAt - now) / 1000, total: OFFER_SECS } },
      secondary: { label: "Keep looking", disabled: busy, act: { type: "offer_wait" } },
    };
  }
  if (kind === "own" && f) {
    const extra = {
      rows,
      waitSwitch: q.leader ? { on: q.waitPlayers, disabled: q.pending !== null } : null,
      chat: { messages: q.tableChat, you: f.you },
    };
    const seats = frameSeats(f, now, { alone: true });
    const youReady = yourReady(q);
    const ring = botsRing(ownBotsAt(q), now);
    if (tableDuo(q) && partner) {
      // the pair's own table: both tap Start, then it searches as one
      return {
        ...base, ...extra, kind,
        title: ownTitle(q, partner), status: { text: `${q.duoReady ?? 0} of 2 ready` },
        seats, you: f.you,
        primary: { label: q.pending === "start" ? "Starting…" : duoStartLabel(q, partner),
                   disabled: q.pending !== null,
                   act: youReady ? { type: "unready" } : { type: "start" },
                   ring: q.pending === "start" ? null : ring,
                   searching: youReady && (q.duoReady ?? 0) >= 2, waiting: youReady },
        secondary: leaveBtn,
      };
    }
    return {
      ...base, ...extra, kind,
      title: ownTitle(q, partner), seats, you: f.you, led,
      primary: { label: q.pending === "bots" ? "Starting…" : "Start with bots", disabled: q.pending !== null,
                 act: { type: "start_bots" }, ring: q.pending === "bots" ? null : ring },
      secondary: leaveBtn,
    };
  }
  if (kind === "shared" && f) {
    const seats = frameSeats(f, now, { move: canMove(q, f), busy: q.pending !== null,
                                       opener: opener && q.stillHereUntil === null, picked });
    if (q.stillHereUntil !== null) {
      // a table with no timer asks before it drops a seat nobody is at; the
      // same I’m back as a game's held seat, and any tap counts
      return {
        ...base, kind,
        title: sharedTitle(f), status: { text: stillHereLine(q.stillHereUntil, now), warn: true },
        seats, you: f.you,
        primary: { label: "I’m back", disabled: false, act: { type: "here" } },
        secondary: leaveBtn,
      };
    }
    const ring = q.pending === "start" ? null : botsRing(f.timers.bots?.at ?? null, now);
    // the opener's Start now, 30 s after the latest arrival; everyone
    // else's button stays Start
    const startAt = f.timers.start_now_at;
    const startNow = opener && startAt !== null && now >= startAt;
    const youReady = f.your_ready === true;
    return {
      ...base, kind, rows, chat: { messages: q.tableChat, you: f.you },
      title: sharedTitle(f), status: { text: sharedStatusLine(f) },
      seats, you: f.you, led,
      primary: startNow
        ? { label: q.pending === "start" ? "Starting…" : "Start now", disabled: q.pending !== null,
            act: { type: "start_now" }, ring }
        : { label: q.pending === "start" ? "Starting…" : startLabel(f),
            disabled: q.pending !== null || (youReady && (f.waiting_for ?? []).length === 0),
            act: youReady ? { type: "unready" } : { type: "start" }, ring, waiting: youReady },
      secondary: leaveBtn,
    };
  }
  if (kind === "elsewhere") {
    return {
      ...base, kind,
      title: "Your table is open on another device.", seats: null, you: 0,
      primary: { label: "I’m back", disabled: q.pending !== null, act: { type: "reclaim" } },
      secondary: q.leader ? leaveBtn : null,
    };
  }
  return null;
}

/** A room's four seats as the panel draws them: you, glowing, in the seat
 *  Join takes; every other seat Join may take is a button that moves you
 *  there. A dropped player's seat is drawn as "Name (away)", glowing too
 *  when it is the one chosen. */
function roomSeats(peek: RoomSeats, you: number | null, busy: boolean): ModelSeat[] {
  const away = new Set(takeoverSeats(peek).map((d) => d.seat));
  const choices = new Set(roomChoices(peek));
  const from = you ?? 0;
  return [0, 1, 2, 3].map((at): ModelSeat => {
    const sd = peek.seats.find((s) => s.seat === at);
    const ours = (at - from + 4) % 2 === 0;
    const move = choices.has(at) ? { act: { type: "code_pick", seat: at } as const, busy } : {};
    if (sd && away.has(at)) {
      // a dropped player's seat keeps their name, glowing when chosen: Join asks first
      return at === you
        ? { at, look: "open", picked: true, name: `${shortName(sd.name)} (away)`, sub: "",
            label: `${sd.name} is away, ${teamWord(true)}. Your seat` }
        : { at, look: "open", name: `${shortName(sd.name)} (away)`, sub: "",
            label: `${sd.name} is away, ${teamWord(ours)}. Sit here`, ...move };
    }
    if (at === you) return { at, look: "you", picked: true, name: "You", sub: "", label: `You, ${teamWord(true)}` };
    if (!sd) return { at, look: "open", name: "Open seat", sub: "", label: `Open seat, ${teamWord(ours)}`, ...move };
    if (sd.is_bot) {
      return { at, look: "bot", name: "Bot", sub: "",
               label: `Bot, ${teamWord(ours)}${choices.has(at) ? ". Sit here" : ""}`, ...move };
    }
    return { at, look: "person", name: shortName(sd.name), sub: "", label: `${sd.name}, ${teamWord(ours)}` };
  });
}

/** A queued table's four seats as they stand: who sits there (with their
 *  Start), the open seats and a Duo's held partner seat, and you, glowing,
 *  where a code join sits you (the server seats it by its own rule, so no
 *  other seat is offered). */
function queuedSeats(peek: TableSeats, you: number | null): ModelSeat[] {
  const from = you ?? 0;
  return [0, 1, 2, 3].map((at): ModelSeat => {
    const sd = peek.seats.find((s) => s.seat === at);
    const ours = (at - from + 4) % 2 === 0;
    if (at === you) return { at, look: "you", picked: true, name: "You", sub: "", label: `You, ${teamWord(true)}` };
    if (sd?.state === "held") return { at, look: "held", name: "Partner", sub: "", label: `Partner seat, held, ${teamWord(ours)}` };
    if (sd?.state !== "taken" || !sd.name) return { at, look: "open", name: "Open seat", sub: "", label: `Open seat, ${teamWord(ours)}` };
    return { at, look: "person", name: shortName(sd.name), sub: "", tick: sd.ready,
             label: [sd.name, sd.ready ? "ready" : null, teamWord(ours)].filter(Boolean).join(", ") };
  });
}

/** A code's Join panel, in Play's place: the table's seats with you glowing
 *  in the seat Join takes, then Join and Not now. A full table shows the
 *  same panel with Join disabled; before the peek answers, the code alone. */
export function fromCode(j: CodeJoin, busy: boolean): TableModel {
  const room = j.peek && !j.peek.table ? j.peek : null;
  const queued = j.peek?.table ? j.peek : null;
  const who = room ? hostName(room) : queued ? tableHostName(queued) : null;
  // a room's Join needs a seat to name; a Play table's is seated by the
  // server, which answers table_full when it is full
  const canJoin = !j.full && !busy && j.peek !== null && (queued !== null || j.seat !== null);
  // a room that is not ranked is casual; before the peek answers, no tag
  const casual = room ? !room.ranked : queued?.mode === "casual";
  return {
    kind: "join-code",
    tag: casual ? "Casual" : undefined,
    title: `Join ${who ? shortName(who) : j.code}`,
    status: j.full ? { text: "Table is full" } : undefined,
    seats: room ? roomSeats(room, j.seat, busy) : queued ? queuedSeats(queued, j.seat) : null,
    you: j.seat ?? 0,
    rows: null, waitSwitch: null, chat: null,
    primary: { label: busy ? "Joining…" : "Join", disabled: !canJoin, act: { type: "code_join" } },
    secondary: { label: "Not now", disabled: false, act: { type: "code_cancel" } },
    leave: { kind: "queue", others: [] },
  };
}

/** You at the bottom, Bot 2 across as your partner, Bots 1 and 3 opposite,
 *  as the offline server seats them. */
const OFFLINE_SEATS: ModelSeat[] = [
  { at: 0, look: "you", name: "You", sub: "", label: "You, your team" },
  { at: 1, look: "bot", name: "Bot 1", sub: "", label: "Bot 1, other team" },
  { at: 2, look: "bot", name: "Bot 2", sub: "", label: "Bot 2, your team" },
  { at: 3, look: "bot", name: "Bot 3", sub: "", label: "Bot 3, other team" },
];

/** Your offline table in Play's place, its mode tag saying Offline: the
 *  chat row greyed (chat needs the server), Start and Leave. `ready` is the
 *  on-device server's socket being open; `starting`, a Start on its way. */
export function offlineModel({ ready, starting }: { ready: boolean; starting: boolean }): TableModel {
  return {
    kind: "offline",
    tag: "Offline",
    title: "You and 3 bots",
    seats: OFFLINE_SEATS,
    you: 0,
    rows: null, waitSwitch: null, chat: { disabled: true },
    primary: { label: starting ? "Starting…" : "Start", disabled: !ready || starting, busy: starting,
               act: { type: "offline_start" } },
    secondary: { label: "Leave", disabled: false, act: { type: "offline_leave" } },
    leave: { kind: "queue", others: [] },
  };
}

/** The queue's dispatcher: each action through the store, which keeps the
 *  pending state and adds the table's sequence and sitting tokens. */
export function queueSend(a: TableAction): void {
  switch (a.type) {
    case "start": return queue.tableStart();
    case "unready": return queue.tableUnready();
    case "start_now": return queue.tableStartNow();
    case "start_bots": return queue.startBots();
    case "move": return queue.tableMove(a.seat);
    case "move_other": if (a.sit) queue.tableMoveOther(a.from, a.to, a.sit); return;
    case "leave": return queue.leave();
    case "chat": queue.tableChat(a.text); return;
    case "start_level": return queue.setStartLevel(a.level);
    case "allow_joiners": return queue.setAllowJoiners(a.on);
    case "bot_level": return queue.setBotLevel(a.level);
    case "wait_players": return a.on ? queue.waitForPlayers() : queue.allowBots();
    case "here": return queue.here();
    case "reclaim": return queue.join();
    case "offer_join": return queue.offerJoin();
    case "offer_wait": return queue.offerWait();
    case "offer_pick": return queue.offerPick(a.seat);
  }
}
