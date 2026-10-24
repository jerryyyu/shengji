// @vitest-environment node
/// <reference types="node" />
// Keeps the CSS motion custom properties and the TS tokens in src/motion.ts in step.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { DUR, EASE } from "./motion";

describe("tokens", () => {
  it("match the CSS custom properties", () => {
    const css = readFileSync(new URL("./index.css", import.meta.url), "utf8");
    const prop = (name: string) => new RegExp(`--${name}:\\s*([^;]+);`).exec(css)?.[1].trim();
    for (const [k, v] of Object.entries(DUR)) expect(prop(`dur-${k}`), k).toBe(`${v}ms`);
    expect(prop("ease-out-expo")).toBe(EASE.outExpo);
    expect(prop("ease-back")).toBe(EASE.back);
    expect(prop("ease-in-out")).toBe(EASE.inOut);
  });
});
