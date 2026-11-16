// @vitest-environment node
/// <reference types="node" />
// Every class an index.css selector names is one the app can set: its name
// appears as a word in a source file under src or in index.html (tests,
// snapshots and stylesheets do not count), or it is built from one of the few
// template prefixes below. A rule for a class nothing sets styles nothing.
import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";

const srcDir = new URL("./", import.meta.url);
const css = readFileSync(new URL("./index.css", srcDir), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

function sourceText(): string {
  const files = readdirSync(srcDir, { recursive: true, encoding: "utf8" })
    .filter((f) => /\.(ts|tsx)$/.test(f) && !/\.test\.tsx?$/.test(f) && !f.includes("__snapshots__"));
  const texts = files.map((f) => readFileSync(new URL(f, srcDir), "utf8"));
  texts.push(readFileSync(new URL("../index.html", srcDir), "utf8"));
  return texts.join("\n");
}
const source = sourceText();
const words = new Set(source.match(/[A-Za-z0-9_-]+/g));

/** Classes whose names only exist at run time, each from one template in the source. */
const PREFIXES: Record<string, string> = {
  "avatar-": "HomeShell: `avatar-${size}`",
  "leave-sheet-": "ConfirmSheet: `leave-sheet-${place}`",
  "phase-": "Table: `phase-${state.phase}`, the server's phase name",
};

/** Classes kept with no source use, because another CSS test pins their rule's exact selector list. */
const PINNED: Record<string, [string, string]> = {
  "you-tag": ["landscapeLayout.test.ts", ".you-tag, .host-tag, .off-tag"],
  "host-tag": ["landscapeLayout.test.ts", ".you-tag, .host-tag, .off-tag"],
  "start-level-row": ["chromeCss.test.ts", ".start-level-row select:focus"],
};

function selectorClasses(): Set<string> {
  const out = new Set<string>();
  const re = /([^{}]+)\{/g;
  for (let m = re.exec(css); m; m = re.exec(css)) {
    const sel = m[1].trim();
    if (sel.startsWith("@")) continue;
    for (const c of sel.matchAll(/\.(-?[A-Za-z_][\w-]*)/g)) out.add(c[1]);
  }
  return out;
}

describe("index.css", () => {
  it("styles only classes the app sets", () => {
    const unused = [...selectorClasses()].filter((c) => !words.has(c)
      && !Object.keys(PREFIXES).some((p) => c.startsWith(p)) && !(c in PINNED));
    expect(unused).toEqual([]);
  });

  it("keeps each template prefix in use", () => {
    for (const p of Object.keys(PREFIXES)) expect(source, p).toContain(`${p}\${`);
  });

  it("keeps each pinned class pinned by its test", () => {
    for (const [c, [file, selector]] of Object.entries(PINNED)) {
      expect(readFileSync(new URL(file, srcDir), "utf8"), c).toContain(selector);
    }
  });
});
