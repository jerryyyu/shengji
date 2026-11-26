// One connection surface: a dropped socket shows the pill at a table or in a
// game (Play with no table says it on its presence line), Retry joins it after RETRY_AFTER_MS, one full screen
// takes over after LOST_AFTER_MS, and a reconnect clears all of it while the
// saved seat is resumed exactly as before. The iOS app's full screen also
// offers its bots on the device; a browser's offers Retry alone.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, onTestFinished, vi } from "vitest";

class FakeWS {
  static OPEN = 1;
  static all: FakeWS[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: { type: string; room?: string; token?: string }[] = [];
  readyState = 0;
  constructor() { FakeWS.all.push(this); }
  send(raw: string) { this.sent.push(JSON.parse(raw)); }
  open() { this.readyState = 1; this.onopen?.(); }
  close() { this.readyState = 3; this.onclose?.(); }
  deliver(msg: unknown) { this.onmessage?.({ data: JSON.stringify(msg) }); }
}

const player = (seat: number) => ({
  seat, name: seat ? `Bot ${seat}` : "Me", is_bot: seat !== 0, connected: true, team: seat % 2,
  cards_left: 25, is_banker: seat === 1, takeover_in: null, controller: seat ? "bot" : "human",
  reserved_for: null, reserved_secs: null,
});
const playing = {
  type: "state", room: "ABCD", you: 0, phase: "play",
  players: [0, 1, 2, 3].map(player),
  hand: [{ id: 1, code: "S6" }, { id: 2, code: "D9" }], levels: ["2", "2"], games_won: [0, 0], banker: 1,
  trump: { suit: "H", rank: "2", declarer: 1 }, turn: 0, declare_options: [],
  current_declaration: null, passed: [], trick: { leader: 1, plays: [{ seat: 1, cards: ["DA"] }] },
  last_trick: null, attacker_points: 0, kitty_count: 8, message: null, notice: null, round_result: null,
};

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const realLocation = window.location;
const assign = vi.fn();
beforeEach(() => {
  vi.useFakeTimers();
  FakeWS.all = [];
  assign.mockReset();
  localStorage.clear();
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  Object.defineProperty(window, "location", { configurable: true, value: { ...realLocation, assign, search: "" } });
  // inside the iOS app, unless a test says otherwise
  (window as unknown as { Capacitor: unknown }).Capacitor = {
    isNativePlatform: () => true,
    registerPlugin: () => new Proxy({}, { get: () => () => Promise.resolve(undefined) }),
  };
  vi.resetModules();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
  delete (window as unknown as { Capacitor?: unknown }).Capacitor;
  vi.useRealTimers();
});

async function mount() {
  const { default: App } = await import("./App");
  const ws = await import("./ws");
  const pill = await import("./components/ConnectionPill");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<App />));
  return { ws, ...pill };
}
const latest = () => FakeWS.all[FakeWS.all.length - 1];
const banner = () => host.querySelector<HTMLElement>(".reconnect-banner");
const retryIn = () => host.querySelector<HTMLButtonElement>(".reconnect-banner .reconnect-retry");
const lost = () => host.querySelector<HTMLElement>(".conn-lost");
// After a long outage the page is between attempts: a connect that never
// opened is abandoned, and the next one follows its backoff. The network
// comes back on the next attempt.
const recover = () => {
  for (let i = 0; i < 40 && !(latest().readyState === 0 && latest().onopen); i++) {
    act(() => { vi.advanceTimersByTime(250); });
  }
  act(() => latest().open());
};

it("at the table the full screen comes 30 s after the drop, when the server's seat hold ends: the pill alone at 29 s", async () => {
  const { LOST_AFTER_MS } = await mount();
  // the same window as server.py TAKEOVER_AFTER (pinned by test_client_server_constants.py)
  expect(LOST_AFTER_MS).toBe(30_000);
  act(() => latest().open());
  act(() => latest().deliver({ type: "resume", room: "ABCD", token: "tok-1" }));
  act(() => latest().deliver(playing));
  act(() => latest().close());
  act(() => { vi.advanceTimersByTime(29_000); });
  expect(lost()).toBeNull();
  expect(banner()?.textContent).toContain("Reconnecting…");
  expect(retryIn()?.textContent).toBe("Retry");
  expect(host.querySelector(".table-screen")).not.toBeNull();
  act(() => { vi.advanceTimersByTime(999); });
  expect(lost()).toBeNull();
  act(() => { vi.advanceTimersByTime(1); });
  expect(banner()).toBeNull();
  expect(lost()?.querySelector("h1")?.textContent).toBe("No connection");
  expect(lost()?.textContent).toContain("A bot holds your seat.");
});

