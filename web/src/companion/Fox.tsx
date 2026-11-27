// The Red-envelope Fox, drawn in its 400-unit box on the store characters'
// rig: gradients only, no SVG filters. One string builder draws every pose;
// the portrait is the same drawing as an image. The colour is a palette swap
// (`storePalette.ts`). Its signature reaction is the coin peek: it lifts the
// envelope's flap, gold coins spill out in an arc and glint, and it snaps
// the flap shut.
import { FOX_COLOURS } from "./storePalette";
import type { FoxColour, FoxColourId } from "./storePalette";
import { ball, confetti, spark, dataUrl, eye, glow, groundShadow, kerchief, part, portraitSvg, ramp, sharedDefs } from "./rig";
import type { CharOpts, CharPose, EyeMode } from "./rig";

/** A colour by id, or a palette given whole (the CSS-variable master passes one). */
const colourOf = (c: FoxColourId | FoxColour): FoxColour => (typeof c === "string" ? FOX_COLOURS[c] ?? FOX_COLOURS.orange : c);

/** Where the sleeping z rises from. */
export const FOX_Z: readonly [number, number] = [318, 96];

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
  hop: { body: "translate(0 -12)", tail: "rotate(-10 244 322)", earL: "rotate(-8 140 112)", earR: "rotate(8 232 112)" },
  cheer: { body: "translate(0 -34)", head: "rotate(-6 186 238)", tail: "rotate(-14 244 322)", prop: "translate(0 -10) rotate(-5 186 296)" },
  react: { head: "translate(0 -8) rotate(-6 186 238)", tail: "rotate(-16 244 322)", flap: "translate(0 516) scale(1 -1)", toss: "translate(0 -240) translate(186 297) scale(1.2) translate(-186 -297)",
           earL: "rotate(-8 140 112)", earR: "rotate(8 232 112)" },
  sleep: { head: "translate(0 12) rotate(6 186 238)", earL: "rotate(-14 140 112)", earR: "rotate(14 232 112)", tail: "rotate(8 244 322)" },
};

/** Where each coin is in the still: two landed either side, one at the top of its arc. */
const COINS = ["translate(-112 264)", "translate(104 264)", "translate(8 -52)"];

/** The Fox's shapes in its 400 box, as SVG markup. `id` keeps its gradient
 *  ids apart from another drawing's on the same page. */
