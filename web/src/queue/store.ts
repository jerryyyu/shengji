// The matchmaking queue as the client sees it: one store fed by the socket,
// read by the Ranked Play button, the queue bar and the table panel. The
// server is the authority; the store only remembers what it was last told
// and the few things the server cannot know (the clock skew).

import { useEffect, useState, useSyncExternalStore } from "react";
import { auth, effectiveName } from "../auth";
import { guestName } from "../guestName";
import type { ConnStatus } from "../ws";
import { conn, getResumeToken, getSavedName, getSavedRoom } from "../ws";
import { decideIntent, intentToJoin } from "../intent";
import { haptic } from "../native";
import type { ChatMsg, ServerMsg } from "../protocol";
import type {
  OfferSeatMsg, OpenTableOfferMsg, PartyMsg, PresenceMsg, QueueClientMsg, QueueMode, QueueStateMsg, TableFrameMsg,
  TableMovedMsg,
} from "./messages";
import { ERROR_ROUTES, QUEUE_ANSWERS } from "../errorCodes";

/** From this long before the bot fill the bar turns amber. */
export const BOTS_WARN_MS = 10_000;
/** The server's bot fill delay (BOT_FILL_SECS); `bots_at` from the server wins. */
export const BOT_FILL_MS = 60_000;
/** After a reconnect, how long the server has to hand a queued entry back
 *  before the client concludes it was dropped while away. */
export const RESYNC_MS = 2500;
/** How long a queue notice stays up. */
export const NOTE_MS = 5000;
/** How long the server has to confirm a Play before the button reverts. */
export const CONFIRM_MS = 3000;
/** While searching, how often the client asks the server what it holds. */
export const CHECK_MS = 15_000;

/** The table you sit at before its game: the last `table` frame, its
 *  times (`since`, `timers`) in local ms. Alone it is your own table. */
export type TableFrame = Omit<TableFrameMsg, "type">;
export type FrameSeat = TableFrame["seats"][number];

/** An open table offered to you, times in local ms; `pick` is the seat you
 *  have chosen (the server's pick until you tap another). */
export interface OfferView {
  room: string;
  seats: OfferSeatMsg[];
  pick: number;
  expiresAt: number;
  roundEnd: boolean;
  /** A pair's offer: both seats are fixed, yours and your partner's. */
  partner: { seat: number; name: string } | null;
}

export interface QueueNote { id: number; title: string; sub?: string }

/** The Play tab's counts: open tables (split by mode when the server
 *  says), people at them, people queued. */
export type Presence = Omit<PresenceMsg, "type">;

/** Where the Play tab's Ranked / Casual choice is kept on this device. */
export const PLAY_MODE_KEY = "shengji.playMode";

/** The mode this device last chose; Ranked until it chooses. Storage may be
 *  blocked (a private window), which reads as no choice. */
export function readPlayMode(): QueueMode {
  try {
    return window.localStorage.getItem(PLAY_MODE_KEY) === "casual" ? "casual" : "ranked";
  } catch {
    return "ranked";
  }
}

function keepPlayMode(mode: QueueMode): void {
  try {
    window.localStorage.setItem(PLAY_MODE_KEY, mode);
  } catch {
    /* blocked storage: the choice lasts this page only */
  }
}

/** Play was refused because the account already plays a ranked game: the
 *  server's words, and whether this device knows the room to go back to. */
export interface InGame { message: string; canReturn: boolean }

export interface QueueView {
  count: number;
  queued: boolean;
  /** Local ms. */
  since: number | null;
  /** The entry waits for real players only: no bot fill. */
  waitPlayers: boolean;
  front: boolean;
  leader: boolean;
  partyId: string | null;
  pending: null | "join" | "leave" | "bots" | "start" | "offer";
  /** Queued: your table (alone, your own), from the `table` frame; null
   *  when not queued or when the search is held elsewhere. */
  frame: TableFrame | null;
  /** An open table offered to you now. */
  offer: OfferView | null;
  /** Open tables you waited on that can still be joined. */
  openTables: number;
  /** Your bot wait stands still while an open table is offered. */
  botsPaused: boolean;
  /** Local ms a queue cooldown ends (Play counts it down); null when none runs. */
  cooldownUntil: number | null;
  /** The cooldown came as the answer to a Play, whose message the lobby
   *  already shows; Play need not say why again. */
  cooldownTold: boolean;
  /** The search is held by another socket of yours (another device or
   *  window): shown, but its table and controls live there. */
  elsewhere: boolean;
  party: PartyMsg | null;
  note: QueueNote | null;
  /** The last presence counts; null until the server sends any, which it
   *  does only while some count is above zero. */
  presence: Presence | null;
  /** The server's id for what the panel shows; sent back with a Start or a
   *  Join so a tap aimed at one panel never acts on the next. */
  panelSeq: number | null;
  /** Local ms you leave the table unless you answer "still here?". */
  stillHereUntil: number | null;
  inGame: InGame | null;
  /** The Ranked / Casual switch above Play: the mode Play queues in. */
  playMode: QueueMode;
  /** The mode of the search the server holds (queue_state.mode). */
  queueMode: QueueMode | null;
  /** Your table's chat, as room chat lines (`room` is the waiting table's
   *  id, empty alone at your own table); empty when not queued. */
  tableChat: ChatMsg[];
  /** Queued: a Duo table's opener, or either member of a Duo made there. */
  duo: boolean;
  /** Queued in a Duo made at a table: how many of you tapped Start; null
   *  for anyone else. */
  duoReady: number | null;
}

