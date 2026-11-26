// The store's characters: the ones on sale (one App Store product each,
// every colour included, ids the server's `accounts.LOOKS` and
// `COMPANION_PRODUCTS`) and the ones coming, which have a tile and a page
// but no product yet. Until each character's own art lands it is drawn as
// the Tractor in the colour its `standIn` names, so every id already travels
// and renders; the art replaces `standIn` and keeps the ids.
import type { TractorColourId } from "./palette";

export type SoldKind = "lamb" | "panda";

export interface Colourway {
  standIn: TractorColourId;
  /** Spoken only (the swatch's label), never drawn. */
  name: { en: string; zh: string; hant: string };
}

export const SOLD_COLOURS = {
  lamb: {
    newyear: { standIn: "red", name: { en: "New Year", zh: "新年", hant: "新年" } },
    jade: { standIn: "jade", name: { en: "Jade", zh: "翡翠", hant: "翡翠" } },
    ink: { standIn: "ink", name: { en: "Ink wash", zh: "水墨", hant: "水墨" } },
    lacquer: { standIn: "orange", name: { en: "Lacquer red", zh: "朱漆", hant: "朱漆" } },
  },
  panda: {
    classic: { standIn: "porcelain", name: { en: "Classic", zh: "黑白", hant: "黑白" } },
    russet: { standIn: "orange", name: { en: "Russet", zh: "小熊猫棕", hant: "小熊貓棕" } },
    ink: { standIn: "ink", name: { en: "Ink wash", zh: "水墨", hant: "水墨" } },
    gilded: { standIn: "yellow", name: { en: "Gold dust", zh: "洒金", hant: "灑金" } },
  },
} as const satisfies Record<SoldKind, Record<string, Colourway>>;

export type SoldColourId = keyof (typeof SOLD_COLOURS)["lamb"] | keyof (typeof SOLD_COLOURS)["panda"];

export function colourway(kind: SoldKind, colour: string): Colourway {
  const set = SOLD_COLOURS[kind] as Record<string, Colourway>;
  return set[colour] ?? Object.values(set)[0];
}

/** The App Store product of each character on sale. */
export const SOLD_PRODUCTS: Record<SoldKind, string> = {
  lamb: "com.jerryyu.shengji.companion.lamb",
  panda: "com.jerryyu.shengji.companion.panda",
};

/** Characters coming to the store: a tile and a page reading Soon, no product. */
export const SOON = ["rabbit", "cat", "fox", "lion", "dragon"] as const;
export type SoonKind = (typeof SOON)[number];

/** Each store character's own name. */
export const STORE_NAMES: Record<SoldKind | SoonKind, { en: string; zh: string; hant: string }> = {
  lamb: { en: "Spring Lamb", zh: "小羊", hant: "小羊" },
  panda: { en: "Baby Panda", zh: "熊猫宝宝", hant: "熊貓寶寶" },
  rabbit: { en: "Jade Rabbit", zh: "玉兔", hant: "玉兔" },
  cat: { en: "Lucky Cat", zh: "招财猫", hant: "招財貓" },
  fox: { en: "Fortune Fox", zh: "福狐", hant: "福狐" },
  lion: { en: "Dancing Lion", zh: "醒狮", hant: "醒獅" },
  dragon: { en: "Little Dragon", zh: "小龙", hant: "小龍" },
};

/** The stand-in a coming character is drawn as until its art lands. */
export const SOON_STAND_IN: Record<SoonKind, TractorColourId> = {
  rabbit: "porcelain", cat: "yellow", fox: "orange", lion: "red", dragon: "green",
};
