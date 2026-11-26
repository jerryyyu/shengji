// The drawn companions' colours (every one but the Tractor, whose table is
// `palette.ts`): the one table their art reads. A colour is
// a palette swap on the same drawing, and a character's four colours come
// with it. A four-tone entry runs highlight, base, low, core shadow; `disc`
// is the portrait's ground, each colour's own so two portraits read apart at
// 24 px. The ids are the `<colour>` half of a look ("bun/taro").

type Tones = readonly [string, string, string, string];
type Pair = readonly [string, string];
type Name = { en: string; zh: string; hant: string };

export interface SparrowColour {
  belly: Tones;
  /** The wing and tail, light to dark. */
  wing: readonly [string, string, string];
  cap: readonly [string, string, string];
  beak: string;
  leg: string;
  /** The pale bars on the wing. */
  bar: string;
  blush: string;
  disc: Pair;
  name: Name;
}

export const SPARROW_COLOURS = {
  tree: { belly: ["#fffaf0", "#fbf0dc", "#e8d3b4", "#c0a391"], wing: ["#cd8a56", "#9a5a2c", "#6b3a1a"], cap: ["#c27a46", "#8f4d24", "#5e2f14"],
          beak: "#f0b547", leg: "#e2a23c", bar: "#fbf0dc", blush: "#f08f84", disc: ["#4a7fa3", "#16304a"],
          name: { en: "Tree sparrow", zh: "麻雀", hant: "麻雀" } },
  java: { belly: ["#ffffff", "#eef0f3", "#cfd4dc", "#9aa3b3"], wing: ["#aab3c2", "#7d8798", "#525c6e"], cap: ["#4a4d58", "#262830", "#101116"],
          beak: "#f47a8a", leg: "#f4a0a8", bar: "#eef0f3", blush: "#f08f84", disc: ["#f0c25a", "#b06f1a"],
          name: { en: "Java grey", zh: "文鸟灰", hant: "文鳥灰" } },
  snow: { belly: ["#ffffff", "#fbf8f2", "#e8e0d6", "#bcaec6"], wing: ["#f6f1ea", "#e2d8cc", "#c4b6a8"], cap: ["#fdfaf5", "#efe7dc", "#d6c9bb"],
          beak: "#f47a8a", leg: "#f4a0a8", bar: "#ffffff", blush: "#f08f84", disc: ["#b42a31", "#5e0d18"],
          name: { en: "Snow", zh: "雪白", hant: "雪白" } },
  oriole: { belly: ["#fff8c8", "#fbdc5a", "#e2ac2a", "#a87414"], wing: ["#55505c", "#2a2730", "#121016"], cap: ["#fde98a", "#f0c23a", "#c48f18"],
            beak: "#f08a7a", leg: "#8a8f95", bar: "#fbdc5a", blush: "#f0806a", disc: ["#1f6157", "#0b2a28"],
            name: { en: "Oriole", zh: "黄鹂", hant: "黃鸝" } },
} as const satisfies Record<string, SparrowColour>;

export type SparrowColourId = keyof typeof SPARROW_COLOURS;

export interface ChickColour {
  down: Tones;
  /** The wings and the tuft. */
  wing: string;
  beak: string;
  leg: string;
  blush: string;
  disc: Pair;
  name: Name;
}

export const CHICK_COLOURS = {
  yellow: { down: ["#fffbd6", "#ffe680", "#f3c43c", "#c08a1c"], wing: "#f5c63e", beak: "#f58a3c", leg: "#f08a3c", blush: "#f58f7a",
            disc: ["#35957c", "#0b2a28"], name: { en: "Chick yellow", zh: "鹅黄", hant: "鵝黃" } },
  cream: { down: ["#ffffff", "#fbf6ec", "#eadfce", "#c2b1c4"], wing: "#eadfce", beak: "#f5a33c", leg: "#f5a33c", blush: "#f08f84",
           disc: ["#b42a31", "#5e0d18"], name: { en: "Cream", zh: "奶白", hant: "奶白" } },
  cocoa: { down: ["#e6b98c", "#c08a58", "#8f5a30", "#5e3414"], wing: "#8f5a30", beak: "#f5c23c", leg: "#f0a83c", blush: "#f0806a",
           disc: ["#f0c25a", "#b06f1a"], name: { en: "Cocoa", zh: "可可", hant: "可可" } },
  ink: { down: ["#7b7583", "#47424e", "#27232d", "#0e0c12"], wing: "#27232d", beak: "#f5c23c", leg: "#c9963a", blush: "#d9707a",
         disc: ["#efe9da", "#b9ae96"], name: { en: "Silkie black", zh: "乌骨", hant: "烏骨" } },
} as const satisfies Record<string, ChickColour>;

export type ChickColourId = keyof typeof CHICK_COLOURS;

export interface BunColour {
  dough: Tones;
  /** The pleat lines at the crown. */
  pleat: string;
  blush: string;
  /** The bamboo steamer, lit side to shade side, and its bands. */
  steamer: readonly [string, string, string];
  band: string;
  disc: Pair;
  name: Name;
}

const BAMBOO = ["#f6dba4", "#dcb066", "#a8793a"] as const;

export const BUN_COLOURS = {
  plain: { dough: ["#ffffff", "#fbf6ec", "#eadfce", "#c2b1c4"], pleat: "#cdbfa8", blush: "#f08f84", steamer: BAMBOO, band: "#8a5a26",
           disc: ["#b42a31", "#5e0d18"], name: { en: "Plain", zh: "白面", hant: "白麵" } },
  custard: { dough: ["#fff8d2", "#fbe08a", "#eab94e", "#b88420"], pleat: "#c9963a", blush: "#f0806a", steamer: BAMBOO, band: "#8a5a26",
             disc: ["#1f6157", "#0b2a28"], name: { en: "Custard", zh: "奶黄", hant: "奶黃" } },
  taro: { dough: ["#f6ecff", "#dcc6f2", "#ad90d2", "#70579a"], pleat: "#8d70ba", blush: "#f08fa8", steamer: BAMBOO, band: "#8a5a26",
          disc: ["#f0c25a", "#b06f1a"], name: { en: "Taro", zh: "香芋", hant: "香芋" } },
  peach: { dough: ["#fff5f3", "#ffd6d6", "#f7a6b2", "#cc708a"], pleat: "#e88aa0", blush: "#f0708a", steamer: BAMBOO, band: "#8a5a26",
           disc: ["#2f7a52", "#123a26"], name: { en: "Longevity peach", zh: "寿桃", hant: "壽桃" } },
} as const satisfies Record<string, BunColour>;

export type BunColourId = keyof typeof BUN_COLOURS;
