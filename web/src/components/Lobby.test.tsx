import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthState } from "../auth";
import { NAME_ADJECTIVES, NAME_NOUNS } from "../randomName";

const { sent, authState, signOut, updated, updateDisplayName, gis, reconnects, link } = vi.hoisted(() => ({
  sent: [] as unknown[],
  link: { generation: 0, listeners: new Set<(m: unknown) => void>() },
  reconnects: { n: 0 },
  authState: { current: { status: "loading", clientId: null, user: null } as AuthState },
  signOut: vi.fn(() => Promise.resolve()),
  updated: vi.fn(),
  updateDisplayName: vi.fn(),
  gis: { initialize: vi.fn(), renderButton: vi.fn(), disableAutoSelect: vi.fn() },
}));
vi.mock("../ws", () => ({
  conn: { send: (m: unknown) => { sent.push(m); return true; },
          subscribe: (fn: (m: unknown) => void) => { link.listeners.add(fn); return () => link.listeners.delete(fn); },
          get generation() { return link.generation; },
          reconnect: () => { reconnects.n += 1; } },
  getSavedName: () => localStorage.getItem("shengji.name") ?? "",
  saveName: (n: string) => localStorage.setItem("shengji.name", n),
  getResumeToken: () => null,
  clearSavedRoom: () => {},
  reconnect: () => {},
}));

vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return {
    ...real,
    useAuth: () => authState.current,
    loadGis: () => Promise.resolve(gis),
    updateDisplayName,
    auth: { signOut, signedIn: vi.fn(), init: vi.fn(), updated },
  };
});

import Lobby, { STALL_MS } from "./Lobby";
import { offlineGame } from "./offlineGame";
import { queue } from "../queue/store";
import { codes } from "../codeJoin";
import { guestName } from "../guestName";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

async function render() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => root.render(<Lobby status="open" error={null} onArmAutoFill={() => {}} />));
}
const NAME_FIELD = ".q-layer:not(.q-out) input[autocomplete='nickname']";
/** A guest's name field, in the editor their chip opens (opened here when
 *  shut); null for an account, which has no chip to open it. */
const nameInput = () => {
  const open = host.querySelector<HTMLInputElement>(NAME_FIELD);
  if (open) return open;
  const chip = host.querySelector<HTMLButtonElement>(".guest-pill");
  if (chip) act(() => chip.click());
  return host.querySelector<HTMLInputElement>(NAME_FIELD)!;
};

beforeEach(() => {
  sent.length = 0;
  queue.reset();
  codes.reset();
  localStorage.clear();
  guestName.reset();
  gis.initialize.mockClear();
  gis.renderButton.mockClear();
  signOut.mockClear();
  updated.mockClear();
  updateDisplayName.mockReset();
});
const JERRY = { name: "Jerry Yu", email: "jerry@example.com", picture: "https://img/j.png",
                display_name: null, name_shown: "Jerry" };
const saveRow = () => host.querySelector<HTMLInputElement>(".save-name-row input[type='checkbox']");
function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
/** The server answers the outstanding start (here with an error), so the next start may go. */
const answered = () => act(() => { for (const fn of [...link.listeners]) fn({ type: "error", code: "x", message: "x" }); });
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("the lobby with sign-in OFF", () => {
  it("renders no Google button, no account chip, and the guest controls", async () => {
    authState.current = { status: "off", clientId: null, user: null };
    await render();
    expect(host.querySelector(".google-signin")).toBeNull();
    expect(host.querySelector(".account-chip")).toBeNull();
    expect(gis.initialize).not.toHaveBeenCalled();
    expect(nameInput().value).toMatch(/^[A-Z][a-z]+ [A-Z][a-z]+$/);   // a random name
    const labels = Array.from(host.querySelectorAll("button")).map((b) => b.textContent);
    expect(labels).toContain("Play bots");
    expect(labels).toContain("Create room");
    expect(labels).not.toContain("Find a game");
    // no accounts: guests still queue, with no way to sign in offered
    expect([...host.querySelectorAll(".play-label")].map((h) => h.textContent)).toEqual(["Casual"]);
    expect([...host.querySelectorAll(".play-ranked-row button")].map((b) => b.textContent)).toEqual(["Play", "Duo"]);
    expect(host.querySelector(".play-guest-line")?.textContent).toBe("Playing as a guest");
  });
  it("the section a guest plays in is called Casual", async () => {
    authState.current = { status: "off", clientId: null, user: null };
    await render();
    expect(host.querySelector(".play-label")?.textContent).toBe("Casual");
    expect(host.textContent).not.toMatch(/unranked/i);
  });
  it("while loading, nothing about accounts shows either", async () => {
    authState.current = { status: "loading", clientId: null, user: null };
    await render();
    expect(host.querySelector(".google-signin")).toBeNull();
    expect(host.querySelector(".account-chip")).toBeNull();
  });
});

