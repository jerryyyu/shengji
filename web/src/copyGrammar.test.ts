// @vitest-environment node
/// <reference types="node" />
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/** "Us" and "Them" are labels (the HUD chips, the table heads, "Games: Us 1 ·
 *  Them 0"); a sentence's subject is "We" or "They". These catch either word,
 *  or a `teamWord(...)` interpolation, standing right before a verb. */
const VERBS = "win|wins|lose|loses|took|take|takes|go|goes|went|scored|score|bank|banks|attack|attacks|defend|defends|won|lost|get|gets";
const LABEL_AS_SUBJECT = new RegExp(`\\b(?:Us|Them)\\s+(?:${VERBS})\\b`);
const TEAMWORD_AS_SUBJECT = new RegExp(`teamWord\\([^)]*\\)\\}?\\s*\\{?\\s*(?:verb\\b|(?:${VERBS})\\b)`);

const root = fileURLToPath(new URL(".", import.meta.url));

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sources(path);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

function offenders(text: string): string[] {
  return text.split("\n").filter((line) => LABEL_AS_SUBJECT.test(line) || TEAMWORD_AS_SUBJECT.test(line));
}

describe("Us and Them are labels, never a sentence's subject", () => {
  it("no source under web/src uses them before a verb", () => {
    const files = sources(root);
    expect(files.some((f) => f.endsWith("components/RoundEndModal.tsx"))).toBe(true);
    const found = files.flatMap((file) =>
      offenders(readFileSync(file, "utf8")).map((line) => `${relative(root, file)}: ${line.trim()}`));
    expect(found).toEqual([]);
  });

  it("catches a label as the subject, in text and through teamWord", () => {
    expect(offenders(`title = "Them win the round";`)).toHaveLength(1);
    expect(offenders("`Us go up ${n}`")).toHaveLength(1);
    expect(offenders("`${teamWord(t, state)} took ${pts} of 80.`")).toHaveLength(1);
    expect(offenders("<>{teamWord(team, state)} {verb} {what}</>")).toHaveLength(1);
  });

  it("leaves the labels alone", () => {
    expect(offenders("Games: Us {a} · Them {b}")).toEqual([]);
    expect(offenders("`${pointsLabel(state)} 15 / 80`")).toEqual([]);
    expect(offenders("Us first")).toEqual([]);
    expect(offenders("<b>{teamWord(team, state)}</b>")).toEqual([]);
  });
});
