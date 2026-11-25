// The coarse stamps every telemetry batch carries: how many days since this
// device was first seen, which session of the device this is, and the
// page's language. The device keeps only a first-seen calendar date, a
// session counter and the minute of its last activity, in this origin's
// storage; only the buckets are ever sent. Storage that is cleared (a
// browser's site data) starts the device over as new; the iOS app's
// WebView storage persists.

export type DaysBucket = "0" | "1" | "2-7" | "8-30" | "31+";
export type SessionBucket = "1" | "2" | "3-5" | "6+";
export type Lang = "en" | "zh";

/** A gap with no activity longer than this starts a new session. */
export const SESSION_GAP_MS = 30 * 60 * 1000;
/** The session counter stops here: the top bucket is open-ended. */
const MAX_SESSIONS = 999;

export const FIRST_KEY = "shengji.telemetry.first";
export const SESSION_KEY = "shengji.telemetry.session";
/** The first-visit marker older builds kept; a device that has it but no
 *  first-seen date was first seen on an unknown day. */
export const LEGACY_SEEN_KEY = "shengji.telemetry.seen";
/** Marks a device first seen before the first-seen date was kept. */
const LEGACY = "legacy";

export interface Store {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem?(key: string): void;
}

function localStore(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** The local calendar date as YYYY-MM-DD. */
export function dayOf(ms: number): string {
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Whole calendar days from `from` to `to`, both YYYY-MM-DD; null if unreadable. */
export function daysBetween(from: string, to: string): number | null {
  const parse = (s: string) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
    return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : NaN;
  };
  const a = parse(from), b = parse(to);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return Math.round((b - a) / 86_400_000);
}

export function daysBucket(days: number): DaysBucket {
  if (days <= 0) return "0";
  if (days === 1) return "1";
  if (days <= 7) return "2-7";
  if (days <= 30) return "8-30";
  return "31+";
}

export function sessionBucket(n: number): SessionBucket {
  if (n <= 1) return "1";
  if (n === 2) return "2";
  if (n <= 5) return "3-5";
  return "6+";
}

/** The device's first-seen date and session count, read and kept in `store`. */
export class DeviceStamps {
  private readonly store: () => Store | null;
  private readonly clock: () => number;
  private first: string | null | undefined;
  private session: { n: number; last: number } | null | undefined;

  constructor(store: () => Store | null = localStore, clock: () => number = Date.now) {
    this.store = store;
    this.clock = clock;
  }

  /** The first-seen date, set to today on a device with none; LEGACY for a
   *  device an older build already saw; null with no storage. */
  private firstSeen(): string | null {
    if (this.first !== undefined) return this.first;
    const s = this.store();
    this.first = null;
    if (!s) return null;
    try {
      let v = s.getItem(FIRST_KEY);
      if (v === null) {
        v = s.getItem(LEGACY_SEEN_KEY) !== null ? LEGACY : dayOf(this.clock());
        s.setItem(FIRST_KEY, v);
      }
      this.first = v;
    } catch {
      this.first = null;
    }
    return this.first;
  }

  /** The bucket of days since first seen; none for a device first seen
   *  before this was kept, or with no storage. */
  days(): DaysBucket | null {
    const first = this.firstSeen();
    if (first === null || first === LEGACY) return null;
    const d = daysBetween(first, dayOf(this.clock()));
    return d === null ? null : daysBucket(d);
  }

  /** Activity now: a gap over SESSION_GAP_MS since the last starts a new
   *  session. Returns whether this activity started one. */
  touch(): boolean {
    // the first-seen date is read before anything marks the device as seen
    this.firstSeen();
    const now = this.clock();
    const s = this.store();
    if (this.session === undefined) this.session = this.read(s);
    const cur = this.session;
    let started = false;
    if (cur === null || now - cur.last > SESSION_GAP_MS) {
      this.session = { n: Math.min(MAX_SESSIONS, (cur?.n ?? 0) + 1), last: now };
      started = true;
    } else {
      this.session = { n: cur.n, last: now };
    }
    // the minute is enough to time a 30-minute gap
    if (started || Math.floor(now / 60_000) !== Math.floor((cur?.last ?? 0) / 60_000)) this.write(s);
    return started;
  }

  /** The session bucket; none for a legacy device (its count began late)
   *  or with no storage. */
  sessionN(): SessionBucket | null {
    if (this.session === undefined || this.session === null) return null;
    const first = this.firstSeen();
    if (first === null || first === LEGACY) return null;
    return sessionBucket(this.session.n);
  }

  private read(s: Store | null): { n: number; last: number } | null {
    try {
      const m = /^(\d{1,3}):(\d{1,10})$/.exec(s?.getItem(SESSION_KEY) ?? "");
      return m ? { n: Number(m[1]), last: Number(m[2]) * 60_000 } : null;
    } catch {
      return null;
    }
  }

  private write(s: Store | null): void {
    if (!s || !this.session) return;
    try {
      s.setItem(SESSION_KEY, `${this.session.n}:${Math.floor(this.session.last / 60_000)}`);
    } catch {
      /* storage full or blocked: the count holds for this page */
    }
  }
}

export const PLAYED_KEY = "shengji.telemetry.played";

/** A round has been started on this device (online or on the device). */
export function markPlayed(store: Store | null = localStore()): void {
  try {
    if (store && store.getItem(PLAYED_KEY) === null) store.setItem(PLAYED_KEY, "1");
  } catch {
    /* storage blocked */
  }
}

/** Whether this device started a round before now; false with no storage. */
export function playedBefore(store: Store | null = localStore()): boolean {
  try {
    return store ? store.getItem(PLAYED_KEY) !== null : false;
  } catch {
    return false;
  }
}
