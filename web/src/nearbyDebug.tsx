// The nearby device test's log pane: only in a Debug build made for the
// device test (the plugin's capabilities say `debug`), never in a shipped
// binary or on the web. A Log tab at the screen's bottom-left corner, clear of
// the rounded corner and the home indicator and above the table, opens the
// last lines of nearbyLog.ts, with Copy, so a tester can paste what the link
// did. Wherever the plugin reports `logFile` (the device test and the Beta),
// the log file (nearbyLog.ts) is always on from the page's start, its new
// bytes go to the server (nearbyLogUpload.ts), and the nearby table's ⋯ menu
// has Copy log, Clear log file and Upload log now, with the soak's Autoplay,
// Chaos and summary. Those rows show in the device test, and in the Beta
// (`chaos`) only once the hidden switch is on: five taps on the ⋯ menu's
// table code within SWITCH_WINDOW_MS, five more to turn it off, kept in
// localStorage; a dot after the code marks it on. The file and its upload
// run with the switch off as well. A soak
// left on (its switches kept by nearbySoak.ts) resumes at the page's start,
// so a reload keeps it going.
import { useEffect, useState, useSyncExternalStore, type CSSProperties } from "react";
import { nearbyPluginProxy } from "./native";
import {
  attachNearbyLogFile, clearNearbyLogFile, listenNativeLog, nearbyLogFileOn, nearbyLogLines, nearbyLogText,
  subscribeNearbyLog, type LogFile,
} from "./nearbyLog";

export { clearNearbyLogFile, nearbyLogFileOn };

interface DebugPlugin {
  capabilities(): Promise<{ debug?: unknown; logFile?: unknown }>;
  addListener(event: "debugLog", fn: (ev: { text: string }) => void): unknown;
}

let checked: Promise<DebugPlugin | null> | null = null;

/** The plugin, when this is a device-test Debug build; asked once per page,
 *  and the log file attached on the way wherever the plugin has one. */
function debugPlugin(): Promise<DebugPlugin | null> {
  checked ??= askDebugPlugin();
  return checked;
}

async function askDebugPlugin(): Promise<DebugPlugin | null> {
  let p: Partial<DebugPlugin> | null;
  try {
    p = nearbyPluginProxy() as Partial<DebugPlugin> | null;
  } catch {
    return null;
  }
  if (!p || typeof p.capabilities !== "function" || typeof p.addListener !== "function") return null;
  try {
    const c = await p.capabilities();
    // the plugin has the file only in the device test and the Beta
    if (c.logFile === true && typeof (p as Partial<LogFile>).debugLogFile === "function") {
      listenNativeLog(p as DebugPlugin);
      if (await attachNearbyLogFile(p as unknown as LogFile)) startUpload();
    }
    if (c.logFile === true && (c.debug === true || ((c as { chaos?: unknown }).chaos === true && switchOn))) resumeSoak();
    return c.debug === true ? (p as DebugPlugin) : null;
  } catch {
    return null;
  }
}

// the soak's own record (nearbySoak.ts KEEP_KEY): its switches and the
// table's code, so a reload (its chaos kind, or a crash) resumes it
const SOAK_KEY = "shengji.nearbySoak.v1";

/** At the page's start: a soak left on loads and resumes, and its driver
 *  rejoins the kept code. */
function resumeSoak(): void {
  let on = false;
  try {
    const k = JSON.parse(localStorage.getItem(SOAK_KEY) ?? "null") as { autoplay?: boolean; chaos?: boolean } | null;
    on = !!k && (k.autoplay === true || k.chaos === true);
  } catch { /* nothing kept */ }
  if (!on) return;
  void import("./nearbySoak").then((m) => {
    soakModule = m;
    m.resumeSoak();
  }, () => {});
}

/** Starts the log file and its upload; nearbyGate.ts calls it once the
 *  plugin reports `logFile`. */
export function startNearbyLogFile(): void {
  void debugPlugin();
}

