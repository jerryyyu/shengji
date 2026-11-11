import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetNativeForTests } from "../native";
import { resetNativeAuthForTests } from "../nativeAuth";

const { gis, loginWithGoogle, signedIn } = vi.hoisted(() => ({
  gis: { initialize: vi.fn(), renderButton: vi.fn(), disableAutoSelect: vi.fn() },
  loginWithGoogle: vi.fn(),
  signedIn: vi.fn(),
}));
vi.mock("../ws", () => ({ conn: { reconnect: () => {} } }));
vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return { ...real, loadGis: () => Promise.resolve(gis), loginWithGoogle, auth: { signedIn } };
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

function fakeShell(plugin: Record<string, unknown> | null) {
  const Plugins: Record<string, unknown> = plugin ? { SocialLogin: plugin } : {};
  (window as unknown as { Capacitor: unknown }).Capacitor = {
    isNativePlatform: () => true,
    isPluginAvailable: (name: string) => name in Plugins,
    Plugins,
  };
}

beforeEach(() => {
  gis.initialize.mockClear();
  gis.renderButton.mockClear();
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
