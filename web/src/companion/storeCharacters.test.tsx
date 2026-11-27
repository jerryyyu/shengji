// The store's characters drawn in their own art: the two on sale and the
// five coming. Every colour draws every pose with one body, the signature
// reaction carries its own moment, a team marks its figures, the coming
// ones have no look id, and the Lucky Cat's card turns up a suit per play.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Stage } from "../components/CharacterPage";
import { Companion, pickSuit } from "./Companion";
import { DRAWINGS } from "./kinds";
import type { DrawnKind } from "./kinds";
import { SOLD_COLOURS, SOON, SOON_COLOURS, soonColour } from "./characters";
import { COMPANIONS, isKind, lookCatalogue, parseLook } from "./look";
import { parseArt } from "./Tractor";
import { readFileSync } from "node:fs";

const STORE: Record<string, readonly string[]> = {
  lamb: Object.keys(SOLD_COLOURS.lamb), panda: Object.keys(SOLD_COLOURS.panda),
  ...Object.fromEntries(SOON.map((k) => [k, Object.keys(SOON_COLOURS[k])])),
};
const KINDS = Object.keys(STORE) as DrawnKind[];
type Node = ReturnType<typeof parseArt>[number];
const flat = (nodes: Node[]): Node[] => nodes.flatMap((n) => [n, ...flat(n[2])]);
/** A sheet with its comments taken out. */
const sheet = (name: string) => readFileSync(`${import.meta.dirname}/${name}`, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
const storeCss = sheet("companion.store.css");
const baseCss = sheet("companion.css");
const classes = (markup: string) => new Set(flat(parseArt(markup)).flatMap((n) => String(n[1].class ?? "").split(" ")));

describe("the store characters' drawings", () => {
  it("every colour draws every pose with one body, and each portrait is its own", () => {
    const urls = new Set<string>();
    for (const kind of KINDS) {
      expect(STORE[kind]).toHaveLength(4);
      for (const colour of STORE[kind]) {
        for (const pose of ["idle", "hop", "cheer", "sleep", "react"] as const) {
          const nodes = parseArt(DRAWINGS[kind].markup(colour as never, "t", { pose }));
          expect(nodes.filter((n) => n[1].class === "cmp-body")).toHaveLength(1);
          expect(nodes.some((n) => n[1].class === "cmp-confetti")).toBe(pose === "cheer");
        }
        urls.add(DRAWINGS[kind].portraitUrl(colour as never, true));
        expect(DRAWINGS[kind].colourName(colour as never).hant).not.toBe("");
      }
      expect(DRAWINGS[kind].char).toBe(true);
    }
    expect(urls.size).toBe(KINDS.length * 4);
  });

  it("each signature carries its own moment, drawn only for the reaction", () => {
    const moment: Record<string, string[]> = {
      lamb: ["cmp-petals", "cmp-petals2", "cmp-impact", "cmp-dizzy"],
      panda: ["cmp-crumbs"],
      rabbit: ["cmp-half-l", "cmp-half-r", "cmp-reach", "cmp-crumbs"],
      cat: ["cmp-card", "cmp-suit-s", "cmp-suit-h", "cmp-suit-c", "cmp-suit-d", "cmp-suit-j"],
      fox: ["cmp-coin"],
      lion: ["cmp-costume", "cmp-pop"],
      dragon: ["cmp-flame"],
    };
    for (const kind of KINDS) {
      const colour = STORE[kind][0] as never;
      const react = classes(DRAWINGS[kind].markup(colour, "t", { pose: "react" }));
      const idle = classes(DRAWINGS[kind].markup(colour, "t", { pose: "idle" }));
      for (const c of moment[kind]) {
        expect([kind, c, react.has(c)]).toEqual([kind, c, true]);
        expect([kind, c, idle.has(c)]).toEqual([kind, c, false]);
      }
    }
  });

  it("at the table a team wears its colour and stands on its ground shadow, with no team pad", () => {
    for (const kind of KINDS) {
      const colour = STORE[kind][0] as never;
      const us = DRAWINGS[kind].markup(colour, "t", { team: "us" });
      const them = DRAWINGS[kind].markup(colour, "t", { team: "them" });
      for (const svg of [us, them]) {
        expect(svg).not.toContain("cmp-pad");
        expect(svg).toContain('class="cmp-shadow"');
      }
      expect(us).toContain("#5b9dff");
      expect(them).toContain("#ff9d4d");
      expect(DRAWINGS[kind].markup(colour, "t", {})).not.toContain("cmp-pad");
    }
  });

  it("the sold two are looks with every colour; the coming five are not looks at all", () => {
    expect(COMPANIONS.lamb).toEqual(["newyear", "jade", "ink", "lacquer"]);
    expect(COMPANIONS.panda).toEqual(["classic", "russet", "ink", "gilded"]);
    for (const kind of SOON) {
      expect(isKind(kind)).toBe(false);
      expect(parseLook(`${kind}/${soonColour(kind)}`)).toEqual({ kind: "tractor", colour: "red" });
    }
    // even a server that listed one would not make it a look here
    const listed = lookCatalogue({}, "tractor/red", [{ id: "rabbit/moon", unlocked: true, needs: null, product: null }]);
    expect(listed.some((e) => e.id.startsWith("rabbit/"))).toBe(false);
  });

  it("every animation shorthand names its keyframes, which the minifier would otherwise drop", () => {
    const defined = new Set([...(baseCss + storeCss).matchAll(/@keyframes ([\w-]+)/g)].map((m) => m[1]));
    for (const [, value] of storeCss.matchAll(/animation:\s*([^;]+);/g)) {
      if (value.trim().startsWith("none")) continue;
      const names = value.split(/[\s,]+/).filter((w) => defined.has(w));
      expect([value, names.length]).toEqual([value, 1]);
    }
  });

  it("the Lucky Cat's card is a joker about one play in twelve, else one of the four suits", () => {
    const seen: Record<string, number> = {};
    for (let i = 0; i < 1200; i++) { const s = pickSuit((i + 0.5) / 1200); seen[s] = (seen[s] ?? 0) + 1; }
    expect(seen).toEqual({ j: 100, s: 275, h: 275, c: 275, d: 275 });
  });
});

describe("the figure", () => {
  let host: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
  afterEach(() => { act(() => root.unmount()); host.remove(); });

  it("sets the Lucky Cat's suit on each play of its reaction, and on nothing else", () => {
    act(() => root.render(<Companion kind="cat" colour={"white" as never} size={120} state="idle" />));
    expect(host.querySelector("svg")!.hasAttribute("data-suit")).toBe(false);
    act(() => root.render(<Companion kind="cat" colour={"white" as never} size={120} state="react" />));
    expect(host.querySelector("svg")!.getAttribute("data-suit")).toMatch(/^[shcdj]$/);
    act(() => root.render(<Companion kind="lamb" colour="newyear" size={120} state="react" />));
    expect(host.querySelector("svg")!.hasAttribute("data-suit")).toBe(false);
  });

  it("a character page holds the signature reaction for its whole length", () => {
    vi.useFakeTimers();
    try {
      act(() => root.render(<Stage kind="lion" colour={"red" as never} size={176} label="Dancing Lion" />));
      const pose = () => [...host.querySelector("svg")!.classList].find((c) => /^cmp-(idle|hop|cheer|react|sleep)$/.test(c));
      // idle, hop (its own length and a beat), idle, cheer, idle: then the reaction
      for (const ms of [3000, 750, 1200, 1450, 1200]) act(() => { vi.advanceTimersByTime(ms); });
      expect(pose()).toBe("cmp-react");
      act(() => { vi.advanceTimersByTime(DRAWINGS.lion.reactMs); });
      expect(pose()).toBe("cmp-react");
      act(() => { vi.advanceTimersByTime(300); });
      expect(pose()).toBe("cmp-sleep");
    } finally {
      vi.useRealTimers();
    }
  });

  it("a figure drawn still with the table's props moves no part of its drawing, for every kind, colour and pose", () => {
    // the sheets' one guarantee: a still figure's descendants animate nothing,
    // and no other rule can outrank it
    const css = baseCss + storeCss;
    expect(css).toMatch(/\.cmp-still:not\(\.cmp-grow\),\s*\.cmp-still \* \{ animation: none !important; \}/);
    for (const [, value] of css.matchAll(/animation[\w-]*:\s*([^;]+);/g)) {
      if (value.includes("!important")) expect(value.trim()).toBe("none !important");
    }
    // the only animation a still figure's own svg may take is the level-up pop
    const animates = (body: string) => [...body.matchAll(/\banimation(?:-name)?:\s*([^;]+);/g)].some((d) => !d[1].trim().startsWith("none"));
    const svgLevel = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter((m) => animates(m[2]))
      .flatMap((m) => m[1].split(",")).map((sel) => sel.trim())
      .filter((sel) => sel && !sel.startsWith("@") && !sel.includes(" ") && !/^[\d.]+%|^from$|^to$/.test(sel));
    expect(svgLevel).toEqual([".cmp-grow"]);
    const colours: Record<string, readonly string[]> = { ...COMPANIONS, ...Object.fromEntries(SOON.map((k) => [k, Object.keys(SOON_COLOURS[k])])) };
    for (const kind of Object.keys(DRAWINGS) as DrawnKind[]) {
      for (const colour of colours[kind]) {
        for (const state of ["idle", "hop", "cheer", "sleep", "react"] as const) {
          act(() => root.render(<Companion kind={kind} colour={colour as never} size={40} max={48} level={12} team="us"
                                           grow={false} state={state} still idle="rest" />));
          const svg = host.querySelector("svg")!;
          expect([kind, colour, state, svg.classList.contains("cmp-still")]).toEqual([kind, colour, state, true]);
          expect(svg.classList.contains("cmp-grow")).toBe(false);
        }
      }
    }
    // an animated figure (a special played with animated markup) is not still
    act(() => root.render(<Companion kind="panda" colour="gilded" size={40} team="us" grow={false} state="react" still={false} />));
    expect(host.querySelector("svg")!.classList.contains("cmp-still")).toBe(false);
    expect(host.querySelector("svg")!.classList.contains("cmp-react")).toBe(true);
  });

  it("under Reduce Motion a reaction is drawn still, its moment left out", () => {
    act(() => root.render(<Companion kind="lamb" colour="newyear" size={120} state="react" still />));
    const svg = host.querySelector("svg")!;
    expect(svg.classList.contains("cmp-react")).toBe(false);
    expect(svg.querySelector(".cmp-petals2, .cmp-dizzy")).toBeNull();
  });
});
