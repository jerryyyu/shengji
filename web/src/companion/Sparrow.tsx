// The Sparrow (麻雀), a free companion, drawn in its 400-unit box on the
// characters' rig (`rig.ts`): gradients only, no SVG filters. One string builder
// draws every pose; the portrait is the same drawing as an image. The colour
// is a palette swap (`storePalette.ts`). Its signature reaction is the loop:
// it takes off, flies one loop with a streak behind it, and lands in feathers.
import { SPARROW_COLOURS } from "./storePalette";
import type { SparrowColour, SparrowColourId } from "./storePalette";
import { ball, confetti, dataUrl, eye, glow, groundShadow, n, part, portraitSvg, ramp, sharedDefs } from "./rig";
import type { CharOpts, CharPose, EyeMode } from "./rig";

/** A colour by id, or a palette given whole (the CSS-variable master passes one). */
const colourOf = (c: SparrowColourId | SparrowColour): SparrowColour => (typeof c === "string" ? SPARROW_COLOURS[c] ?? SPARROW_COLOURS.tree : c);

/** Where the sleeping z rises from. */
export const SPARROW_Z: readonly [number, number] = [330, 70];

const FACE: Record<CharPose, EyeMode> = { idle: "open", hop: "open", cheer: "happy", react: "happy", sleep: "sleep" };

/** Each part's place in a pose drawn still: the peak of its animation. Sleep
 *  is always drawn this way; it has no moving limbs. */
const STILL: Partial<Record<CharPose, Record<string, string>>> = {
  hop: { body: "translate(0 -12)", wing: "rotate(-34 178 162)", tail: "rotate(14 100 270)" },
  cheer: { body: "translate(0 -34)", wing: "rotate(-40 178 162)", head: "rotate(-8 228 226)", tail: "rotate(16 100 270)" },
  react: { body: "translate(0 -40) rotate(-14 196 215)", wing: "rotate(-52 178 162)", tail: "rotate(14 100 270)" },
  sleep: { torso: "translate(196 352) scale(1.04 .97) translate(-196 -352)", head: "translate(-10 22) rotate(-10 228 226)" },
};

/** The Sparrow's shapes in its 400 box, as SVG markup. `id` keeps its
 *  gradient ids apart from another drawing's on the same page. */
export function sparrowMarkup(colour: SparrowColourId | SparrowColour, id: string, { pose = "idle", detail = true, shadow = true, still = false }: CharOpts = {}): string {
  const p = colourOf(colour);
  const eyes = FACE[pose];
  const at = (still || pose === "sleep" ? STILL[pose] : undefined) ?? {};
  const u = (name: string) => `url(#${name}-${id})`;

  const defs = `<defs>${sharedDefs(id)}${ball("belly", id, p.belly, [0.4, 0.28, 0.8])}`
    + ramp("wing", id, p.wing, [0, 0, 1, 1]) + ramp("cap", id, p.cap, [0, 0, 1, 1]) + glow("blush", id, p.blush, 0.8, 0.25)
    + `</defs>`;

  const torso = part("cmp-tail", `<path d="M100 250L34 208Q22 250 40 292L110 294Z" fill="${u("wing")}" stroke-linejoin="round"/>`
      + (detail ? `<path d="M44 230L92 258M42 258L94 274" stroke="${p.wing[2]}" stroke-width="4" stroke-linecap="round" opacity=".6"/>` : ""), at.tail)
    + `<path d="M170 322v28M160 352h20M228 322v28M218 352h20" stroke="${p.leg}" stroke-width="8" stroke-linecap="round" fill="none"/>`
    + `<ellipse cx="196" cy="238" rx="110" ry="98" fill="${u("belly")}"/>`
    + part("cmp-arm-l", `<path d="M92 206C104 150 150 132 190 150C196 210 170 278 110 300C84 280 80 240 92 206Z" fill="${u("wing")}"/>`
      + (detail ? `<g fill="none" stroke-linecap="round"><path d="M102 232C124 236 150 226 172 206M108 266C130 268 152 258 168 240" stroke="${p.bar}" stroke-width="6" opacity=".9"/></g>` : ""), at.wing);

  const head = `<circle cx="234" cy="150" r="84" fill="${u("belly")}"/>`
    + `<path d="M157 118C169 82 200 64 236 64C272 65 301 84 311 116C286 98 254 92 226 95C200 97 176 106 157 118Z" fill="${u("cap")}"/>`
    + `<path d="M306 154L354 172L306 190Q298 172 306 154Z" fill="${p.beak}" stroke-linejoin="round"/>`
    + (detail ? `<path d="M308 173h34" stroke="#000" stroke-width="2.4" stroke-linecap="round" opacity=".3"/>` : "")
    + `<ellipse cx="226" cy="190" rx="21" ry="13.5" fill="${u("blush")}"/>`
    + eye(258, 150, eyes, id, { k: 0.9, detail }) + eye(301, 148, eyes, id, { k: 0.82, detail });

  // the streak: arcs round the loop's centre (196, 125), behind the tail
  const streak = (r: number, from: number, to: number) => {
    const on = (deg: number) => `${n(196 + r * Math.cos((deg * Math.PI) / 180))} ${n(125 + r * Math.sin((deg * Math.PI) / 180))}`;
    return `M${on(from)}A${r} ${r} 0 0 1 ${on(to)}`;
  };
  const trail = pose === "react" ? `<g class="cmp-trail" fill="none" stroke-linecap="round">`
    + `<path d="${streak(72, 150, 225)}" stroke="#fff6d6" stroke-width="12"/><path d="${streak(100, 145, 215)}" stroke="#ffd76a" stroke-width="14"/>`
    + `<path d="${streak(128, 142, 205)}" stroke="#fff6d6" stroke-width="12"/></g>` : "";
  const feather = (a: number, i: number) => `<g transform="translate(196 340) rotate(${a})">`
    + `<path class="cmp-feather" d="M100 0C116 -20 148 -20 166 0C148 20 116 20 100 0Z" fill="${i % 2 ? "#ffd76a" : p.belly[0]}" stroke="${p.wing[2]}" stroke-width="3"/></g>`;
  const feathers = pose === "react" && !still ? [-168, -142, -38, -12].map(feather).join("") : "";
  const body = part("cmp-body", part("cmp-loop", trail + part("cmp-fly", part("cmp-torso", torso, at.torso) + part("cmp-head", head, at.head))), at.body);
  return defs + (shadow ? groundShadow(id, 196, 112) : "") + body + feathers + (pose === "cheer" ? confetti(222, 160) : "");
}

const portraits = new Map<string, string>();

/** The round portrait as a data URL: the head and beak on the colour's
 *  ground, clipped to a disc. The textures are drawn at every size, as at the table. */
export function sparrowPortraitUrl(colour: SparrowColourId, small: boolean): string {
  const key = `${colour}/${small ? "s" : "l"}`;
  let url = portraits.get(key);
  if (!url) {
    url = dataUrl(sparrowPortraitSvg(colour));
    portraits.set(key, url);
  }
  return url;
}

export function sparrowPortraitSvg(colour: SparrowColourId): string {
  return portraitSvg(sparrowMarkup(colour, "p", { detail: true, shadow: false }), 240, 158, 122, colourOf(colour).disc);
}
