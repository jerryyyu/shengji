// The free companions' specials, checked from the drawings and their CSS
// with no browser: a small evaluator plays each special's keyframes over its
// markup and reports where it paints. Each special must stay inside the box
// the table keeps clear for it (`figureBox` of the figure drawn 1.5 times
// its size, at the phone's 44 px), return to the idle drawing as it ends,
// run for a length the eye can follow, move few pieces, and hold still under
// Reduce Motion.
import { readFileSync } from "node:fs";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { Companion } from "./Companion";
import { DRAWINGS } from "./kinds";
import { FREE_KINDS } from "./look";
import { figureBox } from "./seatZones";
import { parseArt } from "./Tractor";
import type { ArtNode } from "./Tractor";

type M = readonly [number, number, number, number, number, number];
const ID: M = [1, 0, 0, 1, 0, 0];
const mul = (a: M, b: M): M => [a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1], a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
  a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5]];
const shift = (x: number, y: number): M => [1, 0, 0, 1, x, y];
const turn = (deg: number): M => { const r = (deg * Math.PI) / 180; return [Math.cos(r), Math.sin(r), -Math.sin(r), Math.cos(r), 0, 0]; };
const size = (x: number, y: number): M => [x, 0, 0, y, 0, 0];
const at = (m: M, x: number, y: number): [number, number] => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];

interface Box { x: number; y: number; w: number; h: number }
interface Fn { name: string; args: { v: number; unit: string }[] }
interface Frame { offset: number; transform?: Fn[]; opacity?: number; easing?: string }
interface Anim { name: string; ms: number; delay: number; count: number; easing: string; fill: string }
interface Rule { path: string[][]; decl: [string, string][]; weight: number }

/** The style sheets as rules and keyframes. Blocks under `@media` are left
 *  out: they hold only the Reduce Motion stills. */
function sheet(css: string): { rules: Rule[]; frames: Map<string, Frame[]> } {
  const src = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules: Rule[] = [];
  const frames = new Map<string, Frame[]>();
  const decls = (body: string) => body.split(";").map((d) => d.split(/:(.*)/s).map((s) => s.trim())).filter((d) => d[0] && d[1] !== undefined) as [string, string][];
  let i = 0;
  while (i < src.length) {
    const open = src.indexOf("{", i);
    if (open < 0) break;
    const head = src.slice(i, open).trim();
    let depth = 1, j = open + 1;
    for (; j < src.length && depth > 0; j++) depth += src[j] === "{" ? 1 : src[j] === "}" ? -1 : 0;
    const body = src.slice(open + 1, j - 1);
    i = j;
    if (head.startsWith("@keyframes")) {
      const list: Frame[] = [];
      for (const m of body.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
        const d = new Map(decls(m[2]));
        for (const stop of m[1].split(",")) {
          const frame: Frame = { offset: parseFloat(stop) / 100 };
          if (d.has("transform")) frame.transform = fns(d.get("transform")!);
          if (d.has("opacity")) frame.opacity = Number(d.get("opacity"));
          if (d.has("animation-timing-function")) frame.easing = d.get("animation-timing-function");
          list.push(frame);
        }
      }
      frames.set(head.split(/\s+/)[1], list.sort((a, b) => a.offset - b.offset));
    } else if (!head.startsWith("@")) {
      for (const sel of head.split(",")) {
        const parts = sel.trim().split(/\s+/);
        // only plain class selectors are followed; any other never matches a special's parts
        if (!parts.every((p) => /^(\.[\w-]+)+$/.test(p))) continue;
        const path = parts.map((p) => p.slice(1).split("."));
        rules.push({ path, decl: decls(body), weight: path.reduce((n, c) => n + c.length, 0) });
      }
    }
  }
  return { rules, frames };
}

function fns(text: string): Fn[] {
  return [...text.matchAll(/([a-zA-Z]+)\(([^)]*)\)/g)].map((m) => {
    const args = m[2].split(/[\s,]+/).filter(Boolean).map((a) => ({ v: parseFloat(a), unit: a.replace(/^[-\d.]+/, "") }));
    if (m[1] === "translate" && args.length === 1) args.push({ v: 0, unit: "px" });
    if (m[1] === "scale" && args.length === 1) args.push({ ...args[0] });
    return { name: m[1], args };
  });
}

