// The Panda, drawn in its 400-unit box on the store characters' rig:
// gradients only, no SVG filters. One string builder draws every pose; the
// figure inlines it (the pose CSS moves its parts), and the portrait is the
// same drawing as an image, one cached data URL per colour. The colour is a
// palette swap (`storePalette.ts`). Its signature reaction is the bamboo
// bite: it sits down hard and chomps the stalk like corn on the cob.
import { PANDA_COLOURS } from "./storePalette";
import type { PandaColour, PandaColourId } from "./storePalette";
import { ball, bits, confetti, dataUrl, eye, glow, groundShadow, part, portraitSvg, ramp, sharedDefs, spark } from "./rig";
import type { CharOpts, CharPose, EyeMode } from "./rig";

/** A colour by id, or a palette given whole (the CSS-variable master passes one). */
const colourOf = (c: PandaColourId | PandaColour): PandaColour => (typeof c === "string" ? PANDA_COLOURS[c] ?? PANDA_COLOURS.classic : c);

/** Where the sleeping z rises from. */
export const PANDA_Z: readonly [number, number] = [30, 84];

const FACE: Record<CharPose, { eyes: EyeMode; mouth: "smile" | "open" | "bite" | "rest" }> = {
  idle: { eyes: "open", mouth: "smile" },
  hop: { eyes: "open", mouth: "smile" },
  cheer: { eyes: "happy", mouth: "open" },
  react: { eyes: "happy", mouth: "bite" },
  sleep: { eyes: "sleep", mouth: "rest" },
};

/** Each part's place in a pose drawn still: the peak of its animation. Sleep
 *  is always drawn this way; it has no moving limbs. */
const STILL: Partial<Record<CharPose, Record<string, string>>> = {
  hop: { body: "translate(0 -12)", armL: "rotate(26 104 222)", armR: "rotate(-14 256 222)", earL: "rotate(-8 112 104)", earR: "rotate(8 248 104)" },
  cheer: { body: "translate(0 -34)", head: "rotate(-5 180 236)", armL: "rotate(104 104 222)", prop: "translate(0 -16) rotate(-4 302 219)" },
  react: { torso: "translate(180 352) scale(1.04 .965) translate(-180 -352)", head: "translate(0 8)", armL: "rotate(56 104 222)", armR: "rotate(-56 256 222)",
           prop: "translate(-118 -3) rotate(78 302 219)" },
  sleep: { head: "translate(4 12) rotate(8 180 236)", prop: "translate(6 2) rotate(7 302 219)", earL: "rotate(-6 112 104)" },
};

/** The Panda's shapes in its 400 box, as SVG markup. `id` keeps its gradient
 *  ids apart from another drawing's on the same page. */
