// The Little Tractor, drawn in its 400-unit box from the companion design's
// art, flattened for the app: gradients only, no SVG filters. The drawing is
// one string builder: the figure inlines it (its poses animate its parts),
// and the portrait is the same drawing as an image, one cached data URL per
// colour, so a column of portraits is a column of <img>s. The colour is a
// palette swap (`palette.ts`).
import { createElement } from "react";
import type { ReactNode } from "react";
import { TRACTOR_COLOURS } from "./palette";
import type { TractorColour, TractorColourId } from "./palette";
import { riderMarkup } from "./TractorRider";
import { TEAM, confetti, puff } from "./rig";
import type { CharPose, Team } from "./rig";

export type Eyes = "open" | "sleep";

/** The blue-and-white scrollwork: one curl, placed four times. */
const CURL = "M0 0c7-11 25-8 24 5c-1 11-17 12-18 2c0-6 7-8 10-4";
const CURLS: readonly (readonly [number, number, number, number])[] = [
  [104, 226, 0, 0.7], [138, 240, 160, 0.6], [214, 200, 20, 0.6], [300, 262, 190, 0.55],
];

const colourOf = (id: TractorColourId): TractorColour => TRACTOR_COLOURS[id] ?? TRACTOR_COLOURS.red;

/** One headlight eye, centred on (cx, cy). `cmp-eye` is what a blink scales. */
function eye(cx: number, cy: number, eyes: Eyes): string {
  if (eyes === "sleep") {
    return `<path d="M${cx - 10} ${cy + 1}q10 8 20 0" fill="none" stroke="#2b1713" stroke-width="4.4" stroke-linecap="round"/>`;
  }
  return `<g class="cmp-eye"><ellipse cx="${cx}" cy="${cy}" rx="10.5" ry="13.5" fill="#2b1713"/>`
    + `<circle cx="${cx - 3.5}" cy="${cy - 5}" r="4.2" fill="#fff"/><circle cx="${cx + 4}" cy="${cy + 4}" r="1.8" fill="#fff" opacity=".85"/></g>`;
}

function wheel(cx: number, cy: number, r: number, id: string, detail: boolean): string {
  let treads = "";
  if (detail) {
    for (let i = 0; i < 10; i++) {
      const a = (i * Math.PI) / 5;
      treads += `<path d="M${(cx + (r - 3) * Math.cos(a)).toFixed(1)} ${(cy + (r - 3) * Math.sin(a)).toFixed(1)}`
        + `L${(cx + (r - 13) * Math.cos(a + 0.22)).toFixed(1)} ${(cy + (r - 13) * Math.sin(a + 0.22)).toFixed(1)}"`
        + ` stroke="#12090c" stroke-width="5" stroke-linecap="round" opacity=".5"/>`;
    }
  }
  return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#tyre-${id})"/>${treads}`
    + `<circle cx="${cx}" cy="${cy}" r="${r * 0.5}" fill="url(#gold-${id})"/><circle cx="${cx}" cy="${cy}" r="${(r * 0.17).toFixed(2)}" fill="#8a5516"/>`;
}

/** The Tractor's shapes in its 400 box, as SVG markup. `id` keeps its
 *  gradient ids apart from another drawing's on the same page; `detail` adds
 *  the treads and scrollwork, which are noise under 40 px; `puffs` draws the
 *  exhaust smoke; `rider` seats the farm kid at the window (`TractorRider.tsx`);
 *  `team` paints the waist band at the table. Its signature reaction is the
 *  wheelie: it rears up on its big wheel in three clouds of exhaust and
 *  slams back down in dust; drawn still, it holds the wheelie. */
