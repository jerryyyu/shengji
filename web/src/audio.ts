// Chinese voice announcements. Clips live at /sounds/<name>.mp3: one per card
// code (H2..SA, H10-style tens, BJ/LJ) plus the VOICE_CLIPS below. Clips are
// fetched+decoded lazily and cached; sequences are queued and played
// back-to-back without overlap.
//
// A sound is for the moment it was asked for. iOS can hold a context out of
// "running" (interrupted or suspended) for minutes while its resume() promise
// stays pending; when that ends every sound still waiting on it would start
// at once, as one loud burst. So a context that has run and is now held drops
// each request at once (only the first unlock gets LATE_MS of grace), a
// change of context state invalidates every earlier request and cancels every
// live source, and at most MAX_VOICES source nodes are ever live.

import type { GameState, Trump } from "./protocol";

const MUTE_KEY = "shengji.muted";
const GAP_MS = 50; // pause between clips in a sequence
const MAX_QUEUE = 4; // pending sequences beyond this drop the oldest
/** Longest a sound waits for a running context before it is dropped. */
const LATE_MS = 150;
/** A queued sequence still waiting this long after its request is dropped. */
const STALE_MS = 2000;
/** Live sources (clips and ticks) at once; one more is dropped. */
const MAX_VOICES = 3;
/** A source whose onended has not come this long after its natural end is
 *  stopped and disconnected, so a freed slot always means a dead node. */
const END_GRACE_MS = 500;
const TICK_S = 0.07;

/** Non-card clips in public/sounds. */
const VOICE_CLIPS = {
  pair: "pair",         // 一对
  nt: "nt",             // 无主
  throw: "throw",       // 甩牌
  tractor: "tractor",   // 拖拉机
  ruff: "bi",           // 毙
  drawTrump: "diaozhu", // 调主
} as const;

let ctx: AudioContext | null = null;
const clipCache = new Map<string, Promise<AudioBuffer | null>>();
/** Clips whose speculative fetch failed: a demand play may fetch them again. */
const retryable = new Set<string>();
interface Request {
  names: string[];
  at: number;
  epoch: number;
}
const queue: Request[] = [];
let pumping = false;
/** Bumped whenever the context stops running, is replaced or the page hides:
 *  requests from an older epoch never play. */
let epoch = 0;
/** Cancels (stop, disconnect, free the slot) of every live source node. */
const live = new Set<() => void>();
/** Contexts that have reached "running" at least once. */
const ranOnce = new WeakSet<AudioContext>();
/** Ran-once contexts that have left "running" since. */
const heldAfterRun = new WeakSet<AudioContext>();

function now(): number {
  return performance.now();
}

function invalidate(): void {
  epoch++;
  queue.length = 0;
  for (const cancel of [...live]) cancel();
}

/** Counts `node` as a live voice until it ends or is cancelled. `release` and
 *  `cancel` are idempotent: the slot is freed exactly once, however many of
 *  onended, the guard timer and an invalidation arrive. */
function addVoice(
  node: AudioScheduledSourceNode, durationMs: number, onFree?: () => void,
): () => void {
  let freed = false;
  const release = () => {
    if (freed) return;
    freed = true;
    live.delete(cancel);
    window.clearTimeout(guard);
    onFree?.();
  };
  const cancel = () => {
    try { node.stop(); } catch { /* not started, or already stopped */ }
    try { node.disconnect(); } catch { /* already disconnected */ }
    release();
  };
  live.add(cancel);
  node.onended = release;
  const guard = window.setTimeout(cancel, durationMs + END_GRACE_MS);
  return cancel;
}
let muted = localStorage.getItem(MUTE_KEY) === "1"; // default: unmuted

function ensureCtx(): AudioContext {
  const AC: typeof AudioContext =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext: typeof AudioContext })
      .webkitAudioContext;
  if (!ctx || (ctx.state as string) === "closed") ctx = watch(new AC());
  if ((ctx.state as string) !== "running") {
    void ctx.resume().catch(() => {});
  }
  return ctx;
}

/** iOS WebKit moves a running context to "interrupted" (the keyboard's
 *  dictation, a call, Siri, another app's audio) or "suspended" without any
 *  visibility change. The gesture listeners were detached once audio first
 *  ran, so each such change re-arms them; otherwise the page stays silent
 *  until a reload. */
function watch(c: AudioContext): AudioContext {
  c.onstatechange = () => {
    if (c !== ctx) return;
    const state = c.state as string;
    if (state === "running") {
      // a recovery, not the first unlock: what was asked for before is stale
      if (heldAfterRun.delete(c)) invalidate();
      ranOnce.add(c);
      return;
    }
    if (ranOnce.has(c)) heldAfterRun.add(c);
    invalidate();
    if (state === "closed") return;
    void c.resume().catch(() => {});
    armUnlock();
  };
  return c;
}

/** Creates the audio context while the lobby is idle. Creating one is a long
 *  task (100 ms and more on a phone); done inside the first tap it lands on
 *  Play vs bots and stalls the table's first frames. A context made outside a
 *  gesture starts suspended, and the unlock below resumes it on the next tap. */
