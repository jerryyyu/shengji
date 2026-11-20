// App source never turns a string into code or markup: no eval, no Function
// constructor, no raw HTML sinks. Text reaches the page through React or
// textContent only, so nothing a peer, the server or a link sends can run.
// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const WEB = new URL("..", import.meta.url).pathname;
const SRC = join(WEB, "src");

const SINKS: [string, RegExp][] = [
  ["eval(", /\beval\s*\(/],
  ["new Function(", /\bnew\s+Function\s*\(/],
  ["dangerouslySetInnerHTML", /dangerouslySetInnerHTML/],
  [".innerHTML =", /\.innerHTML\s*\+?=/],
  [".outerHTML =", /\.outerHTML\s*\+?=/],
  ["insertAdjacentHTML", /insertAdjacentHTML/],
  ["document.write", /document\.write(ln)?\b/],
];

/** Files allowed a sink, each with why it is safe. */
const ALLOW: Record<string, string> = {
  "offline/server/nearby/spike.ts":
    "the transport spike's debug page: its fixed markup is a template literal with no input in it, and it is " +
    "built only with SHENGJI_NEARBY_SPIKE=1 (asserted below), never in a served or shipped build",
};

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name);
    if (e.isDirectory()) return sources(p);
    if (!/\.(ts|tsx|js|jsx|mjs)$/.test(e.name) || /\.test\.(ts|tsx)$/.test(e.name)) return [];
    return [p];
  });
}

/** The sinks `text` contains, by name. */
function sinksIn(text: string): string[] {
  return SINKS.filter(([, re]) => re.test(text)).map(([name]) => name);
}

describe("no code or markup sinks in app source", () => {
  const files = sources(SRC);

  it("finds the app's source", () => {
    expect(files.length).toBeGreaterThan(50);
    for (const f of Object.keys(ALLOW)) expect(files, `allowlisted ${f} exists`).toContain(join(SRC, f));
  });

  it("no file outside the allowlist has a sink", () => {
    const found = files
      .map((f) => [relative(SRC, f), sinksIn(readFileSync(f, "utf8"))] as const)
      .filter(([rel, hits]) => hits.length > 0 && !(rel in ALLOW))
      .map(([rel, hits]) => `${rel}: ${hits.join(", ")}`);
    expect(found).toEqual([]);
  });

  it("the patterns catch each sink and pass plain text", () => {
    expect(sinksIn("const x = eval('1')")).toEqual(["eval("]);
    expect(sinksIn("new Function('return 1')")).toEqual(["new Function("]);
    expect(sinksIn("<div dangerouslySetInnerHTML={{ __html: s }} />")).toEqual(["dangerouslySetInnerHTML"]);
    expect(sinksIn("el.innerHTML = s")).toEqual([".innerHTML ="]);
    expect(sinksIn("el.outerHTML += s")).toEqual([".outerHTML ="]);
    expect(sinksIn("el.insertAdjacentHTML('beforeend', s)")).toEqual(["insertAdjacentHTML"]);
    expect(sinksIn("document.writeln(s)")).toEqual(["document.write"]);
    expect(sinksIn("el.textContent = s; retrieval(x); const html = el.innerHTML;")).toEqual([]);
  });

  it("the spike page stays out of every served and shipped build", () => {
    // only its own html entry loads it; no app module imports it
    const importers = files.filter((f) => /from\s+["'][^"']*\/spike["']|import\(\s*["'][^"']*\/spike["']/
      .test(readFileSync(f, "utf8")));
    expect(importers.map((f) => relative(SRC, f))).toEqual([]);
    expect(readFileSync(join(WEB, "index.html"), "utf8")).not.toMatch(/spike/);
    expect(readFileSync(join(WEB, "nearby-spike.html"), "utf8")).toContain("/src/offline/server/nearby/spike.ts");
    // vite adds that entry only when SHENGJI_NEARBY_SPIKE=1
    const vite = readFileSync(join(WEB, "vite.config.ts"), "utf8");
    expect(vite).toMatch(/const NEARBY_SPIKE = process\.env\.SHENGJI_NEARBY_SPIKE === "1";/);
    expect(vite).toMatch(/NEARBY_SPIKE\s*\?\s*\{ build: \{ rollupOptions: \{ input: \{ main: "index\.html", spike: "nearby-spike\.html" \} \} \} \}\s*:\s*\{\}/);
    expect(vite.match(/nearby-spike\.html/g)?.length, "the spike entry appears once, inside the gate").toBe(2);
  });
});
