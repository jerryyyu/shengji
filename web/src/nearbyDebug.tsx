// The nearby device test's log pane: only in a Debug build made for the
// device test (the plugin's capabilities say `debug`), never in a shipped
// binary or on the web. A Log tab at the screen's bottom-left corner, clear of
// the rounded corner and the home indicator and above the table, opens the
// last lines of nearbyLog.ts, with Copy, so a tester can paste what the link
// did; the nearby table's ⋯ menu has Copy log too.
import { useEffect, useState, useSyncExternalStore, type CSSProperties } from "react";
import { nearbyPluginProxy } from "./native";
import { listenNativeLog, nearbyLogLines, nearbyLogText, subscribeNearbyLog } from "./nearbyLog";

interface DebugPlugin {
  capabilities(): Promise<{ debug?: unknown }>;
  addListener(event: "debugLog", fn: (ev: { text: string }) => void): Promise<unknown>;
}

let checked: Promise<DebugPlugin | null> | null = null;

/** The plugin, when this is a device-test Debug build; asked once per page. */
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
    return c.debug === true ? (p as DebugPlugin) : null;
  } catch {
    return null;
  }
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
