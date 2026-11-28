// The Jade Rabbit, drawn in its 400-unit box on the store characters' rig:
// gradients only, no SVG filters. One string builder draws every pose; the
// figure inlines it (the pose CSS moves its parts), and the portrait is the
// same drawing as an image, one cached data URL per colour. The colour is a
// palette swap (`storePalette.ts`). Its signature reaction is the mooncake
// share: it lifts the cake overhead, breaks it in two with a burst of
// crumbs, keeps one half at its chest and reaches the other toward the
// viewer, its arm coming forward and the half growing as it nears.
import { RABBIT_COLOURS } from "./storePalette";
import type { RabbitColour, RabbitColourId } from "./storePalette";
import { ball, bits, confetti, dataUrl, eye, glow, groundShadow, part, portraitSvg, puff, ramp, sharedDefs } from "./rig";
import type { CharOpts, CharPose, EyeMode } from "./rig";

/** A colour by id, or a palette given whole (the CSS-variable master passes one). */
const colourOf = (c: RabbitColourId | RabbitColour): RabbitColour => (typeof c === "string" ? RABBIT_COLOURS[c] ?? RABBIT_COLOURS.moon : c);

/** Where the sleeping z rises from. */
export const RABBIT_Z: readonly [number, number] = [296, 96];

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
  hop: { body: "translate(0 -12)", earL: "rotate(-14 150 130)", earR: "rotate(14 222 130)" },
  cheer: { body: "translate(0 -34)", earL: "rotate(-16 150 130)", earR: "rotate(16 222 130)", prop: "translate(0 -8) rotate(-5 186 288)" },
  react: { head: "translate(-2 0) rotate(-6 186 240)", earL: "rotate(-14 150 130)", earR: "rotate(14 222 130)", halfL: "translate(-22 -4) rotate(-8 186 288)", halfR: "translate(54 18) translate(186 288) rotate(8) scale(1.55) translate(-186 -288)" },
  sleep: { head: "translate(0 10) rotate(5 186 240)", earL: "rotate(-30 150 130)", earR: "rotate(36 222 130)" },
};

/** The Rabbit's shapes in its 400 box, as SVG markup. `id` keeps its gradient
 *  ids apart from another drawing's on the same page. */
