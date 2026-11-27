// The store's characters: the ones on sale (one App Store product each,
// every colour included, ids the server's `accounts.LOOKS` and
// `COMPANION_PRODUCTS`) and the ones coming, which have a tile and a page
// drawn in their own art but no look id and no product yet, so nobody can
// put one in use or buy it. Each character's colours are its palette's keys
// (`storePalette.ts`), in order.
import { CAT_COLOURS, DRAGON_COLOURS, FOX_COLOURS, LAMB_COLOURS, LION_COLOURS, PANDA_COLOURS, RABBIT_COLOURS } from "./storePalette";
import type { CatColourId, DragonColourId, FoxColourId, LambColourId, LionColourId, PandaColourId, RabbitColourId } from "./storePalette";

export type SoldKind = "lamb" | "panda";

export const SOLD_COLOURS = { lamb: LAMB_COLOURS, panda: PANDA_COLOURS } as const;

export type SoldColourId = LambColourId | PandaColourId;

/** The App Store product of each character on sale. */
export const SOLD_PRODUCTS: Record<SoldKind, string> = {
  lamb: "com.jerryyu.shengji.companion.lamb",
  panda: "com.jerryyu.shengji.companion.panda",
};

/** Characters coming to the store: a tile and a page reading Soon, no product. */
export const SOON = ["rabbit", "cat", "fox", "lion", "dragon"] as const;
export type SoonKind = (typeof SOON)[number];

export type SoonColourId = RabbitColourId | CatColourId | FoxColourId | LionColourId | DragonColourId;

export const SOON_COLOURS = {
  rabbit: RABBIT_COLOURS, cat: CAT_COLOURS, fox: FOX_COLOURS, lion: LION_COLOURS, dragon: DRAGON_COLOURS,
} as const;

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

/** The colour a coming character's tile and page show. */
export const soonColour = (kind: SoonKind): SoonColourId => Object.keys(SOON_COLOURS[kind])[0] as SoonColourId;
