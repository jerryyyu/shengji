import { afterEach, describe, expect, it } from "vitest";
import { keychainAvailable, keychainGet, keychainRemove, keychainSet } from "./keychain";

type Calls = [string, string, unknown][];

function setBridge(bridge: unknown) {
  (window as unknown as { Capacitor?: unknown }).Capacitor = bridge;
}

/** An app shell whose plugin keeps the value in memory. */
function fakeShell(): Calls {
  const calls: Calls = [];
  let stored: string | null = null;
  const methods: Record<string, (opts?: { value?: string }) => Promise<unknown>> = {
    get: async () => ({ value: stored }),
    set: async (opts) => { stored = opts?.value ?? null; },
    remove: async () => { stored = null; },
  };
  setBridge({
    isNativePlatform: () => true,
    isPluginAvailable: (name: string) => name === "ShengjiKeychain",
    registerPlugin: (name: string) => new Proxy({}, {
      get: (_t, m: string) => (opts?: { value?: string }) => {
        calls.push([name, m, opts]);
        return methods[m](opts);
      },
    }),
  });
  return calls;
}

afterEach(() => {
  delete (window as unknown as { Capacitor?: unknown }).Capacitor;
});

describe("keychain", () => {
  it("has no Keychain in a browser: get is null, set and remove do nothing", async () => {
    expect(keychainAvailable()).toBe(false);
    await keychainSet("secret");
    expect(await keychainGet()).toBeNull();
    await keychainRemove();
    expect(await keychainGet()).toBeNull();
  });

  it("has no Keychain when the bridge is not native", async () => {
    let touched = false;
    setBridge({
      isNativePlatform: () => false,
      registerPlugin: () => { touched = true; return {}; },
    });
    expect(await keychainGet()).toBeNull();
    await keychainSet("secret");
    expect(touched).toBe(false);
  });

  it("has no Keychain in an app build that predates the plugin", async () => {
    let touched = false;
    setBridge({
      isNativePlatform: () => true,
      isPluginAvailable: () => false,
      registerPlugin: () => { touched = true; return {}; },
    });
    expect(keychainAvailable()).toBe(false);
    expect(await keychainGet()).toBeNull();
    await keychainSet("secret");
    await keychainRemove();
    expect(touched).toBe(false);
  });

  it("stores, reads and removes through the plugin in the app", async () => {
    const calls = fakeShell();
    expect(keychainAvailable()).toBe(true);
    expect(await keychainGet()).toBeNull();
    await keychainSet("secret");
    expect(await keychainGet()).toBe("secret");
    await keychainRemove();
    expect(await keychainGet()).toBeNull();
    expect(calls.map(([, m, o]) => [m, o])).toEqual([
      ["get", undefined], ["set", { value: "secret" }], ["get", undefined],
      ["remove", undefined], ["get", undefined],
    ]);
  });

  it("passes a plugin rejection through", async () => {
    setBridge({
      isNativePlatform: () => true,
      registerPlugin: () => ({ get: () => Promise.reject(Object.assign(new Error("keychain error -25308"), { code: "-25308" })) }),
    });
    await expect(keychainGet()).rejects.toMatchObject({ code: "-25308" });
  });

  it("refuses an empty value", async () => {
    await expect(keychainSet("")).rejects.toThrow();
  });
});
