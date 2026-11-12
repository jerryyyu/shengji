// The matchmaking queue's screens against a mocked socket: Find a game and
// its sheets, the queue bar, the ready check and what follows it, the pair
// flow, the away notice and the matched game's note.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WIDE } from "../home/HomeShell";

class FakeWS {
  static OPEN = 1;
  static all: FakeWS[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  sent: Record<string, unknown>[] = [];
  constructor() { FakeWS.all.push(this); }
  send(data: string) { this.sent.push(JSON.parse(data)); }
  close() { this.readyState = 3; this.onclose?.(); }
  deliver(msg: unknown) { this.onmessage?.({ data: JSON.stringify(msg) }); }
}

const ws = () => FakeWS.all[FakeWS.all.length - 1];
const say = (msg: unknown) => act(() => ws().deliver(msg));
const sentTypes = () => FakeWS.all.flatMap((w) => w.sent).map((m) => m.type);
const lastSent = () => { const all = FakeWS.all.flatMap((w) => w.sent); return all[all.length - 1]; };
const nowSecs = () => Date.now() / 1000;

let signedIn = true;
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const realMatchMedia = window.matchMedia;

function viewport(wide: boolean) {
  window.matchMedia = ((q: string) => ({
    matches: q === WIDE ? wide : false, media: q, addEventListener() {}, removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  FakeWS.all = [];
  signedIn = true;
  localStorage.clear();
  viewport(false);
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if ((url === "/api/me" || url.startsWith("/api/me/")) && !signedIn) {
      return { status: 401, json: async () => ({}) } as Response;
    }
    const body = url === "/api/auth/config" ? { google_client_id: "cid" }
      : url === "/api/me" ? { name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" }
      : null;
    return { status: body ? 200 : 404, json: async () => body ?? {} } as Response;
  }) as typeof fetch;
  vi.resetModules();
});
afterEach(() => {
  vi.useRealTimers();
  act(() => root.unmount());
  host.remove();
  window.matchMedia = realMatchMedia;
  window.history.replaceState(null, "", "/");
});

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

async function renderApp() {
  const { default: App } = await import("../App");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  act(() => ws().onopen?.());
  await settle();
  await settle();
}

const q = (sel: string) => document.querySelector<HTMLElement>(sel);
const buttons = (scope: ParentNode = document) => [...scope.querySelectorAll<HTMLButtonElement>("button")];
const button = (text: string | RegExp, scope: ParentNode = document) => buttons(scope).find((b) => {
  const t = b.textContent ?? "";
  return typeof text === "string" ? t === text : text.test(t);
});
const click = (b: HTMLElement | null | undefined) => {
  if (!b) throw new Error("no such button");
  act(() => b.click());
};
const findBtn = () => q(".q-find")!;

/** Fake clock from here on; the app is already rendered and settled. */
function fakeClock() {
  vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
}
const tick = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });

function queued(over: Record<string, unknown> = {}) {
  const since = nowSecs();
  return { type: "queue_state", queued: true, count: 3, since, front: false, party_id: null,
           leader: true, bots_at: since + 60, ...over };
}
const MATCH = { type: "match", match_id: "m1", deadline: 0, deadline_in: 10, size: 4, bots: 0, party_id: null };
const match = (over: Record<string, unknown> = {}) => ({ ...MATCH, deadline: nowSecs() + 10, ...over });

describe("Play", () => {
  it("one gold Find a game with the live queue count; Play vs bots is gone", async () => {
    await renderApp();
    expect(button("Play vs bots")).toBeUndefined();
    expect(findBtn().textContent).toBe("Find a game");      // no count below one
    say({ type: "queue_count", count: 3 });
    expect(findBtn().textContent).toBe("Find a game3 in queue");
    expect(findBtn().className).toContain("gold");
    expect(button("Create room")).toBeDefined();
    expect(q("input[aria-label='Game or pair code']")).not.toBeNull();
  });

  it("signed in: the sheet offers Solo and With a friend…; Solo queues", async () => {
    await renderApp();
    click(findBtn());
    const sheet = q(".q-sheet")!;
    expect(sheet.querySelector("h2")?.textContent).toBe("Find a game");
    expect(button("Solo", sheet)).toBeDefined();
    expect(sheet.textContent).toContain("With a friend…");
    expect(sheet.textContent).not.toContain("remember");
    click(button("Solo", sheet));
    expect(lastSent()).toEqual({ type: "queue_join" });
    expect(q(".q-sheet")).toBeNull();
    expect(findBtn().textContent).toContain("Finding a game…");
  });

  it("a guest's sheet offers Play vs bots now (today's unrated path) and Sign in to play people", async () => {
    signedIn = false;
    await renderApp();
    say({ type: "queue_count", count: 2 });
    expect(findBtn().textContent).toBe("Find a game2 in queue");
    click(findBtn());
    const sheet = q(".q-sheet")!;
    expect(button(/^Play vs bots now/, sheet)?.textContent).toContain("unrated");
    expect(button("Sign in to play people", sheet)).toBeDefined();
    expect(button("Solo", sheet)).toBeUndefined();
    click(button(/^Play vs bots now/, sheet));
    expect(lastSent()).toMatchObject({ type: "create_room" });
    expect(sentTypes()).not.toContain("queue_join");
    say({ type: "error", code: "x", message: "x" });
    click(findBtn());
    click(button("Sign in to play people"));
    expect(window.location.hash).toBe("#/me");
  });
});

