// The Tractor's colours: the one table the art reads. Each colour is a
// palette swap on the same drawing, so a new or changed colour is an entry
// here (and its id in the server's `accounts.LOOKS`). `disc` is the
// portrait's ground, each colour's own so two portraits read apart at 24 px.
// `stripe` replaces the gold waist line, `roof` the cream roof, and `motif`
// draws the blue-and-white scrollwork on the cab.

export interface TractorColour {
  /** The cab's gradient, light to dark. */
  body: readonly [string, string];
  hood: string;
  /** The portrait's ground, top to bottom. */
  disc: readonly [string, string];
  stripe?: string;
  roof?: string;
  motif?: boolean;
  /** Spoken only (the swatch's label), never drawn. */
  name: { en: string; zh: string; hant: string };
}

export const TRACTOR_COLOURS = {
  red: { body: ["#ee5a4c", "#b3212b"], hood: "#d83c3c", disc: ["#2f7a52", "#123a26"],
         name: { en: "Icon red", zh: "拖拉机红", hant: "拖拉機紅" } },
  green: { body: ["#6fcf86", "#1f7a48"], hood: "#35a561", disc: ["#f0c25a", "#b9781f"],
           name: { en: "Paddy green", zh: "稻田绿", hant: "稻田綠" } },
  blue: { body: ["#6fb0ff", "#2456b8"], hood: "#3f82e6", disc: ["#f4ead2", "#d9c7a0"],
          name: { en: "Enamel blue", zh: "搪瓷蓝", hant: "搪瓷藍" } },
  yellow: { body: ["#ffe68a", "#e0a21c"], hood: "#f4c53c", disc: ["#a3232b", "#5e0d18"], stripe: "#c22a36",
            name: { en: "Imperial yellow", zh: "明黄", hant: "明黃" } },
  orange: { body: ["#ffb466", "#de5c1a"], hood: "#f2853a", disc: ["#2c377c", "#121738"],
            name: { en: "Lantern orange", zh: "灯笼橙", hant: "燈籠橙" } },
  jade: { body: ["#9be6c8", "#1f7a68"], hood: "#44ad90", disc: ["#2a2024", "#0f0b0d"],
          name: { en: "Jade", zh: "翡翠", hant: "翡翠" } },
  porcelain: { body: ["#ffffff", "#dde5f4"], hood: "#f2f5fb", disc: ["#24408f", "#101e4a"],
               stripe: "#2a4fb0", roof: "#2a4fb0", motif: true,
               name: { en: "Blue and white", zh: "青花", hant: "青花" } },
  ink: { body: ["#5e5964", "#1a171d"], hood: "#302c35", disc: ["#efe9da", "#cfc7b2"], stripe: "#c22a36",
         name: { en: "Ink black", zh: "墨黑", hant: "墨黑" } },
} as const satisfies Record<string, TractorColour>;

export type TractorColourId = keyof typeof TRACTOR_COLOURS;