it("at the table a drop shows the pill, Retry at 10 s, the full screen at 30 s, and a reconnect resumes the seat and clears it", async () => {
  const { ws, RETRY_AFTER_MS, LOST_AFTER_MS } = await mount();
  ws.saveName("Me");
  act(() => latest().open());
  act(() => latest().deliver({ type: "resume", room: "ABCD", token: "tok-1" }));
  act(() => latest().deliver(playing));
  ws.saveRoom("ABCD");
  expect(host.querySelector(".table-screen")).not.toBeNull();
  expect(banner()).toBeNull();

  act(() => latest().close());
  expect(banner()?.textContent).toBe("Reconnecting…");
  expect(retryIn()).toBeNull();
  expect(host.querySelectorAll(".reconnect-banner, .table-stalled, .play-conn")).toHaveLength(1);
  // the socket's own backoff keeps trying underneath; none of those tries opens
  act(() => { vi.advanceTimersByTime(RETRY_AFTER_MS - 1); });
  expect(retryIn()).toBeNull();
  act(() => { vi.advanceTimersByTime(1); });
  expect(retryIn()?.textContent).toBe("Retry");
  expect(host.querySelector(".table-screen")).not.toBeNull();

  // Retry opens a new socket at once and starts the wait over
  const before = FakeWS.all.length;
  act(() => retryIn()!.click());
  act(() => { vi.advanceTimersByTime(0); });
  expect(FakeWS.all.length).toBeGreaterThan(before);
  expect(retryIn()).toBeNull();
  expect(banner()?.textContent).toBe("Reconnecting…");

  act(() => { vi.advanceTimersByTime(LOST_AFTER_MS); });
  expect(banner()).toBeNull();
  expect(lost()?.querySelector("h1")?.textContent).toBe("No connection");
  expect(lost()?.textContent).toContain("A bot holds your seat.");
  // in a game too, the full screen offers the bots on this device
  expect(host.querySelector(".conn-lost-bots")?.textContent).toBe("Play offline with the bots");
  expect(host.querySelector(".conn-lost-retry")?.textContent).toBe("Retry");

  // back online: the saved seat is asked for by its token, and every surface
  // clears; the full screen can land as a connect attempt is cut, so the
  // next live attempt is the one that opens
  for (let i = 0; i < 100 && latest().onopen === null; i++) act(() => { vi.advanceTimersByTime(100); });
  const back = latest();
  act(() => back.open());
  expect(back.sent).toEqual([expect.objectContaining({ type: "table_join", code: "ABCD", expect: "room", token: "tok-1" })]);
  expect(lost()).toBeNull();
  expect(banner()).toBeNull();
  act(() => back.deliver(playing));
  expect(host.querySelector(".table-screen")).not.toBeNull();
});

it("on Play with no table the presence line is the status, no pill, and the full screen offers Retry and bots on this device", async () => {
  const { LOST_AFTER_MS } = await mount();
  // the first connect of a page is not a drop
  expect(banner()).toBeNull();
  expect(host.querySelector(".play-presence")?.textContent).toBe("Connecting…");
  act(() => latest().open());
  expect(banner()).toBeNull();
  expect(host.querySelector(".play-tab")).not.toBeNull();
  expect(host.querySelector(".play-presence")?.textContent).not.toBe("Connecting…");

  act(() => latest().close());
  expect(banner()).toBeNull();
  expect(host.querySelector(".play-presence")?.textContent).toBe("Connecting…");
  expect(host.querySelector(".play-conn")).toBeNull();          // no second status row in the lobby
  act(() => { vi.advanceTimersByTime(LOST_AFTER_MS); });
  expect(banner()).toBeNull();
  expect(host.querySelectorAll(".play-presence")).toHaveLength(1);
  expect(host.querySelector(".play-presence")?.textContent).toBe("Offline");
  expect(lost()).not.toBeNull();
  expect(lost()?.textContent).not.toContain("A bot holds your seat");

  // Retry from the full screen starts the wait over, with no pill on Play
  act(() => host.querySelector<HTMLButtonElement>(".conn-lost-retry")!.click());
  expect(lost()).toBeNull();
  expect(banner()).toBeNull();
  act(() => { vi.advanceTimersByTime(LOST_AFTER_MS); });
  const offline = host.querySelector<HTMLButtonElement>(".conn-lost-bots")!;
  expect(offline.textContent).toBe("Play offline with the bots");

  recover();
  expect(lost()).toBeNull();
  expect(banner()).toBeNull();
});

