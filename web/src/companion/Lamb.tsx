// The Lamb, drawn in its 400-unit box on the characters' rig (`rig.ts`):
// gradients only, no SVG filters. One string builder draws every pose; the
// figure inlines it (the pose CSS moves its parts), and the portrait is the
// same drawing as an image, one cached data URL per colour. The colour is a
// palette swap (`storePalette.ts`). Its signature reaction is the horn butt:
// it paws the ground and puffs up its wool, dashes and butts in a burst of
// stars and spring petals, reels with stars round its head, shakes its wool
// and tosses its head.
import { LAMB_COLOURS } from "./storePalette";
import type { LambColour, LambColourId } from "./storePalette";
import { ball, bits, confetti, curl, dataUrl, eye, glow, groundShadow, part, portraitSvg, puff, ramp, sharedDefs, spark, teamPaint } from "./rig";
import type { CharOpts, CharPose, EyeMode } from "./rig";

/** A colour by id, or a palette given whole (the CSS-variable master passes one). */
const colourOf = (c: LambColourId | LambColour): LambColour => (typeof c === "string" ? LAMB_COLOURS[c] ?? LAMB_COLOURS.newyear : c);

/** Where the sleeping z rises from. */
export const LAMB_Z: readonly [number, number] = [352, 86];

const HORN_L = "M205 100C196 52 132 30 101 74C84 100 99 137 129 133C113 122 108 101 121 86C139 63 168 77 177 110Z";
const HORN_R = "M259 100C268 52 332 30 363 74C380 100 365 137 335 133C351 122 356 101 343 86C325 63 296 77 287 110Z";
const RIDGES = "M200 62L168 92M178 38L156 80M146 30L142 74M112 40L130 82M88 72L122 94M84 106L116 106"
  + "M264 62L296 92M286 38L308 80M318 30L322 74M352 40L334 82M376 72L342 94M380 106L348 106";

const FACE: Record<CharPose, { eyes: EyeMode; mouth: "smile" | "open" | "flat" | "rest" }> = {
  idle: { eyes: "open", mouth: "smile" },
  hop: { eyes: "open", mouth: "smile" },
  cheer: { eyes: "happy", mouth: "open" },
  react: { eyes: "fierce", mouth: "flat" },
  sleep: { eyes: "sleep", mouth: "rest" },
};

/** Each part's place in a pose drawn still: the peak of its animation. Sleep
 *  is always drawn this way; it has no moving limbs. */
const STILL: Partial<Record<CharPose, Record<string, string>>> = {
  hop: { body: "translate(0 -12)", head: "rotate(-4 236 232)", earL: "rotate(16 160 160)", earR: "rotate(-16 312 160)" },
  cheer: { body: "translate(0 -34)", head: "translate(0 -4) rotate(-7 236 232)", earL: "rotate(18 160 160)", earR: "rotate(-18 312 160)", bell: "rotate(-16 236 266)" },
  react: { body: "translate(36 0)", head: "translate(12 16) rotate(15 236 232)", earL: "rotate(-12 160 160)", earR: "rotate(12 312 160)", tail: "rotate(-18 104 262)" },
  sleep: { head: "translate(-2 14) rotate(7 236 232)", earL: "rotate(-16 160 160)", earR: "rotate(16 312 160)" },
};

/** The Lamb's shapes in its 400 box, as SVG markup. `id` keeps its gradient
 *  ids apart from another drawing's on the same page. */
