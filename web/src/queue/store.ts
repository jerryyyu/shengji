// The matchmaking queue as the client sees it: one store fed by the socket,
// read by the Ranked Play button, the queue bar, the waiting table and the
// pair sheet. The server is the authority; the store only remembers what it
// was last told and the few things the server cannot know (which sheet is
// open, the clock skew).

import { useEffect, useState, useSyncExternalStore } from "react";
import { auth, effectiveName } from "../auth";
import type { ConnStatus } from "../ws";
import { conn } from "../ws";
import { haptic } from "../native";
import type { ServerMsg } from "../protocol";
import type { PartyMsg, QueueClientMsg, WaitingTableMsg } from "./messages";
import { QUEUE_ERROR_CODES } from "./messages";

/** From this long before the bot fill the bar turns amber. */
export const BOTS_WARN_MS = 10_000;
/** The server's bot fill delay (BOT_FILL_SECS); `bots_at` from the server wins. */
export const BOT_FILL_MS = 60_000;
/** After a reconnect, how long the server has to hand a queued entry back
 *  before the client concludes it was dropped while away. */
export const RESYNC_MS = 2500;
/** How long a queue notice stays up. */
export const NOTE_MS = 5000;

/** A seat at the waiting table, times in local ms. */
export interface TableSeat {
  name: string;
  you: boolean;
  ready: boolean;
  reconnecting: boolean;
  since: number | null;
  pair: boolean;
  leader: boolean;
}

/** The shared waiting table you sit at, times in local ms. */
export interface TableView {
  id: string;
  /** Seat order; null is empty (a bot plays it). */
  seats: (TableSeat | null)[];
  you: number;
  timer: { at: number; name: string; you: boolean } | null;
  ready: number;
  of: number;
  youReady: boolean;
  waitingFor: string[];
}

export type Sheet = null | "solo" | "guest" | "party";

export interface QueueNote { id: number; title: string; sub?: string }

export interface QueueView {
  count: number;
  queued: boolean;
  /** Local ms. */
  since: number | null;
  /** Local ms of the bot fill; null when none is due. */
  botsAt: number | null;
  /** The entry waits for real players only: no bot fill. */
  waitPlayers: boolean;
  front: boolean;
  leader: boolean;
  partyId: string | null;
  pending: null | "join" | "leave" | "bots" | "start";
  /** The waiting table you sit at; null while alone in the queue. */
  table: TableView | null;
  party: PartyMsg | null;
  partyError: string | null;
  sheet: Sheet;
  /** A pair code from an invite link or typed in, not yet joined. */
  joinCode: string;
  note: QueueNote | null;
}

const EMPTY: QueueView = {
  count: 0, queued: false, since: null, botsAt: null, waitPlayers: false, front: false, leader: true,
  partyId: null, pending: null, table: null,
  party: null, partyError: null, sheet: null, joinCode: "", note: null,
};

function myName(): string {
  const a = auth.state;
  return a?.status === "in" && a.user ? effectiveName(a.user) : "";
}

/** The other member of a pair, by name. */
export function partnerName(party: PartyMsg | null): string | null {
  return party?.members.find((m) => !m.you)?.name ?? null;
}

export class QueueStore {
  view: QueueView = EMPTY;
  private listeners = new Set<() => void>();
  /** Server clock minus local clock, ms. */
  private skew = 0;
  private joinSentAt: number | null = null;
  private droppedWhileQueued = false;
  private resyncTimer: number | null = null;
  /** After a reconnect, how long the server has to hand the pair back. */
  private partyResyncTimer: number | null = null;
  private noteTimer: number | null = null;
  private noteId = 0;
  private status: ConnStatus = "closed";
  /** A guest tapped Sign in to play people: reopen the choice once signed in. */
  findAfterSignIn = false;
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

