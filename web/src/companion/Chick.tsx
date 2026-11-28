// The Chick (小鸡), a free companion offered beside the Sparrow, drawn in
// its 400-unit box on the characters' rig (`rig.ts`): gradients only, no SVG
// filters. One round ball of down with a tuft, a beak and two small wings.
// The colour is a palette swap (`storePalette.ts`). Its signature reaction
// is the flutter: a high hop on beating wings and a burst of feathers at the top.
import { CHICK_COLOURS } from "./storePalette";
import type { ChickColour, ChickColourId } from "./storePalette";
import { ball, confetti, dataUrl, eye, glow, groundShadow, part, portraitSvg, sharedDefs } from "./rig";
import type { CharOpts, CharPose, EyeMode } from "./rig";

/** A colour by id, or a palette given whole (the CSS-variable master passes one). */
const colourOf = (c: ChickColourId | ChickColour): ChickColour => (typeof c === "string" ? CHICK_COLOURS[c] ?? CHICK_COLOURS.yellow : c);

/** Where the sleeping z rises from. */
export const CHICK_Z: readonly [number, number] = [310, 120];

const FACE: Record<CharPose, { eyes: EyeMode; open: boolean }> = {
  idle: { eyes: "open", open: false },
  hop: { eyes: "open", open: false },
  cheer: { eyes: "happy", open: true },
  react: { eyes: "happy", open: true },
  sleep: { eyes: "sleep", open: false },
};

/** Each part's place in a pose drawn still: the peak of its animation. Sleep
 *  is always drawn this way; it has no moving limbs. */
const STILL: Partial<Record<CharPose, Record<string, string>>> = {
  hop: { body: "translate(0 -12)" },
  cheer: { body: "translate(0 -34)", armL: "rotate(118 98 226)", armR: "rotate(-118 282 226)" },
  react: { body: "translate(0 -80)", armL: "rotate(104 98 226) translate(98 226) scale(1.45) translate(-98 -226)", armR: "rotate(-104 282 226) translate(282 226) scale(1.45) translate(-282 -226)" },
  sleep: { head: "translate(190 352) scale(1.04 .95) translate(-190 -352)" },
};

/** The Chick's shapes in its 400 box, as SVG markup. `id` keeps its gradient
 *  ids apart from another drawing's on the same page. */
export function chickMarkup(colour: ChickColourId | ChickColour, id: string, { pose = "idle", detail = true, shadow = true, still = false }: CharOpts = {}): string {
  const p = colourOf(colour);
  const face = FACE[pose];
  const at = (still || pose === "sleep" ? STILL[pose] : undefined) ?? {};
  const u = (name: string) => `url(#${name}-${id})`;

  const defs = `<defs>${sharedDefs(id)}${ball("down", id, p.down, [0.38, 0.28, 0.8])}`
    + glow("blush", id, p.blush, 0.8, 0.25) + `</defs>`;

  const feet = `<path d="M160 336v12M148 350h26M220 336v12M208 350h26" stroke="${p.leg}" stroke-width="9" stroke-linecap="round" fill="none"/>`;
  const beak = face.open
    ? `<path d="M174 236Q190 226 206 236Q200 244 190 245Q180 244 174 236Z" fill="${p.beak}"/><path d="M178 246Q190 242 202 246Q198 260 190 261Q182 260 178 246Z" fill="${p.beak}"/><path d="M181 244q9 4 18 0" stroke="#8a3038" stroke-width="5" stroke-linecap="round"/>`
    : `<path d="M174 238Q190 227 206 238Q199 253 190 255Q181 253 174 238Z" fill="${p.beak}"/>` + (detail ? `<path d="M178 241q12 5 24 0" fill="none" stroke="#000" stroke-width="2.2" stroke-linecap="round" opacity=".25"/>` : "");
  const big = { k: 1.08, detail };
  const head = `<path d="M176 118C166 96 174 78 190 70C186 88 196 100 204 116Z" fill="${p.wing}"/><path d="M190 118C192 100 206 90 220 90C212 102 214 110 212 122Z" fill="${p.wing}"/>`
    + `<path d="M190 108C256 108 298 168 298 238C298 306 252 350 190 350C128 350 82 306 82 238C82 168 124 108 190 108Z" fill="${u("down")}"/>`
    + `<ellipse cx="124" cy="250" rx="22" ry="14" fill="${u("blush")}"/><ellipse cx="256" cy="250" rx="22" ry="14" fill="${u("blush")}"/>`
    + eye(150, 212, face.eyes, id, big) + eye(230, 212, face.eyes, id, big) + beak;
  const wing = (cx: number, s: number) => `<ellipse cx="${cx}" cy="256" rx="22" ry="40" fill="${p.wing}" transform="rotate(${16 * s} ${cx} 256)"/>`;

  // a feather on a spoke round the top of the hop; its keyframes slide it out along the spoke
  const feather = (a: number, i: number) => `<g transform="translate(190 150) rotate(${a})">`
    + `<path class="cmp-feather${i % 2 ? " cmp-feather-b" : ""}" d="M122 0C138 -19 164 -19 178 0C164 19 138 19 122 0Z" fill="${i % 2 ? p.down[0] : p.wing}" stroke="${p.down[3]}" stroke-width="3"/></g>`;
  const feathers = pose === "react" ? [-165, -128, -90, -52, -15].map(feather).join("") : "";
  const body = part("cmp-body", part("cmp-torso", feet) + part("cmp-head", head, at.head)
    + part("cmp-arm-l", wing(86, 1), at.armL) + part("cmp-arm-r", wing(294, -1), at.armR), at.body);
  return defs + (shadow ? groundShadow(id, 190, 112) : "") + body + feathers + (pose === "cheer" ? confetti(190, 190) : "");
}

const portraits = new Map<string, string>();

/** The round portrait as a data URL: the face and tuft on the colour's
 *  ground, clipped to a disc. The textures are drawn at every size, as at the table. */
export function chickPortraitUrl(colour: ChickColourId, small: boolean): string {
  const key = `${colour}/${small ? "s" : "l"}`;
  let url = portraits.get(key);
  if (!url) {
    url = dataUrl(chickPortraitSvg(colour));
    portraits.set(key, url);
  }
  return url;
}

export function chickPortraitSvg(colour: ChickColourId): string {
  return portraitSvg(chickMarkup(colour, "p", { detail: true, shadow: false }), 190, 206, 132, colourOf(colour).disc);
}
