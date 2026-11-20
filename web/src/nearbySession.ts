// Nearby play on this page, the host's side: whether this page offers it,
// and the table its offline panel's Nearby switch opens. Turning the switch
// on creates a nearby room on the on-device server and advertises it on the
// local network (the first time, iOS asks for Local Network access); turning
// it off, or Leave, ends the room. The joiner's side lives with every other
// code in codeJoin.ts.
import { useSyncExternalStore } from "react";
import { nearbyEnabled } from "./offline/server/nearby/flag";
import { binaryReviewed, openNearbySettings } from "./offline/server/nearby/native";
import type { LinkState } from "./offline/server/nearby/transport";
import { setNearbySession } from "./offlineMode";
import type { ServerMsg } from "./protocol";
import { conn } from "./ws";

/** The host's switch: off (the solo table), starting (the room or its
 *  listener is on its way), on (advertised, the code shown). */
export type HostPhase = "off" | "starting" | "on";

export interface NearbyHostView {
  phase: HostPhase;
  /** The panel's one line after the switch fell back off. */
  line: "denied" | "wifiOff" | null;
}

const ALLOWED_KEY = "shengji.nearbyAllowed";

/** Whether a nearby link has worked on this install, so iOS has granted
 *  Local Network access and the joiner's explaining line is not needed. */
export function nearbyAllowedBefore(): boolean {
  try { return localStorage.getItem(ALLOWED_KEY) === "1"; } catch { return false; }
}

export function noteNearbyAllowed(): void {
  try { localStorage.setItem(ALLOWED_KEY, "1"); } catch { /* storage refused: the line shows again */ }
}

let offered = false;
let checked = false;
const offerListeners = new Set<() => void>();

/** Asks the app binary once whether nearby play may run here. */
export function checkNearbyOffered(): void {
  if (checked) return;
  checked = true;
  void binaryReviewed().then((ok) => {
    const on = nearbyEnabled(ok);
    if (on === offered) return;
    offered = on;
    offerListeners.forEach((l) => l());
  });
}

/** Whether this page offers nearby play: the flag and the binary both allow it. */
export function nearbyOffered(): boolean {
  return nearbyEnabled(offered);
}

export function useNearbyOffered(): boolean {
  checkNearbyOffered();
  return useSyncExternalStore((l) => { offerListeners.add(l); return () => { offerListeners.delete(l); }; },
                              nearbyOffered, nearbyOffered);
}

/** Tests: forget the binary's answer. */
export function resetNearbyOfferedForTests(): void {
  offered = false;
  checked = false;
}

export { openNearbySettings };

type OfflineServer = typeof import("./offline/server");

/** The host's nearby table. An object so a test can drive it. */
export class NearbyHostSession {
  view: NearbyHostView = { phase: "off", line: null };
  private listeners = new Set<() => void>();
  /** The room the switch made, once its room frame named it. */
  private room: string | null = null;
  private server: OfflineServer | null = null;
  private attached = false;
  private load: () => Promise<OfflineServer>;

  constructor(load: () => Promise<OfflineServer> = () => import("./offline/server")) {
    this.load = load;
  }

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  };

  getSnapshot = (): NearbyHostView => this.view;

  private set(next: Partial<NearbyHostView>): void {
    this.view = { ...this.view, ...next };
    this.listeners.forEach((l) => l());
  }

  private attach(): void {
    if (this.attached) return;
    this.attached = true;
    conn.subscribe?.((m) => this.onMessage(m));
  }

  /** The switch on: a nearby room on the on-device server, under `name`. */
  turnOn(name: string): void {
    if (this.view.phase !== "off") return;
    this.attach();
    this.room = null;
    setNearbySession(true);
    this.set({ phase: "starting", line: null });
    if (!conn.send({ type: "create_room", nearby: true, name })) this.fallBack(null);
  }

  /** The switch off, or the host's Leave: the room ends for everyone. */
  turnOff(): void {
    if (this.view.phase === "off") return;
    this.server?.stopNearbyHost();
    this.room = null;
    setNearbySession(false);
    this.set({ phase: "off" });
    conn.leaveToLobby();
  }

  /** The switch falls back off with one line: no room is left behind. */
  private fallBack(line: NearbyHostView["line"]): void {
    this.server?.stopNearbyHost();
    const had = this.room !== null;
    this.room = null;
    setNearbySession(false);
    this.set({ phase: "off", line });
    if (had) conn.leaveToLobby();
  }

  private onMessage(m: ServerMsg): void {
    if (this.view.phase === "off") return;
    if (m.type === "room" && m.nearby && this.room === null) {
      this.room = m.room;
      void this.advertise(m.room);
    } else if (m.type === "left" && this.room !== null) {
      // the table ended (Leave from the game's menu, or the host's own end)
      this.server?.stopNearbyHost();
      this.room = null;
      setNearbySession(false);
      this.set({ phase: "off", line: null });
    }
  }

  private async advertise(code: string): Promise<void> {
    try {
      this.server ??= await this.load();
      await this.server.hostNearby(code, { state: (s) => this.onLink(s) });
      if (this.room !== code) return;
      noteNearbyAllowed();
      this.set({ phase: "on" });
    } catch (e) {
      if (this.room !== code) return;
      const state = (e as { state?: LinkState }).state;
      this.fallBack(state === "denied" ? "denied" : state === "wifiOff" ? "wifiOff" : null);
    }
  }

  private onLink(state: LinkState): void {
    if (this.room === null) return;
    if (state === "denied") this.fallBack("denied");
    else if (state === "ended") this.turnOff();
    else if (state === "ready" && this.view.phase === "starting") {
      noteNearbyAllowed();
      this.set({ phase: "on" });
    }
  }
}

export const nearbyHost = new NearbyHostSession();

export function useNearbyHost(): NearbyHostView {
  return useSyncExternalStore(nearbyHost.subscribe, nearbyHost.getSnapshot, nearbyHost.getSnapshot);
}
