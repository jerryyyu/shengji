// The drawn companions' colours (every one but the Tractor, whose table is
// `palette.ts`): the one table their art reads. A colour is
// a palette swap on the same drawing, and a character's four colours come
// with it. A four-tone entry runs highlight, base, low, core shadow; `disc`
// is the portrait's ground, each colour's own so two portraits read apart at
// 24 px. The ids are the `<colour>` half of a look ("bun/taro").

type Tones = readonly [string, string, string, string];
type Pair = readonly [string, string];
type Name = { en: string; zh: string; hant: string };

export interface LambColour {
  wool: Tones;
  /** The scroll marks on the wool. */
  curl: string;
  skin: Tones;
  horn: Tones;
  ridge: string;
  scarf: Tones;
  bell: Tones;
  bellInk: string;
  /** Front legs top to bottom, then the far pair's flat tone. */
  leg: Pair;
  backLeg: string;
  hoof: Pair;
  blush: string;
  earIn: string;
  /** The gold lines: scarf edge, hoof band. */
  trim: string;
  /** The portrait's ground, top to bottom. */
  disc: Pair;
  /** Spoken only (the swatch's label), never drawn. */
  name: Name;
}

const GOLD: Tones = ["#fff3c0", "#f2c25a", "#c4852a", "#8a5516"];
const APRICOT: Tones = ["#fef0d9", "#f8debd", "#e9c29a", "#cf9c7c"];

export const LAMB_COLOURS = {
  newyear: { wool: ["#fffefa", "#fdf3e0", "#eedcc6", "#c6b0c6"], curl: "#d3bba6", skin: APRICOT,
             horn: GOLD, ridge: "#8a5514", scarf: ["#f4675f", "#da3e43", "#a81d2c", "#6d0f1c"],
             bell: GOLD, bellInk: "#7a4a12", leg: ["#f6e0c2", "#dcb98f"], backLeg: "#c9a17b", hoof: ["#6a4335", "#35201a"],
             blush: "#f08f84", earIn: "#eea093", trim: "#f2d27c", disc: ["#b42a31", "#5e0d18"],
             name: { en: "New Year", zh: "新年", hant: "新年" } },
  jade: { wool: ["#f9fffa", "#e3f3e8", "#bddccb", "#7fb3a4"], curl: "#86b8a2", skin: ["#fcf3e0", "#f2e1c3", "#dec6a1", "#bfa07d"],
          horn: ["#dcf7e8", "#63bd9f", "#2a8572", "#12564a"], ridge: "#0f4a40", scarf: ["#49a797", "#2f7d70", "#1b5a52", "#0b332f"],
          bell: GOLD, bellInk: "#7a4a12", leg: ["#f2e4ca", "#d2bb98"], backLeg: "#bda582", hoof: ["#4f6a5f", "#1d342e"],
          blush: "#f0a08e", earIn: "#e9a595", trim: "#f2d27c", disc: ["#f0c25a", "#b06f1a"],
          name: { en: "Jade", zh: "翡翠", hant: "翡翠" } },
  ink: { wool: ["#ffffff", "#f3f2ed", "#d8d6cf", "#9ea3aa"], curl: "#6a6e73", skin: ["#fcf8f0", "#eee6d9", "#d8cebf", "#b3a899"],
         horn: ["#8a8f95", "#44484c", "#1c1d20", "#060607"], ridge: "#000000", scarf: ["#666b71", "#3c4044", "#1c1d1f", "#09090a"],
         bell: ["#ffa093", "#e4504a", "#b01f26", "#7c0f16"], bellInk: "#fff1e0", leg: ["#f1ebde", "#cfc5b4"], backLeg: "#b8ae9e", hoof: ["#44484c", "#111213"],
         blush: "#e9a79c", earIn: "#d9b0a6", trim: "#c9ccd0", disc: ["#7d909e", "#33414d"],
         name: { en: "Ink wash", zh: "水墨", hant: "水墨" } },
  lacquer: { wool: ["#ff9382", "#e34d4b", "#b32331", "#6e0f1e"], curl: "#ffd98a", skin: APRICOT,
             horn: GOLD, ridge: "#8a5514", scarf: ["#5f535a", "#3a3136", "#1d171a", "#0a0708"],
             bell: GOLD, bellInk: "#7a4a12", leg: ["#f6e0c2", "#dcb98f"], backLeg: "#c9a17b", hoof: ["#6a4335", "#35201a"],
             blush: "#f08f84", earIn: "#eea093", trim: "#f2d27c", disc: ["#33272c", "#0f0b0d"],
             name: { en: "Lacquer red", zh: "朱漆", hant: "朱漆" } },
} as const satisfies Record<string, LambColour>;

