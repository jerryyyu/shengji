// A nearby code's join, the joiner's side of nearby play: loaded only where
// the app binary offers nearby play (nearbyGate.ts), so nothing here runs on
// the web or in an App Store binary. The online code join is codeJoin.ts.
import { useSyncExternalStore } from "react";
import { JOIN_TIMEOUT_MS } from "./codeJoin";
import { nearbyChoices, nearbyDefaultSeat } from "./joinSeats";
import type { RoomSeats, ServerMsg } from "./protocol";
import type { ConnStatus } from "./ws";
import { conn, STALE_CONNECT_MS } from "./ws";
import { OFFLINE, setNearbySession, setOffline } from "./offlineMode";
import { forgetNearbyAllowed, noteNearbyAllowed } from "./nearbySession";
import type { LinkState } from "./offline/server/nearby/transport";
import { nearbyLog } from "./nearbyLog";

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
  /** While looking: the link to the table is up and its seats are on their
   *  way, so the panel's line says it is connecting rather than looking. */
  linked?: boolean;
  seat: number | null;
}

/** What the nearby join needs of the page: its socket, the on-device
 *  server's module, offline mode and the app's return to the foreground. */
export interface NearbyJoinDeps {
  conn: Pick<typeof conn, "send" | "subscribe" | "subscribeStatus" | "useNearby" | "leaveNearby" | "leaveToLobby" | "reconnect"
    | "nearbyLeaveOwed">;
  /** `greet` gives the hello a seated joiner's new link resumes with. */
  socketFor(code: string, onState: (state: LinkState, detail?: string) => void,
            greet: () => Record<string, unknown> | null): Promise<() => WebSocket>;
  /** Calls `fn` with each change of the phone's network path; returns the
   *  unsubscribe. */
  watchPath(fn: (up: boolean) => void): Promise<() => void>;
  offline(): boolean;
  setOffline(on: boolean): void;
  setSession(on: boolean): void;
  allowed(): void;
  /** Local Network access was refused: the explaining line shows again. */
  refused(): void;
  /** Calls `fn` each time the page comes back into view. */
  onVisible(fn: () => void): void;
}

/** After the host is gone this long, its table is over for the joiner: the
 *  window the host has to come back in (the plugin's hostWindow), and a few
 *  seconds more, so a host back at the last moment still finds its joiners. */
export const HOST_WINDOW_MS = 65_000;
/** The host-left window counts this page's awake time in ticks this long. */
const AWAKE_TICK_MS = 1000;

/** `fn` once `ms` of this page's awake time have passed, counted in ticks:
 *  a tick that comes late (the page frozen, or in the background) still
 *  counts as one, so the time the page itself was stopped is left out.
 *  Returns the call that cancels it. */
export function afterAwake(fn: () => void, ms: number): () => void {
  let left = Math.ceil(ms / AWAKE_TICK_MS);
  let id = 0;
  const tick = () => {
    left -= 1;
    if (left <= 0) fn();
    else id = window.setTimeout(tick, AWAKE_TICK_MS);
  };
  id = window.setTimeout(tick, AWAKE_TICK_MS);
  return () => window.clearTimeout(id);
}
/** A look that has neither found the table nor been told why by then ends
 *  as not found. It is held while the system's Local Network prompt is up
 *  (the plugin's "waiting" with "prompt"), and any other "waiting" starts
 *  it over. */
export const LOOK_LIMIT_MS = 30_000;
/** After a Leave, the link waits this long at most for the host's answer
 *  before it closes. */
export const LEAVE_LINK_MS = 3000;
/** A Leave the host has not had yet (tapped while the link was down, or
 *  its link gone before the answer) keeps the link this long at the most
 *  for a new link to carry it: a resume's link up (8 s) and its answer
 *  (up to 20 s on a link that carries), with room for one more try. */
export const LEAVE_OWED_MS = 30_000;
/** The socket's link-state detail for a refused resume (its SEAT_GONE),
 *  spelled here so this module never loads the socket's. */
const SEAT_GONE = "seat_gone";

