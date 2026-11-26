import { describe, expect, it } from "vitest";
import {
  DeviceStamps, FIRST_KEY, LEGACY_SEEN_KEY, SESSION_GAP_MS, SESSION_KEY, type Store,
  dayOf, daysBetween, daysBucket, markPlayed, playedBefore, sessionBucket,
} from "./telemetryStamps";

function memStore(init: Record<string, string> = {}): Store & { data: Record<string, string> } {
  const data = { ...init };
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = v; },
    removeItem: (k) => { delete data[k]; },
  };
}

const DAY = 86_400_000;
const NOON = new Date(2026, 10, 25, 12, 0, 0).getTime();

describe("the buckets", () => {
  it("days since first seen", () => {
    expect([0, 1, 2, 7, 8, 30, 31, 400].map(daysBucket)).toEqual(["0", "1", "2-7", "2-7", "8-30", "8-30", "31+", "31+"]);
    expect(daysBucket(-3)).toBe("0");
  });
  it("sessions", () => {
    expect([1, 2, 3, 5, 6, 999].map(sessionBucket)).toEqual(["1", "2", "3-5", "3-5", "6+", "6+"]);
  });
  it("calendar days, not 24-hour spans", () => {
    expect(daysBetween("2026-11-25", "2026-11-26")).toBe(1);
    expect(daysBetween("2026-10-31", "2026-11-25")).toBe(25);
    expect(daysBetween("garbage", "2026-11-25")).toBeNull();
    expect(dayOf(new Date(2026, 0, 5, 23, 59).getTime())).toBe("2026-01-05");
  });
});

describe("the device's stamps", () => {
  it("a new device is day 0, session 1, and keeps only a date and a counter", () => {
    const s = memStore();
    const st = new DeviceStamps(() => s, () => NOON);
    expect(st.touch()).toBe(true);
    expect(st.days()).toBe("0");
    expect(st.sessionN()).toBe("1");
    expect(s.data[FIRST_KEY]).toBe("2026-11-25");
    expect(s.data[SESSION_KEY]).toMatch(/^1:\d+$/);
    expect(Object.keys(s.data).sort()).toEqual([FIRST_KEY, SESSION_KEY].sort());
  });

  it("days count from the first-seen date across loads", () => {
    const s = memStore();
    let now = NOON;
    new DeviceStamps(() => s, () => now).touch();
    now = NOON + 1 * DAY;
    expect(new DeviceStamps(() => s, () => now).days()).toBe("1");
    now = NOON + 9 * DAY;
    expect(new DeviceStamps(() => s, () => now).days()).toBe("8-30");
    now = NOON + 45 * DAY;
    expect(new DeviceStamps(() => s, () => now).days()).toBe("31+");
  });

  it("a session rolls over only after more than 30 idle minutes", () => {
    const s = memStore();
    let now = NOON;
    const st = new DeviceStamps(() => s, () => now);
    expect(st.touch()).toBe(true);
    now += SESSION_GAP_MS;               // exactly 30 minutes: the same session
    expect(st.touch()).toBe(false);
    expect(st.sessionN()).toBe("1");
    now += SESSION_GAP_MS + 60_000;      // 31 minutes idle: the second
    expect(st.touch()).toBe(true);
    expect(st.sessionN()).toBe("2");
    // a reload soon after is the same session; one later is the third
    now += 5 * 60_000;
    const again = new DeviceStamps(() => s, () => now);
    expect(again.touch()).toBe(false);
    expect(again.sessionN()).toBe("2");
    now += 2 * SESSION_GAP_MS;
    const later = new DeviceStamps(() => s, () => now);
    expect(later.touch()).toBe(true);
    expect(later.sessionN()).toBe("3-5");
  });

  it("a device an older build saw has no first-seen day: neither bucket is sent", () => {
    const s = memStore({ [LEGACY_SEEN_KEY]: "1" });
    const st = new DeviceStamps(() => s, () => NOON);
    st.touch();
    expect(st.days()).toBeNull();
    expect(st.sessionN()).toBeNull();
  });

  it("no storage: no buckets and no throw", () => {
    const st = new DeviceStamps(() => null, () => NOON);
    expect(st.touch()).toBe(true);
    expect(st.days()).toBeNull();
    expect(st.sessionN()).toBeNull();
    const throwing: Store = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    const st2 = new DeviceStamps(() => throwing, () => NOON);
    expect(() => st2.touch()).not.toThrow();
    expect(st2.days()).toBeNull();
  });

  it("an unreadable counter starts over", () => {
    const s = memStore({ [FIRST_KEY]: "2026-11-20", [SESSION_KEY]: "Jerry" });
    const st = new DeviceStamps(() => s, () => NOON);
    expect(st.touch()).toBe(true);
    expect(st.sessionN()).toBe("1");
    expect(st.days()).toBe("2-7");
  });

  it("first round played is a flag", () => {
    const s = memStore();
    expect(playedBefore(s)).toBe(false);
    markPlayed(s);
    expect(playedBefore(s)).toBe(true);
    expect(playedBefore(null)).toBe(false);
  });
});
