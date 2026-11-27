// The Lucky Cat, drawn in its 400-unit box on the store characters' rig:
// gradients only, no SVG filters. One string builder draws every pose; the
// figure inlines it (the pose CSS moves its parts), and the portrait is the
// same drawing as an image, one cached data URL per colour. The colour is a
// palette swap (`storePalette.ts`). Its signature reaction is the beckon and
// card: the raised paw sweeps forward twice, then a card pops up, flips and
// shows a suit. The face carries all four suits and the joker; the svg's
// `data-suit` (s, h, c, d or j), set by the owner on each play, shows one.
import { CAT_COLOURS } from "./storePalette";
import type { CatColour, CatColourId } from "./storePalette";
import { ball, confetti, dataUrl, eye, glow, groundShadow, part, portraitSvg, ramp, sharedDefs, spark, teamPad, teamPaint } from "./rig";
import type { CharOpts, CharPose, EyeMode } from "./rig";

/** A colour by id, or a palette given whole (the CSS-variable master passes one). */
const colourOf = (c: CatColourId | CatColour): CatColour => (typeof c === "string" ? CAT_COLOURS[c] ?? CAT_COLOURS.white : c);

/** Where the sleeping z rises from. */
export const CAT_Z: readonly [number, number] = [322, 70];

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
  hop: { body: "translate(0 -12)", arm: "rotate(-8 268 268)", tail: "rotate(-18 100 292)" },
  cheer: { body: "translate(0 -34)", head: "rotate(-5 186 232)", arm: "rotate(-10 268 268)", bell: "rotate(-16 186 244)" },
  react: { head: "rotate(4 186 232)", arm: "rotate(26 268 268)", tail: "rotate(-20 100 292)", bell: "rotate(14 186 244)" },
  sleep: { head: "translate(0 10) rotate(5 186 232)", arm: "rotate(18 268 268)" },
};

/** The Cat's shapes in its 400 box, as SVG markup. `id` keeps its gradient
 *  ids apart from another drawing's on the same page. */