export function prewarmAudio(): void {
  if (ctx || typeof window === "undefined") return;
  const AC = window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return;
  const make = () => {
    if (ctx) return;
    try {
      ctx = watch(new AC());
    } catch {
      /* no audio here; the unlock path tries again on a tap */
    }
  };
  const idle = (window as unknown as {
    requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
  }).requestIdleCallback;
  if (idle) idle(make, { timeout: 2000 });
  else window.setTimeout(make, 500);
}

/** Resolve once the context is running, or immediately if it stays blocked. */
async function ensureRunning(): Promise<AudioContext> {
  const c = ensureCtx();
  if (c.state !== "running") {
    // Await resume(): checking state synchronously right after firing it
    // would drop the first clip after unlock.
    try {
      await c.resume();
    } catch {
      /* still blocked — callers degrade to silence */
    }
  }
  return c;
}

/** The running context for a sound of `reqEpoch`, or null to drop the sound.
 *  Before the first unlock a resume that lands within LATE_MS (the sound of
 *  the unlock tap itself) still plays. A context that has run and is now held
 *  drops the sound at once: its resume can land before the statechange that
 *  reports the recovery, and a sound kept waiting would play stale. */
async function runningFor(reqEpoch: number): Promise<AudioContext | null> {
  const c = ensureCtx();
  if (c.state !== "running" && ranOnce.has(c)) {
    armUnlock();
    if (reqEpoch === epoch) invalidate();
    return null;
  }
  if (c.state !== "running") {
    armUnlock();
    let timer = 0;
    await Promise.race([
      c.resume().catch(() => {}),
      new Promise<void>((r) => { timer = window.setTimeout(r, LATE_MS); }),
    ]);
    window.clearTimeout(timer);
  }
  if (c.state !== "running" || ctx !== c) {
    // a held context: everything asked for meanwhile is late too
    if (reqEpoch === epoch) invalidate();
    return null;
  }
  if (reqEpoch !== epoch || muted) return null;
  ranOnce.add(c);
  return c;
}

// Unlock the context on a user gesture (autoplay policy).
//
// iOS (all browsers there are WebKit, including iPhone Chrome) does not
// reliably unlock audio on `pointerdown`; `touchend`/`click` are the gestures
// that count. Listen on several gesture types and keep listening until the
// context actually reaches "running": a listener that removes itself after a
// failed attempt leaves the page silent for good.
const UNLOCK_EVENTS = ["pointerdown", "touchend", "click", "keydown"] as const;
let unlockArmed = false;

function armUnlock(): void {
  if (unlockArmed) return;
  unlockArmed = true;
  for (const name of UNLOCK_EVENTS) {
    window.addEventListener(name, unlockHandler, { passive: true });
  }
}

function disarmUnlock(): void {
  if (!unlockArmed) return;
  unlockArmed = false;
  for (const name of UNLOCK_EVENTS) {
    window.removeEventListener(name, unlockHandler);
  }
}

function unlockHandler(): void {
  // A context iOS left "interrupted" (after a call, dictation or a trip to
  // the background) can refuse every later resume. A context made inside a
  // gesture may start, so the stuck one is replaced here, synchronously, while
  // the gesture still counts. Decoded clips are AudioBuffers and play in any
  // context.
  if (ctx !== null && (ctx.state as string) === "interrupted") {
    const stuck = ctx;
    ctx = null;
    invalidate();
    void stuck.close().catch(() => {});
  }
  void ensureRunning().then((c) => {
    if (c.state === "running") disarmUnlock();
  });
}

armUnlock();

// Returning from the background can leave the context suspended. Without
// re-arming there would be no listener left to unlock it again, so audio would
// die permanently the first time the player switched apps.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") {
    invalidate();
    return;
  }
  if (ctx !== null && ctx.state !== "running") {
    void ctx.resume().catch(() => {});
    armUnlock();
  }
});

export function isMuted(): boolean {
  return muted;
}

export function setMuted(m: boolean): void {
  muted = m;
  localStorage.setItem(MUTE_KEY, m ? "1" : "0");
  if (m) queue.length = 0;
  for (const cb of muteListeners) cb(m);
}

// Every mute control on screen (the HUD chip, the phone's `…` menu, the Room
// screen's toggle) reads this one store via useMuted, so mounted controls
// cannot drift apart.
const muteListeners = new Set<(m: boolean) => void>();

export function subscribeMuted(cb: (m: boolean) => void): () => void {
  muteListeners.add(cb);
  return () => { muteListeners.delete(cb); };
}

// Bump when clips are regenerated so browsers refetch instead of using
// cached audio from an older voice.
const SOUNDS_VERSION = 9;

/** A clip, fetched and decoded once. A failed speculative fetch (the deal's
 *  prefetch, perhaps offline) is not final: the next demand play retries it
 *  once, while later prefetches leave it alone. A failed demand fetch stays
 *  failed (a missing clip is skipped). */
