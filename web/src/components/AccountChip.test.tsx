import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import AccountChip from "./AccountChip";
import Lobby from "./Lobby";
import { auth } from "../auth";
import { navigate } from "../replay/route";

vi.mock("../ws", () => ({
  conn: { send: () => {}, reconnect: () => {}, subscribe: () => () => {}, subscribeStatus: () => () => {} },
  clearSavedRoom: () => {}, getResumeToken: () => null, getSavedName: () => "", saveName: () => {},
}));

const user = { name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" };
let cleanup: (() => void) | null = null;
afterEach(() => {
  cleanup?.();
  cleanup = null;
  act(() => navigate(null));
  auth.reset();
});

function render(node: React.ReactNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(node));
  cleanup = () => { act(() => root.unmount()); host.remove(); };
  return host;
}

it("the account chip's My games opens the history page", () => {
  const host = render(<AccountChip user={user} />);
  const games = host.querySelector<HTMLButtonElement>(".account-games")!;
  expect(games.textContent).toBe("My games");
  act(() => games.click());
  expect(window.location.hash).toBe("#/games");
});

it("the lobby offers My games only to a signed-in player", () => {
  const host = render(<Lobby status="open" error={null} onArmAutoFill={() => {}} />);
  expect(host.querySelector(".account-games")).toBeNull();
  act(() => auth.signedIn(user));
  expect(host.querySelector(".account-games")).not.toBeNull();
});