describe("the queue bar", () => {
  it("shows the wait and the count on every tab, then turns amber near the bot fill", async () => {
    await renderApp();
    fakeClock();
    say(queued({ since: nowSecs() - 24, bots_at: nowSecs() + 36 }));
    expect(q(".q-bar")?.textContent).toContain("Finding a game");
    expect(q(".q-bar small")?.textContent).toBe("0:24 · 3 in queue");
    expect(q(".q-bar")?.className).not.toContain("warn");
    expect((findBtn() as HTMLButtonElement).disabled).toBe(true);
    tick(2000);
    expect(q(".q-bar small")?.textContent).toBe("0:26 · 3 in queue");
    tick(24_000);   // 50 s: ten seconds before the bots
    expect(q(".q-bar")?.className).toContain("warn");
    expect(q(".q-bar small")?.textContent).toBe("0:50 · bots in 0:10");
    tick(5_000);
    expect(q(".q-bar small")?.textContent).toBe("0:55 · bots in 0:05");
    // the bar follows to the other tabs
    const { openTab } = await import("../home/route");
    act(() => openTab("leaderboard"));
    expect(q(".q-bar")?.className).toContain("warn");
    act(() => openTab("me"));
    expect(q(".q-bar")).not.toBeNull();
  });

  it("Play with bots now sends queue_start_bots; Cancel leaves", async () => {
    await renderApp();
    say(queued());
    click(button("Play with bots now"));
    expect(lastSent()).toEqual({ type: "queue_start_bots" });
    expect(button("Starting…")).toBeDefined();
    say({ type: "match_started", match_id: null, room: "BOTS", rated: true });
    expect(q(".q-bar")).toBeNull();
    say(queued());
    click(button("Cancel", q(".q-bar")!));
    expect(lastSent()).toEqual({ type: "queue_leave" });
    say({ type: "queue_state", queued: false, count: 0 });
    expect(q(".q-bar")).toBeNull();
    expect(findBtn().textContent).toBe("Find a game");
  });

  it("at 700px and up the bar is a chip in the top bar", async () => {
    viewport(true);
    await renderApp();
    say(queued({ since: nowSecs() - 24 }));
    expect(q(".q-bar")).toBeNull();
    const chip = q(".topbar .q-chip")!;
    expect(chip.textContent).toContain("Finding a game · 0:24 · 3 in queue");
    expect(button("Play with bots now", chip)).toBeDefined();
    expect(button("Cancel", chip)).toBeDefined();
  });
});

const TABLE_STATE = {
  type: "state", room: "ABCD", you: 0, phase: "play", matched: true,
  players: [0, 1, 2, 3].map((seat) => ({
    seat, name: `P${seat}`, is_bot: false, connected: true, team: seat % 2, cards_left: 3, is_banker: seat === 1,
    takeover_in: null, controller: "human", reserved_for: null, reserved_secs: null,
  })),
  hand: [{ id: 1, code: "S5" }], levels: ["2", "2"], games_won: [0, 0], banker: 1,
  trump: { suit: "S", rank: "2", declarer: 1 }, turn: 1, declare_options: [], current_declaration: null,
  passed: [], trick: { leader: 1, plays: [] }, last_trick: null, attacker_points: 0, kitty_count: 8,
  message: null, notice: null, round_result: null,
};

