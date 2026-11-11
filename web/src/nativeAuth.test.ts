import { afterEach, describe, expect, it, vi } from "vitest";
import { resetNativeForTests } from "./native";
import {
  IOS_GOOGLE_CLIENT_ID, nativeGoogleAvailable, nativeGoogleCredential, nativeGoogleSignOut,
  resetNativeAuthForTests, SignInCancelled,
} from "./nativeAuth";

type Fn = ReturnType<typeof vi.fn>;

/** The bridge an app build injects: `Plugins` holds what the shell carries. */
function fakeShell(plugin: Record<string, Fn> | null) {
  const Plugins: Record<string, unknown> = plugin ? { SocialLogin: plugin } : {};
  (window as unknown as { Capacitor: unknown }).Capacitor = {
    isNativePlatform: () => true,
    isPluginAvailable: (name: string) => Object.prototype.hasOwnProperty.call(Plugins, name),
    Plugins,
  };
}

function socialLogin(login: Fn = vi.fn(() => Promise.resolve({ provider: "google", result: { idToken: "jwt.tok" } }))) {
  return { initialize: vi.fn(() => Promise.resolve()), login, logout: vi.fn(() => Promise.resolve()) };
}

afterEach(() => {
  delete (window as unknown as { Capacitor?: unknown }).Capacitor;
  resetNativeForTests();
  resetNativeAuthForTests();
});

describe("native Google sign-in", () => {
  it("is unavailable in a browser and in an app build without the plugin", () => {
    expect(nativeGoogleAvailable()).toBe(false);
    fakeShell(null);
    expect(nativeGoogleAvailable()).toBe(false);
  });

  it("initialises once with the iOS client and the web client as server audience, then returns the ID token", async () => {
    const p = socialLogin();
    fakeShell(p);
    expect(nativeGoogleAvailable()).toBe(true);
    expect(await nativeGoogleCredential("web.apps", "n1")).toBe("jwt.tok");
    expect(await nativeGoogleCredential("web.apps", "n2")).toBe("jwt.tok");
    expect(p.initialize).toHaveBeenCalledTimes(1);
    expect(p.initialize).toHaveBeenCalledWith({
      google: { iOSClientId: IOS_GOOGLE_CLIENT_ID, iOSServerClientId: "web.apps", mode: "online" },
    });
    expect(p.login.mock.calls.map((c) => c[0])).toEqual([
      { provider: "google", options: { scopes: ["email", "profile"], nonce: "n1" } },
      { provider: "google", options: { scopes: ["email", "profile"], nonce: "n2" } },
    ]);
  });

  it("reports a closed sheet as a cancellation, not an error", async () => {
    fakeShell(socialLogin(vi.fn(() => Promise.reject(Object.assign(new Error("x"), { code: "USER_CANCELLED" })))));
    await expect(nativeGoogleCredential("web.apps", "n")).rejects.toBeInstanceOf(SignInCancelled);
  });

  it("refuses a response without an ID token", async () => {
    fakeShell(socialLogin(vi.fn(() => Promise.resolve({ provider: "google", result: { idToken: null } }))));
    await expect(nativeGoogleCredential("web.apps", "n")).rejects.toThrow(/no ID token/);
  });

  it("sign-out forgets the device account and swallows a plugin failure", async () => {
    const p = socialLogin();
    p.logout = vi.fn(() => Promise.reject(new Error("not signed in")));
    fakeShell(p);
    await nativeGoogleSignOut();
    expect(p.logout).toHaveBeenCalledWith({ provider: "google" });
  });
});