/** A transform list as a matrix, its lengths measured on `ref`. */
function matrix(list: Fn[], ref: Box): M {
  let m = ID;
  for (const f of list) {
    const len = (k: number, of: number) => (f.args[k].unit === "%" ? (f.args[k].v / 100) * of : f.args[k].v);
    if (f.name === "translate") m = mul(m, shift(len(0, ref.w), len(1, ref.h)));
    else if (f.name === "translateX") m = mul(m, shift(len(0, ref.w), 0));
    else if (f.name === "translateY") m = mul(m, shift(0, len(0, ref.h)));
    else if (f.name === "rotate") m = mul(m, turn(f.args[0].unit === "turn" ? f.args[0].v * 360 : f.args[0].v));
    else if (f.name === "scale") m = mul(m, size(f.args[0].v, f.args[1].v));
    else if (f.name === "scaleY") m = mul(m, size(1, f.args[0].v));
    else throw new Error(`transform ${f.name}`);
  }
  return m;
}

/** A timing function's output at `x`. */
function ease(name: string, x: number): number {
  const curve: Record<string, number[]> = { linear: [0, 0, 1, 1], ease: [0.25, 0.1, 0.25, 1], "ease-in": [0.42, 0, 1, 1], "ease-out": [0, 0, 0.58, 1], "ease-in-out": [0.42, 0, 0.58, 1] };
  const p = curve[name] ?? /cubic-bezier\(([^)]*)\)/.exec(name)?.[1].split(",").map(Number);
  if (!p) throw new Error(`easing ${name}`);
  const b = (t: number, a: number, c: number) => 3 * (1 - t) * (1 - t) * t * a + 3 * (1 - t) * t * t * c + t * t * t;
  let lo = 0, hi = 1;
  for (let k = 0; k < 40; k++) { const mid = (lo + hi) / 2; if (b(mid, p[0], p[2]) < x) lo = mid; else hi = mid; }
  return b((lo + hi) / 2, p[1], p[3]);
}

/** One property of an animation at progress `p` of its iteration. */
function sample<K extends "transform" | "opacity">(list: Frame[], key: K, p: number, easing: string): Frame[K] {
  const own = list.filter((f) => f[key] !== undefined);
  if (!own.length) return undefined;
  if (own[0].offset > 0 || own[own.length - 1].offset < 1) throw new Error(`${key} keyframes must start at 0% and end at 100%`);
  let k = 0;
  while (k < own.length - 2 && own[k + 1].offset <= p) k++;
  const a = own[k], b = own[k + 1];
  const f = ease(a.easing ?? easing, b.offset === a.offset ? 1 : Math.min(1, Math.max(0, (p - a.offset) / (b.offset - a.offset))));
  if (key === "opacity") return (a.opacity! + (b.opacity! - a.opacity!) * f) as Frame[K];
  const ta = a.transform!, tb = b.transform!;
  if (ta.length !== tb.length || ta.some((fn, n) => fn.name !== tb[n].name || fn.args.length !== tb[n].args.length)) throw new Error("keyframes of one animation list the same transforms");
  return ta.map((fn, n) => ({ name: fn.name, args: fn.args.map((arg, q) => {
    const other = tb[n].args[q];
    if (arg.unit !== other.unit && arg.v !== 0 && other.v !== 0) throw new Error(`units ${arg.unit} and ${other.unit}`);
    return { v: arg.v + (other.v - arg.v) * f, unit: arg.v === 0 ? other.unit : arg.unit };
  }) })) as Frame[K];
}

interface El { tag: string; attrs: Record<string, string>; classes: string[]; kids: El[]; up: El | null }
const tree = (nodes: ArtNode[], up: El | null): El[] => nodes.filter(([tag]) => tag !== "#text" && tag !== "defs").map(([tag, attrs, kids]) => {
  const el: El = { tag, attrs, classes: (attrs.class ?? "").split(/\s+/).filter(Boolean), kids: [], up };
  el.kids = tree(kids, el);
  return el;
});