export function tractorMarkup(colour: TractorColourId, id: string, { eyes = "open", detail = true, puffs = true, shadow = true, rider = false, pose = "idle", still = false, team }: {
  eyes?: Eyes; detail?: boolean; puffs?: boolean; shadow?: boolean; rider?: boolean; pose?: CharPose; still?: boolean; team?: Team;
} = {}): string {
  const p = colourOf(colour);
  const r = rider ? riderMarkup(p, id, { pose, still, team }) : null;
  const lg = (name: string, stops: readonly string[]) =>
    `<linearGradient id="${name}-${id}" x1="0" y1="0" x2="1" y2="1">${stops.map((c, i) =>
      `<stop offset="${stops.length === 3 ? [0, 0.6, 1][i] : i}" stop-color="${c}"/>`).join("")}</linearGradient>`;
  const defs = `<defs>${lg("body", p.body)}${lg("roof", ["#fffdf7", "#fdf1dc", "#f1dcc0"])}${lg("glass", ["#e9fbff", "#8fc6d6"])}`
    + `${lg("tyre", ["#4a4048", "#231c22"])}${lg("gold", ["#ffe9a8", "#eeb94f", "#b9781f"])}`
    + `<radialGradient id="shadow-${id}" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#000" stop-opacity=".42"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>${r ? r.defs : ""}</defs>`;
  const motif = p.motif && detail
    ? `<g fill="none" stroke="#2a4fb0" stroke-width="3" stroke-linecap="round" opacity=".9">${CURLS.map(([x, y, r, s]) =>
      `<path transform="translate(${x} ${y}) rotate(${r}) scale(${s})" d="${CURL}"/>`).join("")}<path d="M96 250q12-8 24 0M236 268q10-7 20 0"/></g>`
    : "";
  const react = pose === "react";
  const cloud = (cls: string, cx: number, cy: number, r: number, fill: string) =>
    `<path class="${cls}" d="${puff(cx, cy, r, r * 0.82, 6, 0.4, 0.62)}" fill="${fill}"/>`;
  const smoke = react ? cloud("cmp-smoke cmp-smoke1", 178, 34, 32, "#fff8ea") + cloud("cmp-smoke cmp-smoke2", 150, 24, 36, "#fff8ea")
    + cloud("cmp-smoke cmp-smoke3", 198, 50, 26, "#fff8ea") : "";
  const dust = react && !still ? cloud("cmp-dust cmp-dust-l", 84, 336, 24, "#efe3cd") + cloud("cmp-dust cmp-dust-r", 350, 338, 22, "#efe3cd") : "";
  const reared = still && react;
  return defs + (shadow ? `<ellipse class="cmp-shadow" cx="200" cy="356" rx="140" ry="17" fill="url(#shadow-${id})"/>` : "")
    + (reared ? `<g transform="translate(14 0) rotate(-24 140 354)">` : "") + `<g class="cmp-body">`
    + `<rect x="286" y="96" width="20" height="96" rx="8" fill="#3a3038"/>`
    + (puffs ? `<g fill="#fff8ea"><circle class="cmp-puff cmp-puff1" cx="300" cy="72" r="13"/><circle class="cmp-puff cmp-puff2" cx="318" cy="52" r="10"/><circle class="cmp-puff cmp-puff3" cx="328" cy="34" r="6.5"/></g>` : "")
    + `<path d="M92 118Q92 96 116 96H206Q228 96 228 118V258H92Z" fill="url(#body-${id})"/>`
    + `<path d="M80 98Q80 80 100 80H222Q240 80 240 98V104H80Z" fill="${p.roof ?? `url(#roof-${id})`}"/>`
    + `<path d="M196 178H318Q352 178 352 212V268Q352 282 338 282H196Z" fill="${p.hood}"/>`
    + `<rect x="112" y="118" width="96" height="62" rx="12" fill="url(#glass-${id})"/>`
    + (r ? r.inside : "")
    + `<path d="M124 170L158 124h18L142 170Z" fill="#fff" opacity="${r ? ".3" : ".55"}"/>`
    + `<path d="M92 196H228" ${team ? `class="cmp-team-line" stroke="${TEAM[team].base}" stroke-width="10"` : `stroke="${p.stripe ?? `url(#gold-${id})`}" stroke-width="5"`}/>${motif}`
    + `<rect x="332" y="226" width="22" height="38" rx="7" fill="#fff5d6"/>`
    + `<path d="M336 238h14M336 246h14M336 254h14" stroke="#b9781f" stroke-width="2.4"/>`
    + eye(262, 220, eyes) + eye(306, 220, eyes)
    + `<path d="M274 248q10 8 20 0" fill="none" stroke="#2b1713" stroke-opacity=".7" stroke-width="3.4" stroke-linecap="round"/>`
    + `<ellipse cx="244" cy="244" rx="11" ry="7" fill="#ffb0a0" opacity=".45"/><ellipse cx="324" cy="244" rx="9" ry="6" fill="#ffb0a0" opacity=".35"/>`
    + wheel(140, 282, 72, id, detail) + wheel(306, 308, 46, id, detail) + (r ? r.outside : "")
    + `</g>` + (reared ? `</g>` : "") + smoke + dust + (pose === "cheer" ? confetti(200, 170) : "");
}

/** An element of the drawing: its tag, its attributes, its children. */
export type ArtNode = [tag: string, attrs: Record<string, string>, children: ArtNode[]];

const TAG = /<(\/?)([a-zA-Z]+)((?:\s+[a-zA-Z][a-zA-Z0-9:-]*="[^"]*")*)\s*(\/?)>|([^<]+)/g;
const ATTR = /([a-zA-Z][a-zA-Z0-9:-]*)="([^"]*)"/g;

