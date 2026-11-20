// Every table code, typed in the Play box or followed as a `?code=` link
// (the older `?room=` and `?party=` links are its aliases), runs one flow
// (PROTOCOL.md "Codes"): a table_peek, whose room_seats answer opens the Join
// panel with a seat chosen for you, then the player's Join. A room's Join
// names its seat (table_join expecting a room); a queued table's is the
// queue's table_join with its code, which the server seats by its own rule.
// A peek's answer carries its code, a refusal too (`peek`), so an answer is
// matched by code and one for a code nobody waits on does nothing.

import { useSyncExternalStore } from "react";
import { CODE_LEN, aliasInviteLink, normalizeCode } from "./codes";
import { nearbyChoices, nearbyDefaultSeat, roomChoices, roomDefaultSeat, tableFull, tableJoinSeat } from "./joinSeats";
import type { RoomSeats, ServerMsg, TableSeats } from "./protocol";
import { queue } from "./queue/store";
import { showToast } from "./toast";
import type { ConnStatus } from "./ws";
import { conn, getResumeToken, getSavedRoom } from "./ws";
import { OFFLINE, setNearbySession, setOffline } from "./offlineMode";
import { noteNearbyAllowed } from "./nearbySession";
import type { LinkState } from "./offline/server/nearby/transport";

/** Where a code came from: the Play box or a link. */
export type CodeFrom = "play" | "link";

/** Where a code's join stands.
 *  - `link`: a `?code=` link waiting for the Play screen (a game may be on).
 *  - `ask`: a link while you sit at another table: App asks whether to leave it.
 *  - `leaving`: Leave was tapped; the link opens once that seat is gone.
 *  - `peek`: table_peek sent; the panel waits for the seats (or, already
 *    showing them, for fresh ones).
 *  - `panel`: the panel shows the seats; Join is the player's.
 *  - `joining`: Join sent; the seat, or a refusal, is on its way. */
export type JoinStep = "link" | "ask" | "leaving" | "peek" | "panel" | "joining";

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

  attach(): void {
    if (this.attached) return;
    this.attached = true;
    // a test may stand in a partial socket
    conn.subscribe?.((m) => this.onMessage(m));
    conn.subscribeStatus?.((s) => this.onStatus(s));
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
    this.view = next;
    for (const fn of this.listeners) fn();
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
    const code = normalizeCode(new URLSearchParams(window.location.search).get("code") ?? "");
    if (code.length !== CODE_LEN || (j && j.from === "play")) return;
    // a link to another table while this device holds a room seat goes back
    // to that seat first and asks before leaving it
    const saved = getSavedRoom()?.toUpperCase() ?? null;
    this.seenSeated = false;
    this.set({ code, from: "link", step: saved !== null && saved !== code ? "ask" : "link",
               peek: null, full: false, seat: null });
  }

  /** Where the Play screen stands: a link opens its panel once you sit
   *  nowhere (asking first when you sit at another table), and an open
   *  panel's job is done once you sit. */
  setPlace(p: Place): void {
    this.place = p;
    const j = this.view;
    if (!j) return;
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
      // a seat taken before the link's Join (the queue's table, back on a
      // fresh page) asks first, as a seat held before it would have
      if (now.from === "link" && now.step !== "joining" && p.seatedAt !== now.code) {
        this.seenSeated = true;
        this.set({ ...now, step: "ask", peek: null, full: false, seat: null });
      } else this.drop();
      return;
    }
    if (now.step === "peek" && !this.asked && p.ready) this.sendPeek(now.code);
  }

  /** The Play box's Join: peek `raw`; false when it is not a whole code or
   *  the socket is not up. */
  open(raw: string): boolean {
    const code = normalizeCode(raw);
    if (code.length !== CODE_LEN || !this.place.ready) return false;
    if (!conn.send({ type: "table_peek", code })) return false;
    this.asked = true;
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
    if (!j || j.step !== "panel" || j.full || !j.peek) return;
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
    if (j && (j.step === "ask" || j.step === "leaving")) {
      // Lobby's next place opens it, with where you sit now
      this.set({ ...j, step: "link" });
    }
  }

  private onMessage(msg: ServerMsg): void {
    const j = this.view;
    if (!j) return;
    if (msg.type === "room_seats") {
      if (msg.room !== j.code || j.step !== "peek") return;
      if (msg.table && msg.closed) {
        // a Join of the host's is in flight: as a table_closed answer
        this.drop();
        return;
      }
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
    this.place = { ready: false, seatedAt: null };
  }
}

export const codes = new CodeStore();
codes.attach();

