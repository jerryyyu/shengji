// Every table code, typed in the Play box or followed as a `?code=` link
// (the older `?room=` and `?party=` links are its aliases), runs one flow
// (PROTOCOL.md "Codes"): a table_peek, whose room_seats answer opens the Join
// panel with a seat chosen for you, then the player's Join. A room's Join
// names its seat (table_join expecting a room); a queued table's is the
// queue's table_join with its code, which the server seats by its own rule.
// A peek's answer carries its code, a refusal too (`peek`), so an answer is
// matched by code and one for a code nobody waits on does nothing.

import { useSyncExternalStore } from "react";
import { CODE_LEN, HOST_PARAM, aliasInviteLink, isHostToken, normalizeCode, reportInvite } from "./codes";
import { roomChoices, roomDefaultSeat, tableFull, tableJoinSeat } from "./joinSeats";
import type { RoomSeats, ServerMsg, TableSeats } from "./protocol";
import { queue } from "./queue/store";
import { showToast } from "./toast";
import type { ConnStatus } from "./ws";
import { conn, getResumeToken, getSavedName, getSavedRoom } from "./ws";
import { beforeOnlineSetup } from "./deviceAccount";
import { decideIntent, intentToJoin } from "./intent";
import { t, tIn } from "./i18n";

/** Where a code came from: the Play box or a link. */
export type CodeFrom = "play" | "link";

/** Where a code's join stands.
 *  - `link`: a `?code=` link waiting for the Play screen (a game may be on).
 *  - `resume`: the code of the room this device holds a seat at: the seat
 *    comes back by its resume token, with no panel; a refused resume lets a
 *    link go on to its peek.
 *  - `ask`: a link while you sit at another table: App asks whether to leave it.
 *  - `leaving`: Leave was tapped; the link opens once that seat is gone.
 *  - `peek`: table_peek sent; the panel waits for the seats (or, already
 *    showing them, for fresh ones).
 *  - `panel`: the panel shows the seats; Join is the player's.
 *  - `joining`: Join sent; the seat, or a refusal, is on its way. */
export type JoinStep = "link" | "resume" | "ask" | "leaving" | "peek" | "panel" | "joining";

export interface CodeJoin {
  code: string;
  from: CodeFrom;
  step: JoinStep;
  /** The table's seats, once peeked: a room's, or a queued table's. */
  peek: RoomSeats | TableSeats | null;
  /** No seat for a joiner. */
  full: boolean;
  /** The seat Join takes, drawn glowing: in a room the player may move it
   *  to another claimable seat; a queued table's is where its rule seats you. */
  seat: number | null;
}

/** Where the Play screen stands, as Lobby tells the store. */
export interface Place {
  /** The socket is open to the game server (not the on-device one). */
  ready: boolean;
  /** The code of the table you sit at ("" when it has none yet); null when
   *  you sit nowhere. */
  seatedAt: string | null;
}

/** If neither a seat nor a refusal has come back by then, Join wakes up again. */
export const JOIN_TIMEOUT_MS = 15000;
/** A table closed for a moment (its host claiming another seat) is looked
 *  at again this often, at most CLOSED_LOOKS times, while its panel shows. */
export const CLOSED_LOOK_MS = 2000;
export const CLOSED_LOOKS = 15;

/** Drop one query parameter from the address, keeping the rest. */
export function dropParam(name: string): void {
  const params = new URLSearchParams(window.location.search);
  if (!params.has(name)) return;
  params.delete(name);
  const rest = params.toString();
  window.history.replaceState(window.history.state, "",
    `${window.location.pathname}${rest ? `?${rest}` : ""}${window.location.hash}`);
}

/** Whether the panel is up for `j`: a link's panel shows while its seats
 *  come, the Play box's only once they have (a code that names nothing
 *  never opens it). */
export function panelShown(j: CodeJoin | null): j is CodeJoin {
  if (!j) return false;
  if (j.step === "panel" || j.step === "joining") return true;
  return j.step === "peek" && (j.from === "link" || j.peek !== null);
}