const NUM = /-?\d*\.?\d+(?:e-?\d+)?/g;
/** Points whose hull holds a shape, in its own coordinates: a curve by its
 *  control points, an arc (never more than half a turn here) by the square
 *  round its chord, a round shape by a polygon drawn outside it. */
function hull(el: El): [number, number][] {
  const v = (name: string) => Number(el.attrs[name] ?? 0);
  if (el.tag === "rect") return [[v("x"), v("y")], [v("x") + v("width"), v("y")], [v("x"), v("y") + v("height")], [v("x") + v("width"), v("y") + v("height")]];
  if (el.tag === "circle" || el.tag === "ellipse") {
    const rx = el.tag === "circle" ? v("r") : v("rx"), ry = el.tag === "circle" ? v("r") : v("ry"), k = 1 / Math.cos(Math.PI / 16);
    return Array.from({ length: 16 }, (_, n) => [v("cx") + rx * k * Math.cos((n * Math.PI) / 8), v("cy") + ry * k * Math.sin((n * Math.PI) / 8)] as [number, number]);
  }
  if (el.tag !== "path") return [];
  const pts: [number, number][] = [];
  let x = 0, y = 0, sx = 0, sy = 0;
  for (const m of (el.attrs.d ?? "").matchAll(/([a-zA-Z])([^a-zA-Z]*)/g)) {
    const c = m[1], rel = c === c.toLowerCase() && c !== "z", n = (m[2].match(NUM) ?? []).map(Number);
    const step = { m: 2, l: 2, h: 1, v: 1, c: 6, q: 4, a: 7, z: 0 }[c.toLowerCase()];
    if (step === undefined) throw new Error(`path command ${c}`);
    if (step === 0) { x = sx; y = sy; continue; }
    for (let k = 0; k + step <= n.length; k += step) {
      const p = n.slice(k, k + step), ox = rel ? x : 0, oy = rel ? y : 0;
      const kind = c.toLowerCase();
      if (kind === "h") x = ox + p[0];
      else if (kind === "v") y = oy + p[0];
      else if (kind === "a") {
        const ex = ox + p[5], ey = oy + p[6], half = Math.hypot(ex - x, ey - y) / 2, mx = (x + ex) / 2, my = (y + ey) / 2;
        pts.push([mx - half, my - half], [mx + half, my - half], [mx - half, my + half], [mx + half, my + half]);
        x = ex; y = ey;
      } else {
        for (let q = 0; q + 2 < p.length; q += 2) pts.push([ox + p[q], oy + p[q + 1]]);
        x = ox + p[p.length - 2]; y = oy + p[p.length - 1];
      }
      pts.push([x, y]);
      if (kind === "m" && k === 0) { sx = x; sy = y; }
    }
  }
  return pts;
}

/** A drawing's `transform` attribute. */
function attrMatrix(text: string | undefined): M {
  let m = ID;
  for (const f of text ? [...text.matchAll(/([a-z]+)\(([^)]*)\)/g)] : []) {
    const a = f[2].split(/[\s,]+/).filter(Boolean).map(Number);
    if (f[1] === "translate") m = mul(m, shift(a[0], a[1] ?? 0));
    else if (f[1] === "rotate") m = mul(m, mul(shift(a[1] ?? 0, a[2] ?? 0), mul(turn(a[0]), shift(-(a[1] ?? 0), -(a[2] ?? 0)))));
    else if (f[1] === "scale") m = mul(m, size(a[0], a[1] ?? a[0]));
    else throw new Error(`attribute transform ${f[1]}`);
  }
  return m;
}

const CSS = sheet(["companion.css", "companion.store.css"].map((f) => readFileSync(`${import.meta.dirname}/${f}`, "utf8")).join("\n"));
const VIEW: Box = { x: 0, y: 0, w: 400, h: 400 };

