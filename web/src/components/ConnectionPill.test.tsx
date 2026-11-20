import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("../ws", () => ({ conn: { generation: 1, reconnect: () => {} } }));
vi.mock("./offlineGame", () => ({ offlineGame: { startFromPlay: () => {} }, offlineOffered: () => false }));

const { default: ConnectionPill } = await import("./ConnectionPill");
const { setStalled } = await import("../link");

afterEach(() => { act(() => setStalled(false)); });

it("an unanswered action shows the Reconnecting pill while the socket still reads open, and an answer hides it", () => {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<ConnectionPill status="open" inRoom inGame />));
  const pill = () => host.querySelector(".reconnect-banner");
  expect(pill()).toBeNull();
  act(() => setStalled(true));
  expect(pill()?.textContent).toBe("Reconnecting…");
  act(() => setStalled(false));
  expect(pill()).toBeNull();
  act(() => root.unmount());
  host.remove();
});