function loadClip(name: string, speculative = false): Promise<AudioBuffer | null> {
  const cached = clipCache.get(name);
  if (cached) {
    if (speculative) return cached;
    // a demand play awaiting a prefetch that then fails gets its retry too,
    // and a second play waiting meanwhile shares that retry
    return cached.then((buf) => {
      if (buf !== null) return buf;
      if (retryable.delete(name)) return fetchClip(name, false);
      const latest = clipCache.get(name);
      return latest !== undefined && latest !== cached ? latest : null;
    });
  }
  return fetchClip(name, speculative);
}

function fetchClip(name: string, speculative: boolean): Promise<AudioBuffer | null> {
  const p = fetch(`/sounds/${name}.mp3?v=${SOUNDS_VERSION}`)
    .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(`${r.status}`))))
    .then((ab) => ensureCtx().decodeAudioData(ab))
    .catch(() => {
      if (speculative) retryable.add(name);
      return null; // 404 / decode failure: silently skip
    });
  clipCache.set(name, p);
  return p;
}

/** Plays `buffer` now; false when it was dropped instead. */
async function playBuffer(buffer: AudioBuffer, reqEpoch: number): Promise<boolean> {
  const c = await runningFor(reqEpoch);
  if (c === null || live.size >= MAX_VOICES) return false;
  await new Promise<void>((resolve) => {
    const src = c.createBufferSource();
    src.buffer = buffer;
    src.connect(c.destination);
    // the guard inside addVoice keeps a wedged onended from stalling the pump
    const cancel = addVoice(src, buffer.duration * 1000, resolve);
    try {
      src.start();
    } catch {
      cancel();
    }
  });
  return true;
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => window.setTimeout(r, ms));
}

/** Short synthesized click for plays with no voice line (junk dumps). */
function playTick(): void {
  if (muted) return;
  void runningFor(epoch).then((c) => {
    if (c === null || live.size >= MAX_VOICES) return;
    const t = c.currentTime;
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.frequency.value = 2100;
    gain.gain.setValueAtTime(0.07, t);
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.06);
    osc.connect(gain);
    gain.connect(c.destination);
    addVoice(osc, TICK_S * 1000);
    osc.start(t);
    osc.stop(t + TICK_S);
  });
}

/** Enqueue a sequence of clip names (played in order, never overlapping). */
export function play(names: string[]): void {
  if (muted || names.length === 0) return;
  queue.push({ names, at: now(), epoch });
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
      if (seq.epoch !== epoch || now() - seq.at > STALE_MS) continue;
      for (const name of seq.names) {
        if (muted) break;
        const buf = await loadClip(name);
        if (!buf) continue;
        // a dropped clip ends its sequence: the rest would be out of context
        if (!(await playBuffer(buf, seq.epoch))) break;
        await sleep(GAP_MS);
      }
    }
  } finally {
    pumping = false;
  }
}

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

/** Fetch and decode, while the cards are still coming, every clip a
 *  declaration this deal can announce: the trump-rank card of each suit, a
 *  pair and no-trump. A clip is otherwise first fetched when its declaration
 *  lands, so the first call of a rank is heard a network round trip late. */
function prefetchDeclareClips(state: GameState): void {
  if (muted) return;
  const { banker, levels } = state;
  const ranks = banker === null ? new Set(levels) : new Set([levels[banker % 2]]);
  const names: string[] = [VOICE_CLIPS.pair, VOICE_CLIPS.nt];
  for (const rank of ranks) for (const suit of "SHDC") names.push(`${suit}${rank}`);
  for (const name of names) void loadClip(name, true);
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
  if (state.phase === "deal") prefetchDeclareClips(state);
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
        if (first === "BJ" || first === "LJ") play([VOICE_CLIPS.nt]);
        else if (d.cards.length >= 2) play([VOICE_CLIPS.pair, first]);
        else if (first) play([first]);
      }
    }
  }

  // Every newly appeared play gets a sound. Ruffs take priority; a lead is
  // announced by the shape the server sent; followers get a click.
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
    if (isRuff) play([VOICE_CLIPS.ruff]);
    else if (i === 0) {
      // card names only on the LEAD of each trick
      const allTrump =
        trump !== null && n > 0 && p.cards.every((c) => isTrump(c, trump));
      // The SERVER decides the shape: whether pairs form a tractor depends on
      // consecutiveness under the trump ordering, which this side cannot see.
      const isPair = n === 2 && p.cards[0] === p.cards[1];
      const shape = p.shape ?? (n === 1 ? "single" : isPair ? "pair" : "throw");
      if (allTrump) play([VOICE_CLIPS.drawTrump]);
      else if (shape === "single") play([p.cards[0]]);
      else if (shape === "pair") play([VOICE_CLIPS.pair, p.cards[0]]);
      else if (shape === "tractor") play([VOICE_CLIPS.tractor]);
      else play([VOICE_CLIPS.throw]);
    } else playTick(); // followers: just a click (ruffs handled above)
  });
  seenPlays = nextSeen;
}