it("the full screen's Play offline with the bots opens the offline table on this page, with no reload", async () => {
  const { LOST_AFTER_MS } = await mount();
  act(() => latest().open());
  act(() => latest().close());
  act(() => { vi.advanceTimersByTime(LOST_AFTER_MS); });
  const sockets = FakeWS.all.length;
  const dropped = latest();
  act(() => host.querySelector<HTMLButtonElement>(".conn-lost-bots")!.click());
  await vi.waitFor(async () => {
    await act(async () => { vi.advanceTimersByTime(10); });
    expect(host.querySelector(".tp-offline")).not.toBeNull();
  });
  expect(assign).not.toHaveBeenCalled();
  expect(lost()).toBeNull();
  expect(banner()).toBeNull();
  expect(host.querySelector(".tp-offline .tp-title")?.textContent).toBe("You and 3 bots");
  // the network's backoff stops: no new socket to the game server, and a late open of the old one is cut off
  act(() => { vi.advanceTimersByTime(30_000); });
  expect(FakeWS.all.length).toBe(sockets);
  act(() => dropped.open());
  expect(dropped.sent).toEqual([]);
});

it("a short blip clears before Retry ever shows", async () => {
  const { RETRY_AFTER_MS } = await mount();
  act(() => latest().open());
  act(() => latest().close());
  act(() => { vi.advanceTimersByTime(600); });
  act(() => latest().open());
  expect(banner()).toBeNull();
  act(() => { vi.advanceTimersByTime(RETRY_AFTER_MS * 7); });
  expect(banner()).toBeNull();
  expect(lost()).toBeNull();
});

const tab = (shift = false) => act(() => {
  (document.activeElement ?? document.body).dispatchEvent(
    new KeyboardEvent("keydown", { key: "Tab", shiftKey: shift, bubbles: true, cancelable: true }));
});
const focusables = () => [...host.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), a[href]")];

it("the full screen is modal: Retry has focus, Tab stays inside, the page behind is inert, and recovery gives focus back", async () => {
  const { LOST_AFTER_MS } = await mount();
  act(() => latest().open());
  const howto = [...host.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent === "How to play")!;
  act(() => howto.focus());
  act(() => latest().close());
  act(() => { vi.advanceTimersByTime(LOST_AFTER_MS); });

  const modal = lost()!;
  const retry = modal.querySelector<HTMLButtonElement>(".conn-lost-retry")!;
  const bots = modal.querySelector<HTMLButtonElement>(".conn-lost-bots")!;
  expect(modal.tagName).toBe("DIALOG");
  expect(modal.hasAttribute("open")).toBe(true);
  expect(document.activeElement).toBe(retry);
  // Tab and Shift+Tab wrap at its ends (between them the browser moves focus)
  tab(true);
  expect(document.activeElement).toBe(bots);
  tab();
  expect(document.activeElement).toBe(retry);
  // every control outside it sits under an inert ancestor
  const outside = focusables().filter((el) => !modal.contains(el));
  expect(outside.length).toBeGreaterThan(0);
  expect(outside.every((el) => el.closest("[inert]") !== null)).toBe(true);
  expect(modal.closest("[inert]")).toBeNull();
  // Escape does not dismiss it
  act(() => { document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })); });
  expect(lost()).not.toBeNull();

  recover();
  expect(lost()).toBeNull();
  expect(host.querySelector("[inert]")).toBeNull();
  expect(document.activeElement).toBe(howto);
});

