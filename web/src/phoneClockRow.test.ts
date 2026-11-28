// @vitest-environment node
/// <reference types="node" />
// Guards the phone table's row of your action while your move timer runs
// (index.css, the `:where(.phone-landscape)` block). Play is the row's middle
// column; the timer's ring and the banker's crown both stand in the column to
// its left. The ring is pinned to the row's first line, so a crown left to
// auto-placement drops to a second line, the row grows upward and the ring
// rises into the trick cross over the left seat's cards and LEAD tag. jsdom
// does no layout, so this reads the block's rules; the e2e matrix's
// `ranked_clock` state checks the rendered row.
import { expect, it } from "vitest";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("./index.css", import.meta.url), "utf8");

/** Body of the block opened by `head`, braces balanced. */
function blockAt(head: string): string {
  const start = css.indexOf(head);
  expect(start).toBeGreaterThan(-1);
  const open = css.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}" && --depth === 0) return css.slice(open + 1, i);
  }
  throw new Error("unbalanced block");
}

/** Declarations of every top-level rule in `block` whose selector is exactly `selector`, merged. */
function rule(block: string, selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  const re = /([^{}]+)\{([^{}]*)\}/g;
  for (let m = re.exec(block); m; m = re.exec(block)) {
    const sel = m[1].replace(/\/\*[\s\S]*?\*\//g, "").trim().replace(/\s+/g, " ");
    if (sel !== selector) continue;
    for (const decl of m[2].replace(/\/\*[\s\S]*?\*\//g, "").split(";")) {
      const i = decl.indexOf(":");
      if (i > 0) out[decl.slice(0, i).trim()] = decl.slice(i + 1).trim().replace(/\s+/g, " ");
    }
  }
  return out;
}

/** A sum of px lengths, bare or in one calc(). */
function px(v: string | undefined): number {
  expect(v).toBeDefined();
  const body = v!.replace(/^calc\((.*)\)$/, "$1");
  return body.split("+").reduce((s, t) => {
    const m = /^\s*(\d+(?:\.\d+)?)px\s*$/.exec(t);
    expect(m, `a px length: ${t}`).not.toBeNull();
    return s + Number(m![1]);
  }, 0);
}

const phone = blockAt(":where(.phone-landscape) {");
const ring = rule(phone, ".phase-play .action-bar .timer-ring");
const crown = rule(phone, ".you-row:has(.action-bar .btn) .you-tagline:has(.banker-crown)");
const crownBesideRing = rule(phone, ".phase-play .you-row:has(.action-bar .timer-ring) .you-tagline:has(.banker-crown)");

it("stands the ring just left of Play, on the row's first line", () => {
  expect([ring["grid-column"], ring["grid-row"], ring["justify-self"]]).toEqual(["1", "1", "end"]);
  expect(rule(phone, ".phase-play .action-bar .btn.primary")["grid-column"]).toBe("2");
});

it("keeps the crown on the ring's line while the timer runs, so your row stays one line", () => {
  expect(crown["grid-column"]).toBe("1");
  expect(crownBesideRing["grid-row"]).toBe(ring["grid-row"]);
});

it("stands the crown clear of the ring, left of it", () => {
  const size = px(rule(css, ".timer-ring")["--size"]);
  const gap = px(crown.margin.split(" ")[1]);
  expect(px(crownBesideRing["margin-right"])).toBeGreaterThanOrEqual(px(ring["margin-right"]) + size + gap);
  expect([crown["justify-self"], crownBesideRing["grid-column"] ?? crown["grid-column"]]).toEqual(["end", "1"]);
});
