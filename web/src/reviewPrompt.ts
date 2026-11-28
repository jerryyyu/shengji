// The App Store rating sheet, asked for once per app version in the iOS app
// only: on a round your team won, from the 2nd ranked win or the 5th casual
// win (online casual, offline and nearby rounds are casual), never in the
// app's first session. The sheet is Apple's own (StoreKit through the
// shell's ShengjiReview plugin), with no prompt of ours before it, and Apple
// may decline to show it.
//
// The counts live in the app's native store (UserDefaults through the
// Preferences plugin): the hosted page and the bundled offline page are two
// origins with two localStorages, and both count toward the same wins. In a
// browser, or a shell without the plugins, nothing is kept or asked.
//
// A session is one stretch of use: a new one starts only after an observed
// absence of SESSION_GAP_MS or more, the app going to the background (or its
// page unloading, as when the app is closed) and then coming back or being
// launched again. Time in the foreground never starts one. A session that went
// wrong while the app was in use (a socket lost, or an action left unanswered,
// past TROUBLE_GRACE_MS of being in view) asks nothing; its wins still count,
// and a later session may ask. An ask is reported as one
// `review_prompt` telemetry event (its trigger and the app version, no ids);
// one made offline, where telemetry is off, goes from the next online page.
import { isNative } from "./native";
import { nativeStore } from "./i18n/locale";
import { subscribeLink, subscribeStalled } from "./link";

export const REVIEW_KEY = "shengji.review";
export const SESSION_GAP_MS = 30 * 60 * 1000;
export const RANKED_WINS = 2;
export const CASUAL_WINS = 5;
/** The ask waits this long after the round-end card appears. */
export const PROMPT_DELAY_MS = 1500;
/** Each count stops here. */
export const MAX_COUNT = 99;
export const REVIEW_PLUGIN = "ShengjiReview";
/** A drop or a stall this soon after the app comes into view is the socket
 *  iOS let die in the background being found and replaced, not trouble. */
export const TROUBLE_GRACE_MS = 10_000;

export type WinKind = "ranked" | "casual";
export type Trigger = "ranked2" | "casual5";

export interface ReviewState {
  /** When the app was first opened (ms since the epoch); 0 before. */
  first: number;
  /** When the app was last seen going away (background, or its page
   *  unloading); 0 while it is in use. */
  away: number;
  /** 1 for the first session, then 2, 3, … */
  session: number;
  ranked: number;
  casual: number;
  /** The session that went wrong in use; 0 for none. */
  troubled: number;
  /** The app version last asked for, and why; null before any ask. */
  prompted: string | null;
  trigger: Trigger | null;
  /** The last ask went out as telemetry. */
  reported: boolean;
}

export const FRESH: ReviewState = {
  first: 0, away: 0, session: 0, ranked: 0, casual: 0, troubled: 0, prompted: null, trigger: null, reported: true,
};

export interface Kv {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
}

function count(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) ? Math.min(MAX_COUNT, Math.max(0, Math.floor(v))) : 0;
}

function time(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) && v > 0 ? Math.floor(v) : 0;
}

export function parseState(raw: string | null): ReviewState {
  let o: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(raw ?? "");
    if (typeof parsed !== "object" || parsed === null) return { ...FRESH };
    o = parsed as Record<string, unknown>;
  } catch {
    return { ...FRESH };
  }
  const trigger = o.trigger === "ranked2" || o.trigger === "casual5" ? o.trigger : null;
  return {
    first: time(o.first), away: time(o.away),
    session: Math.max(0, Math.min(1_000_000, Math.floor(Number(o.session) || 0))),
    ranked: count(o.ranked), casual: count(o.casual),
    troubled: Math.max(0, Math.min(1_000_000, Math.floor(Number(o.troubled) || 0))),
    prompted: typeof o.prompted === "string" && o.prompted.length <= 32 ? o.prompted : null,
    trigger,
    reported: o.reported !== false,
  };
}

/** The app is in use at `now` (a launch, a page load, a return from the
 *  background): the first open starts session 1, and a return after an
 *  observed absence of SESSION_GAP_MS or more starts the next. */
export function touch(s: ReviewState, now: number): ReviewState {
  if (s.first === 0 || s.session === 0) return { ...s, first: s.first || now, away: 0, session: Math.max(1, s.session) };
  if (s.away === 0) return s;
  const session = now - s.away >= SESSION_GAP_MS ? s.session + 1 : s.session;
  return { ...s, away: 0, session };
}

