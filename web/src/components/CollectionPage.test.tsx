// The Collection as one page: a tile selects its character into the stage at
// the top, in place, with no page and no history entry of its own; the
// colours and the one button under the stage follow the selection; a link to
// `#/collection/<kind>` selects that character and leaves the plain address.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthState, AuthUser } from "../auth";

const { authState } = vi.hoisted(() => ({
  authState: { current: { status: "out", clientId: "cid", user: null } as AuthState },
}));
vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));
vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return { ...real, useAuth: () => authState.current, auth: { updated: () => {}, get state() { return authState.current; } } };
});

import CollectionPage from "./CollectionPage";
import { forgetHomeSession } from "../home/session";
import { guestLookFor } from "../companion/look";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const puts: unknown[] = [];
const user: AuthUser = {
  name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry",
  rounds_played: 3, ranked_wins: 0, look: "tractor/red", companions: "individual", features: { collection: true },
};
beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  forgetHomeSession();
  window.history.replaceState(null, "", "/#/collection");
  puts.length = 0;
  globalThis.fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body ?? "{}"));
    if (url === "/api/me/look") puts.push(body);
    return { status: 200, json: async () => ({ ...user, ...body }) } as Response;
  }) as unknown as typeof fetch;
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  authState.current = { status: "out", clientId: "cid", user: null };
  window.history.replaceState(null, "", "/");
});
const draw = async () => {
  await act(async () => { root.render(<CollectionPage />); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
};
const tile = (name: string) => [...host.querySelectorAll<HTMLButtonElement>(".coll-tile")]
  .find((b) => b.querySelector(".coll-tile-name")!.textContent === name)!;
const stageKind = () => [...(host.querySelector(".char-stage svg.cmp")?.classList ?? [])]
  .find((c) => /^cmp-(tractor|bun|chick|sparrow|lamb|panda|rabbit|cat|fox|lion|dragon)$/.test(c));
const swatchNames = () => [...host.querySelectorAll(".char-swatches .coll-swatch")].map((s) => s.getAttribute("aria-label"));

describe("one page", () => {
  it("the stage shows the one in use; a tile selects its character into it, in place", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    expect(stageKind()).toBe("cmp-tractor");
    expect(tile("Tractor").classList.contains("selected")).toBe(true);
    const entries = window.history.length;
    await act(async () => { tile("Bun").click(); });
    expect(stageKind()).toBe("cmp-bun");
    expect(host.querySelector(".large-title")?.textContent).toBe("Collection");      // no page of its own
    expect(window.location.hash).toBe("#/collection");
    expect(window.history.length).toBe(entries);                                      // and no history entry
    expect(tile("Bun").classList.contains("selected")).toBe(true);
    expect(tile("Tractor").classList.contains("selected")).toBe(false);
    expect(tile("Tractor").querySelector(".coll-tick")).not.toBeNull();             // the one in use keeps its tick
    expect(host.querySelector(".coll-back, .edge-swipe")).toBeNull();
    // the grid stays under the stage
    expect(host.querySelector(".coll-yours")).not.toBeNull();
  });

  it("the colours, the status line and the one button follow the selection; Use puts the selected look in use", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    expect(swatchNames()[0]).toBe("Icon red");
    await act(async () => { tile("Chick").click(); });
    expect(swatchNames()).toHaveLength(4);
    expect(swatchNames()[0]).toMatch(/^Chick yellow/);
    expect(host.querySelector(".char-page .coll-status")?.textContent).toBe("Chick · Chick yellow");
    const use = host.querySelector<HTMLButtonElement>(".coll-use")!;
    expect(use.textContent).toBe("Use");
    await act(async () => { use.click(); await new Promise((r) => setTimeout(r, 0)); });
    expect(puts).toEqual([{ look: "chick/yellow" }]);
  });

  it("a link to a character selects it and leaves the plain address, with no history entry", async () => {
    window.history.replaceState(null, "", "/#/collection/sparrow");
    const entries = window.history.length;
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    expect(stageKind()).toBe("cmp-sparrow");
    expect(window.location.hash).toBe("#/collection");
    expect(window.history.length).toBe(entries);
  });

  it("the tiles stand still and only the stage moves; a tapped tile hops once and rests again", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    const figures = [...host.querySelectorAll(".coll-tile svg.cmp")];
    expect(figures.length).toBeGreaterThan(1);
    for (const f of figures) expect(f.classList.contains("cmp-rest")).toBe(true);
    expect(host.querySelector(".char-stage svg.cmp")!.classList.contains("cmp-rest")).toBe(false);
    await act(async () => { tile("Bun").click(); });
    const hopping = tile("Bun").querySelector("svg.cmp")!;
    expect(hopping.getAttribute("data-pose")).toBe("hop");
    expect(hopping.classList.contains("cmp-rest")).toBe(false);
    const ended = "AnimationEvent" in window ? "animationend" : "webkitAnimationEnd";
    await act(async () => { hopping.querySelector(".cmp-body")!.dispatchEvent(new Event(ended, { bubbles: true })); });
    const after = tile("Bun").querySelector("svg.cmp")!;
    expect(after.getAttribute("data-pose")).toBe("idle");
    expect(after.classList.contains("cmp-rest")).toBe(true);
  });

  it("on a phone a selection scrolls the page back up to the stage", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    const page = host.querySelector<HTMLElement>(".coll-page")!;
    const to = vi.fn();
    page.scrollTo = to as never;
    Object.defineProperty(page, "scrollTop", { value: 420, configurable: true });
    await act(async () => { tile("Sparrow").click(); });
    expect(to).toHaveBeenCalledWith({ top: 0, behavior: "smooth" });
  });
});

