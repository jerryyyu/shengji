// The table panel's one model, from the queue's table (`fromQueue`), a
// code's peek (`fromCode`) or the offline table (`offlineModel`). The panel draws only the model and answers only
// `PanelAction`s; the queue's dispatcher turns a `TableAction` into its
// frame, with the table's sitting token added there.
import type { CodeJoin } from "../codeJoin";
import { t } from "../i18n";
import type { LeaveContext } from "../components/leaveCopy";
import { hostName, roomChoices, tableHostName, takeoverSeats } from "../joinSeats";
import type { ChatMsg, Rank, RoomSeats, TableSeats } from "../protocol";
import { BOT_FILL_MS, isOpener, namesAt, partnerName, queue, tableDuo, yourReady } from "./store";
import type { OfferView, QueueView, TableFrame } from "./store";
import type { BotLevel } from "./messages";
import { telemetry, type TapId } from "../telemetry";
import {
  JUST_JOINED_MS, OFFER_SECS, joinTitle, labelList, moveTargets, ownBotsAt, ownTitle, panelKind,
  ownerName, seatLabel, sharedStatusLine, sharedTitle, shortName, stillHereLine, teamWord, waitingLine,
} from "./tableText";
import type { PanelKind } from "./tableText";

/** One seat as the panel draws it in its team columns. The seats carry names and live status only;
 *  which seat is your partner's the layout already shows. */
export interface SeatItem {
  at: number;
  /** `held`: an empty seat kept for a Duo opener's friend. */
  look: "you" | "friend" | "person" | "open" | "held" | "bot";
  /** Empty for an open seat, drawn as its "+" alone; a dropped player's
   *  open seat in a Join panel keeps "Name (away)". */
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
  /** A person's companion look, when the frame names one; their portrait
   *  shows the default without it. */
  companion?: string | null;
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
  | { type: "chat"; text: string; phrase?: string }
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

/** What the offline table does: Start deals at once; Leave puts Play back;
 *  the Nearby switch opens the table to nearby phones (or closes it), and
 *  its denied line's link opens Settings. At a nearby table the host's
 *  Start starts it, a guest's Ready is its tick, and the joiner's not-found
 *  panel tries again. */
export type OfflineAction =
  | { type: "offline_start" }
  | { type: "offline_leave" }
  | { type: "nearby_toggle" }
  | { type: "nearby_settings" }
  | { type: "nearby_start" }
  | { type: "nearby_ready"; on: boolean }
  | { type: "nearby_again" };

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
  /** Your Ready is in, and a tap takes it back: drawn quiet. */
  waiting?: boolean;
  /** A toggle's state, drawn as `aria-pressed`. */
  pressed?: boolean;
  /** Drawn as `aria-busy`: the press is on its way. */
  busy?: boolean;
}

/** The rows: the code with its Invite, then the settings, Starting level
 *  and Bots (when `bots` is set) on a casual table (the opener picks them,
 *  others read them), and Allow joiners when `joiners` is set. The panel
 *  folds two or more settings into one Table settings row. */