/** What the sheets say of one element under a figure whose root carries `root`. */
function styled(el: El, root: string[]) {
  const chain: string[][] = [];
  for (let e = el.up; e; e = e.up) chain.push(e.classes);
  chain.push(root);
  const under = (path: string[][], from: number): boolean => {
    if (!path.length) return true;
    const want = path[path.length - 1];
    for (let k = from; k < chain.length; k++) if (want.every((c) => chain[k].includes(c)) && under(path.slice(0, -1), k + 1)) return true;
    return false;
  };
  const hit = CSS.rules.map((r, order) => ({ r, order }))
    .filter(({ r }) => r.path[r.path.length - 1].every((c) => el.classes.includes(c)) && under(r.path.slice(0, -1), 0))
    .sort((a, b) => a.r.weight - b.r.weight || a.order - b.order);
  let box = "view-box", origin = "0 0", opacity = 1;
  const now: { anim: Anim | null } = { anim: null };
  for (const { r } of hit) {
    for (const [prop, value] of r.decl) {
      if (prop === "transform-box") box = value;
      else if (prop === "transform-origin") origin = value;
      else if (prop === "opacity") opacity = Number(value);
      else if (prop === "animation") {
        if (value.startsWith("none")) { now.anim = null; continue; }
        const next: Anim = { name: "", ms: 0, delay: 0, count: 1, easing: "ease", fill: "none" };
        let times = 0;
        for (const tok of value.match(/[\w-]+\([^)]*\)|[^\s]+/g) ?? []) {
          if (/^[\d.]+m?s$/.test(tok)) { const ms = tok.endsWith("ms") ? parseFloat(tok) : parseFloat(tok) * 1000; if (times++ === 0) next.ms = ms; else next.delay = ms; }
          else if (/^(linear|ease|ease-in|ease-out|ease-in-out|cubic-bezier\(.*\))$/.test(tok)) next.easing = tok;
          else if (/^\d+$/.test(tok)) next.count = Number(tok);
          else if (tok === "infinite") next.count = Infinity;
          else if (/^(both|forwards|backwards)$/.test(tok)) next.fill = tok;
          else next.name = tok;
        }
        now.anim = next;
      } else if (now.anim && prop === "animation-delay") now.anim = { ...now.anim, delay: parseFloat(value) * (value.endsWith("ms") ? 1 : 1000) };
      else if (now.anim && prop === "animation-name") now.anim = { ...now.anim, name: value };
    }
  }
  return { box, origin, opacity, anim: now.anim };
}

/** The static box of an element's own drawing, for a `fill-box` origin. */
function ownBox(el: El, m: M = ID, out = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity }, top = true) {
  const here = top ? m : mul(m, attrMatrix(el.attrs.transform));
  for (const [x, y] of hull(el)) {
    const [px, py] = at(here, x, y);
    out.x0 = Math.min(out.x0, px); out.y0 = Math.min(out.y0, py); out.x1 = Math.max(out.x1, px); out.y1 = Math.max(out.y1, py);
  }
  for (const kid of el.kids) ownBox(kid, here, out, false);
  return out;
}

interface Played { box: Box; moved: { cls: string; shift: number; opacity: number }[] }

/** Where a figure paints `t` ms into the pose its root classes name, in its
 *  400 units, and how far each animated part stands from its drawn place. */
