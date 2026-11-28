// Every character in every colour is one figure wherever it is drawn: a
// preview (the Collection's stage and tiles, the portraits) and the table
// draw the same shapes, paints, gradients and textures. No figure wears a
// team's colour: the Lamb's scarf and the Lucky Cat's collar are their
// colourway's own, and the Tractor's stripe and its rider's neckerchief its
// colour's.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Companion } from "./Companion";
import type { Pose } from "./Companion";
import { DRAWINGS } from "./kinds";
import type { DrawnColour, DrawnKind } from "./kinds";
import { SOON, SOON_COLOURS } from "./characters";
import { COMPANIONS } from "./look";
import { LAMB_COLOURS, CAT_COLOURS } from "./storePalette";

const ALL: [DrawnKind, string][] = [
  ...(Object.keys(COMPANIONS) as (keyof typeof COMPANIONS)[]).flatMap((k) => COMPANIONS[k].map((c) => [k, c] as [DrawnKind, string])),
  ...SOON.flatMap((k) => Object.keys(SOON_COLOURS[k]).map((c) => [k, c] as [DrawnKind, string])),
];
const POSES: Pose[] = ["idle", "hop", "cheer", "sleep", "react"];
/** The marks the team's neckwear had, and (at rest, where no confetti flies) its paints. */
const TEAMISH = /cmp-(team|us|them)/;
const TEAM_PAINT = /#5b9dff|#2f6fd6|#ff9d4d|#d96a14/i;

/** Every element of `markup` in document order, as its tag and sorted attributes (children apart). */
function shapes(markup: string): string[] {
  const doc = new DOMParser().parseFromString(`<svg xmlns="http://www.w3.org/2000/svg">${markup}</svg>`, "image/svg+xml");
  return [...doc.documentElement.querySelectorAll("*")].map((el) =>
    `${el.tagName} ${[...el.attributes].map((a) => `${a.name}=${a.value}`).sort().join(" ")}`);
}

describe("no figure wears a team's colour", () => {
  it.each(ALL)("%s in %s draws one figure, with nothing of a team in it, in every pose", (kind, colour) => {
    for (const pose of POSES) for (const still of [false, true]) {
      const markup = DRAWINGS[kind].markup(colour as DrawnColour, "x", { pose, still, detail: true });
      expect(markup, `${pose}${still ? " still" : ""}`).not.toMatch(TEAMISH);
      if (pose === "idle" || pose === "sleep") expect(markup, pose).not.toMatch(TEAM_PAINT);
      // a team passed by an older caller changes nothing: the builders take none
      const asked = (DRAWINGS[kind].markup as (c: DrawnColour, id: string, o: object) => string)(colour as DrawnColour, "x", { pose, still, detail: true, team: "us" });
      expect(shapes(asked)).toEqual(shapes(markup));
    }
  });

  it("the Lamb wears its colourway's scarf and the Lucky Cat its collar, the bell hanging from it, in every pose", () => {
    for (const [kind, colour] of ALL.filter(([k]) => k === "lamb" || k === "cat")) {
      const own = kind === "lamb" ? LAMB_COLOURS[colour as keyof typeof LAMB_COLOURS].scarf : CAT_COLOURS[colour as keyof typeof CAT_COLOURS].collar;
      for (const pose of POSES) {
        const markup = DRAWINGS[kind].markup(colour as DrawnColour, "x", { pose, detail: true });
        const doc = new DOMParser().parseFromString(`<svg xmlns="http://www.w3.org/2000/svg">${markup}</svg>`, "image/svg+xml");
        const paint = doc.querySelector(`#${kind === "lamb" ? "scarf" : "collar"}-x`);
        expect(paint, `${kind} ${colour} ${pose}`).not.toBeNull();
        expect([...paint!.querySelectorAll("stop")].map((s) => s.getAttribute("stop-color"))).toEqual([own[0], own[1], own[2]]);
        expect(markup).toContain(`fill="url(#${kind === "lamb" ? "scarf" : "collar"}-x)"`);
        expect(doc.querySelector(".cmp-bell circle")).not.toBeNull();
      }
    }
    // the four Lamb scarves are four colours, Lacquer's the near-black one
    expect(new Set(Object.values(LAMB_COLOURS).map((p) => p.scarf[1])).size).toBe(4);
    expect(LAMB_COLOURS.lacquer.scarf[1]).toBe("#3a3136");
  });

  it("the Tractor's stripe and its rider's neckerchief are its colour's own", () => {
    for (const [, colour] of ALL.filter(([k]) => k === "tractor")) {
      const all = shapes(DRAWINGS.tractor.markup(colour as DrawnColour, "x", { detail: true }));
      const stripe = all.find((s) => s.includes("d=M92 196H228"))!;
      expect(stripe, colour).toContain("stroke-width=5");
      expect(all.some((s) => s.includes("d=M136 178Q158 190 180 178L182 186Q158 200 134 186Z") && /fill=/.test(s)), colour).toBe(true);
    }
  });
});

