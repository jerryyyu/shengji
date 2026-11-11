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

import Lobby from "./Lobby";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

async function render() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => root.render(<Lobby status="open" error={null} onArmAutoFill={() => {}} />));
}
const nameInput = () => host.querySelector<HTMLInputElement>("input[autocomplete='nickname']")!;

beforeEach(() => {
  sent.length = 0;
  localStorage.clear();
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
    expect(labels).toContain("Play vs bots");
    expect(labels).toContain("Create room");
  });
  it("while loading, nothing about accounts shows either", async () => {
    authState.current = { status: "loading", clientId: null, user: null };
    await render();
    expect(host.querySelector(".google-signin")).toBeNull();
    expect(host.querySelector(".account-chip")).toBeNull();
  });
});

describe("the lobby with sign-in ON", () => {
  it("signed out: renders the Google button slot and initialises GIS with the client id", async () => {
    authState.current = { status: "out", clientId: "cid.apps", user: null };
    await render();
    expect(host.querySelector(".google-signin")).not.toBeNull();
    expect(host.querySelector(".account-chip")).toBeNull();
    expect(gis.initialize).toHaveBeenCalledTimes(1);
    const cfg = gis.initialize.mock.calls[0][0] as { client_id: string; nonce: string };
    expect(cfg.client_id).toBe("cid.apps");
    expect(cfg.nonce).toMatch(/^[0-9a-f]{32}$/);
    expect(gis.renderButton).toHaveBeenCalledTimes(1);
    expect(gis.renderButton.mock.calls[0][0]).toBe(host.querySelector(".google-signin-slot"));
  });

  it("signed in: shows avatar, name and Sign out, and no name field of its own", async () => {
    authState.current = {
      status: "in", clientId: "cid.apps",
      user: JERRY,
    };
    await render();
    const chip = host.querySelector(".account-card")!;
    expect(chip).not.toBeNull();
    expect(chip.querySelector("img.account-avatar")?.getAttribute("src")).toBe("https://img/j.png");
    expect(chip.querySelector(".account-name")?.textContent).toBe("Jerry");   // the effective name
    expect(host.querySelector(".google-signin")).toBeNull();
    expect(nameInput()).toBeNull();
    expect(host.querySelector("button[aria-label='Random name']")).toBeNull();
    act(() => chip.querySelector<HTMLButtonElement>(".account-signout")!.click());
    expect(signOut).toHaveBeenCalledTimes(1);
  });

  it("a sign-out the server refused keeps the chip and shows a retryable error", async () => {
    authState.current = {
      status: "in", clientId: "cid.apps",
      user: { ...JERRY, picture: null },
    };
    signOut.mockImplementationOnce(() => Promise.reject(new Error("Sign-out failed (500). Try again.")));
    await render();
    await act(async () => { host.querySelector<HTMLButtonElement>(".account-signout")!.click(); });
    expect(host.querySelector(".account-chip")).not.toBeNull();
    expect(host.querySelector(".account-error")?.textContent).toContain("Try again");
    expect(host.querySelector<HTMLButtonElement>(".account-signout")!.disabled).toBe(false);
    await act(async () => { host.querySelector<HTMLButtonElement>(".account-signout")!.click(); });
    expect(signOut).toHaveBeenCalledTimes(2);
    expect(host.querySelector(".account-error")).toBeNull();
  });

  it("a blank avatar shows the initial", async () => {
    authState.current = {
      status: "in", clientId: "cid.apps",
      user: { ...JERRY, picture: null },
    };
    await render();
    expect(host.querySelector(".account-avatar-blank")?.textContent).toBe("J");
  });
});