function play(kind: string, root: string[], els: El[], t: number): Played {
  const out = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
  const moved: Played["moved"] = [];
  const walk = (el: El, m: M, stroke: number) => {
    const s = styled(el, root);
    let own = attrMatrix(el.attrs.transform), opacity = s.opacity;
    if (s.anim) {
      const list = CSS.frames.get(s.anim.name);
      if (!list) throw new Error(`no keyframes ${s.anim.name} (${kind})`);
      const local = t - s.anim.delay, end = s.anim.ms * s.anim.count;
      const p = local < 0 ? (/both|backwards/.test(s.anim.fill) ? 0 : null) : local >= end ? (/both|forwards/.test(s.anim.fill) ? 1 : null) : (local % s.anim.ms) / s.anim.ms;
      if (p !== null) {
        opacity = sample(list, "opacity", p, s.anim.easing) ?? opacity;
        const tf = sample(list, "transform", p, s.anim.easing);
        if (tf) {
          if (el.attrs.transform) throw new Error("an animated part carries no transform attribute of its own");
          let ref = VIEW;
          if (s.box === "fill-box") { const b = ownBox(el); ref = { x: b.x0, y: b.y0, w: b.x1 - b.x0, h: b.y1 - b.y0 }; }
          const [ox, oy] = s.origin.split(/\s+/).map((v, n) => ref[n ? "y" : "x"] + (v.endsWith("%") ? (parseFloat(v) / 100) * ref[n ? "h" : "w"] : parseFloat(v)));
          own = mul(shift(ox, oy), mul(matrix(tf, ref), shift(-ox, -oy)));
          const c = at(own, ref.x + ref.w / 2, ref.y + ref.h / 2);
          moved.push({ cls: el.classes.join("."), opacity, shift: Math.hypot(c[0] - ref.x - ref.w / 2, c[1] - ref.y - ref.h / 2) + 200 * (Math.abs(own[0] - 1) + Math.abs(own[1]) + Math.abs(own[2]) + Math.abs(own[3] - 1)) });
        }
      }
    }
    if (opacity < 0.02) return;
    const here = mul(m, own);
    const width = el.attrs.stroke === "none" ? 0 : el.attrs["stroke-width"] !== undefined || el.attrs.stroke !== undefined ? Number(el.attrs["stroke-width"] ?? 1) : stroke;
    const pad = (el.attrs.stroke ?? (stroke ? "inherit" : "none")) === "none" ? 0 : (width / 2) * Math.max(Math.hypot(here[0], here[1]), Math.hypot(here[2], here[3]));
    for (const [x, y] of hull(el)) {
      const [px, py] = at(here, x, y);
      out.x0 = Math.min(out.x0, px - pad); out.y0 = Math.min(out.y0, py - pad); out.x1 = Math.max(out.x1, px + pad); out.y1 = Math.max(out.y1, py + pad);
    }
    for (const kid of el.kids) walk(kid, here, el.attrs.stroke && el.attrs.stroke !== "none" ? Number(el.attrs["stroke-width"] ?? 1) : el.attrs.stroke === "none" ? 0 : stroke);
  };
  for (const el of els) walk(el, ID, 0);
  return { box: { x: out.x0, y: out.y0, w: out.x1 - out.x0, h: out.y1 - out.y0 }, moved };
}

const PHONE = 44, GROWN = 1.5;
/** The room a figure of `px` drawn `k` times its size may paint in, in its
 *  own 400 units: the table's `figureBox` of the grown figure, taken the
 *  same on both sides since a figure may face either way. */
function room(px: number, k: number): { side: number; top: number; bottom: number } {
  const drawn = px * k, b = figureBox({ x: 0, y: 0 }, drawn, false), u = 400 / drawn;
  return { side: Math.min(-b.x, b.x + b.w - drawn) * u, top: -b.y * u, bottom: (b.y + b.h - drawn) * u };
}

const KINDS = FREE_KINDS;
const rootOf = (kind: string, pose: string) => ["cmp", ...(DRAWINGS[kind as keyof typeof DRAWINGS].char ? ["cmp-char"] : []), `cmp-${kind}`, ...(pose ? [`cmp-${pose}`] : []), "cmp-us"];
const drawing = (kind: string, still: boolean) => tree(parseArt(DRAWINGS[kind as keyof typeof DRAWINGS].markup("" as never, "t", { pose: "react", detail: false, still, team: "us" })), null);
/** The pieces a special adds to the figure: each fades in and out for it alone. */
const PIECES = ["cmp-smoke", "cmp-dust", "cmp-jet", "cmp-pop", "cmp-feather", "cmp-trail"];
const pieces = (els: El[]): El[] => els.flatMap((el) => (PIECES.some((c) => el.classes.includes(c)) ? [el] : pieces(el.kids)));