/** The builder's markup as elements. It reads only the markup this file
 *  writes (no entities, no comments), so the figure is drawn by React as
 *  elements, never as raw HTML. */
export function parseArt(markup: string): ArtNode[] {
  const root: ArtNode = ["", {}, []];
  const stack: ArtNode[] = [root];
  for (const m of markup.matchAll(TAG)) {
    const top = stack[stack.length - 1];
    if (m[5] !== undefined) {
      top[2].push(["#text", { text: m[5] }, []]);
      continue;
    }
    if (m[1]) {
      stack.pop();
      continue;
    }
    const attrs: Record<string, string> = {};
    for (const a of m[3].matchAll(ATTR)) attrs[a[1]] = a[2];
    const node: ArtNode = [m[2], attrs, []];
    top[2].push(node);
    if (!m[4]) stack.push(node);
  }
  return root[2];
}

const REACT_NAMES: Record<string, string> = { class: "className", "clip-path": "clipPath" };
const camel = (name: string) => REACT_NAMES[name] ?? name.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase());

/** The elements as React nodes. */
export function renderArt(nodes: ArtNode[]): ReactNode[] {
  return nodes.map(([tag, attrs, children], i) => {
    if (tag === "#text") return attrs.text;
    const props: Record<string, string | number> = { key: i };
    for (const [k, v] of Object.entries(attrs)) props[camel(k)] = v;
    return createElement(tag, props, ...renderArt(children));
  });
}

const portraits = new Map<string, string>();

/** The round portrait as a data URL: the whole Tractor, a little smaller, on
 *  its colour's ground, clipped to a disc. `small` drops the fine detail. */
export function tractorPortraitUrl(colour: TractorColourId, small: boolean): string {
  const key = `${colour}/${small ? "s" : "l"}`;
  let url = portraits.get(key);
  if (!url) {
    const p = colourOf(colour);
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="4 9 392 392">`
      + `<defs><linearGradient id="disc" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${p.disc[0]}"/><stop offset="1" stop-color="${p.disc[1]}"/></linearGradient>`
      + `<clipPath id="clip"><circle cx="200" cy="205" r="196"/></clipPath></defs>`
      + `<g clip-path="url(#clip)"><rect x="4" y="9" width="392" height="392" fill="url(#disc)"/>`
      + `<g transform="translate(30 44) scale(.86)">${tractorMarkup(colour, "p", { detail: !small, puffs: false, shadow: false, rider: true })}</g></g></svg>`;
    url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
    portraits.set(key, url);
  }
  return url;
}