export type LambColourId = keyof typeof LAMB_COLOURS;

export interface PandaColour {
  /** The light coat: head and belly. */
  fur: Tones;
  /** The dark coat: ears, eye patches, arms, feet. */
  dark: Tones;
  earIn: string;
  /** The sole and toe pads. */
  pad: string;
  blush: string;
  nose: string;
  /** The lids of a closed or smiling eye, drawn on the patch. */
  lid: string;
  /** The bamboo across its width, lit side to shade side. */
  bamboo: readonly [string, string, string];
  node: string;
  leaf: Pair;
  /** Gold dust on the dark coat. */
  dust?: boolean;
  disc: Pair;
  name: Name;
}

export const PANDA_COLOURS = {
  classic: { fur: ["#ffffff", "#f8f4ea", "#e3dac9", "#b9a9bd"], dark: ["#6a6572", "#3f3b46", "#25222b", "#100e14"],
             earIn: "#857a8c", pad: "#f2a79b", blush: "#f08f84", nose: "#2a2530", lid: "#fff5e4",
             bamboo: ["#b6e894", "#63bb69", "#2f8a4a"], node: "#1f6a38", leaf: ["#a3e38f", "#2f8a4a"],
             disc: ["#35957c", "#0b2a28"], name: { en: "Classic", zh: "黑白", hant: "黑白" } },
  russet: { fur: ["#fffaf0", "#fdecd2", "#efd3ad", "#c9a183"], dark: ["#f09a58", "#cf6a2c", "#9c421a", "#63240d"],
            earIn: "#ffd9ae", pad: "#5a2a16", blush: "#f08f84", nose: "#4a2416", lid: "#fff5e4",
            bamboo: ["#b6e894", "#63bb69", "#2f8a4a"], node: "#1f6a38", leaf: ["#a3e38f", "#2f8a4a"],
            disc: ["#2c377c", "#121738"], name: { en: "Russet", zh: "小熊猫棕", hant: "小熊貓棕" } },
  ink: { fur: ["#ffffff", "#f3f2ed", "#d8d6cf", "#9ea3aa"], dark: ["#a3a8ae", "#72777d", "#474b50", "#24262a"],
         earIn: "#c3c7cc", pad: "#d9dcdf", blush: "#e9a79c", nose: "#2a2c30", lid: "#ffffff",
         bamboo: ["#b9c4b8", "#6f8273", "#3a4a3f"], node: "#26332b", leaf: ["#a9b8a9", "#3a4a3f"],
         disc: ["#c8372f", "#7c1418"], name: { en: "Ink wash", zh: "水墨", hant: "水墨" } },
  gilded: { fur: ["#fffdf5", "#fdf3d9", "#f0dcae", "#caa66c"], dark: ["#ffe9a0", "#eab64a", "#bb7c1f", "#7a4a12"],
            earIn: "#fff3c4", pad: "#a3232b", blush: "#f08f84", nose: "#5e3410", lid: "#5e3410",
            bamboo: ["#c9f0dc", "#4fae93", "#1b6b5c"], node: "#0f4a40", leaf: ["#bfeed9", "#1b6b5c"],
            dust: true, disc: ["#a3232b", "#4f0a15"], name: { en: "Gold dust", zh: "洒金", hant: "灑金" } },
} as const satisfies Record<string, PandaColour>;

export type PandaColourId = keyof typeof PANDA_COLOURS;

