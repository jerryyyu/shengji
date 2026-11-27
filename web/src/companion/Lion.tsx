// The Lion-dance Lion, drawn in its 400-unit box on the store characters'
// rig: gradients only, no SVG filters. A round lacquered head in a soft
// mane, big friendly eyes, cloud brows, a closed smile. One string builder
// draws every pose; the portrait is the same drawing as an image. The colour
// is a palette swap (`storePalette.ts`). Its signature reaction is the lion
// dance. Only then does the dance costume appear. From rest the lion squats
// and jumps straight up; at the top the costume (a cloth body in three
// segments, a tail and the two dancers' legs) bursts out behind the head in
// a puff and the cape goes; it lands as the whole lion, stomps twice, rears
// its head high so the body arches, shakes its mane, bows, springs back up
// through a pop of red and gold, and the costume folds away. At rest the
// lion keeps its narrow footprint; the costume reaches about 60 units past
// the box's left edge while it dances.
import { LION_COLOURS } from "./storePalette";
import type { LionColour, LionColourId } from "./storePalette";
import { ball, bits, confetti, curl, dataUrl, eye, glow, groundShadow, kerchief, part, portraitSvg, puff, ramp, sharedDefs, teamPad } from "./rig";
import type { CharOpts, CharPose, EyeMode } from "./rig";

/** A colour by id, or a palette given whole (the CSS-variable master passes one). */
const colourOf = (c: LionColourId | LionColour): LionColour => (typeof c === "string" ? LION_COLOURS[c] ?? LION_COLOURS.red : c);

/** Where the sleeping z rises from. */
export const LION_Z: readonly [number, number] = [320, 70];

const FACE: Record<CharPose, { eyes: EyeMode; mouth: "smile" | "open" | "rest" }> = {
  idle: { eyes: "open", mouth: "smile" },
  hop: { eyes: "open", mouth: "smile" },
  cheer: { eyes: "happy", mouth: "open" },
  react: { eyes: "open", mouth: "open" },
  sleep: { eyes: "sleep", mouth: "rest" },
};

/** Each part's place in a pose drawn still: the peak of its animation. Sleep
 *  is always drawn this way; it has no moving limbs. */
const STILL: Partial<Record<CharPose, Record<string, string>>> = {
  hop: { body: "translate(0 -12)", earL: "rotate(-14 104 112)", earR: "rotate(14 276 112)" },
  cheer: { body: "translate(0 -34)", head: "rotate(-6 190 240)", tail: "rotate(-20 110 300)" },
  react: { head: "translate(10 -72) rotate(-14 190 240)", mane: "translate(190 156) scale(1.1) translate(-190 -156)", seg1: "translate(6 -36) rotate(-18 160 308)", seg2: "translate(0 -12) rotate(-8 116 308)",
           legsF: "translate(10 -44)", ctail: "rotate(-24 60 284)" },
  sleep: { head: "translate(0 12) rotate(5 190 240)" },
};

/** The Lion's shapes in its 400 box, as SVG markup. `id` keeps its gradient
 *  ids apart from another drawing's on the same page. */
