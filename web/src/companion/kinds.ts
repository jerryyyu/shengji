// Each companion's drawing, in one table: its markup builder, its round
// portrait, where its sleeping z rises from, and the name of its signature
// reaction. `Companion.tsx` and the Collection read only this.
import { BUN_COLOURS, CHICK_COLOURS, SPARROW_COLOURS } from "./storePalette";
import type { BunColourId, ChickColourId, SparrowColourId } from "./storePalette";
import { TRACTOR_COLOURS } from "./palette";
import type { TractorColourId } from "./palette";
import { tractorMarkup, tractorPortraitUrl } from "./Tractor";
import { bunMarkup, bunPortraitUrl, BUN_Z } from "./Bun";
import { chickMarkup, chickPortraitUrl, CHICK_Z } from "./Chick";
import { sparrowMarkup, sparrowPortraitUrl, SPARROW_Z } from "./Sparrow";
import type { CharOpts } from "./rig";
import { colourway } from "./characters";
import type { SoldKind } from "./characters";
import type { Colour, CompanionKind } from "./look";

export interface Drawing {
  markup(colour: Colour, id: string, opts: CharOpts): string;
  portraitUrl(colour: Colour, small: boolean): string;
  /** Where the sleeping z rises from, in the 400 box. */
  z: readonly [number, number];
  /** Spoken only (a swatch's label), never drawn. */
  colourName(colour: Colour): { en: string; zh: string; hant: string };
  /** The Tractor keeps its own hop and cheer (companion.css); the drawn
   *  characters take `cmp-char`'s (companion.store.css). */
  char: boolean;
}

/** A store character drawn as the Tractor in its colourway's stand-in
 *  colour, until its own art lands (characters.ts). */
function standIn(kind: SoldKind): Drawing {
  const tractor = (colour: Colour) => colourway(kind, colour).standIn;
  return {
    markup: (colour, id, o) => tractorMarkup(tractor(colour), id,
      { ...o, eyes: o.pose === "sleep" ? "sleep" : "open", rider: false }),
    portraitUrl: (colour, small) => tractorPortraitUrl(tractor(colour), small),
    z: [300, 80],
    colourName: (colour) => colourway(kind, colour).name,
    char: false,
  };
}

const named = <T extends Record<string, { name: { en: string; zh: string; hant: string } }>>(table: T, fallback: keyof T) =>
  (colour: Colour) => (table[colour as keyof T] ?? table[fallback]).name;

export const DRAWINGS: Record<CompanionKind, Drawing> = {
  tractor: {
    markup: (colour, id, o) => tractorMarkup(colour as TractorColourId, id,
      { ...o, eyes: o.pose === "sleep" ? "sleep" : "open", rider: true }),
    portraitUrl: (colour, small) => tractorPortraitUrl(colour as TractorColourId, small),
    z: [300, 80],
    colourName: named(TRACTOR_COLOURS, "red"),
    char: false,
  },
  bun: {
    markup: (colour, id, o) => bunMarkup(colour as BunColourId, id, o),
    portraitUrl: (colour, small) => bunPortraitUrl(colour as BunColourId, small),
    z: BUN_Z,
    colourName: named(BUN_COLOURS, "plain"),
    char: true,
  },
  chick: {
    markup: (colour, id, o) => chickMarkup(colour as ChickColourId, id, o),
    portraitUrl: (colour, small) => chickPortraitUrl(colour as ChickColourId, small),
    z: CHICK_Z,
    colourName: named(CHICK_COLOURS, "yellow"),
    char: true,
  },
  sparrow: {
    markup: (colour, id, o) => sparrowMarkup(colour as SparrowColourId, id, o),
    portraitUrl: (colour, small) => sparrowPortraitUrl(colour as SparrowColourId, small),
    z: SPARROW_Z,
    colourName: named(SPARROW_COLOURS, "tree"),
    char: true,
  },
  lamb: standIn("lamb"),
  panda: standIn("panda"),
};
