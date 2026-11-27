// The Little Dragon, drawn in its 400-unit box on the store characters'
// rig: gradients only, no SVG filters. A free-standing baby dragon with
// small wings, so the head reads at table size. One string builder draws
// every pose; the portrait is the same drawing as an image. The colour is a
// palette swap (`storePalette.ts`). Its signature reaction is loop and fire:
// the wings beat, it lifts off and turns one loop, hovers, breathes one
// small puff of flame with a smoke ring, and lands.
import { DRAGON_COLOURS } from "./storePalette";
import type { DragonColour, DragonColourId } from "./storePalette";
import { ball, confetti, dataUrl, eye, glow, groundShadow, kerchief, part, portraitSvg, puff, ramp, sharedDefs, spark, teamPad } from "./rig";
import type { CharOpts, CharPose, EyeMode } from "./rig";

/** A colour by id, or a palette given whole (the CSS-variable master passes one). */
const colourOf = (c: DragonColourId | DragonColour): DragonColour => (typeof c === "string" ? DRAGON_COLOURS[c] ?? DRAGON_COLOURS.red : c);

/** Where the sleeping z rises from. */
export const DRAGON_Z: readonly [number, number] = [322, 80];

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
  hop: { body: "translate(0 -12)" },
  cheer: { body: "translate(0 -34)", head: "rotate(-6 190 226)", wingL: "rotate(30 134 250)", wingR: "rotate(-30 246 250)", tail: "rotate(-16 130 320)" },
  react: { body: "translate(0 -74)", head: "translate(4 4) rotate(5 190 226)", wingL: "rotate(36 134 250)", wingR: "rotate(-36 246 250)", tail: "rotate(18 130 320)" },
  sleep: { head: "translate(0 14) rotate(6 190 226)", wingL: "rotate(-22 134 250)", wingR: "rotate(22 246 250)" },
};
/** The Dragon's shapes in its 400 box, as SVG markup. `id` keeps its
 *  gradient ids apart from another drawing's on the same page. */