/** The app goes to the background, or its page unloads, at `now`. */
export function leave(s: ReviewState, now: number): ReviewState {
  return s.first === 0 || s.away !== 0 ? s : { ...s, away: now };
}

/** The session in use at `now` went wrong. */
export function markTrouble(s: ReviewState, now: number): ReviewState {
  const t = s.first === 0 ? touch(s, now) : s;
  return t.troubled === t.session ? t : { ...t, troubled: t.session };
}

/** A round your team won, counted; and the ask it earns, if any: a later
 *  session than the first, a count at its bar, and no ask yet for `version`. */
export function recordWin(s: ReviewState, kind: WinKind, version: string | null, now: number):
    { state: ReviewState; trigger: Trigger | null } {
  // a win is played in the foreground: it starts no session itself
  const t = s.first === 0 ? touch(s, now) : s;
  const state = kind === "ranked" ? { ...t, ranked: count(t.ranked + 1) } : { ...t, casual: count(t.casual + 1) };
  if (version === null || state.session < 2 || state.troubled === state.session || state.prompted === version) {
    return { state, trigger: null };
  }
  const trigger: Trigger | null = state.ranked >= RANKED_WINS ? "ranked2" : state.casual >= CASUAL_WINS ? "casual5" : null;
  return { state, trigger };
}

/** The app's version from the `ShengjiApp/<version>` token the shell adds
 *  to the WebView's User-Agent (capacitor.config.ts), or null. */
export function appVersion(userAgent: string): string | null {
  const m = /(?:^|\s)ShengjiApp\/(\d{1,4}\.\d{1,4}(?:\.\d{1,4})?)(?=\s|$)/.exec(userAgent);
  return m ? m[1] : null;
}

export interface ReviewDeps {
  /** The native store, or null (a browser, or a shell without it). */
  kv: () => Kv | null;
  /** The shell's rating call, or null when the plugin is missing. */
  request: () => (() => Promise<unknown>) | null;
  version: () => string | null;
  /** Sends the ask's telemetry; false when it cannot go now (offline). */
  report: (trigger: Trigger, version: string) => boolean;
  now: () => number;
}

export class ReviewPrompt {
  private chain: Promise<unknown> = Promise.resolve();
  private asking = false;
  private readonly deps: ReviewDeps;

  constructor(deps: ReviewDeps) {
    this.deps = deps;
  }

  /** One read-change-write at a time, in call order; a failure changes nothing. */
  private run<T>(change: (s: ReviewState) => { state: ReviewState | null; out: T }, fallback: T): Promise<T> {
    const next = this.chain.then(async () => {
      const kv = this.deps.kv();
      if (!kv) return fallback;
      const { state, out } = change(parseState(await kv.get(REVIEW_KEY)));
      if (state !== null) await kv.set(REVIEW_KEY, JSON.stringify(state));
      return out;
    }).catch(() => fallback);
    this.chain = next;
    return next;
  }

  /** The app is in use now (a launch, a page load, a return to the app). */
  touch(): Promise<void> {
    return this.run((s) => ({ state: this.flushed(touch(s, this.deps.now())), out: undefined }), undefined);
  }

  /** The app is going to the background: the gap is counted from here. */
  away(): Promise<void> {
    return this.run((s) => {
      const next = leave(s, this.deps.now());
      return { state: next === s ? null : next, out: undefined };
    }, undefined);
  }

  /** This session went wrong in use: it asks nothing more. */
  trouble(): Promise<void> {
    return this.run((s) => {
      const next = markTrouble(s, this.deps.now());
      return { state: next === s ? null : next, out: undefined };
    }, undefined);
  }

  /** Your team won a round you finished seated. Resolves the ask it earned,
   *  for `ask` once the round-end card has been up PROMPT_DELAY_MS. */
  roundWon(kind: WinKind): Promise<Trigger | null> {
    if (!isNativeShell(this.deps)) return Promise.resolve(null);
    const version = this.deps.version();
    return this.run((s) => {
      const { state, trigger } = recordWin(s, kind, version, this.deps.now());
      return { state: this.flushed(state), out: trigger };
    }, null);
  }

  /** Asks the shell for the sheet when this version has not been asked and
   *  this session has not gone wrong;
   *  only a request the shell made (`{requested: true}`) marks the version
   *  asked and is reported. One ask at a time: a call while one is in flight
   *  does nothing. */
  async ask(trigger: Trigger): Promise<boolean> {
    if (this.asking) return false;
    const version = this.deps.version();
    const request = this.deps.request();
    if (version === null || request === null) return false;
    this.asking = true;
    try {
      // the session may have gone wrong since the win earned this ask
      const skip = await this.run((s) => ({ state: null, out: s.prompted === version || s.troubled === s.session }), true);
      if (skip) return false;
      let made = false;
      try {
        made = (await request() as { requested?: unknown } | undefined)?.requested === true;
      } catch {
        made = false;
      }
      if (!made) return false;
      return await this.run((s) => (s.prompted === version
        ? { state: null, out: false }
        : { state: this.flushed({ ...s, prompted: version, trigger, reported: false }), out: true }), false);
    } finally {
      this.asking = false;
    }
  }

