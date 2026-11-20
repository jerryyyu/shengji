// The M1 transport spike's test page (nearby-spike.html). It drives the
// ShengjiNearby plugin directly, with none of the room or NearbyHost on top:
// host a code, join it, pump frames and time them, and log every state. It
// is built only with SHENGJI_NEARBY_SPIKE=1 (vite.config.ts) and opened only
// by a Debug app compiled with SHENGJI_NEARBY_SPIKE (ShellViewController).
//
// Link protocol, both directions JSON text: the joiner sends
// {k:"p", seq, t, pad} and the host echoes each frame back unchanged; a
// {k:"hb", t} heartbeat every second keeps both ends' liveness timers fed.
import { registerPlugin } from "@capacitor/core";
import { newNearbyCode } from "./codes";

interface Listener { remove(): Promise<void> }
interface SpikePlugin {
  capabilities(): Promise<Record<string, unknown>>;
  host(o: { code: string; tls13?: boolean }): Promise<void>;
  join(o: { code: string; tls13?: boolean }): Promise<void>;
  send(o: { peer: string; text: string }): Promise<void>;
  close(o: { peer: string }): Promise<void>;
  stop(): Promise<void>;
  spikeBench(o: { iterations: number; runs: number }): Promise<{ iterations: number; ms: number; all: number[]; model: string }>;
  addListener(ev: string, fn: (e: Record<string, string>) => void): Promise<Listener>;
}

const P = registerPlugin<SpikePlugin>("ShengjiNearby");
const T0 = performance.now();
const now = () => performance.now();
const HEARTBEAT_MS = 1000;
const SILENT_MS = 3000;

document.body.innerHTML = `
<style>
  body { background:#14171e; color:#e8e8ea; font:14px -apple-system,system-ui,sans-serif; margin:0;
         padding:calc(env(safe-area-inset-top) + 8px) 12px calc(env(safe-area-inset-bottom) + 8px); }
  h1 { font-size:17px; margin:4px 0 8px } h2 { font-size:14px; margin:12px 0 4px; color:#9ab }
  button { font:inherit; background:#2c3442; color:#fff; border:0; border-radius:8px; padding:9px 12px; margin:3px 2px }
  button.go { background:#2f6fde } input { font:inherit; width:6.5em; padding:7px; border-radius:6px; border:1px solid #445;
         background:#0d1015; color:#fff } input.code { width:7em; letter-spacing:2px; text-transform:uppercase }
  .row { display:flex; flex-wrap:wrap; align-items:center; gap:4px }
  #status { font-size:16px; font-weight:600; padding:8px; border-radius:8px; background:#222a36; margin:6px 0 }
  #result { white-space:pre-wrap; font:13px ui-monospace,Menlo,monospace; background:#0d1015; padding:8px; border-radius:8px; min-height:2em }
  #log { white-space:pre-wrap; font:11px ui-monospace,Menlo,monospace; background:#0d1015; padding:8px; border-radius:8px;
         max-height:40vh; overflow:auto; -webkit-user-select:text; user-select:text }
  label { display:inline-flex; align-items:center; gap:4px; margin-right:8px }
</style>
<h1>Nearby M1 spike</h1>
<div id="status">idle</div>
<div class="row"><label><input type="checkbox" id="tls13" style="width:auto"> TLS 1.3 PSK</label></div>
<h2>Host</h2>
<div class="row"><button class="go" id="host">Host</button><button id="stop">Stop</button></div>
<h2>Join</h2>
<div class="row"><input class="code" id="code" maxlength="5" placeholder="CODE" autocapitalize="characters" autocomplete="off">
  <button class="go" id="join">Join</button><button id="trials">Find ×10</button></div>
<div class="row"><label><input type="checkbox" id="rejoin" style="width:auto"> auto-rejoin</label>
  <button id="back">I'm back in range</button></div>
<h2>Pump (joiner)</h2>
<div class="row">N <input id="n" value="1000" inputmode="numeric"> bytes <input id="s" value="4096" inputmode="numeric">
  in flight <input id="w" value="1" inputmode="numeric"> <button class="go" id="pump">Send</button></div>
<h2>Key</h2>
<div class="row">iterations <input id="iter" value="200000" inputmode="numeric"> <button id="bench">Time PBKDF2</button></div>
<h2>Result</h2>
<div id="result"></div>
<h2>Log <button id="copy">Copy log</button><button id="clear">Clear</button></h2>
<div id="log"></div>`;

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const logEl = $("log");
const lines: string[] = [];
function log(text: string): void {
  const line = `${new Date().toISOString().slice(11, 23)} +${((now() - T0) / 1000).toFixed(3)}s ${text}`;
  lines.push(line);
  logEl.textContent = lines.slice(-400).join("\n");
  logEl.scrollTop = logEl.scrollHeight;
}
const status = (s: string) => { $("status").textContent = s; log(`STATUS ${s}`); };
const result = (s: string) => { $("result").textContent = s; log(`RESULT ${s.replace(/\n/g, " | ")}`); };
const tls13 = () => $<HTMLInputElement>("tls13").checked;
const num = (id: string) => Number($<HTMLInputElement>(id).value);

