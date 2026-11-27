// The drawn characters' shared rig: one light (key from the upper left, core
// shadow at the lower right, a warm rim on the right edge), one eye, one
// ground shadow. Every form is a gradient fill, so a figure costs no SVG
// filter. A character file composes these into its own markup builder, the
// way `Tractor.tsx` does.

/** A form's four tones: highlight, base, low, core shadow. */
export type Tones = readonly [string, string, string, string];
export type Pair = readonly [string, string];

/** What a figure is doing. `react` is the character's signature reaction. */
export type CharPose = "idle" | "hop" | "cheer" | "sleep" | "react";
export type EyeMode = "open" | "happy" | "sleep" | "fierce";

/** The levels a team climbs, 2 to A; a level's index here is what grows its companions. */
export const LEVELS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"] as const;
/** The levels a table companion takes to grow from its base to its seat's
 *  cap: it reaches the cap at 6, so each of the first levels gained is a
 *  step that shows (2 px on a phone, 3 on a tablet). */
export const GROW_LEVELS = 4;

/** A table companion's size in px: its base size, grown an equal step a
 *  level from 2 until it reaches what the seat area allows (`layoutMax`). */
export const companionSize = (base: number, levelIndex: number, layoutMax: number): number => {
  if (!Number.isFinite(layoutMax)) return base;
  const step = Math.min(Math.max(0, levelIndex), GROW_LEVELS) / GROW_LEVELS;
  return Math.min(Math.round(base + (layoutMax - base) * step), layoutMax);
};

/** The side a figure plays for at the table. */
export type Team = "us" | "them";

/** Each team's colour and its shade. The pose CSS repaints `cmp-team` and
 *  `cmp-team-lo` shapes from `--team` and `--team-lo`, so the app can change
 *  a team's colour without redrawing; these are what a still shows. */
export const TEAM: Record<Team, { base: string; lo: string }> = {
  us: { base: "#5b9dff", lo: "#2f6fd6" },
  them: { base: "#ff9d4d", lo: "#d96a14" },
};

export interface CharOpts {
  pose?: CharPose;
  /** At the table: the figure wears its team's colour at the neck and stands on its team's pad. */
  team?: Team;
  /** Fine marks (curls, ridges, gold lines), which are noise under 64 px. */
  detail?: boolean;
  shadow?: boolean;
  /** Draw the pose at its peak with no animation: the Reduce Motion frame and the exported stills. */
  still?: boolean;
}

export const n = (v: number): string => String(Math.round(v * 10) / 10);

/** A lit round form: light at the upper left, core shadow at the far edge. */
export function ball(name: string, id: string, t: Tones, c: readonly [number, number, number] = [0.36, 0.3, 0.8]): string {
  return `<radialGradient id="${name}-${id}" cx="${c[0]}" cy="${c[1]}" r="${c[2]}">`
    + `<stop offset="0" stop-color="${t[0]}"/><stop offset=".42" stop-color="${t[1]}"/>`
    + `<stop offset=".8" stop-color="${t[2]}"/><stop offset="1" stop-color="${t[3]}"/></radialGradient>`;
}

/** A lit flat or long form: a straight ramp from (x1, y1) to (x2, y2) of its box. */
export function ramp(name: string, id: string, stops: readonly string[], d: readonly [number, number, number, number] = [0, 0, 1, 1]): string {
  return `<linearGradient id="${name}-${id}" x1="${d[0]}" y1="${d[1]}" x2="${d[2]}" y2="${d[3]}">`
    + stops.map((c, i) => `<stop offset="${n(i / (stops.length - 1))}" stop-color="${c}"/>`).join("") + `</linearGradient>`;
}

/** A soft spot that fades to nothing at its edge: blush, muzzle, contact shade. */
export function glow(name: string, id: string, colour: string, opacity = 1, hold = 0): string {
  return `<radialGradient id="${name}-${id}" cx=".5" cy=".5" r=".5"><stop offset="${hold}" stop-color="${colour}" stop-opacity="${opacity}"/>`
    + `<stop offset="1" stop-color="${colour}" stop-opacity="0"/></radialGradient>`;
}

/** The warm rim: a stroke that is clear on the lit side and gold on the right edge. */
export function rim(name: string, id: string, colour: string, opacity = 0.9): string {
  return `<linearGradient id="${name}-${id}" x1="0" y1=".2" x2="1" y2=".6"><stop offset=".55" stop-color="${colour}" stop-opacity="0"/>`
    + `<stop offset="1" stop-color="${colour}" stop-opacity="${opacity}"/></linearGradient>`;
}

/** The defs every character shares: the eye, the ground shadow. */
export function sharedDefs(id: string): string {
  return `<radialGradient id="eye-${id}" cx=".4" cy=".3" r=".8"><stop offset="0" stop-color="#5a3528"/><stop offset=".6" stop-color="#2b1713"/><stop offset="1" stop-color="#170b09"/></radialGradient>`
    + glow("shadow", id, "#000", 0.42);
}

export function groundShadow(id: string, cx: number, rx: number): string {
  return `<ellipse class="cmp-shadow" cx="${cx}" cy="356" rx="${rx}" ry="17" fill="url(#shadow-${id})"/>`;
}