describe("the lobby when the server cannot be reached", () => {
  it("keeps the Ranked section, with Play and Duo unavailable, instead of dropping it", async () => {
    authState.current = { status: "error", clientId: null, user: null };
    await render();
    expect([...host.querySelectorAll(".play-label")].map((h) => h.textContent)).toEqual(["Ranked", "Casual"]);
    const ranked = host.querySelector("[data-testid=ranked-unavailable]")!;
    expect(ranked).not.toBeNull();
    const buttons = [...ranked.querySelectorAll<HTMLButtonElement>("button")];
    expect(buttons.map((b) => b.textContent)).toEqual(["Play", "Duo"]);
    expect(buttons.every((b) => b.disabled)).toBe(true);
    // a guest still gets a name to play under
    expect(nameInput().value).toMatch(/^[A-Z][a-z]+ [A-Z][a-z]+$/);
  });
});

describe("the lobby with sign-in ON", () => {
  const STATS = { name: "Jerry", rating: 1532, rank: 12, rounds: 80, provisional: false, levels_per_round: 0.4,
                  won_pct: 58, defender_won_pct: 61, attacker_won_pct: 54, best_streak: 7, games_won: 3,
                  week_delta: 8, history: [], recent_games: [], visible: true };
  beforeEach(() => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/me/stats") return { status: 200, json: async () => STATS } as Response;
      return { status: 404, json: async () => ({}) } as Response;
    }) as typeof fetch;
  });
  afterEach(() => { window.history.replaceState(null, "", "/"); });

  it("signed out: the signed-in layout with a guest chip, Play and Duo with no Ranked heading, and Casual rows", async () => {
    authState.current = { status: "out", clientId: "cid.apps", user: null };
    await render();
    expect([...host.querySelectorAll(".play-label")].map((h) => h.textContent)).toEqual(["Casual"]);
    expect(host.textContent).not.toContain("Sign in to play ranked");
    expect(host.textContent).not.toContain("Your name");
    // the chip sits where an account's does: initial, name, and Guest for the rating
    const chip = host.querySelector<HTMLButtonElement>(".guest-pill")!;
    expect(chip.previousElementSibling?.className).toBe("lobby-preview");
    const name = chip.querySelector(".account-pill-name")!.textContent!;
    expect(name).toMatch(/^[A-Z][a-z]+ [A-Z][a-z]+$/);
    expect(chip.querySelector(".avatar")?.textContent).toBe(name.slice(0, 1));
    expect(chip.querySelector(".account-pill-rating")?.textContent).toBe("Guest");
    const row = [...host.querySelectorAll<HTMLButtonElement>(".play-ranked-row button")];
    expect(row.map((b) => b.textContent)).toEqual(["Play", "Duo"]);
    expect(row[0].className).toContain("gold");
    expect(host.querySelector(".play-guest-line")?.textContent).toBe("Playing as a guest · Sign in to be ranked");
    // Play bots is a Casual row, as it is for an account
    const rows = [...host.querySelectorAll(".play-grp .grp-row")].map((b) => b.textContent);
    expect(rows).toEqual(["Create room", "Play bots"]);
    expect(buttonNamed("Play bots").className).not.toContain("gold");
    // the sign-in buttons appear only once asked for
    expect(host.querySelector(".google-signin")).toBeNull();
    act(() => host.querySelector<HTMLButtonElement>(".play-guest-signin")!.click());
    expect(host.querySelector(".google-signin")).not.toBeNull();
    expect(sent).toHaveLength(0);
    // Play queues a guest like anyone
    act(() => row[0].click());
    expect(sent).toEqual([{ type: "queue_join" }]);
  });

  it("signed out: the chip opens the name editor, whose Done keeps the name", async () => {
    authState.current = { status: "out", clientId: "cid.apps", user: null };
    await render();
    expect(host.querySelector(".q-sheet")).toBeNull();
    act(() => host.querySelector<HTMLButtonElement>(".guest-pill")!.click());
    type(nameInput(), "Ace");
    act(() => buttonNamed("Done").click());
    expect(host.querySelector(".q-layer:not(.q-out) .q-sheet")).toBeNull();
    expect(host.querySelector(".guest-pill .account-pill-name")?.textContent).toBe("Ace");
    expect(localStorage.getItem("shengji.name")).toBe("Ace");
  });

  it("signed in: an account chip under the preview opens the name editor, and there is no name field", async () => {
    authState.current = { status: "in", clientId: "cid.apps", user: JERRY };
    await render();
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    const chip = host.querySelector<HTMLButtonElement>(".account-pill")!;
    expect(chip.previousElementSibling?.className).toBe("lobby-preview");
    expect(chip.querySelector("img.avatar")?.getAttribute("src")).toBe("https://img/j.png");
    expect(chip.querySelector(".account-pill-name")?.textContent).toBe("Jerry");
    expect(chip.querySelector(".account-pill-rating")?.textContent).toBe("1,532");
    expect(host.querySelector(".google-signin")).toBeNull();
    expect(nameInput()).toBeNull();
    expect(host.querySelector("button[aria-label='Random name']")).toBeNull();
    act(() => chip.click());
    expect(window.location.hash).toBe("#/me");
  });

  it("signed in: Ranked first (Play and Duo), then Casual (Create room, Play bots)", async () => {
    authState.current = { status: "in", clientId: "cid.apps", user: JERRY };
    await render();
    expect([...host.querySelectorAll(".play-label")].map((h) => h.textContent)).toEqual(["Ranked", "Casual"]);
    const ranked = [...host.querySelectorAll(".play-ranked-row button")].map((b) => b.textContent);
    expect(ranked).toEqual(["Play", "Duo"]);
    const rows = [...host.querySelectorAll(".play-grp .grp-row")].map((b) => b.textContent);
    expect(rows).toEqual(["Create room", "Play bots"]);
    expect(host.textContent).not.toContain("Find a game");
    expect(host.querySelector(".game-subtitle")).toBeNull();
  });

  it("a blank avatar shows the initial", async () => {
    authState.current = { status: "in", clientId: "cid.apps", user: { ...JERRY, picture: null } };
    await render();
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(host.querySelector(".account-pill .avatar")?.textContent).toBe("J");
  });

  it("stats that cannot load leave the rating out of the chip", async () => {
    globalThis.fetch = vi.fn(async () => ({ status: 500, json: async () => ({}) }) as Response) as typeof fetch;
    authState.current = { status: "in", clientId: "cid.apps", user: JERRY };
    await render();
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(host.querySelector(".account-pill-name")?.textContent).toBe("Jerry");
    expect(host.querySelector(".account-pill-rating")).toBeNull();
  });
});

