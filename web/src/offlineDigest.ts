// The rounds played on the device's own server (offline, or a nearby game)
// since the last online socket: three small counts, kept on the device and
// sent once as an `offline_digest` on the next online socket, then zeroed.
// In the app they live in its native store (UserDefaults), which the
// bundled offline page and the live site share; elsewhere in this origin's
// storage. Nothing else about an offline round is kept or sent.
import { nativeStore } from "./i18n/locale";
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

export class OfflineDigest {
  private chain: Promise<void> = Promise.resolve();
  private readonly kv: () => Kv | null;

  constructor(kv: () => Kv | null = deviceKv) {
    this.kv = kv;
  }

  /** One read-change-write at a time, in call order; a failure changes nothing. */
  private run(change: (c: OfflineCounts) => OfflineCounts | null, after?: (c: OfflineCounts) => void): Promise<void> {
    this.chain = this.chain.then(async () => {
      const kv = this.kv();
      if (!kv) return;
      const was = parseCounts(await kv.get(DIGEST_KEY));
      const next = change(was);
      if (next === null) return;
      await kv.set(DIGEST_KEY, formatCounts(next));
      after?.(was);
    }).catch(() => undefined);
    return this.chain;
  }

  /** A round on the device started (`nearby`: a nearby game's), or reached its end. */
  count(what: "started" | "finished", nearby: boolean): Promise<void> {
    return this.run((c) => what === "started"
      ? { ...c, rounds_started: c.rounds_started + 1, nearby_rounds: c.nearby_rounds + (nearby ? 1 : 0) }
      : { ...c, rounds_finished: c.rounds_finished + 1 });
  }

  /** Hands any counts to `send` and zeroes them; nothing when all are zero. */
  drain(send: (c: OfflineCounts) => void): Promise<void> {
    return this.run((c) => (c.rounds_started || c.rounds_finished || c.nearby_rounds ? { ...ZERO } : null),
                    (was) => send(was));
  }
}

export const offlineDigest = new OfflineDigest();