/** The team's pad under a figure. The two teams differ in shape as well as
 *  colour: a disc for Us, a diamond for Them. */
export function teamPad(team: Team, cx: number, rx: number): string {
  const t = TEAM[team], ry = 36;
  const shape = team === "us"
    ? `<ellipse class="cmp-team" cx="${cx}" cy="350" rx="${rx + 6}" ry="${ry}" fill="${t.base}" stroke="#0e2a5c" stroke-opacity=".55" stroke-width="5"/>`
      + `<ellipse cx="${cx}" cy="350" rx="${n(rx - 6)}" ry="${ry - 9}" fill="none" stroke="#fff" stroke-width="5" opacity=".6"/>`
    : `<path class="cmp-team" d="M${n(cx - rx - 26)} 350L${cx} ${350 - ry - 12}L${n(cx + rx + 26)} 350L${cx} ${350 + ry + 12}Z" fill="${t.base}" stroke="#4a2204" stroke-opacity=".7" stroke-width="7" stroke-linejoin="round"/>`
      + `<path d="M${n(cx - rx + 2)} 350L${cx} ${350 - ry + 2}L${n(cx + rx - 2)} 350L${cx} ${350 + ry - 2}Z" fill="none" stroke="#4a2204" stroke-width="5" opacity=".45" stroke-linejoin="round"/>`;
  return `<g class="cmp-pad">${shape}</g>`;
}

/** The paint of a shape that turns team colour at the table: its own fill off the table. */
export const teamPaint = (team: Team | undefined, own: string, lo = false): string =>
  team ? `class="${lo ? "cmp-team-lo" : "cmp-team"}" fill="${lo ? TEAM[team].lo : TEAM[team].base}"` : `fill="${own}"`;

/** A neckerchief for a character with nothing at its neck: the band across
 *  the chest from (x1, y) to (x2, y), sagging `sag`, and its knot. Drawn at the table only. */
export function kerchief(team: Team, x1: number, x2: number, y: number, sag: number, knotX: number): string {
  const m = (x1 + x2) / 2, ky = y + sag * 0.72;
  return `<path ${teamPaint(team, "")} d="M${x1} ${y}Q${m} ${y + 2 * sag} ${x2} ${y}L${x2 + 5} ${y + 22}Q${m} ${y + 2 * sag + 30} ${x1 - 5} ${y + 22}Z"/>`
    + `<path d="M${x1 + 6} ${y + 6}Q${m} ${y + 2 * sag + 4} ${x2 - 6} ${y + 6}L${x2} ${y}Q${m} ${y + 2 * sag} ${x1} ${y}Z" fill="#000" opacity=".22"/>`
    + `<path ${teamPaint(team, "", true)} d="M${knotX - 4} ${ky + 8}l-16 40l30-12z"/><circle ${teamPaint(team, "")} cx="${knotX}" cy="${ky + 12}" r="11"/>`;
}

/** A cloud outline: `count` outward arcs round an ellipse. */
export function puff(cx: number, cy: number, rx: number, ry: number, count: number, rot = 0, bulge = 0.6): string {
  const pts: [number, number][] = [];
  for (let i = 0; i < count; i++) {
    const a = rot + (i * 2 * Math.PI) / count;
    pts.push([cx + rx * Math.cos(a), cy + ry * Math.sin(a)]);
  }
  let d = `M${n(pts[0][0])} ${n(pts[0][1])}`;
  for (let i = 1; i <= count; i++) {
    const p = pts[i % count], q = pts[i - 1];
    const r = n(Math.hypot(p[0] - q[0], p[1] - q[1]) * bulge);
    d += `A${r} ${r} 0 0 1 ${n(p[0])} ${n(p[1])}`;
  }
  return d + "Z";
}

/** One scroll curl, the wool and cloud mark. */
export const curl = (x: number, y: number, r = 0, s = 1): string =>
  `<path transform="translate(${x} ${y}) rotate(${r}) scale(${s})" d="M0 0c7-11 25-8 24 5c-1 11-17 12-18 2c0-6 7-8 10-4"/>`;

/** One eye centred on (cx, cy), `k` times the standard size. `cmp-eye` is
 *  what a blink scales. `ink` draws the closed and smiling lids, so an eye
 *  on a dark patch passes a light ink. A light `fill` takes a slit `pupil`. */