/** A seat token kept on the phone lets a restarted app take its seat back by
 *  the code: it lasts this long from its last write. */
export const SEAT_KEEP_MS = 2 * 60 * 60 * 1000;
/** At most this many tables' tokens are kept; the oldest goes first. */
export const SEAT_KEEP_MAX = 4;
export const SEATS_KEY = "shengji.nearbySeats";
/** While seated, the kept token's time is written again this often, so a
 *  long game does not outlast it. */
const SEAT_REFRESH_MS = 10 * 60 * 1000;

type KeptSeats = Record<string, { token: string; at: number }>;

/** The kept tokens still within SEAT_KEEP_MS, by table code. A nearby code
 *  is drawn at random for each new table and kept by that table alone, so
 *  the code names the table; a token that reaches another table with the
 *  same code is unknown there, and the join is a newcomer's. */
function keptSeats(): KeptSeats {
  let raw: unknown;
  try { raw = JSON.parse(localStorage.getItem(SEATS_KEY) ?? "{}"); } catch { return {}; }
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return {};
  const now = Date.now();
  const out: KeptSeats = {};
  for (const [code, v] of Object.entries(raw as Record<string, unknown>)) {
    const e = v as { token?: unknown; at?: unknown } | null;
    if (e && typeof e.token === "string" && e.token && typeof e.at === "number" && now - e.at < SEAT_KEEP_MS && e.at <= now) {
      out[code] = { token: e.token, at: e.at };
    }
  }
  return out;
}

function writeSeats(seats: KeptSeats): void {
  try {
    if (Object.keys(seats).length === 0) localStorage.removeItem(SEATS_KEY);
    else localStorage.setItem(SEATS_KEY, JSON.stringify(seats));
  } catch { /* storage refused: a restart joins as a newcomer */ }
}

/** The kept seat token for the table `code`, if one is still fresh. */
export function keptSeatToken(code: string): string | null {
  return keptSeats()[code]?.token ?? null;
}

/** Keep `token` as the seat at the table `code`, in place of any other. */
export function keepSeatToken(code: string, token: string): void {
  const seats = keptSeats();
  seats[code] = { token, at: Date.now() };
  const codes = Object.keys(seats).sort((a, b) => seats[b].at - seats[a].at);
  for (const old of codes.slice(SEAT_KEEP_MAX)) delete seats[old];
  writeSeats(seats);
}

