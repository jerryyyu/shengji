// The Bun (包子), a free companion, drawn in its 400-unit box on the
// characters' rig (`rig.ts`): gradients only, no SVG filters. A round pleated bun
// in a bamboo steamer. The colour is a palette swap (`storePalette.ts`).
// Its signature reaction is the steam puff: the bun swells and three puffs
// of steam rise.
import { BUN_COLOURS } from "./storePalette";
import type { BunColour, BunColourId } from "./storePalette";
import { ball, confetti, dataUrl, eye, glow, groundShadow, kerchief, part, portraitSvg, ramp, sharedDefs, teamPad } from "./rig";
import type { CharOpts, CharPose, EyeMode } from "./rig";

/** A colour by id, or a palette given whole (the CSS-variable master passes one). */
const colourOf = (c: BunColourId | BunColour): BunColour => (typeof c === "string" ? BUN_COLOURS[c] ?? BUN_COLOURS.plain : c);

/** Where the sleeping z rises from. */
export const BUN_Z: readonly [number, number] = [308, 76];

const FACE: Record<CharPose, { eyes: EyeMode; mouth: "smile" | "open" | "rest" }> = {
  idle: { eyes: "open", mouth: "smile" },
  hop: { eyes: "open", mouth: "smile" },
  cheer: { eyes: "happy", mouth: "open" },
  react: { eyes: "happy", mouth: "open" },
  sleep: { eyes: "sleep", mouth: "rest" },
};

/** Each part's place in a pose drawn still: the peak of its animation. Sleep
 *  is always drawn this way; it has no moving limbs. */
const STILL: Partial<Record<CharPose, Record<string, string>>> = {
  hop: { head: "translate(0 -12)" },
  cheer: { head: "translate(0 -30)", armL: "rotate(120 100 236)", armR: "rotate(-120 280 236)" },
  react: { head: "translate(190 282) scale(1.05 .95) translate(-190 -282)" },
  sleep: { head: "translate(190 282) scale(1.04 .95) translate(-190 -282)" },
};

/** The Bun's shapes in its 400 box, as SVG markup. `id` keeps its gradient
 *  ids apart from another drawing's on the same page. */
export function bunMarkup(colour: BunColourId | BunColour, id: string, { pose = "idle", detail = true, shadow = true, still = false, team }: CharOpts = {}): string {
  const p = colourOf(colour);
  const face = FACE[pose];
  const at = (still || pose === "sleep" ? STILL[pose] : undefined) ?? {};
  const u = (name: string) => `url(#${name}-${id})`;

  const defs = `<defs>${sharedDefs(id)}${ball("dough", id, p.dough, [0.38, 0.26, 0.82])}`
    + ramp("bamboo", id, p.steamer, [0, 0, 1, 0]) + glow("blush", id, p.blush, 0.8, 0.25) + `</defs>`;

  const steam = pose === "react" || pose === "idle"
    ? `<g fill="#fff" opacity=".85"><circle class="cmp-puff cmp-puff1" cx="150" cy="78" r="14"/><circle class="cmp-puff cmp-puff2" cx="190" cy="58" r="11"/><circle class="cmp-puff cmp-puff3" cx="228" cy="76" r="8"/></g>` : "";
  const mouth = face.mouth === "open"
    ? `<path d="M178 218q12 5 24 0q-2 16-12 16q-10 0-12-16z" fill="#8a3038"/><path d="M183 228q7-4 14 0q-3 6-7 6q-4 0-7-6z" fill="#f08a8a"/>`
    : face.mouth === "rest" ? `<path d="M184 220q6 4 12 0" fill="none" stroke="#8a5240" stroke-width="3" stroke-linecap="round"/>`
      : `<path d="M178 218q12 10 24 0" fill="none" stroke="#8a5240" stroke-width="3.2" stroke-linecap="round"/>`;
  const bun = `<path d="M190 96C262 96 302 160 302 216C302 264 258 284 190 284C122 284 78 264 78 216C78 160 118 96 190 96Z" fill="${u("dough")}"/>`
    + `<g fill="none" stroke="${p.pleat}" stroke-width="4" stroke-linecap="round" opacity=".9"><path d="M190 106C176 118 150 124 128 142M190 106C204 118 230 124 252 142M190 106C186 124 168 138 160 158M190 106C194 124 212 138 220 158"/>`
    + (detail ? `<path d="M190 106V150"/>` : "") + `</g>`
    + `<ellipse cx="190" cy="103" rx="15" ry="9.5" fill="${p.dough[1]}" stroke="${p.pleat}" stroke-width="3"/>`
    + `<ellipse cx="120" cy="230" rx="22" ry="14" fill="${u("blush")}"/><ellipse cx="260" cy="230" rx="22" ry="14" fill="${u("blush")}"/>`
    + eye(152, 196, face.eyes, id, { detail }) + eye(228, 196, face.eyes, id, { detail })
    + mouth;
  const arm = (cx: number) => `<ellipse cx="${cx}" cy="250" rx="17" ry="24" fill="${p.dough[1]}" stroke="${p.pleat}" stroke-width="2.4"/>`;

  const basket = `<ellipse cx="190" cy="268" rx="118" ry="19" fill="${p.steamer[2]}"/>`;
  const front = `<path d="M72 268C72 284 124 292 190 292C256 292 308 284 308 268V326C308 344 256 354 190 354C124 354 72 344 72 326Z" fill="${u("bamboo")}"/>`
    + `<path d="M72 290C100 306 280 306 308 290M72 328C100 344 280 344 308 328" fill="none" stroke="${p.band}" stroke-width="6" stroke-linecap="round"/>`
    + (detail ? `<path d="M110 300v30M150 304v32M190 305v33M230 304v32M270 300v30" stroke="${p.band}" stroke-width="2.4" opacity=".4"/>` : "");

  const body = part("cmp-body", basket
    + part("cmp-head", bun + (team ? kerchief(team, 96, 284, 246, 8, 150) : "") + part("cmp-arm-l", arm(98), at.armL) + part("cmp-arm-r", arm(282), at.armR), at.head)
    + front + steam);
  return defs + (team ? teamPad(team, 190, 124) : "") + (shadow ? groundShadow(id, 190, 128) : "") + body + (pose === "cheer" ? confetti(190, 180) : "");
}

const portraits = new Map<string, string>();

/** The round portrait as a data URL: the bun's face and pleats on the
 *  colour's ground, clipped to a disc. `small` drops the fine detail. */
export function bunPortraitUrl(colour: BunColourId, small: boolean): string {
  const key = `${colour}/${small ? "s" : "l"}`;
  let url = portraits.get(key);
  if (!url) {
    url = dataUrl(bunPortraitSvg(colour, small));
    portraits.set(key, url);
  }
  return url;
}

export function bunPortraitSvg(colour: BunColourId, small: boolean): string {
  return portraitSvg(bunMarkup(colour, "p", { detail: !small, shadow: false }), 190, 186, 128, colourOf(colour).disc);
}
