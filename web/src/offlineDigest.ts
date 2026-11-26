// The rounds played on the device's own server (offline, or a nearby game)
// since the last online socket: three small counts, kept on the device and
// sent once as an `offline_digest` on the next online socket, then zeroed.
// In the app they live in its native store (UserDefaults), which the
// bundled offline page and the live site share; elsewhere in this origin's
// storage. Every read-change-write takes the origin's Web Lock, so two tabs
// that come online together send the counts once. A page that could share
// the store with another and has no Web Locks leaves it alone. Nothing else
// about an offline round is kept or sent.
import { nativeStore } from "./i18n/locale";
import { isNative } from "./native";
import type { OfflineCounts } from "./telemetry";

export const DIGEST_KEY = "shengji.telemetry.offline";
/** Each count stops here. */
export const MAX_COUNT = 99;

export interface Kv {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
}

const ZERO: OfflineCounts = { rounds_started: 0, rounds_finished: 0, nearby_rounds: 0 };

export function parseCounts(raw: string | null): OfflineCounts {
  const m = /^(\d{1,2}),(\d{1,2}),(\d{1,2})$/.exec(raw ?? "");
  if (!m) return { ...ZERO };
  return { rounds_started: Number(m[1]), rounds_finished: Number(m[2]), nearby_rounds: Number(m[3]) };
}

export function formatCounts(c: OfflineCounts): string {
  const cap = (n: number) => Math.min(MAX_COUNT, Math.max(0, Math.floor(n)));
  return `${cap(c.rounds_started)},${cap(c.rounds_finished)},${cap(c.nearby_rounds)}`;
}

/** The app's native store, else this origin's localStorage, else nothing. */
export function deviceKv(): Kv | null {
  const get = nativeStore("get"), set = nativeStore("set");
  if (get && set) {
    return {
      get: async (key) => {
        const r = await get({ key }) as { value?: unknown } | undefined;
        return typeof r?.value === "string" ? r.value : null;
      },
      set: async (key, value) => { await set({ key, value }); },
    };
  }
  try {
    if (typeof localStorage === "undefined") return null;
    const ls = localStorage;
    return {
      get: async (key) => ls.getItem(key),
      set: async (key, value) => { ls.setItem(key, value); },
    };
  } catch {
    return null;
  }
}

/** The one lock every page of this origin takes around the digest's
 *  read-change-write, so two tabs never send the same counts. */
export const DIGEST_LOCK = "shengji.telemetry.offline";

/** The part of the Web Locks API the digest uses. */
export interface Locks {
  request(name: string, callback: () => Promise<void>): Promise<void>;
}

/** The browser's Web Locks, exclusive and shared by every page of the origin;
 *  null where the API is missing. */
export function webLocks(): Locks | null {
  try {
    const locks = (globalThis.navigator as Navigator | undefined)?.locks;
    if (!locks || typeof locks.request !== "function") return null;
    return { request: (name, callback) => locks.request(name, { mode: "exclusive" }, callback) as Promise<void> };
  } catch {
    return null;
  }
}

export interface DigestDeps {
  kv: () => Kv | null;
  locks: () => Locks | null;
  /** No other page can share the store now: the iOS app runs one page. */
  onePage: () => boolean;
}

export class OfflineDigest {
  private chain: Promise<void> = Promise.resolve();
  private readonly deps: DigestDeps;

  constructor(deps: Partial<DigestDeps> & { kv?: () => Kv | null } = {}) {
    this.deps = { kv: deps.kv ?? deviceKv, locks: deps.locks ?? webLocks, onePage: deps.onePage ?? (() => isNative()) };
  }

  /** One read-change-write at a time: in call order on this page, and under
   *  the origin's lock across pages. A failure changes nothing. `change`
   *  runs after the read and returns null to write nothing. With no lock
   *  where another page could share the store (a browser without Web
   *  Locks), nothing is read or written: neither a count nor a send, and any
   *  stored counts stay as they are. Such a page's device rounds go uncounted. */
  private run(change: (c: OfflineCounts) => OfflineCounts | null): Promise<void> {
    const task = async () => {
      const kv = this.deps.kv();
      if (!kv) return;
      const next = change(parseCounts(await kv.get(DIGEST_KEY)));
      if (next === null) return;
      await kv.set(DIGEST_KEY, formatCounts(next));
    };
    this.chain = this.chain.then(() => {
      const locks = this.deps.locks();
      if (locks) return locks.request(DIGEST_LOCK, task);
      if (!this.deps.onePage()) return undefined;
      return task();
    }).catch(() => undefined);
    return this.chain;
  }

  /** A round on the device started (`nearby`: a nearby game's), or reached its end. */
  count(what: "started" | "finished", nearby: boolean): Promise<void> {
    return this.run((c) => what === "started"
      ? { ...c, rounds_started: c.rounds_started + 1, nearby_rounds: c.nearby_rounds + (nearby ? 1 : 0) }
      : { ...c, rounds_finished: c.rounds_finished + 1 });
  }

  /** Offers any counts to `send`, after the stored ones are read, and takes
   *  them off only when `send` says its transport accepted them; a refusal
   *  (no socket, the page gone offline meanwhile) keeps them for the next
   *  online socket. Nothing is offered when all are zero. The read, the
   *  send and the zeroing are one unit under the lock: another page's drain
   *  or count waits for it, so it neither sends the same counts nor has a
   *  count wiped. */
  drain(send: (c: OfflineCounts) => boolean): Promise<void> {
    return this.run((c) => {
      if (!(c.rounds_started || c.rounds_finished || c.nearby_rounds)) return null;
      return send(c) ? { ...ZERO } : null;
    });
  }
}

export const offlineDigest = new OfflineDigest();