export interface TableRows {
  code: string | null;
  /** The code is the Invite control; a nearby table has no link to share. */
  invite?: boolean;
  ranked: boolean;
  opener: boolean;
  /** The Starting level; null for a table that has no such row (offline). */
  level: string | null;
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
  /** The mode tag above the title, where nothing else on screen says the
   *  mode: the offline panels and a code's Join panel. The queue's panels sit
   *  under the Ranked / Casual switch and have none. */
  tag?: "Casual" | "Offline";
  title: string;
  /** `link`: a button at the line's end (the denied line's Open Settings). */
  status?: { text: string; warn?: boolean; link?: { label: string; act: PanelAction } };
  seats: ModelSeat[] | null;
  you: number;
  /** The seat the columns are drawn around, when it is not `you`: a seat
   *  picker's, which stays put while a tap moves `you`, so the tapped seat
   *  glows where it was tapped. */
  layout?: number;
  rows: TableRows | null;
  /** The leader's Wait for people on your own table. */
  waitSwitch: { on: boolean; disabled: boolean } | null;
  /** The offline host's Nearby switch; `disabled` once someone has joined,
   *  when only Leave ends the table. */
  nearbySwitch?: { label: string; on: boolean; disabled: boolean } | null;
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


/** The seats of the table an offer would sit you at, you in the picked seat. */
function offerSeats(o: OfferView, busy: boolean): ModelSeat[] {
  return o.seats.map((s, at): ModelSeat => {
    const ours = (at - o.pick + 4) % 2 === 0;
    if (at === o.pick) return { at, look: "you", name: t("queue.seat.you"), sub: "", label: t("queue.seat.youOurs") };
    if (o.partner && at === o.partner.seat) {
      return { at, look: "friend", name: shortName(o.partner.name), sub: "",
               label: t("queue.seat.partnerNamed", { name: o.partner.name }) };
    }
    if (s.open && !o.partner) {
      // whose seat it was is the screen reader's only; the seat shows a name alone
      return { at, look: "open", name: "", sub: "", busy,
               label: s.bot ? seatLabel("queue.seat.openSit", ours) : seatLabel("queue.seat.openAwaySit", ours, { name: s.name }),
               act: { type: "offer_pick", seat: at } };
    }
    if (s.bot || s.open) return { at, look: "bot", name: t("queue.seat.bot"), sub: "", label: seatLabel("queue.seat.bot", ours) };
    return { at, look: "person", name: shortName(s.name), sub: "", label: seatLabel("queue.seat.playing", ours, { name: s.name }) };
  });
}

/** The held seat: "Partner" across from you, the friend a Duo waits for. */
function heldSeat(at: number, ours: boolean): ModelSeat {
  return { at, look: "held", name: t("queue.seat.partner"), sub: "",
           label: ours ? t("queue.seat.heldFriend") : seatLabel("queue.seat.held", false) };
}

/** Whether you may move seats: a single, before your Ready, with someone
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
        ? { at, look: "open", name: "", sub: "", busy,
            label: seatLabel("queue.seat.openMoveOther", ours, { name }), act: { type: "move_to", at } }
        : { at, look: "open", name: "", sub: "", label: seatLabel("queue.seat.open", ours) };
    }
    if (!s && move) {
      return { at, look: "open", name: "", sub: "", busy,
               label: seatLabel("queue.seat.openMove", ours), act: { type: "move", seat: at } };
    }
    if (!s) return { at, look: "open", name: "", sub: "", label: seatLabel("queue.seat.open", ours) };
    const name = s.name ?? "";
    const ready = s.ready === true;
    const status = alone ? ""
      : s.reconnecting ? t("queue.seat.reconnecting")
      : !s.you && !ready && s.since !== null && now - s.since < JUST_JOINED_MS ? t("queue.seat.justJoined")
      : "";
    if (s.you) {
      return { at, look: "you", name: t("queue.seat.you"), sub: status, tick: ready,
               label: alone && !ready ? t("queue.seat.youOurs")
                 : labelList([t("queue.seat.you"), ready && t("queue.seat.ready"), status]) };
    }
    const partner = s.pair && ours;
    const item: ModelSeat = {
      at, look: partner ? "friend" : "person", name: shortName(name), sub: status, tick: ready,
      companion: s.look ?? null,
      label: labelList([name, ready && t("queue.seat.ready"), status,
                        partner ? t("queue.seat.duoPartner") : teamWord(ours)]),
    };
    if (!opener || partner) return item;
    const on = picked === at;
    return { ...item, picked: on, busy, act: { type: "pick_person", at },
             label: t(on ? "queue.seat.moving" : "queue.seat.movable", { name: item.label }) };
  });
}

/** A joiner's Ready: the same word on and off, pressed once tapped (its
 *  seat's tick says so too); a second tap takes it back. A signal only:
 *  the owner's Start never waits for it. */
function readyToggle(on: boolean, pending: QueueView["pending"], ring: Ring | null): TableButton {
  return { label: t("queue.btn.ready"), disabled: pending !== null, pressed: on, waiting: on,
           act: on ? { type: "unready" } : { type: "start" }, ring: pending === "start" ? null : ring };
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
  const led = q.leader || tableDuo(q) ? undefined
    : t("queue.led", { name: shortName(partner ?? t("queue.led.partner")) });
  const leaveBtn: TableButton = { label: t("queue.btn.leave"), disabled: q.pending === "leave", act: { type: "ask_leave" } };
  const ranked = (q.queueMode ?? q.playMode) === "ranked";
  const f = q.frame;
  const opener = isOpener(q);
  const rows: TableRows = { code: f?.code ?? null, ranked, opener, level: f?.settings.start_level ?? "2",
                            joiners: opener ? f?.settings.allow_joiners !== false : undefined,
                            bots: ranked ? undefined : f?.settings.bot_level };
  const leave = queueLeaveContext(q);
  const base = { leave, rows: null, waitSwitch: null, chat: null };
  if (kind === "join" && q.offer) {
    const o = q.offer;
    const busy = q.pending !== null;
    return {
      ...base, kind, title: joinTitle(o), seats: offerSeats(o, busy), you: o.pick,
      primary: { label: t(q.pending === "offer" ? "queue.btn.joining" : "queue.btn.join"), disabled: busy,
                 act: { type: "offer_join" },
                 ring: q.pending === "offer" ? null : { left: Math.max(0, o.expiresAt - now) / 1000, total: OFFER_SECS } },
      secondary: { label: t("queue.btn.keepLooking"), disabled: busy, act: { type: "offer_wait" } },
    };
  }
  if (kind === "own" && f) {
    const extra = {
      rows,
      waitSwitch: q.leader ? { on: q.waitPlayers, disabled: q.pending !== null } : null,
      chat: { messages: q.tableChat, you: f.you },
    };
    const seats = frameSeats(f, now, { alone: true });
    const ring = botsRing(ownBotsAt(q), now);
    if (tableDuo(q) && partner) {
      // the pair's own table: the leader owns it and starts, Ready or not;
      // the partner's Ready is a signal (its tick)
      if (q.leader) {
        return {
          ...base, ...extra, kind,
          title: ownTitle(q, partner), seats, you: f.you,
          primary: { label: t(q.pending === "bots" ? "queue.btn.starting" : "queue.btn.startBots"),
                     disabled: q.pending !== null, act: { type: "start_bots" },
                     ring: q.pending === "bots" ? null : ring },
          secondary: leaveBtn,
        };
      }
      const youReady = yourReady(q);
      return {
        ...base, ...extra, kind,
        title: ownTitle(q, partner), status: { text: waitingLine(partner) }, seats, you: f.you,
        primary: readyToggle(youReady, q.pending, ring),
        secondary: leaveBtn,
      };
    }
    return {
      ...base, ...extra, kind,
      title: ownTitle(q, partner), seats, you: f.you, led,
      primary: { label: t(q.pending === "bots" ? "queue.btn.starting" : "queue.btn.startBots"), disabled: q.pending !== null,
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
        primary: { label: t("queue.btn.back"), disabled: false, act: { type: "here" } },
        secondary: leaveBtn,
      };
    }
    const ring = q.pending === "start" ? null : botsRing(f.timers.bots?.at ?? null, now);
    // only the owner starts, with everyone seated, Ready or not; a
    // joiner's Ready is a signal (its tick and the owner's count)
    const owns = opener && q.leader;
    return {
      ...base, kind, rows, chat: { messages: q.tableChat, you: f.you },
      title: sharedTitle(f), status: { text: owns ? sharedStatusLine(f) : waitingLine(ownerName(f)) },
      seats, you: f.you, led,
      primary: owns
        ? { label: t(q.pending === "start" ? "queue.btn.starting" : "queue.btn.startBots"),
            disabled: q.pending !== null, act: { type: "start_now" }, ring }
        : readyToggle(f.your_ready === true, q.pending, ring),
      secondary: leaveBtn,
    };
  }
  if (kind === "elsewhere") {
    return {
      ...base, kind,
      title: t("queue.title.elsewhere"), seats: null, you: 0,
      primary: { label: t("queue.btn.back"), disabled: q.pending !== null, act: { type: "reclaim" } },
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
        ? { at, look: "open", picked: true, name: t("queue.seat.away", { name: shortName(sd.name) }), sub: "",
            label: t("queue.seat.awayYours", { name: sd.name }) }
        : { at, look: "open", name: t("queue.seat.away", { name: shortName(sd.name) }), sub: "",
            label: seatLabel("queue.seat.awaySit", ours, { name: sd.name }), ...move };
    }
    if (at === you) return { at, look: "you", picked: true, name: t("queue.seat.you"), sub: "", label: t("queue.seat.youOurs") };
    if (!sd) return { at, look: "open", name: "", sub: "", label: seatLabel("queue.seat.open", ours), ...move };
    if (sd.is_bot) {
      return { at, look: "bot", name: t("queue.seat.bot"), sub: "",
               label: seatLabel(choices.has(at) ? "queue.seat.botSit" : "queue.seat.bot", ours), ...move };
    }
    return { at, look: "person", name: shortName(sd.name), sub: "", label: seatLabel("queue.seat.named", ours, { name: sd.name }) };
  });
}