export function foxMarkup(colour: FoxColourId | FoxColour, id: string, { pose = "idle", detail = true, shadow = true, still = false, team }: CharOpts = {}): string {
  const p = colourOf(colour);
  const face = FACE[pose];
  const at = (still || pose === "sleep" ? STILL[pose] : undefined) ?? {};
  const u = (name: string) => `url(#${name}-${id})`;

  const defs = `<defs>${sharedDefs(id)}${ball("fur", id, p.fur, [0.36, 0.28, 0.8])}${ball("seal", id, p.seal, [0.34, 0.28, 0.8])}`
    + ramp("tail", id, [p.fur[0], p.fur[1], p.fur[2]], [0, 0, 1, 1]) + ramp("env", id, [p.envelope[0], p.envelope[1], p.envelope[2]], [0, 0, 1, 1]) + glow("under", id, "#3a1a10", 0.32) + glow("blush", id, p.blush, 0.75, 0.25)
    + `</defs>`;

  const torso = part("cmp-tail", `<path d="M232 338C322 348 372 270 342 200C332 176 302 174 292 196C310 238 290 272 236 288Z" fill="${u("tail")}"/>`
      + `<path d="M346 212C338 178 304 170 292 196C304 202 316 220 320 240C334 236 342 224 346 212Z" fill="${p.tip}"/>`, at.tail)
    + `<ellipse cx="150" cy="344" rx="28" ry="13" fill="${p.dark}"/><ellipse cx="222" cy="344" rx="28" ry="13" fill="${p.dark}"/>`
    + `<ellipse cx="186" cy="284" rx="70" ry="70" fill="${u("fur")}"/>`
    + `<ellipse cx="186" cy="244" rx="68" ry="22" fill="${u("under")}"/>`;

  const ear = (s: number) => {
    const x = (v: number) => 186 + s * v;
    return `<path d="M${x(-84)} 132Q${x(-92)} 60 ${x(-76)} 28Q${x(-70)} 18 ${x(-60)} 26Q${x(-24)} 54 ${x(-6)} 90Z" fill="${u("tail")}"/>`
      + `<path d="M${x(-70)} 108Q${x(-76)} 66 ${x(-68)} 46Q${x(-44)} 62 ${x(-30)} 88Z" fill="${p.earIn}"/>`;
  };
  const look = { detail, ink: p.lid, fill: p.eye ?? "", pupil: p.pupil ?? "" };
  const mouth = face.mouth === "open"
    ? `<path d="M175 216q11 5 22 0q-2 15-11 15q-9 0-11-15z" fill="#8a3038"/><path d="M180 226q6-4 12 0q-3 5-6 5q-3 0-6-5z" fill="#f08a8a"/>`
    : face.mouth === "rest" ? `<path d="M180 218q6 4 12 0" fill="none" stroke="#8a5240" stroke-width="3" stroke-linecap="round"/>`
      : `<path d="M186 211v6M173 218q7 8 13-1q6 9 13 1" fill="none" stroke="#8a5240" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`;
  const head = part("cmp-ear-l", ear(1), at.earL) + part("cmp-ear-r", ear(-1), at.earR)
    + `<path d="M82 154C82 102 132 74 186 74C240 74 290 102 290 154C290 196 254 228 186 240C118 228 82 196 82 154Z" fill="${u("fur")}"/>`
    + `<path d="M86 176C124 160 158 192 186 200C214 192 248 160 286 176C274 212 238 230 186 239C134 230 98 212 86 176Z" fill="${p.cream}"/>`
    + `<ellipse cx="118" cy="198" rx="19" ry="12" fill="${u("blush")}"/><ellipse cx="254" cy="198" rx="19" ry="12" fill="${u("blush")}"/>`
    + eye(146, 156, face.eyes, id, look) + eye(226, 156, face.eyes, id, look)
    + (detail && face.eyes === "open" ? `<path d="M126 144q-8-2-13-8M246 144q8-2 13-8" fill="none" stroke="${p.lid}" stroke-width="3.4" stroke-linecap="round" opacity=".8"/>` : "")
    + `<ellipse cx="186" cy="203" rx="11.5" ry="8.5" fill="${p.nose}"/><ellipse cx="183" cy="200" rx="3.6" ry="1.8" fill="#fff" opacity=".55"/>`
    + mouth;

  const flap = `<path d="M146 258L186 300L226 258Z" fill="${p.envelope[2]}" stroke="${p.seal[1]}" stroke-width="2.6" stroke-linejoin="round"/>`;
  const envelope = `<rect x="144" y="250" width="84" height="94" rx="9" fill="${u("env")}"/>`
    + (detail ? `<rect x="150" y="256" width="72" height="82" rx="6" fill="none" stroke="${p.seal[1]}" stroke-width="1.8" opacity=".7"/>` : "")
    + (pose === "react" ? `<rect class="cmp-inside" x="160" y="232" width="52" height="30" rx="4" fill="${p.seal[0]}"/>` : "")
    + part("cmp-flap", flap, at.flap)
    + `<circle cx="186" cy="304" r="13.5" fill="${u("seal")}"/>`;
  const paws = `<ellipse cx="138" cy="304" rx="17" ry="23" fill="${u("fur")}" transform="rotate(16 138 304)"/><ellipse cx="234" cy="304" rx="17" ry="23" fill="${u("fur")}" transform="rotate(-16 234 304)"/>`;

  // The coins are drawn where the tossed envelope opens, over the head; their keyframes carry them from there.
  const coin = (i: number) => part(`cmp-coin cmp-coin${i}`, `<circle cx="186" cy="60" r="30" fill="${u("seal")}"/><rect x="175" y="49" width="22" height="22" rx="4" fill="${p.seal[3]}" opacity=".85"/>`
    + `<ellipse cx="174" cy="46" rx="9" ry="5" fill="#fff" opacity=".8" transform="rotate(-30 174 46)"/>`, still ? COINS[i - 1] : "");
  const coins = pose === "react" ? coin(1) + coin(2) + coin(3) + `<g class="cmp-glint">${spark(60, 300, 2.4, "#fff6d6")}${spark(312, 296, 2.2, "#fff6d6")}</g>` : "";
  // In the special the envelope is thrown up in front of the face, so it is drawn over the head; at rest it sits under the chin either way.
  const prop = part("cmp-prop", part("cmp-toss", envelope, at.toss) + paws, at.prop), face2 = part("cmp-head", head, at.head);
  const body = part("cmp-body", part("cmp-torso", torso) + (team ? kerchief(team, 124, 248, 226, 10, 240) : "") + (pose === "react" ? face2 + prop : prop + face2) + coins, at.body);
  return defs + (shadow ? groundShadow(id, 200, 126) : "") + body + (pose === "cheer" ? confetti(186, 150) : "");
}

const portraits = new Map<string, string>();

/** The round portrait as a data URL: the head and ears on the colour's
 *  ground, clipped to a disc. `small` drops the fine detail. */
export function foxPortraitUrl(colour: FoxColourId, small: boolean): string {
  const key = `${colour}/${small ? "s" : "l"}`;
  let url = portraits.get(key);
  if (!url) {
    url = dataUrl(foxPortraitSvg(colour, small));
    portraits.set(key, url);
  }
  return url;
}

export function foxPortraitSvg(colour: FoxColourId, small: boolean): string {
  return portraitSvg(foxMarkup(colour, "p", { detail: !small, shadow: false }), 186, 138, 132, colourOf(colour).disc);
}
