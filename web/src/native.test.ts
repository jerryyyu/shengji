import { afterEach, describe, expect, it } from "vitest";
import { haptic, hapticCall, hideSplash, isNative, isPhone, lockFor, resetNativeForTests } from "./native";

type Calls = [string, string, unknown][];

function fakeShell(idiom: "phone" | "pad"): Calls {
  const calls: Calls = [];
  const plugin = (name: string) => new Proxy({}, {
    get: (_t, method: string) => (opts?: unknown) => {
      calls.push([name, method, opts]);
      return Promise.resolve(name === "ShengjiShell" && method === "idiom" ? { idiom } : undefined);
    },
  });
  (window as unknown as { Capacitor: unknown }).Capacitor = {
    isNativePlatform: () => true,
    registerPlugin: plugin,
  };
  return calls;
}

afterEach(() => {
  delete (window as unknown as { Capacitor?: unknown }).Capacitor;
  resetNativeForTests();
});

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("native bridge", () => {
  it("is a no-op in a browser", async () => {
    expect(isNative()).toBe(false);
    expect(await isPhone()).toBe(false);
    await lockFor("game");
    haptic("play");
    hideSplash();   // nothing to call, nothing thrown
  });

  it("locks an iPhone: the table to both landscapes, the lobby to portrait", async () => {
    const calls = fakeShell("phone");
    await lockFor("game");
    await lockFor("game");          // unchanged screen: no second call
    await lockFor("lobby");
    expect(calls.filter(([, m]) => m !== "idiom")).toEqual([
      ["ShengjiShell", "lockOrientation", { orientation: "landscape" }],
      ["ScreenOrientation", "lock", { orientation: "portrait" }],
    ]);
  });

  it("never locks an iPad", async () => {
    const calls = fakeShell("pad");
    await lockFor("game");
    await lockFor("lobby");
    expect(calls.map(([n, m]) => `${n}.${m}`)).toEqual(["ShengjiShell.idiom"]);
  });

  it("maps each table event to a UIKit feedback style", async () => {
    expect(hapticCall("play")).toEqual({ method: "impact", opts: { style: "LIGHT" } });
    expect(hapticCall("turn")).toEqual({ method: "impact", opts: { style: "MEDIUM" } });
    expect(hapticCall("declare")).toEqual({ method: "impact", opts: { style: "MEDIUM" } });
    expect(hapticCall("won")).toEqual({ method: "notification", opts: { type: "SUCCESS" } });
    const calls = fakeShell("phone");
    haptic("select");
    await flush();
    haptic("select");
    haptic("won");
    await flush();
    expect(calls.map(([n, m]) => `${n}.${m}`)).toEqual([
      "Haptics.selectionStart", "Haptics.selectionChanged", "Haptics.selectionChanged", "Haptics.notification",
    ]);
  });

  it("hides the splash once", () => {
    const calls = fakeShell("phone");
    hideSplash();
    hideSplash();
    expect(calls).toEqual([["SplashScreen", "hide", { fadeOutDuration: 200 }]]);
  });

  it("swallows a plugin the shell does not have", async () => {
    (window as unknown as { Capacitor: unknown }).Capacitor = {
      isNativePlatform: () => true,
      registerPlugin: () => ({ idiom: () => Promise.reject(new Error("not implemented")) }),
    };
    expect(await isPhone()).toBe(false);
  });
});
