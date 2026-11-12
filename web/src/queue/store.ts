// The matchmaking queue as the client sees it: one store fed by the socket,
// read by the Find a game button, the queue bar, the ready check and the pair
// sheet. The server is the authority; the store only remembers what it was
// last told and the few things the server cannot know (which sheet is open,
// whether this client declined, the clock skew).

import { useEffect, useState, useSyncExternalStore } from "react";
import { auth, effectiveName } from "../auth";
import type { ConnStatus } from "../ws";
import { conn } from "../ws";
import { haptic } from "../native";
import type { ServerMsg } from "../protocol";
import type { PartyMsg, QueueClientMsg } from "./messages";
import { QUEUE_ERROR_CODES } from "./messages";

/** From this long before the bot fill the bar turns amber. */
export const BOTS_WARN_MS = 10_000;
/** After a reconnect, how long the server has to hand a queued entry back
 *  before the client concludes it was dropped while away. */
export const RESYNC_MS = 2500;
/** How long a queue notice stays up. */
export const NOTE_MS = 5000;

export interface ReadyCheck {
  id: string;
  /** Local ms. */
  deadline: number;
  /** The whole countdown, ms, for the ring. */
  window: number;
  size: number;
  bots: number;
  partyId: string | null;
  accepted: number;
  of: number;
  names: string[] | null;
  mine: "pending" | "accepted";
}

/** The ready check ended with this client's entry out of the queue. */
export interface Missed {
  reason: "missed" | "declined";
  /** The pair member who missed it, when it was not you. */
  by: string | null;
}

export type Sheet = null | "solo" | "guest" | "party";

export interface QueueNote { id: number; title: string; sub?: string }

export interface QueueView {
  count: number;
  queued: boolean;
  /** Local ms. */
  since: number | null;
  botsAt: number | null;
  front: boolean;
  leader: boolean;
  partyId: string | null;
  pending: null | "join" | "leave" | "bots";
  check: ReadyCheck | null;
  missed: Missed | null;
  /** Local ms. */
  cooldownUntil: number | null;
  party: PartyMsg | null;
  partyError: string | null;
  sheet: Sheet;
  /** A pair code from an invite link or typed in, not yet joined. */
  joinCode: string;
  note: QueueNote | null;
}