/** What a table's end clears: no search, no table, nothing it showed. */
const NOT_SEATED: Pick<QueueView, "queued" | "frame" | "pending" | "since" | "waitPlayers" | "front" | "offer"
  | "openTables" | "botsPaused" | "elsewhere" | "panelSeq" | "stillHereUntil" | "queueMode" | "tableChat" | "duo"
  | "duoReady"> = {
  queued: false, frame: null, pending: null, since: null, waitPlayers: false, front: false, offer: null,
  openTables: 0, botsPaused: false, elsewhere: false, panelSeq: null, stillHereUntil: null, queueMode: null,
  tableChat: [], duo: false, duoReady: null,
};

const EMPTY: QueueView = {
  ...NOT_SEATED, count: 0, leader: true, partyId: null, cooldownUntil: null, cooldownTold: false,
  party: null, note: null, presence: null, inGame: null, playMode: "ranked",
};

/** The name you play under: the account's, or a guest's own. */
function myName(): string {
  const a = auth.state;
  return a?.status === "in" && a.user ? effectiveName(a.user) : guestName.name.trim();
}

/** The toast for a seat move at your table: the opener's move of you,
 *  someone the opener moved, or someone's own move. */
export function movedNote(m: TableMovedMsg): string {
  const team = m.your_team ? "your team" : "the other team";
  if (m.by && m.you) return m.team_changed ? `${m.by} moved you to the other team.` : `${m.by} moved your seat.`;
  if (m.by) return `${m.by} moved ${m.name} to ${team}.`;
  return `${m.name} moved to ${team}.`;
}

/** Queued as the two members of a Duo made at a table: each taps Start. */
export function tableDuo(q: QueueView): boolean {
  return q.duo && q.partyId !== null && q.duoReady !== null;
}

/** The other member of a pair, by name. */
export function partnerName(party: PartyMsg | null): string | null {
  return party?.members.find((m) => !m.you)?.name ?? null;
}

/** Whether a seat at `f` is your Duo partner's: across from you, both
 *  seats a pair's. */
function partnerSeat(f: TableFrame, s: FrameSeat): boolean {
  return s.pair && f.seats[f.you]?.pair === true && s.seat === (f.you + 2) % 4;
}

/** The people at your table besides you and your Duo partner. */
export function othersAt(f: TableFrame | null): string[] {
  return f ? f.seats.flatMap((s) => (s.state === "taken" && !s.you && !partnerSeat(f, s) ? [s.name ?? ""] : [])) : [];
}

/** Someone besides you and your Duo partner sits at your table: a shared
 *  table, not your own. */
export function sharedTable(f: TableFrame | null): boolean {
  return othersAt(f).length > 0;
}

/** The names at your table besides yours, your Duo partner's too. */
export function namesAt(f: TableFrame | null): string[] {
  return f ? f.seats.flatMap((s) => (s.state === "taken" && !s.you ? [s.name ?? ""] : [])) : [];
}

/** You opened your table (alone, always), so you set its level and Allow
 *  joiners and may move people. */
export function isOpener(q: QueueView): boolean {
  return q.frame !== null && q.frame.opener === q.frame.you;
}

/** Your own Start is in (a Duo member's, alone or at a table). */
export function yourReady(q: QueueView): boolean {
  return q.frame?.your_ready === true;
}

