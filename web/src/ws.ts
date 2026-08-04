// Small WebSocket connection manager: connect, auto-reconnect with backoff,
// send(msg), subscribers for messages + status. On (re)connect, re-sends
// join_room with the room/name persisted in localStorage so refresh survives.

import type { ClientMsg, ServerMsg } from "./protocol";

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
  private chatLog: any[] = [];
  private chatRoom: string | null = null;

  private ws: WebSocket | null = null;
  private msgListeners = new Set<MsgListener>();
  private statusListeners = new Set<StatusListener>();
  private backoff = 500;
  private reconnectTimer: number | null = null;
  private started = false;

  /** Chat buffered since the last room change. */
  chatHistory(): any[] {
    return this.chatLog.slice();
  }

  /** Drop buffered chat — call when LEAVING a room, so the next room starts
   *  clean. Not called on reconnect: the server replays its own scrollback. */
  clearChat(): void {
    this.chatLog = [];
    this.chatRoom = null;
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
      // Chat scrollback is delivered on join, BEFORE the first state — i.e.
      // before <Table> mounts and subscribes. Buffer it here or a joiner sees
      // an empty log (Codex case 7).
      const room = (msg as any)?.room;
      if (typeof room === "string" && room !== this.chatRoom) {
        this.chatRoom = room;      // room changed: the old log is not ours
        this.chatLog = [];
      }
      if ((msg as any)?.type === "resume" && (msg as any).token) {
        saveResumeToken((msg as any).token as string);
      }
      if ((msg as any)?.type === "chat") {
        this.chatLog.push(msg as any);
        if (this.chatLog.length > 100) this.chatLog.splice(0, this.chatLog.length - 100);
      }
      for (const fn of this.msgListeners) fn(msg);
    };

    ws.onclose = () => {
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