const rerender = () => act(async () => root.render(<Lobby status="open" error={null} onArmAutoFill={() => {}} />));
const buttonNamed = (label: string) => Array.from(host.querySelectorAll("button")).find((b) => b.textContent === label)!;
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

  it("shows no name field and no 'Save as my name'; Create and Play vs bots send the account name", async () => {
    authState.current = { status: "in", clientId: "cid.apps", user: CAPTAIN };
    await render();
    expect(nameInput()).toBeNull();
    expect(saveRow()).toBeNull();
    expect(host.textContent).not.toContain("Your name");
    expect(host.querySelector(".account-name")?.textContent).toBe("Captain");
    act(() => buttonNamed("Create room").click());
    answered();
    act(() => buttonNamed("Play vs bots").click());
    expect(sent.map((m) => (m as { type: string }).type)).toEqual(["create_room", "create_room"]);
    expect([sentName(0), sentName(1)]).toEqual(["Captain", "Captain"]);
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

  it("the Edit name button opens the form, and a saved name reaches the store", async () => {
    authState.current = { status: "in", clientId: "cid.apps", user: JERRY };
    const next = { ...JERRY, display_name: "Cap", name_shown: "Cap" };
    updateDisplayName.mockResolvedValue(next);
    await render();
    expect(host.querySelector(".name-edit")).toBeNull();
    act(() => host.querySelector<HTMLButtonElement>(".account-edit")!.click());
    const input = host.querySelector<HTMLInputElement>(".name-edit-input")!;
    expect(input.value).toBe("Jerry");
    type(input, "Cap");
    await act(async () => { host.querySelector("form.name-edit")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    expect(updateDisplayName).toHaveBeenCalledWith("Cap");
    expect(updated).toHaveBeenCalledWith(next);
    expect(host.querySelector(".name-edit")).toBeNull();
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
  const dice = () => host.querySelector<HTMLButtonElement>("button[aria-label='Random name']")!;

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
    act(() => buttonNamed("Play vs bots").click());
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
    expect(buttonNamed("Play vs bots").disabled).toBe(false);
    act(() => buttonNamed("Create room").click());
    expect(isRandom(sentName())).toBe(true);
    expect(nameInput().value).toBe(sentName());          // the field shows the name it went with
    await remount();
    type(nameInput(), "   ");
    act(() => buttonNamed("Play vs bots").click());
    expect(isRandom(sentName())).toBe(true);
    expect(nameInput().value).toBe(sentName());
  });
});

describe("no connection", () => {
  afterEach(() => { vi.useRealTimers(); });

  it("says Connecting… first, then after 4 s that the server is unreachable, with a Retry that reconnects", async () => {
    vi.useFakeTimers();
    authState.current = { status: "off", clientId: null, user: null };
    reconnects.n = 0;
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => root.render(<Lobby status="connecting" error={null} onArmAutoFill={() => {}} />));
    expect(host.querySelector(".conn-status")?.textContent).toContain("Connecting…");
    expect(buttonNamed("Retry")).toBeUndefined();
    await act(async () => { vi.advanceTimersByTime(3999); });
    expect(buttonNamed("Retry")).toBeUndefined();
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(host.querySelector(".conn-status.stalled")?.textContent).toContain("Can’t reach the server");
    act(() => buttonNamed("Retry").click());
    expect(reconnects.n).toBe(1);
    // the wait starts over after a retry
    expect(buttonNamed("Retry")).toBeUndefined();
    await act(async () => { vi.advanceTimersByTime(4000); });
    expect(buttonNamed("Retry")).toBeDefined();
    // a connection clears it at once
    await act(async () => root.render(<Lobby status="open" error={null} onArmAutoFill={() => {}} />));
    expect(buttonNamed("Retry")).toBeUndefined();
    expect(host.querySelector(".conn-status")?.textContent).toContain("Connected");
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

  it("New to Sheng Ji? How to play opens #/howto", async () => {
    authState.current = { status: "out", clientId: "cid", user: null };
    await render();
    const entry = host.querySelector(".howto-entry")!;
    expect(entry.textContent).toBe("New to Sheng Ji? How to play");
    try {
      act(() => entry.querySelector<HTMLButtonElement>("button")!.click());
      expect(window.location.hash).toBe("#/howto");
    } finally {
      window.history.replaceState(null, "", "/");
    }
  });
});

describe("starting a game waits for the server", () => {
  const button = (text: RegExp) => [...host.querySelectorAll<HTMLButtonElement>("button")].find((b) => text.test(b.textContent ?? ""))!;
  const serverSays = (m: unknown) => act(() => { for (const fn of [...link.listeners]) fn(m); });
  async function renderWith(status: "open" | "closed" | "connecting") {
    await act(async () => root.render(<Lobby status={status} error={null} onArmAutoFill={() => {}} />));
  }

  for (const [start, busy] of [[/^Play vs bots$/, "Starting…"], [/^Create room$/, "Creating…"]] as const) {
    it(`${busy} shows at once, and a second tap sends nothing; an error allows a retry`, async () => {
      await render();
      act(() => button(start).click());
      expect(sent).toHaveLength(1);
      const b = button(new RegExp(busy));
      expect(b.getAttribute("aria-busy")).toBe("true");
      expect(b.disabled).toBe(true);
      act(() => b.click());
      expect(sent).toHaveLength(1);
      // every other start waits too
      expect(button(/^(Play vs bots|Create room)$/).disabled).toBe(true);
      serverSays({ type: "error", code: "busy", message: "Server busy." });
      expect(button(start).disabled).toBe(false);
      expect(button(start).getAttribute("aria-busy")).toBeNull();
      act(() => button(start).click());
      expect(sent).toHaveLength(2);
    });
  }

  it("a reconnect frees a start that was never answered, for a deliberate retry", async () => {
    await render();
    act(() => button(/^Play vs bots$/).click());
    expect(button(/Starting…/).disabled).toBe(true);
    await renderWith("closed");
    link.generation += 1;
    await renderWith("open");
    expect(button(/^Play vs bots$/).disabled).toBe(false);
    act(() => button(/^Play vs bots$/).click());
    expect(sent).toHaveLength(2);
    link.generation = 0;
  });

  it("Join says Joining… while the room is looked up, and an error frees it", async () => {
    await render();
    const code = host.querySelector<HTMLInputElement>("input[aria-label='Room code']")!;
    type(code, "ABCD");
    act(() => button(/^Join$/).click());
    expect(sent).toEqual([{ type: "peek_room", room: "ABCD" }]);
    expect(button(/Joining…/).getAttribute("aria-busy")).toBe("true");
    act(() => button(/Joining…/).click());
    expect(sent).toHaveLength(1);
    // straight through when there is no seat to choose: still joining, one join
    serverSays({ type: "room_seats", room: "ABCD", seats: [] });
    expect(sent.filter((m) => (m as { type: string }).type === "join_room")).toHaveLength(1);
    expect(button(/Joining…/).disabled).toBe(true);
    serverSays({ type: "error", code: "room_not_found", message: "No such room." });
    expect(button(/^Join$/).disabled).toBe(false);
  });
});