describe("every surface draws the same figure", () => {
  let host: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  beforeEach(() => {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
  });
  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });
  /** A figure's shapes with its own id taken out, so two figures compare. */
  const drawn = (svg: Element) => {
    const id = /-([A-Za-z0-9]+)\)/.exec(svg.innerHTML)?.[1] ?? "";
    return shapes(svg.innerHTML.split(id).join("ID"));
  };

  it("a table-sized figure (44 px) has every layer of the stage's (176 px), and no other", async () => {
    for (const [kind, colour] of ALL) {
      await act(async () => {
        root.render(<>
          <Companion kind={kind} colour={colour as DrawnColour} size={176} still />
          <Companion kind={kind} colour={colour as DrawnColour} size={44} still />
        </>);
      });
      const [stage, seat] = [...host.querySelectorAll("svg.cmp")];
      expect(drawn(seat), `${kind} ${colour}`).toEqual(drawn(stage));
      expect(seat.getAttribute("class"), `${kind} ${colour}`).not.toMatch(/cmp-(us|them)/);
    }
  });

  it("with six figures mounted, every id is unique and every reference resolves in its own figure", async () => {
    const six: [DrawnKind, string][] = [["lamb", "lacquer"], ["lamb", "lacquer"], ["tractor", "red"], ["panda", "gilded"], ["bun", "plain"], ["cat", ALL.find(([k]) => k === "cat")![1]]];
    await act(async () => {
      root.render(<>{six.map(([k, c], i) => <Companion key={i} kind={k} colour={c as DrawnColour} size={48} />)}</>);
    });
    const ids = [...host.querySelectorAll("[id]")].map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const svg of host.querySelectorAll("svg.cmp")) {
      const own = new Set([...svg.querySelectorAll("[id]")].map((e) => e.id));
      const refs = [...svg.innerHTML.matchAll(/url\(#([^)]+)\)/g)].map((m) => m[1]);
      expect(refs.length).toBeGreaterThan(0);
      for (const r of refs) expect(own.has(r), `#${r}`).toBe(true);
    }
  });

  it("the Lacquer Lamb keeps its gold curls, its bell and its dark scarf at every size", async () => {
    await act(async () => {
      root.render(<>
        <Companion kind="lamb" colour="lacquer" size={176} still />
        <Companion kind="lamb" colour="lacquer" size={48} still />
      </>);
    });
    for (const svg of host.querySelectorAll("svg.cmp")) {
      expect(svg.querySelectorAll('g[stroke="#ffd98a"] path').length).toBeGreaterThanOrEqual(6);   // the curls
      expect(svg.querySelector(".cmp-bell circle")).not.toBeNull();
      expect(svg.querySelector('linearGradient[id^="scarf-"] stop')?.getAttribute("stop-color")).toBe("#5f535a");
    }
  });
});
