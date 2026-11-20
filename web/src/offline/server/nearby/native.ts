// The nearby link on the app's ShengjiNearby plugin (NearbyPlugin.swift). The
// plugin runs one session at a time, a hosted table or a join, and reports it
// through three events: `peer`, `message` and `state`. Outside the app, or in
// a binary that does not register the plugin, there is no native transport.
import { nearbyPluginProxy } from "../../../native";
import { listenNativeLog, nearbyLog } from "../../../nearbyLog";
import { NearbyError, type HostLink, type JoinLink, type LinkState, type NearbyTransport } from "./transport";

interface Listener {
  remove(): Promise<void> | void;
}

interface NearbyPlugin {
  capabilities(): Promise<{ reviewed?: unknown; debug?: unknown; nearbyV?: unknown; serviceType?: unknown }>;
  openSettings(): Promise<unknown>;
  host(opts: { code: string }): Promise<unknown>;
  join(opts: { code: string; resume?: boolean }): Promise<unknown>;
  send(opts: { peer: string; text: string }): Promise<unknown>;
  close(opts: { peer: string }): Promise<unknown>;
  stop(): Promise<unknown>;
  addListener(event: "peer", fn: (ev: { peer: string; state: string; device?: string; via?: string }) => void): Promise<Listener>;
  addListener(event: "message", fn: (ev: { peer: string; text: string }) => void): Promise<Listener>;
  addListener(event: "state", fn: (ev: { state: string; detail?: string }) => void): Promise<Listener>;
  addListener(event: "debugLog", fn: (ev: { text: string }) => void): Promise<Listener>;
  addListener(event: "path", fn: (ev: { satisfied: boolean }) => void): Promise<Listener>;
}

const STATES: ReadonlySet<string> = new Set(["ready", "waiting", "denied", "wifiOff", "notFound", "failed", "ended", "version"]);
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

/** The plugin runs one session at a time, so each host() or join() takes
 *  this over, across every transport object: a session it replaced hears
 *  no more events and can no longer stop the plugin, which would end the
 *  newer session's link without either end being told. */
let owner = 0;

/** The native transport, or null when the app has no plugin. */
export function nativeTransport(): NearbyTransport | null {
  const p = nearbyPlugin();
  if (!p) return null;
  listenNativeLog(p);
  let listeners: Listener[] = [];
  let mine = 0;
  const current = () => mine === owner;
  const unlisten = () => {
    for (const l of listeners) void l.remove();
    listeners = [];
  };
  /** Stops the plugin only while this object's session is the plugin's. */
  const stopMine = () => {
    if (current()) void p.stop().catch(() => {});
  };
  const fail = (e: unknown): never => {
    unlisten();
    stopMine();
    throw e instanceof NearbyError ? e : new NearbyError("failed", String(e));
  };
  return {
    path(fn) {
      let gone = false;
      let listener: Listener | null = null;
      void p.addListener("path", (ev) => {
        nearbyLog("join", `path ${ev.satisfied ? "satisfied" : "unsatisfied"}`);
        if (!gone) fn(ev.satisfied === true);
      }).then((l) => { if (gone) void l.remove(); else listener = l; }, () => {});
      return () => {
        gone = true;
        void listener?.remove();
      };
    },
    async host(code, handlers): Promise<HostLink> {
      unlisten();
      const me = mine = ++owner;
      const live = () => me === owner;
      // the plugin's host() settles once the listener is ready; a denied
      // permission leaves it waiting, so a denial ends the wait instead
      let refuse: ((e: NearbyError) => void) | null = null;
      const refused = new Promise<never>((_, no) => { refuse = no; });
      listeners = await Promise.all([
        p.addListener("peer", (ev) => {
          if (live()) handlers.peer(ev.peer, ev.state === "connected", typeof ev.device === "string" ? ev.device : undefined);
        }),
        p.addListener("message", (ev) => { if (live()) handlers.message(ev.peer, ev.text); }),
        p.addListener("state", (ev) => {
          if (!live()) return;
          const state = asState(ev.state);
          handlers.state(state, ev.detail);
          if (state === "denied" || state === "wifiOff") refuse?.(new NearbyError(state, ev.detail));
        }),
      ]);
      refused.catch(() => {});
      await Promise.race([p.host({ code }), refused]).catch(fail);
      refuse = null;
      return {
        send: (peer, text) => {
          if (live()) void p.send({ peer, text }).catch((e: unknown) => nearbyLog("host", `send to ${peer} failed: ${String(e)}`));
        },
        close: (peer) => { if (live()) void p.close({ peer }).catch(() => {}); },
        stop: () => {
          unlisten();
          stopMine();
        },
      };
    },
    async join(code, handlers): Promise<JoinLink> {
      unlisten();
      const me = mine = ++owner;
      const live = () => me === owner;
      // the plugin's join() returns at once; the link is up when the host
      // peer connects, and a terminal state ends the attempt
      let open = false;
      let done = false;
      let peerToPeer = false;
      let settle: { ok: () => void; fail: (e: NearbyError) => void } | null = null;
      const linked = new Promise<void>((ok, fail) => { settle = { ok, fail }; });
      const closed = () => {
        if (done) return;
        done = true;
        unlisten();
        // the plugin's join session ends with its link, whichever end closed
        // it, so its screen wake lock does not outlive the table; a session
        // a newer join replaced leaves that one's link alone
        if (live()) void p.stop().catch(() => {});
        if (open) handlers.closed();
        else settle!.fail(new NearbyError("failed", "closed"));
      };
      listeners = await Promise.all([
        p.addListener("peer", (ev) => {
          if (!live()) return;
          if (ev.state === "connected" && !open && !done) {
            open = true;
            peerToPeer = ev.via === "p2p";
            nearbyLog("join", `link up via ${ev.via ?? "?"}`);
            settle!.ok();
          } else if (ev.state === "disconnected") closed();
        }),
        p.addListener("message", (ev) => { if (live() && open && !done) handlers.message(ev.text); }),
        p.addListener("state", (ev) => {
          if (!live()) return;
          const state = asState(ev.state);
          handlers.state(state, ev.detail);
          if (!open && !done && state !== "ready" && state !== "waiting") {
            done = true;
            unlisten();
            settle!.fail(new NearbyError(state, ev.detail));
          }
        }),
      ]);
      // replaced while its listeners were being added: the newer join owns
      // the plugin, so this one never starts
      if (!live()) fail(new NearbyError("failed", "replaced"));
      nearbyLog("join", `attempt (${handlers.resume ? "resume" : "first look"})`);
      await p.join({ code, resume: handlers.resume === true }).catch(fail);
      await linked.catch(fail);
      return {
        peerToPeer,
        send: (text) => {
          if (!live() || done) return;
          void p.send({ peer: "host", text }).catch((e: unknown) => {
            nearbyLog("join", `send failed: ${String(e)}`);
            closed();
          });
        },
        close: () => closed(),
      };
    },
  };
}