const EMPTY: QueueView = {
  count: 0, queued: false, since: null, botsAt: null, front: false, leader: true,
  partyId: null, pending: null, check: null, missed: null, cooldownUntil: null,
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
  private declined: string | null = null;
  private droppedWhileQueued = false;
  /** A ready check failed for someone else: say so once the queue_state
   *  that follows tells whether this entry went to the front. */
  private missedByOther = false;
  private resyncTimer: number | null = null;
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

  /** Queue, pair and ready-check state belong to one account: a sign-out,
   *  a deletion or another account's sign-in starts from nothing. */
  private onAuth(account: string | null | undefined): void {
    if (account === this.account) return;
    const was = this.account;
    this.account = account;
    // loading -> signed in keeps what the resync delivered
    if (was === null || (was === undefined && account !== null)) return;
    this.clearResync();
    this.declined = null;
    this.joinSentAt = null;
    this.droppedWhileQueued = false;
    this.missedByOther = false;
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

  private onStatus(s: ConnStatus): void {
    const was = this.status;
    this.status = s;
    // an unanswered join or start counts too: its reply may have died with the socket
    if (s !== "open" && was === "open" && (this.view.queued || this.view.check || this.view.pending)) {
      this.droppedWhileQueued = true;
    }
    if (s === "open" && this.droppedWhileQueued) {
      this.droppedWhileQueued = false;
      this.clearResync();
      // A socket that comes back within the server's grace gets its entry
      // back at once (queue_state); silence means it was dropped.
      this.resyncTimer = window.setTimeout(() => {
        this.resyncTimer = null;
        const held = this.view.queued || !!this.view.check;
        if (!held && !this.view.pending) return;
        const signedIn = auth.state?.status === "in";
        this.joinSentAt = null;
        this.set({ queued: false, check: null, pending: null, since: null, botsAt: null, front: false });
        if (held && signedIn) this.notify("You left the queue while away.", "Tap Find a game to queue again; no cooldown.");
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
          this.set({ queued: false, count: msg.count, since: null, botsAt: null, front: false,
                     pending: null, check: this.view.check });
          if (msg.replaced && wasQueued) this.notify("Your search moved to another window.");
          break;
        }
        if (this.joinSentAt !== null && !msg.front && msg.since !== undefined) {
          // a fresh entry: `since` is the server's clock at our join
          this.skew = msg.since * 1000 - this.joinSentAt;
        }
        this.joinSentAt = null;
        if (this.missedByOther) {
          this.missedByOther = false;
          // only an entry whose every member accepted goes to the front
          this.notify("A player didn't accept.", msg.front ? "You're back in the queue and keep your place."
                                                           : "You're still in the queue.");
        }
        this.set({
          queued: true, count: msg.count,
          since: msg.since !== undefined ? this.local(msg.since) : now,
          botsAt: msg.bots_at !== undefined ? this.local(msg.bots_at) : null,
          front: !!msg.front, leader: msg.leader !== false, partyId: msg.party_id ?? null,
          pending: this.view.pending === "bots" ? "bots" : null,
          missed: null, cooldownUntil: null,
        });
        break;
      }
      case "match": {
        this.clearResync();
        this.skew = (msg.deadline - msg.deadline_in) * 1000 - now;
        const window_ = Math.max(0, msg.deadline_in * 1000);
        this.set({
          check: { id: msg.match_id, deadline: now + window_, window: Math.max(window_, 1), size: msg.size,
                   bots: msg.bots, partyId: msg.party_id, accepted: 0, of: msg.size, names: null,
                   mine: "pending" },
          sheet: null, pending: null,
        });
        haptic("declare");
        break;
      }
      case "match_ready": {
        const c = this.view.check;
        if (!c || c.id !== msg.match_id) break;
        this.set({ check: { ...c, accepted: msg.accepted, of: msg.of, names: msg.names ?? c.names } });
        break;
      }
      case "match_started":
        this.clearResync();
        this.set({ queued: false, check: null, pending: null, sheet: null, missed: null,
                   since: null, botsAt: null, front: false, note: null });
        break;
      case "match_cancelled": {
        const c = this.view.check?.id === msg.match_id ? this.view.check : null;
        if (c) this.set({ check: null });
        if (msg.reason === "player_missed") {
          this.missedByOther = true;
        } else if (msg.reason === "server_error") {
          this.notify("The game could not start.", "You're back in the queue and keep your place.");
        }
        break;
      }
      case "queue_removed": {
        this.clearResync();
        const mine = msg.match_id !== undefined && this.declined === msg.match_id;
        const me = myName();
        const by = msg.by && msg.by !== me ? msg.by : null;
        const next: Partial<QueueView> = {
          queued: false, check: null, pending: null, since: null, botsAt: null, front: false,
          cooldownUntil: msg.cooldown_until !== null ? this.local(msg.cooldown_until) : null,
        };
        if (msg.reason === "missed" || (msg.reason === "declined" && !mine)) {
          next.missed = { reason: msg.reason, by };
        }
        this.set(next);
        if (msg.reason === "away") {
          this.notify(by ? `${by} left the queue while away.` : "You left the queue while away.",
                      "Tap Find a game to queue again; no cooldown.");
        } else if (msg.reason === "in_room" && by) {
          this.notify(`${by} joined a room, so your search ended.`);
        }
        break;
      }
      case "party": {
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
        this.set({ party: null });
        if (msg.reason === "expired") this.notify("Your pair code expired.");
        else if (msg.by && !msg.you) this.notify(`${msg.by} left the pair.`);
        break;
      case "error":
        if (!msg.code || !QUEUE_ERROR_CODES.has(msg.code)) break;
        this.joinSentAt = null;
        if (msg.code === "cooldown") {
          const extra = msg as unknown as { cooldown_until?: number; cooldown_secs?: number };
          if (extra.cooldown_until !== undefined && extra.cooldown_secs !== undefined) {
            this.skew = (extra.cooldown_until - extra.cooldown_secs) * 1000 - now;
          }
          const secs = extra.cooldown_secs ?? 30;
          this.set({ pending: null, cooldownUntil: now + secs * 1000 });
        } else if (msg.code.startsWith("party") || msg.code === "in_queue" || msg.code === "in_party"
                   || msg.code === "not_in_party") {
          this.set({ pending: null, partyError: msg.message });
        } else if (msg.code === "start_failed") {
          // the entry left the queue before the start was tried
          this.set({ pending: null, queued: false, since: null, botsAt: null, front: false });
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
    this.set({ pending: "join", sheet: null, missed: null });
  }

  leave(): void {
    if (this.send({ type: "queue_leave" })) this.set({ pending: "leave" });
  }

  startBots(): void {
    if (this.send({ type: "queue_start_bots" })) this.set({ pending: "bots" });
  }

  accept(): void {
    const c = this.view.check;
    // the server refuses an accept after the deadline
    if (!c || c.mine === "accepted" || Date.now() >= c.deadline) return;
    if (this.send({ type: "match_accept", match_id: c.id })) {
      this.set({ check: { ...c, mine: "accepted" } });
    }
  }

  decline(): void {
    const c = this.view.check;
    if (!c) return;
    this.declined = c.id;
    this.send({ type: "match_decline", match_id: c.id });
    this.set({ check: null });
  }

  keepWaiting(): void {
    const c = this.view.check;
    if (!c) return;
    this.send({ type: "match_decline", match_id: c.id, keep_waiting: true });
    this.set({ check: null });
  }

  dismissMissed(): void {
    this.set({ missed: null });
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
    if (this.noteTimer !== null) window.clearTimeout(this.noteTimer);
    this.noteTimer = null;
    this.view = EMPTY;
    this.skew = 0;
    this.declined = null;
    this.joinSentAt = null;
    this.droppedWhileQueued = false;
    this.missedByOther = false;
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
