import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetNativeForTests } from "../native";
import { resetNativeAuthForTests } from "../nativeAuth";

const { gis, loginWithApple, loginWithGoogle, signedIn } = vi.hoisted(() => ({
  gis: { initialize: vi.fn(), renderButton: vi.fn(), disableAutoSelect: vi.fn() },
  loginWithApple: vi.fn(),
  loginWithGoogle: vi.fn(),
  signedIn: vi.fn(),
}));
vi.mock("../ws", () => ({ conn: { reconnect: () => {} } }));
vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return { ...real, loadGis: () => Promise.resolve(gis), loginWithApple, loginWithGoogle, auth: { signedIn } };
});

import GoogleSignIn from "./GoogleSignIn";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

async function render() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => root.render(<GoogleSignIn clientId="web.apps" />));
}

function fakeShell(plugin: Record<string, unknown> | null, platform?: string) {
  const Plugins: Record<string, unknown> = plugin ? { SocialLogin: plugin } : {};
  (window as unknown as { Capacitor: unknown }).Capacitor = {
    isNativePlatform: () => true,
    ...(platform ? { getPlatform: () => platform } : {}),
    isPluginAvailable: (name: string) => name in Plugins,
    Plugins,
  };
}

beforeEach(() => {
  gis.initialize.mockClear();
  gis.renderButton.mockClear();
  loginWithApple.mockReset();
  loginWithGoogle.mockReset();
  signedIn.mockClear();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  delete (window as unknown as { Capacitor?: unknown }).Capacitor;
  resetNativeForTests();
  resetNativeAuthForTests();
});

describe("GoogleSignIn", () => {
  it("in a browser renders the GIS button, as before", async () => {
    await render();
    expect(gis.initialize).toHaveBeenCalledTimes(1);
    expect(host.querySelector(".google-signin-slot")).not.toBeNull();
    expect(host.querySelector(".google-signin-native")).toBeNull();
    expect(host.querySelector("[data-testid='apple-signin']")).toBeNull();
  });

  it("in the app posts the native ID token with its nonce and signs in", async () => {
    const login = vi.fn((_opts: { options: { nonce: string } }) =>
      Promise.resolve({ provider: "google", result: { idToken: "jwt.tok" } }));
    fakeShell({ initialize: vi.fn(() => Promise.resolve()), login, logout: vi.fn() });
    const user = { name: "Jerry Yu", email: "j@example.com", picture: null, display_name: null, name_shown: "Jerry" };
    loginWithGoogle.mockResolvedValue(user);
    await render();
    expect(gis.initialize).not.toHaveBeenCalled();
    const button = host.querySelector<HTMLButtonElement>(".google-signin-native")!;
    expect(button.textContent).toBe("Continue with Google");
    await act(async () => button.click());
    const nonce = login.mock.calls[0][0].options.nonce;
    expect(nonce).toMatch(/^[0-9a-f]{32}$/);
    expect(loginWithGoogle).toHaveBeenCalledWith("jwt.tok", nonce);
    expect(signedIn).toHaveBeenCalledWith(user);
    expect(host.querySelector(".lobby-error")).toBeNull();
  });

  it("in the app a cancelled sheet shows no error, a refused token does", async () => {
    const login = vi.fn()
      .mockRejectedValueOnce(Object.assign(new Error("cancel"), { code: "USER_CANCELLED" }))
      .mockResolvedValueOnce({ provider: "google", result: { idToken: "jwt.tok" } });
    fakeShell({ initialize: vi.fn(() => Promise.resolve()), login, logout: vi.fn() });
    loginWithGoogle.mockRejectedValue(new Error("Sign-in rejected (bad_audience)."));
    await render();
    const button = host.querySelector<HTMLButtonElement>(".google-signin-native")!;
    await act(async () => button.click());
    expect(host.querySelector(".lobby-error")).toBeNull();
    await act(async () => button.click());
    expect(host.querySelector(".lobby-error")?.textContent).toBe("Sign-in rejected (bad_audience).");
    expect(signedIn).not.toHaveBeenCalled();
  });

  it("in an app build without the plugin shows a note and no button", async () => {
    fakeShell(null);
    await render();
    expect(host.querySelector("button")).toBeNull();
    expect(host.querySelector("[data-testid='google-signin-unavailable']")?.textContent).toBe("Update the app to sign in.");
    expect(gis.initialize).not.toHaveBeenCalled();
  });
});

async function sha256(text: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(d), (b) => b.toString(16).padStart(2, "0")).join("");
}