export function lionMarkup(colour: LionColourId | LionColour, id: string, { pose = "idle", detail = true, shadow = true, still = false, team }: CharOpts = {}): string {
  const p = colourOf(colour);
  const face = FACE[pose];
  const at = (still || pose === "sleep" ? STILL[pose] : undefined) ?? {};
  const u = (name: string) => `url(#${name}-${id})`;

  const defs = `<defs>${sharedDefs(id)}${ball("body", id, p.body, [0.36, 0.26, 0.82])}${ball("mane", id, p.mane, [0.36, 0.28, 0.8])}${ball("accent", id, p.accent, [0.34, 0.28, 0.8])}`
    + ramp("cape", id, [p.body[0], p.body[1], p.body[2]], [0, 0, 1, 1]) + glow("under", id, "#2a0a14", 0.4) + glow("blush", id, p.blush, 0.85, 0.25)
    + `</defs>`;

  let hem = "M92 322";
  for (let i = 0; i < 8; i++) hem += `q12.3 ${i < 4 ? 15 : 11} 24.6 ${i < 3 ? 3 : i > 4 ? -3 : 0}`;
  const torso = part("cmp-tail", `<path d="M112 306C92 304 86 290 92 274" fill="none" stroke="${p.body[2]}" stroke-width="12" stroke-linecap="round"/><path d="${puff(92, 264, 19, 17, 6, 0.3)}" fill="${u("mane")}"/>`, at.tail)
    + `<ellipse cx="150" cy="344" rx="28" ry="13" fill="${p.shoe}"/><ellipse cx="230" cy="344" rx="28" ry="13" fill="${p.shoe}"/>`
    + (detail ? `<path d="M130 341h40M210 341h40" stroke="${p.mane[1]}" stroke-width="3.6" stroke-linecap="round" opacity=".9"/>` : "")
    + `<path d="M116 232Q190 212 264 232L290 322Q190 348 90 322Z" fill="${u("cape")}"/>`
    + `<path d="${hem}" fill="none" stroke="${p.accent[1]}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>`
    + (detail ? `<g fill="none" stroke="${p.trim}" stroke-width="3.2" stroke-linecap="round" opacity=".9">${curl(120, 292, 0, 0.8)}${curl(238, 292, -10, 0.8)}</g>` : "")
    + `<ellipse cx="190" cy="246" rx="84" ry="24" fill="${u("under")}"/>`;

  // The dance costume, drawn only for the special: three cloth segments, a tail and the two dancers' legs,
  // laid out behind the head (to its left). It stands outside the at-rest footprint.
  const hemOf = (cx: number) => `M${cx - 44} 308q11 13 22 0q11 13 22 0q11 13 22 0q11 13 22 0`;
  const seg = (i: number, cx: number, baked?: string) => part(`cmp-seg${i}`, part("cmp-rip",
    `<path d="M${cx - 46} 310Q${cx - 52} 246 ${cx} 240Q${cx + 52} 246 ${cx + 46} 310Z" fill="${u("cape")}"/>`
    + `<path d="${hemOf(cx)}" fill="none" stroke="${p.accent[1]}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>`
    + `<path d="${puff(cx, 244, 30, 9, 5, 0.3, 0.62)}" fill="${u("mane")}"/>`
    + (detail ? `<g fill="none" stroke="${p.trim}" stroke-width="3" stroke-linecap="round" opacity=".9">${curl(cx - 14, 284, i * 40, 0.75)}</g>` : "")), baked);
  const leg = (x: number) => `<rect x="${x - 11}" y="298" width="22" height="46" rx="9" fill="${p.body[2]}"/><ellipse cx="${x + 4}" cy="346" rx="18" ry="9.5" fill="${p.shoe}"/>`
    + (detail ? `<path d="M${x - 8} 344h24" stroke="${p.mane[1]}" stroke-width="3" stroke-linecap="round" opacity=".9"/>` : "");
  const dancing = pose === "react";
  const costume = dancing ? part("cmp-costume", `<g transform="translate(-46 0)">`
    + part("cmp-legs-b", leg(82) + leg(118), at.legsB) + part("cmp-legs-f", leg(206) + leg(246), at.legsF)
    + part("cmp-ctail", `<path d="M58 284C40 280 34 264 40 250" fill="none" stroke="${p.body[2]}" stroke-width="11" stroke-linecap="round"/><path d="${puff(40, 240, 18, 16, 6, 0.3)}" fill="${u("mane")}"/>`, at.ctail)
    + seg(3, 92, at.seg3) + seg(2, 140, at.seg2) + seg(1, 188, at.seg1) + `</g>`)
    + (still ? "" : bits("cmp-poof", 96, 270, 84, 7, ["#fff6e6", p.accent[1], "#fff6e6"], -210, 30, 1.1)) : "";

  const brow = (cx: number) => `<path d="${puff(cx, 116, 27, 10.5, 5, 0.35, 0.62)}" fill="${u("mane")}"/>`;
  const mouth = face.mouth === "open"
    ? `<path d="M176 208q14 6 28 0q-2 18-14 18q-12 0-14-18z" fill="#7a1a26"/><path d="M182 220q8-5 16 0q-3 6-8 6q-5 0-8-6z" fill="#f08a8a"/>`
    : face.mouth === "rest" ? `<path d="M183 211q7 5 14 0" fill="none" stroke="#8a5240" stroke-width="3" stroke-linecap="round"/>`
      : `<path d="M190 202v7M176 210q7 8 14-1q7 9 14 1" fill="none" stroke="#8a5240" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>`;
  const big = { k: 1.2, detail };
  const head = part("cmp-mane", `<path d="${puff(190, 156, 120, 104, 14, 0.12, 0.58)}" fill="${u("mane")}"/>`, at.mane)
    + part("cmp-ear-l", `<circle cx="92" cy="96" r="25" fill="${u("accent")}"/>`, at.earL) + part("cmp-ear-r", `<circle cx="288" cy="96" r="25" fill="${u("accent")}"/>`, at.earR)
    + `<path d="${puff(190, 62, 24, 12, 5, 0.3)}" fill="${u("mane")}"/><circle cx="190" cy="46" r="15" fill="${u("accent")}"/>`
    + `<path d="M94 156C94 104 136 72 190 72C244 72 286 104 286 156C286 206 246 236 190 236C134 236 94 206 94 156Z" fill="${u("body")}"/>`
    + `<circle cx="190" cy="100" r="13" fill="${u("accent")}"/><ellipse cx="186" cy="95" rx="4.6" ry="2.8" fill="#fff" opacity=".8" transform="rotate(-30 186 95)"/>`
    + `<ellipse cx="148" cy="160" rx="31" ry="33" fill="${p.eyeRing}"/><ellipse cx="232" cy="160" rx="31" ry="33" fill="${p.eyeRing}"/>`
    + brow(146) + brow(234)
    + `<ellipse cx="190" cy="206" rx="46" ry="29" fill="${u("mane")}"/>`
    + `<ellipse cx="116" cy="200" rx="20" ry="13" fill="${u("blush")}"/><ellipse cx="264" cy="200" rx="20" ry="13" fill="${u("blush")}"/>`
    + eye(148, 162, face.eyes, id, big) + eye(232, 162, face.eyes, id, big)
    + `<path d="M178 190Q190 183 202 190Q199 202 190 203Q181 202 178 190Z" fill="${p.nose}"/><ellipse cx="186" cy="191" rx="4.2" ry="1.9" fill="#fff" opacity=".5"/>`
    + mouth
    + `<path d="${puff(190, 240, 34, 12, 5, 0.2, 0.62)}" fill="${u("mane")}"/>`;

  // In the special the plain cape gives way to the costume; drawn still, the costume alone shows.
  const cape = dancing ? (still ? "" : part("cmp-cape", torso)) : torso;
  const body = part("cmp-body", costume + part("cmp-torso", cape, at.torso) + part("cmp-head", head, at.head) + (team ? kerchief(team, 122, 258, 244, 7, 236) : ""), at.body);
  return defs + (team ? teamPad(team, 190, 124) : "") + (shadow ? groundShadow(id, 190, 128) : "") + body + (pose === "react" ? bits("cmp-pop", 190, 150, 176, 9, [p.accent[1], "#e2474a", "#fff3c0", "#f2c14e"], -176, -4, 1.15) : "") + (pose === "cheer" ? confetti(190, 150) : "");
}

const portraits = new Map<string, string>();

/** The round portrait as a data URL: the head in its mane on the colour's
 *  ground, clipped to a disc. `small` drops the fine detail. */
export function lionPortraitUrl(colour: LionColourId, small: boolean): string {
  const key = `${colour}/${small ? "s" : "l"}`;
  let url = portraits.get(key);
  if (!url) {
    url = dataUrl(lionPortraitSvg(colour, small));
    portraits.set(key, url);
  }
  return url;
}

export function lionPortraitSvg(colour: LionColourId, small: boolean): string {
  return portraitSvg(lionMarkup(colour, "p", { detail: !small, shadow: false }), 190, 146, 140, colourOf(colour).disc);
}