export class QueueStore {
  view: QueueView = { ...EMPTY, playMode: readPlayMode() };
  private listeners = new Set<() => void>();
  /** Server clock minus local clock, ms. */
  private skew = 0;
  private joinSentAt: number | null = null;
  /** A queue_state that holds the entry, kept until its `table` frame,
   *  which the server sends right after it: the two are one update. */
  private heldState: QueueStateMsg | null = null;
  /** A table's chat history that came before the queue_state seating you
   *  there (the server sends it as you sit): taken up when that state lands. */
  private chatAhead: { table: string | null; lines: ChatMsg[] } | null = null;
  private droppedWhileQueued = false;
  private resyncTimer: number | null = null;
  /** After a reconnect, how long the server has to hand the pair back. */
  private partyResyncTimer: number | null = null;
  private noteTimer: number | null = null;
  /** A Play the server has not confirmed yet. */
  private confirmTimer: number | null = null;
  /** The next periodic check of what the server holds. */
  private checkTimer: number | null = null;
  private noteId = 0;
  private status: ConnStatus = "closed";
  private attached = false;
  /** The signed-in account this state belongs to; null when signed out,
   *  undefined while sign-in is still being checked (a resync may land first). */
  private account: string | null | undefined = undefined;

  attach(): void {
    if (this.attached) return;
    this.attached = true;
    // a test may stand in a partial auth store or socket
    auth.subscribe?.((a) => this.onAuth(a.status === "loading" ? undefined
                                      : a.status === "in" ? a.user?.email ?? "" : null));
    conn.subscribeStatus?.((s) => this.onStatus(s));
    conn.subscribe?.((m) => this.onMessage(m));
  }