  /** Queue, table and pair state belong to one account: a sign-out,
   *  a deletion or another account's sign-in starts from nothing. */
  private onAuth(account: string | null | undefined): void {
    if (account === this.account) return;
    const was = this.account;
    this.account = account;
    // loading -> signed in keeps what the resync delivered
    if (was === null || (was === undefined && account !== null)) return;
    this.clearResync();
    this.clearPartyResync();
    this.joinSentAt = null;
    this.droppedWhileQueued = false;
    this.findAfterSignIn = false;
    this.set({ ...EMPTY, count: this.view.count, note: null });
  }

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  };

  getSnapshot = (): QueueView => this.view;

  private set(next: Partial<QueueView>): void {
    this.view = { ...this.view, ...next };
    for (const fn of this.listeners) fn();
  }

  /** Local ms for a server time in Unix seconds. */
  local(serverSecs: number): number {
    return serverSecs * 1000 - this.skew;
  }

  private send(msg: QueueClientMsg): boolean {
    return conn.send(msg);
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
    // Pairs live in the server's memory: a restart forgets them, and a
    // reconnect that gets no pair back means this one is gone.
    if (s === "open" && was !== "open" && this.view.party) {
      const id = this.view.party.party_id;
      this.clearPartyResync();
      this.partyResyncTimer = window.setTimeout(() => {
        this.partyResyncTimer = null;
        if (this.view.party?.party_id === id) this.set({ party: null, partyError: null });
      }, RESYNC_MS);
    }
    if (s === "open" && this.droppedWhileQueued) {
      this.droppedWhileQueued = false;
      this.clearResync();
      // A socket that comes back within the server's grace gets its entry
      // back at once (queue_state); silence means it was dropped.
      this.resyncTimer = window.setTimeout(() => {
        this.resyncTimer = null;
        const held = this.view.queued;
        if (!held && !this.view.pending) return;
        const signedIn = auth.state?.status === "in";
        this.joinSentAt = null;
        this.set({ queued: false, table: null, pending: null, since: null, botsAt: null, waitPlayers: false, front: false });
        if (held && signedIn) this.notify("You left the queue while away.", "No cooldown.");
      }, RESYNC_MS);
    }
  }

  private onMessage(msg: ServerMsg): void {
    const now = Date.now();
    // the queue and pairs are signed-in only; a signed-out page keeps just the count
    if (this.account === null && msg.type !== "queue_count") return;
    switch (msg.type) {
      case "queue_count":
        this.set({ count: msg.count });
        break;
      case "queue_state": {
        this.clearResync();
        if (!msg.queued) {
          const wasQueued = this.view.queued;
          this.set({ queued: false, count: msg.count, since: null, botsAt: null, waitPlayers: false, front: false,
                     pending: null, table: null });
          if (msg.replaced && wasQueued) this.notify("Your search moved to another window.");
          break;
        }
        if (this.joinSentAt !== null && !msg.front && msg.since !== undefined) {
          // a fresh entry: `since` is the server's clock at our join
          this.skew = msg.since * 1000 - this.joinSentAt;
        }
        this.joinSentAt = null;
        const table = msg.table ? this.tableView(msg.table) : null;
        // someone sat down with you: the bar grows into the table
        if (table && !this.view.table) haptic("declare");
        const pending = this.view.pending === "bots" ? "bots"
          : this.view.pending === "start" && table && !table.youReady ? "start" : null;
        this.set({
          queued: true, count: msg.count,
          since: msg.since !== undefined ? this.local(msg.since) : now,
          botsAt: msg.bots_at != null ? this.local(msg.bots_at) : null,
          waitPlayers: msg.wait_players === true,
          front: !!msg.front, leader: msg.leader !== false, partyId: msg.party_id ?? null,
          pending, table,
        });
        break;
      }
      case "match_started":
        this.clearResync();
        this.set({ queued: false, table: null, pending: null, sheet: null,
                   since: null, botsAt: null, waitPlayers: false, front: false, note: null });
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
        this.set({ queued: false, table: null, pending: null, since: null, botsAt: null, waitPlayers: false,
                   front: false });
        if (msg.reason === "idle") {
          this.notify("You left the table.", "No tap for 2 minutes. No cooldown.");
        } else if (msg.reason === "away") {
          this.notify(by ? `${by} left the queue while away.` : "You left the queue while away.",
                      "No cooldown.");
        } else if (msg.reason === "in_room" && by) {
          this.notify(`${by} joined a room, so your search ended.`);
        }
        break;
      }
      case "party": {
        this.clearPartyResync();
        const before = this.view.party;
        const joined = msg.members.length === 2 && (!before || before.members.length < 2);
        this.set({ party: msg, partyError: null, joinCode: "",
                   sheet: joined && this.view.sheet === "party" ? null : this.view.sheet });
        if (joined) {
          const other = partnerName(msg);
          if (other) this.notify(msg.you_lead ? `${other} joined your pair.` : `You joined ${other}'s pair.`);
        }
        break;
      }
      case "party_closed":
        if (this.view.party && this.view.party.party_id !== msg.party_id) break;
        this.clearPartyResync();
        this.set({ party: null });
        if (msg.reason === "expired") this.notify("Your pair code expired.");
        else if (msg.by && !msg.you) this.notify(`${msg.by} left the pair.`);
        break;
      case "error":
        if (!msg.code || !QUEUE_ERROR_CODES.has(msg.code)) break;
        this.joinSentAt = null;
        if (msg.code === "not_in_party") {
          // the server holds no pair for this account: the chip is stale
          this.clearPartyResync();
          this.set({ pending: null, party: null, partyError: null });
        } else if (msg.code.startsWith("party") || msg.code === "in_queue" || msg.code === "in_party") {
          this.set({ pending: null, partyError: msg.message });
        } else if (msg.code === "start_failed") {
          // the entry left the queue before the start was tried
          this.set({ pending: null, queued: false, table: null, since: null, botsAt: null, waitPlayers: false,
                     front: false });
        } else {
          this.set({ pending: null });
        }
        break;
      default:
        break;
    }
  }

  // ---- actions

  /** Queue now: as the pair when one is formed and you lead it, else alone. */
  join(): void {
    const p = this.view.party;
    const pair = p && p.members.length === 2 ? p : null;
    if (pair && !pair.you_lead) return;
    const sent = this.send(pair ? { type: "queue_join", party_id: pair.party_id } : { type: "queue_join" });
    if (!sent) return;
    this.joinSentAt = Date.now();
    this.set({ pending: "join", sheet: null });
  }

  leave(): void {
    if (this.send({ type: "queue_leave" })) this.set({ pending: "leave" });
  }

  startBots(): void {
    if (this.send({ type: "queue_start_bots" })) this.set({ pending: "bots" });
  }

  /** Turn the bot fill off; the server's queue_state confirms it. */
  waitForPlayers(): void {
    if (this.send({ type: "queue_wait_players" })) this.set({ waitPlayers: true, botsAt: null });
  }

  /** Turn the bot fill back on, due a minute from now. */
  allowBots(): void {
    if (this.send({ type: "queue_allow_bots" })) {
      this.set({ waitPlayers: false, botsAt: Date.now() + BOT_FILL_MS });
    }
  }

  /** Start at the waiting table: your tick is in for good. */
  tableStart(): void {
    const t = this.view.table;
    if (!t || t.youReady || this.view.pending !== null) return;
    if (this.send({ type: "table_start" })) this.set({ pending: "start" });
  }

  private tableView(t: WaitingTableMsg): TableView {
    return {
      id: t.id, you: t.you, ready: t.ready, of: t.of, youReady: t.you_ready, waitingFor: t.waiting_for,
      seats: t.seats.map((s) => (s ? { ...s, since: s.since !== null ? this.local(s.since) : null } : null)),
      timer: t.timer ? { ...t.timer, at: this.local(t.timer.at) } : null,
    };
  }

  openSheet(sheet: Sheet): void {
    this.set({ sheet, partyError: null });
  }

  closeSheet(): void {
    this.set({ sheet: null });
  }

  /** The pair sheet, with a code to share: one is made if you have none. */
  openParty(): void {
    this.set({ sheet: "party", partyError: null });
    if (!this.view.party && !this.view.joinCode) this.send({ type: "party_create" });
  }

  makeCode(): void {
    this.set({ joinCode: "", partyError: null });
    this.send({ type: "party_create" });
  }

  setJoinCode(code: string): void {
    this.set({ joinCode: code.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 4), partyError: null });
  }

  /** A pair-sheet message the server did not send as a party error. */
  showPartyError(message: string | null): void {
    this.set({ partyError: message });
  }

  joinParty(code: string): void {
    const c = code.trim().toUpperCase();
    if (c.length !== 4) return;
    this.send({ type: "party_join", code: c });
  }

  leaveParty(): void {
    this.send({ type: "party_leave" });
  }

  /** Test seam: forget everything, as a fresh page would. */
  reset(): void {
    this.clearResync();
    this.clearPartyResync();
    if (this.noteTimer !== null) window.clearTimeout(this.noteTimer);
    this.noteTimer = null;
    this.view = EMPTY;
    this.skew = 0;
    this.joinSentAt = null;
    this.droppedWhileQueued = false;
    this.findAfterSignIn = false;
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
