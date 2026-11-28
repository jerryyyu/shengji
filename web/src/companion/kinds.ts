// Each companion's drawing, in one table: its markup builder, its round
// portrait, where its sleeping z rises from, how long its signature
// reaction runs, and its colours' names. `Companion.tsx` and the Collection
// read only this. The coming store characters are drawn here too, so their
// tiles and pages show their own art; they have no look id (look.ts).
import { BUN_COLOURS, CAT_COLOURS, CHICK_COLOURS, DRAGON_COLOURS, FOX_COLOURS, LAMB_COLOURS, LION_COLOURS,
  PANDA_COLOURS, RABBIT_COLOURS, SPARROW_COLOURS } from "./storePalette";
import { TRACTOR_COLOURS } from "./palette";
import type { TractorColourId } from "./palette";
import { tractorMarkup, tractorPortraitUrl } from "./Tractor";
import { bunMarkup, bunPortraitUrl, BUN_Z } from "./Bun";
import { chickMarkup, chickPortraitUrl, CHICK_Z } from "./Chick";
import { sparrowMarkup, sparrowPortraitUrl, SPARROW_Z } from "./Sparrow";
import { lambMarkup, lambPortraitUrl, LAMB_Z } from "./Lamb";
import { pandaMarkup, pandaPortraitUrl, PANDA_Z } from "./Panda";
import { rabbitMarkup, rabbitPortraitUrl, RABBIT_Z } from "./Rabbit";
import { catMarkup, catPortraitUrl, CAT_Z } from "./LuckyCat";
import { foxMarkup, foxPortraitUrl, FOX_Z } from "./Fox";
import { lionMarkup, lionPortraitUrl, LION_Z } from "./Lion";
import { dragonMarkup, dragonPortraitUrl, DRAGON_Z } from "./Dragon";
import type { CharOpts } from "./rig";
import type { SoonColourId, SoonKind } from "./characters";
import type { Colour, CompanionKind } from "./look";

/** Everything drawn: the companions a look can name, and the coming ones. */
export type DrawnKind = CompanionKind | SoonKind;
export type DrawnColour = Colour | SoonColourId;

type Name = { en: string; zh: string; hant: string };

export interface Drawing {
  markup(colour: DrawnColour, id: string, opts: CharOpts): string;
  portraitUrl(colour: DrawnColour, small: boolean): string;
  /** Where the sleeping z rises from, in the 400 box. */
  z: readonly [number, number];
  /** How long the signature reaction (`react`) runs, as its CSS does: its
   *  longest part, that part's delay included. */
  reactMs: number;
  /** Spoken only (a swatch's label), never drawn. */
  colourName(colour: DrawnColour): Name;
  /** The Tractor keeps its own hop and cheer (companion.css); the drawn
   *  characters take `cmp-char`'s (companion.store.css). */
  char: boolean;
}

/** A drawn character from its builders and its palette; a colour it does
 *  not have is drawn as its first. */
function drawn<T extends Record<string, { name: Name }>>(table: T, z: readonly [number, number], reactMs: number,
  markup: (colour: keyof T & string, id: string, o: CharOpts) => string,
  portraitUrl: (colour: keyof T & string, small: boolean) => string): Drawing {
  const first = Object.keys(table)[0] as keyof T & string;
  const own = (colour: DrawnColour) => (Object.prototype.hasOwnProperty.call(table, colour) ? colour : first) as keyof T & string;
  return {
    markup: (colour, id, o) => markup(own(colour), id, o),
    portraitUrl: (colour, small) => portraitUrl(own(colour), small),
    z,
    reactMs,
    colourName: (colour) => table[own(colour)].name,
    char: true,
  };
}

const TRACTOR: Drawing = {
  markup: (colour, id, o) => tractorMarkup(colour as TractorColourId, id,
    { ...o, eyes: o.pose === "sleep" ? "sleep" : "open", rider: true }),
  portraitUrl: (colour, small) => tractorPortraitUrl(colour as TractorColourId, small),
  z: [300, 80],
  reactMs: 1600,
  colourName: (colour) => (TRACTOR_COLOURS[colour as TractorColourId] ?? TRACTOR_COLOURS.red).name,
  char: false,
};

export const DRAWINGS: Record<DrawnKind, Drawing> = {
  tractor: TRACTOR,
  bun: drawn(BUN_COLOURS, BUN_Z, 1600, bunMarkup, bunPortraitUrl),
  chick: drawn(CHICK_COLOURS, CHICK_Z, 1500, chickMarkup, chickPortraitUrl),
  sparrow: drawn(SPARROW_COLOURS, SPARROW_Z, 1800, sparrowMarkup, sparrowPortraitUrl),
  lamb: drawn(LAMB_COLOURS, LAMB_Z, 1500, lambMarkup, lambPortraitUrl),
  panda: drawn(PANDA_COLOURS, PANDA_Z, 1900, pandaMarkup, pandaPortraitUrl),
  rabbit: drawn(RABBIT_COLOURS, RABBIT_Z, 2400, rabbitMarkup, rabbitPortraitUrl),
  cat: drawn(CAT_COLOURS, CAT_Z, 2200, catMarkup, catPortraitUrl),
  fox: drawn(FOX_COLOURS, FOX_Z, 2000, foxMarkup, foxPortraitUrl),
  lion: drawn(LION_COLOURS, LION_Z, 2500, lionMarkup, lionPortraitUrl),
  dragon: drawn(DRAGON_COLOURS, DRAGON_Z, 2400, dragonMarkup, dragonPortraitUrl),
};

