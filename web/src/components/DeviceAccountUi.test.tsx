// The app's own account on screen: the chip (name, rating, pencil), the
// identity sheet with its one line "On this iPhone only", Me with no Sign out,
// and the one confirm when a sign-in's identity already has an account. The
// website draws none of it.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthState } from "../auth";

const { authState, signOut, deleted, updated, signedIn, loginWithGoogle } = vi.hoisted(() => ({
  authState: { current: { status: "loading", clientId: null, user: null } as AuthState },
  signOut: vi.fn(() => Promise.resolve()),
  deleted: vi.fn(),
  updated: vi.fn(),
  signedIn: vi.fn(),
  loginWithGoogle: vi.fn(),
}));
vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));
vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return { ...real, loginWithGoogle, useAuth: () => authState.current,
           auth: { signOut, deleted, updated, signedIn, get state() { return authState.current; } } };
});

import { AccountExists } from "../auth";
import MePage from "./MePage";
import AccountChip from "./AccountChip";
import GuestChip, { IdentitySheet } from "./GuestChip";
import { RankedSection } from "../queue/Ranked";
import { forgetHomeSession } from "../home/session";
import { guestName } from "../guestName";
import { resetNativeForTests } from "../native";
import { resetNativeAuthForTests } from "../nativeAuth";
import { telemetry } from "../telemetry";

const DEVICE = { name: "Gentle Tractor", email: "", picture: null, display_name: "Gentle Tractor",
                 name_shown: "Gentle Tractor", rounds_played: 12, linked: false };
const STATS = { name: "Gentle Tractor", rating: 962, rank: 7, rounds: 12, provisional: true, levels_per_round: 0.31,
                won_pct: 58, defender_won_pct: 61, attacker_won_pct: 54, best_streak: 7, games_won: 1,
                week_delta: -38, history: [1000, 962], visible: true, recent_games: [] };

beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});

let calls: { url: string; method: string; body?: unknown }[];
let patch: { status: number; body: unknown };

function iosShell(withGoogle = false, idiom = "phone") {
  const shell = { ShengjiShell: { idiom: vi.fn(() => Promise.resolve({ idiom })) } };
  const Plugins: Record<string, unknown> = withGoogle ? {
    ...shell,
    SocialLogin: {
      initialize: vi.fn(() => Promise.resolve()),
      login: vi.fn(() => Promise.resolve({ provider: "google", result: { idToken: "jwt.tok" } })),
      logout: vi.fn(),
    },
  } : { ...shell };
  (window as unknown as { Capacitor: unknown }).Capacitor = {
    isNativePlatform: () => true,
    getPlatform: () => "ios",
    isPluginAvailable: (name: string) => name in Plugins,
    Plugins,
  };
}

beforeEach(() => {
  forgetHomeSession();
  guestName.reset();
  calls = [];
  patch = { status: 200, body: { ...DEVICE, display_name: "Brave Kite", name_shown: "Brave Kite" } };
  for (const f of [signOut, deleted, updated, signedIn, loginWithGoogle]) f.mockReset();
  signOut.mockImplementation(() => Promise.resolve());
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (method === "DELETE" && url === "/api/me") return { status: 204, json: async () => { throw new Error("no body"); } } as unknown as Response;
    if (method === "PATCH" && url === "/api/me") return { status: patch.status, json: async () => patch.body } as Response;
    const body = url === "/api/me/stats" ? STATS : url.startsWith("/api/me/games?") ? { games: [], next_before: null } : null;
    return { status: body ? 200 : 404, json: async () => body ?? {} } as Response;
  }) as typeof fetch;
  authState.current = { status: "in", clientId: "cid", user: DEVICE };
});

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  delete (window as unknown as { Capacitor?: unknown }).Capacitor;
  resetNativeForTests();
  resetNativeAuthForTests();
  window.history.replaceState(null, "", "/");
});

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
async function render(node: React.ReactNode) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<>{node}<IdentitySheet /></>); });
  await settle();
}
const rowLabels = () => [...host.querySelectorAll(".grp-row .grp-label")].map((e) => e.textContent);
const rowNamed = (label: string) =>
  [...host.querySelectorAll<HTMLElement>(".grp-row")].find((r) => r.querySelector(".grp-label")?.textContent === label)!;
