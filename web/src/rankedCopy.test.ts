// @vitest-environment node
/// <reference types="node" />
// Queue games are "Ranked" everywhere a player reads about them, and the
// queue's sheet is no longer called "Find a game": no source string, JSX text
// or comment under src says otherwise.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

const SRC = fileURLToPath(new URL(".", import.meta.url));

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...sources(p));
    else if (/\.(tsx?|css)$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}

/** What a player can read: string literals and JSX text, comments removed. */
function visibleText(code: string): string[] {
  const bare = code.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
  const strings = bare.match(/"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`/g) ?? [];
  const jsxText = bare.match(/>[^<>{}=;()]+</g) ?? [];
  return [...strings, ...jsxText];
}

const files = sources(SRC);

it("no source mentions Find a game, in copy or comments", () => {
  const hits = files.filter((f) => /find a game/i.test(readFileSync(f, "utf8")));
  expect(hits).toEqual([]);
});

it("no player-facing string says Rated or rated: queue games are Ranked", () => {
  const hits: string[] = [];
  for (const f of files.filter((p) => !p.endsWith(".css"))) {
    for (const text of visibleText(readFileSync(f, "utf8"))) {
      // class names such as me-rated-link are not copy
      if (/(?<![-\w])(Rated|rated|unrated|Unrated)(?![-\w])/.test(text)) hits.push(`${f}: ${text}`);
    }
  }
  expect(hits).toEqual([]);
});