type Role = "idle" | "host" | "join";
let role: Role = "idle";
let code = "";
const lastHeard = new Map<string, number>(); // peer -> ms
let joined = false;
let joinStarted = 0;
let onConnected: ((ms: number) => void) | null = null;
let backAt = 0;
let downAt = 0;
let rejoining = false;
let pump: { n: number; size: number; window: number; sent: number; got: number; rtts: number[];
  outOfOrder: number; nextExpected: number; started: number; done: (() => void) | null } | null = null;

function percentile(sorted: number[], p: number): number {
  if (!sorted.length) return NaN;
  return sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)];
}

async function send(peer: string, text: string): Promise<void> {
  try {
    await P.send({ peer, text });
  } catch (e) {
    log(`send to ${peer} failed: ${errText(e)}`);
  }
}

function errText(e: unknown): string {
  const x = e as { code?: string; message?: string };
  return `${x.code ?? ""} ${x.message ?? String(e)}`.trim();
}

void P.addListener("spikeLog", (e) => log(`native: ${e.text}`));
void P.addListener("state", (e) => {
  log(`state ${e.state}${e.detail ? ` (${e.detail})` : ""}`);
  if (role === "host") status(`hosting ${code}: ${e.state}${e.detail ? ` (${e.detail})` : ""}`);
  if (role === "join" && !joined) {
    if (e.state !== "ready" && e.state !== "waiting") {
      status(`join: ${e.state}${e.detail ? ` (${e.detail})` : ""}`);
      if ($<HTMLInputElement>("rejoin").checked && rejoining) setTimeout(() => void startJoin(true), 500);
    }
  }
});
void P.addListener("peer", (e) => {
  log(`peer ${e.peer} ${e.state}`);
  if (role === "host") {
    if (e.state === "connected") lastHeard.set(e.peer, now());
    else lastHeard.delete(e.peer);
    status(`hosting ${code}: ${lastHeard.size} joiner(s)`);
    return;
  }
  if (e.state === "connected") {
    joined = true;
    lastHeard.set("host", now());
    const ms = now() - joinStarted;
    log(`FOUND+CONNECTED in ${(ms / 1000).toFixed(2)} s`);
    status(`joined ${code} in ${(ms / 1000).toFixed(2)} s`);
    if (rejoining) {
      rejoining = false;
      const outage = ((now() - downAt) / 1000).toFixed(1);
      const sinceBack = backAt ? ` | back in range → linked ${((now() - backAt) / 1000).toFixed(1)} s` : "";
      result(`relinked: outage ${outage} s${sinceBack}`);
      backAt = 0;
    }
    onConnected?.(ms);
  } else if (e.state === "disconnected") {
    linkDown("peer disconnected");
  }
});
void P.addListener("message", (e) => {
  lastHeard.set(e.peer, now());
  if (role === "host") {
    if (!e.text.startsWith('{"k":"hb"')) void send(e.peer, e.text); // echo
    return;
  }
  if (e.text.startsWith('{"k":"hb"')) return;
  let m: { seq: number; t: number };
  try { m = JSON.parse(e.text); } catch { return log("bad frame"); }
  if (!pump) return;
  pump.rtts.push(now() - m.t);
  if (m.seq !== pump.nextExpected) pump.outOfOrder++;
  pump.nextExpected = m.seq + 1;
  pump.got++;
  if (pump.sent < pump.n) void sendFrame();
  if (pump.got === pump.n) pump.done?.();
});
document.addEventListener("visibilitychange", () => log(`page ${document.visibilityState}`));

