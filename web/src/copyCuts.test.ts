// @vitest-environment node
/// <reference types="node" />
// The copy rule (docs/design/FLOWS.md, "Copy rule") cut these lines from the
// table panel and its sheets; queue/copyRule.test.tsx holds the rule on the
// rendered panels.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

// The "before" column of docs/design/COPY_CUTS.md: exact strings a player
// read under a control, cut by the copy rule. They stay cut.
const CUT = [
  "Rates signed-in players",
  "On by default",
  "Tap a green seat to move",
  "Tap a green seat to sit there",
  "Tap a seat to move",
  "Invite by link or code",
  "Bots sit in empty seats",
  "opened this table",
  "Starts when everyone taps Start",
  "You sit after this trick",
  "Leaving a casual table is free",
  "Say hi to the table",
  "a bot holds it",
  "The ring is the bots' timer",
  "Others can join as they arrive",
  "play the bots on this device",
  "Ranked needs a connection",
  "Duo and rooms need a connection",
  "Nothing is rated or saved",
  "Press Play and the next person can join you",
  "Others see this name at the table",
  "Sign in to keep stats and games",
  "Sign in to be ranked and keep your games",
  "Your game goes on with a bot in your seat",
  "before you can play again",
  "Friends join by code",
  "at best a draw for you",
  "A bot takes your seat",
  "the others keep playing",
  "A bot plays your seat until then",
  "· away",
  "Leave the room?",
  "Your turn: tap",
  "They took",
  "We took",
  "Attackers took",
  "Levels restart at",
  "重新打起",
  "满 80 上台",
  "Waiting for {n} players",
];

const SRC = fileURLToPath(new URL(".", import.meta.url));
function sources(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...sources(p));
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(p);
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

it("no copy the copy rule cut comes back, in a string or JSX text", () => {
  const hits: string[] = [];
  for (const f of sources(SRC)) {
    for (const text of visibleText(readFileSync(f, "utf8"))) {
      for (const cut of CUT) if (text.toLowerCase().includes(cut.toLowerCase())) hits.push(`${f}: ${cut}`);
    }
  }
  expect(hits, "This line was cut by the copy rule (docs/design/COPY_CUTS.md); explanations belong in How to play")
    .toEqual([]);
});