/** The table `code` is over for this phone: its token is not kept. */
export function forgetSeatToken(code: string): void {
  const seats = keptSeats();
  delete seats[code];
  writeSeats(seats);
}

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
  /** Cancels the host-left window while it runs. */
  private gone: (() => void) | null = null;
  private attempt = 0;
  private lookTimer: number | null = null;
  private joinTimer: number | null = null;
  /** A Leave is waiting for the host's answer (the link's close). */
  private leaving: number | null = null;
  /** That Leave's wait has been given LEAVE_OWED_MS for a new link once. */
  private leaveRetried = false;
  /** The seat token. It is also kept on the phone by the table's code
   *  (keepSeatToken) until the table is over for this phone, and is never
   *  sent to the game server or written to the log. */
  private token: string | null = null;
  /** The game at the table is over: its token is no longer kept. */
  private over = false;
  /** Date.now() of the kept token's last write. */
  private keptAt = 0;
  /** The socket's latest status. */
  private status: ConnStatus = "closed";
  /** When the socket's current attempt began (its latest "connecting"). */
  private connectingAt = 0;
  /** Ends the network path watch, while the link is live. */
  private unwatch: (() => void) | null = null;

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
    if (next?.step !== "joining") this.clearJoinTimer();
    if (next?.step !== "looking") this.clearLookTimer();
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
    this.over = false;
    this.retried = false;
    this.denied = false;
    this.set({ code, step: "looking", peek: null, seat: null });
    const attempt = ++this.attempt;
    this.armLook(attempt);
    void this.deps.socketFor(code, (s, detail) => this.onLink(attempt, s, detail), () => this.greeting()).then((make) => {
      if (attempt !== this.attempt || this.view?.step !== "looking") return;
      if (!this.live) {
        this.live = true;
        this.wasOffline = this.deps.offline();
        this.deps.setOffline(true);
        this.deps.setSession(true);
        this.watchPath();
      }
      this.deps.conn.useNearby(make);
    }, () => {
      if (attempt === this.attempt) this.stop("notFound");
    });
  }

  /** The look ends as not found LOOK_LIMIT_MS from now unless it has its answer. */
  private armLook(attempt: number): void {
    this.clearLookTimer();
    this.lookTimer = window.setTimeout(() => {
      this.lookTimer = null;
      if (attempt === this.attempt && this.view?.step === "looking") this.stop("notFound");
    }, LOOK_LIMIT_MS);
  }

  private clearLookTimer(): void {
    if (this.lookTimer !== null) window.clearTimeout(this.lookTimer);
    this.lookTimer = null;
  }

  private clearJoinTimer(): void {
    if (this.joinTimer !== null) window.clearTimeout(this.joinTimer);
    this.joinTimer = null;
  }

  /** The panel's link dropped, or its Join went unanswered: look at the
   *  table again, so the seats shown are the table's now. */
  private lookAgain(): void {
    const v = this.view;
    if (!v) return;
    this.set({ ...v, step: "looking", peek: null });
    this.armLook(this.attempt);
    this.deps.conn.send({ type: "table_peek", code: v.code });
  }

  private onLink(attempt: number, state: LinkState, detail?: string): void {
    if (attempt !== this.attempt) return;
    if (this.seated) {
      // the seat is gone: a Leave waiting for a link has nothing to leave
      if (detail === SEAT_GONE) {
        if (this.leaving === null) this.seatGone();
        else this.cancel();
      }
      return;
    }
    const step = this.view?.step;
    if (step !== "looking") return;
    // a denial is final for this attempt: no later not-found replaces its line
    if (state === "denied") {
      this.denied = true;
      this.deps.refused();
      this.stop("denied");
    } else if (state === "wifiOff") this.stop("wifiOff");
    else if (state === "version") this.stop("version");
    else if (state === "waiting" && detail === "prompt") {
      // the system's Local Network prompt is up: no answer is not a miss
      this.clearLookTimer();
    } else if (state === "waiting") this.armLook(attempt);
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
    this.endLeaving();
    this.token = null;
    this.unwatch?.();
    this.unwatch = null;
    if (!this.live) return;
    this.live = false;
    this.seated = false;
    this.deps.conn.leaveNearby();
    this.deps.setSession(false);
    this.deps.setOffline(this.wasOffline);
  }

  /** The table this join is at, or is looking at. */
  private tableCode(): string | null {
    return this.seated ? this.seatedCode : (this.view?.code ?? null);
  }

  /** Keep this seat's token on the phone, by the table's code. */
  private keepToken(): void {
    const code = this.tableCode();
    if (!code || !this.token || this.over || this.leaving !== null) return;
    keepSeatToken(code, this.token);
    this.keptAt = Date.now();
  }

  /** The table is over for this phone: its kept token goes. */
  private forgetTable(): void {
    const code = this.tableCode();
    if (code) forgetSeatToken(code);
  }

  /** A new link's hello while seated: the seat's resume by its token. */
  private greeting(): Record<string, unknown> | null {
    if (!this.seated) return null;
    return { type: "table_join", code: this.seatedCode, name: this.name, ...(this.token ? { token: this.token } : {}) };
  }

  /** While the link is live: when the phone's network comes back and the
   *  seat is not connected, a fresh attempt starts at once rather than
   *  after the socket's backoff or on a link that went stale with the old
   *  path. An attempt begun within STALE_CONNECT_MS is on the new path
   *  already and is kept, as ws.ts keeps a fresh connect on a wake. */
  private watchPath(): void {
    const live = this.attempt;
    void this.deps.watchPath((up) => {
      nearbyLog("join", `path ${up ? "back" : "down"} (${this.status})`);
      if (up && this.live && this.seated && this.status === "connecting" && Date.now() - this.connectingAt <= STALE_CONNECT_MS) {
        nearbyLog("join", "the attempt under way is fresh: kept");
      } else if (up && this.live && this.seated && this.status !== "open"
                 && (this.leaving === null || this.deps.conn.nearbyLeaveOwed())) {
        nearbyLog("join", "reconnect now: the network is back");
        this.deps.conn.reconnect();
      }
    }).then((unwatch) => {
      if (this.live && this.unwatch === null && this.attempt >= live) this.unwatch = unwatch;
      else unwatch();
    }, () => {});
  }

  /** The host refused the seat's resume: the table no longer knows its
   *  token. It is forgotten, and the code's join starts over with the
   *  table's seats, so the player picks one. */
  private seatGone(): void {
    nearbyLog("join", "resume refused: the seat is gone; the seats again");
    const code = this.seatedCode;
    this.forgetTable();
    this.token = null;
    this.seated = false;
    this.clearGone();
    this.look(code);
  }

  /** Move the glowing seat to another open seat. */
  pick(seat: number): void {
    const v = this.view;
    if (!v || v.step !== "panel" || !v.peek) return;
    if (!nearbyChoices(v.peek).includes(seat)) return;
    this.set({ ...v, seat });
  }

  /** The panel's Join: the picked seat, with the seat token kept for this
   *  table if there is one (after a restart, the seat it held; a token the
   *  table does not know seats the phone as a newcomer). If no seat or
   *  refusal comes back within JOIN_TIMEOUT_MS, the table is looked at again. */
  join(): void {
    const v = this.view;
    if (!v || v.step !== "panel" || v.seat === null) return;
    const kept = keptSeatToken(v.code);
    if (!this.deps.conn.send({ type: "table_join", code: v.code, name: this.name, seat: v.seat, ...(kept ? { token: kept } : {}) })) return;
    nearbyLog("join", `join sent (${kept ? "with" : "no"} token)`);
    this.set({ ...v, step: "joining" });
    this.joinTimer = window.setTimeout(() => {
      this.joinTimer = null;
      if (this.view?.step === "joining" && !this.seated) this.lookAgain();
    }, JOIN_TIMEOUT_MS);
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

  /** The seated joiner's Leave: the host is told, and the link closes once
   *  it has answered (it ends the link), or after LEAVE_LINK_MS. */
  leave(): void {
    this.forgetTable();
    if (this.seated) this.deps.conn.leaveToLobby();
    else this.cancel();
  }

  /** The page has left the table (leaveToLobby's own `left`): the page is
   *  back at once, and the link stays until the host has the leave. */
  private leaveSent(): void {
    if (this.leaving !== null) return;
    this.forgetTable();
    this.clearGone();
    this.hostLeft = false;
    // with the link down the Leave waits for the next link (ws.ts sends it
    // as that link opens)
    this.leaveRetried = this.status !== "open";
    this.leaveBy(this.status === "open" ? LEAVE_LINK_MS : LEAVE_OWED_MS);
    this.set(null);
  }

  /** The link closes `ms` from now unless the host's answer ends it first.
   *  A Leave still unanswered by then on a link that looks open was lost
   *  with a stuck link: a fresh one carries it, once. */
  private leaveBy(ms: number): void {
    this.clearLeaving();
    this.leaving = window.setTimeout(() => {
      this.leaving = null;
      if (this.deps.conn.nearbyLeaveOwed() && !this.leaveRetried) {
        this.leaveRetried = true;
        nearbyLog("join", "leave: no answer from the host; a new link sends it");
        this.leaveBy(LEAVE_OWED_MS);
        this.deps.conn.reconnect();
        return;
      }
      this.cancel();
    }, ms);
  }

  private clearLeaving(): void {
    if (this.leaving !== null) window.clearTimeout(this.leaving);
    this.leaving = null;
  }

  /** The Leave's wait is over, whichever way. */
  private endLeaving(): void {
    this.clearLeaving();
    this.leaveRetried = false;
  }

  private clearGone(): void {
    this.gone?.();
    this.gone = null;
  }

  private onStatus(s: ConnStatus): void {
    this.status = s;
    if (s === "connecting") this.connectingAt = Date.now();
    if (!this.live) return;
    if (this.leaving !== null) {
      if (s === "open") return;
      if (this.deps.conn.nearbyLeaveOwed()) {
        // the link went before the host answered the Leave: the socket's
        // reconnect resumes the seat only to carry the Leave, once more
        if (s === "closed" && !this.leaveRetried) {
          this.leaveRetried = true;
          nearbyLog("join", "leave: the link went before the host answered; the next link sends it");
          this.leaveBy(LEAVE_OWED_MS);
        }
        return;
      }
      // the host answered the Leave by ending the link; the socket's
      // reconnect is dropped with the transport, outside this callback
      window.setTimeout(() => { if (this.leaving !== null) this.cancel(); }, 0);
      return;
    }
    if (s !== "open") {
      // a seated joiner's link dropped: the socket keeps looking, by token,
      // for as long as the host may take to come back
      if (this.seated && this.gone === null) {
        // the page's own time stopped (the background) is not the host's
        this.gone = afterAwake(() => {
          this.gone = null;
          this.forgetTable();
          this.hostLeft = true;
          this.endLink();
          this.emit();
        }, HOST_WINDOW_MS);
      } else if (!this.seated && (this.view?.step === "panel" || this.view?.step === "joining")) {
        // the seats on the panel are from the dropped link: look again once
        // the socket is back
        this.set({ ...this.view, step: "looking", peek: null, linked: false });
        this.armLook(this.attempt);
      } else if (!this.seated && this.view?.step === "looking" && this.view.linked) {
        this.set({ ...this.view, linked: false });
      }
      return;
    }
    if (this.seated) {
      // the new link's hello was the resume (greeting), and it is open only
      // once the host answered it
      nearbyLog("join", "resume: connected");
    } else if (this.view?.step === "looking") {
      this.set({ ...this.view, linked: true });
      this.deps.conn.send({ type: "table_peek", code: this.view.code });
    }
  }

  /** The table's code while seated (the panel's view is gone then). */
  private seatedCode = "";

  private onMessage(m: ServerMsg): void {
    if (!this.live) return;
    const v = this.view;
    if (m.type === "resume") {
      if (m.token) {
        // a token the table did not know comes back as a new seat's: it
        // replaces the kept one
        this.token = m.token;
        this.keepToken();
      }
      return;
    }
    if (this.leaving !== null) return;
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
      if (m.type === "state" && m.round_result?.game_over && !this.over) {
        this.over = true;
        this.forgetTable();
      } else if (Date.now() - this.keptAt > SEAT_REFRESH_MS) this.keepToken();
      if (!this.seated) {
        this.seated = true;
        this.seatedCode = v!.code;
        this.set(null);
      }
    } else if (m.type === "error" && (m.code as string | undefined) === "nearby_version") {
      this.stop("version");
    } else if (m.type === "error" && m.code === "room_full" && v?.step === "joining") {
      this.stop("full");
    } else if (m.type === "left" && this.seated) {
      // the host ended the table: the link ends with it. Any other `left` is
      // this page's own Leave, whose link waits for the host's answer.
      if (m.reason === "host_left") {
        this.forgetTable();
        this.cancel();
      } else this.leaveSent();
    }
  }
}

export const nearbyJoin = new NearbyJoinStore({
  conn,
  async socketFor(code, onState, greet) {
    const m = await import("./offline/server");
    return () => m.nearbyJoinSocket(code, onState, greet) as unknown as WebSocket;
  },
  async watchPath(fn) {
    const m = await import("./offline/server");
    return m.onNearbyPath(fn);
  },
  offline: () => OFFLINE,
  setOffline,
  setSession: setNearbySession,
  allowed: noteNearbyAllowed,
  refused: forgetNearbyAllowed,
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