const rerender = () => act(async () => root.render(<Lobby status="open" error={null} onArmAutoFill={() => {}} />));
const buttonNamed = (label: string) => Array.from(host.querySelectorAll("button")).find((b) => b.textContent === label)!;
/** A bots game: one tap on Play bots. */
const playBots = () => act(() => buttonNamed("Play bots").click());
const sentName = (k = 0) => (sent[k] as { name: string }).name;
const isRandom = (v: string) => {
  const [adj, noun] = v.split(" ");
  return (NAME_ADJECTIVES as readonly string[]).includes(adj) && (NAME_NOUNS as readonly string[]).includes(noun);
};
async function remount() {
  act(() => root.unmount());
  host.remove();
  sent.length = 0;
  await render();
}

describe("signed in, the player plays under the account name", () => {
  const CAPTAIN = { ...JERRY, display_name: "Captain", name_shown: "Captain" };

  it("shows no name field; Create and Play bots send the account name; Play queues at once", async () => {
    authState.current = { status: "in", clientId: "cid.apps", user: CAPTAIN };
    await render();
    expect(nameInput()).toBeNull();
    expect(saveRow()).toBeNull();
    expect(host.textContent).not.toContain("Your name");
    act(() => buttonNamed("Create room").click());
    answered();
    playBots();
    answered();
    // Play joins the ranked queue with no sheet in between
    act(() => buttonNamed("Play").click());
    expect(queue.view.sheet).toBeNull();
    expect(sent.map((m) => (m as { type: string }).type)).toEqual(["create_room", "create_room", "queue_join"]);
    expect(sentName(0)).toBe("Captain");
    expect(sentName(1)).toBe("Captain");
    expect(sent[2]).toEqual({ type: "queue_join" });
  });

  it("Duo opens the pair sheet", async () => {
    authState.current = { status: "in", clientId: "cid.apps", user: CAPTAIN };
    await render();
    act(() => buttonNamed("Duo").click());
    expect(queue.view.sheet).toBe("party");
    expect(sent).toEqual([{ type: "party_create" }]);
  });

  it("without a display name the first name is used, and a rename is followed at once", async () => {
    authState.current = { status: "in", clientId: "cid.apps", user: JERRY };
    await render();
    act(() => buttonNamed("Create room").click());
    expect(sentName()).toBe("Jerry");
    authState.current = { status: "in", clientId: "cid.apps", user: CAPTAIN };
    await rerender();
    answered();
    act(() => buttonNamed("Create room").click());
    expect(sentName(1)).toBe("Captain");
  });

  it("a guest name saved on this device is neither used nor overwritten", async () => {
    localStorage.setItem("shengji.name", "JY");
    authState.current = { status: "in", clientId: "cid.apps", user: JERRY };
    await render();
    act(() => buttonNamed("Create room").click());
    expect(sentName()).toBe("Jerry");
    expect(localStorage.getItem("shengji.name")).toBe("JY");
  });

  it("while sign-in is loading nothing is filled; once signed in the field goes away", async () => {
    authState.current = { status: "loading", clientId: "cid.apps", user: null };
    await render();
    expect(nameInput().value).toBe("");
    authState.current = { status: "in", clientId: "cid.apps", user: JERRY };
    await rerender();
    expect(nameInput()).toBeNull();
  });
});