export function useCodes(): CodeJoin | null {
  return useSyncExternalStore(codes.subscribe, codes.getSnapshot, codes.getSnapshot);
}

/** A nearby code's join, from the code box: look for the table on the
 *  local network, show its seats (the seat picker), then Join. Once seated
 *  the link is the page's socket until the table ends.
 *  - `looking`: the link is being made ("Looking for the table…").
 *  - `panel`: the table's seats are up; Join is the player's.
 *  - `joining`: Join sent; the seat is on its way.
 *  - `notFound`: no table answered the code, after one automatic retry.
 *  - `denied` / `wifiOff`: the link could not be made; the code box says why.
 *  - `full` / `version`: the table answered, and has no seat for this phone. */
export type NearbyStep = "looking" | "panel" | "joining" | "notFound" | "denied" | "wifiOff" | "full" | "version";

export interface NearbyJoin {
  code: string;
  step: NearbyStep;
  peek: RoomSeats | null;
  seat: number | null;
}

/** What the nearby join needs of the page: its socket, the on-device
 *  server's module, offline mode and the app's return to the foreground. */
export interface NearbyJoinDeps {
  conn: Pick<typeof conn, "send" | "subscribe" | "subscribeStatus" | "useNearby" | "leaveNearby" | "leaveToLobby">;
  socketFor(code: string, onState: (state: LinkState) => void): Promise<() => WebSocket>;
  offline(): boolean;
  setOffline(on: boolean): void;
  setSession(on: boolean): void;
  allowed(): void;
  token(): string | null;
  /** Calls `fn` each time the page comes back into view. */
  onVisible(fn: () => void): void;
}

/** After the host is gone this long, its table is over for the joiner: the
 *  same window the host has to come back in (the plugin's hostWindow). */
export const HOST_WINDOW_MS = 60_000;
/** A look that has neither found the table nor been told why by then ends
 *  as not found. */
export const LOOK_LIMIT_MS = 30_000;

export class NearbyJoinStore {
  view: NearbyJoin | null = null;
  /** Seated at the table: the socket is the link, and a drop rejoins by token. */
  seated = false;
  /** The host has been gone past HOST_WINDOW_MS: the end screen is up. */
  hostLeft = false;
  private listeners = new Set<() => void>();
  private deps: NearbyJoinDeps;
  private name = "";
  private live = false;
  private wasOffline = false;
  private retried = false;
  private denied = false;
  private gone: number | null = null;
  private attempt = 0;