// heartbeat and liveness: a silent link is a dead link
setInterval(() => {
  const t = now();
  if (role === "host") {
    for (const [peer, heard] of lastHeard) {
      void send(peer, `{"k":"hb","t":${t}}`);
      if (t - heard > SILENT_MS * 2) {
        log(`host: ${peer} silent ${((t - heard) / 1000).toFixed(1)} s, closing it`);
        lastHeard.delete(peer);
        void P.close({ peer });
      }
    }
  } else if (role === "join" && joined) {
    void send("host", `{"k":"hb","t":${t}}`);
    const heard = lastHeard.get("host") ?? t;
    if (t - heard > SILENT_MS) linkDown(`host silent ${((t - heard) / 1000).toFixed(1)} s`);
  }
}, HEARTBEAT_MS);

function linkDown(why: string): void {
  if (!joined) return;
  joined = false;
  lastHeard.delete("host");
  downAt = now();
  log(`LINK DOWN: ${why}`);
  status(`link down (${why})`);
  if (pump && pump.got < pump.n) pump.done?.();
  if ($<HTMLInputElement>("rejoin").checked && role === "join") {
    rejoining = true;
    void startJoin(true);
  }
}

async function stopAll(): Promise<void> {
  role = "idle";
  joined = false;
  rejoining = false;
  lastHeard.clear();
  try { await P.stop(); } catch (e) { log(`stop: ${errText(e)}`); }
}

$("host").onclick = async () => {
  await stopAll();
  code = newNearbyCode();
  role = "host";
  status(`hosting ${code}: starting`);
  try {
    await P.host({ code, tls13: tls13() });
    status(`hosting ${code}: ready`);
  } catch (e) {
    status(`host failed: ${errText(e)}`);
  }
};
$("stop").onclick = async () => { await stopAll(); status("stopped"); };

async function startJoin(again = false): Promise<void> {
  if (!again) await stopAll();
  code = $<HTMLInputElement>("code").value.trim().toUpperCase();
  role = "join";
  joined = false;
  joinStarted = now();
  status(`joining ${code}…`);
  try {
    await P.join({ code, tls13: tls13() });
  } catch (e) {
    status(`join failed: ${errText(e)}`);
    if (again && $<HTMLInputElement>("rejoin").checked) setTimeout(() => void startJoin(true), 1000);
  }
}
$("join").onclick = () => void startJoin();

$("trials").onclick = async () => {
  const times: string[] = [];
  for (let i = 0; i < 10; i++) {
    const ms = await new Promise<number>((ok) => {
      const giveUp = setTimeout(() => { onConnected = null; ok(NaN); }, 20000);
      onConnected = (m) => { clearTimeout(giveUp); onConnected = null; ok(m); };
      void startJoin();
    });
    times.push(Number.isNaN(ms) ? "none" : (ms / 1000).toFixed(2));
    log(`trial ${i + 1}: ${times[i]} s`);
    await stopAll();
    await new Promise((r) => setTimeout(r, 2000));
  }
  const ok = times.filter((t) => t !== "none" && Number(t) <= 5).length;
  result(`find ×10 (s): ${times.join(", ")}\n≤ 5 s: ${ok}/10`);
};

