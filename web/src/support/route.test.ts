import { afterEach, describe, expect, it } from "vitest";
import { closeInfoPage, followInfoLink, openInfoPage, parseInfoPath } from "./route";

afterEach(() => { window.history.replaceState(null, "", "/"); });

describe("the support and privacy paths", () => {
  it("names the page for each path, with or without a trailing slash", () => {
    expect(parseInfoPath("/support")).toBe("support");
    expect(parseInfoPath("/support/")).toBe("support");
    expect(parseInfoPath("/privacy")).toBe("privacy");
    expect(parseInfoPath("/")).toBeNull();
    expect(parseInfoPath("/supportx")).toBeNull();
    expect(parseInfoPath("/support/more")).toBeNull();
  });

  it("opens in place and goes back to where it came from", () => {
    openInfoPage("privacy");
    expect(window.location.pathname).toBe("/privacy");
    expect((window.history.state as Record<string, unknown>).shengjiInfo).toBe(true);
  });

  it("closes a deep-linked page to the app's root", () => {
    window.history.replaceState(null, "", "/support");
    closeInfoPage();
    expect(window.location.pathname).toBe("/");
  });

  it("leaves a modified click to the browser", () => {
    let prevented = false;
    const e = { preventDefault: () => { prevented = true; }, metaKey: true };
    followInfoLink(e, "support");
    expect(prevented).toBe(false);
    expect(window.location.pathname).toBe("/");
    followInfoLink({ preventDefault: () => { prevented = true; } }, "support");
    expect(prevented).toBe(true);
    expect(window.location.pathname).toBe("/support");
  });
});