describe("signed out, the guest names themselves", () => {
  const dice = () => { nameInput(); return host.querySelector<HTMLButtonElement>("button[aria-label='Random name']")!; };

  it("restores the name used last time, which Create and Play vs bots save without asking", async () => {
    localStorage.setItem("shengji.name", "Ace");
    authState.current = { status: "out", clientId: "cid.apps", user: null };
    await render();
    expect(nameInput().value).toBe("Ace");
    expect(saveRow()).toBeNull();
    expect(host.querySelector(".account-edit")).toBeNull();
    type(nameInput(), "Deuce");
    act(() => buttonNamed("Create room").click());
    expect(sentName()).toBe("Deuce");
    expect(localStorage.getItem("shengji.name")).toBe("Deuce");
    await remount();
    expect(nameInput().value).toBe("Deuce");
    type(nameInput(), "Trey");
    playBots();
    expect(sentName()).toBe("Trey");
    expect(localStorage.getItem("shengji.name")).toBe("Trey");
  });

  it("with no saved name, a first visit gets a random name (sign-in off or signed out)", async () => {
    for (const status of ["off", "out"] as const) {
      localStorage.clear();
      authState.current = { status, clientId: status === "out" ? "cid.apps" : null, user: null };
      if (status === "off") await render(); else await remount();
      expect(isRandom(nameInput().value)).toBe(true);
      act(() => buttonNamed("Create room").click());
      expect(sentName()).toBe(nameInput().value);
      expect(localStorage.getItem("shengji.name")).toBe(nameInput().value);
    }
  });

  it("the name field is a keyboard-friendly name entry that Enter puts away without submitting", async () => {
    authState.current = { status: "off", clientId: null, user: null };
    await render();
    const input = nameInput();
    expect(input.getAttribute("enterkeyhint")).toBe("done");
    expect(input.getAttribute("spellcheck")).toBe("false");
    expect(input.getAttribute("autocapitalize")).toBe("words");
    expect(input.getAttribute("autocorrect")).toBe("off");
    act(() => input.focus());
    expect(document.activeElement).toBe(input);
    act(() => { input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
    expect(document.activeElement).not.toBe(input);
    expect(sent).toHaveLength(0);
  });

  it("the dice reroll the name, have an accessible label and never submit", async () => {
    authState.current = { status: "off", clientId: null, user: null };
    await render();
    expect(dice().getAttribute("type")).toBe("button");
    for (let i = 0; i < 20; i++) {
      const before = nameInput().value;
      act(() => dice().click());
      expect(nameInput().value).not.toBe(before);
      expect(isRandom(nameInput().value)).toBe(true);
    }
    expect(sent).toHaveLength(0);
  });

  it("a name typed before sign-in resolves is kept, and a cleared field is not refilled", async () => {
    authState.current = { status: "loading", clientId: "cid.apps", user: null };
    await render();
    type(nameInput(), "Mine");
    authState.current = { status: "out", clientId: "cid.apps", user: null };
    await rerender();
    expect(nameInput().value).toBe("Mine");
    type(nameInput(), "");
    await rerender();
    expect(nameInput().value).toBe("");
  });

  it("with the name cleared, Create room and Play vs bots both stay enabled and pick a random name", async () => {
    authState.current = { status: "off", clientId: null, user: null };
    await render();
    type(nameInput(), "");
    expect(buttonNamed("Create room").disabled).toBe(false);
    expect(buttonNamed("Play bots").disabled).toBe(false);
    act(() => buttonNamed("Create room").click());
    expect(isRandom(sentName())).toBe(true);
    expect(nameInput().value).toBe(sentName());          // the field shows the name it went with
    await remount();
    type(nameInput(), "   ");
    playBots();
    expect(isRandom(sentName())).toBe(true);
    expect(nameInput().value).toBe(sentName());
  });
});

describe("no connection", () => {
  afterEach(() => { vi.useRealTimers(); });

  const pill = () => host.querySelector(".play-conn");
  const retryPill = () => host.querySelector<HTMLButtonElement>("button.play-conn");
  async function renderAt(status: "open" | "closed" | "connecting") {
    if (!host || !host.isConnected) {
      host = document.createElement("div");
      document.body.appendChild(host);
      root = createRoot(host);
    }
    await act(async () => root.render(<Lobby status={status} error={null} onArmAutoFill={() => {}} />));
  }

  it("says Connecting… first, then after 4 s No connection · retrying, which retries on a tap", async () => {
    vi.useFakeTimers();
    authState.current = { status: "off", clientId: null, user: null };
    reconnects.n = 0;
    await renderAt("connecting");
    expect(pill()?.textContent).toBe("Connecting…");
    expect(retryPill()).toBeNull();
    expect(buttonNamed("Play bots").disabled).toBe(true);    // not yet known to be offline
    await act(async () => { vi.advanceTimersByTime(3999); });
    expect(retryPill()).toBeNull();
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(retryPill()?.textContent).toBe("No connection · retrying");
    act(() => retryPill()!.click());
    expect(reconnects.n).toBe(1);
    // the wait starts over after a retry
    expect(retryPill()).toBeNull();
    await act(async () => { vi.advanceTimersByTime(4000); });
    expect(retryPill()).not.toBeNull();
    // a connection clears it at once, and says nothing while all is well
    await renderAt("open");
    expect(pill()).toBeNull();
    expect(host.textContent).not.toContain("Connected");
  });

  it("with no connection Play bots stays gold and plays on this device; the rest is disabled", async () => {
    vi.useFakeTimers();
    const start = vi.spyOn(offlineGame, "start").mockImplementation(() => {});
    try {
      authState.current = { status: "in", clientId: "cid.apps", user: JERRY };
      await renderAt("closed");
      await act(async () => { vi.advanceTimersByTime(STALL_MS); });
      const bots = buttonNamed("Play bots");
      expect(bots.className).toContain("gold");               // the main button, signed in too
      expect(bots.disabled).toBe(false);
      for (const label of ["Play", "Duo", "Create room", "Join"]) expect(buttonNamed(label).disabled).toBe(true);
      expect(host.querySelector<HTMLInputElement>("input[aria-label='Room or duo code']")!.disabled).toBe(true);
      expect(host.querySelector(".play-label")?.textContent).toBe("Ranked");   // same layout, greyed
      act(() => bots.click());
      expect(start).toHaveBeenCalledTimes(1);
      expect(sent).toHaveLength(0);
    } finally {
      start.mockRestore();
    }
  });

  it("connected, Play bots plays online (never the offline game)", async () => {
    const start = vi.spyOn(offlineGame, "start").mockImplementation(() => {});
    try {
      authState.current = { status: "in", clientId: "cid.apps", user: JERRY };
      await renderAt("open");
      const bots = buttonNamed("Play bots");
      expect(bots.className).toContain("grp-row");
      act(() => bots.click());
      expect(start).not.toHaveBeenCalled();
      expect(sent).toMatchObject([{ type: "create_room" }]);
    } finally {
      start.mockRestore();
    }
  });
});

describe("the lobby preview and the How to play entry", () => {
  const preview = () => host.querySelector(".lobby-preview");

  it("draws a live trick with the table's cards, not a video", async () => {
    authState.current = { status: "out", clientId: "cid", user: null };
    await render();
    expect(host.querySelector("video")).toBeNull();
    expect(preview()!.getAttribute("aria-hidden")).toBe("true");
    expect(preview()!.querySelectorAll(".card").length).toBeGreaterThan(0);
  });

  it("shows the preview signed in, signed out, while loading and with sign-in off", async () => {
    for (const state of [
      { status: "in", clientId: "cid", user: JERRY },
      { status: "out", clientId: "cid", user: null },
      { status: "loading", clientId: null, user: null },
      { status: "off", clientId: null, user: null },
    ] as AuthState[]) {
      authState.current = state;
      await render();
      expect(preview()).not.toBeNull();
      act(() => root.unmount());
      host.remove();
    }
    await render(); // afterEach unmounts once more
  });

  it("reduced motion shows one still frame", async () => {
    authState.current = { status: "out", clientId: "cid", user: null };
    const mm = window.matchMedia;
    window.matchMedia = ((q: string) => ({ matches: q.includes("reduce"), media: q })) as unknown as typeof window.matchMedia;
    try {
      await render();
    } finally {
      window.matchMedia = mm;
    }
    expect(host.querySelector("video")).toBeNull();
    expect(preview()!.getAttribute("data-still")).toBe("true");
  });

  it("How to play opens #/howto", async () => {
    authState.current = { status: "out", clientId: "cid", user: null };
    await render();
    const entry = host.querySelector(".howto-entry")!;
    expect(entry.textContent).toBe("How to play");
    try {
      act(() => entry.querySelector<HTMLButtonElement>("button")!.click());
      expect(window.location.hash).toBe("#/howto");
    } finally {
      window.history.replaceState(null, "", "/");
    }
  });
});

describe("help and policy links", () => {
  it("Play keeps the How to play line and leaves Privacy and Support to the Me tab", async () => {
    for (const current of [{ status: "out", clientId: "cid", user: null },
                           { status: "in", clientId: "cid", user: JERRY }] as AuthState[]) {
      authState.current = current;
      if (host) { act(() => root.unmount()); host.remove(); }
      await render();
      expect(host.querySelector(".howto-entry")?.textContent).toBe("How to play");
      expect(host.querySelector(".info-links")).toBeNull();
      expect(host.querySelector("a[href='/privacy'], a[href='/support']")).toBeNull();
    }
  });
});

describe("starting a game waits for the server", () => {
  const button = (text: RegExp) => [...host.querySelectorAll<HTMLButtonElement>("button")].find((b) => text.test(b.textContent ?? ""))!;
  const serverSays = (m: unknown) => act(() => { for (const fn of [...link.listeners]) fn(m); });
  async function renderWith(status: "open" | "closed" | "connecting") {
    await act(async () => root.render(<Lobby status={status} error={null} onArmAutoFill={() => {}} />));
  }

  beforeEach(() => { authState.current = { status: "off", clientId: null, user: null }; });
  const tapStart = (start: RegExp) => act(() => button(start).click());
  for (const [start, busy] of [[/^Play bots$/, "Starting…"], [/^Create room$/, "Creating…"]] as const) {
    it(`${busy} shows at once, and a second tap sends nothing; an error allows a retry`, async () => {
      await render();
      tapStart(start);
      expect(sent).toHaveLength(1);
      const b = button(new RegExp(busy));
      expect(b.getAttribute("aria-busy")).toBe("true");
      expect(b.disabled).toBe(true);
      act(() => b.click());
      expect(sent).toHaveLength(1);
      // every other start waits too
      expect(button(/^(Play bots|Create room)$/).disabled).toBe(true);
      serverSays({ type: "error", code: "busy", message: "Server busy." });
      expect(button(start).disabled).toBe(false);
      expect(button(start).getAttribute("aria-busy")).toBeNull();
      tapStart(start);
      expect(sent).toHaveLength(2);
    });
  }

  it("a reconnect frees a start that was never answered, for a deliberate retry", async () => {
    await render();
    playBots();
    expect(button(/Starting…/).disabled).toBe(true);
    await renderWith("closed");
    link.generation += 1;
    await renderWith("open");
    expect(button(/^Play bots$/).disabled).toBe(false);
    playBots();
    expect(sent).toHaveLength(2);
    link.generation = 0;
  });

  it("Join says Joining… while the room is looked up, and an error frees it", async () => {
    await render();
    const code = host.querySelector<HTMLInputElement>("input[aria-label='Room or duo code']")!;
    type(code, "abcd");
    act(() => button(/^Join$/).click());
    expect(sent).toEqual([{ type: "code_lookup", code: "ABCD" }]);
    expect(button(/Joining…/).getAttribute("aria-busy")).toBe("true");
    act(() => button(/Joining…/).click());
    expect(sent).toHaveLength(1);
    serverSays({ type: "code_kind", code: "ABCD", kind: "room" });
    expect(sent).toEqual([{ type: "code_lookup", code: "ABCD" }, { type: "peek_room", room: "ABCD" }]);
    expect(button(/Joining…/).disabled).toBe(true);
    // straight through when there is no seat to choose: still joining, one join
    serverSays({ type: "room_seats", room: "ABCD", seats: [] });
    expect(sent.filter((m) => (m as { type: string }).type === "join_room")).toHaveLength(1);
    expect(button(/Joining…/).disabled).toBe(true);
    serverSays({ type: "error", code: "room_not_found", message: "No such room." });
    expect(button(/^Join$/).disabled).toBe(false);
  });

  it("a code that names nothing frees Join and says so until the box changes", async () => {
    await render();
    const code = host.querySelector<HTMLInputElement>("input[aria-label='Room or duo code']")!;
    type(code, "ZZZZ");
    act(() => button(/^Join$/).click());
    serverSays({ type: "code_kind", code: "ZZZZ", kind: "none" });
    expect(button(/^Join$/).disabled).toBe(false);
    expect(host.querySelector(".lobby-error")?.textContent).toBe("No game or pair has that code.");
    // shown above the sections, where it is on screen at rest, not under Join
    const err = host.querySelector(".lobby-error")!;
    const first = host.querySelector(".play-section")!;
    expect(err.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(err.getAttribute("role")).toBe("alert");
    expect(sent).toEqual([{ type: "code_lookup", code: "ZZZZ" }]);
    type(code, "ZZZ");
    expect(host.querySelector(".lobby-error")).toBeNull();
  });
});