describe("the ready check", () => {
  it("counts down, accepts with the match id, shows counts only, and names once all accept", async () => {
    await renderApp();
    say(queued());
    fakeClock();
    say(match());
    const dlg = q(".q-dlg")!;
    expect(dlg.textContent).toContain("Match found");
    expect(q(".q-big")?.textContent).toBe("Ready?");
    expect(q(".q-ring-n")?.textContent).toBe("10");
    expect(dlg.querySelectorAll(".q-pips i")).toHaveLength(4);
    expect(q(".q-bar")).toBeNull();          // the bar steps aside for the dialog
    tick(3000);
    expect(q(".q-ring-n")?.textContent).toBe("7");
    click(button("Accept"));
    expect(lastSent()).toEqual({ type: "match_accept", match_id: "m1" });
    expect(q(".q-big")?.textContent).toBe("You're ready");
    say({ type: "match_ready", match_id: "m1", accepted: 2, of: 4 });
    expect(button("2 of 4 ready")?.disabled).toBe(true);
    expect(q(".q-dlg")?.querySelectorAll(".q-pips i.ok")).toHaveLength(2);
    expect(q(".q-dlg")?.textContent).not.toContain("Mei");
    expect(q(".q-sub")?.textContent).toBe("Names are shown when everyone has accepted.");
    say({ type: "match_ready", match_id: "m1", accepted: 4, of: 4, names: ["Mei", "Wen", "Jerry", "Hao"] });
    expect(q(".q-big")?.textContent).toBe("Starting…");
    expect(q(".q-names")?.textContent).toBe("Mei · Wen · you · Hao");
    say({ type: "match_started", match_id: "m1", room: "ABCD", rated: true });
    expect(q(".q-dlg")).toBeNull();
  });

  it("Accept is disabled at zero", async () => {
    await renderApp();
    fakeClock();
    say(match());
    tick(10_000);
    expect(q(".q-ring-n")?.textContent).toBe("0");
    expect(button("Accept")?.disabled).toBe(true);
    click(button("Accept"));
    expect(sentTypes()).not.toContain("match_accept");
  });

  it("a decline sends the match id and shows the cooldown on Find a game", async () => {
    await renderApp();
    say(queued());
    fakeClock();
    say(match());
    click(button("Decline"));
    expect(lastSent()).toEqual({ type: "match_decline", match_id: "m1" });
    expect(q(".q-dlg")).toBeNull();
    say({ type: "queue_removed", reason: "declined", cooldown_until: nowSecs() + 30, match_id: "m1" });
    expect(q(".q-dlg")).toBeNull();           // no "missed" dialog for your own decline
    expect(findBtn().textContent).toBe("Queue again in 0:30");
    expect((findBtn() as HTMLButtonElement).disabled).toBe(true);
    tick(30_000);
    expect(findBtn().textContent).toBe("Find a game3 in queue");
    expect((findBtn() as HTMLButtonElement).disabled).toBe(false);
  });

  it("a timeout: You missed it, Queue again in 0:30, live at zero, and it queues", async () => {
    await renderApp();
    say(queued());
    fakeClock();
    say(match());
    tick(10_500);
    say({ type: "queue_removed", reason: "missed", cooldown_until: nowSecs() + 30, match_id: "m1" });
    expect(q(".q-big")?.textContent).toBe("You missed it");
    expect(q(".q-dlg")?.textContent).toContain("out of the queue for 30 seconds");
    expect(button("Queue again in 0:30")?.disabled).toBe(true);
    tick(12_000);
    expect(button("Queue again in 0:18")).toBeDefined();
    tick(18_000);
    click(button("Queue again"));
    expect(lastSent()).toEqual({ type: "queue_join" });
    expect(q(".q-dlg")).toBeNull();
  });

  it("someone else missed it: back in the queue at the front, and you keep your place", async () => {
    await renderApp();
    say(queued({ since: nowSecs() - 30 }));
    say(match());
    click(button("Accept"));
    say({ type: "match_cancelled", match_id: "m1", reason: "player_missed" });
    say(queued({ since: nowSecs() - 30, front: true }));
    expect(q(".q-dlg")).toBeNull();
    expect(q(".q-toast")?.textContent).toContain("A player didn't accept.");
    expect(q(".q-toast")?.textContent).toContain("You're back in the queue and keep your place.");
    expect(q(".q-bar b")?.textContent).toBe("Back in queue");
    expect(q(".q-bar small")?.textContent).toBe("you keep your place");
  });

  it("an unanswered player is told they are still queued, without the front-of-line copy", async () => {
    await renderApp();
    say(queued());
    say(match());
    say({ type: "match_cancelled", match_id: "m1", reason: "player_missed" });
    say(queued());
    expect(q(".q-toast")?.textContent).toContain("You're still in the queue.");
    expect(q(".q-bar b")?.textContent).toBe("Finding a game");
  });

  it("a pair whose partner had not answered keeps its place but not the front", async () => {
    await renderApp();
    say(queued({ party_id: "p1" }));
    say(match({ party_id: "p1" }));
    click(button("Accept"));
    say({ type: "match_cancelled", match_id: "m1", reason: "player_missed" });
    say(queued({ party_id: "p1", front: false }));
    expect(q(".q-toast")?.textContent).toContain("You're still in the queue.");
    expect(q(".q-bar b")?.textContent).not.toBe("Back in queue");
  });

  it("a late accept: the timeout comes first, then stale_match; the missed state shows", async () => {
    await renderApp();
    say(queued());
    say(match());
    say({ type: "queue_removed", reason: "missed", cooldown_until: nowSecs() + 30, match_id: "m1" });
    say({ type: "error", code: "stale_match", message: "That ready check is over." });
    expect(q(".q-big")?.textContent).toBe("You missed it");
    expect(button(/^Queue again in 0:/)?.disabled).toBe(true);
  });

  it("server_error after the room's frames: back to the lobby, queued at the front", async () => {
    await renderApp();
    say(queued());
    say(match());
    click(button("Accept"));
    say({ type: "match_ready", match_id: "m1", accepted: 4, of: 4, names: ["Jerry", "Mei", "Wen", "Hao"] });
    say({ type: "match_started", match_id: "m1", room: "ABCD", rated: true });
    say({ type: "resume", token: "t1", gen: 1 });
    say({ type: "room", room: "ABCD", you: 0, host: 0, start_level: "2", matched: true,
          players: [0, 1, 2, 3].map((seat) => ({ seat, name: `P${seat}`, is_bot: false, connected: true })) });
    say(TABLE_STATE);
    expect(q(".table-screen")).not.toBeNull();
    expect(localStorage.getItem("shengji.room")).toBe("ABCD");
    say({ type: "match_cancelled", match_id: "m1", reason: "server_error" });
    say(queued({ front: true }));
    expect(q(".table-screen")).toBeNull();
    expect(q(".q-find")).not.toBeNull();
    expect(localStorage.getItem("shengji.room")).toBeNull();   // nothing to resume
    expect(q(".q-bar b")?.textContent).toBe("Back in queue");
    expect(q(".q-toast")?.textContent).toContain("The game could not start.");
  });

  it("a bots game that fails to start returns to the lobby, out of the queue", async () => {
    await renderApp();
    say(queued());
    click(button("Play with bots now"));
    say({ type: "match_started", match_id: null, room: "BOTS", rated: true });
    say({ ...TABLE_STATE, room: "BOTS" });
    say({ type: "error", code: "start_failed", message: "Could not start the game." });
    expect(q(".table-screen")).toBeNull();
    expect(q(".q-bar")).toBeNull();
    expect((findBtn() as HTMLButtonElement).disabled).toBe(false);
  });

  it("a bot-fill match offers Keep waiting, which declines with keep_waiting", async () => {
    await renderApp();
    say(queued({ since: nowSecs() - 60 }));
    say(match({ match_id: "m2", size: 2, bots: 2 }));
    const dlg = q(".q-dlg")!;
    expect(dlg.querySelector("h3")?.textContent).toBe("Not enough players");
    expect(q(".q-big")?.textContent).toBe("Starting with 2 bots");
    expect(dlg.querySelectorAll(".q-pips i.bot")).toHaveLength(2);
    expect(button("Decline")).toBeUndefined();
    click(button("Keep waiting"));
    expect(lastSent()).toEqual({ type: "match_decline", match_id: "m2", keep_waiting: true });
    expect(q(".q-dlg")).toBeNull();
    say({ type: "match_cancelled", match_id: "m2", reason: "keep_waiting" });
    say(queued());
    expect(q(".q-bar b")?.textContent).toBe("Finding a game");
  });
});