export function rabbitMarkup(colour: RabbitColourId | RabbitColour, id: string, { pose = "idle", detail = true, shadow = true, still = false }: CharOpts = {}): string {
  const p = colourOf(colour);
  const face = FACE[pose];
  const at = (still || pose === "sleep" ? STILL[pose] : undefined) ?? {};
  const u = (name: string) => `url(#${name}-${id})`;

  const defs = `<defs>${sharedDefs(id)}${ball("fur", id, p.fur, [0.36, 0.28, 0.8])}${ball("cake", id, p.cake, [0.34, 0.28, 0.78])}`
    + ramp("ear", id, [p.fur[0], p.fur[1], p.fur[2]], [0, 0, 1, 1]) + ramp("foot", id, p.foot, [0, 0, 0, 1]) + glow("under", id, "#3a2a4a", 0.28) + glow("blush", id, p.blush, 0.8, 0.25)
    + (pose === "react" ? `<clipPath id="halfl-${id}"><rect x="126" y="230" width="60" height="116"/></clipPath><clipPath id="halfr-${id}"><rect x="186" y="230" width="60" height="116"/></clipPath>` : "")
    + `</defs>`;

  const torso = part("cmp-tail", `<circle cx="262" cy="304" r="21" fill="${u("fur")}"/>`)
    + part("cmp-foot-l", `<ellipse cx="148" cy="342" rx="34" ry="15" fill="${u("foot")}"/>`)
    + part("cmp-foot-r", `<ellipse cx="226" cy="342" rx="34" ry="15" fill="${u("foot")}"/>`)
    + `<ellipse cx="186" cy="282" rx="76" ry="70" fill="${u("fur")}"/>`
    + `<ellipse cx="186" cy="238" rx="70" ry="22" fill="${u("under")}"/>`;

  const ear = (cx: number, s: number) => `<g transform="rotate(${-8 * s} ${cx} 120)"><ellipse cx="${cx}" cy="74" rx="24" ry="68" fill="${u("ear")}"/>`
    + `<ellipse cx="${cx}" cy="80" rx="10.5" ry="46" fill="${p.earIn}" opacity=".9"/></g>`;
  const mouth = face.mouth === "open"
    ? `<path d="M174 211q12 5 24 0q-2 17-12 17q-10 0-12-17z" fill="#8a3038"/><path d="M179 222q7-4 14 0q-3 6-7 6q-4 0-7-6z" fill="#f08a8a"/>`
    : face.mouth === "rest" ? `<path d="M180 212q6 4 12 0" fill="none" stroke="#8a5240" stroke-width="3" stroke-linecap="round"/>`
      : `<path d="M186 205v7M174 213q6 7 12-1q6 8 12 1" fill="none" stroke="#8a5240" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`;
  const head = part("cmp-ear-l", ear(148, 1), at.earL) + part("cmp-ear-r", ear(224, -1), at.earR)
    + `<ellipse cx="186" cy="172" rx="88" ry="76" fill="${u("fur")}"/>`
    + `<ellipse cx="123" cy="201" rx="21" ry="13.5" fill="${u("blush")}"/><ellipse cx="249" cy="201" rx="21" ry="13.5" fill="${u("blush")}"/>`
    + eye(152, 174, face.eyes, id, { detail }) + eye(220, 174, face.eyes, id, { detail })
    + `<path d="M177 195Q186 190 195 195Q193 204 186 205Q179 204 177 195Z" fill="${p.nose}"/>`
    + mouth;

  const petals = [0, 1, 2, 3, 4].map((i) => `<path transform="rotate(${i * 72} 186 288)" d="M186 284q-10-12 0-24q10 12 0 24"/>`).join("");
  const cake = `<path d="${puff(186, 288, 47, 47, 12, 0.2, 0.56)}" fill="${u("cake")}"/>`
    + `<circle cx="186" cy="288" r="34" fill="none" stroke="${p.cakeLine}" stroke-width="2.8" opacity=".7"/>`
    + (detail ? `<g fill="none" stroke="${p.cakeLine}" stroke-width="2.8" stroke-linecap="round" opacity=".8">${petals}</g>` : "")
    + `<circle cx="186" cy="288" r="5.5" fill="${p.cakeLine}" opacity=".8"/>`
    + (detail ? `<path d="M158 262q14-12 30-12" stroke="${p.cake[0]}" stroke-width="4" fill="none" stroke-linecap="round" opacity=".7"/>` : "")
;
  const pawL = `<ellipse cx="140" cy="292" rx="17" ry="21" fill="${u("fur")}" transform="rotate(20 140 288)"/>`;
  const pawR = `<ellipse cx="232" cy="292" rx="17" ry="21" fill="${u("fur")}" transform="rotate(-20 232 288)"/>`;
  const whole = part("cmp-prop", cake + pawL + pawR, at.prop);
  // The arm that carries the offered half toward the viewer: it grows out from the shoulder as the half comes forward.
  const reach = part("cmp-reach", `<path d="M236 266L296 304" stroke="${p.fur[2]}" stroke-width="40" stroke-linecap="round"/><path d="M236 266L296 304" stroke="${p.fur[1]}" stroke-width="33" stroke-linecap="round"/>`);
  const halves = part("cmp-half-l", `<g clip-path="url(#halfl-${id})">${cake}</g>` + pawL, at.halfL) + reach
    + part("cmp-half-r", `<g clip-path="url(#halfr-${id})">${cake}</g><path d="M186 244v88" stroke="${p.cake[0]}" stroke-width="5" opacity=".8"/>` + pawR, at.halfR)
    + (still ? "" : bits("cmp-crumbs", 186, 96, 46, 7, [p.cake[1], p.cake[0], p.cake[2]], -200, 20, 0.7));

  const body = part("cmp-body", part("cmp-torso", torso) + part("cmp-head", head, at.head) + (pose === "react" ? halves : whole), at.body);
  return defs + (shadow ? groundShadow(id, 188, 112) : "") + body + (pose === "cheer" ? confetti(186, 150) : "");
}

const portraits = new Map<string, string>();

/** The round portrait as a data URL: the head and ears on the colour's
 *  ground, clipped to a disc. The textures are drawn at every size, as at the table. */
export function rabbitPortraitUrl(colour: RabbitColourId, small: boolean): string {
  const key = `${colour}/${small ? "s" : "l"}`;
  let url = portraits.get(key);
  if (!url) {
    url = dataUrl(rabbitPortraitSvg(colour));
    portraits.set(key, url);
  }
  return url;
}

export function rabbitPortraitSvg(colour: RabbitColourId): string {
  return portraitSvg(rabbitMarkup(colour, "p", { detail: true, shadow: false }), 186, 138, 136, colourOf(colour).disc);
}