export interface RabbitColour {
  fur: Tones;
  earIn: string;
  /** The feet, top to bottom. */
  foot: Pair;
  blush: string;
  nose: string;
  /** The mooncake, and the pressed flower on it. */
  cake: Tones;
  cakeLine: string;
  disc: Pair;
  name: Name;
}

const CAKE: Tones = ["#fbe09a", "#e9ad4e", "#b97420", "#7e480f"];

export const RABBIT_COLOURS = {
  moon: { fur: ["#ffffff", "#f8f4ee", "#e4dad0", "#b9aac6"], earIn: "#ffb9b0", foot: ["#fbe9d2", "#e3c29e"], blush: "#f08f84", nose: "#e88a80",
          cake: CAKE, cakeLine: "#8a5514", disc: ["#34418f", "#121738"], name: { en: "Moon white", zh: "月白", hant: "月白" } },
  osmanthus: { fur: ["#fff8d9", "#fbe094", "#e9b752", "#b47a1e"], earIn: "#ffd2a8", foot: ["#fdeab4", "#e2b765"], blush: "#f08f84", nose: "#d97f72",
               cake: ["#f4b87a", "#cc7a3e", "#8f4318", "#5e260a"], cakeLine: "#5e260a", disc: ["#1f6157", "#0b2a28"],
               name: { en: "Osmanthus gold", zh: "桂花金", hant: "桂花金" } },
  jade: { fur: ["#f7fff9", "#dbf1e4", "#abd7c1", "#6aa893"], earIn: "#f7c6bd", foot: ["#e6f4ea", "#b6d6c4"], blush: "#f0a08e", nose: "#e88a80",
          cake: CAKE, cakeLine: "#8a5514", disc: ["#b42a31", "#5e0d18"], name: { en: "Pale jade", zh: "玉色", hant: "玉色" } },
  lotus: { fur: ["#fff5f5", "#ffdbde", "#f5b0ba", "#c9788f"], earIn: "#ff8fa2", foot: ["#ffe8e8", "#efb5bd"], blush: "#f0708a", nose: "#e0607a",
           cake: CAKE, cakeLine: "#8a5514", disc: ["#2f7a52", "#123a26"], name: { en: "Lotus pink", zh: "荷粉", hant: "荷粉" } },
} as const satisfies Record<string, RabbitColour>;

export type RabbitColourId = keyof typeof RABBIT_COLOURS;

export interface CatColour {
  fur: Tones;
  earIn: string;
  collar: Tones;
  bell: Tones;
  bellInk: string;
  /** The open eye's fill when it is not the rig's dark eye, and its slit pupil. */
  eye?: string;
  pupil?: string;
  /** The lids of a closed or smiling eye. */
  lid: string;
  whisker: string;
  pad: string;
  blush: string;
  nose: string;
  /** Calico: the warm patch and the dark patch. */
  patches?: Pair;
  trim: string;
  disc: Pair;
  name: Name;
}

const CINNABAR: Tones = ["#f4675f", "#da3e43", "#a81d2c", "#6d0f1c"];

export const CAT_COLOURS = {
  white: { fur: ["#ffffff", "#faf5ea", "#e8dccb", "#bcaac4"], earIn: "#ffb9b0", collar: CINNABAR, bell: GOLD, bellInk: "#7a4a12",
           lid: "#2b1713", whisker: "#c9b9a6", pad: "#f29a8e", blush: "#f08f84", nose: "#e88a80", trim: "#f2d27c",
           disc: ["#b42a31", "#5e0d18"], name: { en: "White", zh: "白猫", hant: "白貓" } },
  black: { fur: ["#716b77", "#403b46", "#231f29", "#0c0a10"], earIn: "#9a6470", collar: GOLD, bell: ["#ffa093", "#e4504a", "#b01f26", "#7c0f16"], bellInk: "#fff1e0",
           eye: "#f8d76e", pupil: "#231709", lid: "#f8d76e", whisker: "#a39cab", pad: "#f29a8e", blush: "#d9707a", nose: "#e88a80", trim: "#8a5516",
           disc: ["#f0c25a", "#b06f1a"], name: { en: "Black", zh: "黑猫", hant: "黑貓" } },
  gold: { fur: ["#fff8d2", "#f9d670", "#dfa634", "#a06a18"], earIn: "#fff1c0", collar: CINNABAR, bell: ["#ffffff", "#fff3c0", "#f2c25a", "#b9781f"], bellInk: "#7a4a12",
          lid: "#2b1713", whisker: "#b9781f", pad: "#f29a8e", blush: "#f08f84", nose: "#d97f72", trim: "#fff3c0",
          disc: ["#1f6157", "#0b2a28"], name: { en: "Gold", zh: "金猫", hant: "金貓" } },
  calico: { fur: ["#ffffff", "#faf5ea", "#e8dccb", "#bcaac4"], earIn: "#ffb9b0", collar: ["#49a797", "#2f7d70", "#1b5a52", "#0b332f"], bell: GOLD, bellInk: "#7a4a12",
            lid: "#2b1713", whisker: "#c9b9a6", pad: "#f29a8e", blush: "#f08f84", nose: "#e88a80", patches: ["#f09a48", "#45404c"], trim: "#f2d27c",
            disc: ["#34418f", "#121738"], name: { en: "Calico", zh: "三花", hant: "三花" } },
} as const satisfies Record<string, CatColour>;