describe("with a friend", () => {
  const party = (members: { name: string; leader: boolean; you: boolean }[], youLead = true) => ({
    type: "party", party_id: "p1", code: "7F2K", you_lead: youLead, members, expires_at: nowSecs() + 300,
  });
  const ME = { name: "Jerry", leader: true, you: true };
  const SAM = { name: "Sam", leader: false, you: false };

  it("creates a code, shows it, forms the pair chip and queues as a pair", async () => {
    await renderApp();
    click(findBtn());
    click(button(/^With a friend…/));
    expect(lastSent()).toEqual({ type: "party_create" });
    expect(q(".q-sheet h2")?.textContent).toBe("Queue with a friend");
    say(party([ME]));
    expect(q(".q-codebox b")?.textContent).toBe("7F2K");
    expect(button("Share invite link")).toBeDefined();
    expect(button("Copy code")).toBeDefined();
    click(button("Cancel", q(".q-sheet")!));
    expect(q(".q-party-chip")?.textContent).toContain("7F2K");
    say(party([ME, SAM]));
    expect(q(".q-toast")?.textContent).toContain("Sam joined your pair.");
    const chip = q(".q-party-chip")!;
    expect(chip.textContent).toContain("You + Sam");
    expect(chip.textContent).toContain("you lead");
    expect(findBtn().textContent).toContain("Find a game as a pair");
    click(findBtn());          // no sheet: straight into the queue
    expect(q(".q-sheet")).toBeNull();
    expect(lastSent()).toEqual({ type: "queue_join", party_id: "p1" });
    fakeClock();
    say(queued({ party_id: "p1" }));
    tick(12_000);
    expect(q(".q-bar b")?.textContent).toBe("You + Sam · 0:12");
    expect(q(".q-bar small")?.textContent).toBe("3 in queue");
    say(match({ party_id: "p1", size: 4 }));
    expect(q(".q-big")?.textContent).toBe("Ready? Both of you");
  });

  it("joins a friend's pair by code from Me; the member cannot start or cancel", async () => {
    await renderApp();
    const { openTab } = await import("../home/route");
    act(() => openTab("me"));
    await settle();
    click(button(/^Queue with a friend/));
    expect(lastSent()).toEqual({ type: "party_create" });
    const input = q("#q-join-code") as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, "ab12"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    click(button("Join", q(".q-join")!));
    expect(lastSent()).toEqual({ type: "code_lookup", code: "AB12" });
    say({ type: "code_kind", code: "AB12", kind: "party" });
    expect(lastSent()).toEqual({ type: "party_join", code: "AB12" });
    say(party([{ name: "Sam", leader: true, you: false }, { name: "Jerry", leader: false, you: true }], false));
    expect(q(".q-sheet")).toBeNull();
    expect(q(".q-toast")?.textContent).toContain("You joined Sam's pair.");
    act(() => openTab("play"));
    expect(findBtn().textContent).toContain("Sam starts the search");
    expect((findBtn() as HTMLButtonElement).disabled).toBe(true);
    say(queued({ party_id: "p1", leader: false }));
    expect(button("Cancel", q(".q-bar")!)).toBeUndefined();
    expect(q(".q-bar")?.textContent).toContain("Sam leads");
    expect(button("Play with bots now")?.disabled).toBe(true);
  });

  it("an invite link opens the pair sheet with its code", async () => {
    window.history.replaceState(null, "", "/?party=7F2K");
    await renderApp();
    await settle();
    expect(q(".q-sheet h2")?.textContent).toBe("Queue with a friend");
    expect((q("#q-join-code") as HTMLInputElement).value).toBe("7F2K");
    expect(window.location.search).toBe("");
    expect(sentTypes()).not.toContain("party_create");
  });
});

