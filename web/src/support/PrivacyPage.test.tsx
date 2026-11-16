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
    expect(headings).toEqual(["Playing as a guest", "Game records", "Table chat",
                              "Signing in with Google or Apple", "Saved games", "Ratings and the leaderboard",
                              "Usage events", "Reporting a player", "Support messages",
                              "IP addresses and server logs", "Where it is kept", "Deleting your account",
                              "Children", "Automated play", "Contact"]);
    const text = host.textContent ?? "";
    expect(text).toContain("Last updated 2026-11-16");
    expect(text).toContain("Fly.io");
    expect(text).toContain("hash");
    expect(text).toContain("Show me on the leaderboard");
    expect(text).toContain("must not create or join rooms");
    expect(text).toContain("choose Delete account");
    expect(text).toContain("revoke the app’s access");
    expect(text).toContain("last 20 chat lines");
    expect(text).toContain("for 90 days, and then our server deletes them");
    expect(text).toContain("report another player at the table, signed in or a guest");
    expect(text).toContain("not directed at children under 13");
    expect(text).not.toContain("no ratings or leaderboards");
    expect(text).not.toContain("don’t use analytics");
    expect(text).not.toContain("My games");
    expect(text).not.toMatch(/\S+@\S+\.\S+/);
    const links = [...host.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(links).toContain("/terms");
    expect(links.every((h) => h === "/support" || h === "/terms")).toBe(true);
  });
});
