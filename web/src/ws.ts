// Small WebSocket connection manager: connect, auto-reconnect with backoff,
// send(msg), subscribers for messages + status. On (re)connect it only reports
// "open"; whether and where to rejoin is decided by App via intent.ts.

import type { ChatMsg, ClientMsg, ServerMsg } from "./protocol";
import { noteServerBuild } from "./reloadGate";
import { noteLink, setStalled, type DropCause } from "./link";

export type ConnStatus = "connecting" | "open" | "closed";

/**
 * Pick the WebSocket URL:
 * - Vite dev server (`npm run dev`): the page is on :5173 but the backend is on
 *   :8000, so target it directly.
 * - Served by the game server itself (production build behind any host/TLS):
 *   connect same-origin, upgrading to wss when the page is https.
 */
function wsUrl(): string {
  if (import.meta.env.DEV) {
    return `ws://${location.hostname}:8000/ws`;
  }
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/ws`;
}

const DEVICE_KEY = "shengji.device";
/** Used when storage refuses: one key for this page's life. */
let memoryDevice: string | null = null;

/** 128 random bits as url-safe base64 without padding: 22 characters. */
function newDeviceKey(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** This device's opaque key, made on first use and kept in storage. The
 *  server uses it to tell two tabs on one device apart from two people. It
 *  identifies a browser, not a person: clearing site data makes a new one. */
export function deviceKey(): string {
  try {
    const saved = localStorage.getItem(DEVICE_KEY);
    if (saved && /^[A-Za-z0-9_-]{22}$/.test(saved)) return saved;
    const made = newDeviceKey();
    localStorage.setItem(DEVICE_KEY, made);
    return made;
  } catch {
    memoryDevice ??= newDeviceKey();
    return memoryDevice;
  }
}

/** The socket URL, with the device key read at each connect. */
export function socketUrl(): string {
  return `${wsUrl()}?heartbeat=1&device=${deviceKey()}`;
}
/** Away from a table, a ping this long after the last pong, answered within
 *  the same time: a lobby socket stays cheap on a phone's battery. */
export const HEARTBEAT_MS = 15_000;
/** At a table, a ping this long after the last pong, and the deadline for its
 *  pong. A socket gone half-open (a phone changing networks, a Wi-Fi drop)
 *  carries nothing and never closes, so this bounds how long a quiet table
 *  can sit on one: TABLE_PING_MS + TABLE_PONG_MS at most. */
export const TABLE_PING_MS = 8000;
export const TABLE_PONG_MS = 6000;
/** Back in view, an open socket must answer a ping this fast: a phone can
 *  suspend a socket without closing it, and its traffic then goes nowhere. */
export const PROBE_MS = 2000;
/** The server answers every table action at once (a state, or an error).
 *  When nothing at all has come back this long after one, a ping goes out,
 *  and the socket is replaced if its pong is not back within ACTION_PONG_MS. */
export const ANSWER_MS = 1500;
export const ACTION_PONG_MS = 3000;
/** A socket still connecting this long is abandoned for a fresh one: a
 *  handshake can hang on a network that has just changed. */
export const CONNECT_MS = 5000;
/** A wake event (back online, back in view) restarts a connect this old. */
export const STALE_CONNECT_MS = 2000;
/** Losing a socket that had been open this long retries at once: one
 *  that worked a moment ago is likely to work again now. */
export const LONG_LIVED_MS = 10_000;
/** The retry delay doubles up to this at a table, where every second is
 *  the table waiting; elsewhere up to RETRY_MAX_MS. */
export const TABLE_RETRY_MAX_MS = 3000;
const RETRY_MAX_MS = 8000;
/** The client messages the server answers with a state or an error. */
const ANSWERED: ReadonlySet<ClientMsg["type"]> = new Set<ClientMsg["type"]>([
  "play", "bury", "declare", "pass_declare", "next_round", "im_back",
  "table_chat", "table_allow_joiners",
]);
/** The longest wait between a nearby link's reconnect attempts. */
export const NEARBY_BACKOFF_MAX_MS = 2000;

// Offline mode is decided in its own module, so components can read it
// where a test stands in for this one.
import { NEARBY_SESSION, OFFLINE } from "./offlineMode";
export { OFFLINE };

/** Whether this page may remember its seat in storage: only for the game
 *  server. A table on this device or a nearby phone's is never written down,
 *  so a later launch with a network never sends its code or token to the
 *  game server. */
function remembersSeats(): boolean {
  return !OFFLINE && !NEARBY_SESSION;
}

const NAME_KEY = "shengji.name";
const ROOM_KEY = "shengji.room";
const TOKEN_KEY = "shengji.token";   // opaque seat identity, per room
/** How long leaveToLobby() waits for the server's "left" before retiring the socket. */
const LEAVE_ACK_MS = 5000;

export function getSavedName(): string {
  return localStorage.getItem(NAME_KEY) ?? "";
}
export function saveName(name: string): void {
  localStorage.setItem(NAME_KEY, name);
}
export function getSavedRoom(): string | null {
  return localStorage.getItem(ROOM_KEY);
}
export function saveRoom(room: string): void {
  if (remembersSeats()) localStorage.setItem(ROOM_KEY, room);
}
export function clearSavedRoom(): void {
  localStorage.removeItem(ROOM_KEY);
  localStorage.removeItem(TOKEN_KEY);
}

/** Opaque resume token for our seat. Names are NOT identity: two players
 *  called "jerry", or one player on two devices, must not be able to seize
 *  each other's seat, and a returning player must be able to resume even
 *  while a stale socket of theirs is still open. */
export function getResumeToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function saveResumeToken(token: string): void {
  if (remembersSeats()) localStorage.setItem(TOKEN_KEY, token);
}

type MsgListener = (msg: ServerMsg) => void;
type StatusListener = (status: ConnStatus) => void;

class Connection {
  status: ConnStatus = "closed";

  /** Chat received so far, including lines that arrived before the table
   *  mounted. Cleared on room change, NOT on reconnect (the server replays
   *  scrollback and duplicates would double up). */
  private chatLog: ChatMsg[] = [];
  private chatRoom: string | null = null;
  private chatSeen = new Set<number>();
  /** Bumped on every socket open. A membership transaction (peek -> pick ->
   *  join) belongs to ONE generation; a response that arrives after a
   *  reconnect refers to a socket the server no longer has, so acting on it
   *  would join the wrong room. */
  generation = 0;

  private ws: WebSocket | null = null;
  private msgListeners = new Set<MsgListener>();
  private statusListeners = new Set<StatusListener>();
  /** The socket a leaveToLobby() is waiting on: until the server confirms
   *  with {type:"left"}, messages already in flight on it belong to the room
   *  we just left and must not pull the UI back into it. */
  private leavingWs: WebSocket | null = null;
  private leaveTimer: number | null = null;
  private backoff = 500;
  private reconnectTimer: number | null = null;
  private started = false;
  /** Opens the transport: the game server's WebSocket, or offline the
   *  in-page server's look-alike (set once its module has loaded). */
  private makeSocket: () => WebSocket = () => new WebSocket(socketUrl());
  /** Which server the socket talks to. "local" is set as soon as offline play
   *  is asked for, while the on-device server's module may still be loading;
   *  browser wake events never open the network socket then. */
  private transport: "remote" | "local" | "nearby" = "remote";
  /** The transport a nearby join replaced, which its end goes back to. */
  private beforeNearby: "remote" | "local" = "remote";
  /** Bumped on every transport request, so a module load that finishes after
   *  a later request changes nothing. */
  private transportSeq = 0;
  /** A socket has been opened on this page: a swap after that ends its room. */
  private opened = false;
  private stopHeartbeat: (() => void) | null = null;
  /** Removes the wake listeners start() added. */
  private unlisten: (() => void) | null = null;
  /** Ping now with a short deadline (the socket's heartbeat, if it has one). */
  private probe: (() => void) | null = null;
  /** Starts the wait for the server's answer to an action just sent. */
  private awaitAnswer: (() => void) | null = null;
  /** Re-times the next ping when the cadence changes. */
  private retime: (() => void) | null = null;
  /** A game's state has come since the last "left": the table cadence. Kept
   *  across a reconnect, because the table stays on screen while its seat is
   *  asked back. */
  private atTable = false;
  /** When the current socket opened; null while it connects. */
  private openedAt: number | null = null;
  /** When the current socket started connecting. */
  private connectAt = 0;
  /** When the last open socket was lost; null once a new one opens. */
  private lostAt: number | null = null;
  /** The next reconnect is deliberate (a sign-in or sign-out): open it at
   *  once instead of after the failure backoff. */
  private immediate = false;

  /** Chat buffered since the last room change. */
  chatHistory(): ChatMsg[] {
    return this.chatLog.slice();
  }

  /** Drop buffered chat — call when LEAVING a room, so the next room starts
   *  clean. Not called on reconnect: the server replays its own scrollback. */
  clearChat(): void {
    this.chatLog = [];
    this.chatRoom = null;
    this.chatSeen.clear();
  }

  /** Idempotent: begin connecting (called once from App). */
  start(): void {
    if (this.started) return;
    this.started = true;
    // A browser wake can end an outage before the retry timer expires.
    // Preserve healthy sockets and handshakes that are already in progress.
    // The on-device server has no outages to end.
    // A connect started before the wake may be stuck on the old network.
    const wake = () => {
      if (this.transport !== "remote") return;
      if (this.status === "closed"
          || (this.status === "connecting" && Date.now() - this.connectAt > STALE_CONNECT_MS)) {
        this.reconnect();
      }
    };
    // Back in view, or onto a new network with no offline moment between
    // (Wi-Fi to cellular): an open socket must prove it still carries.
    const check = () => {
      if (this.status === "open") this.probe?.();
      else wake();
    };
    const visible = () => {
      if (document.visibilityState === "visible") check();
    };
    window.addEventListener("online", check);
    window.addEventListener("pageshow", wake);
    document.addEventListener("visibilitychange", visible);
    this.unlisten = () => {
      window.removeEventListener("online", check);
      window.removeEventListener("pageshow", wake);
      document.removeEventListener("visibilitychange", visible);
    };
    if (OFFLINE) void this.useLocalServer().catch(() => {});
    else this.open();
  }

  /** Undo start(). The page never calls it; a test that started the
   *  connection ends it here, because the on-device socket runs on the host's
   *  own timers, which outlive the test's DOM. The socket closes with its
   *  handlers cut, and no reconnect, heartbeat, leave or transport load still
   *  pending opens another. */
  stop(): void {
    if (!this.started) return;
    this.started = false;
    this.transportSeq += 1;
    this.unlisten?.();
    this.unlisten = null;
    this.cutSocket();
    this.transport = "remote";
    this.makeSocket = () => new WebSocket(socketUrl());
    this.setStatus("closed");
  }

  /** Play on the on-device server from now on, in place: the game server's
   *  socket is cut at once, the in-page server's module loads (it is not in
   *  the online bundle), and its socket opens. If the module cannot load, the
   *  game server's socket opens again and the promise rejects. */
  async useLocalServer(): Promise<void> {
    const seq = ++this.transportSeq;
    if (this.transport === "local") return;
    this.transport = "local";
    this.retireTransport();
    let m: typeof import("./offline/server");
    try {
      m = await import("./offline/server");
    } catch (e) {
      if (seq === this.transportSeq) this.useGameServer();
      throw e;
    }
    if (seq !== this.transportSeq) return;
    this.makeSocket = () => new m.LocalSocket() as unknown as WebSocket;
    if (this.started) this.open();
  }

  /** Play at a nearby phone's table from now on, in place: `make` opens the
   *  link to it (a NearbySocket). Reconnects open a new link the same way,
   *  until `leaveNearby` goes back to the transport this replaced. */
  useNearby(make: () => WebSocket): void {
    this.transportSeq += 1;
    if (this.transport !== "nearby") this.beforeNearby = this.transport;
    this.transport = "nearby";
    this.retireTransport();
    this.makeSocket = make;
    if (this.started) this.open();
  }

  /** The nearby table is over for this page: back to the transport it replaced. */
  leaveNearby(): void {
    if (this.transport !== "nearby") return;
    if (this.beforeNearby === "local") {
      this.transport = "remote";
      void this.useLocalServer().catch(() => {});
    } else {
      this.transport = "local";
      this.useGameServer();
    }
  }

  /** Back to the game server, in place. */
  useGameServer(): void {
    this.transportSeq += 1;
    if (this.transport === "remote") return;
    this.transport = "remote";
    this.retireTransport();
    this.makeSocket = () => new WebSocket(socketUrl());
    if (this.started) this.open();
  }

  /** End the current transport so nothing crosses to the next one: the
   *  socket's handlers are cut before it closes, a pending leave, probe or
   *  reconnect is dropped, and the room it held is forgotten (the other
   *  server has never heard of it), so listeners get {type:"left"} as from
   *  a leave. The next socket opens as a fresh page's would. */
  private retireTransport(): void {
    this.cutSocket();
    this.backoff = 500;
    this.immediate = false;
    if (this.opened) {
      clearSavedRoom();
      this.clearChat();
      this.emit({ type: "left" });
    }
    this.setStatus("connecting");
  }

  /** Close the socket with its handlers cut first, and drop its heartbeat,
   *  probe, pending leave and reconnect timer. */
  private cutSocket(): void {
    this.stopHeartbeat?.();
    this.stopHeartbeat = null;
    this.probe = null;
    this.awaitAnswer = null;
    this.retime = null;
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.endLeave();
    const old = this.ws;
    this.ws = null;
    if (old) {
      old.onopen = null;
      old.onmessage = null;
      old.onclose = null;
      old.onerror = null;
      try { old.close(); } catch { /* already closed */ }
    }
  }

  /** Sends when the socket is open; returns whether it did, so a caller can
   *  confirm an action (a haptic, a pending state) only for a real send. */
  send(msg: ClientMsg): boolean {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
      if (ANSWERED.has(msg.type)) this.awaitAnswer?.();
      return true;
    }
    return false;
  }

  /** Leave the current room and go straight back to the lobby, keeping this
   *  socket. The saved room is forgotten, the server is told (table_leave
   *  frees the seat exactly like a disconnect), and listeners get the same {type:"left"}
   *  the server will send, so the UI resets now instead of a round trip later.
   *  If the socket is not open there is nothing to tell the server: the seat
   *  was already dropped, and with the saved room gone a reconnect will not
   *  resume it. */
  leaveToLobby(): void {
    clearSavedRoom();
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      const ws = this.ws;
      ws.send(JSON.stringify({ type: "table_leave" } satisfies ClientMsg));
      this.leavingWs = ws;
      // Fail-safe: no confirmation means no barrier can be lifted safely, so
      // give up on this socket rather than swallow the next room's replies.
      if (this.leaveTimer !== null) window.clearTimeout(this.leaveTimer);
      this.leaveTimer = window.setTimeout(() => {
        this.leaveTimer = null;
        if (this.leavingWs === ws) this.retire(ws);
      }, LEAVE_ACK_MS);
    }
    this.clearChat();
    this.emit({ type: "left" });
  }

  /** Replace the socket: the server reads who we are (the session cookie)
   *  only on the handshake, so after a sign-in or sign-out the identity
   *  moves to the connection by opening a new one. Everything else is the
   *  ordinary reconnect path: App decides from the saved room and resume
   *  token whether to rejoin, and a seat mid-game is reclaimed by its
   *  token, so the player keeps it. Safe to call in any state. */
  reconnect(): void {
    this.replace("replaced");
  }

  /** Give up the current socket (or connect) and open a new one at once. */
  private replace(cause: DropCause): void {
    if (!this.started) return;
    this.immediate = true;
    this.stopHeartbeat?.();
    const ws = this.ws;
    if (ws) {
      this.lose(cause);
      ws.close();     // onclose -> scheduleReconnect (immediately, see above)
      if (this.ws === ws) {   // a fake or half-open socket that never fired onclose
        this.ws = null;
        this.setStatus("closed");
        this.scheduleReconnect();
      }
    } else if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
      this.scheduleReconnect();
    }
  }

  /** The current socket is being given up: if it had opened, say so, and
   *  retry at once when it had been working for a while. */
  private lose(cause: DropCause): void {
    setStalled(false);
    const opened = this.openedAt;
    this.openedAt = null;
    if (opened === null) return;
    if (Date.now() - opened > LONG_LIVED_MS) this.immediate = true;
    this.lostAt ??= Date.now();
    noteLink({ kind: "down", cause });
  }

  private endLeave(): void {
    this.leavingWs = null;
    if (this.leaveTimer !== null) window.clearTimeout(this.leaveTimer);
    this.leaveTimer = null;
  }

  /** Abandon a socket whose remaining traffic cannot be trusted: everything
   *  still in flight on it dies with it, and the normal reconnect opens a
   *  clean one (the saved room is already cleared, so nothing is resumed). */
  private retire(ws: WebSocket): void {
    this.endLeave();
    ws.onmessage = null;   // nothing more from it reaches the UI
    ws.close();
  }

  private emit(msg: ServerMsg): void {
    const atTable = msg.type === "state" ? true : msg.type === "left" ? false : this.atTable;
    if (atTable !== this.atTable) {
      this.atTable = atTable;
      this.retime?.();
    }
    for (const fn of this.msgListeners) fn(msg);
  }

  subscribe(fn: MsgListener): () => void {
    this.msgListeners.add(fn);
    return () => {
      this.msgListeners.delete(fn);
    };
  }

  subscribeStatus(fn: StatusListener): () => void {
    this.statusListeners.add(fn);
    fn(this.status);
    return () => {
      this.statusListeners.delete(fn);
    };
  }

  private open(): void {
    this.opened = true;
    this.setStatus("connecting");
    const ws = this.makeSocket();
    this.ws = ws;
    this.openedAt = null;
    this.connectAt = Date.now();
    let connectTimer: number | null = window.setTimeout(() => {
      connectTimer = null;
      if (this.ws === ws && this.openedAt === null) {
        // never opened: cut it, so a late open or close changes nothing
        ws.onopen = null;
        ws.onmessage = null;
        ws.onclose = null;
        ws.onerror = null;
        try { ws.close(); } catch { /* already closed */ }
        this.ws = null;
        stop();
        this.setStatus("closed");
        this.scheduleReconnect();
      }
    }, CONNECT_MS);
    // One ping in flight at a time. `timer` is the next ping's, or the
    // deadline of the one in flight; `answer` waits for the server to answer
    // an action.
    let timer: number | null = null;
    let deadlineAt = 0;
    let answer: number | null = null;
    let nonce = 0;
    let awaiting: number | null = null;
    let enabled = false;
    const stop = () => {
      if (timer !== null) window.clearTimeout(timer);
      timer = null;
      if (answer !== null) window.clearTimeout(answer);
      answer = null;
      if (connectTimer !== null) window.clearTimeout(connectTimer);
      connectTimer = null;
    };
    this.stopHeartbeat = stop;
    const expire = (ms: number) => {
      if (timer !== null) window.clearTimeout(timer);
      deadlineAt = Date.now() + ms;
      timer = window.setTimeout(() => {
        timer = null;
        if (this.ws === ws && awaiting !== null) this.replace("no_pong");
      }, ms);
    };
    /** Ping, and replace the socket if no pong is back within `deadline`. A
     *  ping already in flight is not doubled: its deadline only moves closer. */
    const ping = (deadline: number) => {
      if (!enabled || this.ws !== ws || ws.readyState !== WebSocket.OPEN) return;
      if (awaiting !== null) {
        if (deadlineAt - Date.now() > deadline) expire(deadline);
        return;
      }
      awaiting = ++nonce;
      try {
        ws.send(JSON.stringify({ type: "ping", nonce: awaiting } satisfies ClientMsg));
      } catch {
        this.replace("closed");
        return;
      }
      expire(deadline);
    };
    const schedulePing = () => {
      if (timer !== null) window.clearTimeout(timer);
      const [every, deadline] = this.atTable
        ? [TABLE_PING_MS, TABLE_PONG_MS] : [HEARTBEAT_MS, HEARTBEAT_MS];
      timer = window.setTimeout(() => {
        timer = null;
        ping(deadline);
      }, every);
    };

    this.probe = () => ping(PROBE_MS);
    this.awaitAnswer = () => {
      if (!enabled || this.ws !== ws || answer !== null) return;
      answer = window.setTimeout(() => {
        answer = null;
        setStalled(true);
        ping(ACTION_PONG_MS);
      }, ANSWER_MS);
    };
    this.retime = () => {
      if (enabled && this.ws === ws && awaiting === null) schedulePing();
    };

    ws.onopen = () => {
      if (this.ws !== ws) return;
      if (connectTimer !== null) window.clearTimeout(connectTimer);
      connectTimer = null;
      this.backoff = 500;
      this.generation += 1;
      this.openedAt = Date.now();
      if (this.lostAt !== null) {
        noteLink({ kind: "up", ms: Date.now() - this.lostAt });
        this.lostAt = null;
      }
      // Report "open" and stop there. Deciding WHETHER to rejoin, and which
      // room wins between an invite link, an explicit action, and a saved
      // session, is App's call (intent.ts); reading localStorage here would
      // race the invite flow.
      this.setStatus("open");
    };

    ws.onmessage = (ev: MessageEvent) => {
      if (this.ws !== ws) return;   // a socket we closed or replaced
      // Anything at all from the server answers the action just sent.
      if (answer !== null) { window.clearTimeout(answer); answer = null; }
      setStalled(false);
      let msg: ServerMsg;
      try {
        msg = JSON.parse(ev.data as string) as ServerMsg;
      } catch {
        return;
      }
      // Negotiate before sending probes so an older server never receives
      // unknown actions. Heartbeats are transport-only, not game messages.
      if (msg.type === "heartbeat_ready") {
        if (!enabled) { enabled = true; schedulePing(); }
        noteServerBuild(msg.build);
        return;
      }
      if (msg.type === "pong") {
        if (awaiting !== null && msg.nonce === awaiting) {
          awaiting = null;
          schedulePing();
        }
        return;
      }
      if (this.leavingWs === ws) {
        // Already reset locally by leaveToLobby(): drop whatever the room
        // sent before the server processed our table_leave. Only "left" is
        // causally tied to it (server.py answers a room's leave with "left" once
        // the seat is detached), so only "left" reopens the socket. Errors
        // carry no request id: one may be a late reply to an old action, with
        // more old-room state behind it, or the server refusing the leave
        // (stale_connection / no room). Neither is safe to read as the end of
        // the old room, so an error retires the socket instead; a close, or
        // the timeout above, ends the wait the same way.
        if (msg.type === "left") this.endLeave();
        else if (msg.type === "error") this.retire(ws);
        return;
      }
      // Chat arrives BEFORE the first state — i.e. before <Table> mounts and
      // subscribes — so it is buffered here. The server sends one
      // authoritative chat_history snapshot per attach, then live events with
      // room-scoped monotonic ids, which is what makes reconnect
      // deduplication possible.
      const room = "room" in msg ? msg.room : undefined;
      if (typeof room === "string" && room !== this.chatRoom) {
        this.chatRoom = room;      // room changed: the old log is not ours
        this.chatLog = [];
        this.chatSeen.clear();
      }
      switch (msg.type) {
        case "resume":
          if (msg.token && this.transport === "remote") saveResumeToken(msg.token);
          break;
        case "chat_history":
          this.chatLog = msg.messages.slice(-100);   // REPLACE, never merge
          this.chatSeen = new Set(this.chatLog.map((x) => x.id));
          break;
        case "chat":
          if (!this.chatSeen.has(msg.id)) {
            this.chatSeen.add(msg.id);
            this.chatLog.push(msg);
            if (this.chatLog.length > 100) {
              this.chatLog.splice(0, this.chatLog.length - 100);
            }
          }
          break;
        default:
          break;
      }
      this.emit(msg);
    };

    ws.onclose = () => {
      stop();
      if (this.leavingWs === ws) this.endLeave();
      if (this.ws !== ws) return;
      this.lose("closed");
      this.ws = null;
      this.setStatus("closed");
      this.scheduleReconnect();
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) return;
    const delay = this.immediate ? 0 : this.backoff;
    this.immediate = false;
    // a nearby seat has the host's window (about a minute) to get back in:
    // its attempts stay close together through it
    this.backoff = Math.min(this.backoff * 2,
      this.transport === "nearby" ? NEARBY_BACKOFF_MAX_MS : this.atTable ? TABLE_RETRY_MAX_MS : RETRY_MAX_MS);
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.open();
    }, delay);
  }

  private setStatus(status: ConnStatus): void {
    this.status = status;
    for (const fn of this.statusListeners) fn(status);
  }
}

export const conn = new Connection();