  /** The state with an unreported ask sent, when telemetry can take it. */
  private flushed(s: ReviewState): ReviewState {
    if (s.reported || s.prompted === null || s.trigger === null) return s;
    let sent = false;
    try {
      sent = this.deps.report(s.trigger, s.prompted);
    } catch {
      sent = false;
    }
    return sent ? { ...s, reported: true } : s;
  }
}

function isNativeShell(deps: ReviewDeps): boolean {
  return deps.kv() !== null && deps.request() !== null;
}

interface PluginBridge {
  isPluginAvailable?: (name: string) => boolean;
  registerPlugin?: (name: string) => Record<string, ((o?: unknown) => Promise<unknown>) | undefined>;
  Plugins?: Record<string, Record<string, ((o?: unknown) => Promise<unknown>) | undefined> | undefined>;
}

/** The shell's ShengjiReview.request, or null in a browser or a shell
 *  without the plugin (every app up to 1.0.2). */
export function nativeRequest(): (() => Promise<unknown>) | null {
  if (!isNative()) return null;
  const cap = (window as unknown as { Capacitor?: PluginBridge }).Capacitor;
  if (!cap) return null;
  try {
    if (typeof cap.isPluginAvailable === "function" && !cap.isPluginAvailable(REVIEW_PLUGIN)) return null;
    const proxy = cap.registerPlugin?.(REVIEW_PLUGIN) ?? cap.Plugins?.[REVIEW_PLUGIN];
    const fn = proxy?.request;
    return typeof fn === "function" ? () => fn() : null;
  } catch {
    return null;
  }
}

/** The Preferences plugin as a key-value store, or null outside the app. */
export function nativeKv(): Kv | null {
  const get = nativeStore("get"), set = nativeStore("set");
  if (!get || !set) return null;
  return {
    get: async (key) => {
      const r = await get({ key }) as { value?: unknown } | undefined;
      return typeof r?.value === "string" ? r.value : null;
    },
    set: async (key, value) => { await set({ key, value }); },
  };
}

function liveVersion(): string | null {
  try {
    return typeof navigator === "undefined" ? null : appVersion(navigator.userAgent);
  } catch {
    return null;
  }
}

let reporter: (trigger: Trigger, version: string) => boolean = () => false;

/** Where an ask's telemetry goes (telemetry.ts sets it; false offline). */
export function setReviewReporter(fn: (trigger: Trigger, version: string) => boolean): void {
  reporter = fn;
}

export const reviewPrompt = new ReviewPrompt({
  kv: nativeKv,
  request: nativeRequest,
  version: liveVersion,
  report: (trigger, version) => reporter(trigger, version),
  now: () => Date.now(),
});

/** Calls `mark` when the socket is lost or an action goes unanswered while
 *  the page is in view and has been for TROUBLE_GRACE_MS; returns the
 *  unsubscribe. */
export function watchTrouble(mark: () => void, now: () => number): () => void {
  const inView = () => document.visibilityState !== "hidden";
  let since = now();
  const shown = () => { if (inView()) since = now(); };
  const check = () => { if (inView() && now() - since >= TROUBLE_GRACE_MS) mark(); };
  document.addEventListener("visibilitychange", shown);
  const offLink = subscribeLink((ev) => { if (ev.kind === "down" && !ev.identity) check(); });
  const offStall = subscribeStalled((on) => { if (on) check(); });
  return () => {
    document.removeEventListener("visibilitychange", shown);
    offLink();
    offStall();
  };
}

/** Starts session keeping in the app: this page load, and each return to
 *  the app, is a moment of use; going to the background marks the gap. */
export function startReviewSessions(): void {
  if (typeof document === "undefined" || nativeKv() === null) return;
  void reviewPrompt.touch();
  try {
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") void reviewPrompt.away();
      else void reviewPrompt.touch();
    });
    window.addEventListener("pagehide", () => { void reviewPrompt.away(); });
    watchTrouble(() => { void reviewPrompt.trouble(); }, () => Date.now());
  } catch {
    /* no document events */
  }
}