it("Retry from the full screen gives focus back too, and Tab stays inside its two buttons at the table", async () => {
  const { ws, LOST_AFTER_MS } = await mount();
  ws.saveName("Me");
  act(() => latest().open());
  act(() => latest().deliver(playing));
  const more = host.querySelector<HTMLButtonElement>(".hud-more-btn")!;
  act(() => more.focus());
  act(() => latest().close());
  act(() => { vi.advanceTimersByTime(LOST_AFTER_MS); });
  const retry = lost()!.querySelector<HTMLButtonElement>(".conn-lost-retry")!;
  const bots = lost()!.querySelector<HTMLButtonElement>(".conn-lost-bots")!;
  expect(document.activeElement).toBe(retry);
  // Tab and Shift+Tab wrap at its ends (between them the browser moves focus)
  tab(true);
  expect(document.activeElement).toBe(bots);
  tab();
  expect(document.activeElement).toBe(retry);
  act(() => retry.click());
  expect(lost()).toBeNull();
  expect(document.activeElement).toBe(more);
});

it("with a sheet already open, the full screen sits above it and Retry is reachable", async () => {
  const { LOST_AFTER_MS } = await mount();
  act(() => latest().open());
  act(() => host.querySelector<HTMLButtonElement>(".guest-pill")!.click());
  const sheet = host.querySelector<HTMLElement>(".q-sheet")!;
  expect(sheet).not.toBeNull();
  expect(sheet.contains(document.activeElement)).toBe(true);
  act(() => latest().close());
  act(() => { vi.advanceTimersByTime(LOST_AFTER_MS); });

  const modal = lost()!;
  const retry = modal.querySelector<HTMLButtonElement>(".conn-lost-retry")!;
  expect(document.activeElement).toBe(retry);
  expect(sheet.closest("[inert]")).not.toBeNull();
  // the sheet's own Tab trap and Escape never see keys pressed in the modal
  tab();
  expect(modal.contains(document.activeElement)).toBe(true);
  tab();
  expect(document.activeElement).toBe(retry);
  act(() => { retry.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })); });
  expect(host.querySelector(".q-sheet")).not.toBeNull();
  expect(document.activeElement).toBe(retry);

  recover();
  expect(lost()).toBeNull();
  expect(sheet.closest("[inert]")).toBeNull();
  expect(sheet.contains(document.activeElement)).toBe(true);
});

it("with the leave sheet open at the table, the full screen still takes focus", async () => {
  const { ws, LOST_AFTER_MS } = await mount();
  ws.saveName("Me");
  act(() => latest().open());
  act(() => latest().deliver(playing));
  act(() => host.querySelector<HTMLButtonElement>(".hud-more-btn")!.click());
  act(() => host.querySelector<HTMLButtonElement>(".hud-menu-row.leave")!.click());
  const alert = host.querySelector<HTMLElement>(".leave-sheet-backdrop")!;
  expect(alert.contains(document.activeElement)).toBe(true);
  act(() => latest().close());
  act(() => { vi.advanceTimersByTime(LOST_AFTER_MS); });
  const retry = lost()!.querySelector<HTMLButtonElement>(".conn-lost-retry")!;
  expect(document.activeElement).toBe(retry);
  expect(alert.closest("[inert]")).not.toBeNull();
});

it("a seat taken in a game already on is saved from its first state, so a reconnect resumes it by its token", async () => {
  // a mid-game seat gets no "room" frame: the device remembers it by its first state
  const { ws } = await mount();
  ws.saveName("Cee");
  act(() => latest().open());
  expect(latest().sent).toEqual([]);
  // watching the seat until the handover is not holding it yet
  act(() => latest().deliver({ ...playing, you: 2, joining_you: true }));
  expect(ws.getSavedRoom()).toBeNull();
  act(() => latest().deliver({ type: "resume", token: "tok-mid", gen: 1 }));
  act(() => latest().deliver({ ...playing, you: 2 }));
  expect(ws.getSavedRoom()).toBe("ABCD");
  expect(host.querySelector(".table-screen")).not.toBeNull();

  act(() => latest().close());
  act(() => { vi.advanceTimersByTime(600); });
  const back = latest();
  act(() => back.open());
  expect(back.sent).toEqual([expect.objectContaining({ type: "table_join", code: "ABCD", expect: "room", token: "tok-mid" })]);
  act(() => back.deliver({ type: "resume", token: "tok-mid", gen: 2 }));
  act(() => back.deliver({ ...playing, you: 2 }));
  expect(host.querySelector(".table-screen")).not.toBeNull();
});

