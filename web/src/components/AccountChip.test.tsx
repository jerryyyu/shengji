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

it("shows the rating and this week's change, and opens the Leaderboard tab", async () => {
  const host = await render(200, { rating: 1468, week_delta: -6 });
  const chip = host.querySelector<HTMLButtonElement>(".rating-chip")!;
  expect(chip.querySelector(".avatar")?.textContent).toBe("J");
  expect(chip.querySelector(".rating-chip-value")?.textContent).toBe("1468");
  expect(chip.querySelector(".delta-dn")?.textContent).toBe("▼ 6");
  act(() => chip.click());
  expect(window.location.hash).toBe("#/leaderboard");
});

it("is left out while the stats cannot be read", async () => {
  const host = await render(401, {});
  expect(host.querySelector(".rating-chip")).toBeNull();
});