export function eye(cx: number, cy: number, mode: EyeMode, id: string, { k = 1, detail = true, ink = "#2b1713", fill = "", pupil = "" }: {
  k?: number; detail?: boolean; ink?: string; fill?: string; pupil?: string;
} = {}): string {
  if (mode === "sleep") {
    return `<path d="M${n(cx - 13 * k)} ${n(cy + 2)}q${n(13 * k)} ${n(9 * k)} ${n(26 * k)} 0" fill="none" stroke="${ink}" stroke-width="${n(4.8 * k)}" stroke-linecap="round"/>`;
  }
  if (mode === "happy") {
    return `<path d="M${n(cx - 13 * k)} ${n(cy + 6 * k)}q${n(13 * k)} ${n(-18 * k)} ${n(26 * k)} 0" fill="none" stroke="${ink}" stroke-width="${n(5.4 * k)}" stroke-linecap="round"/>`;
  }
  const ry = mode === "fierce" ? 14.5 : 17.5;
  return `<g class="cmp-eye"><ellipse cx="${cx}" cy="${cy}" rx="${n(13.5 * k)}" ry="${n(ry * k)}" fill="${fill || `url(#eye-${id})`}"/>`
    + (pupil ? `<ellipse cx="${cx}" cy="${cy}" rx="${n(5.5 * k)}" ry="${n(12 * k)}" fill="${pupil}"/>` : "")
    + (detail && !pupil ? `<path d="M${n(cx - 9 * k)} ${n(cy + 9 * k)}q${n(9 * k)} ${n(7 * k)} ${n(18 * k)} 0" fill="none" stroke="#a8683f" stroke-width="${n(2.4 * k)}" stroke-linecap="round" opacity=".7"/>` : "")
    + `<circle cx="${n(cx - 4.5 * k)}" cy="${n(cy - 6.5 * k)}" r="${n(5.4 * k)}" fill="#fff"/>`
    + `<circle cx="${n(cx + 5 * k)}" cy="${n(cy + 5.5 * k)}" r="${n(2.4 * k)}" fill="#fff" opacity=".85"/></g>`;
}

/** A group the pose CSS moves (`cls`), inside the still pose's own transform
 *  when there is one. The CSS transform replaces nothing the drawing set. */
export function part(cls: string, inner: string, baked = ""): string {
  const g = `<g class="${cls}">${inner}</g>`;
  return baked ? `<g transform="${baked}">${g}</g>` : g;
}

/** The cheer's burst: two rings of paper bits and sparks over the head at
 *  (cx, cy), one for each beat of the jump. They stand outside `cmp-body`,
 *  so the figure jumps through them. */
export function confetti(cx: number, cy: number): string {
  const ink = ["#f2c14e", "#e2474a", "#3fae90", "#fff6e6", "#5b9dff", "#ff9d4d"];
  const ring = (r: number, count: number, from: number, to: number, k: number) => {
    let out = "";
    for (let i = 0; i < count; i++) {
      const a = ((from + ((to - from) * i) / (count - 1)) * Math.PI) / 180;
      const x = n(cx + r * Math.cos(a)), y = n(cy + r * 0.82 * Math.sin(a)), c = ink[(i + k) % ink.length];
      out += i % 3 === 1 ? spark(+x, +y, 1.7, c)
        : `<rect x="${n(+x - 11)}" y="${n(+y - 6)}" width="22" height="12" rx="3" fill="${c}" transform="rotate(${(i * 47 + k * 20) % 180} ${x} ${y})"/>`;
    }
    return out;
  };
  return `<g class="cmp-confetti">${ring(150, 7, -168, -12, 0)}</g><g class="cmp-confetti cmp-confetti-b">${ring(186, 6, -150, -30, 3)}</g>`;
}

/** A four-point sparkle, for the gilded colours. */
export const spark = (x: number, y: number, s: number, c = "#fff7d6"): string =>
  `<path transform="translate(${x} ${y}) scale(${s})" d="M0-10Q1.5-1.5 10 0Q1.5 1.5 0 10Q-1.5 1.5-10 0Q-1.5-1.5 0-10Z" fill="${c}"/>`;

/** A small burst for a signature's payoff: `count` bits (dots and sparks)
 *  in `inks`, on an arc of radius `r` round (cx, cy) from angle `from` to
 *  `to` in degrees. The pose CSS scales and fades the group (`cls`). */
export function bits(cls: string, cx: number, cy: number, r: number, count: number, inks: readonly string[], from = -170, to = -10, size = 1): string {
  let out = "";
  for (let i = 0; i < count; i++) {
    const a = ((from + ((to - from) * i) / Math.max(1, count - 1)) * Math.PI) / 180, k = i % 2 ? 1 : 0.72;
    const x = n(cx + r * k * Math.cos(a)), y = n(cy + r * k * Math.sin(a)), c = inks[i % inks.length];
    out += i % 3 === 0 ? spark(+x, +y, 1.5 * size, c) : `<circle cx="${x}" cy="${y}" r="${n(8 * size)}" fill="${c}"/>`;
  }
  return `<g class="${cls}">${out}</g>`;
}

/** A round portrait as a data URL: the head crop on its ground, clipped to a disc. */
export function portraitSvg(markup: string, cx: number, cy: number, r: number, disc: Pair): string {
  const x = n(cx - r), y = n(cy - r), d = n(2 * r);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${x} ${y} ${d} ${d}">`
    + `<defs><linearGradient id="disc" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${disc[0]}"/><stop offset="1" stop-color="${disc[1]}"/></linearGradient>`
    + `<clipPath id="clip"><circle cx="${cx}" cy="${cy}" r="${r}"/></clipPath></defs>`
    + `<g clip-path="url(#clip)"><rect x="${x}" y="${y}" width="${d}" height="${d}" fill="url(#disc)"/>${markup}</g></svg>`;
}

export const dataUrl = (svg: string): string => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
