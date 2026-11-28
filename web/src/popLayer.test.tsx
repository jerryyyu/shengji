import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeAll, describe, expect, it, vi } from "vitest";
import HudMenu from "./components/HudMenu";
import { PopLayer } from "./popLayer";

vi.mock("./ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));

beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});

/** HudMenu in a table screen whose header clips, as the phone table's does. */
function table() {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(
    <div className="table-screen">
      <div className="hud" style={{ overflowX: "clip" }}><HudMenu room="ABCD" /></div>
      <PopLayer />
    </div>,
  ));
  return { host, unmount: () => { act(() => root.unmount()); host.remove(); } };
}

describe("a pop-up opened from the table's header", () => {
  it("is drawn in the screen's pop-up layer, outside the header, placed at its anchor", () => {
    const v = table();
    act(() => v.host.querySelector<HTMLButtonElement>(".hud-more-btn")!.click());
    const menu = v.host.querySelector<HTMLElement>(".hud-menu")!;
    expect(menu.parentElement!.className).toBe("pop-layer");
    expect(v.host.querySelector(".hud .hud-menu")).toBeNull();
    expect(menu.style.getPropertyValue("--anchor-b")).toMatch(/px$/);
    expect(menu.style.getPropertyValue("--anchor-r")).toMatch(/px$/);
    v.unmount();
  });

  it("stays open for a tap on its own rows, closes for a tap elsewhere and on Escape, focus back on ⋯", () => {
    const v = table();
    const btn = v.host.querySelector<HTMLButtonElement>(".hud-more-btn")!;
    act(() => btn.click());
    const row = v.host.querySelector<HTMLElement>(".pop-layer [role=menuitem], .pop-layer [role=menuitemcheckbox]")!;
    act(() => { row.dispatchEvent(new Event("pointerdown", { bubbles: true })); });
    expect(v.host.querySelector(".hud-menu")).not.toBeNull();
    act(() => { document.body.dispatchEvent(new Event("pointerdown", { bubbles: true })); });
    expect(v.host.querySelector(".hud-menu")).toBeNull();
    btn.focus();
    act(() => { btn.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })); });
    expect(v.host.querySelector(".pop-layer")!.contains(document.activeElement)).toBe(true);
    act(() => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); });
    expect(v.host.querySelector(".hud-menu")).toBeNull();
    expect(document.activeElement).toBe(btn);
    v.unmount();
  });
});