/** A queued table's four seats as they stand: who sits there (with their
 *  Ready), the open seats and a Duo's held partner seat, and you, glowing,
 *  where a code join sits you (the server seats it by its own rule, so no
 *  other seat is offered). */
function queuedSeats(peek: TableSeats, you: number | null): ModelSeat[] {
  const from = you ?? 0;
  return [0, 1, 2, 3].map((at): ModelSeat => {
    const sd = peek.seats.find((s) => s.seat === at);
    const ours = (at - from + 4) % 2 === 0;
    if (at === you) return { at, look: "you", picked: true, name: t("queue.seat.you"), sub: "", label: t("queue.seat.youOurs") };
    if (sd?.state === "held") {
      return { at, look: "held", name: t("queue.seat.partner"), sub: "", label: seatLabel("queue.seat.held", ours) };
    }
    if (sd?.state !== "taken" || !sd.name) return { at, look: "open", name: "", sub: "", label: seatLabel("queue.seat.open", ours) };
    return { at, look: "person", name: shortName(sd.name), sub: "", tick: sd.ready,
             label: labelList([sd.name, sd.ready && t("queue.seat.ready"), teamWord(ours)]) };
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
  // a table closed for a moment (its host claiming another seat) waits to reopen
  const canJoin = !j.full && !busy && j.peek !== null && !queued?.closed && (queued !== null || j.seat !== null);
  // a room that is not ranked is casual; before the peek answers, no tag
  const casual = room ? !room.ranked : queued?.mode === "casual";
  return {
    kind: "join-code",
    tag: casual ? "Casual" : undefined,
    title: t("queue.title.join", { name: who ? shortName(who) : j.code }),
    status: j.full ? { text: t("queue.status.full") } : undefined,
    seats: room ? roomSeats(room, j.seat, busy) : queued ? queuedSeats(queued, j.seat) : null,
    you: j.seat ?? 0,
    rows: null, waitSwitch: null, chat: null,
    primary: { label: t(busy ? "queue.btn.joining" : "queue.btn.join"), disabled: !canJoin, act: { type: "code_join" } },
    secondary: { label: t("queue.btn.notNow"), disabled: false, act: { type: "code_cancel" } },
    leave: { kind: "queue", others: [] },
  };
}

/** You at the bottom, Bot 2 across as your partner, Bots 1 and 3 opposite,
 *  as the offline server seats them. */
function offlineSeats(): ModelSeat[] {
  const bot = (at: number): ModelSeat => ({ at, look: "bot", name: t("queue.seat.botN", { n: at }), sub: "",
                                            label: seatLabel("queue.seat.botN", at === 2, { n: at }) });
  return [{ at: 0, look: "you", name: t("queue.seat.you"), sub: "", label: t("queue.seat.youOurs") }, bot(1), bot(2), bot(3)];
}

/** The offline table's Nearby switch row and its line, as nearbyModel.ts
 *  words them. */
export interface NearbySwitch {
  label: string;
  on: boolean;
  status?: TableModel["status"];
}

/** Your offline table in Play's place, its mode tag saying Offline: the
 *  chat row greyed (chat needs the server), Start and Leave. `ready` is the
 *  on-device server's socket being open; `starting`, a Start on its way. */
export function offlineModel({ ready, starting, bots, nearby = null }: {
  ready: boolean; starting: boolean; bots: BotLevel;
  /** The Nearby switch, where this page offers nearby play (nearbyModel.ts
   *  builds it): `on` while the table is being opened to nearby phones;
   *  `status`, its one line after it fell back off. */
  nearby?: NearbySwitch | null;
}): TableModel {
  const status = nearby?.status;
  return {
    kind: "offline",
    tag: "Offline",
    title: t("queue.title.offline"),
    status,
    seats: offlineSeats(),
    you: 0,
    // the Bots row only, which you pick until Start; while the table is being
    // opened to nearby phones it shows the level the nearby table takes
    rows: { code: null, ranked: false, opener: !starting && !nearby?.on, level: null, joiners: undefined, bots },
    waitSwitch: null,
    nearbySwitch: nearby ? { label: nearby.label, on: nearby.on, disabled: nearby.on } : null,
    // nearby tables have no chat
    chat: nearby?.on ? null : { disabled: true },
    primary: { label: t(starting ? "queue.btn.starting" : "queue.btn.start"), disabled: !ready || starting, busy: starting,
               act: { type: "offline_start" } },
    secondary: { label: t("queue.btn.leave"), disabled: false, act: { type: "offline_leave" } },
    leave: { kind: "queue", others: [] },
  };
}

/** The panel's taps that telemetry names, by action. */
const TAPS: Partial<Record<TableAction["type"], TapId | ((a: TableAction) => TapId)>> = {
  start: "table_start", start_bots: "start_with_bots", leave: "leave_queue",
  wait_players: (a) => (a.type === "wait_players" && a.on ? "wait_people_on" : "wait_people_off"),
  offer_join: "offer_join", offer_wait: "offer_wait",
};

/** The queue's dispatcher: each action through the store, which keeps the
 *  pending state and adds the table's sequence and sitting tokens. */
export function queueSend(a: TableAction): void {
  const tap = TAPS[a.type];
  if (tap) telemetry.tap(typeof tap === "function" ? tap(a) : tap);
  switch (a.type) {
    case "start": return queue.tableStart();
    case "unready": return queue.tableUnready();
    case "start_now": return queue.tableStartNow();
    case "start_bots": return queue.startBots();
    case "move": return queue.tableMove(a.seat);
    case "move_other": if (a.sit) queue.tableMoveOther(a.from, a.to, a.sit); return;
    case "leave": return queue.leave();
    case "chat": queue.tableChat(a.text, a.phrase); return;
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