export function pandaMarkup(colour: PandaColourId | PandaColour, id: string, { pose = "idle", detail = true, shadow = true, still = false }: CharOpts = {}): string {
  const p = colourOf(colour);
  const face = FACE[pose];
  const at = (still || pose === "sleep" ? STILL[pose] : undefined) ?? {};
  const u = (name: string) => `url(#${name}-${id})`;

  const defs = `<defs>${sharedDefs(id)}${ball("fur", id, p.fur, [0.36, 0.28, 0.8])}${ball("dark", id, p.dark, [0.34, 0.26, 0.85])}`
    + ramp("stalk", id, p.bamboo, [0, 0, 1, 0]) + ramp("leaf", id, p.leaf, [0, 0, 1, 1]) + glow("under", id, "#3a2a4a", 0.3) + glow("blush", id, p.blush, 0.8, 0.25)
    + `</defs>`;

  const foot = (cx: number, s: number) => `<ellipse cx="${cx}" cy="326" rx="40" ry="31" fill="${u("dark")}" transform="rotate(${-10 * s} ${cx} 326)"/>`
    + `<ellipse cx="${cx - 2 * s}" cy="332" rx="17" ry="12.5" fill="${p.pad}" opacity=".9"/>`
    + (detail ? `<g fill="${p.pad}" opacity=".9"><circle cx="${cx - 18 * s}" cy="314" r="5.6"/><circle cx="${cx - 4 * s}" cy="309" r="6"/><circle cx="${cx + 11 * s}" cy="313" r="5.6"/></g>` : "");
  const torso = foot(112, 1) + foot(248, -1)
    + `<path d="M180 194C238 194 274 234 274 282C274 324 236 350 180 350C124 350 86 324 86 282C86 234 122 194 180 194Z" fill="${u("fur")}"/>`
    + `<ellipse cx="180" cy="238" rx="84" ry="25" fill="${u("under")}"/>`;

  const ear = (cx: number) => `<circle cx="${cx}" cy="84" r="35" fill="${u("dark")}"/><circle cx="${cx + 3}" cy="89" r="16" fill="${p.earIn}" opacity=".6"/>`;
  const lid = { k: 0.95, detail, ink: p.lid, fill: "#0e0809" };
  const mouth = face.mouth === "open"
    ? `<path d="M167 203q13 6 26 0q-2 19-13 19q-11 0-13-19z" fill="#8a3038"/><path d="M172 215q8-5 16 0q-3 7-8 7q-5 0-8-7z" fill="#f08a8a"/>`
    : face.mouth === "bite" ? `<path d="M166 200q14 9 28 0" fill="none" stroke="#8a5240" stroke-width="3.2" stroke-linecap="round"/>`
      : face.mouth === "rest" ? `<path d="M173 206q7 5 14 0" fill="none" stroke="#8a5240" stroke-width="3" stroke-linecap="round"/>`
        : `<path d="M180 197v8M167 206q7 8 13-1q6 9 13 1" fill="none" stroke="#8a5240" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`;
  const head = part("cmp-ear-l", ear(98), at.earL) + part("cmp-ear-r", ear(262), at.earR)
    + `<path d="M74 152C74 98 120 62 180 62C240 62 286 98 286 152C286 204 242 240 180 240C118 240 74 204 74 152Z" fill="${u("fur")}"/>`
    + `<ellipse cx="137" cy="158" rx="29" ry="36" fill="${u("dark")}" transform="rotate(22 137 158)"/><ellipse cx="223" cy="158" rx="29" ry="36" fill="${u("dark")}" transform="rotate(-22 223 158)"/>`
    + `<ellipse cx="98" cy="200" rx="22" ry="14" fill="${u("blush")}"/><ellipse cx="262" cy="200" rx="22" ry="14" fill="${u("blush")}"/>`
    + eye(141, 160, face.eyes, id, lid) + eye(219, 160, face.eyes, id, lid)
    + `<path d="M167 183Q180 176 193 183Q190 196 180 197Q170 196 167 183Z" fill="${p.nose}"/><ellipse cx="176" cy="184.5" rx="4.4" ry="2" fill="#fff" opacity=".5"/>`
    + mouth;

  const arm = (cx: number, s: number) => `<ellipse cx="${cx}" cy="258" rx="27" ry="48" fill="${u("dark")}" transform="rotate(${16 * s} ${cx} 258)"/>`;
  const stalk = `<g transform="rotate(8 286 334)">`
    + `<path d="M294 160C316 132 348 128 364 138C346 160 318 168 294 160Z" fill="${u("leaf")}"/><path d="M294 222C312 204 334 204 346 212C332 228 312 232 294 222Z" fill="${u("leaf")}"/>`
    + (detail ? `<path d="M300 158Q330 142 358 139M300 221Q322 212 341 212" fill="none" stroke="${p.node}" stroke-width="2" stroke-linecap="round" opacity=".5"/>` : "")
    + `<rect x="276" y="98" width="20" height="240" rx="9" fill="${u("stalk")}"/>`
    + `<path d="M276 160h20M276 222h20M276 284h20" stroke="${p.node}" stroke-width="3.2" opacity=".75"/>`
    + (detail ? `<path d="M281.5 108v48M281.5 168v46M281.5 230v46M281.5 292v38" stroke="#fff" stroke-width="3" stroke-linecap="round" opacity=".45"/>` : "")
    + `</g>`;
  const prop = part("cmp-prop", stalk, at.prop);
  const front = pose === "react";
  const dust = p.dust ? `<g class="cmp-dust">` + spark(96, 66, 0.95) + spark(276, 252, 0.7) + spark(238, 150, 0.55) + spark(86, 262, 0.6) + (detail ? spark(256, 320, 0.5) + spark(332, 76, 0.8, p.dark[0]) + spark(40, 150, 0.6, p.dark[0]) : "") + `</g>` : "";

  const body = part("cmp-body", part("cmp-torso", torso, at.torso) + part("cmp-head", head, at.head)
    + part("cmp-arm-l", arm(92, 1), at.armL) + (front ? "" : prop) + part("cmp-arm-r", arm(268, -1), at.armR) + (front ? prop : "") + dust, at.body);
  return defs + (shadow ? groundShadow(id, 184, 132) : "") + body + (pose === "react" ? bits("cmp-crumbs", 180, 236, 62, 6, [p.leaf[0], p.bamboo[1], p.leaf[1]], 10, 170, 0.8) : "") + (pose === "cheer" ? confetti(180, 150) : "");
}

const portraits = new Map<string, string>();

/** The round portrait as a data URL: the head on the colour's ground,
 *  clipped to a disc. The textures are drawn at every size, as at the table. */
export function pandaPortraitUrl(colour: PandaColourId, small: boolean): string {
  const key = `${colour}/${small ? "s" : "l"}`;
  let url = portraits.get(key);
  if (!url) {
    url = dataUrl(pandaPortraitSvg(colour));
    portraits.set(key, url);
  }
  return url;
}

export function pandaPortraitSvg(colour: PandaColourId): string {
  return portraitSvg(pandaMarkup(colour, "p", { detail: true, shadow: false }), 180, 147, 138, colourOf(colour).disc);
}