export function lambMarkup(colour: LambColourId | LambColour, id: string, { pose = "idle", detail = true, shadow = true, still = false, team }: CharOpts = {}): string {
  const p = colourOf(colour);
  const face = FACE[pose];
  const at = (still || pose === "sleep" ? STILL[pose] : undefined) ?? {};
  const u = (name: string) => `url(#${name}-${id})`;

  const defs = `<defs>${sharedDefs(id)}${ball("wool", id, p.wool)}${ball("skin", id, p.skin, [0.34, 0.28, 0.82])}${ball("bell", id, p.bell, [0.34, 0.28, 0.8])}`
    + ramp("horn", id, [p.horn[0], p.horn[1], p.horn[2], p.horn[3]], [0.1, 0, 0.9, 1])
    + ramp("scarf", id, [p.scarf[0], p.scarf[1], p.scarf[2]], [0, 0, 1, 1])
    + ramp("leg", id, p.leg, [0, 0, 0, 1]) + ramp("hoof", id, p.hoof, [0, 0, 0, 1]) + glow("ao", id, p.wool[3], 0.75) + glow("under", id, "#3a1f2e", 0.42)
    + glow("muzzle", id, "#fffaf0", 0.96, 0.55) + glow("blush", id, p.blush, 0.78, 0.25)
    + (detail ? `<clipPath id="horns-${id}"><path d="${HORN_L}"/><path d="${HORN_R}"/></clipPath>` : "")
    + `</defs>`;

  const hoofs = (x: number, y: number, w: number, r: number) =>
    `M${x} ${y}h${w}v${r - 2}a${r} ${r} 0 0 1-${r} ${r}h-${w - 2 * r}a${r} ${r} 0 0 1-${r}-${r}z`;
  const torso = part("cmp-tail", `<path d="${puff(84, 258, 23, 21, 6, 0.4)}" fill="${u("wool")}"/>`, at.tail)
    + `<rect x="158" y="292" width="30" height="54" rx="13" fill="${p.backLeg}"/><rect x="238" y="292" width="30" height="54" rx="13" fill="${p.backLeg}"/>`
    + `<path d="${hoofs(158, 332, 30, 8)}${hoofs(238, 332, 30, 8)}" fill="${p.hoof[1]}" opacity=".88"/>`
    + `<path d="${puff(178, 268, 96, 62, 11, 0.2)}" fill="${u("wool")}"/>`
    + (detail ? `<g fill="none" stroke="${p.curl}" stroke-width="3.6" stroke-linecap="round">${curl(102, 264, -20, 1)}${curl(84, 250, 0, 0.6)}${curl(118, 228, 20, 0.7)}${curl(164, 310, 8, 0.75)}</g>` : "")
    + `<rect x="118" y="298" width="34" height="56" rx="15" fill="${u("leg")}"/><rect x="204" y="298" width="34" height="56" rx="15" fill="${u("leg")}"/>`
    + `<ellipse cx="135" cy="302" rx="22" ry="11" fill="${u("ao")}"/><ellipse cx="221" cy="302" rx="22" ry="11" fill="${u("ao")}"/>`
    + `<path d="${hoofs(118, 336, 34, 10)}${hoofs(204, 336, 34, 10)}" fill="${u("hoof")}"/>`
    + (detail ? `<path d="M118 336h34M204 336h34" stroke="${p.trim}" stroke-width="2.4"/>` : "");

  const earL = `<path d="M162 150C132 136 100 146 84 170C108 184 142 180 166 168Z" fill="${u("skin")}"/><path d="M154 156C134 150 114 156 100 168C118 174 138 172 156 164Z" fill="${p.earIn}" opacity=".85"/>`;
  const earR = `<path d="M310 150C340 136 372 146 388 170C364 184 330 180 306 168Z" fill="${u("skin")}"/><path d="M318 156C338 150 358 156 372 168C354 174 334 172 316 164Z" fill="${p.earIn}" opacity=".85"/>`;
  const brow = (cx: number, cy: number) => {
    const s = cx < 236 ? 1 : -1;
    return `<path d="M${cx - 19 * s} ${cy - 29}L${cx + 14 * s} ${cy - 16}" stroke="#7b4a2a" stroke-width="6.5" stroke-linecap="round"/>`;
  };
  const mouth = face.mouth === "open"
    ? `<path d="M224 207q12 5 24 0q-2 17-12 17q-10 0-12-17z" fill="#8a3038"/><path d="M229 218q7-4 14 0q-3 6-7 6q-4 0-7-6z" fill="#f08a8a"/>`
    : face.mouth === "flat" ? `<path d="M228 211h16" fill="none" stroke="#8a5240" stroke-width="3.2" stroke-linecap="round"/>`
      : face.mouth === "rest" ? `<path d="M230 209q6 4 12 0" fill="none" stroke="#8a5240" stroke-width="3" stroke-linecap="round"/>`
        : `<path d="M236 201v7M224 209q6 7 12-1q6 8 12 1" fill="none" stroke="#8a5240" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`;

  // The special is drawn with both faces (the charge, then the delight), its dizzy stars, dust and petals; the still shows the butt alone.
  const special = pose === "react" && !still;
  const eyesOf = (mode: EyeMode) => eye(198, 168, mode, id, { detail }) + eye(274, 168, mode, id, { detail }) + (mode === "fierce" ? brow(198, 168) + brow(274, 168) : "");
  const petals = (cls: string, cx: number, cy: number, r: number, count: number) => `<g class="${cls}">` + Array.from({ length: count }, (_, i) => {
    const a = (i * 2 * Math.PI) / count + 0.4, x = Math.round(cx + r * (i % 2 ? 1 : 0.6) * Math.cos(a)), y = Math.round(cy + r * (i % 2 ? 1 : 0.6) * Math.sin(a));
    return `<ellipse cx="${x}" cy="${y}" rx="11" ry="6.5" fill="${i % 3 ? "#ffb7c5" : "#ff8fa8"}" transform="rotate(${(i * 67) % 180} ${x} ${y})"/>`;
  }).join("") + `</g>`;
  const head = `<ellipse cx="226" cy="266" rx="84" ry="34" fill="${u("under")}"/>`
    + `<path d="M178 246C154 256 138 280 130 306L153 312C158 288 170 268 190 256Z" ${teamPaint(team, u("scarf"))}/>`
    + `<path d="M176 250C166 264 164 282 166 298L186 296C184 280 188 266 196 256Z" ${teamPaint(team, p.scarf[2], true)}/>`
    + `<path d="M166 222Q236 268 306 222L311 247Q236 296 161 247Z" ${teamPaint(team, u("scarf"))}/>`
    + `<path d="M176 232Q236 270 298 230L306 222Q236 268 166 222Z" fill="${team ? "#000" : p.scarf[3]}" opacity="${team ? ".25" : ".55"}"/>`
    + (detail ? `<path d="M164 240Q236 288 308 240" fill="none" stroke="${p.trim}" stroke-width="2.8"/><path d="M133 300l19 5M168 292l17-1.6" stroke="${p.trim}" stroke-width="2.8" stroke-linecap="round"/>` : "")
    + part("cmp-bell", `<circle cx="236" cy="284" r="15.5" fill="${u("bell")}"/>`
      + `<path d="M225 287h22" stroke="${p.bellInk}" stroke-width="2.8" stroke-linecap="round"/><circle cx="236" cy="293" r="2.7" fill="${p.bellInk}"/>`
      + `<ellipse cx="230" cy="277" rx="4.8" ry="2.8" fill="#fff" opacity=".8" transform="rotate(-30 230 277)"/>`, at.bell)
    + `<path d="${HORN_L}" fill="${u("horn")}"/><path d="${HORN_R}" fill="${u("horn")}"/>`
    + (detail ? `<g clip-path="url(#horns-${id})"><path d="${RIDGES}" fill="none" stroke="${p.ridge}" stroke-width="3.2" stroke-linecap="round" opacity=".5"/></g>`
      + `<path d="M199 84C188 58 150 44 122 62M265 84C276 58 314 44 342 62" fill="none" stroke="${p.horn[0]}" stroke-width="3.4" stroke-linecap="round" opacity=".8"/>` : "")
    + part("cmp-ear-l", earL, at.earL) + part("cmp-ear-r", earR, at.earR)
    + `<path d="M150 164C150 108 192 80 236 80C280 80 322 108 322 164C322 212 286 244 236 244C186 244 150 212 150 164Z" fill="${u("skin")}"/>`
    + `<path d="${puff(236, 98, 50, 26, 7, 0.45, 0.62)}" fill="${u("wool")}"/>`
    + (detail ? `<g fill="none" stroke="${p.curl}" stroke-width="3.4" stroke-linecap="round">${curl(206, 100, -10, 0.75)}${curl(240, 92, 15, 0.7)}</g>` : "")
    + `<ellipse cx="236" cy="208" rx="44" ry="31" fill="${u("muzzle")}"/>`
    + `<ellipse cx="179" cy="201" rx="21" ry="13.5" fill="${u("blush")}"/><ellipse cx="293" cy="201" rx="21" ry="13.5" fill="${u("blush")}"/>`
    + (special
      ? `<g class="cmp-face-a">${eyesOf(face.eyes)}${mouth}</g><g class="cmp-face-b" opacity="0">${eyesOf("happy")}`
        + `<path d="M224 207q12 5 24 0q-2 17-12 17q-10 0-12-17z" fill="#8a3038"/><path d="M229 218q7-4 14 0q-3 6-7 6q-4 0-7-6z" fill="#f08a8a"/></g>`
      : eyesOf(face.eyes) + mouth)
    + `<path d="M225 189Q236 184 247 189Q244 200 236 201Q228 200 225 189Z" fill="#d97f72"/><ellipse cx="232" cy="190.5" rx="4" ry="1.8" fill="#fff" opacity=".55"/>`
    + (special ? `<g class="cmp-dizzy">${spark(192, 66, 1.5, "#fff3c0")}${spark(246, 44, 1.2, "#f2c14e")}${spark(284, 70, 1.5, "#fff3c0")}</g>` : "");

  const body = part("cmp-body", part("cmp-torso", torso) + part("cmp-head", head, at.head), at.body);
  return defs + (shadow ? groundShadow(id, 186, 128) : "") + (special ? `<g class="cmp-dust" fill="#e9dcc6"><circle cx="104" cy="346" r="13"/><circle cx="84" cy="338" r="9"/><circle cx="120" cy="334" r="7"/></g>` : "")
    + body + (pose === "react" ? bits("cmp-impact", 372, 190, 48, 5, ["#fff6d6", "#f2c14e", "#fff6d6"], -80, 80, 1.15) + petals("cmp-petals", 366, 186, 58, 7) : "")
    + (special ? petals("cmp-petals2", 180, 236, 92, 8) : "") + (pose === "cheer" ? confetti(236, 150) : "");
}

const portraits = new Map<string, string>();

/** The round portrait as a data URL: the head and horns on the colour's
 *  ground, clipped to a disc. `small` drops the fine detail. */
export function lambPortraitUrl(colour: LambColourId, small: boolean): string {
  const key = `${colour}/${small ? "s" : "l"}`;
  let url = portraits.get(key);
  if (!url) {
    url = dataUrl(lambPortraitSvg(colour, small));
    portraits.set(key, url);
  }
  return url;
}

export function lambPortraitSvg(colour: LambColourId, small: boolean): string {
  return portraitSvg(lambMarkup(colour, "p", { detail: !small, shadow: false }), 236, 154, 158, colourOf(colour).disc);
}