describe("away from the app", () => {
  it("a drop while the socket was gone: the notice on return", async () => {
    await renderApp();
    say(queued());
    fakeClock();
    act(() => ws().close());
    tick(600);                 // the reconnect backoff
    act(() => ws().onopen?.());
    expect(q(".q-bar")).not.toBeNull();      // the server may still hand it back
    tick(3000);
    expect(q(".q-bar")).toBeNull();
    expect(q(".q-toast")?.textContent).toContain("You left the queue while away.");
  });

  it("a socket back in time gets its entry back and no notice", async () => {
    await renderApp();
    say(queued());
    fakeClock();
    act(() => ws().close());
    tick(600);
    act(() => ws().onopen?.());
    say(queued());
    tick(3000);
    expect(q(".q-bar")).not.toBeNull();
    expect(q(".q-toast")).toBeNull();
  });

  it("the server's away removal says so too", async () => {
    await renderApp();
    say(queued());
    say({ type: "queue_removed", reason: "away", cooldown_until: null });
    expect(q(".q-toast")?.textContent).toContain("You left the queue while away.");
    expect(q(".q-bar")).toBeNull();
    expect((findBtn() as HTMLButtonElement).disabled).toBe(false);   // no cooldown
  });
});

describe("the table", () => {
  const player = (seat: number) => ({
    seat, name: `P${seat}`, is_bot: false, connected: true, team: seat % 2, cards_left: 3, is_banker: seat === 1,
    takeover_in: null, controller: "human", reserved_for: null, reserved_secs: null,
  });
  const state = (matched: boolean) => ({
    type: "state", room: "ABCD", you: 0, phase: "play", ...(matched ? { matched: true } : {}),
    players: [0, 1, 2, 3].map(player), hand: [{ id: 1, code: "S5" }], levels: ["2", "2"], games_won: [0, 0],
    banker: 1, trump: { suit: "S", rank: "2", declarer: 1 }, turn: 1, declare_options: [],
    current_declaration: null, passed: [], trick: { leader: 1, plays: [] }, last_trick: null,
    attacker_points: 0, kitty_count: 8, message: null, notice: null, round_result: null,
  });

  it("a matched room says Matched game · rated; an invite room does not", async () => {
    await renderApp();
    say({ type: "match_started", match_id: "m1", room: "ABCD", rated: true });
    say(state(true));
    expect(q(".table-screen .q-matched")?.textContent).toBe("Matched game · rated");
    say(state(false));
    expect(q(".q-matched")).toBeNull();
  });
});

