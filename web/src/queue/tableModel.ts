// The table panel's one model, from either backend: a room before its game
// (`fromRoom`) or the queue's table (`fromQueue`). The panel draws only the
// model and answers only `TableAction`s; each backend's dispatcher turns an
// action into its own frame, with that backend's precondition (a room's
// `expect`, a table's sitting token) added there.
import type { LeaveContext } from "../components/leaveCopy";
import type { ChatMsg, Rank, RoomMsg } from "../protocol";
import { conn } from "../ws";
import { BOT_FILL_MS, partnerName, queue, tableDuo } from "./store";
import type { OfferView, QueueView, TableView } from "./store";
import {
  JUST_JOINED_MS, OFFER_SECS, START_NOW_SECS, duoStartLabel, joinLabel, joinTitle, moveTargets, ownBotsAt,
  ownTitle, panelKind, roomReadyLine, roomTitle, roomWaitingLabel, sharedStatusLine, sharedTitle, shortName,
  startLabel, stillHereLine,
} from "./tableText";
import type { PanelKind } from "./tableText";

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

/** Everything a table does, the same names for both backends. */
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
  | { type: "wait_players"; on: boolean }
  | { type: "here" }
  | { type: "reclaim" }
  | { type: "offer_join" }
  | { type: "offer_wait" }
  | { type: "offer_pick"; seat: number };

/** What the panel answers itself: the leave sheet, and the opener's tap on
 *  a person and then on the seat they go to (one confirm sends the move). */
export type PanelAction =
  | TableAction
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
}

/** The settings rows: the code with its Invite link, Starting level on a
 *  casual table (the opener picks it, others read it), and Allow joiners
 *  when `joiners` is set. */
export interface TableRows {
  code: string | null;
  ranked: boolean;
  opener: boolean;
  level: string;
  joiners: boolean | undefined;
}

/** The seats the opener's move reads: a name per seat (blank for one that
 *  cannot be moved), the sitting token where the server gives one, a Duo's
 *  `pair`; null for empty. */
export type MoverSeat = { name: string; sit?: string | null; pair?: boolean } | null;

/** A panel is its title, its seats, at most one live status line, its rows
 *  and its buttons; explanations live in How to play and the coach. */