export function dragonMarkup(colour: DragonColourId | DragonColour, id: string, { pose = "idle", detail = true, shadow = true, still = false, team }: CharOpts = {}): string {
  const p = colourOf(colour);
  const face = FACE[pose];
  const at = (still || pose === "sleep" ? STILL[pose] : undefined) ?? {};
  const u = (name: string) => `url(#${name}-${id})`;

  const defs = `<defs>${sharedDefs(id)}${ball("body", id, p.body, [0.36, 0.26, 0.82])}${ball("horn", id, p.horn, [0.34, 0.28, 0.85])}`
    + ramp("limb", id, [p.body[0], p.body[1], p.body[2]], [0, 0, 1, 1])
    + glow("under", id, "#2a0a14", 0.35) + glow("blush", id, p.blush, 0.8, 0.25)
    + `</defs>`;

  const wing = (s: number) => {
    const x = (v: number) => 190 + s * v;
    return `<path d="M${x(-56)} 246C${x(-92)} 210 ${x(-132)} 206 ${x(-150)} 226C${x(-132)} 228 ${x(-124)} 240 ${x(-122)} 254C${x(-108)} 248 ${x(-98)} 254 ${x(-92)} 268C${x(-80)} 262 ${x(-66)} 264 ${x(-54)} 274Z" fill="${u("limb")}"/>`
      + `<path d="M${x(-64)} 250C${x(-92)} 224 ${x(-120)} 220 ${x(-136)} 228C${x(-122)} 234 ${x(-116)} 244 ${x(-112)} 258C${x(-100)} 254 ${x(-90)} 258 ${x(-84)} 266C${x(-76)} 262 ${x(-70)} 262 ${x(-62)} 266Z" fill="${p.belly}" opacity=".55"/>`;
  };
  const torso = part("cmp-tail", `<path d="M140 324C94 326 62 294 70 252" fill="none" stroke="${u("limb")}" stroke-width="28" stroke-linecap="round"/>`
      + `<path d="M68 260C42 242 44 206 64 186C66 208 80 216 92 234C96 248 84 262 68 260Z" fill="${u("horn")}"/>`, at.tail)
    + part("cmp-arm-l", wing(1), at.wingL) + part("cmp-arm-r", wing(-1), at.wingR)
    + `<ellipse cx="158" cy="342" rx="27" ry="13" fill="${p.body[2]}"/><ellipse cx="222" cy="342" rx="27" ry="13" fill="${p.body[2]}"/>`
    + `<ellipse cx="190" cy="278" rx="64" ry="62" fill="${u("body")}"/>`
    + `<ellipse cx="190" cy="288" rx="38" ry="42" fill="${p.belly}"/>`
    + (detail ? `<path d="M164 276q26 9 52 0M160 294q30 10 60 0M166 312q24 8 48 0" fill="none" stroke="${p.body[2]}" stroke-width="2.6" stroke-linecap="round" opacity=".35"/>` : "")
    + `<ellipse cx="190" cy="240" rx="68" ry="20" fill="${u("under")}"/>`
    + `<ellipse cx="140" cy="290" rx="15" ry="19" fill="${u("limb")}" transform="rotate(14 140 290)"/><ellipse cx="240" cy="290" rx="15" ry="19" fill="${u("limb")}" transform="rotate(-14 240 290)"/>`;

  const horn = (s: number) => {
    const x = (v: number) => 190 + s * v;
    return `<path d="M${x(-40)} 92C${x(-56)} 66 ${x(-52)} 40 ${x(-36)} 30C${x(-36)} 50 ${x(-26)} 62 ${x(-16)} 80Z" fill="${u("horn")}"/>`
      + `<path d="M${x(-50)} 62C${x(-66)} 58 ${x(-74)} 44 ${x(-70)} 32C${x(-60)} 42 ${x(-52)} 46 ${x(-42)} 52Z" fill="${u("horn")}"/>`;
  };
  const fin = (s: number) => {
    const x = (v: number) => 190 + s * v;
    return `<path d="M${x(-84)} 130C${x(-118)} 112 ${x(-132)} 132 ${x(-128)} 156C${x(-112)} 160 ${x(-96)} 160 ${x(-84)} 162Z" fill="${u("limb")}"/>`
      + `<path d="M${x(-90)} 138C${x(-108)} 130 ${x(-118)} 140 ${x(-116)} 152C${x(-106)} 154 ${x(-98)} 154 ${x(-90)} 154Z" fill="${p.blush}" opacity=".8"/>`;
  };
  const mouth = face.mouth === "open"
    ? `<path d="M177 200q13 6 26 0q-2 17-13 17q-11 0-13-17z" fill="#7a1a26"/><path d="M183 211q7-4 14 0q-3 6-7 6q-4 0-7-6z" fill="#f08a8a"/>`
    : face.mouth === "rest" ? `<path d="M183 203q7 5 14 0" fill="none" stroke="#8a5240" stroke-width="3" stroke-linecap="round"/>`
      : `<path d="M172 200q18 12 36 0" fill="none" stroke="#8a5240" stroke-width="3.2" stroke-linecap="round"/>`;
  const big = { k: 1.12, detail };
  const head = `<path d="${puff(190, 78, 40, 15, 6, 0.3, 0.62)}" fill="${p.mane}"/>`
    + horn(1) + horn(-1)
    + part("cmp-ear-l", fin(1)) + part("cmp-ear-r", fin(-1))
    + `<path d="M96 148C96 100 138 72 190 72C242 72 284 100 284 148C284 194 246 226 190 226C134 226 96 194 96 148Z" fill="${u("body")}"/>`
    + `<path d="${puff(190, 84, 30, 11, 5, 0.2, 0.62)}" fill="${p.mane}"/>`
    + `<ellipse cx="150" cy="148" rx="28" ry="30" fill="${p.belly}"/><ellipse cx="230" cy="148" rx="28" ry="30" fill="${p.belly}"/>`
    + `<ellipse cx="190" cy="192" rx="50" ry="28" fill="${p.belly}"/>`
    + `<ellipse cx="118" cy="188" rx="18" ry="12" fill="${u("blush")}"/><ellipse cx="262" cy="188" rx="18" ry="12" fill="${u("blush")}"/>`
    + eye(150, 150, face.eyes, id, big) + eye(230, 150, face.eyes, id, big)
    + `<circle cx="180" cy="182" r="3.4" fill="${p.body[3]}"/><circle cx="200" cy="182" r="3.4" fill="${p.body[3]}"/>`
    + mouth
    + `<path d="M142 194c-26 0-40-16-34-34M238 194c26 0 40-16 34-34" fill="none" stroke="${p.whisker}" stroke-width="5" stroke-linecap="round"/>`;

  const flame = pose === "react" ? `<g class="cmp-flame"><path d="M250 214C272 176 318 172 342 196C366 220 350 256 318 258C288 260 262 244 250 214Z" fill="#ff9d4d"/>`
    + `<path d="M262 214C278 190 310 188 326 204C342 220 332 244 312 246C290 248 270 234 262 214Z" fill="#ffd76a"/><ellipse cx="304" cy="220" rx="13" ry="10" fill="#fff6d6"/>`
    + `<circle cx="356" cy="176" r="12" fill="none" stroke="#fff6e6" stroke-width="5" opacity=".8"/></g>` : "";
  const puffs = pose === "cheer" ? `<g class="cmp-puffs">${spark(232, 222, 1.5, "#ffd76a")}${spark(256, 200, 1, "#fff6e6")}${spark(250, 240, 0.8, "#ff9d4d")}</g>` : "";

  const body = part("cmp-body", part("cmp-spin", part("cmp-torso", torso) + (team ? kerchief(team, 124, 256, 222, 9, 144) : "") + part("cmp-head", head, at.head)) + flame, at.body);
  return defs + (team ? teamPad(team, 190, 120) : "") + (shadow ? groundShadow(id, 180, 126) : "") + body + puffs + (pose === "cheer" ? confetti(190, 150) : "");
}

const portraits = new Map<string, string>();

/** The round portrait as a data URL: the head and horns on the colour's
 *  ground, clipped to a disc. `small` drops the fine detail. */
export function dragonPortraitUrl(colour: DragonColourId, small: boolean): string {
  const key = `${colour}/${small ? "s" : "l"}`;
  let url = portraits.get(key);
  if (!url) {
    url = dataUrl(dragonPortraitSvg(colour, small));
    portraits.set(key, url);
  }
  return url;
}

export function dragonPortraitSvg(colour: DragonColourId, small: boolean): string {
  return portraitSvg(dragonMarkup(colour, "p", { detail: !small, shadow: false }), 190, 136, 134, colourOf(colour).disc);
}
