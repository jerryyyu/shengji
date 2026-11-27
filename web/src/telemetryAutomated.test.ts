import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./ws", () => ({ conn: { send: () => true } }));

type Batch = Record<string, unknown>;

/** A fresh page load at `url`: the telemetry module evaluated anew, as on a navigation. */
async function load(url: string) {
  window.history.replaceState(null, "", url);
  vi.resetModules();
  return import("./telemetry");
}

/** An app_open buffered on the loaded page; `flush()` sends it and returns the batch. */
function buffered(mod: typeof import("./telemetry")): { flush: () => Batch } {
  const sent: Batch[] = [];
  const t = new mod.Telemetry((m) => { sent.push(m as Batch); return true; }, true);
  t.appOpen(true);
  return { flush: () => { t.flush(); return sent[0]; } };
}

afterEach(() => { window.history.replaceState(null, "", "/"); localStorage.clear(); });

describe("the automation marker is taken when the page loads", () => {
  it("a ?e2e=1 load stays marked after the page routes away before its first flush", async () => {
    localStorage.clear();
    const mod = await load("/?e2e=1");
    const page = buffered(mod);
    expect(localStorage.getItem(mod.AUTOMATED_KEY)).toBe("1");   // persisted at load, not at a flush
    window.history.pushState(null, "", "/privacy");               // the route drops the query
    expect(page.flush()).toMatchObject({ automated: true });
  });

  it("a person's load that routes the same way sends no marker", async () => {
    localStorage.clear();
    const mod = await load("/");
    const page = buffered(mod);
    expect(localStorage.getItem(mod.AUTOMATED_KEY)).toBeNull();
    window.history.pushState(null, "", "/privacy");
    expect(page.flush()).not.toHaveProperty("automated");
  });

  it("the harness's flag set before the load, or a WebDriver browser, marks the page", async () => {
    localStorage.clear();
    localStorage.setItem("shengji.automated", "1");
    expect(buffered(await load("/")).flush()).toMatchObject({ automated: true });
    localStorage.clear();
    const mod = await load("/");
    Object.defineProperty(navigator, "webdriver", { value: true, configurable: true });
    try {
      expect(buffered(mod).flush()).toMatchObject({ automated: true });
    } finally {
      delete (navigator as { webdriver?: boolean }).webdriver;
    }
  });

  it("a ?e2e=1 load keeps the origin marked for its later loads", async () => {
    localStorage.clear();
    await load("/?e2e=1");
    expect(buffered(await load("/")).flush()).toMatchObject({ automated: true });
  });
});
