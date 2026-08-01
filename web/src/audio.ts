// Chinese voice announcements. Clips live at /sounds/<name>.mp3 — one per card
// code (H2..SA, H10-style tens, BJ/LJ) plus pair.mp3 (一对), nt.mp3 (无主),
// throw.mp3 (甩牌). Clips are fetched+decoded lazily and cached; sequences are
// queued and played back-to-back without overlap.

import type { GameState } from "./protocol";

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
const SOUNDS_VERSION = 2;

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

  // Throws: a newly appeared play of 4+ cards in the current trick.
  const nextSeen = new Set<string>();
  for (const p of state.trick?.plays ?? []) {
    const key = `${p.seat}:${p.cards.join(",")}`;
    nextSeen.add(key);
    if (!seedOnly && p.cards.length >= 4 && !seenPlays.has(key)) {
      play(["throw"]);
    }
  }
  seenPlays = nextSeen;
}
