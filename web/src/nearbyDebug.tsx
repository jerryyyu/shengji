// The nearby device test's log pane: only in a Debug build made for the
// device test (the plugin's capabilities say `debug`), never in a shipped
// binary or on the web. A small Log tab at the screen's corner opens the last
// lines of nearbyLog.ts, with Copy, so a tester can paste what the link did.
import { useEffect, useState, useSyncExternalStore, type CSSProperties } from "react";
import { nearbyPluginProxy } from "./native";
import { listenNativeLog, nearbyLogLines, nearbyLogText, subscribeNearbyLog } from "./nearbyLog";

interface DebugPlugin {
  capabilities(): Promise<{ debug?: unknown }>;
  addListener(event: "debugLog", fn: (ev: { text: string }) => void): Promise<unknown>;
}

async function debugPlugin(): Promise<DebugPlugin | null> {
  const p = nearbyPluginProxy() as Partial<DebugPlugin> | null;
  if (!p || typeof p.capabilities !== "function" || typeof p.addListener !== "function") return null;
  try {
    const c = await p.capabilities();
    return c.debug === true ? (p as DebugPlugin) : null;
  } catch {
    return null;
  }
}

const tab: CSSProperties = {
  position: "fixed", left: 4, bottom: 4, zIndex: 99999, font: "11px ui-monospace, monospace",
  padding: "2px 6px", opacity: 0.6, background: "#222", color: "#eee", border: "1px solid #555", borderRadius: 4,
};
const pane: CSSProperties = {
  position: "fixed", left: 0, right: 0, bottom: 0, height: "45vh", zIndex: 99999, background: "rgba(0,0,0,0.88)",
  color: "#cfc", font: "10px/1.3 ui-monospace, monospace", display: "flex", flexDirection: "column",
};

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
    void navigator.clipboard?.writeText(nearbyLogText()).then(() => setCopied(true), () => setCopied(false));
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
