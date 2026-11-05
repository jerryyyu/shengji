import { afterEach, describe, expect, it, vi } from "vitest";
import { parseHash, routeHash } from "./route";

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("games routes", () => {
  it("parses and builds the three pages", () => {
    expect(parseHash("#/games")).toEqual({ page: "list" });
    expect(parseHash("#/games/abc")).toEqual({ page: "game", id: "abc" });
    expect(parseHash("#/games/abc/rounds/3")).toEqual({ page: "replay", id: "abc", round: 3 });
    expect(routeHash({ page: "replay", id: "a b", round: 2 })).toBe("#/games/a%20b/rounds/2");
    expect(parseHash(routeHash({ page: "game", id: "a b" }))).toEqual({ page: "game", id: "a b" });
    expect(parseHash("")).toBeNull();
    expect(parseHash("#/other")).toBeNull();
  });

  it("reads a malformed escape as no route instead of throwing", () => {
    expect(parseHash("#/games/%")).toBeNull();
    expect(parseHash("#/games/%E0%A4%A/rounds/1")).toBeNull();
  });

  it("loads with a malformed hash and survives navigating to one", async () => {
    window.history.replaceState(null, "", "/#/games/%");
    vi.resetModules();
    const route = await import("./route");          // parses the hash at load
    const { act, createElement } = await import("react");
    const { createRoot } = await import("react-dom/client");
    let seen: unknown = "unset";
    function Probe() {
      seen = route.useGamesRoute();
      return null;
    }
    const host = document.createElement("div");
    const root = createRoot(host);
    await act(async () => { root.render(createElement(Probe)); });
    expect(seen).toBeNull();
    window.history.replaceState(null, "", "/#/games/abc");
    act(() => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(seen).toEqual({ page: "game", id: "abc" });
    window.history.replaceState(null, "", "/#/games/%zz/rounds/2");
    act(() => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(seen).toBeNull();
    window.history.replaceState(null, "", "/#/games/abc");
    act(() => { window.dispatchEvent(new PopStateEvent("popstate")); });
    expect(seen).toEqual({ page: "game", id: "abc" });
    window.history.replaceState(null, "", "/#/games/%");
    act(() => { window.dispatchEvent(new PopStateEvent("popstate")); });
    expect(seen).toBeNull();
    act(() => root.unmount());
  });
});