it("a move refused for want of a seat asks for the seat back once, then goes to Play with one toast", async () => {
  const { ws } = await mount();
  ws.saveName("Cee");
  act(() => latest().open());
  act(() => latest().deliver({ type: "resume", token: "tok-mid", gen: 1 }));
  act(() => latest().deliver({ ...playing, you: 2 }));
  const sock = latest();
  act(() => sock.deliver({ type: "error", code: "no_room", message: "Join a room first." }));
  expect(sock.sent.at(-1)).toEqual(expect.objectContaining({ type: "table_join", code: "ABCD", token: "tok-mid" }));
  expect(host.querySelector(".table-screen")).not.toBeNull();
  // moves sent before the refusal arrived are refused too: they are not the
  // ask's answer, so the table stays and nothing more is asked
  const asked = sock.sent.length;
  act(() => sock.deliver({ type: "error", code: "no_room", message: "Join a room first." }));
  act(() => sock.deliver({ type: "error", code: "no_room", message: "Join a room first." }));
  expect(sock.sent.length).toBe(asked);
  expect(host.querySelector(".table-screen")).not.toBeNull();
  // the ask itself is refused: the table goes at once
  act(() => sock.deliver({ type: "error", code: "seat_unavailable", message: "That seat was just taken." }));
  expect(sock.sent.length).toBe(asked);
  expect(host.querySelector(".table-screen")).toBeNull();
  expect(host.querySelector(".lobby-panel")).not.toBeNull();
  expect(host.querySelectorAll(".toast")).toHaveLength(1);
  expect(host.querySelector(".toast")?.textContent).toBe("You're no longer at a table.");
  expect(ws.getSavedRoom()).toBeNull();
});