export interface TableModel {
  kind: Exclude<PanelKind, "play"> | "room";
  /** The mode tag above the title; a ranked table has none. */
  tag?: "Casual";
  title: string;
  status?: { text: string; warn?: boolean };
  seats: ModelSeat[] | null;
  you: number;
  rows: TableRows | null;
  /** The leader's Wait for people on your own table. */
  waitSwitch: { on: boolean; disabled: boolean } | null;
  chat: { messages: ChatMsg[]; you: number } | null;
  primary: TableButton | null;
  secondary: TableButton | null;
  /** A Duo's other member: who presses the buttons instead. */
  led?: string;
  leave: LeaveContext;
  movers: MoverSeat[] | null;
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

/** Your own table, drawn from the lone queue entry: the server keeps no
 *  table for one, so you sit at the bottom and a Duo partner, or the seat
 *  held for one, across. In a Duo made there each member's Start shows. */
function ownSeats(q: QueueView): ModelSeat[] {
  const partner = q.partyId ? partnerName(q.party) : null;
  const duo = tableDuo(q);
  const partnerReady = duo && (q.duoReady ?? 0) - (q.youReady ? 1 : 0) > 0;
  return [0, 1, 2, 3].map((at): ModelSeat => {
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

/** A shared table's seats; with `move`, an empty seat moves you there;
 *  with `opener`, the opener taps another person, then a seat for them
 *  (`picked`: the person tapped). */
function sharedSeats(t: TableView, now: number, move: boolean, busy: boolean, opener: boolean,
                     picked: number | null): ModelSeat[] {
  const targets = opener && picked !== null ? moveTargets(t.seats, t.heldSeats, picked) : null;
  return [0, 1, 2, 3].map((at): ModelSeat => {
    const s = t.seats[at] ?? null;
    const ours = (at - t.you + 4) % 2 === 0;
    if (!s && t.heldSeats.includes(at)) return heldSeat(at, ours);
    if (!s && targets) {
      const name = t.seats[picked!]?.name ?? "";
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
    const status = s.reconnecting ? "Reconnecting"
      : !s.you && !s.ready && s.since !== null && now - s.since < JUST_JOINED_MS ? "Just joined"
      : "";
    if (s.you) {
      return { at, look: "you", name: "You", sub: status, tick: s.ready,
               label: ["You", s.ready ? "ready" : null, status || null].filter(Boolean).join(", ") };
    }
    const partner = s.pair && ours;
    const item: ModelSeat = {
      at, look: partner ? "friend" : "person", name: shortName(s.name), sub: status, tick: s.ready,
      label: [s.name, s.ready ? "ready" : null, status || null, partner ? "your Duo partner" : teamWord(ours)]
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

/** The queue's table, by the kind its state calls for; null on Play. */
export function fromQueue(q: QueueView, { now, picked }: PanelState): TableModel | null {
  const kind = panelKind(q);
  const partner = q.partyId ? partnerName(q.party) : null;
  // a Duo made at a table has no leader to press for it: each member taps
  const led = q.leader || tableDuo(q) ? undefined : `${shortName(partner ?? "Your partner")} leads`;
  const leaveBtn: TableButton = { label: "Leave", disabled: q.pending === "leave", act: { type: "ask_leave" } };
  const ranked = (q.queueMode ?? q.playMode) === "ranked";
  const tag = (q.queueMode ?? q.playMode) === "casual" && kind !== "elsewhere" ? "Casual" as const : undefined;
  const rows: TableRows = { code: q.tableCode, ranked, opener: q.opener, level: q.startLevel,
                            joiners: q.opener ? q.allowJoiners : undefined };
  // the people a shared table keeps when you go; your own table has nobody
  // else, but for a Duo partner, who keeps it
  const others = kind === "shared" && q.table
    ? q.table.seats.flatMap((s) => (s && !s.you ? [s.name] : [])) : [];
  const duoPartner = tableDuo(q) ? partnerName(q.party) : null;
  const leave: LeaveContext = duoPartner ? { kind: "duo", partner: duoPartner, opener: q.opener }
    : { kind: "queue", others };
  const base = { tag, leave, movers: q.table?.seats ?? null, rows: null, waitSwitch: null, chat: null };
  if (kind === "join" && q.offer) {
    const o = q.offer;
    const busy = q.pending !== null;
    return {
      ...base, kind, title: joinTitle(o), seats: offerSeats(o, busy), you: o.pick,
      primary: { label: q.pending === "offer" ? "Joining…" : joinLabel(o), disabled: busy, act: { type: "offer_join" },
                 ring: q.pending === "offer" ? null : { left: Math.max(0, o.expiresAt - now) / 1000, total: OFFER_SECS } },
      secondary: { label: "Keep looking", disabled: busy, act: { type: "offer_wait" } },
    };
  }
  if (kind === "own") {
    const extra = {
      rows,
      waitSwitch: q.leader ? { on: q.waitPlayers, disabled: q.pending !== null } : null,
      chat: { messages: q.tableChat, you: q.leader ? 0 : 2 },
    };
    const ring = botsRing(ownBotsAt(q), now);
    if (tableDuo(q) && partner) {
      // the pair's own table: both tap Start, then it searches as one
      return {
        ...base, ...extra, kind,
        title: ownTitle(q, partner), status: { text: `${q.duoReady ?? 0} of 2 ready` },
        seats: ownSeats(q), you: 0,
        primary: { label: q.pending === "start" ? "Starting…" : duoStartLabel(q, partner),
                   disabled: q.pending !== null,
                   act: q.youReady ? { type: "unready" } : { type: "start" },
                   ring: q.pending === "start" ? null : ring,
                   searching: q.youReady && (q.duoReady ?? 0) >= 2, waiting: q.youReady },
        secondary: leaveBtn,
      };
    }
    return {
      ...base, ...extra, kind,
      title: ownTitle(q, partner), seats: ownSeats(q), you: 0, led,
      primary: { label: q.pending === "bots" ? "Starting…" : "Start with bots", disabled: q.pending !== null,
                 act: { type: "start_bots" }, ring: q.pending === "bots" ? null : ring },
      secondary: leaveBtn,
    };
  }
  if (kind === "shared" && q.table) {
    const t = q.table;
    const seats = sharedSeats(t, now, canMove(q), q.pending !== null, q.opener && q.stillHereUntil === null, picked);
    if (q.stillHereUntil !== null) {
      // a table with no timer asks before it drops a seat nobody is at; the
      // same I’m back as a game's held seat, and any tap counts
      return {
        ...base, kind,
        title: sharedTitle(t), status: { text: stillHereLine(q.stillHereUntil, now), warn: true },
        seats, you: t.you,
        primary: { label: "I’m back", disabled: false, act: { type: "here" } },
        secondary: leaveBtn,
      };
    }
    const ring = q.pending === "start" ? null : botsRing(t.timer?.at ?? null, now);
    // the opener's Start now, 30 s after the latest arrival, as in a room;
    // everyone else's button stays Start
    const startNow = q.opener && t.startNowAt !== null && now >= t.startNowAt;
    return {
      ...base, kind, rows, chat: { messages: q.tableChat, you: t.you },
      title: sharedTitle(t), status: { text: sharedStatusLine(t) },
      seats, you: t.you, led,
      primary: startNow
        ? { label: q.pending === "start" ? "Starting…" : "Start now", disabled: q.pending !== null,
            act: { type: "start_now" }, ring }
        : { label: q.pending === "start" ? "Starting…" : startLabel(t),
            disabled: q.pending !== null || (t.youReady && t.waitingFor.length === 0),
            act: t.youReady ? { type: "unready" } : { type: "start" }, ring, waiting: t.youReady },
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

/** The opener's Start now deadline, as a local time, from the frame's
 *  `start_now_in`; each frame restarts it. */
export function roomStartNowAt(room: RoomMsg, at: number): number | null {
  return room.start_now_in !== undefined ? at + room.start_now_in * 1000 : null;
}

const roomOpener = (room: RoomMsg) => (room.opener ?? room.host) === room.you;
const roomOthers = (room: RoomMsg) => room.players.filter((pl) => !pl.is_bot && pl.seat !== room.you);

/** Whether the room's Start now is counting down: the opener's, once
 *  others sit. */
export function roomCounting(room: RoomMsg, startNowAt: number | null): boolean {
  return roomOpener(room) && roomOthers(room).length > 0 && startNowAt !== null;
}

/** A room's seats from its frame. Before your Start an empty seat moves you
 *  there; the server refuses it once you tapped. With `opener`, the opener
 *  taps another person, then an empty seat. */
function roomSeats(room: RoomMsg, ready: Set<number>, move: boolean, opener: boolean,
                   picked: number | null): ModelSeat[] {
  const me = room.players.find((pl) => pl.seat === room.you);
  return [0, 1, 2, 3].map((at): ModelSeat => {
    const pl = room.players.find((x) => x.seat === at);
    const ours = (at - room.you + 4) % 2 === 0;
    if (!pl && opener && picked !== null) {
      const name = room.players.find((x) => x.seat === picked)?.name ?? "";
      return { at, look: "open", name: "Open seat", sub: "",
               label: `Open seat, ${teamWord(ours)}. Move ${name} here`, act: { type: "move_to", at } };
    }
    if (!pl) {
      if (move && me) {
        return { at, look: "open", name: "Open seat", sub: "",
                 label: `Open seat, ${teamWord(ours)}. Move here`, act: { type: "move", seat: at } };
      }
      return { at, look: "open", name: "Open seat", sub: "", label: `Open seat, ${teamWord(ours)}` };
    }
    const tick = ready.has(at);
    if (at === room.you) {
      return { at, look: "you", name: "You", sub: "", tick, label: ["You", tick ? "ready" : null].filter(Boolean).join(", ") };
    }
    if (pl.is_bot) return { at, look: "bot", name: shortName(pl.name), sub: "", label: `${pl.name}, bot, ${teamWord(ours)}` };
    const sub = pl.connected ? "" : "Reconnecting";
    const item: ModelSeat = { at, look: "person", name: shortName(pl.name), sub, tick,
                              label: [pl.name, tick ? "ready" : null, sub || null, teamWord(ours)].filter(Boolean).join(", ") };
    if (!opener) return item;
    return { ...item, picked: picked === at, act: { type: "pick_person", at },
             label: `${item.label}. ${picked === at ? "Moving; tap again to cancel" : "Move"}` };
  });
}

/** The people who stay when you leave the room, in seat order: the first
 *  of them takes the opener's controls, as the server hands them on. */
function staying(room: RoomMsg): string[] {
  return room.players.filter((p) => !p.is_bot && p.seat !== room.you)
    .sort((a, b) => a.seat - b.seat).map((p) => p.name);
}

/** The room's seats for the opener's move: people by name; a bot's seat
 *  and your own read blank, so neither can be picked. */
export function roomMovers(room: RoomMsg): MoverSeat[] {
  return [0, 1, 2, 3].map((at): MoverSeat => {
    const pl = room.players.find((x) => x.seat === at && !x.is_bot && at !== room.you);
    return pl ? { name: pl.name } : room.players.some((x) => x.seat === at) ? { name: "" } : null;
  });
}

/** A room before its game, as a kind of the same panel: the table's rows,
 *  the chat row, the seats, and Start for everyone. Once others sit, the
 *  opener also gets Start now when `start_now_in` runs out. */
export function fromRoom(room: RoomMsg, chat: ChatMsg[], { now, picked }: PanelState,
                         startNowAt: number | null): TableModel {
  const opener = roomOpener(room);
  const ranked = !!(room.matched || room.ranked);
  const ready = new Set(room.ready ?? []);
  const youReady = ready.has(room.you);
  const others = roomOthers(room);
  const left = roomCounting(room, startNowAt) ? Math.max(0, startNowAt! - now) : null;
  let primary: TableButton;
  if (left !== null && left <= 0) {
    primary = { label: "Start now", disabled: false, act: { type: "start_now" } };
  } else if (!youReady) {
    primary = { label: others.length ? "Start" : "Start with bots", disabled: false, act: { type: "start" } };
  } else if (left !== null) {
    primary = { label: "Start now", disabled: true, ring: { left: left / 1000, total: START_NOW_SECS } };
  } else {
    const label = roomWaitingLabel(room);
    primary = { label, disabled: label === "Starting…", waiting: true, act: { type: "unready" } };
  }
  const readyLine = roomReadyLine(room);
  return {
    kind: "room",
    tag: ranked ? undefined : "Casual",
    title: roomTitle(room),
    status: readyLine ? { text: readyLine } : undefined,
    seats: roomSeats(room, ready, !youReady, opener, opener ? picked : null),
    you: room.you,
    rows: { code: room.room, ranked, opener, level: room.start_level, joiners: room.allow_joiners },
    waitSwitch: null,
    chat: { messages: chat, you: room.you },
    primary,
    secondary: { label: "Leave", disabled: false, act: { type: "ask_leave" } },
    leave: { kind: "room", others: staying(room), host: opener },
    movers: roomMovers(room),
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
    case "wait_players": return a.on ? queue.waitForPlayers() : queue.allowBots();
    case "here": return queue.here();
    case "reclaim": return queue.join();
    case "offer_join": return queue.offerJoin();
    case "offer_wait": return queue.offerWait();
    case "offer_pick": return queue.offerPick(a.seat);
  }
}

/** A room's dispatcher: the same actions as the room's frames. A move
 *  names who it expects in the seat it moves from (`expect`), and your own
 *  move is marked in `ownMove` so the seat change it causes is not told as
 *  the opener's. The queue's own actions mean nothing to a room. */
export function roomSend(room: RoomMsg, ownMove: { current: boolean }): (a: TableAction) => void {
  return (a) => {
    switch (a.type) {
      case "start": conn.send({ type: "table_start", on: true }); return;
      case "unready": conn.send({ type: "table_start", on: false }); return;
      case "start_now": conn.send({ type: "table_start_now" }); return;
      case "move": {
        const me = room.players.find((pl) => pl.seat === room.you);
        if (!me) return;
        ownMove.current = true;
        conn.send({ type: "table_move", seat: a.seat, expect: [{ name: me.name, is_bot: me.is_bot }, null] });
        return;
      }
      case "move_other": {
        const pl = room.players.find((x) => x.seat === a.from);
        if (!pl) return;
        conn.send({ type: "table_move", seat: a.to, from: a.from, expect: [{ name: pl.name, is_bot: pl.is_bot }, null] });
        return;
      }
      case "leave": conn.send({ type: "table_leave" }); return;
      case "chat": conn.send({ type: "table_chat", text: a.text }); return;
      case "start_level": conn.send({ type: "table_start_level", start_level: a.level }); return;
      case "allow_joiners": conn.send({ type: "table_allow_joiners", on: a.on }); return;
      default: return;
    }
  };
}
