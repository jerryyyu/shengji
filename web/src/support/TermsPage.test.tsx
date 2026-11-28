import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import TermsPage from "./TermsPage";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

afterEach(() => { act(() => root.unmount()); host.remove(); });

describe("the terms of use page", () => {
  it("covers the rules a store review asks for and names its date", () => {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => root.render(<TermsPage />));
    expect(host.querySelector("h1")?.textContent).toBe("Terms of use");
    const headings = [...host.querySelectorAll("h2")].map((h) => h.textContent);
    expect(headings).toEqual(["The game", "Guests and accounts", "Purchases",
                              "How to behave", "What we do about it",
                              "Reporting a player", "Ratings and the leaderboard", "No guarantees",
                              "Changes to these terms", "Contact"]);
    const text = host.textContent ?? "";
    expect(text).toContain("Last updated 2026-11-27");
    expect(text).toContain("Some companion looks can be bought in the iOS app through Apple. There are no ads.");
    expect(text).toContain("If Apple refunds a purchase, its look is removed.");
    expect(text).toContain("choose Restore purchases");
    expect(text).not.toContain("There are no purchases");
    expect(text).toContain("Anyone can play. Children should have a parent or guardian’s permission before signing in, chatting or buying.");
    expect(text).not.toContain("13 or older");
    expect(text).toContain("zero tolerance for objectionable content");
    expect(text).toContain("within 24 hours");
    expect(text).toContain("choose Report");
    expect(text).toContain("no prizes");
    expect(text).toContain("as it is, without any warranty");
    expect(text).not.toMatch(/\S+@\S+\.\S+/);
    const links = [...host.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(new Set(links)).toEqual(new Set(["/privacy", "/support"]));
  });
});
