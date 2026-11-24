import { afterEach, describe, expect, it, vi } from "vitest";
import { MOVED_MARK, applyOriginMove, resetOriginMoveForTests, takeMovedSignIn } from "./originMove";

const ORIGIN = "https://playshengji.com";

function memoryStorage(initial: Record<string, string> = {}): Storage {
  const m = new Map(Object.entries(initial));
  return {
    get length() { return m.size; },
    key: (i: number) => [...m.keys()][i] ?? null,
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => { m.set(k, String(v)); },
    removeItem: (k: string) => { m.delete(k); },
    clear: () => { m.clear(); },
  };
}

function page(handoff: unknown, storage: Storage = memoryStorage(), origin = ORIGIN) {
  return { __shengjiOriginMove: handoff as never, location: { origin }, localStorage: storage };
}

afterEach(() => { resetOriginMoveForTests(); });

describe("applyOriginMove", () => {
  it("writes each key the new origin lacks and marks the install moved", () => {
    const storage = memoryStorage({ "shengji.muted": "1" });
    const wrote = applyOriginMove(page({
      origin: ORIGIN, session: false,
      entries: { "shengji.name": "Mei", "shengji.muted": "0", "shengji.haptics": "0" },
    }, storage));
    expect(wrote).toBe(2);
    expect(storage.getItem("shengji.name")).toBe("Mei");
    expect(storage.getItem("shengji.haptics")).toBe("0");
    expect(storage.getItem("shengji.muted")).toBe("1"); // the new origin's own value wins
    expect(storage.getItem(MOVED_MARK)).toBe("1");
  });

  it("writes nothing a second time, so a key removed since stays removed", () => {
    const storage = memoryStorage();
    const handoff = { origin: ORIGIN, entries: { "shengji.room": "AB12" } };
    expect(applyOriginMove(page(handoff, storage))).toBe(1);
    storage.removeItem("shengji.room");
    expect(applyOriginMove(page(handoff, storage))).toBe(0);
    expect(storage.getItem("shengji.room")).toBeNull();
  });

  it("does nothing without a handoff: the website and every later launch", () => {
    const storage = memoryStorage();
    expect(applyOriginMove(page(undefined, storage))).toBe(0);
    expect(applyOriginMove(page(null, storage))).toBe(0);
    expect(applyOriginMove(page("x", storage))).toBe(0);
    expect(storage.length).toBe(0);
  });

  it("does nothing on another origin, such as the bundled offline page", () => {
    const storage = memoryStorage();
    const handoff = { origin: ORIGIN, entries: { a: "1" }, session: true };
    expect(applyOriginMove(page(handoff, storage, "capacitor://localhost"))).toBe(0);
    expect(storage.length).toBe(0);
    expect(takeMovedSignIn("out")).toBe(false);
  });

  it("keeps string values only and never writes the mark from the old origin", () => {
    const storage = memoryStorage();
    applyOriginMove(page({ origin: ORIGIN, entries: { a: "1", n: 2, o: {}, [MOVED_MARK]: "x" } }, storage));
    expect(storage.getItem("a")).toBe("1");
    expect(storage.getItem("n")).toBeNull();
    expect(storage.getItem("o")).toBeNull();
    expect(storage.getItem(MOVED_MARK)).toBe("1");
  });

  it("survives storage that refuses a write or every read", () => {
    const full = memoryStorage();
    const setItem = full.setItem.bind(full);
    full.setItem = (k, v) => { if (k === "big") throw new Error("QuotaExceededError"); setItem(k, v); };
    expect(applyOriginMove(page({ origin: ORIGIN, entries: { big: "x", small: "y" } }, full))).toBe(1);
    expect(full.getItem("small")).toBe("y");
    const refused = { ...memoryStorage(), getItem: vi.fn(() => { throw new Error("SecurityError"); }) };
    expect(applyOriginMove(page({ origin: ORIGIN, entries: { a: "1" } }, refused as Storage))).toBe(0);
  });
});

describe("takeMovedSignIn", () => {
  const signedIn = () => applyOriginMove(page({ origin: ORIGIN, entries: {}, session: true }));

  it("asks once when the old origin was signed in and the new one is not", () => {
    signedIn();
    expect(takeMovedSignIn("out")).toBe(true);
    expect(takeMovedSignIn("out")).toBe(false);
  });

  it("does not ask when the session carried over or the keychain restored it", () => {
    signedIn();
    expect(takeMovedSignIn("in")).toBe(false);
    expect(takeMovedSignIn("out")).toBe(false);
  });

  it("does not ask with sign-in off or unreachable", () => {
    signedIn();
    expect(takeMovedSignIn("off")).toBe(false);
    signedIn();
    expect(takeMovedSignIn("error")).toBe(false);
  });

  it("waits while sign-in is still loading", () => {
    signedIn();
    expect(takeMovedSignIn("loading")).toBe(false);
    expect(takeMovedSignIn(undefined)).toBe(false);
    expect(takeMovedSignIn("out")).toBe(true);
  });

  it("does not ask for a guest or a device-only install the old origin had no session for", () => {
    applyOriginMove(page({ origin: ORIGIN, entries: { a: "1" }, session: false }));
    expect(takeMovedSignIn("out")).toBe(false);
  });

  it("does not ask on a page after the handoff was written", () => {
    const storage = memoryStorage();
    applyOriginMove(page({ origin: ORIGIN, entries: {}, session: true }, storage));
    resetOriginMoveForTests(); // a reload in the same launch
    applyOriginMove(page({ origin: ORIGIN, entries: {}, session: true }, storage));
    expect(takeMovedSignIn("out")).toBe(false);
  });
});