$("back").onclick = () => { backAt = now(); log("BACK IN RANGE (tapped)"); };

async function sendFrame(): Promise<void> {
  if (!pump) return;
  const seq = pump.sent++;
  const head = `{"k":"p","seq":${seq},"t":${now()},"pad":"`;
  const text = head + "x".repeat(Math.max(0, pump.size - head.length - 2)) + `"}`;
  await send("host", text);
}

$("pump").onclick = async () => {
  if (role !== "join" || !joined) return status("join first");
  const n = num("n");
  const size = num("s");
  const inFlight = Math.max(1, num("w"));
  await new Promise<void>((done) => {
    pump = { n, size, window: inFlight, sent: 0, got: 0, rtts: [], outOfOrder: 0, nextExpected: 0, started: now(), done: null };
    let quiet: ReturnType<typeof setTimeout> | null = null;
    pump.done = () => { if (quiet) clearTimeout(quiet); done(); };
    // after the last send, wait 5 s for stragglers
    const watch = setInterval(() => {
      if (pump && pump.sent >= pump.n && !quiet) {
        clearInterval(watch);
        quiet = setTimeout(done, 5000);
      }
    }, 200);
    status(`pumping ${n} × ${size} B`);
    for (let i = 0; i < Math.min(inFlight, n); i++) void sendFrame();
  });
  const p = pump!;
  const secs = (now() - p.started) / 1000;
  const sorted = [...p.rtts].sort((a, b) => a - b);
  result(
    `${p.n} × ${p.size} B, in flight ${p.window}, TLS ${tls13() ? "1.3" : "1.2"}\n` +
    `received ${p.got}/${p.n}, lost ${p.n - p.got}, out of order ${p.outOfOrder}\n` +
    `RTT ms p50 ${percentile(sorted, 50).toFixed(1)}  p95 ${percentile(sorted, 95).toFixed(1)}  max ${(sorted.at(-1) ?? NaN).toFixed(1)}\n` +
    `${secs.toFixed(1)} s, ${((p.got * p.size * 2) / 1024 / secs).toFixed(0)} KB/s both ways\n` +
    `PASS bar (none lost, in order, p95 ≤ 150): ${p.got === p.n && p.outOfOrder === 0 && percentile(sorted, 95) <= 150 ? "PASS" : "FAIL"}`,
  );
  status(`joined ${code}`);
  pump = null;
};

$("bench").onclick = async () => {
  try {
    const r = await P.spikeBench({ iterations: num("iter"), runs: 5 });
    const n250 = Math.round((r.iterations * 250) / r.ms / 1000) * 1000;
    result(`PBKDF2 ${r.model}: ${r.iterations} iterations = ${r.ms.toFixed(1)} ms (median of 5: ${r.all.map((x) => x.toFixed(0)).join(", ")})\n≈250 ms needs N ≈ ${n250}`);
  } catch (e) {
    result(`bench failed: ${errText(e)}`);
  }
};

$("copy").onclick = async () => {
  const text = lines.join("\n");
  try {
    await navigator.clipboard.writeText(text);
    log("log copied");
  } catch {
    const range = document.createRange();
    range.selectNodeContents(logEl);
    getSelection()?.removeAllRanges();
    getSelection()?.addRange(range);
    log("select-all done: tap Copy in the menu");
  }
};
$("clear").onclick = () => { lines.length = 0; logEl.textContent = ""; };

void P.capabilities().then((c) => log(`capabilities ${JSON.stringify(c)}`), (e) => log(`capabilities failed: ${errText(e)}`));
log(`page loaded at ${location.href}; nothing touches the network until Host or Join`);
