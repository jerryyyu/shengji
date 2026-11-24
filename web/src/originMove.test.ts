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
  const confirms: unknown[] = [];
  const shell = { postMessage: (body: unknown) => { confirms.push(body); } };
  return {
    __shengjiOriginMove: handoff as never, location: { origin }, localStorage: storage,
    webkit: { messageHandlers: { shengjiOriginMove: shell } }, confirms,
  };
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

  it("survives storage that refuses every read", () => {
    const refused = { ...memoryStorage(), getItem: vi.fn(() => { throw new Error("SecurityError"); }) };
    const p = page({ origin: ORIGIN, entries: { a: "1" } }, refused as Storage);
    expect(applyOriginMove(p)).toBe(0);
    expect(p.confirms).toEqual([]);
  });

  it("a key that cannot be written withholds completion; the retry writes the rest and keeps what is there", () => {
    const storage = memoryStorage({ "shengji.muted": "1" });     // the new origin's own value
    const setItem = storage.setItem.bind(storage);
    let full = true;
    storage.setItem = (k, v) => {
      if (full && k === "shengji.room") throw new DOMException("quota", "QuotaExceededError");
      setItem(k, v);
    };
    const handoff = {
      origin: ORIGIN, session: true,
      entries: { "shengji.haptics": "0", "shengji.room": "AB12", "shengji.muted": "0" },
    };
    const first = page(handoff, storage);
    expect(applyOriginMove(first)).toBe(1);
    expect(storage.getItem("shengji.haptics")).toBe("0");
    expect(storage.getItem("shengji.room")).toBeNull();
    expect(storage.getItem(MOVED_MARK)).toBeNull();             // not marked
    expect(first.confirms).toEqual([]);                         // not confirmed: offered again
    expect(takeMovedSignIn("out")).toBe(false);                 // no ask until the move is done

    full = false;                                               // the next launch has room
    storage.setItem("shengji.haptics", "1");                    // changed on the new origin meanwhile
    const retry = page(handoff, storage);
    expect(applyOriginMove(retry)).toBe(1);                     // only the missing seat
    expect(storage.getItem("shengji.room")).toBe("AB12");
    expect(storage.getItem("shengji.haptics")).toBe("1");       // present keys are never overwritten
    expect(storage.getItem("shengji.muted")).toBe("1");
    expect(storage.getItem(MOVED_MARK)).toBe("1");
    expect(retry.confirms).toEqual(["imported"]);
    expect(takeMovedSignIn("out")).toBe(true);
  });

  it("a key whose read fails withholds completion too", () => {
    const storage = memoryStorage();
    const getItem = storage.getItem.bind(storage);
    storage.getItem = (k) => { if (k === "b") throw new Error("SecurityError"); return getItem(k); };
    const p = page({ origin: ORIGIN, entries: { a: "1", b: "2" } }, storage);
    applyOriginMove(p);
    expect(storage.getItem("a")).toBe("1");
    expect(getItem(MOVED_MARK)).toBeNull();
    expect(p.confirms).toEqual([]);
  });
});

describe("confirming the import to the shell", () => {
  it("confirms once the mark is kept and drops the handoff from the page", () => {
    const p = page({ origin: ORIGIN, entries: { "shengji.room": "AB12" } });
    applyOriginMove(p);
    expect(p.confirms).toEqual(["imported"]);
    expect(p.__shengjiOriginMove).toBeUndefined();
  });

  it("a launch killed after the write but before the shell heard it: the next offer writes nothing and confirms", () => {
    const storage = memoryStorage();
    const first = page({ origin: ORIGIN, entries: { "shengji.room": "AB12" }, session: true }, storage);
    first.webkit.messageHandlers.shengjiOriginMove.postMessage = () => { throw new Error("process gone"); };
    applyOriginMove(first);
    resetOriginMoveForTests();
    storage.removeItem("shengji.room");            // the player left the seat since
    const again = page({ origin: ORIGIN, entries: { "shengji.room": "AB12" }, session: true }, storage);
    expect(applyOriginMove(again)).toBe(0);
    expect(storage.getItem("shengji.room")).toBeNull();
    expect(again.confirms).toEqual(["imported"]);
    expect(takeMovedSignIn("out")).toBe(false);    // a sign-out since then sticks
  });

  it("does not confirm when the mark cannot be kept, so the next launch offers it again", () => {
    const storage = memoryStorage();
    const setItem = storage.setItem.bind(storage);
    storage.setItem = (k, v) => { if (k === MOVED_MARK) throw new Error("QuotaExceededError"); setItem(k, v); };
    const p = page({ origin: ORIGIN, entries: { a: "1" } }, storage);
    applyOriginMove(p);
    expect(p.confirms).toEqual([]);
  });

  it("never confirms on another origin or without a handoff", () => {
    const off = page({ origin: ORIGIN, entries: { a: "1" } }, memoryStorage(), "https://shengji.fly.dev");
    applyOriginMove(off);
    const none = page(undefined);
    applyOriginMove(none);
    expect(off.confirms).toEqual([]);
    expect(none.confirms).toEqual([]);
  });

  it("a first launch offline, then online in a later launch: imported then, once", () => {
    const storage = memoryStorage();
    const handoff = { origin: ORIGIN, entries: { "shengji.name": "Mei" } };
    const offline = page(handoff, memoryStorage(), "capacitor://localhost");
    expect(applyOriginMove(offline)).toBe(0);
    expect(offline.confirms).toEqual([]);          // nothing confirmed: the shell offers it again
    const online = page(handoff, storage);
    expect(applyOriginMove(online)).toBe(1);
    expect(online.confirms).toEqual(["imported"]);
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
