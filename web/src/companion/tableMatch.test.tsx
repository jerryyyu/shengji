// Every character in every colour is the same figure in a preview (the
// Collection's stage and tiles, the portraits) and at the table: the same
// shapes, paints, gradients and textures. The table adds only the team's
// neckwear (a scarf, a collar or a kerchief, every shape of it marked
// `cmp-team`), and a preview draws none, whatever the colourway.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Companion } from "./Companion";
import type { Pose } from "./Companion";
import { DRAWINGS } from "./kinds";
import type { DrawnColour, DrawnKind } from "./kinds";
import { SOON, SOON_COLOURS } from "./characters";
import { COMPANIONS } from "./look";

const ALL: [DrawnKind, string][] = [
  ...(Object.keys(COMPANIONS) as (keyof typeof COMPANIONS)[]).flatMap((k) => COMPANIONS[k].map((c) => [k, c] as [DrawnKind, string])),
  ...SOON.flatMap((k) => Object.keys(SOON_COLOURS[k]).map((c) => [k, c] as [DrawnKind, string])),
];
const POSES: Pose[] = ["idle", "hop", "cheer", "sleep", "react"];
const TEAMISH = /\bcmp-team(-lo|-shade|-line)?\b/;
/** Shapes the table repaints in the team's colour rather than adds: the
 *  Tractor's waist stripe and its rider's neckerchief, which a preview draws
 *  in the colourway's own paint. */
const REPAINTED: Partial<Record<DrawnKind, readonly string[]>> = {
  tractor: ["d=M92 196H228", "d=M136 178Q158 190 180 178L182 186Q158 200 134 186Z"],
};

/** Every element of `markup` in document order, as its tag and sorted attributes (children apart). */
function shapes(markup: string): string[] {
  const doc = new DOMParser().parseFromString(`<svg xmlns="http://www.w3.org/2000/svg">${markup}</svg>`, "image/svg+xml");
  return [...doc.documentElement.querySelectorAll("*")].map((el) =>
    `${el.tagName} ${[...el.attributes].map((a) => `${a.name}=${a.value}`).sort().join(" ")}`);
}
const team = (s: string) => TEAMISH.test(s);

describe("a figure at the table is its preview plus the team's neckwear", () => {
  it.each(ALL)("%s in %s", (kind, colour) => {
    for (const pose of POSES) {
      for (const still of [false, true]) {
        const preview = shapes(DRAWINGS[kind].markup(colour as DrawnColour, "x", { pose, still, detail: true }));
        for (const side of ["us", "them"] as const) {
          const table = shapes(DRAWINGS[kind].markup(colour as DrawnColour, "x", { pose, still, detail: true, team: side }));
          const repainted = (s: string) => (REPAINTED[kind] ?? []).some((d) => s.includes(` ${d} `) || s.endsWith(` ${d}`));
          expect(table.filter((s) => !team(s)), `${pose}${still ? " still" : ""} ${side}`).toEqual(preview.filter((s) => !repainted(s)));
          expect(table.some(team), `${pose} ${side}: the table shows the team`).toBe(true);
        }
        // a preview wears no team neckwear and no colourway scarf
        expect(preview.some(team)).toBe(false);
        expect(preview.join("\n")).not.toMatch(/(scarf|collar)-x/);
      }
    }
  });
});

describe("every surface draws the textures", () => {
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

  it("a table-sized figure (44 px) has every layer of the stage's (176 px), the team's neckwear aside", async () => {
    for (const [kind, colour] of ALL) {
      await act(async () => {
        root.render(<>
          <Companion kind={kind} colour={colour as DrawnColour} size={176} still />
          <Companion kind={kind} colour={colour as DrawnColour} size={44} still team="us" />
        </>);
      });
      const [stage, seat] = [...host.querySelectorAll("svg.cmp")];
      const repainted = (s: string) => (REPAINTED[kind] ?? []).some((d) => s.includes(` ${d} `) || s.endsWith(` ${d}`));
      expect(drawn(seat).filter((s) => !team(s)), `${kind} ${colour}`).toEqual(drawn(stage).filter((s) => !repainted(s)));
    }
  });

  it("with six figures mounted, every id is unique and every reference resolves in its own figure", async () => {
    const six: [DrawnKind, string][] = [["lamb", "lacquer"], ["lamb", "lacquer"], ["tractor", "red"], ["panda", "gilded"], ["bun", "plain"], ["cat", ALL.find(([k]) => k === "cat")![1]]];
    await act(async () => {
      root.render(<>{six.map(([k, c], i) => <Companion key={i} kind={k} colour={c as DrawnColour} size={48} team={i % 2 ? "them" : "us"} />)}</>);
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

  it("a character with a bell at its neck keeps it in every preview and at the table", () => {
    for (const [kind, colour] of ALL.filter(([k]) => k === "lamb" || k === "cat")) {
      for (const side of [undefined, "us"] as const) {
        const doc = new DOMParser().parseFromString(`<svg xmlns="http://www.w3.org/2000/svg">${DRAWINGS[kind].markup(colour as DrawnColour, "x", { detail: true, team: side })}</svg>`, "image/svg+xml");
        expect(doc.querySelector(".cmp-bell circle"), `${kind} ${colour} ${side ?? "preview"}`).not.toBeNull();
      }
    }
  });

  it("the Lacquer Lamb keeps its gold curls and its bell at the table, and wears its scarf there only", async () => {
    await act(async () => {
      root.render(<>
        <Companion kind="lamb" colour="lacquer" size={176} still />
        <Companion kind="lamb" colour="lacquer" size={48} still team="us" />
      </>);
    });
    const [stage, seat] = [...host.querySelectorAll("svg.cmp")];
    for (const svg of [stage, seat]) {
      expect(svg.querySelectorAll('g[stroke="#ffd98a"] path').length).toBeGreaterThanOrEqual(6);   // the curls
      expect(svg.querySelector(".cmp-bell circle")).not.toBeNull();
    }
    expect(stage.querySelector(".cmp-team")).toBeNull();
    expect(seat.querySelectorAll(".cmp-team").length).toBeGreaterThanOrEqual(2);
  });
});
