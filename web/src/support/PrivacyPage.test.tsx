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
    expect(headings).toEqual(["Playing as a guest", "Accounts in the iOS app", "Game records", "Table chat",
                              "Signing in with Google or Apple", "Saved games", "Ratings and the leaderboard",
                              "Purchases", "Usage events", "Reporting a player", "Blocking a player", "Support messages",
                              "IP addresses and server logs", "Where it is kept", "Deleting your account",
                              "Children", "Automated play", "Contact"]);
    const text = host.textContent ?? "";
    expect(text).toContain("Last updated 2026-11-27");
    expect(text).toContain("whether a script is driving the page");
    expect(text).toContain("checks Apple’s signature before using it");
    expect(text).toContain("Apple’s transaction ids, the purchase date, the App Store country");
    expect(text).toContain("a refunded purchase is kept, marked with the refund date, and its look is removed");
    expect(text).toContain("A purchase never gives us your card or other payment details");
    expect(text).toContain("it carries a random code for your device so we can count");
    expect(text).toContain("We store only a scrambled version of it");
    expect(text).toContain("groups those events across visits");
    expect(text).toContain("From version 1.0.1, the iOS app makes you an account");
    expect(text).toContain("It is not synced to iCloud");
    expect(text).toContain("deleted after 30 days unused");
    expect(text).toContain("12 months unused");
    expect(text).toContain("Deleting the app does not delete the account");
    expect(text).toContain("the first time it sets you up to play online");
    expect(text).toContain("Games played offline make none");
    expect(text).toContain("console logs (below) may record it when you connect");
    expect(text).not.toContain("never writes it down");
    expect(text).toContain("for queues and seats and to recognise a returning guest");
    expect(text).not.toContain("only while you are seated");
    expect(text).not.toContain("everything tied to it");
    expect(text).toContain("the same way as Delete account (below)");
    expect(text).toContain("top-rated players who leave “Show me on the leaderboard” on in Me");
    expect(text).toContain("Support messages and player reports are kept");
    expect(text).toContain("Fly.io");
    expect(text).toContain("hash");
    expect(text).toContain("Show me on the leaderboard");
    expect(text).toContain("must not create or join rooms");
    expect(text).toContain("choose Delete account");
    expect(text).toContain("revoke the app’s access");
    expect(text).toContain("last 20 chat lines");
    expect(text).toContain("removes the days older than 90 days as new events arrive");
    expect(text).toContain("report another player at the table, signed in or a guest");
    expect(text).toContain("we store the pair of accounts and the");
    expect(text).toContain("the blocks you made, or others made of you");
    expect(text).not.toContain("Muting a player");
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