describe("the stage's line and button", () => {
  it("a locked colour says what unlocks it on the status line; the button stays Use, inert, at its size", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    const swatch = (name: string) => [...host.querySelectorAll<HTMLButtonElement>(".char-swatches .coll-swatch")]
      .find((s) => s.getAttribute("aria-label")!.startsWith(name))!;
    await act(async () => { swatch("Imperial yellow").click(); });
    expect(host.querySelector(".char-page .coll-status")?.textContent).toBe("Win 10 ranked rounds to unlock · 0 of 10");
    const use = host.querySelector<HTMLButtonElement>(".coll-use")!;
    expect(use.textContent).toBe("Use");
    expect(use.disabled).toBe(true);
  });

  it("a colour named as its companion is named once (麻雀, not 麻雀 · 麻雀)", async () => {
    const { setLanguageChoice } = await import("../i18n/locale");
    setLanguageChoice("zh-Hans");
    try {
      authState.current = { status: "in", clientId: "cid", user: { ...user, look: "sparrow/tree" } };
      await draw();
      expect(host.querySelector(".char-page .coll-status")?.textContent).toBe("麻雀");
      const swatch = [...host.querySelectorAll<HTMLButtonElement>(".char-swatches .coll-swatch")][1];
      await act(async () => { swatch.click(); });
      expect(host.querySelector(".char-page .coll-status")?.textContent).toBe("麻雀 · 文鸟灰");
    } finally {
      setLanguageChoice("system");
    }
  });
});

const names = () => [...host.querySelectorAll(".coll-yours .coll-tile-name")].map((n) => n.textContent);

describe("Yours", () => {
  it("is ordered by last use: the one in use first, then the latest used, then the rest in Collection order", async () => {
    authState.current = { status: "in", clientId: "cid",
      user: { ...user, look: "chick/ink", recent_looks: ["sparrow/java", "chick/ink", "bun/taro", "sparrow/tree"] } };
    await draw();
    expect(names()).toEqual(["Chick", "Sparrow", "Bun", "Tractor"]);
    expect(tile("Chick").querySelector(".coll-tick")).not.toBeNull();
  });

  it("keeps Collection order for an account that has used nothing, the one in use first", async () => {
    authState.current = { status: "in", clientId: "cid", user: { ...user, look: "sparrow/snow" } };
    await draw();
    expect(names()).toEqual(["Sparrow", "Tractor", "Bun", "Chick"]);
  });
});

describe("a guest", () => {
  it("wears the free look its device key draws, the same on every visit", async () => {
    window.localStorage.setItem("shengji.device", "AAAAAAAAAAAAAAAAAAAAAA");    // draws bun/taro
    await draw();
    expect(stageKind()).toBe("cmp-bun");
    expect(tile("Bun").querySelector(".coll-tick")).not.toBeNull();
    act(() => root.unmount());
    root = createRoot(host);
    await draw();
    expect(stageKind()).toBe("cmp-bun");
    expect(window.localStorage.getItem("shengji.device")).toBe("AAAAAAAAAAAAAAAAAAAAAA");
  });

  it("is given a device key, and so a look, on a first visit", async () => {
    window.localStorage.removeItem("shengji.device");
    await draw();
    const key = window.localStorage.getItem("shengji.device")!;
    expect(key).toMatch(/^[A-Za-z0-9_-]{22}$/);
    expect(stageKind()).toBe(`cmp-${guestLookFor(key).split("/")[0]}`);
    expect(host.querySelectorAll(".coll-yours .coll-tick")).toHaveLength(1);
  });
});