describe("Sign in with Apple", () => {
  beforeEach(() => {
    const digest = crypto.subtle.digest.bind(crypto.subtle);
    vi.spyOn(crypto.subtle, "digest").mockImplementation(async (...args) => {
      await new Promise((resolve) => setTimeout(resolve, 25));
      return digest(...args);
    });
  });
  afterEach(() => vi.restoreAllMocks());
  it("shows beside the Google button on iOS and posts the token, code, raw nonce and name", async () => {
    const initialize = vi.fn((_opts: Record<string, unknown>) => Promise.resolve());
    const login = vi.fn((_opts: { provider: string; options: { nonce: string } }) => Promise.resolve({
      provider: "apple",
      result: {
        idToken: "apple.jwt", authorizationCode: "code-1", accessToken: null,
        profile: { user: "001.abc", email: "", givenName: "Ann", familyName: "Lee" },
      },
    }));
    fakeShell({ initialize, login, logout: vi.fn() }, "ios");
    const user = { name: "Ann Lee", email: "", picture: null, display_name: null, name_shown: "Ann" };
    loginWithApple.mockResolvedValue(user);
    await render();
    const google = host.querySelector<HTMLButtonElement>(".google-signin-native")!;
    const apple = host.querySelector<HTMLButtonElement>("[data-testid='apple-signin']")!;
    expect(apple).not.toBeNull();
    expect(apple.textContent).toBe("Sign in with Apple");
    expect(apple.style.minHeight).toBe(google.style.minHeight);
    expect(apple.style.maxWidth).toBe(google.style.maxWidth);
    expect(apple.style.width).toBe(google.style.width);
    expect(initialize).toHaveBeenCalledWith({ apple: { useProperTokenExchange: true, redirectUrl: "" } });
    await act(async () => {
      apple.click();
      await vi.waitFor(() => expect(signedIn).toHaveBeenCalledWith(user));
    });
    expect(login).toHaveBeenCalledTimes(1);
    const opts = login.mock.calls[0][0];
    expect(opts.provider).toBe("apple");
    const posted = loginWithApple.mock.calls[0][0];
    expect(posted.nonce).toMatch(/^[0-9a-f]{32}$/);
    expect(opts.options.nonce).toBe(await sha256(posted.nonce));
    expect(posted).toEqual({
      identityToken: "apple.jwt", nonce: posted.nonce, authorizationCode: "code-1", givenName: "Ann", familyName: "Lee",
    });
    expect(signedIn).toHaveBeenCalledWith(user);
    expect(loginWithGoogle).not.toHaveBeenCalled();
  });

  it("a later sign-in without a name posts nulls; a cancelled sheet shows no error", async () => {
    const login = vi.fn()
      .mockRejectedValueOnce(new Error("The operation couldn't be completed. (com.apple.AuthenticationServices.AuthorizationError error 1001.)"))
      .mockResolvedValueOnce({ provider: "apple", result: {
        idToken: "apple.jwt", authorizationCode: "code-2", profile: { user: "u", email: "", givenName: "", familyName: "" } } });
    fakeShell({ initialize: vi.fn(() => Promise.resolve()), login, logout: vi.fn() }, "ios");
    loginWithApple.mockResolvedValue({ name: "Ann Lee", email: "", picture: null, display_name: null, name_shown: "Ann" });
    await render();
    const apple = host.querySelector<HTMLButtonElement>("[data-testid='apple-signin']")!;
    await act(async () => {
      apple.click();
      await vi.waitFor(() => expect(login).toHaveBeenCalledTimes(1));
    });
    expect(apple.disabled).toBe(false);
    expect(host.querySelector(".lobby-error")).toBeNull();
    expect(loginWithApple).not.toHaveBeenCalled();
    await act(async () => {
      apple.click();
      await vi.waitFor(() => expect(signedIn).toHaveBeenCalledTimes(1));
    });
    expect(loginWithApple.mock.calls[0][0]).toMatchObject({ authorizationCode: "code-2", givenName: null, familyName: null });
  });

  it("in the iOS app the Google button never says it opens a tab, and Apple sits beside it", async () => {
    fakeShell({ initialize: vi.fn(() => Promise.resolve()), login: vi.fn(), logout: vi.fn() }, "ios");
    await render();
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    const google = host.querySelector<HTMLButtonElement>("[data-testid='google-signin']")!;
    expect(google.textContent).toBe("Continue with Google");
    const labels = [...host.querySelectorAll("*")].map((el) => `${el.textContent} ${el.getAttribute("aria-label") ?? ""}`);
    expect(labels.join(" ")).not.toMatch(/new tab|coming soon/i);
    expect(host.querySelector("[data-testid='apple-signin']")?.textContent).toBe("Sign in with Apple");
    expect(gis.renderButton).not.toHaveBeenCalled();
  });

  it("is absent on a non-iOS native shell and in a shell whose plugin refuses the Apple provider", async () => {
    fakeShell({ initialize: vi.fn(() => Promise.resolve()), login: vi.fn(), logout: vi.fn() }, "android");
    await render();
    expect(host.querySelector(".google-signin-native")).not.toBeNull();
    expect(host.querySelector("[data-testid='apple-signin']")).toBeNull();
    act(() => root.unmount());
    host.remove();
    resetNativeAuthForTests();
    const initialize = vi.fn(() => Promise.reject(new Error("Apple Sign-In provider is disabled in capacitor.config")));
    fakeShell({ initialize, login: vi.fn(), logout: vi.fn() }, "ios");
    await render();
    expect(initialize).toHaveBeenCalled();
    expect(host.querySelector(".google-signin-native")).not.toBeNull();
    expect(host.querySelector("[data-testid='apple-signin']")).toBeNull();
  });
});
