// A companion look travels as "<companion>/<colour>" (the server's
// `accounts.LOOKS`, `DEFAULT_COMPANION`, `DEFAULT_COLOUR`, `LOOK_UNLOCKS`,
// mirrored here by hand and held to them by server/tests/test_look.py;
// each companion's colours are its palette's keys, in order). A
// seat with no look, or one this client cannot draw, shows the default; a
// bot shows an initial instead.
import { TRACTOR_COLOURS } from "./palette";
import type { TractorColourId } from "./palette";
import { BUN_COLOURS, CHICK_COLOURS, SPARROW_COLOURS } from "./storePalette";
import type { BunColourId, ChickColourId, SparrowColourId } from "./storePalette";

export const DEFAULT_COMPANION = "tractor";
export const DEFAULT_COLOUR = "red";
export const DEFAULT_LOOK = `${DEFAULT_COMPANION}/${DEFAULT_COLOUR}`;

export type CompanionKind = "tractor" | "bun" | "chick" | "sparrow";
export type Colour = TractorColourId | BunColourId | ChickColourId | SparrowColourId;

/** Every companion this client draws, in Collection order, each with its
 *  colours in Collection order. */
export const COMPANIONS: Record<CompanionKind, readonly Colour[]> = {
  tractor: Object.keys(TRACTOR_COLOURS) as Colour[],
  bun: Object.keys(BUN_COLOURS) as Colour[],
  chick: Object.keys(CHICK_COLOURS) as Colour[],
  sparrow: Object.keys(SPARROW_COLOURS) as Colour[],
};

export const COMPANION_KINDS = Object.keys(COMPANIONS) as CompanionKind[];

export const isKind = (raw: unknown): raw is CompanionKind =>
  typeof raw === "string" && Object.prototype.hasOwnProperty.call(COMPANIONS, raw);

export type UnlockCount = "rounds" | "ranked_wins";

/** What unlocks a look; a look not listed is free from the start. */
export const LOOK_UNLOCKS: Record<string, { count: UnlockCount; of: number }> = {
  "tractor/yellow": { count: "rounds", of: 10 },
  "tractor/orange": { count: "rounds", of: 25 },
  "tractor/jade": { count: "rounds", of: 50 },
  "tractor/porcelain": { count: "rounds", of: 100 },
  "tractor/ink": { count: "ranked_wins", of: 1 },
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
}

/** Every look with whether `progress` has unlocked it: the server's list
 *  when it sent one, else this client's own reading of the same rules (a
 *  guest, an older server, no connection). */
export function lookCatalogue(progress: Partial<Record<UnlockCount, number>>, equipped: string,
                              fromServer?: readonly LookEntry[] | null): LookEntry[] {
  const known = new Map((fromServer ?? []).map((e) => [e.id, e]));
  const out: LookEntry[] = [];
  for (const [kind, colours] of Object.entries(COMPANIONS)) {
    for (const colour of colours) {
      const id = `${kind}/${colour}`;
      const rule = LOOK_UNLOCKS[id] ?? null;
      const served = known.get(id);
      const unlocked = served ? served.unlocked
        : rule === null || id === equipped || (progress[rule.count] ?? 0) >= rule.of;
      out.push({ id, unlocked, needs: rule });
    }
  }
  return out;
}