const sheet = () => document.querySelector(".identity-sheet");

describe("the chip", () => {
  it("in the app: the name, the rating and a pencil; a tap opens the identity sheet", async () => {
    iosShell();
    await render(<AccountChip user={DEVICE} />);
    const chip = host.querySelector<HTMLButtonElement>(".account-pill")!;
    expect(chip.className).toContain("device-pill");
    expect(chip.querySelector(".account-pill-name")?.textContent).toBe("Gentle Tractor");
    expect(chip.querySelector(".account-pill-rating")?.textContent).toBe("962");
    expect(chip.querySelector(".guest-pill-edit")).not.toBeNull();
    expect(chip.getAttribute("aria-label")).toBe("Gentle Tractor, rating 962, edit name");
    act(() => chip.click());
    expect(sheet()).not.toBeNull();
    expect(window.location.hash).toBe("");
  });

  it("the wide top bar's chip has no pencil", async () => {
    iosShell();
    await render(<AccountChip user={DEVICE} compact />);
    expect(host.querySelector(".guest-pill-edit")).toBeNull();
  });

  it("on the website the same account's chip is the signed-in chip, opening Me", async () => {
    await render(<AccountChip user={DEVICE} />);
    const chip = host.querySelector<HTMLButtonElement>(".account-pill")!;
    expect(chip.className).not.toContain("device-pill");
    expect(chip.querySelector(".guest-pill-edit")).toBeNull();
    act(() => chip.click());
    expect(window.location.hash).toBe("#/me");
    expect(sheet()).toBeNull();
  });
});

describe("the identity sheet", () => {
  it("shows the name, the one line 'On this iPhone only', the sign-in and Done", async () => {
    iosShell(true);
    await render(null);
    act(() => guestName.open());
    await settle();
    const s = sheet()!;
    expect(s.querySelector("input")?.value).toBe("Gentle Tractor");
    expect(s.querySelector(".identity-status")?.textContent).toBe("On this iPhone only");
    expect(s.querySelectorAll(".identity-status")).toHaveLength(1);
    expect(s.querySelector("[data-testid='google-signin']")).not.toBeNull();
    expect(s.querySelector(".identity-terms")?.textContent).toBe("By signing in you agree to the Terms of use.");
    expect(s.querySelector(".btn.gold")?.textContent).toBe("Done");
  });

  it("Done saves the edited name on the account and closes", async () => {
    iosShell();
    await render(null);
    act(() => guestName.open());
    const input = sheet()!.querySelector("input")!;
    act(() => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      set.call(input, "Brave Kite");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { sheet()!.querySelector<HTMLButtonElement>(".btn.gold")!.click(); });
    await settle();
    expect(calls.filter((c) => c.method === "PATCH")).toEqual([{ url: "/api/me", method: "PATCH", body: { display_name: "Brave Kite" } }]);
    expect(updated).toHaveBeenCalledWith(expect.objectContaining({ name_shown: "Brave Kite" }));
    expect(sheet()).toBeNull();
  });

  it("a name another account shows is refused in the sheet: 'That name is taken.'", async () => {
    iosShell();
    patch = { status: 400, body: { detail: "taken" } };
    await render(null);
    act(() => guestName.open());
    const input = sheet()!.querySelector("input")!;
    act(() => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      set.call(input, "Mei");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { sheet()!.querySelector<HTMLButtonElement>(".btn.gold")!.click(); });
    await settle();
    expect(sheet()?.querySelector("[role='alert']")?.textContent).toBe("That name is taken.");
    expect(updated).not.toHaveBeenCalled();
  });

  it("on an iPad the sheet and Me both say 'On this iPad only'", async () => {
    iosShell(false, "pad");
    await render(<MePage section="stats" />);
    await settle();
    expect(host.querySelector(".me-sub")?.textContent).toBe("On this iPad only");
    act(() => guestName.open());
    await settle();
    expect(sheet()?.querySelector(".identity-status")?.textContent).toBe("On this iPad only");
  });

  it("on the website a signed-in account never sees the sheet", async () => {
    await render(null);
    act(() => guestName.open());
    await settle();
    expect(sheet()).toBeNull();
  });
});

