// The nearby link on the app's ShengjiNearby plugin (NearbyPlugin.swift). The
// plugin runs one session at a time, a hosted table or a join, and reports it
// through three events: `peer`, `message` and `state`. Outside the app, or in
// a binary that does not register the plugin, there is no native transport.
import { nearbyPluginProxy } from "../../../native";
import { NearbyError, type HostLink, type JoinLink, type LinkState, type NearbyTransport } from "./transport";

interface Listener {
  remove(): Promise<void> | void;
}

interface NearbyPlugin {
  capabilities(): Promise<{ reviewed?: unknown; debug?: unknown; nearbyV?: unknown; serviceType?: unknown }>;
  openSettings(): Promise<unknown>;
  host(opts: { code: string }): Promise<unknown>;
  join(opts: { code: string }): Promise<unknown>;
  send(opts: { peer: string; text: string }): Promise<unknown>;
  close(opts: { peer: string }): Promise<unknown>;
  stop(): Promise<unknown>;
  addListener(event: "peer", fn: (ev: { peer: string; state: string }) => void): Promise<Listener>;
  addListener(event: "message", fn: (ev: { peer: string; text: string }) => void): Promise<Listener>;
  addListener(event: "state", fn: (ev: { state: string; detail?: string }) => void): Promise<Listener>;
}

const STATES: ReadonlySet<string> = new Set(["ready", "waiting", "denied", "wifiOff", "notFound", "failed", "ended"]);
const asState = (s: string): LinkState => (STATES.has(s) ? (s as LinkState) : "failed");

function nearbyPlugin(): NearbyPlugin | null {
  const p = nearbyPluginProxy() as Partial<NearbyPlugin> | null;
  return p && typeof p.host === "function" && typeof p.addListener === "function" ? (p as NearbyPlugin) : null;
}

/** Whether this app binary may run nearby play (flag.ts): it was reviewed
 *  with it, or it is a Debug build compiled for the device test. A shipped
 *  binary reports neither. */
export async function binaryReviewed(): Promise<boolean> {
  const p = nearbyPlugin();
  if (!p) return false;
  try {
    const c = await p.capabilities();
    return c.reviewed === true || c.debug === true;
  } catch {
    return false;
  }
}

/** Opens the app's page in Settings, where Local Network is switched on. */
export function openNearbySettings(): void {
  void nearbyPlugin()?.openSettings().catch(() => {});
}

/** The native transport, or null when the app has no plugin. */
export function nativeTransport(): NearbyTransport | null {
  const p = nearbyPlugin();
  if (!p) return null;
  let listeners: Listener[] = [];
  const unlisten = () => {
    for (const l of listeners) void l.remove();
    listeners = [];
  };
  const fail = (e: unknown): never => {
    unlisten();
    void p.stop().catch(() => {});
    throw e instanceof NearbyError ? e : new NearbyError("failed", String(e));
  };
  return {
    async host(code, handlers): Promise<HostLink> {
      unlisten();
      // the plugin's host() settles once the listener is ready; a denied
      // permission leaves it waiting, so a denial ends the wait instead
      let refuse: ((e: NearbyError) => void) | null = null;
      const refused = new Promise<never>((_, no) => { refuse = no; });
      listeners = await Promise.all([
        p.addListener("peer", (ev) => handlers.peer(ev.peer, ev.state === "connected")),
        p.addListener("message", (ev) => handlers.message(ev.peer, ev.text)),
        p.addListener("state", (ev) => {
          const state = asState(ev.state);
          handlers.state(state, ev.detail);
          if (state === "denied" || state === "wifiOff") refuse?.(new NearbyError(state, ev.detail));
        }),
      ]);
      refused.catch(() => {});
      await Promise.race([p.host({ code }), refused]).catch(fail);
      refuse = null;
      return {
        send: (peer, text) => void p.send({ peer, text }).catch(() => {}),
        close: (peer) => void p.close({ peer }).catch(() => {}),
        stop: () => {
          unlisten();
          void p.stop().catch(() => {});
        },
      };
    },
    async join(code, handlers): Promise<JoinLink> {
      unlisten();
      // the plugin's join() returns at once; the link is up when the host
      // peer connects, and a terminal state ends the attempt
      let open = false;
      let done = false;
      let settle: { ok: () => void; fail: (e: NearbyError) => void } | null = null;
      const linked = new Promise<void>((ok, fail) => { settle = { ok, fail }; });
      const closed = () => {
        if (done) return;
        done = true;
        unlisten();
        if (open) handlers.closed();
        else settle!.fail(new NearbyError("failed", "closed"));
      };
      listeners = await Promise.all([
        p.addListener("peer", (ev) => {
          if (ev.state === "connected" && !open && !done) {
            open = true;
            settle!.ok();
          } else if (ev.state === "disconnected") closed();
        }),
        p.addListener("message", (ev) => { if (open && !done) handlers.message(ev.text); }),
        p.addListener("state", (ev) => {
          const state = asState(ev.state);
          handlers.state(state, ev.detail);
          if (!open && !done && state !== "ready" && state !== "waiting") {
            done = true;
            unlisten();
            settle!.fail(new NearbyError(state, ev.detail));
          }
        }),
      ]);
      await p.join({ code }).catch(fail);
      await linked.catch(fail);
      return {
        send: (text) => void p.send({ peer: "host", text }).catch(() => closed()),
        close: () => {
          void p.stop().catch(() => {});
          closed();
        },
      };
    },
  };
}
