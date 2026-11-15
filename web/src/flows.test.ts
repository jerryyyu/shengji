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
  "components/GuestChip.tsx", // the one identity sheet: a guest's name and sign-in, mounted once by App
  "components/JoinPanel.tsx", // the confirm before taking a dropped player's seat
  "components/LastTrickPanel.tsx", // the last trick played, over the table
  "components/LeaveSheet.tsx", // the one Leave sheet
  "components/MePage.tsx", // the delete-account confirm
  "components/OpponentActions.tsx", // a player's options at the table
  "components/ResultDialog.tsx", // the round end's modal frame
  "queue/Sheet.tsx", // the queue sheet frame every Sheet uses
  "queue/TablePanel.tsx", // the opener's one confirm before moving someone
];

// The message unions and the on-device server name these messages without
// sending them from a player's tap.
const notAClient = (rel: string) =>
  rel === "protocol.ts" || rel === "queue/messages.ts" || rel.startsWith("offline/server/");

/** Every file that sends a leave (table_leave, or the older leave_room) or
 *  leaves the queue. Target: one leave.ts. */
const LEAVE_SITES = [
  "App.tsx", // the leave sheet a link opens while you sit elsewhere
  "components/HudMenu.tsx", // ⋯ → Leave game
  "components/OfflinePlay.tsx", // leaving the offline table
  "components/RoundEndModal.tsx", // Leave game on the round end
  "components/Table.tsx", // Leave on the joining-after-this-trick pill
  "queue/store.ts", // queue.leave(): the queue's own leave, which the queue sites call
  "queue/tableModel.ts", // the panel's Leave, through the queue's dispatcher
  "ws.ts", // leaveToLobby: the socket's own leave, keeping the connection
];

/** Every file that sends a join or peek (table_join / table_peek, or the
 *  older join_room / peek_room) or joins the queue. Target: codeJoin.ts only. */
const JOIN_SITES = [
  "components/Lobby.tsx", // the code box and the Join panel a link opens
  "intent.ts", // the join_room a saved intent resumes with
  "queue/Ranked.tsx", // Play (and Duo, which opens your own table)
  "queue/tableModel.ts", // the panel's I’m back (your table, moved here from another device)
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
  expect(matching(/["'](?:leave_room|table_leave)["']|\bqueue\.leave\(/, notAClient),
    "A new way to leave duplicates the one Leave sheet (FLOWS.md section 3). Route it through an existing "
    + "leave site; a removed one shrinks LEAVE_SITES.")
    .toEqual([...LEAVE_SITES].sort());
});

it("join paths are exactly the listed ones", () => {
  expect(matching(/["'](?:join_room|peek_room|table_join|table_peek)["']|\bqueue\.join\(/, notAClient),
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

/** The one file that draws a toast: every message off the hand line passes through it. */
const TOAST_VIEW_SITES = ["components/Toast.tsx"];

/** Every file that shows a toast, and what it says there. */
const TOAST_SITES = [
  "App.tsx", // the server's errors and notices
  "components/Hud.tsx", // a failed throw and the engine's table messages
  "components/Lobby.tsx", // a link's table that is gone, a code that names nothing
  "components/Table.tsx", // Coach on/off, a newcomer joining the table
  "queue/QueueLayer.tsx", // the queue's notices
];

/** The one line between the trick and your hand is drawn only by the table. */
const HAND_LINE_SITES = ["components/Table.tsx"];

/** The message surfaces the one toast and the hand line replaced. They stay gone. */
const RETIRED_CLASSES = ["q-toast", "join-error", "hud-notice", "hud-message", "follow-hint", "phase-help",
  "coach-cue", "action-hint", "join-notice"];

it("one toast component draws every toast, and the listed files are the ones that show one", () => {
  expect(matching(/className=\{?["'`][^"'`]*\btoast\b/),
    "A toast is drawn only by components/Toast.tsx, in its one spot; call showToast instead (FLOWS.md, one toast).")
    .toEqual(TOAST_VIEW_SITES);
  expect(matching(/\bshowToast\(/, (rel) => rel === "toast.ts"),
    "A new toast source names its row here; a removed one shrinks TOAST_SITES.")
    .toEqual([...TOAST_SITES].sort());
  expect(matching(/<HandLine\b/), "The hand line is the table's one line above your hand.").toEqual(HAND_LINE_SITES);
});

it("the retired message surfaces stay gone, in code and in CSS", () => {
  const cssFiles = (function css(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      const p = join(dir, name);
      return statSync(p).isDirectory() ? css(p) : name.endsWith(".css") ? [p] : [];
    });
  })(SRC);
  const texts = [...files.map((f) => ({ rel: f.rel, text: f.code })),
    ...cssFiles.map((p) => ({ rel: relative(SRC, p).split(sep).join("/"), text: readFileSync(p, "utf8").replace(/\/\*[\s\S]*?\*\//g, "") }))];
  const found = texts.flatMap(({ rel, text }) =>
    RETIRED_CLASSES.filter((c) => new RegExp(`(?<![\\w-])${c}(?![\\w-])`).test(text)).map((c) => `${rel}: ${c}`));
  expect(found).toEqual([]);
  // the lobby's own error box went with them; page-load errors elsewhere keep theirs
  expect(files.find((f) => f.rel === "components/Lobby.tsx")!.code).not.toMatch(/lobby-error/);
});