describe("one code for rooms and pairs", () => {
  const typeInto = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  };
  const playBox = () => q("input[aria-label='Game or pair code']") as HTMLInputElement;
  const playJoin = () => click(button(/^Join$/, q(".join-row")!));
  const pairParty = (code: string) => ({
    type: "party", party_id: "p9", code, you_lead: false, expires_at: nowSecs() + 300,
    members: [{ name: "Sam", leader: true, you: false }, { name: "Jerry", leader: false, you: true }],
  });
  const seats = (room: string) => ({
    type: "room_seats", room, in_game: false,
    seats: [{ seat: 0, name: "Host", is_bot: false, connected: true, team: 0, claimable: false,
              controller: "human", reserved_secs: null }],
  });
  let clipboard: string[];
  beforeEach(() => {
    clipboard = [];
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: (t: string) => { clipboard.push(t); return Promise.resolve(); } },
    });
  });

  it("the Play box joins a room code through the room flow", async () => {
    await renderApp();
    typeInto(playBox(), "wxyz");
    playJoin();
    expect(lastSent()).toEqual({ type: "code_lookup", code: "WXYZ" });
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    expect(lastSent()).toEqual({ type: "peek_room", room: "WXYZ" });
    say(seats("WXYZ"));
    expect(lastSent()).toMatchObject({ type: "join_room", room: "WXYZ", name: "Jerry" });
  });

  it("the Play box joins a pair code: the pair chip and the toast", async () => {
    await renderApp();
    typeInto(playBox(), "7F2K");
    playJoin();
    say({ type: "code_kind", code: "7F2K", kind: "party" });
    expect(lastSent()).toEqual({ type: "party_join", code: "7F2K" });
    expect(sentTypes()).not.toContain("peek_room");
    say(pairParty("7F2K"));
    expect(q(".q-party-chip")?.textContent).toContain("You + Sam");
    expect(q(".q-toast")?.textContent).toContain("You joined Sam's pair.");
    expect(button(/^Join$/, q(".join-row")!)?.disabled).toBe(false);
  });

  it("a code that names nothing says so in the Play box and the pair sheet", async () => {
    await renderApp();
    typeInto(playBox(), "ZZZZ");
    playJoin();
    say({ type: "code_kind", code: "ZZZZ", kind: "none" });
    expect(q(".lobby-error")?.textContent).toBe("No game or pair has that code.");
    expect(sentTypes()).not.toContain("peek_room");
    expect(sentTypes()).not.toContain("party_join");
    click(findBtn());
    click(button(/^With a friend…/));
    typeInto(q("#q-join-code") as HTMLInputElement, "ZZZZ");
    click(button("Join", q(".q-join")!));
    say({ type: "code_kind", code: "ZZZZ", kind: "none" });
    expect(q(".q-sheet .q-error")?.textContent).toBe("No game or pair has that code.");
  });

  it("a guest who types a pair code is asked to sign in, then lands on the pair sheet", async () => {
    signedIn = false;
    await renderApp();
    typeInto(playBox(), "7F2K");
    playJoin();
    expect(lastSent()).toEqual({ type: "code_lookup", code: "7F2K" });
    say({ type: "code_kind", code: "7F2K", kind: "party" });
    expect(sentTypes()).not.toContain("party_join");
    const sheet = q(".q-sheet")!;
    expect(button("Sign in to play people", sheet)).toBeDefined();
    expect(sheet.textContent).toContain("Pair code 7F2K is for signed-in players.");
    click(button("Sign in to play people", sheet));
    expect(window.location.hash).toBe("#/me");
  });

  it("the pair sheet's box says it takes either, and a game code closes it and opens the room", async () => {
    await renderApp();
    const { openTab } = await import("../home/route");
    act(() => openTab("me"));
    await settle();
    click(button(/^Queue with a friend/));
    expect(q(".q-join-label")?.textContent).toContain("A pair code or a game code");
    typeInto(q("#q-join-code") as HTMLInputElement, "wxyz");
    click(button("Join", q(".q-join")!));
    expect(lastSent()).toEqual({ type: "code_lookup", code: "WXYZ" });
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    await settle();
    expect(q(".q-sheet")).toBeNull();
    expect(window.location.hash).toBe("");
    expect(lastSent()).toEqual({ type: "peek_room", room: "WXYZ" });
    say(seats("WXYZ"));
    expect(lastSent()).toMatchObject({ type: "join_room", room: "WXYZ" });
  });

  it("a ?code= link for a room prefills Join and waits for the player", async () => {
    window.history.replaceState(null, "", "/?code=wxyz");
    await renderApp();
    expect(lastSent()).toEqual({ type: "code_lookup", code: "WXYZ" });
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    await settle();
    expect(playBox().value).toBe("WXYZ");
    expect(sentTypes()).not.toContain("join_room");
    expect(sentTypes()).not.toContain("peek_room");
  });

  it("a ?code= link for a room with a name joins it, as ?room= does", async () => {
    signedIn = false;
    window.history.replaceState(null, "", "/?code=WXYZ&name=Ann");
    await renderApp();
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    await settle();
    expect(lastSent()).toEqual({ type: "join_room", room: "WXYZ", name: "Ann" });
  });

  it("a ?code= link for a pair opens the pair sheet with its code", async () => {
    window.history.replaceState(null, "", "/?code=7F2K");
    await renderApp();
    expect(lastSent()).toEqual({ type: "code_lookup", code: "7F2K" });
    say({ type: "code_kind", code: "7F2K", kind: "party" });
    await settle();
    expect(q(".q-sheet h2")?.textContent).toBe("Queue with a friend");
    expect((q("#q-join-code") as HTMLInputElement).value).toBe("7F2K");
    expect(window.location.search).toBe("");
    expect(sentTypes()).not.toContain("party_join");
  });

  it("a ?code= link that names nothing says so", async () => {
    window.history.replaceState(null, "", "/?code=ZZZZ");
    await renderApp();
    say({ type: "code_kind", code: "ZZZZ", kind: "none" });
    await settle();
    expect(q(".lobby-error")?.textContent).toBe("No game or pair has that code.");
    expect(window.location.search).toBe("");
  });

  it("an old ?room= link still prefills Join without a lookup", async () => {
    window.history.replaceState(null, "", "/?room=WXYZ");
    await renderApp();
    expect(playBox().value).toBe("WXYZ");
    expect(sentTypes()).not.toContain("code_lookup");
  });

  it("share links are ?code= links, for a pair and for a room", async () => {
    Object.defineProperty(navigator, "share", { configurable: true, value: undefined });
    await renderApp();
    click(findBtn());
    click(button(/^With a friend…/));
    say({ type: "party", party_id: "p1", code: "7F2K", you_lead: true, expires_at: nowSecs() + 300,
          members: [{ name: "Jerry", leader: true, you: true }] });
    click(button("Share invite link"));
    await settle();
    expect(clipboard).toEqual([`${window.location.origin}/?code=7F2K`]);
    click(button("Cancel", q(".q-sheet")!));
    say({ type: "room", room: "WXYZ", you: 0, host: 0, start_level: "2",
          players: [{ seat: 0, name: "Jerry", is_bot: false, connected: true }] });
    click(q(".room-code"));
    await settle();
    expect(clipboard.at(-1)).toBe(`${window.location.origin}/?code=WXYZ`);
  });
});

