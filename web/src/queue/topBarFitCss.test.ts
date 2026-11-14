// @vitest-environment node
/// <reference types="node" />
// Guards the top bar's fit while searching, which jsdom cannot lay out: the
// side columns never shrink below their content, the groups keep 8px apart,
// and a narrow bar collapses the search pill to its time, then drops the
// account chip's name and rating.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../index.css", import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

/** The declarations of every rule whose selector is exactly `selector`, inside `media` when given. */
function decls(selector: string, media?: string): string {
  let source = css;
  if (media) {
    const at = css.indexOf(`@media ${media} {`);
    if (at < 0) throw new Error(`no @media ${media}`);
    source = css.slice(at, css.indexOf("\n}", at));
  }
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let found = "";
  for (let m = re.exec(source); m; m = re.exec(source)) {
    const sel = m[1].replace(/@media[^{]*$/, "").trim().replace(/\s+/g, " ");
    if (sel === selector) found += m[2];
  }
  if (found) return found;
  throw new Error(`no rule ${selector}${media ? ` in ${media}` : ""}`);
}

describe("the top bar while searching", () => {
  it("gives each side at least its content's width, 8px from the tabs", () => {
    const bar = decls(".topbar");
    expect(bar).toContain("grid-template-columns: minmax(min-content, 1fr) auto minmax(min-content, 1fr);");
    expect(bar).toContain("column-gap: 8px;");
    expect(bar).not.toMatch(/grid-template-columns: 1fr auto 1fr/);
    expect(decls(".topbar-mark")).toContain("white-space: nowrap");
  });

  it("caps the account chip so a long name ellipsizes instead of widening the bar", () => {
    expect(decls(".topbar .account-pill")).toContain("max-width: 280px");
    expect(decls(".topbar .account-pill", "(max-width: 799px)")).toContain("max-width: 220px");
    expect(decls(".account-pill-name")).toContain("text-overflow: ellipsis");
  });

  it("collapses the pill to its time below 1200px, still 44px, then drops the name and rating", () => {
    expect(decls(".q-pill")).toContain("height: 44px");
    expect(decls(".topbar .q-pill-label", "(max-width: 1199px)")).toContain("display: none");
    expect(decls(".topbar .q-pill", "(max-width: 1199px)")).toContain("min-width: 44px");
    expect(decls(".topbar:has(.q-pill) .account-pill-name", "(max-width: 959px)")).toContain("display: none");
    expect(decls(".topbar:has(.q-pill) .account-pill-rating", "(max-width: 767px)")).toContain("display: none");
  });
});