  constructor(deps: NearbyJoinDeps) {
    this.deps = deps;
    deps.conn.subscribe((m) => this.onMessage(m));
    deps.conn.subscribeStatus((s) => this.onStatus(s));
    deps.onVisible(() => {
      // back from Settings: the join tries again on its own with the kept code
      if (this.view?.step === "denied") this.look(this.view.code);
    });
  }

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  };

  getSnapshot = (): NearbyJoin | null => this.view;

  private emit(): void {
    this.listeners.forEach((l) => l());
  }

  private set(next: NearbyJoin | null): void {
    this.view = next;
    this.emit();
  }

  /** The code box's Join on a nearby code, under `name`. */
  open(code: string, name: string): void {
    this.name = name;
    this.hostLeft = false;
    this.look(code);
  }

  private look(code: string): void {
    this.retried = false;
    this.denied = false;
    this.set({ code, step: "looking", peek: null, seat: null });
    const attempt = ++this.attempt;
    window.setTimeout(() => {
      if (attempt === this.attempt && this.view?.step === "looking") this.stop("notFound");
    }, LOOK_LIMIT_MS);
    void this.deps.socketFor(code, (s) => this.onLink(attempt, s)).then((make) => {
      if (attempt !== this.attempt || this.view?.step !== "looking") return;
      if (!this.live) {
        this.live = true;
        this.wasOffline = this.deps.offline();
        this.deps.setOffline(true);
        this.deps.setSession(true);
      }
      this.deps.conn.useNearby(make);
    }, () => {
      if (attempt === this.attempt) this.stop("notFound");
    });
  }

  private onLink(attempt: number, state: LinkState): void {
    if (attempt !== this.attempt) return;
    if (this.seated) return;
    const step = this.view?.step;
    if (step !== "looking") return;
    // a denial is final for this attempt: no later not-found replaces its line
    if (state === "denied") {
      this.denied = true;
      this.stop("denied");
    } else if (state === "wifiOff") this.stop("wifiOff");
    else if ((state === "notFound" || state === "failed") && !this.denied) {
      // one miss in a few is the radio: the socket's reconnect looks once more
      if (!this.retried) this.retried = true;
      else this.stop("notFound");
    }
  }

  /** The link attempt ends with `step` on the panel or the code box. */
  private stop(step: NearbyStep): void {
    const v = this.view;
    this.attempt += 1;
    this.endLink();
    if (v) this.set({ ...v, step, peek: step === "full" || step === "version" ? v.peek : null });
  }

  private endLink(): void {
    this.clearGone();
    if (!this.live) return;
    this.live = false;
    this.seated = false;
    this.deps.conn.leaveNearby();
    this.deps.setSession(false);
    this.deps.setOffline(this.wasOffline);
  }

  /** Move the glowing seat to another open seat. */
  pick(seat: number): void {
    const v = this.view;
    if (!v || v.step !== "panel" || !v.peek) return;
    if (!nearbyChoices(v.peek).includes(seat)) return;
    this.set({ ...v, seat });
  }

  /** The panel's Join: the picked seat. */
  join(): void {
    const v = this.view;
    if (!v || v.step !== "panel" || v.seat === null) return;
    if (!this.deps.conn.send({ type: "table_join", code: v.code, name: this.name, seat: v.seat })) return;
    this.set({ ...v, step: "joining" });
  }

  /** Try again after not found: another look, for as long as the first. */
  again(): void {
    const v = this.view;
    if (v && (v.step === "notFound" || v.step === "wifiOff")) this.look(v.code);
  }

  /** Not now, the code box's edit, or the end screen's Leave: the nearby
   *  join is over and the page is back where it was. */
  cancel(): void {
    this.attempt += 1;
    this.hostLeft = false;
    this.endLink();
    this.set(null);
  }

  /** The seated joiner's Leave: the host is told, and the page goes back. */
  leave(): void {
    if (this.seated) this.deps.conn.leaveToLobby();
    this.cancel();
  }

  private clearGone(): void {
    if (this.gone !== null) window.clearTimeout(this.gone);
    this.gone = null;
  }

  private onStatus(s: ConnStatus): void {
    if (!this.live) return;
    if (s !== "open") {
      // a seated joiner's link dropped: the socket keeps looking, by token,
      // for as long as the host may take to come back
      if (this.seated && this.gone === null) {
        this.gone = window.setTimeout(() => {
          this.gone = null;
          this.hostLeft = true;
          this.endLink();
          this.emit();
        }, HOST_WINDOW_MS);
      }
      return;
    }
    if (this.seated) {
      const token = this.deps.token();
      this.deps.conn.send({ type: "table_join", code: this.view?.code ?? this.seatedCode, name: this.name,
                            ...(token ? { token } : {}) });
    } else if (this.view?.step === "looking") {
      this.deps.conn.send({ type: "table_peek", code: this.view.code });
    }
  }

  /** The table's code while seated (the panel's view is gone then). */
  private seatedCode = "";

  private onMessage(m: ServerMsg): void {
    if (!this.live) return;
    const v = this.view;
    if (m.type === "room_seats" && v?.step === "looking" && !m.table) {
      this.deps.allowed();
      if (m.full) {
        this.stop("full");
        this.set({ ...this.view!, peek: m });
        return;
      }
      this.set({ ...v, step: "panel", peek: m, seat: nearbyDefaultSeat(m) });
    } else if ((m.type === "room" || m.type === "state") && (v?.step === "joining" || this.seated)) {
      this.clearGone();
      if (!this.seated) {
        this.seated = true;
        this.seatedCode = v!.code;
        this.set(null);
      }
    } else if (m.type === "error" && m.code === "nearby_version") {
      this.stop("version");
    } else if (m.type === "error" && m.code === "room_full" && v?.step === "joining") {
      this.stop("full");
    } else if (m.type === "left" && this.seated) {
      // the host ended the table, or this Leave was answered
      this.cancel();
    }
  }
}

export const nearbyJoin = new NearbyJoinStore({
  conn,
  async socketFor(code, onState) {
    const m = await import("./offline/server");
    return () => m.nearbyJoinSocket(code, onState) as unknown as WebSocket;
  },
  offline: () => OFFLINE,
  setOffline,
  setSession: setNearbySession,
  allowed: noteNearbyAllowed,
  token: () => getResumeToken(),
  onVisible(fn) {
    if (typeof document === "undefined") return;
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") fn(); });
  },
});

export function useNearbyJoin(): NearbyJoin | null {
  return useSyncExternalStore(nearbyJoin.subscribe, nearbyJoin.getSnapshot, nearbyJoin.getSnapshot);
}

/** The end screen after the host's window passed. */
export function useNearbyHostLeft(): boolean {
  return useSyncExternalStore(nearbyJoin.subscribe, () => nearbyJoin.hostLeft, () => nearbyJoin.hostLeft);
}
