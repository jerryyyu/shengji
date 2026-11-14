// @vitest-environment node
/// <reference types="node" />
// The player's surfaces and flow paths are fixed lists. A new dialog, sheet,
// leave path or join path fails here until the list below names it, and the
// flow map (docs/design/FLOWS.md, docs/design/mocks/core.py) says why the
// existing one could not carry it. Removing one must shrink its list, so the
// lists only ever describe the app as it is.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

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

/** The code without its comments, so a comment naming a message is no hit. */
function code(path: string): string {
  return readFileSync(path, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
}

const files = sources(SRC).map((p) => ({ rel: relative(SRC, p).split(sep).join("/"), code: code(p) }));
const matching = (re: RegExp, skip: (rel: string) => boolean = () => false) =>
  files.filter((f) => !skip(f.rel) && re.test(f.code)).map((f) => f.rel).sort();

// A surface is a dialog, an alert dialog, a modal layer or a queue Sheet. A
// selector that looks for an open one ("[aria-modal='true']") is not a surface.
const SURFACE = /<dialog\b|role=["'](?:alert)?dialog["']|(?<![[\w-])aria-modal\s*=|<Sheet\b/;

/** Every file that draws a surface, and what it draws. */
const SURFACES = [
  "components/ConnectionPill.tsx", // the 60 s full-screen "No connection" state
  "components/GuestChip.tsx", // the guest name sheet ("Your name")
  "components/LastTrickPanel.tsx", // the last trick played, over the table
  "components/LeaveSheet.tsx", // the one Leave sheet
  "components/Lobby.tsx", // the "Table is full" card on a code join
  "components/MePage.tsx", // the delete-account confirm
  "components/OpponentActions.tsx", // a player's options at the table
  "components/ResultDialog.tsx", // the round end's modal frame
  "components/SeatTakeover.tsx", // the dropped-seat picker on a code join
  "queue/Sheet.tsx", // the queue sheet frame every Sheet uses
];

// The protocol's message union and the on-device server name these messages
// without sending them from a player's tap.
const notAClient = (rel: string) => rel === "protocol.ts" || rel.startsWith("offline/server/");

/** Every file that sends leave_room or leaves the queue. Target: one leave.ts. */
const LEAVE_SITES = [
  "App.tsx", // the leave sheet a room link opens while you sit elsewhere
  "components/HudMenu.tsx", // ⋯ → Leave game
  "components/OfflinePlay.tsx", // leaving the offline table
  "components/RoundEndModal.tsx", // Leave game on the round end
  "components/Table.tsx", // Leave on the joining-after-this-trick pill
  "queue/TablePanel.tsx", // the panel's Leave (queue and room kinds)
  "ws.ts", // leaveToLobby: the socket's own leave, keeping the connection
];

/** Every file that sends join_room / peek_room or joins the queue. Target: codeJoin.ts only. */
const JOIN_SITES = [
  "components/Lobby.tsx", // the code box and room links
  "intent.ts", // the join_room a saved intent resumes with
  "queue/Ranked.tsx", // Play (and Duo, which opens your own table)
  "queue/TablePanel.tsx", // Move it here (an offer for another table)
];

/** The files that render the panel frame: the one table UI. */
const PANEL_VIEW_SITES = ["queue/TablePanel.tsx"];

it("the surfaces a player can open are exactly the listed ones", () => {
  expect(matching(SURFACE),
    "A new dialog, sheet or modal layer needs its row in docs/design/FLOWS.md and the mock first: "
    + "each server concept getting its own container is how the UI sprawled. A removed one shrinks SURFACES.")
    .toEqual([...SURFACES].sort());
});

it("leave paths are exactly the listed ones", () => {
  expect(matching(/["']leave_room["']|\bqueue\.leave\(/, notAClient),
    "A new way to leave duplicates the one Leave sheet (FLOWS.md section 3). Route it through an existing "
    + "leave site; a removed one shrinks LEAVE_SITES.")
    .toEqual([...LEAVE_SITES].sort());
});

it("join paths are exactly the listed ones", () => {
  expect(matching(/["'](?:join_room|peek_room)["']|\bqueue\.join\(/, notAClient),
    "A new way to join or peek a table duplicates Play and the code box (FLOWS.md sections 1-2). Route it "
    + "through an existing join site; a removed one shrinks JOIN_SITES.")
    .toEqual([...JOIN_SITES].sort());
});

it("the table panel's frame is rendered only from TablePanel.tsx", () => {
  expect(matching(/\bPanelView\b/),
    "Every table kind is a kind of the one panel (FLOWS.md section 1); draw a new kind inside TablePanel.tsx.")
    .toEqual(PANEL_VIEW_SITES);
  const panel = files.find((f) => f.rel === "queue/TablePanel.tsx")!;
  expect(panel.code, "PanelView stays private to TablePanel.tsx").not.toMatch(/export[^;\n]*\bPanelView\b/);
});
