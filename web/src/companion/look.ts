// A companion look travels as "<companion>/<colour>" (the server's
// `accounts.LOOKS`, `DEFAULT_COMPANION`, `DEFAULT_COLOUR`, `LOOK_UNLOCKS`,
// mirrored here by hand and held to them by server/tests/test_look.py;
// each companion's colours are its palette's keys, in order). A
// seat with no look, or one this client cannot draw, shows the default; a
// bot shows an initial instead. A guest's own look is drawn from its device
// key (`freeLook`, the server's `accounts.free_look`).
import { TRACTOR_COLOURS } from "./palette";
import type { TractorColourId } from "./palette";
import { BUN_COLOURS, CHICK_COLOURS, SPARROW_COLOURS } from "./storePalette";
import type { BunColourId, ChickColourId, SparrowColourId } from "./storePalette";
import { SOLD_COLOURS, SOLD_PRODUCTS } from "./characters";
import type { SoldColourId, SoldKind } from "./characters";

export const DEFAULT_COMPANION = "tractor";
export const DEFAULT_COLOUR = "red";
export const DEFAULT_LOOK = `${DEFAULT_COMPANION}/${DEFAULT_COLOUR}`;

export type CompanionKind = "tractor" | "bun" | "chick" | "sparrow" | SoldKind;
export type Colour = TractorColourId | BunColourId | ChickColourId | SparrowColourId | SoldColourId;

/** Every companion this client draws, in Collection order, each with its
 *  colours in Collection order. */
export const COMPANIONS: Record<CompanionKind, readonly Colour[]> = {
  tractor: Object.keys(TRACTOR_COLOURS) as Colour[],
  bun: Object.keys(BUN_COLOURS) as Colour[],
  chick: Object.keys(CHICK_COLOURS) as Colour[],
  sparrow: Object.keys(SPARROW_COLOURS) as Colour[],
  lamb: Object.keys(SOLD_COLOURS.lamb) as Colour[],
  panda: Object.keys(SOLD_COLOURS.panda) as Colour[],
};

/** The companions sold in the app, each one App Store product with every
 *  colour included (the server's `accounts.COMPANION_PRODUCTS`). */
export const COMPANION_PRODUCTS: Partial<Record<CompanionKind, string>> = SOLD_PRODUCTS;

/** The companions free to everyone, in Collection order. */
export const FREE_KINDS = (Object.keys(COMPANIONS) as CompanionKind[]).filter((k) => !(k in SOLD_PRODUCTS));

export const COMPANION_KINDS = Object.keys(COMPANIONS) as CompanionKind[];

export const isKind = (raw: unknown): raw is CompanionKind =>
  typeof raw === "string" && Object.prototype.hasOwnProperty.call(COMPANIONS, raw);

export type UnlockCount = "rounds" | "ranked_wins" | "ranked_games";

/** What unlocks a look; a look not listed is free from the start. */
export const LOOK_UNLOCKS: Record<string, { count: UnlockCount; of: number }> = {
  "tractor/yellow": { count: "ranked_wins", of: 10 },
  "tractor/orange": { count: "ranked_wins", of: 25 },
  "tractor/jade": { count: "ranked_wins", of: 50 },
  "tractor/porcelain": { count: "ranked_wins", of: 100 },
  "tractor/ink": { count: "ranked_wins", of: 1000 },
};

/** Where your own screen draws companions at the table (the server's
 *  `accounts.COMPANION_MODES`); the first is the default. */
export const COMPANION_MODES = ["individual", "team", "off"] as const;
export type CompanionMode = (typeof COMPANION_MODES)[number];

export interface Look {
  kind: CompanionKind;
  colour: Colour;
}

/** The look a seat shows: its own when this client can draw it, else the default. */
export function parseLook(raw: unknown): Look {
  if (typeof raw === "string") {
    const [kind, colour, extra] = raw.split("/");
    const colours = (COMPANIONS as Record<string, readonly string[]>)[kind];
    if (extra === undefined && colours?.includes(colour)) {
      return { kind: kind as CompanionKind, colour: colour as Colour };
    }
  }
  return { kind: DEFAULT_COMPANION, colour: DEFAULT_COLOUR };
}

export const lookId = (l: Look): string => `${l.kind}/${l.colour}`;

/** One look as the Collection lists it (the server's `/api/me` `looks`). */
export interface LookEntry {
  id: string;
  unlocked: boolean;
  needs: { count: UnlockCount; of: number } | null;
  /** The App Store product that sells it, null when it is not sold. */
  product?: string | null;
}

/** Every look with whether `progress` has unlocked it: the server's list
 *  when it sent one, else this client's own reading of the same rules (a
 *  guest, an older server, no connection). A sold companion is listed only
 *  when the server listed it (an owner, or an account the store is on for),
 *  and unlocked only by the server's word. */
export function lookCatalogue(progress: Partial<Record<UnlockCount, number>>, equipped: string,
                              fromServer?: readonly LookEntry[] | null): LookEntry[] {
  const known = new Map((fromServer ?? []).map((e) => [e.id, e]));
  const out: LookEntry[] = [];
  for (const [kind, colours] of Object.entries(COMPANIONS)) {
    for (const colour of colours) {
      const id = `${kind}/${colour}`;
      const rule = LOOK_UNLOCKS[id] ?? null;
      const served = known.get(id);
      const product = COMPANION_PRODUCTS[kind as CompanionKind] ?? null;
      if (product !== null && !served) continue;
      const unlocked = served ? served.unlocked
        : rule === null || id === equipped || (progress[rule.count] ?? 0) >= rule.of;
      out.push({ id, unlocked, needs: rule, product });
    }
  }
  return out;
}

/** A 32-bit hash of `text`: FNV-1a over its UTF-8 bytes, then the murmur3
 *  finaliser (the server's `accounts._look_hash`, held to it by the shared
 *  vectors in look.test.ts). */
function lookHash(text: string): number {
  let h = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(text)) h = Math.imul(h ^ byte, 0x01000193) >>> 0;
  h ^= h >>> 16;
  h = Math.imul(h, 0x85ebca6b) >>> 0;
  h ^= h >>> 13;
  h = Math.imul(h, 0xc2b2ae35) >>> 0;
  return (h ^ (h >>> 16)) >>> 0;
}

/** A free look picked by `seed` among the colours free from the start: a
 *  companion first, then one of its colours (the server's `free_look`). */
export function freeLook(seed: string): string {
  const h = lookHash(seed);
  const kind = FREE_KINDS[h % FREE_KINDS.length];
  const colours = COMPANIONS[kind].filter((c) => !(`${kind}/${c}` in LOOK_UNLOCKS));
  return `${kind}/${colours[Math.floor(h / FREE_KINDS.length) % colours.length]}`;
}

/** The look a guest's seat shows: the one its device key draws (the
 *  server's `accounts.guest_look`). */
export const guestLookFor = (device: string): string => freeLook(`guest:${device}`);

/** The Collection's Yours in order of use: the character in use first, then
 *  the others by the latest use of any of their looks (`recent`, the latest
 *  first), then those never used in Collection order (the order of `kinds`). */
export function yoursOrder(kinds: readonly CompanionKind[], worn: CompanionKind,
                           recent: readonly string[] | undefined): CompanionKind[] {
  const used = (recent ?? []).filter((id) => lookId(parseLook(id)) === id).map((id) => parseLook(id).kind);
  const rank = (k: CompanionKind) => (k === worn ? -1 : used.includes(k) ? used.indexOf(k) : used.length);
  return [...kinds].sort((a, b) => rank(a) - rank(b));
}
