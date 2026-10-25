import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import HudMenu from "./HudMenu";
import MuteButton from "./MuteButton";
import { isMuted, setMuted } from "../audio";
import { auth } from "../auth";

const sent: unknown[] = [];
vi.mock("../ws", () => ({ conn: { send: (m: unknown) => { sent.push(m); }, reconnect: () => {} } }));

beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});
beforeEach(() => { sent.length = 0; });

function render() {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<HudMenu room="ABCD" kittyCount={8} />));
  return { host, unmount: () => act(() => root.unmount()) };
}
const btn = (host: HTMLElement) => host.querySelector<HTMLButtonElement>(".hud-more-btn")!;
const rows = (host: HTMLElement) => Array.from(host.querySelectorAll<HTMLElement>(".hud-menu-row"));

describe("the phone overflow menu (#651)", () => {
  it("is closed until tapped, then lists kitty, sound, invite and leave", () => {
    const v = render();
    expect(v.host.querySelector(".hud-menu")).toBeNull();
    expect(btn(v.host).getAttribute("aria-expanded")).toBe("false");
    act(() => btn(v.host).click());
    expect(btn(v.host).getAttribute("aria-expanded")).toBe("true");
    const text = rows(v.host).map((r) => r.textContent);
    expect(text[0]).toContain("Kitty"); expect(text[0]).toContain("8 cards");
    expect(text[1]).toContain("Sound");
    expect(text[2]).toContain("Copy invite link");
    expect(text[3]).toContain("Leave game");
    v.unmount();
  });

  it("leave needs TWO taps, and the first one keeps the menu open", () => {
    const v = render();
    act(() => btn(v.host).click());
    const leave = () => rows(v.host)[3] as HTMLButtonElement;
    act(() => leave().click());
    expect(sent).toEqual([]);
    expect(v.host.querySelector(".hud-menu")).not.toBeNull();
    expect(leave().textContent).toContain("Leave game?");
    act(() => leave().click());
    expect(sent).toEqual([{ type: "leave_room" }]);
    expect(v.host.querySelector(".hud-menu")).toBeNull();
    v.unmount();
  });

  it("an armed leave reverts after 3 s without a second tap", () => {
    vi.useFakeTimers();
    const v = render();
    act(() => btn(v.host).click());
    act(() => (rows(v.host)[3] as HTMLButtonElement).click());
    act(() => { vi.advanceTimersByTime(3100); });
    expect(rows(v.host)[3].textContent).toContain("Leave game…");
    expect(sent).toEqual([]);
    v.unmount();
    vi.useRealTimers();
  });

  it("the sound row toggles and reports its state", () => {
    const v = render();
    act(() => btn(v.host).click());
    const sound = () => rows(v.host)[1] as HTMLButtonElement;
    const before = sound().getAttribute("aria-checked");
    act(() => sound().click());
    expect(sound().getAttribute("aria-checked")).not.toBe(before);
    act(() => sound().click());
    expect(sound().getAttribute("aria-checked")).toBe(before);
    v.unmount();
  });

  it("Escape closes it", () => {
    const v = render();
    act(() => btn(v.host).click());
    act(() => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); });
    expect(v.host.querySelector(".hud-menu")).toBeNull();
    v.unmount();
  });
});

describe("a signed-in player's rows", () => {
  it("shows the account name with Edit name, then Sign out; Edit name opens the form in place", async () => {
    auth.signedIn({ name: "Jerry Yu", email: "j@x", picture: null, display_name: "Cap", name_shown: "Cap" });
    const v = render();
    act(() => btn(v.host).click());
    const text = rows(v.host).map((r) => r.textContent);
    expect(text[3]).toContain("Cap"); expect(text[3]).toContain("Edit name");
    expect(text[4]).toContain("Sign out");
    expect(text[5]).toContain("Leave game");
    act(() => (rows(v.host)[3] as HTMLButtonElement).click());
    expect(v.host.querySelector(".hud-menu")).not.toBeNull();     // the menu stays open
    const input = v.host.querySelector<HTMLInputElement>(".hud-menu-edit .name-edit-input")!;
    expect(input.value).toBe("Cap");
    act(() => v.host.querySelector<HTMLButtonElement>(".name-edit-cancel")!.click());
    expect(v.host.querySelector(".name-edit")).toBeNull();
    expect(rows(v.host)[3].textContent).toContain("Edit name");
    v.unmount();
    auth.reset();
  });
});

describe("mute state is shared between controls (Codex, #653)", () => {
  it("toggling the HUD chip updates the menu's Sound row, and vice versa", () => {
    setMuted(false);
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => root.render(<><MuteButton /><HudMenu room="ABCD" kittyCount={8} /></>));
    const chip = () => host.querySelector<HTMLButtonElement>(".mute-btn")!;
    act(() => btn(host).click());
    const sound = () => rows(host)[1] as HTMLButtonElement;
    expect(sound().getAttribute("aria-checked")).toBe("true");
    act(() => chip().click());                       // mute from the chip...
    expect(isMuted()).toBe(true);
    expect(sound().getAttribute("aria-checked")).toBe("false");   // ...the menu row follows
    expect(sound().textContent).toContain("off");
    act(() => sound().click());                      // unmute from the menu...
    expect(isMuted()).toBe(false);
    expect(chip().textContent).toBe("🔊");            // ...the chip follows, and it was ONE tap
    act(() => root.unmount());
  });
});

describe("the account row (optional sign-in)", () => {
  it("is absent for a guest, and when signed in a refused sign-out keeps the menu open to retry", async () => {
    auth.reset();
    const v = render();
    act(() => btn(v.host).click());
    expect(rows(v.host).some((r) => r.textContent?.includes("Sign out"))).toBe(false);
    act(() => auth.signedIn({ name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" }));
    const row = () => rows(v.host).find((r) => r.textContent?.includes("Sign out")) as HTMLButtonElement;
    expect(rows(v.host).find((r) => r.textContent?.includes("Edit name"))?.textContent).toContain("Jerry");
    globalThis.fetch = vi.fn(async () => ({ status: 500, json: async () => ({}) })) as unknown as typeof fetch;
    await act(async () => { row().click(); });
    expect(v.host.querySelector(".hud-menu")).not.toBeNull();   // still open
    expect(row().textContent).toContain("Sign out failed, retry");
    expect(auth.state.status).toBe("in");
    globalThis.fetch = vi.fn(async () => ({ status: 200, json: async () => ({ ok: true }) })) as unknown as typeof fetch;
    await act(async () => { row().click(); });
    expect(v.host.querySelector(".hud-menu")).toBeNull();
    expect(auth.state.status).toBe("out");
    v.unmount();
    auth.reset();
  });
});