describe("a code lookup that is interrupted or refused", () => {
  const typeInto = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  };
  const lookups = () => FakeWS.all.flatMap((w) => w.sent).filter((m) => m.type === "code_lookup");
  const LIMITED = { type: "error", code: "rate_limited", message: "Too many requests; wait a minute." };
  const reconnect = () => {
    fakeClock();
    act(() => ws().close());
    tick(600);                 // the reconnect backoff
    act(() => ws().onopen?.());
    vi.useRealTimers();
  };

  it("a ?code= link whose lookup died with the socket is asked once more, then joins", async () => {
    signedIn = false;
    window.history.replaceState(null, "", "/?code=WXYZ&name=Ann");
    await renderApp();
    expect(lookups()).toHaveLength(1);
    reconnect();
    await settle();
    expect(lookups()).toHaveLength(2);
    expect(ws().sent).toEqual([{ type: "code_lookup", code: "WXYZ" }]);
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    await settle();
    expect(lastSent()).toEqual({ type: "join_room", room: "WXYZ", name: "Ann" });
  });

  it("a ?code= link already answered and joined is not looked up or joined again on reconnect", async () => {
    signedIn = false;
    window.history.replaceState(null, "", "/?code=WXYZ&name=Ann");
    await renderApp();
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    await settle();
    const joins = () => FakeWS.all.flatMap((w) => w.sent).filter((m) => m.type === "join_room");
    expect(joins()).toHaveLength(1);
    reconnect();
    await settle();
    expect(lookups()).toHaveLength(1);
    expect(joins()).toHaveLength(1);
  });

  it("a rate-limited Play lookup says so under the Play box", async () => {
    await renderApp();
    typeInto(q("input[aria-label='Game or pair code']") as HTMLInputElement, "WXYZ");
    click(button(/^Join$/, q(".join-row")!));
    say(LIMITED);
    expect(q(".lobby-error")?.textContent).toBe("Too many requests; wait a minute.");
    expect(button(/^Join$/, q(".join-row")!)?.disabled).toBe(false);
  });

  it("a rate-limited ?code= lookup says so under the Play box", async () => {
    window.history.replaceState(null, "", "/?code=WXYZ");
    await renderApp();
    say(LIMITED);
    await settle();
    expect(q(".lobby-error")?.textContent).toBe("Too many requests; wait a minute.");
  });

  it("a rate-limited pair-sheet lookup says so in the sheet", async () => {
    await renderApp();
    click(findBtn());
    click(button(/^With a friend…/));
    typeInto(q("#q-join-code") as HTMLInputElement, "WXYZ");
    click(button("Join", q(".q-join")!));
    say(LIMITED);
    expect(q(".q-sheet .q-error")?.textContent).toBe("Too many requests; wait a minute.");
  });

  it("an unrelated error while a lookup waits does not cancel it", async () => {
    await renderApp();
    typeInto(q("input[aria-label='Game or pair code']") as HTMLInputElement, "WXYZ");
    click(button(/^Join$/, q(".join-row")!));
    say({ type: "error", code: "room_full", message: "Room is full." });
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    expect(lastSent()).toEqual({ type: "peek_room", room: "WXYZ" });
  });
});