/** Whether lines are going to the file; asked only while `ask` holds. */
export function useNearbyLogFile(ask: boolean): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    if (!ask) return;
    let live = true;
    debugPlugin().then(() => { if (live) setOn(nearbyLogFileOn()); }, () => {});
    return () => { live = false; };
  }, [ask]);
  return ask && on;
}

// The hidden switch for the ⋯ menu's log and soak rows, where the plugin
// reports `chaos` without `debug` (the Beta).
export const SWITCH_TAPS = 5;
export const SWITCH_WINDOW_MS = 3000;
const SWITCH_KEY = "shengji.nearbySoakSwitch.v1";
const switchListeners = new Set<() => void>();
let taps: number[] = [];
let soakModule: typeof import("./nearbySoak") | null = null;

function readSwitch(): boolean {
  try { return localStorage.getItem(SWITCH_KEY) === "1"; } catch { return false; }
}

let switchOn = readSwitch();

const subscribeSwitch = (fn: () => void): (() => void) => {
  switchListeners.add(fn);
  return () => { switchListeners.delete(fn); };
};
const switchSnapshot = (): boolean => switchOn;

export { subscribeSwitch as subscribeNearbySoakSwitch, switchSnapshot as nearbySoakSwitchOn };

/** Whether the hidden switch is on. */
export function useNearbySoakSwitch(): boolean {
  return useSyncExternalStore(subscribeSwitch, switchSnapshot, switchSnapshot);
}

/** One tap on the ⋯ menu's table code: the fifth within SWITCH_WINDOW_MS
 *  turns the switch over. A no-op unless the plugin reports `chaos`.
 *  Turning it off stops Autoplay and Chaos. */
export function nearbySoakSwitchTap(chaos: boolean, now: number = Date.now()): void {
  if (!chaos) return;
  taps = [...taps.filter((t) => now - t < SWITCH_WINDOW_MS), now];
  if (taps.length < SWITCH_TAPS) return;
  taps = [];
  switchOn = !switchOn;
  try { localStorage.setItem(SWITCH_KEY, switchOn ? "1" : "0"); } catch { /* this page only */ }
  if (!switchOn) {
    soakModule?.setAutoplay(false);
    soakModule?.setChaos(false);
    try { localStorage.removeItem(SOAK_KEY); } catch { /* this page only */ }
  }
  switchListeners.forEach((l) => l());
}

let upload: Promise<typeof import("./nearbyLogUpload") | null> = Promise.resolve(null);

/** The upload module loads only once the log file is attached, so only
 *  where the plugin reports the device test's `logFile`. */
function startUpload(): void {
  upload = import("./nearbyLogUpload").then((m) => (m.startNearbyLogUpload() || m.nearbyLogUploadOn() ? m : null), () => null);
}

/** The ⋯ menu's Upload log now; resolves when the tick is done. */
export function uploadNearbyLogNow(): Promise<void> {
  return upload.then((m) => m?.uploadNearbyLogNow());
}

/** Tests: ask the plugin again, and read the hidden switch afresh. */
export function resetNearbyDebugForTests(): void {
  checked = null;
  taps = [];
  switchOn = readSwitch();
  switchListeners.forEach((l) => l());
}

const TOP = 2147483647;
const tab: CSSProperties = {
  position: "fixed", left: "max(8px, env(safe-area-inset-left))", bottom: "max(8px, env(safe-area-inset-bottom))",
  zIndex: TOP, minWidth: 56, minHeight: 44, font: "600 14px ui-monospace, monospace",
  padding: "0 12px", opacity: 0.85, background: "#222", color: "#fff", border: "1px solid #888", borderRadius: 8,
};
const pane: CSSProperties = {
  position: "fixed", left: 0, right: 0, bottom: 0, height: "45vh", zIndex: TOP, background: "rgba(0,0,0,0.88)",
  paddingLeft: "env(safe-area-inset-left)", paddingRight: "env(safe-area-inset-right)",
  paddingBottom: "env(safe-area-inset-bottom)", boxSizing: "border-box",
  color: "#cfc", font: "10px/1.3 ui-monospace, monospace", display: "flex", flexDirection: "column",
};

/** Whether this page runs in a device-test Debug build; asked only while
 *  `ask` (a nearby table) holds. */
