// @vitest-environment node
/// <reference types="node" />
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

const SRC = fileURLToPath(new URL(".", import.meta.url));
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? sources(p) : /\.tsx$/.test(name) && !/\.test\.tsx$/.test(name) ? [p] : [];
  });
}

it("every menu and tooltip is drawn through the pop-up layer", () => {
  // a menu or tooltip drawn in place hangs inside whatever box it opens from; iOS WebKit
  // leaves it undrawn when that box clips (e2e/menus.mjs checks the drawn ones)
  const popups = sources(SRC).filter((p) => /role=["'](?:menu|tooltip)["']/.test(readFileSync(p, "utf8")));
  const unlayered = popups.filter((p) => !/\busePopLayer\(/.test(readFileSync(p, "utf8")))
    .map((p) => relative(SRC, p).split(sep).join("/"));
  expect(popups.length).toBeGreaterThan(0);
  expect(unlayered).toEqual([]);
});