export function catMarkup(colour: CatColourId | CatColour, id: string, { pose = "idle", detail = true, shadow = true, still = false, team }: CharOpts = {}): string {
  const p = colourOf(colour);
  const face = FACE[pose];
  const at = (still || pose === "sleep" ? STILL[pose] : undefined) ?? {};
  const u = (name: string) => `url(#${name}-${id})`;
  const [warm, cool] = p.patches ?? ["", ""];

  const defs = `<defs>${sharedDefs(id)}${ball("fur", id, p.fur, [0.36, 0.28, 0.8])}${ball("bell", id, p.bell, [0.34, 0.28, 0.8])}`
    + ramp("limb", id, [p.fur[0], p.fur[1], p.fur[2]], [0, 0, 1, 1]) + ramp("collar", id, [p.collar[0], p.collar[1], p.collar[2]], [0, 0, 1, 1])
    + ramp("card", id, ["#ffffff", "#f1ede4"], [0, 0, 0, 1]) + ramp("back", id, ["#3a9a6c", "#1d5638"], [0, 0, 1, 1]) + glow("under", id, "#3a2a4a", 0.3) + glow("blush", id, p.blush, 0.8, 0.25)
    + (p.patches ? `<clipPath id="head-${id}"><ellipse cx="186" cy="152" rx="96" ry="82"/></clipPath><clipPath id="belly-${id}"><ellipse cx="186" cy="278" rx="82" ry="76"/></clipPath>` : "")
    + `</defs>`;

  const torso = part("cmp-tail", `<path d="M96 304C58 302 50 262 72 246C80 242 86 248 86 256C86 270 98 276 112 280Z" fill="${cool || u("limb")}"/>`, at.tail)
    + `<ellipse cx="146" cy="342" rx="34" ry="15" fill="${u("limb")}"/><ellipse cx="226" cy="342" rx="34" ry="15" fill="${u("limb")}"/>`
    + `<ellipse cx="186" cy="278" rx="82" ry="76" fill="${u("fur")}"/>`
    + (p.patches ? `<g clip-path="url(#belly-${id})"><ellipse cx="252" cy="306" rx="34" ry="40" fill="${warm}"/></g>` : "");

  const arm = `<g transform="rotate(20 268 268)"><rect x="243" y="138" width="50" height="156" rx="25" fill="${warm || u("limb")}"/>`
    + `<ellipse cx="268" cy="164" rx="11" ry="9" fill="${p.pad}" opacity=".9"/>`
    + (detail ? `<g fill="${p.pad}" opacity=".9"><circle cx="254" cy="150" r="4.6"/><circle cx="268" cy="145" r="4.6"/><circle cx="282" cy="150" r="4.6"/></g>` : "") + `</g>`;

  const earL = `<path d="M100 128Q96 62 104 40Q108 30 118 36Q152 56 178 84Z" fill="${warm || u("limb")}"/><path d="M116 104Q114 70 119 56Q138 66 154 82Z" fill="${p.earIn}"/>`;
  const earR = `<path d="M272 128Q276 62 268 40Q264 30 254 36Q220 56 194 84Z" fill="${cool || u("limb")}"/><path d="M256 104Q258 70 253 56Q234 66 218 82Z" fill="${p.earIn}"/>`;
  const look = { detail, ink: p.lid, fill: p.eye ?? "", pupil: p.pupil ?? "" };
  const mouth = face.mouth === "open"
    ? `<path d="M174 196q12 5 24 0q-2 17-12 17q-10 0-12-17z" fill="#8a3038"/><path d="M179 207q7-4 14 0q-3 6-7 6q-4 0-7-6z" fill="#f08a8a"/>`
    : face.mouth === "rest" ? `<path d="M180 197q6 4 12 0" fill="none" stroke="${p.whisker}" stroke-width="3" stroke-linecap="round"/>`
      : `<path d="M186 189v8M174 198q6 7 12-1q6 8 12 1" fill="none" stroke="${p.eye ? p.whisker : "#8a5240"}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`;
  const head = part("cmp-ear-l", earL) + part("cmp-ear-r", earR)
    + `<ellipse cx="186" cy="152" rx="96" ry="82" fill="${u("fur")}"/>`
    + (p.patches ? `<g clip-path="url(#head-${id})"><path d="M84 138C92 84 140 60 182 64C176 100 152 128 112 146Z" fill="${warm}"/><path d="M206 62C250 66 284 100 290 144C258 134 224 108 206 62Z" fill="${cool}"/></g>` : "")
    + `<ellipse cx="121" cy="187" rx="21" ry="13.5" fill="${u("blush")}"/><ellipse cx="251" cy="187" rx="21" ry="13.5" fill="${u("blush")}"/>`
    + eye(150, 158, face.eyes, id, look) + eye(222, 158, face.eyes, id, look)
    + `<path d="M177 180Q186 175 195 180Q193 189 186 190Q179 189 177 180Z" fill="${p.nose}"/>`
    + mouth
    + (detail ? `<path d="M108 170l-34-8M108 182l-36 4M264 170l34-8M264 182l36 4" stroke="${p.whisker}" stroke-width="2.6" stroke-linecap="round" opacity=".9"/>` : "");

  const collar = `<path d="M112 214Q186 256 260 214L264 236Q186 282 108 236Z" ${teamPaint(team, u("collar"))}/>`
    + `<path d="M118 219Q186 258 254 219L260 214Q186 256 112 214Z" fill="${team ? "#000" : p.collar[3]}" opacity="${team ? ".25" : ".5"}"/>`
    + (detail ? `<path d="M110 230Q186 274 262 230" fill="none" stroke="${p.trim}" stroke-width="2.6"/>` : "")
    + part("cmp-bell", `<circle cx="186" cy="262" r="17.5" fill="${u("bell")}"/>`
      + `<path d="M173 265h26" stroke="${p.bellInk}" stroke-width="3" stroke-linecap="round"/><circle cx="186" cy="272.5" r="3" fill="${p.bellInk}"/>`
      + `<ellipse cx="179" cy="253" rx="5.4" ry="3.2" fill="#fff" opacity=".8" transform="rotate(-30 179 253)"/>`, at.bell);

  const card = `<g transform="rotate(-12 124 300)"><rect x="92" y="254" width="62" height="86" rx="8" fill="${u("card")}" stroke="#e2ac45" stroke-width="3"/>`
    + `<path d="M123 274c-13 13-15 26-3 24c-1 6-3 9-5 12h16c-2-3-4-6-5-12c12 2 10-11-3-24z" fill="#1d1f26"/></g>`
    + `<ellipse cx="148" cy="320" rx="21" ry="18" fill="${u("fur")}"/>`;

  const pip = (suit: string, on: boolean, art: string) => `<g class="cmp-suit cmp-suit-${suit}" opacity="${on ? 1 : 0}">${art}</g>`;
  const trick = pose === "react" ? part("cmp-card", `<g class="cmp-card-back"${still ? ` opacity="0"` : ""}><rect x="286" y="52" width="60" height="84" rx="8" fill="${u("back")}" stroke="#fbf9f4" stroke-width="5"/>`
    + `<path d="M316 78l11 16l-11 16l-11-16z" fill="#f2d27c" opacity=".9"/></g>`
    + `<g class="cmp-card-face" opacity="${still ? 1 : 0}"><rect x="286" y="52" width="60" height="84" rx="8" fill="${u("card")}" stroke="#d9d3c6" stroke-width="2"/>`
    + pip("h", true, `<path d="M316 114C294 99 295 80 306 78C312 77 315 81 316 85C317 81 320 77 326 78C337 80 338 99 316 114Z" fill="#c9283a"/>`)
    + pip("d", false, `<path d="M316 74l15 20l-15 20l-15-20z" fill="#c9283a"/>`)
    + pip("s", false, `<path transform="translate(193 -198)" d="M123 274c-13 13-15 26-3 24c-1 6-3 9-5 12h16c-2-3-4-6-5-12c12 2 10-11-3-24z" fill="#1d1f26"/>`)
    + pip("c", false, `<g fill="#1d1f26"><circle cx="316" cy="84" r="8.5"/><circle cx="306.5" cy="97" r="8.5"/><circle cx="325.5" cy="97" r="8.5"/><path d="M316 94l-6 20h12z"/></g>`)
    + pip("j", false, spark(316, 94, 2.3, "#c9283a") + `<circle cx="316" cy="94" r="6" fill="#f2c14e"/>`)
    + `</g>`) : "";
  const body = part("cmp-body", part("cmp-arm-r", arm, at.arm) + part("cmp-torso", torso)
    + part("cmp-head", head + `<ellipse cx="186" cy="232" rx="78" ry="16" fill="${u("under")}"/>`, at.head) + collar + part("cmp-prop", card), at.body);
  return defs + (team ? teamPad(team, 186, 124) : "") + (shadow ? groundShadow(id, 186, 124) : "") + body + trick + (pose === "cheer" ? confetti(186, 150) : "");
}

const portraits = new Map<string, string>();

/** The round portrait as a data URL: the head and the raised paw on the
 *  colour's ground, clipped to a disc. `small` drops the fine detail. */
export function catPortraitUrl(colour: CatColourId, small: boolean): string {
  const key = `${colour}/${small ? "s" : "l"}`;
  let url = portraits.get(key);
  if (!url) {
    url = dataUrl(catPortraitSvg(colour, small));
    portraits.set(key, url);
  }
  return url;
}

export function catPortraitSvg(colour: CatColourId, small: boolean): string {
  return portraitSvg(catMarkup(colour, "p", { detail: !small, shadow: false }), 198, 146, 138, colourOf(colour).disc);
}
