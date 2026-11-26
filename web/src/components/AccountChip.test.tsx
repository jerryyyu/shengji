import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import AccountChip from "./AccountChip";

const user = { name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" };
let cleanup: (() => void) | null = null;
afterEach(() => {
  cleanup?.();
  cleanup = null;
  window.history.replaceState(null, "", "/");
});

async function render(status: number, body: unknown) {
  globalThis.fetch = vi.fn(async () => ({ status, json: async () => body }) as Response) as typeof fetch;
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<AccountChip user={user} />); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  cleanup = () => { act(() => root.unmount()); host.remove(); };
  return host;
}

it("shows the avatar, the name and the rating, and a tap opens Me", async () => {
  const host = await render(200, { rating: 1468, week_delta: -6 });
  const chip = host.querySelector<HTMLButtonElement>(".account-pill")!;
  expect(chip.querySelector(".avatar")?.textContent).toBe("J");
  expect(chip.querySelector(".account-pill-name")?.textContent).toBe("Jerry");
  expect(chip.querySelector(".account-pill-rating")?.textContent).toBe("1,468");
  expect(chip.querySelector("svg")).toBeNull();   // no pencil: the name is edited on Me
  expect(chip.getAttribute("aria-label")).toBe("Jerry, rating 1468, open profile");
  act(() => chip.click());
  expect(window.location.hash).toBe("#/me");
});

it("without stats it still shows the name, and leaves the rating out", async () => {
  const host = await render(401, {});
  expect(host.querySelector(".account-pill-name")?.textContent).toBe("Jerry");
  expect(host.querySelector(".account-pill-rating")).toBeNull();
  expect(host.querySelector(".account-pill")?.getAttribute("aria-label")).toBe("Jerry, open profile");
});
