// Small WebSocket connection manager: connect, auto-reconnect with backoff,
// send(msg), subscribers for messages + status. On (re)connect, re-sends
// join_room with the room/name persisted in localStorage so refresh survives.

import type { ChatMsg, ClientMsg, ServerMsg } from "./protocol";

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

const WS_URL = wsUrl();

const NAME_KEY = "shengji.name";
const ROOM_KEY = "shengji.room";
const TOKEN_KEY = "shengji.token";   // opaque seat identity, per room

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
  localStorage.setItem(ROOM_KEY, room);
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
  localStorage.setItem(TOKEN_KEY, token);
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
   *  would join the wrong room (Codex ship gate P0-6). */
  generation = 0;

  private ws: WebSocket | null = null;
  private msgListeners = new Set<MsgListener>();
  private statusListeners = new Set<StatusListener>();
  /** The socket a leaveToLobby() is waiting on: until the server confirms
   *  with {type:"left"}, room-scoped messages already in flight on it belong
   *  to the room we just left and must not pull the UI back into it. */
  private leavingWs: WebSocket | null = null;
  private backoff = 500;
  private reconnectTimer: number | null = null;
  private started = false;

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
    this.open();
  }

  send(msg: ClientMsg): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  /** Leave the current room and go straight back to the lobby, keeping this
   *  socket. Replaces the old full-page reload after a finished game: the
   *  saved room is forgotten, the server is told (leave_room frees the seat
   *  exactly like a disconnect did), and listeners get the same {type:"left"}
   *  the server will send, so the UI resets now instead of a round trip later.
   *  If the socket is not open there is nothing to tell the server: the seat
   *  was already dropped, and with the saved room gone a reconnect will not
   *  resume it. */
  leaveToLobby(): void {
    clearSavedRoom();
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "leave_room" } satisfies ClientMsg));
      this.leavingWs = this.ws;
    }
    this.clearChat();
    this.emit({ type: "left" });
  }

  private emit(msg: ServerMsg): void {
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
    this.setStatus("connecting");
    const ws = new WebSocket(WS_URL);
    this.ws = ws;

    ws.onopen = () => {
      this.backoff = 500;
      this.generation += 1;
      // Report "open" and stop there. Deciding WHETHER to rejoin, and which
      // room wins between an invite link, an explicit action, and a saved
      // session, is App's call — the connection reading localStorage on its
      // own raced the invite flow (Codex, 2026-08-03).
      this.setStatus("open");
    };

    ws.onmessage = (ev: MessageEvent) => {
      let msg: ServerMsg;
      try {
        msg = JSON.parse(ev.data as string) as ServerMsg;
      } catch {
        return;
      }
      if (this.leavingWs === ws) {
        // Already reset locally by leaveToLobby(): drop whatever the room
        // sent before the server processed our leave_room. The server always
        // answers it with "left" (or an error, or by closing the socket), and
        // any of those ends the wait, so this can never swallow the reply to
        // the user's next create/join.
        if (msg.type === "left" || msg.type === "error") this.leavingWs = null;
        return;
      }
      // Chat arrives BEFORE the first state — i.e. before <Table> mounts and
      // subscribes — so it is buffered here. The server sends one
      // authoritative chat_history snapshot per attach, then live events with
      // room-scoped monotonic ids, which is what makes reconnect
      // deduplication possible (Codex ship gate P0-5).
      const room = "room" in msg ? msg.room : undefined;
      if (typeof room === "string" && room !== this.chatRoom) {
        this.chatRoom = room;      // room changed: the old log is not ours
        this.chatLog = [];
        this.chatSeen.clear();
      }
      switch (msg.type) {
        case "resume":
          if (msg.token) saveResumeToken(msg.token);
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
      if (this.leavingWs === ws) this.leavingWs = null;
      if (this.ws !== ws) return;
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
    const delay = this.backoff;
    this.backoff = Math.min(this.backoff * 2, 8000);
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