describe("a pair-sheet lookup the player walks away from", () => {
  const typeInto = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  };
  const openPairSheet = () => {
    click(findBtn());
    click(button(/^With a friend…/));
  };
  const pairJoinButton = () => q(".q-join button[type='submit']") as HTMLButtonElement;
  const askInSheet = (code: string) => {
    typeInto(q("#q-join-code") as HTMLInputElement, code);
    click(pairJoinButton());
    expect(lastSent()).toEqual({ type: "code_lookup", code });
  };
  const LIMITED = { type: "error", code: "rate_limited", message: "Too many requests; wait a minute." };

  it("Cancel, then a late pair answer: no party_join and nothing shown", async () => {
    await renderApp();
    openPairSheet();
    askInSheet("FG3K");
    click(button("Cancel", q(".q-sheet")!));
    expect(q(".q-sheet")).toBeNull();
    say({ type: "code_kind", code: "FG3K", kind: "party" });
    expect(sentTypes()).not.toContain("party_join");
    expect(q(".q-sheet")).toBeNull();
    expect(q(".q-error")).toBeNull();
  });

  it("a tap on the scrim, then a late room answer: no Play tab, no peek, no join", async () => {
    await renderApp();
    const { openTab } = await import("../home/route");
    act(() => openTab("me"));
    await settle();
    click(button(/^Queue with a friend/));
    askInSheet("WXYZ");
    click(q(".q-scrim"));
    expect(q(".q-sheet")).toBeNull();
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    await settle();
    expect(window.location.hash).toBe("#/me");
    expect(sentTypes()).not.toContain("peek_room");
    expect(sentTypes()).not.toContain("join_room");
  });

  it("Escape, then a late answer of either kind: nothing happens", async () => {
    await renderApp();
    openPairSheet();
    askInSheet("FG3K");
    act(() => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); });
    expect(q(".q-sheet")).toBeNull();
    say({ type: "code_kind", code: "FG3K", kind: "party" });
    await settle();
    expect(sentTypes()).not.toContain("party_join");
    expect(sentTypes()).not.toContain("peek_room");
  });

  it("a new lookup after a cancel is answered and joins", async () => {
    await renderApp();
    openPairSheet();
    askInSheet("FG3K");
    click(button("Cancel", q(".q-sheet")!));
    openPairSheet();
    askInSheet("AB12");
    say({ type: "code_kind", code: "FG3K", kind: "party" });    // the cancelled one's answer
    expect(sentTypes()).not.toContain("party_join");
    say({ type: "code_kind", code: "AB12", kind: "party" });
    expect(lastSent()).toEqual({ type: "party_join", code: "AB12" });
    expect(FakeWS.all.flatMap((w) => w.sent).filter((m) => m.type === "party_join")).toHaveLength(1);
  });

  it("the pair sheet's Join says Joining… and holds while the lookup waits; a refusal frees it", async () => {
    await renderApp();
    openPairSheet();
    askInSheet("WXYZ");
    expect(pairJoinButton().textContent).toBe("Joining…");
    expect(pairJoinButton().disabled).toBe(true);
    expect(pairJoinButton().getAttribute("aria-busy")).toBe("true");
    say(LIMITED);
    expect(pairJoinButton().textContent).toBe("Join");
    expect(pairJoinButton().disabled).toBe(false);
  });

  it("the pair sheet's Join is freed when the socket drops", async () => {
    await renderApp();
    openPairSheet();
    askInSheet("WXYZ");
    act(() => ws().close());
    expect(pairJoinButton().textContent).toBe("Join");
    expect(pairJoinButton().disabled).toBe(false);
  });

  it("the Play box's Join holds while its lookup waits, past an unrelated error, and a drop frees it", async () => {
    await renderApp();
    typeInto(q("input[aria-label='Game or pair code']") as HTMLInputElement, "WXYZ");
    const playJoin = () => q(".join-row button") as HTMLButtonElement;
    click(playJoin());
    expect(playJoin().textContent).toBe("Joining…");
    expect(playJoin().disabled).toBe(true);
    say({ type: "error", code: "room_full", message: "Room is full." });
    expect(playJoin().textContent).toBe("Joining…");
    expect(playJoin().disabled).toBe(true);
    say(LIMITED);
    expect(playJoin().disabled).toBe(false);
    click(playJoin());
    act(() => ws().close());
    expect(playJoin().textContent).toBe("Join");
  });
});