export function useNearbyDebug(ask: boolean): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    if (!ask) return;
    let live = true;
    debugPlugin().then((p) => { if (live && p) setOn(true); }, () => {});
    return () => { live = false; };
  }, [ask]);
  return ask && on;
}

/** The device-test switch for the peer-to-peer keepalive, once its module
 *  (the on-device server's, loaded at a nearby table) is in; null before. */
export function useNearbyKeepalive(ask: boolean): { on: boolean; toggle: () => void } | null {
  const [mod, setMod] = useState<typeof import("./offline/server/nearby/socket") | null>(null);
  const [, bump] = useState(0);
  useEffect(() => {
    if (!ask) return;
    let live = true;
    let off = () => {};
    void import("./offline/server/nearby/socket").then((m) => {
      if (!live) return;
      setMod(m);
      off = m.subscribeNearbyKeepalive(() => bump((n) => n + 1));
    }, () => {});
    return () => { live = false; off(); };
  }, [ask]);
  if (!ask || mod === null) return null;
  return { on: mod.nearbyKeepalive(), toggle: () => mod.setNearbyKeepalive(!mod.nearbyKeepalive()) };
}

/** The soak's switches (nearbySoak.ts: Autoplay, Chaos, the soak summary),
 *  once its module is in; null before, and never loaded until their rows may
 *  show (the device test, or the Beta with the hidden switch on). */
export function useNearbySoak(ask: boolean): {
  autoplay: boolean; chaos: boolean; toggleAutoplay: () => void; toggleChaos: () => void; copy: () => Promise<boolean>;
} | null {
  const [mod, setMod] = useState<typeof import("./nearbySoak") | null>(null);
  const [, bump] = useState(0);
  useEffect(() => {
    if (!ask) return;
    let live = true;
    let off = () => {};
    void import("./nearbySoak").then((m) => {
      soakModule = m;
      if (!live) return;
      setMod(m);
      off = m.subscribeSoak(() => bump((n) => n + 1));
    }, () => {});
    return () => { live = false; off(); };
  }, [ask]);
  if (!ask || mod === null) return null;
  const s = mod.soakState();
  return {
    autoplay: s.autoplay,
    chaos: s.chaos,
    toggleAutoplay: () => mod.setAutoplay(!s.autoplay),
    toggleChaos: () => mod.setChaos(!s.chaos),
    copy: () => navigator.clipboard?.writeText(mod.soakSummaryText()).then(() => true, () => false) ?? Promise.resolve(false),
  };
}

/** Puts the log on the clipboard; resolves whether it did. */
export function copyNearbyLog(): Promise<boolean> {
  return navigator.clipboard?.writeText(nearbyLogText()).then(() => true, () => false) ?? Promise.resolve(false);
}

export default function NearbyDebugPane() {
  const [on, setOn] = useState(false);
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const lines = useSyncExternalStore(subscribeNearbyLog, nearbyLogLines, nearbyLogLines);
  useEffect(() => {
    let live = true;
    void debugPlugin().then((p) => {
      if (!live || !p) return;
      listenNativeLog(p);
      setOn(true);
    });
    return () => { live = false; };
  }, []);
  if (!on) return null;
  if (!open) return <button type="button" style={tab} onClick={() => setOpen(true)}>Log {lines.length}</button>;
  const copy = () => {
    void copyNearbyLog().then(setCopied);
  };
  return (
    <div style={pane}>
      <div style={{ display: "flex", gap: 8, padding: 4 }}>
        <button type="button" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
        <button type="button" onClick={() => { setOpen(false); setCopied(false); }}>Close</button>
      </div>
      <div style={{ overflowY: "auto", flex: 1, padding: "0 4px", whiteSpace: "pre-wrap" }}>
        {lines.slice().reverse().map((l, i) => (
          <div key={lines.length - i} style={/REFUSED|IGNORED|STUCK|failed|error/.test(l.text) ? { color: "#f88" } : undefined}>
            {(l.t / 1000).toFixed(3)} {l.from} {l.text}
          </div>
        ))}
      </div>
    </div>
  );
}
