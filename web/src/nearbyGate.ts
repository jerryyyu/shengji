// Whether this page offers nearby play, decided at run time. The live site
// and the bundled page carry the same code; nearby play shows only where the
// app binary registers the ShengjiNearby plugin and its `capabilities()`
// enable it (flag.ts). Until that answer is in, and wherever it is no (a
// browser, an App Store binary, a binary whose plugin is not enabled),
// nothing nearby renders and none of its modules load: the one plugin call
// is `capabilities()`, made only where the plugin is registered. Once it is
// yes, the nearby UI (nearbyUi.tsx) is imported, and components draw its
// parts. The soak's log file (with its upload) runs wherever the plugin
// reports `logFile` (the device test and the Beta), whatever the menu shows;
// the ⋯ menu's log and soak rows need `debug`, or `chaos` with the hidden
// switch (nearbyDebug.tsx).
import { createElement, useSyncExternalStore } from "react";
import { nearbyPluginProxy, pluginAvailable } from "./native";
import { nearbyEnabled, type NearbyCapabilities } from "./offline/server/nearby/flag";
import type { NearbyJoin } from "./nearbyJoin";
import type { NearbyHostView } from "./nearbySession";

export type NearbyUi = typeof import("./nearbyUi");

/** What the binary allows: nearby play, the device test's Debug tools, the
 *  soak's log file, and the soak's chaos faults. */
export interface NearbyGate {
  on: boolean;
  debug: boolean;
  logFile: boolean;
  chaos: boolean;
}

const OFF: NearbyGate = { on: false, debug: false, logFile: false, chaos: false };

let gate: NearbyGate = OFF;
let ui: NearbyUi | null = null;
let asked = false;
let load: () => Promise<NearbyUi> = () => import("./nearbyUi");
const listeners = new Set<() => void>();

function emit(): void {
  for (const l of [...listeners]) l();
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => { listeners.delete(l); };
}

/** The gate for these capabilities. */
export function gateFor(c: NearbyCapabilities | null): NearbyGate {
  const on = nearbyEnabled(c);
  return { on, debug: on && c?.debug === true, logFile: on && c?.logFile === true, chaos: on && c?.chaos === true };
}

async function probe(): Promise<NearbyGate> {
  try {
    if (!pluginAvailable("ShengjiNearby")) return OFF;
    const p = nearbyPluginProxy() as { capabilities?: () => Promise<NearbyCapabilities> } | null;
    if (!p || typeof p.capabilities !== "function") return OFF;
    return gateFor(await p.capabilities());
  } catch {
    return OFF;
  }
}

function open(next: NearbyGate): void {
  gate = next;
  if (!next.on) return;
  void load().then((m) => {
    ui = m;
    if (next.logFile) m.startNearbyLogFile();
    emit();
  }, () => {});
}

/** Asks the app binary once per page. */
export function askNearby(): void {
  if (asked) return;
  asked = true;
  void probe().then(open);
}

/** The gate as last answered: all off until the binary has said yes. */
export function nearbyGate(): NearbyGate {
  return gate;
}

const uiSnapshot = (): NearbyUi | null => ui;

/** The nearby UI module once the binary offers nearby play; null until then
 *  and wherever it does not. */
export function useNearbyUi(): NearbyUi | null {
  askNearby();
  return useSyncExternalStore(subscribe, uiSnapshot, uiSnapshot);
}

const noSubscribe = () => () => {};
const nothing = () => null;

/** The nearby join's view (nearbyJoin.ts); null without the nearby UI. */
export function useNearbyJoinView(): NearbyJoin | null {
  const m = useNearbyUi();
  const get = m ? m.nearbyJoin.getSnapshot : nothing;
  return useSyncExternalStore(m ? m.nearbyJoin.subscribe : noSubscribe, get, get);
}

const off = () => false;

/** Whether the ⋯ menu's code marks the Beta's hidden switch as on; false
 *  without the nearby UI. */
export function useNearbySoakMarker(): boolean {
  const m = useNearbyUi();
  const get = m ? m.nearbySoakMarker.getSnapshot : off;
  return useSyncExternalStore(m ? m.nearbySoakMarker.subscribe : noSubscribe, get, get);
}

const HOST_OFF: NearbyHostView = { phase: "off", line: null };
const hostOff = () => HOST_OFF;

/** The host's switch (nearbySession.ts); off without the nearby UI. */
export function useNearbyHostView(): NearbyHostView {
  const m = useNearbyUi();
  const get = m ? m.nearbyHost.getSnapshot : hostOff;
  return useSyncExternalStore(m ? m.nearbyHost.subscribe : noSubscribe, get, get);
}

const notLeft = () => false;

/** The joiner's end screen after the host's window passed. */
export function useNearbyHostLeft(): boolean {
  const m = useNearbyUi();
  const get = m ? () => m.nearbyJoin.hostLeft : notLeft;
  return useSyncExternalStore(m ? m.nearbyJoin.subscribe : noSubscribe, get, get);
}

/** The device test's log pane, in a Debug build for the device test only. */
export function NearbyDebugMount() {
  const m = useNearbyUi();
  return m && gate.debug ? createElement(m.NearbyDebugPane) : null;
}

/** Tests: answer the gate with `c` (null: no plugin) and load the UI with
 *  `loader`, or put the gate back to unasked. */
export function setNearbyGateForTests(c: NearbyCapabilities | null | undefined,
                                      loader?: () => Promise<NearbyUi>): Promise<void> {
  gate = OFF;
  ui = null;
  asked = c !== undefined;
  load = loader ?? (() => import("./nearbyUi"));
  if (c === undefined) { emit(); return Promise.resolve(); }
  const next = gateFor(c);
  gate = next;
  if (!next.on) { emit(); return Promise.resolve(); }
  return load().then((m) => {
    ui = m;
    if (next.logFile) m.startNearbyLogFile();
    emit();
  });
}

/** Tests: forget the answer, so the next render asks the binary again
 *  through `loader`. */
export function resetNearbyGateForTests(loader?: () => Promise<NearbyUi>): void {
  gate = OFF;
  ui = null;
  asked = false;
  load = loader ?? (() => import("./nearbyUi"));
  emit();
}