describe("the free companions' specials", () => {
  it("are the Tractor's, the Bun's, the Chick's and the Sparrow's", () => {
    expect([...KINDS].sort()).toEqual(["bun", "chick", "sparrow", "tractor"]);
  });

  it.each(KINDS)("the %s's special paints inside the box the table keeps for it at the phone's 44 px, drawn 1.5 times its size", (kind) => {
    const els = drawing(kind, false), lim = room(PHONE, GROWN), ms = DRAWINGS[kind].reactMs;
    const reach = { left: 0, right: 0, top: 0, bottom: 0 };
    for (let t = 0; t < ms; t += 10) {
      const b = play(kind, rootOf(kind, "react"), els, t).box;
      reach.left = Math.max(reach.left, -b.x); reach.right = Math.max(reach.right, b.x + b.w - 400);
      reach.top = Math.max(reach.top, -b.y); reach.bottom = Math.max(reach.bottom, b.y + b.h - 400);
    }
    expect(reach.left).toBeLessThanOrEqual(lim.side);
    expect(reach.right).toBeLessThanOrEqual(lim.side);
    expect(reach.top).toBeLessThanOrEqual(lim.top);
    expect(reach.bottom).toBeLessThanOrEqual(lim.bottom);
  });

  it("the evaluator sees a part that leaves the box: the Sparrow's loop turned about a centre 80 units higher breaks the top", () => {
    const els = drawing("sparrow", false), lim = room(PHONE, GROWN);
    const loop = CSS.rules.find((r) => r.path.length === 2 && r.path[1].includes("cmp-loop") && r.decl.some(([p]) => p === "transform-origin"))!;
    const kept = loop.decl;
    loop.decl = kept.map(([p, v]) => (p === "transform-origin" ? [p, "196px 45px"] : [p, v]));
    try {
      let top = 0;
      for (let t = 0; t < DRAWINGS.sparrow.reactMs; t += 10) top = Math.max(top, -play("sparrow", rootOf("sparrow", "react"), els, t).box.y);
      expect(top).toBeGreaterThan(lim.top);
    } finally {
      loop.decl = kept;
    }
  });

  it.each(KINDS)("the %s's special runs 1.2 to 2 s, as long as its longest part and exactly as long as its body's move", (kind) => {
    const ms = DRAWINGS[kind].reactMs;
    expect(ms).toBeGreaterThanOrEqual(1200);
    expect(ms).toBeLessThanOrEqual(2000);
    const ends: number[] = [];
    let body = 0;
    const each = (el: El) => {
      const a = styled(el, rootOf(kind, "react")).anim;
      if (a) { ends.push(a.delay + a.ms * a.count); if (el.classes.includes("cmp-body")) body = a.delay + a.ms * a.count; }
      el.kids.forEach(each);
    };
    drawing(kind, false).forEach(each);
    expect(ends.length).toBeGreaterThan(1);
    expect(Math.max(...ends)).toBeLessThanOrEqual(ms);
    // the body's animation ending is what ends the pose (Companion.tsx)
    expect(body).toBe(ms);
  });

  it.each(KINDS)("the %s's special ends at idle: every part is back in its drawn place and every added piece has faded", (kind) => {
    const els = drawing(kind, false), ms = DRAWINGS[kind].reactMs;
    const last = play(kind, rootOf(kind, "react"), els, ms - 1);
    expect(last.moved.length).toBeGreaterThan(0);
    // a limb only the pose draws (the rider's waving arm) leaves with the pose
    const inIdle = new Set<string>();
    const note = (el: El) => { el.classes.forEach((c) => inIdle.add(c)); el.kids.forEach(note); };
    tree(parseArt(DRAWINGS[kind].markup("" as never, "t", { pose: "idle", detail: false, still: true, team: "us" })), null).forEach(note);
    for (const part of last.moved) {
      const cls = part.cls.split(".");
      if (PIECES.some((c) => cls.includes(c))) expect(part.opacity, part.cls).toBeLessThan(0.05);
      else if (cls.some((c) => inIdle.has(c))) expect(part.shift, part.cls).toBeLessThan(4);
    }
    // and it paints where the idle drawing does, within a couple of units
    const idle = play(kind, rootOf(kind, ""), tree(parseArt(DRAWINGS[kind].markup("" as never, "t", { pose: "idle", detail: false, still: true, team: "us" })), null), 0).box;
    expect(Math.abs(last.box.y - idle.y)).toBeLessThan(4);
    expect(Math.abs(last.box.x - idle.x)).toBeLessThan(4);
    expect(Math.abs(last.box.w - idle.w)).toBeLessThan(8);
  });

  it.each(KINDS)("the %s's special moves at most five added pieces, each hidden before and after its moment", (kind) => {
    const added = pieces(drawing(kind, false));
    expect(added.length).toBeGreaterThan(0);
    expect(added.length).toBeLessThanOrEqual(5);
    for (const el of added) {
      const a = styled(el, rootOf(kind, "react")).anim!;
      expect(a.fill, el.classes.join(".")).toBe("both");
      const list = CSS.frames.get(a.name)!;
      expect(sample(list, "opacity", 0, a.easing)).toBeCloseTo(0, 6);
      expect(sample(list, "opacity", 1, a.easing)).toBeCloseTo(0, 6);
    }
  });

  it("every keyframe of the four specials sets only transform, opacity and its own timing", () => {
    const src = readFileSync(`${import.meta.dirname}/companion.store.css`, "utf8");
    const names = new Set<string>();
    for (const kind of KINDS) {
      const each = (el: El) => { const a = styled(el, rootOf(kind, "react")).anim; if (a) names.add(a.name); el.kids.forEach(each); };
      drawing(kind, false).forEach(each);
    }
    expect(names.size).toBeGreaterThan(12);
    for (const name of names) {
      const body = new RegExp(`@keyframes ${name} \\{([\\s\\S]*?)\\n\\}`).exec(src)?.[1] ?? new RegExp(`@keyframes ${name} \\{([\\s\\S]*?)\\n\\}`).exec(readFileSync(`${import.meta.dirname}/companion.css`, "utf8"))![1];
      const props = [...body.matchAll(/[{;]\s*([a-z-]+)\s*:/g)].map((m) => m[1]);
      expect(props.filter((p) => p !== "transform" && p !== "opacity" && p !== "animation-timing-function"), name).toEqual([]);
    }
  });

  describe("under Reduce Motion", () => {
    it.each(KINDS)("the %s's special is one still drawing inside the figure's own box at the table, with no dust or landing pieces", (kind) => {
      const els = drawing(kind, true), lim = room(PHONE, 1);
      const b = play(kind, ["cmp", `cmp-${kind}`, "cmp-still", "cmp-us"], els, 0).box;
      expect(-b.x).toBeLessThanOrEqual(lim.side);
      expect(b.x + b.w - 400).toBeLessThanOrEqual(lim.side);
      expect(-b.y).toBeLessThanOrEqual(lim.top);
      expect(b.y + b.h - 400).toBeLessThanOrEqual(lim.bottom);
      expect(pieces(els).some((el) => el.classes.includes("cmp-dust"))).toBe(false);
    });

    it.each(KINDS)("the %s is drawn without its special's animation class, and the sheet stills whatever is left", async (kind) => {
      const host = document.createElement("div");
      document.body.appendChild(host);
      const root = createRoot(host);
      try {
        await act(async () => { root.render(<Companion kind={kind} colour={"" as never} size={PHONE} state="react" still team="us" />); });
        const svg = host.querySelector("svg.cmp")!;
        expect(svg.classList.contains("cmp-react")).toBe(false);
        expect(svg.classList.contains("cmp-still")).toBe(true);
      } finally {
        act(() => root.unmount());
        host.remove();
      }
      const src = readFileSync(`${import.meta.dirname}/companion.store.css`, "utf8");
      expect(src).toMatch(/@media \(prefers-reduced-motion: reduce\) \{\s*\.cmp \* \{ animation: none !important; \}/);
    });
  });
});