it("in a browser the full screen offers Retry alone, and Play keeps its own controls, disabled", async () => {
  delete (window as unknown as { Capacitor?: unknown }).Capacitor;
  const { LOST_AFTER_MS } = await mount();
  act(() => latest().open());
  act(() => latest().close());
  act(() => { vi.advanceTimersByTime(LOST_AFTER_MS); });
  expect(lost()?.querySelector("h1")?.textContent).toBe("No connection");
  expect([...lost()!.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["Retry"]);
  expect(host.querySelector(".play-offline")).toBeNull();
  expect(host.querySelector(".play-presence")?.textContent).toBe("Connecting…");
  expect(host.textContent).not.toMatch(/Play offline/);
  recover();
  expect(lost()).toBeNull();
});

// An owed Leave with App's own open-time resume in the loop: the page leaves
// only its own seat, and nothing App does on that socket undoes the Leave.
const seatedAtABCD = async () => {
  const m = await mount();
  m.ws.saveName("Me");
  act(() => latest().open());
  act(() => latest().deliver({ type: "resume", token: "tok-1", gen: 1 }));
  act(() => latest().deliver(playing));
  expect(m.ws.getSavedRoom()).toBe("ABCD");
  return m;
};
const resumeThenLeave = [
  { type: "table_join", code: "ABCD", name: "Me", expect: "room", token: "tok-1" },
  { type: "table_leave" },
];
const otherTabSits = () => {
  localStorage.setItem("shengji.room", "BBBB");
  localStorage.setItem("shengji.token", "tok-B");
};

it("the socket that delivers an owed Leave resumes no other tab's saved seat, and its left keeps that seat", async () => {
  const { ws } = await seatedAtABCD();
  act(() => latest().close());
  otherTabSits();
  act(() => { ws.conn.send({ type: "table_leave" }); });
  expect(host.querySelector(".table-screen")).toBeNull();
  act(() => { vi.advanceTimersByTime(500); });
  const next = latest();
  act(() => next.open());
  expect(next.sent).toEqual(resumeThenLeave);
  act(() => next.deliver({ type: "left" }));
  expect(ws.getSavedRoom()).toBe("BBBB");
  expect(ws.getResumeToken()).toBe("tok-B");
});

it("the server's left for a Leave on an open socket keeps the seat another tab saved since", async () => {
  const { ws } = await seatedAtABCD();
  otherTabSits();
  act(() => { ws.conn.send({ type: "table_leave" }); });
  act(() => latest().deliver({ type: "left" }));
  expect(host.querySelector(".table-screen")).toBeNull();
  expect(ws.getSavedRoom()).toBe("BBBB");
  expect(ws.getResumeToken()).toBe("tok-B");
});

it("an owed Leave past its hold, reopened later, still does not resume the seat it left", async () => {
  const { ws } = await seatedAtABCD();
  act(() => { ws.conn.send({ type: "table_leave" }); });   // sent; the page closes before the left
  act(() => { ws.conn.stop(); root.unmount(); });
  host.remove();
  act(() => { vi.advanceTimersByTime(91_000); });
  vi.resetModules();
  const again = await mount();
  act(() => latest().open());
  expect(latest().sent).toEqual([]);
  expect(again.ws.getSavedRoom()).toBeNull();
});

it("a reconnect whose owed Leave another page answered resumes no other tab's saved seat", async () => {
  const { ws } = await seatedAtABCD();
  act(() => latest().close());
  act(() => { ws.conn.send({ type: "table_leave" }); });
  otherTabSits();
  // another page on the same storage delivers the stored Leave and has it answered
  vi.resetModules();
  const other = await import("./ws");
  other.conn.start();
  const theirs = latest();
  act(() => theirs.open());
  expect(theirs.sent).toEqual(resumeThenLeave);
  act(() => theirs.deliver({ type: "left" }));
  act(() => { vi.advanceTimersByTime(500); });
  const mine = latest();
  expect(mine).not.toBe(theirs);
  act(() => mine.open());
  expect(mine.sent).toEqual([]);                         // no join BBBB
  expect(ws.getSavedRoom()).toBe("BBBB");
  other.conn.stop();
});

it("the round end fills in only for a result the socket that showed play delivered; a reconnect's open draws nothing live", async () => {
  const proto = HTMLDialogElement.prototype as unknown as Record<string, unknown>;
  const saved = { showModal: proto.showModal, close: proto.close };
  proto.showModal = function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
  proto.close = function (this: HTMLDialogElement) { this.removeAttribute("open"); };
  onTestFinished(() => { proto.showModal = saved.showModal; proto.close = saved.close; });
  const { ws } = await mount();
  ws.saveName("Me");
  // we bank at 5 (seat 0); they attack and climb one, to A; an older server sends no old_levels
  const banked = { ...playing, banker: 0, players: [0, 1, 2, 3].map((s) => ({ ...player(s), is_banker: s === 0 })),
                   trump: { suit: "H", rank: "5", declarer: 0 } };
  const at = (theirs: string) => ({ ...banked, levels: ["5", theirs] });
  const result = { ...banked, levels: ["5", "A"], phase: "round_end", turn: null, trick: null,
                   round_result: { attacker_points: 125, kitty_points: 0, kitty_cards: [], winner_team: 1, level_change: 1,
                                   next_banker: 1, new_levels: ["5", "A"], games_won: [0, 0], point_scored: false, game_over: false } };
  const theirs = () => {
    const lane = host.querySelector(".rank-lane.team1")!;
    return { was: lane.querySelector(".lane-cell.was")?.textContent ?? null, fill: lane.querySelector(".lane-cell.fill") !== null };
  };
  act(() => latest().open());
  act(() => latest().deliver({ type: "resume", room: "ABCD", token: "tok-1" }));
  ws.saveRoom("ABCD");

  // one socket: play at K, then the result
  act(() => latest().deliver(at("K")));
  act(() => latest().deliver(result));
  expect(theirs()).toEqual({ was: "K", fill: true });

  // the next round's play at Q, then the socket drops; the new socket opens (the table
  // renders again on that status) and its first frame, 150 ms later, is the result
  act(() => latest().deliver(at("Q")));
  act(() => latest().close());
  recover();
  act(() => { vi.advanceTimersByTime(150); });
  act(() => latest().deliver(result));
  expect(theirs()).toEqual({ was: null, fill: false });
});
