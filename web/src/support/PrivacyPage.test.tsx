import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import PrivacyPage from "./PrivacyPage";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

afterEach(() => { act(() => root.unmount()); host.remove(); });

describe("the privacy page", () => {
  it("covers each kind of data the game keeps and names its effective date", () => {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => root.render(<PrivacyPage />));
    const headings = [...host.querySelectorAll("h2")].map((h) => h.textContent);
    expect(headings).toEqual(["Playing as a guest", "Game records", "Signing in with Google",
                              "Saved games", "Ratings and the leaderboard", "Support messages", "IP addresses and server logs",
                              "Where it is kept", "Deleting your account", "Contact"]);
    const text = host.textContent ?? "";
    expect(text).toContain("Effective 2026-11-11");
    expect(text).toContain("Fly.io");
    expect(text).toContain("hash");
    expect(text).toContain("Show me on the leaderboard");
    expect(text).not.toContain("no ratings or leaderboards");
    expect(text).not.toMatch(/\S+@\S+\.\S+/);
    const links = [...host.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(links.every((h) => h === "/support")).toBe(true);
  });
});
