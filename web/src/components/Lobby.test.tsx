import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthState } from "../auth";

const { sent, authState, signOut, gis } = vi.hoisted(() => ({
  sent: [] as unknown[],
  authState: { current: { status: "loading", clientId: null, user: null } as AuthState },
  signOut: vi.fn(() => Promise.resolve()),
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
    auth: { signOut, signedIn: vi.fn(), init: vi.fn() },
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
});
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
      user: { name: "Jerry Yu", email: "jerry@example.com", picture: "https://img/j.png" },
    };
    await render();
    const chip = host.querySelector(".account-chip")!;
    expect(chip).not.toBeNull();
    expect(chip.querySelector("img.account-avatar")?.getAttribute("src")).toBe("https://img/j.png");
    expect(chip.querySelector(".account-name")?.textContent).toBe("Jerry Yu");
    expect(host.querySelector(".google-signin")).toBeNull();
    expect(nameInput().value).toBe("Jerry");
    act(() => chip.querySelector<HTMLButtonElement>(".account-signout")!.click());
    expect(signOut).toHaveBeenCalledTimes(1);
  });

  it("a sign-out the server refused keeps the chip and shows a retryable error", async () => {
    authState.current = {
      status: "in", clientId: "cid.apps",
      user: { name: "Jerry Yu", email: "jerry@example.com", picture: null },
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
      user: { name: "Jerry Yu", email: "jerry@example.com", picture: null },
    };
    await render();
    expect(nameInput().value).toBe("JY");
    expect(host.querySelector(".account-avatar-blank")?.textContent).toBe("J");
  });
});