  /** Queue, table and pair state belong to one identity: a sign-in, a
   *  sign-out, a deletion or another account's sign-in starts from nothing.
   *  A guest who signs in mid-search is told to press Play again: the socket
   *  reconnects as the account, and the server ends the guest's search,
   *  waiting-table seat and pair (the others there see an ordinary leave). */
  private onAuth(account: string | null | undefined): void {
    if (account === this.account) return;
    const was = this.account;
    this.account = account;
    // loading -> known keeps what the resync delivered
    if (was === undefined) return;
    const searching = was === null && (this.view.queued || this.view.pending === "join");
    this.clearResync();
    this.clearConfirm();
    this.clearPartyResync();
    this.joinSentAt = null;
    this.droppedWhileQueued = false;
    this.set({ ...EMPTY, count: this.view.count, presence: this.view.presence, note: null,
               playMode: this.view.playMode });
    if (searching) this.notify("Signed in. Press Play to find a table.");
  }

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  };

  getSnapshot = (): QueueView => this.view;

  private set(next: Partial<QueueView>): void {
    this.view = { ...this.view, ...next };
    if (this.view.pending !== "join") this.clearConfirm();
    this.armCheck();
    for (const fn of this.listeners) fn();
  }

  /** Ask the server what it holds for this socket; it answers queue_state. */
  private askStatus(): void {
    this.send({ type: "queue_status" });
  }

  /** While the client shows a search, it asks the server now and then, so
   *  a lost message can never leave a search on screen the server dropped. */
  private armCheck(): void {
    const showing = this.view.queued || this.view.pending !== null;
    if (!showing) {
      if (this.checkTimer !== null) window.clearTimeout(this.checkTimer);
      this.checkTimer = null;
      return;
    }
    if (this.checkTimer !== null) return;
    this.checkTimer = window.setTimeout(() => {
      this.checkTimer = null;
      if (this.status === "open" && (this.view.queued || this.view.pending !== null)) this.askStatus();
      this.armCheck();
    }, CHECK_MS);
  }

  private clearConfirm(): void {
    if (this.confirmTimer !== null) window.clearTimeout(this.confirmTimer);
    this.confirmTimer = null;
  }

  /** Local ms for a server time in Unix seconds. */
  local(serverSecs: number): number {
    return serverSecs * 1000 - this.skew;
  }

  /** A guest's messages carry the name it plays under, which is kept for
   *  next time (and for resuming a matched seat). */
  private send(msg: QueueClientMsg): boolean {
    if (auth.state?.status === "in") return conn.send(msg);
    const name = guestName.name.trim();
    if (!name) return conn.send(msg);
    guestName.keep(name);
    return conn.send({ ...msg, name });
  }

  notify(title: string, sub?: string): void {
    this.noteId += 1;
    this.set({ note: { id: this.noteId, title, sub } });
    if (this.noteTimer !== null) window.clearTimeout(this.noteTimer);
    this.noteTimer = window.setTimeout(() => {
      this.noteTimer = null;
      this.set({ note: null });
    }, NOTE_MS);
  }

  private clearResync(): void {
    if (this.resyncTimer !== null) window.clearTimeout(this.resyncTimer);
    this.resyncTimer = null;
  }

  private clearPartyResync(): void {
    if (this.partyResyncTimer !== null) window.clearTimeout(this.partyResyncTimer);
    this.partyResyncTimer = null;
  }

  private onStatus(s: ConnStatus): void {
    const was = this.status;
    this.status = s;
    // an unanswered join or start counts too: its reply may have died with the socket
    if (s !== "open" && was === "open" && (this.view.queued || this.view.pending)) {
      this.droppedWhileQueued = true;
    }
    if (s !== "open") this.heldState = null;
    // Pairs live in the server's memory: a restart forgets them, and a
    // reconnect that gets no pair back means this one is gone.
    // a new socket hears the counts again only when some count is above zero
    if (s === "open" && was !== "open" && this.view.presence) this.set({ presence: null });
    if (s === "open" && was !== "open" && this.view.party) {
      const id = this.view.party.party_id;
      this.clearPartyResync();
      this.partyResyncTimer = window.setTimeout(() => {
        this.partyResyncTimer = null;
        if (this.view.party?.party_id === id) this.set({ party: null });
      }, RESYNC_MS);
    }
    if (s === "open" && this.droppedWhileQueued) {
      this.droppedWhileQueued = false;
      this.clearResync();
      // the server answers at once; the timer below is for one that cannot
      this.askStatus();
      // A socket that comes back within the server's grace gets its entry
      // back at once (queue_state); silence means it was dropped.
      this.resyncTimer = window.setTimeout(() => {
        this.resyncTimer = null;
        const held = this.view.queued;
        if (!held && !this.view.pending) return;
        this.joinSentAt = null;
        this.set(NOT_SEATED);
        if (held) this.notify("You left the table while away.", "No cooldown.");
      }, RESYNC_MS);
    }
  }

  private onMessage(msg: ServerMsg): void {
    const now = Date.now();
    switch (msg.type) {
      case "presence":
        this.set({ presence: { tables: msg.tables, playing: msg.playing, waiting: msg.waiting,
                               ranked: msg.ranked, casual: msg.casual } });
        break;
      case "table_chat_history": {
        const lines = msg.messages.slice(-100).map((m): ChatMsg => ({ ...m, type: "chat", room: msg.table ?? "" }));
        if (this.view.queued && (this.view.frame?.chat_log ?? null) === msg.table) {
          this.chatAhead = null;
          this.set({ tableChat: lines });
        } else {
          this.chatAhead = { table: msg.table, lines };
        }
        break;
      }
      case "table_chat": {
        // the waiting table's line, or (table null) your own table's while alone
        if (!this.view.queued || (this.view.frame?.chat_log ?? null) !== msg.table
            || this.view.tableChat.some((m) => m.id === msg.id)) break;
        const line: ChatMsg = { type: "chat", id: msg.id, room: msg.table ?? "", seat: msg.seat, name: msg.name,
                                text: msg.text, t: msg.t };
        this.set({ tableChat: [...this.view.tableChat, line].slice(-100) });
        break;
      }
      case "table_moved":
        this.notify(movedNote(msg));
        break;
      case "left":
        this.heldState = null;
        break;
      case "room":
      case "state":
        // in a room: whatever refused Play no longer stands
        if (this.view.inGame) this.set({ inGame: null });
        break;
      case "queue_state": {
        this.clearResync();
        this.heldState = null;
        if (!msg.queued) {
          const wasQueued = this.view.queued && !this.view.elsewhere;
          const leaving = this.view.pending === "leave";
          // the one difference from any other end: a cooldown may run
          this.set({ ...NOT_SEATED, count: msg.count, cooldownTold: false,
                     cooldownUntil: msg.cooldown_until != null ? this.local(msg.cooldown_until) : null });
          if (msg.replaced && wasQueued) {
            const there = msg.by === "window" ? "window" : "device";
            this.notify(msg.stopped ? `Your table was closed from another ${there}.` : `Your table moved to another ${there}.`);
          } else if (wasQueued && !leaving && !msg.replaced) {
            this.notify("You're no longer at a table.", "Press Play to find one.");
          }
          break;
        }
        if (msg.elsewhere) {
          // held by another socket of yours: shown here, run there
          this.joinSentAt = null;
          this.set({ queued: true, elsewhere: true, count: msg.count,
                     since: msg.since !== undefined ? this.local(msg.since) : now,
                     waitPlayers: false, front: !!msg.front, leader: msg.leader !== false,
                     partyId: msg.party_id ?? null, pending: null, frame: null, offer: null,
                     openTables: 0, botsPaused: false, cooldownUntil: null, inGame: null,
                     panelSeq: msg.panel_seq ?? null, stillHereUntil: null, duo: false, duoReady: null });
          break;
        }
        // the table frame follows on this socket: the view changes with it
        this.heldState = msg;
        break;
      }
      case "table": {
        if (msg.phase !== "open") break;
        const held = this.heldState;
        this.heldState = null;
        if (held) this.seat(held, msg);
        else if (this.view.queued && !this.view.elsewhere && this.view.frame) this.reseat(this.frameView(msg));
        break;
      }
      case "match_started":
        this.clearResync();
        this.heldState = null;
        // a game clears its notice and an in-game refusal too
        this.set({ ...NOT_SEATED, note: null, inGame: null });
        break;
      case "match_cancelled":
        this.set({ pending: null });
        if (msg.reason === "server_error") {
          this.notify("The game could not start.", "You keep your place.");
        }
        break;
      case "queue_removed": {
        this.clearResync();
        const me = myName();
        const by = msg.by && msg.by !== me ? msg.by : null;
        this.heldState = null;
        this.set(NOT_SEATED);
        if (msg.reason === "idle") {
          this.notify("You left the table.", "No tap for 2 minutes. No cooldown.");
        } else if (msg.reason === "away") {
          this.notify(by ? `${by} left the table while away.` : "You left the table while away.",
                      "No cooldown.");
        } else if (msg.reason === "in_room" && by) {
          this.notify(`${by} joined a room, so you left the table.`);
        }
        break;
      }
      case "party": {
        this.clearPartyResync();
        const before = this.view.party;
        const joined = msg.members.length === 2 && (!before || before.members.length < 2);
        this.set({ party: msg });
        if (joined) {
          const other = partnerName(msg);
          if (other) this.notify(msg.you_lead ? `${other} joined your Duo.` : `You joined ${other}'s Duo.`);
        }
        break;
      }
      case "party_closed":
        if (this.view.party && this.view.party.party_id !== msg.party_id) break;
        this.clearPartyResync();
        this.set({ party: null });
        if (msg.by && !msg.you) this.notify(`${msg.by} left the Duo.`);
        break;
      case "error":
        if (msg.code === "account_in_game") {
          // One person holds one seat: Play's place says so, with the way
          // back when this device knows the room.
          this.joinSentAt = null;
          const canReturn = auth.state?.status === "in" && getSavedRoom() !== null;
          this.set({ pending: null, inGame: { message: msg.message, canReturn } });
          break;
        }
        if (!msg.code || !QUEUE_ANSWERS.has(msg.code)) {
          // An error the queue does not name may still be the answer to a
          // Play: never keep searching on it; the server says what it holds.
          if (this.view.pending === "join" && !("peek" in msg)) {
            this.joinSentAt = null;
            this.set({ pending: null });
            this.askStatus();
          }
          break;
        }
        this.joinSentAt = null;
        if (msg.code === "not_in_party") {
          // the server holds no pair for this account: ours is stale
          this.clearPartyResync();
          this.set({ pending: null, party: null });
        } else if (msg.code === "cooldown") {
          // the lobby shows the server's message; Play counts down to the end
          this.set({ pending: null, cooldownTold: true,
                     cooldownUntil: msg.cooldown_until != null ? this.local(msg.cooldown_until) : this.view.cooldownUntil });
        } else if (msg.code === "seat_taken") {
          this.set({ pending: null });
          this.notify(...ERROR_ROUTES.seat_taken.text);
        } else if (msg.code === "table_closed" || msg.code === "no_offer") {
          this.set({ pending: null, offer: null });
          this.notify(...ERROR_ROUTES[msg.code].text);
        } else if (msg.code === "panel_changed") {
          // the fresh panel is on its way; the tap was for the old one
          this.set({ pending: null });
          this.askStatus();
        } else if (msg.code === "pair_seats_fixed") {
          this.set({ pending: null });
          this.notify(...ERROR_ROUTES.pair_seats_fixed.text);
        } else if (msg.code === "already_ready") {
          this.set({ pending: null });
          this.notify(...ERROR_ROUTES.already_ready.text);
        } else if (msg.code === "bad_seat") {
          this.set({ pending: null });
          this.notify(...ERROR_ROUTES.bad_seat.text);
        } else if (msg.code === "start_failed") {
          // the entry left the queue before the start was tried
          this.set(NOT_SEATED);
        } else {
          this.set({ pending: null });
        }
        break;
      default:
        break;
    }
  }

  /** A queue_state that holds the entry, with the table frame that came
   *  right after it. */
  private seat(msg: QueueStateMsg, raw: TableFrameMsg): void {
    const now = Date.now();
    if (this.joinSentAt !== null && !msg.front && msg.since !== undefined) {
      // a fresh entry: `since` is the server's clock at our join
      this.skew = msg.since * 1000 - this.joinSentAt;
    }
    this.joinSentAt = null;
    const frame = this.frameView(raw);
    const shared = sharedTable(frame);
    const youReady = frame.your_ready === true;
    const duoReady = msg.duo_ready ?? null;
    // a Start alone counts only in a Duo made at your table
    const pending = this.view.pending === "bots" ? "bots"
      : this.view.pending === "start" && (shared || duoReady !== null) && !youReady ? "start" : null;
    const offer = msg.offer ? this.offerView(msg.offer) : null;
    if (offer && !this.view.offer) haptic("declare");
    // a table's chat belongs to that table: another table starts empty,
    // or with the history the server sent as you sat down
    const same = this.view.queued && (this.view.frame?.chat_log ?? null) === frame.chat_log;
    let tableChat = same ? this.view.tableChat : [];
    if (this.chatAhead && this.chatAhead.table === frame.chat_log) tableChat = this.chatAhead.lines;
    this.chatAhead = null;
    this.reseat(frame, {
      queueMode: msg.mode ?? this.view.queueMode ?? "ranked", tableChat,
      duo: msg.duo === true, duoReady,
      queued: true, count: msg.count,
      since: msg.since !== undefined ? this.local(msg.since) : now,
      waitPlayers: msg.wait_players === true,
      front: !!msg.front, leader: msg.leader !== false, partyId: msg.party_id ?? null,
      pending, offer, openTables: msg.open_tables ?? 0, botsPaused: msg.bots_paused === true,
      elsewhere: false, cooldownUntil: null, inGame: null, panelSeq: msg.panel_seq ?? null,
      stillHereUntil: shared && msg.still_here_until != null ? this.local(msg.still_here_until) : null,
    });
  }

  /** Your table is now `frame`: someone sitting down buzzes, and anyone
   *  besides your Duo partner who got up is named. */
  private reseat(frame: TableFrame, rest: Partial<QueueView> = {}): void {
    const was = this.view.frame;
    if (sharedTable(frame) && !sharedTable(was)) haptic("declare");
    const left = othersAt(was).filter((n) => !othersAt(frame).includes(n));
    this.set({ ...rest, frame });
    if (left.length === 1) this.notify(`${left[0]} left the table.`);
    else if (left.length > 1) this.notify(`${left.join(" and ")} left the table.`);
  }

  // ---- actions

  /** Queue now: as the pair when one is formed and you lead it, else alone.
   *  With `code` (a friend's table, from a link or the code box), sit at
   *  that table instead, in its mode and with its settings, as `name`: the
   *  room that table has just become, if it started meanwhile, seats you
   *  under it. */
  join(code?: string, name?: string): void {
    this.sendJoin(code, false, name);
  }

  /** Duo: your own table, as Play opens it, with the partner seat held for
   *  the friend who joins by its code. A formed pair queues as the pair. */
  joinDuo(): void {
    this.sendJoin(undefined, true);
  }

  private sendJoin(code: string | undefined, duo: boolean, name?: string): void {
    const p = this.view.party;
    const pair = p && p.members.length === 2 ? p : null;
    if (pair && !pair.you_lead && code === undefined) return;
    if (this.cooling()) return;
    const mode = this.view.playMode;
    const sent = this.send(code !== undefined ? { type: "table_join", code, ...(name ? { name } : {}) }
      : pair ? { type: "queue_join", party_id: pair.party_id, mode }
      : duo ? { type: "queue_join", mode, duo: true } : { type: "queue_join", mode });
    if (!sent) {
      this.notify("Not connected.", "Press Play again in a moment.");
      return;
    }
    this.joinSentAt = Date.now();
    this.set({ pending: "join", inGame: null });
    this.clearConfirm();
    // Searching shows only once the server confirms; a Play lost on a dead
    // socket reverts instead of searching forever.
    this.confirmTimer = window.setTimeout(() => {
      this.confirmTimer = null;
      if (this.view.pending !== "join") return;
      this.joinSentAt = null;
      this.set({ pending: null });
      this.notify("Couldn't open a table.", "Press Play to try again.");
      if (this.status === "open") this.askStatus();
    }, CONFIRM_MS);
  }

  /** The Ranked / Casual switch above Play, kept on this device. A search
   *  under way keeps its own mode (the server holds it). */
  setPlayMode(mode: QueueMode): void {
    keepPlayMode(mode);
    if (mode !== this.view.playMode) this.set({ playMode: mode });
  }

  /** Your table's Allow joiners, alone or at a waiting table (the opener
   *  only). */
  setAllowJoiners(on: boolean): void {
    if (!this.view.queued || !isOpener(this.view)) return;
    this.send({ type: "table_allow_joiners", on });
  }

  /** Your casual table's starting level (the opener only). */
  setStartLevel(level: string): void {
    if (!this.view.queued || !isOpener(this.view)) return;
    this.send({ type: "table_start_level", start_level: level });
  }

  /** Your casual table's Relaxed bots (the opener only). */
  setRelaxedBots(on: boolean): void {
    if (!this.view.queued || !isOpener(this.view)) return;
    this.send({ type: "table_relaxed_bots", on });
  }

  /** A line to everyone at your waiting table; the server echoes it back. */
  tableChat(text: string): boolean {
    const line = text.trim();
    if (!line || !this.view.queued) return false;
    return this.send({ type: "table_chat", text: line });
  }

  /** A queue cooldown still runs: Play waits it out. */
  cooling(now = Date.now()): boolean {
    return this.view.cooldownUntil !== null && this.view.cooldownUntil > now;
  }

  leave(): void {
    if (this.send({ type: "table_leave" })) this.set({ pending: "leave" });
  }

  /** The panel the tap was aimed at, for a Start or a Join. */
  private seq(): { panel_seq?: number } {
    return this.view.panelSeq !== null ? { panel_seq: this.view.panelSeq } : {};
  }

  startBots(): void {
    if (this.send({ type: "table_start_bots", ...this.seq() })) this.set({ pending: "bots" });
  }

  /** Turn the bot fill off; the server's queue_state confirms it. */
  waitForPlayers(): void {
    if (this.send({ type: "queue_wait_players" })) this.set({ waitPlayers: true });
  }

  /** Turn the bot fill back on, due a minute from now on your own table. */
  allowBots(): void {
    if (!this.send({ type: "queue_allow_bots" })) return;
    const f = this.view.frame;
    const bots = { at: Date.now() + BOT_FILL_MS, name: f?.timers.bots?.name ?? myName(), you: true };
    this.set({ waitPlayers: false,
               frame: f && !sharedTable(f) ? { ...f, timers: { ...f.timers, bots } } : f });
  }

  /** Start at the waiting table, or as a member of a Duo made at your own
   *  table: your tick is in for good. */
  tableStart(): void {
    if (!sharedTable(this.view.frame) && !tableDuo(this.view)) return;
    if (yourReady(this.view) || this.view.pending !== null) return;
    if (this.send({ type: "table_start", ...this.seq() })) this.set({ pending: "start" });
  }

  /** The opener's Start now at a waiting table: it starts at once with
   *  bots. The server refuses it before `start_now_at`. */
  tableStartNow(): void {
    if (!sharedTable(this.view.frame) || !isOpener(this.view) || this.view.pending !== null) return;
    if (this.send({ type: "table_start_now", ...this.seq() })) this.set({ pending: "start" });
  }

  /** Take your Start back while the table waits: Start shows again. */
  tableUnready(): void {
    if (!sharedTable(this.view.frame) && !tableDuo(this.view)) return;
    if (!yourReady(this.view) || this.view.pending !== null) return;
    this.send({ type: "table_start", on: false });
  }

  /** The opener moves the person at `from`, the sitting `who` the opener
   *  confirmed, to the empty `seat` (a pair moves as one); the server
   *  refuses a seat whose sitting changed, and its queue_state shows the
   *  new seats. */
  tableMoveOther(from: number, seat: number, who: string): void {
    const f = this.view.frame;
    if (!f || !sharedTable(f) || !isOpener(this.view) || this.view.pending !== null || from === f.you) return;
    if (f.seats[from]?.state !== "taken" || f.seats[from].sit !== who || f.seats[seat]?.state === "taken") return;
    this.send({ type: "table_move", seat, from, who });
  }

  /** A single at a shared table moves to an empty seat before its Start;
   *  the server's queue_state shows the new seats. */
  tableMove(seat: number): void {
    const f = this.view.frame;
    if (!f || !sharedTable(f) || f.your_ready || this.view.partyId || this.view.pending !== null) return;
    if (f.seats[seat]?.state === "taken") return;
    this.send({ type: "table_move", seat });
  }

  /** Answer "still here?". Only a tap does: the periodic queue_status is
   *  read-only and never keeps a seat. */
  here(): void {
    if (this.view.stillHereUntil === null) return;
    if (this.send({ type: "table_here" })) this.set({ stillHereUntil: null });
  }

  /** Back to the ranked game this device last sat in, through the same
   *  join_room a reload's resume sends. */
  returnToGame(): void {
    const intent = decideIntent({ savedRoom: getSavedRoom(), savedName: getSavedName() || "Player",
                                  savedToken: getResumeToken() });
    const join = intentToJoin(intent);
    if (intent.kind === "resume" && join) conn.send(join as never);
    this.set({ inGame: null });
  }

  /** Put Play back after an in-game refusal. */
  dismissInGame(): void {
    this.set({ inGame: null });
  }

  /** Take the seat you picked at the offered table. */
  offerJoin(): void {
    const o = this.view.offer;
    if (!o || this.view.pending !== null) return;
    if (this.send({ type: "open_table_join", room: o.room, seat: o.pick, ...this.seq() })) this.set({ pending: "offer" });
  }

  /** Pick another open seat at the offered table. */
  offerPick(seat: number): void {
    const o = this.view.offer;
    if (!o || o.partner || !o.seats[seat]?.open) return;
    this.set({ offer: { ...o, pick: seat } });
  }

  /** Keep queuing; the bar keeps a way back while the table is joinable. */
  offerWait(): void {
    // a Join in flight is answered by the server first
    if (!this.view.offer || this.view.pending === "offer") return;
    if (this.send({ type: "open_table_wait" })) this.set({ offer: null });
  }

  /** The bar's open-table chip: the offer again. */
  offerShow(): void {
    this.send({ type: "open_table_show" });
  }

  /** A re-sent offer keeps the seat you picked while it is still open. */
  private offerView(o: OpenTableOfferMsg): OfferView {
    const was = this.view.offer;
    const partner = o.partner ?? null;
    const keep = !partner && was && was.room === o.room && o.seats[was.pick]?.open ? was.pick : o.pick;
    return { room: o.room, seats: o.seats, pick: keep, expiresAt: this.local(o.expires_at), roundEnd: o.round_end,
             partner };
  }

  /** A table frame with its server times made local. */
  private frameView({ type: _type, ...f }: TableFrameMsg): TableFrame {
    return {
      ...f,
      seats: f.seats.map((s) => ({ ...s, since: s.since !== null ? this.local(s.since) : null })),
      timers: {
        bots: f.timers.bots ? { ...f.timers.bots, at: this.local(f.timers.bots.at) } : null,
        start_now_at: f.timers.start_now_at !== null ? this.local(f.timers.start_now_at) : null,
      },
    };
  }

  /** Leave your pair (a Duo after its game, say): the server ends it for
   *  both and tells each with party_closed. */
  leaveParty(): boolean {
    return this.send({ type: "party_leave" });
  }

  /** Test seam: forget everything, as a fresh page would. */
  reset(): void {
    this.clearResync();
    this.clearPartyResync();
    this.clearConfirm();
    if (this.checkTimer !== null) window.clearTimeout(this.checkTimer);
    this.checkTimer = null;
    if (this.noteTimer !== null) window.clearTimeout(this.noteTimer);
    this.noteTimer = null;
    this.view = { ...EMPTY, playMode: readPlayMode() };
    this.skew = 0;
    this.joinSentAt = null;
    this.heldState = null;
    this.droppedWhileQueued = false;
  }
}

export const queue = new QueueStore();
queue.attach();

export function useQueue(): QueueView {
  return useSyncExternalStore(queue.subscribe, queue.getSnapshot, queue.getSnapshot);
}

/** Date.now(), refreshed every `ms` while `active`. */
export function useNow(active: boolean, ms = 250): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const t = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(t);
  }, [active, ms]);
  return now;
}

/** "0:24" for a span in ms (rounded up for a countdown, down for elapsed). */
export function clock(ms: number, up = false): string {
  const s = Math.max(0, up ? Math.ceil(ms / 1000) : Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