export class CodeStore {
  view: CodeJoin | null = null;
  private listeners = new Set<() => void>();
  private attached = false;
  /** The `?code=` link is taken once per page, on the first open socket. */
  private linkTaken = false;
  /** This socket carries the waiting peek; a peek on a closed one is asked again. */
  private asked = false;
  /** During `ask`, whether the seat it asks about has been seen. */
  private seenSeated = false;
  private place: Place = { ready: false, seatedAt: null };
  private timer: number | null = null;
  /** The waiting peek re-reads a panel already showing, on the page's return. */
  private refreshing = false;
  /** The page came back while the lobby was not ready: look once it is. */
  private refreshOwed = false;
  /** The next look at a table closed for a moment, and how many are left. */
  private closedTimer: number | null = null;
  private closedLooks = 0;
  /** This page loaded from an invite link (its sender's token, or null for
   *  a link without one), until its visitor is seated by the link's Join;
   *  undefined when it did not, or once that seat was reported. */
  private landing: string | null | undefined = undefined;

  attach(): void {
    if (this.attached) return;
    this.attached = true;
    // a test may stand in a partial socket
    conn.subscribe?.((m) => this.onMessage(m));
    conn.subscribeStatus?.((s) => this.onStatus(s));
    // a table can end while its panel shows: back on the page, look again
    if (typeof window === "undefined") return;
    window.addEventListener("focus", () => this.refresh());
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") this.refresh();
    });
  }

  /** Peek a showing panel's code again: fresh seats, or, for a table that
   *  ended meanwhile, the panel closes with its one line. */
  refresh(): void {
    const j = this.view;
    if (!j || j.step !== "panel") return;
    if (!this.place.ready) {
      this.refreshOwed = true;
      return;
    }
    this.refreshOwed = false;
    this.refreshing = true;
    this.set({ ...j, step: "peek" });
    this.sendPeek(j.code);
  }

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  };

  getSnapshot = (): CodeJoin | null => this.view;

  private set(next: CodeJoin | null): void {
    if (this.timer !== null && next?.step !== "joining") {
      window.clearTimeout(this.timer);
      this.timer = null;
    }
    if (next?.step !== "peek") this.refreshing = false;
    if (next === null) {
      this.refreshOwed = false;
      this.stopClosedLooks();
    }
    this.view = next;
    for (const fn of this.listeners) fn();
  }

  private stopClosedLooks(): void {
    if (this.closedTimer !== null) window.clearTimeout(this.closedTimer);
    this.closedTimer = null;
    this.closedLooks = 0;
  }

  private patch(next: Partial<CodeJoin>): void {
    if (this.view) this.set({ ...this.view, ...next });
  }

  /** The join is over, joined or not: the link goes with it. */
  private drop(): void {
    if (!this.view) return;
    if (this.view.from === "link") dropParam("code");
    this.set(null);
  }

  private sendPeek(code: string): void {
    this.asked = conn.send({ type: "table_peek", code });
  }

  private onStatus(s: ConnStatus): void {
    const j = this.view;
    if (s !== "open") {
      // the answer, if any, died with the socket
      this.asked = false;
      if (j?.step === "joining") this.patch({ step: "panel" });
      return;
    }
    if (j?.step === "peek" && !this.asked && this.place.ready) this.sendPeek(j.code);
    if (this.linkTaken) return;
    this.linkTaken = true;
    aliasInviteLink();
    const params = new URLSearchParams(window.location.search);
    const code = normalizeCode(params.get("code") ?? "");
    const host = params.get(HOST_PARAM);
    dropParam(HOST_PARAM);
    if (code.length === CODE_LEN) {
      this.landing = isHostToken(host) ? host : null;
      reportInvite("opened", undefined, this.landing);
    }
    if (code.length !== CODE_LEN || (j && j.from === "play")) return;
    // a link to another table while this device holds a room seat goes back
    // to that seat first and asks before leaving it
    // and its own room's link is that seat, which App's resume brings back
    const saved = getSavedRoom()?.toUpperCase() ?? null;
    this.seenSeated = false;
    this.set({ code, from: "link", step: saved === null ? "link" : saved === code ? "resume" : "ask",
               peek: null, full: false, seat: null });
  }

  /** Where the Play screen stands: a link opens its panel once you sit
   *  nowhere (asking first when you sit at another table), and an open
   *  panel's job is done once you sit. */
  setPlace(p: Place): void {
    this.place = p;
    const j = this.view;
    if (!j) return;
    if (j.step === "resume") {
      // the seat is back: your own table's code changes nothing
      if (p.seatedAt === j.code) this.drop();
      return;
    }
    if (j.step === "ask" || j.step === "leaving") {
      if (p.seatedAt !== null) {
        this.seenSeated = true;
        return;
      }
      // a seat left (or never taken: App releases the question) lets the link go on
      if (j.step === "ask" && !this.seenSeated) return;
      this.set({ ...j, step: "link" });
    }
    const now = this.view!;
    if (now.step === "link") {
      if (!p.ready) return;
      if (p.seatedAt !== null) {
        // your own table's link changes nothing; another table's asks first
        if (p.seatedAt === now.code) this.drop();
        else {
          this.seenSeated = true;
          this.set({ ...now, step: "ask" });
        }
        return;
      }
      this.set({ ...now, step: "peek" });
      this.sendPeek(now.code);
      return;
    }
    if (p.seatedAt !== null) {
      if (now.from === "link" && now.step === "joining" && this.landing !== undefined) {
        reportInvite("seated", undefined, this.landing);
        this.landing = undefined;
      }
      // a seat taken before the link's Join (the queue's table, back on a
      // fresh page) asks first, as a seat held before it would have
      if (now.from === "link" && now.step !== "joining" && p.seatedAt !== now.code) {
        this.seenSeated = true;
        this.set({ ...now, step: "ask", peek: null, full: false, seat: null });
      } else this.drop();
      return;
    }
    if (now.step === "peek" && !this.asked && p.ready) this.sendPeek(now.code);
    if (now.step === "panel" && this.refreshOwed && p.ready) this.refresh();
  }

  /** The Play box's Join: peek `raw`; false when it is not a whole code or
   *  the socket is not up. */
  open(raw: string): boolean {
    const code = normalizeCode(raw);
    if (code.length !== CODE_LEN || !this.place.ready) return false;
    // your own table's code changes nothing
    if (code === this.place.seatedAt) return true;
    if (code === getSavedRoom()?.toUpperCase()) {
      // the room this device holds a seat at: the seat comes back, no panel
      const join = intentToJoin(decideIntent({ savedRoom: code, savedName: getSavedName() || "Player",
                                               savedToken: getResumeToken() }));
      if (!join || !conn.send(join)) return false;
      this.set({ code, from: "play", step: "resume", peek: null, full: false, seat: null });
      return true;
    }
    if (!conn.send({ type: "table_peek", code })) return false;
    this.asked = true;
    this.refreshing = false;
    this.set({ code, from: "play", step: "peek", peek: null, full: false, seat: null });
    return true;
  }

  /** Move the glowing seat to another claimable seat of a room. */
  pick(seat: number): void {
    const j = this.view;
    if (!j || j.step !== "panel" || !j.peek || j.peek.table) return;
    if (roomChoices(j.peek).includes(seat)) this.patch({ seat });
  }

  /** The panel's Join, under `name`: a room's chosen seat, or a queued
   *  table by its code. */
  join(name: string): void {
    const j = this.view;
    if (!j || j.step !== "panel") return;
    // held back for the device's sign-in, it joins only the panel still showing
    beforeOnlineSetup(() => this.joinNow(name),
                      () => this.view?.code === j.code && this.view.step === "panel");
  }

  private joinNow(name: string): void {
    const j = this.view;
    if (!j || j.step !== "panel" || j.full || !j.peek || (j.peek.table && j.peek.closed)) return;
    if (j.peek.table) {
      queue.join(j.code, name);
    } else {
      if (j.seat === null) return;
      const token = getResumeToken();
      if (!conn.send({ type: "table_join", code: j.code, name, seat: j.seat, expect: "room",
                       ...(token ? { token } : {}) })) return;
    }
    dropParam("code");
    this.set({ ...j, step: "joining" });
    this.timer = window.setTimeout(() => {
      this.timer = null;
      if (this.view?.step === "joining") this.patch({ step: "panel" });
    }, JOIN_TIMEOUT_MS);
  }

  /** Not now, or Stay: the panel (or the link) goes, and its answer, if one
   *  is on the way, does nothing. */
  cancel(): void {
    this.drop();
  }

  /** App's Leave, asked about a link: the link waits for the seat to go. */
  leaving(): void {
    if (this.view?.step === "ask") this.patch({ step: "leaving" });
  }

  /** The table the link's question was about is gone: the link goes ahead. */
  release(): void {
    const j = this.view;
    if (j?.step === "resume") {
      this.resumeRefused();
      return;
    }
    if (j && (j.step === "ask" || j.step === "leaving")) {
      // Lobby's next place opens it, with where you sit now
      this.set({ ...j, step: "link" });
    }
  }

  /** The seat a `resume` waited for was refused: a link goes on to its
   *  peek (it may name a table you can join); a typed code is done, as App
   *  has said why. */
  resumeRefused(): void {
    const j = this.view;
    if (j?.step !== "resume") return;
    if (j.from === "link") this.set({ ...j, step: "link" });
    else this.drop();
  }

  private onMessage(msg: ServerMsg): void {
    const j = this.view;
    if (!j) return;
    if (j.step === "resume" && (msg.type === "room" || msg.type === "state") && msg.room === j.code) {
      // the seat is back (a game in progress answers with its state alone,
      // and the Table, not the Play screen, shows it): the link is spent
      this.drop();
      return;
    }
    if (msg.type === "room_seats") {
      if (msg.room !== j.code || j.step !== "peek") return;
      const again = this.refreshing;
      this.refreshing = false;
      if (msg.table && msg.closed) {
        if (!again) {
          // a Join of the host's is in flight: as a table_closed answer
          this.drop();
          return;
        }
        // a second look finds the table closed for a moment (its host is
        // claiming another seat): the panel stays, Join waits, and the table
        // is looked at again until it opens
        this.set({ ...j, step: "panel", peek: msg, full: msg.full, seat: null });
        if (this.closedTimer === null && this.closedLooks < CLOSED_LOOKS) {
          this.closedLooks += 1;
          this.closedTimer = window.setTimeout(() => {
            this.closedTimer = null;
            this.refresh();
          }, CLOSED_LOOK_MS);
        }
        return;
      }
      if (msg.table && msg.seats.some((sd) => sd.you)) {
        // your own waiting table: the queue's frame brings you back to it
        this.drop();
        return;
      }
      if (again) this.closedLooks = 0;
      if (msg.table) {
        this.set({ ...j, step: "panel", peek: msg, full: msg.full, seat: msg.full ? null : tableJoinSeat(msg) });
        return;
      }
      const keep = j.seat !== null && roomChoices(msg).includes(j.seat);
      this.set({ ...j, step: "panel", peek: msg, full: tableFull(msg),
                 seat: keep ? j.seat : roomDefaultSeat(msg) });
      return;
    }
    if (msg.type !== "error") return;
    if (msg.peek !== undefined) {
      // the peek's own refusal: the code names nothing (or the limit is reached)
      if (msg.peek !== j.code || j.step !== "peek") return;
      if (this.refreshing) {
        // a second look: a code that names nothing now is a table that ended;
        // any other refusal (the lookup limit) leaves the panel as it was
        if (msg.message === tIn("en", "roundend.srvNoCode")) {
          this.drop();
          showToast(t("roundend.toastGameEnded"));
        } else this.set({ ...j, step: "panel" });
        return;
      }
      this.drop();
      showToast(msg.message);
      return;
    }
    if (j.step !== "joining") return;
    switch (msg.code) {
      case "choose_seat":
      case "seat_unavailable":
        // the seat went between the peek and the Join: look again, and the
        // glow moves to a seat there is
        this.set({ ...j, step: "peek" });
        this.sendPeek(j.code);
        return;
      case "table_full":
        this.set({ ...j, step: "panel", full: true, seat: null });
        return;
      case "room_not_found":
      case "table_not_found":
      case "table_closed":
      case "own_table":
        // the table is gone (App says so) or is your own
        this.drop();
        return;
      default:
        // any other refusal answers the Join: it is the player's again
        this.set({ ...j, step: "panel" });
    }
  }

  /** Test seam: forget everything, as a fresh page would. */
  reset(): void {
    if (this.timer !== null) window.clearTimeout(this.timer);
    this.timer = null;
    this.view = null;
    this.linkTaken = false;
    this.asked = false;
    this.seenSeated = false;
    this.refreshing = false;
    this.refreshOwed = false;
    this.stopClosedLooks();
    this.place = { ready: false, seatedAt: null };
    this.landing = undefined;
  }
}

export const codes = new CodeStore();
codes.attach();

export function useCodes(): CodeJoin | null {
  return useSyncExternalStore(codes.subscribe, codes.getSnapshot, codes.getSnapshot);
}
