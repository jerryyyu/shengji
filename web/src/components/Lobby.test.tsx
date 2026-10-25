import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthState } from "../auth";

const { sent, authState, signOut, updated, updateDisplayName, gis } = vi.hoisted(() => ({
  sent: [] as unknown[],
  authState: { current: { status: "loading", clientId: null, user: null } as AuthState },
  signOut: vi.fn(() => Promise.resolve()),
  updated: vi.fn(),
  updateDisplayName: vi.fn(),
  gis: { initialize: vi.fn(), renderButton: vi.fn(), disableAutoSelect: vi.fn() },
}));
vi.mock("../ws", () => ({
  conn: { send: (m: unknown) => { sent.push(m); }, subscribe: () => () => {}, generation: 0 },
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
    expect(nameInput().value).toBe("");
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

  it("signed in: shows avatar, name and Sign out; the empty name field takes the first name", async () => {
    authState.current = {
      status: "in", clientId: "cid.apps",
      user: JERRY,
    };
    await render();
    const chip = host.querySelector(".account-chip")!;
    expect(chip).not.toBeNull();
    expect(chip.querySelector("img.account-avatar")?.getAttribute("src")).toBe("https://img/j.png");
    expect(chip.querySelector(".account-name")?.textContent).toBe("Jerry");   // the effective name
    expect(host.querySelector(".google-signin")).toBeNull();
    expect(nameInput().value).toBe("Jerry");
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

  it("signed in with a saved name keeps that name", async () => {
    localStorage.setItem("shengji.name", "JY");
    authState.current = {
      status: "in", clientId: "cid.apps",
      user: { ...JERRY, picture: null },
    };
    await render();
    expect(nameInput().value).toBe("JY");
    expect(host.querySelector(".account-avatar-blank")?.textContent).toBe("J");
  });
});

describe("the display name in the lobby", () => {
  it("prefills the empty name field from the chosen display name and shows it in the chip", async () => {
    authState.current = {
      status: "in", clientId: "cid.apps", user: { ...JERRY, display_name: "Captain", name_shown: "Captain" },
    };
    await render();
    expect(nameInput().value).toBe("Captain");
    expect(host.querySelector(".account-name")?.textContent).toBe("Captain");
    expect(saveRow()).toBeNull();                   // nothing differs, nothing to save
  });

  it("a field still showing the old account name follows a rename; a typed name does not", async () => {
    authState.current = { status: "in", clientId: "cid.apps", user: JERRY };
    await render();
    expect(nameInput().value).toBe("Jerry");
    authState.current = {
      status: "in", clientId: "cid.apps", user: { ...JERRY, display_name: "Cap", name_shown: "Cap" },
    };
    await act(async () => root.render(<Lobby status="open" error={null} onArmAutoFill={() => {}} />));
    expect(nameInput().value).toBe("Cap");
    type(nameInput(), "Someone");
    authState.current = {
      status: "in", clientId: "cid.apps", user: { ...JERRY, display_name: "Other", name_shown: "Other" },
    };
    await act(async () => root.render(<Lobby status="open" error={null} onArmAutoFill={() => {}} />));
    expect(nameInput().value).toBe("Someone");
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

  it("a different typed name offers 'Save as my name', off by default; ticked, create PATCHes once", async () => {
    authState.current = { status: "in", clientId: "cid.apps", user: JERRY };
    updateDisplayName.mockResolvedValue({ ...JERRY, display_name: "Cap", name_shown: "Cap" });
    await render();
    expect(saveRow()).toBeNull();
    type(nameInput(), "Cap");
    expect(saveRow()).not.toBeNull();
    expect(saveRow()!.checked).toBe(false);
    // unticked: create sends the room message only
    const create = () => Array.from(host.querySelectorAll("button")).find((b) => b.textContent === "Create room")!;
    act(() => create().click());
    expect(updateDisplayName).not.toHaveBeenCalled();
    expect(sent).toHaveLength(1);
    expect((sent[0] as { name: string }).name).toBe("Cap");
    // ticked: one PATCH with the typed name, and the room message as before
    act(() => saveRow()!.click());
    expect(saveRow()!.checked).toBe(true);
    await act(async () => create().click());
    expect(updateDisplayName).toHaveBeenCalledTimes(1);
    expect(updateDisplayName).toHaveBeenCalledWith("Cap");
    expect(updated).toHaveBeenCalled();
    expect(sent).toHaveLength(2);
  });

  it("ticked with a reserved name: the message shows and nothing is PATCHed", async () => {
    authState.current = { status: "in", clientId: "cid.apps", user: JERRY };
    await render();
    type(nameInput(), "Bot 1");
    act(() => saveRow()!.click());
    expect(host.querySelector(".save-name-error")?.textContent).toContain("reserved");
    const create = Array.from(host.querySelectorAll("button")).find((b) => b.textContent === "Create room")!;
    await act(async () => create.click());
    expect(updateDisplayName).not.toHaveBeenCalled();
    expect((sent[0] as { name: string }).name).toBe("Bot 1");   // the room still gets the typed name
  });

  it("guests see no checkbox and no edit button", async () => {
    authState.current = { status: "off", clientId: null, user: null };
    await render();
    type(nameInput(), "Anyone");
    expect(saveRow()).toBeNull();
    expect(host.querySelector(".account-edit")).toBeNull();
  });
});

describe("a saved account default follows a rename; a typed name does not (review1157)", () => {
  const CAPTAIN = { ...JERRY, display_name: "Captain", name_shown: "Captain" };
  const createBtn = () => Array.from(host.querySelectorAll("button")).find((b) => b.textContent === "Create room")!;
  const remount = async () => {
    act(() => root.unmount());
    host.remove();
    sent.length = 0;
    await render();
  };

  it("in-game edit: the auto-filled name was saved, then renamed while the lobby was unmounted", async () => {
    authState.current = { status: "in", clientId: "cid.apps", user: JERRY };
    await render();
    act(() => createBtn().click());
    expect(localStorage.getItem("shengji.name")).toBe("Jerry");
    expect(localStorage.getItem("shengji.nameSource")).toBe("account");
    authState.current = { status: "in", clientId: "cid.apps", user: CAPTAIN };   // edited from the phone menu
    await remount();
    expect(nameInput().value).toBe("Captain");
    act(() => createBtn().click());
    expect((sent[0] as { name: string }).name).toBe("Captain");
    expect(localStorage.getItem("shengji.name")).toBe("Captain");
  });

  it("reload: a saved account default meets a renamed account on first paint", async () => {
    localStorage.setItem("shengji.name", "Jerry");
    localStorage.setItem("shengji.nameSource", "account");
    authState.current = { status: "in", clientId: "cid.apps", user: CAPTAIN };
    await render();
    expect(nameInput().value).toBe("Captain");
    expect(saveRow()).toBeNull();
    act(() => createBtn().click());
    expect((sent[0] as { name: string }).name).toBe("Captain");
  });

  it("a typed room name survives a rename, in-game and on reload", async () => {
    authState.current = { status: "in", clientId: "cid.apps", user: JERRY };
    await render();
    type(nameInput(), "Ace");
    act(() => createBtn().click());
    expect(localStorage.getItem("shengji.nameSource")).toBe("typed");
    authState.current = { status: "in", clientId: "cid.apps", user: CAPTAIN };
    await remount();
    expect(nameInput().value).toBe("Ace");
    act(() => createBtn().click());
    expect((sent[0] as { name: string }).name).toBe("Ace");
    expect(saveRow()).not.toBeNull();            // offered, not forced
    expect(saveRow()!.checked).toBe(false);
  });

  it("a saved name without a marker (pre-marker save) is treated as typed", async () => {
    localStorage.setItem("shengji.name", "Jerry");
    authState.current = { status: "in", clientId: "cid.apps", user: CAPTAIN };
    await render();
    expect(nameInput().value).toBe("Jerry");
  });

  it("a guest is unaffected", async () => {
    localStorage.setItem("shengji.name", "Ace");
    localStorage.setItem("shengji.nameSource", "account");   // even a stale marker
    authState.current = { status: "off", clientId: null, user: null };
    await render();
    expect(nameInput().value).toBe("Ace");
    act(() => createBtn().click());
    expect((sent[0] as { name: string }).name).toBe("Ace");
    expect(localStorage.getItem("shengji.nameSource")).toBe("typed");
  });
});
