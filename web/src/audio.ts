// Chinese voice announcements. Clips live at /sounds/<name>.mp3 — one per card
// code (H2..SA, H10-style tens, BJ/LJ) plus pair.mp3 (一对), nt.mp3 (无主),
// throw.mp3 (甩牌). Clips are fetched+decoded lazily and cached; sequences are
// queued and played back-to-back without overlap.

import type { GameState, Trump } from "./protocol";

const MUTE_KEY = "shengji.muted";
const GAP_MS = 80; // pause between clips in a sequence
const MAX_QUEUE = 4; // pending sequences beyond this drop the oldest

let ctx: AudioContext | null = null;
const clipCache = new Map<string, Promise<AudioBuffer | null>>();
const queue: string[][] = [];
let pumping = false;
let muted = localStorage.getItem(MUTE_KEY) === "1"; // default: unmuted

function ensureCtx(): AudioContext {
  if (!ctx) ctx = new AudioContext();
  if (ctx.state === "suspended") {
    void ctx.resume().catch(() => {});
  }
  return ctx;
}

// Unlock the context on the first user gesture (autoplay policy).
window.addEventListener(
  "pointerdown",
  () => {
    ensureCtx();
  },
  { once: true }
);

export function isMuted(): boolean {
  return muted;
}

export function setMuted(m: boolean): void {
  muted = m;
  localStorage.setItem(MUTE_KEY, m ? "1" : "0");
  if (m) queue.length = 0;
}

// Bump when clips are regenerated so browsers refetch instead of using
// cached audio from an older voice.
const SOUNDS_VERSION = 6;

function loadClip(name: string): Promise<AudioBuffer | null> {
  let p = clipCache.get(name);
  if (!p) {
    p = fetch(`/sounds/${name}.mp3?v=${SOUNDS_VERSION}`)
      .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(`${r.status}`))))
      .then((ab) => ensureCtx().decodeAudioData(ab))
      .catch(() => null); // 404 / decode failure: silently skip
    clipCache.set(name, p);
  }
  return p;
}

function playBuffer(buffer: AudioBuffer): Promise<void> {
  return new Promise((resolve) => {
    const c = ensureCtx();
    if (c.state !== "running") {
      resolve(); // not unlocked yet — drop rather than stall the queue
      return;
    }
    const src = c.createBufferSource();
    src.buffer = buffer;
    src.connect(c.destination);
    // Guard timer so a wedged onended can never stall the pump.
    const guard = window.setTimeout(resolve, buffer.duration * 1000 + 500);
    src.onended = () => {
      window.clearTimeout(guard);
      resolve();
    };
    try {
      src.start();
    } catch {
      window.clearTimeout(guard);
      resolve();
    }
  });
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => window.setTimeout(r, ms));
}

/** Short synthesized click for plays with no voice line (junk dumps). */
function playTick(): void {
  if (muted) return;
  const c = ensureCtx();
  if (c.state !== "running") return;
  const t = c.currentTime;
  const osc = c.createOscillator();
  const gain = c.createGain();
  osc.frequency.value = 2100;
  gain.gain.setValueAtTime(0.07, t);
  gain.gain.exponentialRampToValueAtTime(0.001, t + 0.06);
  osc.connect(gain);
  gain.connect(c.destination);
  osc.start(t);
  osc.stop(t + 0.07);
}

/** Enqueue a sequence of clip names (played in order, never overlapping). */
export function play(names: string[]): void {
  if (muted || names.length === 0) return;
  queue.push(names);
  while (queue.length > MAX_QUEUE) queue.shift();
  void pump();
}

async function pump(): Promise<void> {
  if (pumping) return;
  pumping = true;
  try {
    for (;;) {
      const seq = queue.shift();
      if (!seq) break;
      for (const name of seq) {
        if (muted) break;
        const buf = await loadClip(name);
        if (buf) {
          await playBuffer(buf);
          await sleep(GAP_MS);
        }
      }
    }
  } finally {
    pumping = false;
  }
}

// ---------- state-diff triggers ----------

let lastDecl: string | null = null;
let seenPlays = new Set<string>();

/** Jokers, trump-rank cards, and (for real suits) trump-suit cards are trump.
 * trump.suit "NT" means only jokers + rank cards. */
function isTrump(code: string, trump: Trump): boolean {
  if (code === "BJ" || code === "LJ") return true;
  if (code.slice(1) === trump.rank) return true;
  const s = trump.suit;
  return (s === "S" || s === "H" || s === "D" || s === "C") && code.startsWith(s);
}

/** Reset diff trackers (call when leaving a room / before a fresh join). */
export function resetAnnouncer(): void {
  lastDecl = null;
  seenPlays = new Set();
}

/**
 * Inspect a new state and announce changes. With `seedOnly` (first state after
 * (re)join) trackers are updated but nothing plays — no stale announcements.
 * Dedupes by declaration identity (seat+cards) and by play identity, so rapid
 * bot states never repeat a clip.
 */
export function announceState(state: GameState, seedOnly = false): void {
  // Declarations: single card => [code]; suited pair => ["pair", code];
  // joker pair => ["nt"].
  const d = state.current_declaration;
  if (!d) {
    lastDecl = null; // cleared each new deal, so next round re-announces
  } else {
    const key = `${d.seat}:${d.cards.join(",")}`;
    if (key !== lastDecl) {
      lastDecl = key;
      if (!seedOnly) {
        const first = d.cards[0] ?? "";
        if (first === "BJ" || first === "LJ") play(["nt"]);
        else if (d.cards.length >= 2) play(["pair", first]);
        else if (first) play([first]);
      }
    }
  }

  // Every newly appeared play gets a sound. Ruffs ("bi") take priority;
  // singles say the card, pairs say 一对+card, 4+ all-pairs say 拖拉机,
  // other multi-card plays say 甩牌; forced junk dumps get a click.
  const trump = state.trump;
  const plays = state.trick?.plays ?? [];
  const lead = plays[0];
  const leadHasTrump =
    trump !== null && lead !== undefined ? lead.cards.some((c) => isTrump(c, trump)) : true;
  const nextSeen = new Set<string>();
  plays.forEach((p, i) => {
    const key = `${p.seat}:${p.cards.join(",")}`;
    nextSeen.add(key);
    if (seedOnly || seenPlays.has(key)) return;
    const n = p.cards.length;
    const isRuff =
      i > 0 && trump !== null && !leadHasTrump && n > 0 &&
      p.cards.every((c) => isTrump(c, trump));
    const counts = new Map<string, number>();
    for (const c of p.cards) counts.set(c, (counts.get(c) ?? 0) + 1);
    const allPairs = n >= 2 && [...counts.values()].every((k) => k % 2 === 0);
    if (isRuff) play(["bi"]);
    else if (i === 0) {
      // card names only on the LEAD of each trick
      const allTrump =
        trump !== null && n > 0 && p.cards.every((c) => isTrump(c, trump));
      if (allTrump) play(["diaozhu"]); // 调主: drawing trump
      else if (n === 1) play([p.cards[0]]);
      else if (n === 2 && allPairs) play(["pair", p.cards[0]]);
      else if (n >= 4 && allPairs) play(["tractor"]);
      else play(["throw"]); // multi-component lead
    } else playTick(); // followers: just a click (ruffs handled above)
  });
  seenPlays = nextSeen;
}