export type CatColourId = keyof typeof CAT_COLOURS;

export interface LionColour {
  /** The lacquered head and the cape. */
  body: Tones;
  /** The fur trim: mane, brows, muzzle, beard, tail tuft. */
  mane: Tones;
  /** The pom-pom ears, the crown knob, the mirror and the hem. */
  accent: Tones;
  eyeRing: string;
  nose: string;
  blush: string;
  shoe: string;
  /** The scroll marks on the cape. */
  trim: string;
  disc: Pair;
  name: Name;
}

const SNOW: Tones = ["#ffffff", "#fdf3e0", "#eedcc6", "#c6b0c6"];

export const LION_COLOURS = {
  red: { body: ["#ff8272", "#e2474a", "#b3212b", "#6d0f1c"], mane: SNOW, accent: GOLD, eyeRing: "#fff6e6", nose: "#5e0d18", blush: "#ffc0a8",
         shoe: "#3a2026", trim: "#f2d27c", disc: ["#3a2c31", "#0f0b0d"], name: { en: "Red and gold", zh: "红金", hant: "紅金" } },
  yellow: { body: ["#fff3ac", "#f9d150", "#dfa01e", "#a06a18"], mane: SNOW, accent: CINNABAR, eyeRing: "#fffaf0", nose: "#8a1723", blush: "#ffb09a",
            shoe: "#8a1723", trim: "#c22a36", disc: ["#b42a31", "#5e0d18"], name: { en: "Yellow and red", zh: "黄红", hant: "黃紅" } },
  black: { body: ["#716b77", "#403b46", "#231f29", "#0c0a10"], mane: SNOW, accent: CINNABAR, eyeRing: "#fffaf0", nose: "#0c0a10", blush: "#e0808a",
           shoe: "#0c0a10", trim: "#f2d27c", disc: ["#f0c25a", "#b06f1a"], name: { en: "Black and white", zh: "黑白", hant: "黑白" } },
  green: { body: ["#8be3b6", "#38a973", "#1f7a4e", "#0f4a30"], mane: SNOW, accent: GOLD, eyeRing: "#fffaf0", nose: "#0f4a30", blush: "#ffd0b0",
           shoe: "#0f3a28", trim: "#f2d27c", disc: ["#34418f", "#121738"], name: { en: "Green and gold", zh: "绿金", hant: "綠金" } },
} as const satisfies Record<string, LionColour>;

export type LionColourId = keyof typeof LION_COLOURS;

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

export interface FoxColour {
  fur: Tones;
  /** The cheek mask and chest. */
  cream: string;
  /** The ear tips and paws. */
  dark: string;
  earIn: string;
  /** The tail's tip. */
  tip: string;
  envelope: Tones;
  seal: Tones;
  /** The open eye's fill when it is not the rig's dark eye, and its slit pupil. */
  eye?: string;
  pupil?: string;
  lid: string;
  blush: string;
  nose: string;
  disc: Pair;
  name: Name;
}