describe("Me", () => {
  it("in the app: 'On this device only', Stats and Games, the name row, the switch and Delete account, no Sign out", async () => {
    iosShell();
    await render(<MePage section="stats" />);
    expect(host.querySelector(".me-name")?.textContent).toBe("Gentle Tractor");
    expect(host.querySelector(".me-sub")?.textContent).toBe("On this iPhone only");
    expect([...host.querySelectorAll(".segmented-btn")].map((b) => b.textContent)).toEqual(["Stats", "Games"]);
    expect(host.querySelectorAll(".me-tile")).toHaveLength(3);
    const labels = rowLabels();
    expect(labels.slice(labels.indexOf("How to play") + 1)).toEqual(["Gentle Tractor", "Show me on the leaderboard",
      "Privacy policy", "Terms of use", "Support", "Delete account"]);
    expect(labels).not.toContain("Sign out");
    expect(labels).not.toContain("Edit name");
    act(() => rowNamed("Gentle Tractor").click());
    expect(sheet()).not.toBeNull();
  });

  it("Delete account deletes after the confirm and forgets the account", async () => {
    iosShell();
    await render(<MePage section="stats" />);
    act(() => rowNamed("Delete account").click());
    await act(async () => {
      host.querySelector<HTMLButtonElement>(".me-delete-yes")!.click();
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(calls.filter((c) => c.method === "DELETE")).toEqual([{ url: "/api/me", method: "DELETE", body: undefined }]);
    expect(deleted).toHaveBeenCalledTimes(1);
  });

  it("a linked account in the app keeps Edit name and Sign out", async () => {
    iosShell();
    authState.current = { status: "in", clientId: "cid", user: { ...DEVICE, email: "g@x", linked: true } };
    await render(<MePage section="stats" />);
    expect(rowLabels()).toContain("Sign out");
    expect(rowLabels()).toContain("Edit name");
    expect(host.querySelector(".me-sub")?.textContent).not.toBe("On this iPhone only");
  });
});

describe("before the first Play", () => {
  const pending = (on: boolean): AuthState => ({ status: "out", clientId: "cid", user: null, ...(on ? { deviceAccounts: true as const } : {}) });

  it("with device accounts on: the chip is the name alone, and Play has no guest line", async () => {
    iosShell();
    authState.current = pending(true);
    guestName.getSnapshot();
    guestName.setName("Gentle Tractor");
    await render(<><GuestChip /><RankedSection online /></>);
    const chip = host.querySelector(".guest-pill")!;
    expect(chip.querySelector(".account-pill-name")?.textContent).toBe("Gentle Tractor");
    expect(chip.querySelector(".account-pill-rating")).toBeNull();
    expect(chip.getAttribute("aria-label")).toBe("Gentle Tractor, edit name");
    expect(host.querySelector(".play-guest-line")).toBeNull();
    expect(host.querySelector(".q-find")).not.toBeNull();
  });

  it("with them off: today's guest chip and guest line, exactly", async () => {
    iosShell();
    authState.current = pending(false);
    guestName.getSnapshot();
    guestName.setName("Gentle Tractor");
    await render(<><GuestChip /><RankedSection online /></>);
    expect(host.querySelector(".guest-pill .account-pill-rating")?.textContent).toBe("Guest");
    expect(host.querySelector(".guest-pill")?.getAttribute("aria-label")).toBe("Gentle Tractor, guest, edit name");
    expect(host.querySelector(".play-guest-line")?.textContent).toBe("Playing as a guest · Sign in to be ranked");
  });
});

describe("the linking conflict", () => {
  async function openAndSignIn() {
    iosShell(true);
    await render(null);
    act(() => guestName.open());
    await settle();
    await act(async () => { sheet()!.querySelector<HTMLButtonElement>("[data-testid='google-signin']")!.click(); });
    await settle();
  }

  it("asks once: 'Switch to Mei?', 'This device's rating is replaced.', Cancel and Switch", async () => {
    loginWithGoogle.mockRejectedValueOnce(new AccountExists("Mei"));
    await openAndSignIn();
    const dialog = document.querySelector(".switch-account-confirm")!;
    expect(dialog.getAttribute("role")).toBe("alertdialog");
    expect(dialog.querySelector("h2")?.textContent).toBe("Switch to Mei?");
    expect(dialog.querySelector("p")?.textContent).toBe("This device's rating is replaced.");
    expect([...dialog.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["Cancel", "Switch"]);
    expect(dialog.className).toContain("leave-sheet-card");
    expect(signedIn).not.toHaveBeenCalled();
    expect(document.querySelector(".lobby-error")).toBeNull();
  });

  it("Switch repeats the sign-in with confirm and signs in as that account", async () => {
    const mei = { name: "Mei Chen", email: "mei@x", picture: null, display_name: "Mei", name_shown: "Mei" };
    loginWithGoogle.mockRejectedValueOnce(new AccountExists("Mei")).mockResolvedValueOnce(mei);
    await openAndSignIn();
    const nonce = loginWithGoogle.mock.calls[0][1];
    await act(async () => { document.querySelector<HTMLButtonElement>(".switch-account-yes")!.click(); });
    await settle();
    expect(loginWithGoogle.mock.calls[1]).toEqual(["jwt.tok", nonce, true]);
    expect(signedIn).toHaveBeenCalledWith(mei);
    expect(document.querySelector(".switch-account-confirm")).toBeNull();
  });

  it("Cancel keeps this device's account and asks nothing more", async () => {
    loginWithGoogle.mockRejectedValueOnce(new AccountExists("Mei"));
    await openAndSignIn();
    act(() => document.querySelector<HTMLButtonElement>(".switch-account-confirm .leave-sheet-stay")!.click());
    expect(document.querySelector(".switch-account-confirm")).toBeNull();
    expect(loginWithGoogle).toHaveBeenCalledTimes(1);
    expect(signedIn).not.toHaveBeenCalled();
  });

  it("telemetry: the confirm shown, then the switch, enums only", async () => {
    const mei = { name: "Mei Chen", email: "mei@x", picture: null, display_name: "Mei", name_shown: "Mei" };
    loginWithGoogle.mockRejectedValueOnce(new AccountExists("Mei")).mockResolvedValueOnce(mei);
    telemetry.reset();
    await openAndSignIn();
    await act(async () => { document.querySelector<HTMLButtonElement>(".switch-account-yes")!.click(); });
    await settle();
    const seen = telemetry.pending().filter((e) => e.e === "signin" || e.e === "device_account")
      .map((e) => `${e.e}:${(e as { step: string }).step}`);
    expect(seen).toEqual(["signin:provider_tap", "device_account:conflict_shown", "signin:done", "device_account:switched"]);
    expect(JSON.stringify(telemetry.pending())).not.toMatch(/Mei|mei@x|jwt\.tok|Gentle/);
    telemetry.reset();
  });

  it("telemetry: a new identity linked onto the device's account", async () => {
    loginWithGoogle.mockResolvedValueOnce({ ...DEVICE, linked: true });
    telemetry.reset();
    await openAndSignIn();
    const seen = telemetry.pending().filter((e) => e.e === "device_account").map((e) => (e as { step: string }).step);
    expect(seen).toEqual(["linked"]);
    telemetry.reset();
  });

  it("a refused Switch says why inside the confirm", async () => {
    loginWithGoogle.mockRejectedValueOnce(new AccountExists("Mei"))
      .mockRejectedValueOnce(new Error("This account is suspended. Contact support if you think this is a mistake."));
    await openAndSignIn();
    await act(async () => { document.querySelector<HTMLButtonElement>(".switch-account-yes")!.click(); });
    await settle();
    expect(document.querySelector(".switch-account-confirm")?.textContent)
      .toContain("This account is suspended.");
    expect(signedIn).not.toHaveBeenCalled();
  });
});
