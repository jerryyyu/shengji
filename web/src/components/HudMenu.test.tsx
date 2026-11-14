import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import HudMenu from "./HudMenu";
import MuteButton from "./MuteButton";
import { isMuted, setMuted } from "../audio";
import { auth } from "../auth";

const sent: unknown[] = [];
vi.mock("../ws", () => ({ conn: { send: (m: unknown) => { sent.push(m); }, reconnect: () => {} } }));
const goOnline = vi.fn();
vi.mock("./offlineGame", () => ({ offlineGame: { startFromPlay: () => {}, goOnline: () => goOnline() } }));

beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});
beforeEach(() => { sent.length = 0; });

function render(props: { ranked?: boolean; offline?: boolean } = {}) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<HudMenu room="ABCD" {...props} />));
  return { host, unmount: () => act(() => root.unmount()) };
}
const btn = (host: HTMLElement) => host.querySelector<HTMLButtonElement>(".hud-more-btn")!;
const rows = (host: HTMLElement) => Array.from(host.querySelectorAll<HTMLElement>(".hud-menu-row"));

describe("the phone overflow menu (#651)", () => {
  it("is closed until tapped, then lists the settings (Coach, Sound, How to play), invite and leave", () => {
    const v = render();
    expect(v.host.querySelector(".hud-menu")).toBeNull();
    expect(btn(v.host).getAttribute("aria-expanded")).toBe("false");
    act(() => btn(v.host).click());
    expect(btn(v.host).getAttribute("aria-expanded")).toBe("true");
    const text = rows(v.host).map((r) => r.textContent);
    expect(text[0]).toContain("Coach");
    expect(text[1]).toContain("Sound");
    expect(text[2]).toBe("How to play");
    expect(text[3]).toContain("Copy invite link");
    expect(text[4]).toContain("Leave game");
    // the kitty's count is no longer a menu row, and a browser has no Haptics
    expect(text.some((t) => t.includes("Kitty"))).toBe(false);
    expect(text.some((t) => t.includes("Haptics"))).toBe(false);
    v.unmount();
  });

  it("Leave game closes the menu and opens the leave sheet; Leave sends leave_room", () => {
    const v = render();
    act(() => btn(v.host).click());
    act(() => (rows(v.host)[4] as HTMLButtonElement).click());
    expect(sent).toEqual([]);
    expect(v.host.querySelector(".hud-menu")).toBeNull();
    const alert = v.host.querySelector("[role='alertdialog']")!;
    expect(alert.textContent).toContain("Leave the game?");
    expect(alert.textContent).toContain("A bot takes your seat and the others keep playing.");
    act(() => alert.querySelector<HTMLButtonElement>(".leave-sheet-leave")!.click());
    expect(sent).toEqual([{ type: "leave_room" }]);
    expect(v.host.querySelector("[role='alertdialog']")).toBeNull();
    v.unmount();
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

describe("a signed-in player's menu", () => {
  it("is the same five rows: account rows live on the Me tab", () => {
    auth.signedIn({ name: "Jerry Yu", email: "j@x", picture: null, display_name: "Cap", name_shown: "Cap" });
    const v = render();
    act(() => btn(v.host).click());
    const text = rows(v.host).map((r) => r.textContent ?? "");
    expect(text).toHaveLength(5);
    expect(text[0]).toContain("Coach");
    expect(text[1]).toContain("Sound");
    expect(text[2]).toContain("How to play");
    expect(text[3]).toContain("Copy invite link");
    expect(text[4]).toContain("Leave game");
    for (const gone of ["Edit name", "My games", "Sign out", "Cap"]) {
      expect(text.some((t) => t.includes(gone))).toBe(false);
    }
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
    act(() => root.render(<><MuteButton /><HudMenu room="ABCD" /></>));
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

describe("keyboard focus in the menu", () => {
  const key = (el: Element, k: string) => act(() => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true }));
  });
  const focused = () => (document.activeElement as HTMLElement | null)?.textContent ?? "";

  it("opening focuses the first actionable row; arrows wrap, Home and End go to the ends", () => {
    const v = render();
    const trigger = btn(v.host);
    trigger.focus();
    act(() => trigger.click());
    expect(focused()).toContain("Coach");
    key(document.activeElement!, "ArrowDown");
    expect(focused()).toContain("Sound");
    key(document.activeElement!, "ArrowDown");
    expect(focused()).toContain("How to play");
    key(document.activeElement!, "ArrowDown");
    expect(focused()).toContain("Copy invite link");
    key(document.activeElement!, "ArrowDown");
    expect(focused()).toContain("Leave game");
    key(document.activeElement!, "ArrowDown");
    expect(focused()).toContain("Coach");             // wraps
    key(document.activeElement!, "ArrowUp");
    expect(focused()).toContain("Leave game");
    key(document.activeElement!, "Home");
    expect(focused()).toContain("Coach");
    key(document.activeElement!, "End");
    expect(focused()).toContain("Leave game");
    v.unmount();
  });

  it("ArrowDown and ArrowUp on the closed button open it at the first and last row", () => {
    const v = render();
    btn(v.host).focus();
    key(btn(v.host), "ArrowDown");
    expect(v.host.querySelector(".hud-menu")).not.toBeNull();
    expect(focused()).toContain("Coach");
    key(document.activeElement!, "Escape");
    key(btn(v.host), "ArrowUp");
    expect(focused()).toContain("Leave game");
    v.unmount();
  });

  it("Escape closes the menu and returns focus to the More button", () => {
    const v = render();
    act(() => btn(v.host).click());
    key(document.activeElement!, "ArrowDown");
    key(document.activeElement!, "Escape");
    expect(v.host.querySelector(".hud-menu")).toBeNull();
    expect(document.activeElement).toBe(btn(v.host));
    v.unmount();
  });

  it("the leave sheet focuses Stay; Stay returns focus to the More button", () => {
    const v = render();
    act(() => btn(v.host).click());
    key(document.activeElement!, "End");
    act(() => (document.activeElement as HTMLButtonElement).click());
    expect(focused()).toBe("Stay");
    act(() => (document.activeElement as HTMLButtonElement).click());
    expect(v.host.querySelector("[role='alertdialog']")).toBeNull();
    expect(document.activeElement).toBe(btn(v.host));
    expect(sent).toEqual([]);
    v.unmount();
  });

  it("an outside tap still closes it", () => {
    const v = render();
    act(() => btn(v.host).click());
    act(() => { document.body.dispatchEvent(new Event("pointerdown", { bubbles: true })); });
    expect(v.host.querySelector(".hud-menu")).toBeNull();
    v.unmount();
  });
});

describe("the menu's scale-and-fade", () => {
  const reduceMotion = (on: boolean) => {
    const mm = window.matchMedia;
    window.matchMedia = ((q: string) => ({ matches: on && q.includes("reduce"), media: q })) as unknown as typeof window.matchMedia;
    return () => { window.matchMedia = mm; };
  };
  const canAnimate = () => {
    const had = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "animate");
    Object.defineProperty(HTMLElement.prototype, "animate", { configurable: true, value: () => ({}) });
    return () => {
      if (had) Object.defineProperty(HTMLElement.prototype, "animate", had);
      else Reflect.deleteProperty(HTMLElement.prototype, "animate");
    };
  };

  it("pops in, stays through its fade out, then goes", () => {
    vi.useFakeTimers();
    const restore = [reduceMotion(false), canAnimate()];
    try {
      const v = render();
      act(() => btn(v.host).click());
      expect(v.host.querySelector(".hud-menu")!.classList.contains("pop-in")).toBe(true);
      act(() => btn(v.host).click());
      const menu = v.host.querySelector(".hud-menu")!;
      expect(menu.classList.contains("pop-out")).toBe(true);
      expect(menu.getAttribute("aria-hidden")).toBe("true");
      act(() => { vi.advanceTimersByTime(199); });
      expect(v.host.querySelector(".hud-menu")).not.toBeNull();
      act(() => { vi.advanceTimersByTime(1); });
      expect(v.host.querySelector(".hud-menu")).toBeNull();
      v.unmount();
    } finally { restore.forEach((r) => r()); vi.useRealTimers(); }
  });

  it("under Reduce Motion appears and goes at once, with no animation class", () => {
    const restore = [reduceMotion(true), canAnimate()];
    try {
      const v = render();
      act(() => btn(v.host).click());
      const menu = v.host.querySelector(".hud-menu")!;
      expect(menu.classList.contains("pop-in")).toBe(false);
      expect(menu.classList.contains("pop-out")).toBe(false);
      act(() => btn(v.host).click());
      expect(v.host.querySelector(".hud-menu")).toBeNull();
      v.unmount();
    } finally { restore.forEach((r) => r()); }
  });
});

describe("a ranked game's leave sheet", () => {
  it("names the ranked game and its result", () => {
    const v = render({ ranked: true });
    act(() => btn(v.host).click());
    act(() => (rows(v.host)[4] as HTMLButtonElement).click());
    const alert = v.host.querySelector("[role='alertdialog']")!;
    expect(alert.querySelector("h2")!.textContent).toBe("Leave the game?");
    expect(alert.querySelector("p")!.textContent).toBe("A bot takes your seat. This round counts as at best a draw for you.");
    expect(Array.from(alert.querySelectorAll("button")).map((b) => b.textContent)).toEqual(["Stay", "Leave"]);
    v.unmount();
  });

  it("Escape keeps playing and sends nothing", () => {
    const v = render({ ranked: true });
    act(() => btn(v.host).click());
    act(() => (rows(v.host)[4] as HTMLButtonElement).click());
    const alert = v.host.querySelector("[role='alertdialog']")!;
    act(() => { alert.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    expect(v.host.querySelector("[role='alertdialog']")).toBeNull();
    expect(sent).toEqual([]);
    v.unmount();
  });

  it("waits with no timer", () => {
    vi.useFakeTimers();
    const v = render({ ranked: true });
    act(() => btn(v.host).click());
    act(() => (rows(v.host)[4] as HTMLButtonElement).click());
    act(() => { vi.advanceTimersByTime(30_000); });
    expect(v.host.querySelector("[role='alertdialog']")).not.toBeNull();
    expect(sent).toEqual([]);
    v.unmount();
    vi.useRealTimers();
  });
});

describe("the offline menu", () => {
  it("Leave ends practice: a short alert, then leave_room (App's start screen takes the player home)", () => {
    goOnline.mockClear();
    const v = render({ offline: true });
    act(() => btn(v.host).click());
    act(() => rows(v.host).find((r) => r.classList.contains("leave"))!.click());
    const alert = v.host.querySelector("[role='alertdialog']")!;
    expect(alert.querySelector("h2")!.textContent).toBe("Leave the game?");
    expect(alert.querySelector("p")!.textContent).toBe("This offline game ends.");
    expect(goOnline).not.toHaveBeenCalled();
    act(() => alert.querySelector<HTMLButtonElement>(".leave-sheet-leave")!.click());
    expect(sent).toEqual([{ type: "leave_room" }]);
    expect(v.host.querySelector("[role='alertdialog']")).toBeNull();
    v.unmount();
  });

  it("Stay keeps you in the offline game", () => {
    goOnline.mockClear();
    const v = render({ offline: true });
    act(() => btn(v.host).click());
    act(() => rows(v.host).find((r) => r.classList.contains("leave"))!.click());
    act(() => v.host.querySelector<HTMLButtonElement>(".leave-sheet-stay")!.click());
    expect(sent).toEqual([]);
    expect(goOnline).not.toHaveBeenCalled();
    v.unmount();
  });

  it("has no invite link and no Play online, with the network up or coming back", () => {
    goOnline.mockClear();
    const v = render({ offline: true });
    act(() => btn(v.host).click());
    const text = () => rows(v.host).map((r) => r.textContent ?? "");
    expect(text().some((t) => t.includes("Copy invite link"))).toBe(false);
    expect(text()).not.toContain("Play online");
    act(() => { window.dispatchEvent(new Event("online")); });
    expect(text()).not.toContain("Play online");
    expect(goOnline).not.toHaveBeenCalled();
    v.unmount();
  });
});