export const FOX_COLOURS = {
  orange: { fur: ["#ffba78", "#f08a3c", "#cf5f1e", "#8f3a10"], cream: "#fff6e6", dark: "#4a2a1a", earIn: "#5e3320", tip: "#fff6e6",
            envelope: CINNABAR, seal: GOLD, lid: "#2b1713", blush: "#f0806a", nose: "#3a2018", disc: ["#1f6157", "#0b2a28"],
            name: { en: "Orange", zh: "赤狐", hant: "赤狐" } },
  snow: { fur: ["#ffffff", "#f6f2ec", "#e0d6ca", "#b9aac6"], cream: "#ffffff", dark: "#a9b1c0", earIn: "#ffb9b0", tip: "#dfe6f6",
          envelope: CINNABAR, seal: GOLD, lid: "#2b1713", blush: "#f08f84", nose: "#3a2018", disc: ["#34418f", "#121738"],
          name: { en: "Snow", zh: "雪狐", hant: "雪狐" } },
  silver: { fur: ["#dfe3ea", "#a9b0bd", "#737c8c", "#454d5c"], cream: "#f6f8fb", dark: "#2e343f", earIn: "#2e343f", tip: "#f6f8fb",
            envelope: CINNABAR, seal: GOLD, lid: "#2b1713", blush: "#f08f84", nose: "#1c2028", disc: ["#b42a31", "#5e0d18"],
            name: { en: "Silver", zh: "银狐", hant: "銀狐" } },
  black: { fur: ["#716b77", "#403b46", "#231f29", "#0c0a10"], cream: "#77717e", dark: "#0c0a10", earIn: "#9a6470", tip: "#f2c25a",
           envelope: CINNABAR, seal: GOLD, eye: "#f8d76e", pupil: "#231709", lid: "#f8d76e", blush: "#d9707a", nose: "#0c0a10", disc: ["#f0c25a", "#b06f1a"],
           name: { en: "Black and gold", zh: "玄狐", hant: "玄狐" } },
} as const satisfies Record<string, FoxColour>;

export type FoxColourId = keyof typeof FOX_COLOURS;

export interface DragonColour {
  body: Tones;
  /** The belly, the muzzle and the patch behind each eye. */
  belly: string;
  horn: Tones;
  mane: string;
  whisker: string;
  blush: string;
  disc: Pair;
  name: Name;
}

export const DRAGON_COLOURS = {
  red: { body: ["#ff8a78", "#e2474a", "#b3212b", "#6d0f1c"], belly: "#fff3dc", horn: GOLD,
         mane: "#fff6e6", whisker: "#f2c25a", blush: "#ffc0a8", disc: ["#1f6157", "#0b2a28"], name: { en: "Red and cream", zh: "朱红", hant: "朱紅" } },
  jade: { body: ["#a3ecd0", "#3fae90", "#1b6b5c", "#0f4a40"], belly: "#f6ffe8", horn: GOLD,
          mane: "#fff6e6", whisker: "#e2474a", blush: "#f0a08e", disc: ["#b42a31", "#5e0d18"], name: { en: "Jade and gold", zh: "青龙", hant: "青龍" } },
  indigo: { body: ["#9db2ff", "#4f63c2", "#2a3580", "#141a4a"], belly: "#eef2fc", horn: ["#ffffff", "#dfe6f6", "#a9b8dc", "#5f6f9c"],
            mane: "#ffffff", whisker: "#dfe6f6", blush: "#f0a0b8", disc: ["#f0c25a", "#b06f1a"], name: { en: "Indigo and silver", zh: "靛蓝", hant: "靛藍" } },
  lacquer: { body: ["#716b77", "#403b46", "#231f29", "#0c0a10"], belly: "#f6e2a8", horn: GOLD,
             mane: "#f6e2a8", whisker: "#f2c25a", blush: "#d9707a", disc: ["#b42a31", "#5e0d18"], name: { en: "Black lacquer", zh: "玄漆", hant: "玄漆" } },
} as const satisfies Record<string, DragonColour>;

export type DragonColourId = keyof typeof DRAGON_COLOURS;

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
