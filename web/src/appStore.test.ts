// Every App Store link the site serves names its placement with a campaign
// token, so App Analytics can split installs by where the link sat.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { APP_STORE_URL, CAMPAIGN_TOKEN_MAX, appStoreUrl } from "./appStore";

const WEB = join(__dirname, "..");

function files(dir: string, keep: (p: string) => boolean): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? files(p, keep) : keep(p) ? [p] : [];
  });
}

const unescape = (s: string) => s.replace(/&amp;/g, "&");
const pages = [join(WEB, "index.html"), ...files(join(WEB, "public"), (p) => p.endsWith(".html"))];

describe("App Store campaign tokens", () => {
  it("builds a link with the placement's token", () => {
    const url = new URL(appStoreUrl("guides-en-how-to-play"));
    expect(url.origin + url.pathname).toBe(APP_STORE_URL);
    expect(url.searchParams.get("ct")).toBe("guides-en-how-to-play");
  });

  it("refuses a token Apple would not take", () => {
    expect(() => appStoreUrl("")).toThrow();
    expect(() => appStoreUrl("Has Space")).toThrow();
    expect(() => appStoreUrl("x".repeat(CAMPAIGN_TOKEN_MAX + 1))).toThrow();
  });

  it("gives every App Store link in the served pages its own token", () => {
    const tokens: string[] = [];
    for (const page of pages) {
      const html = readFileSync(page, "utf8");
      for (const [, href] of html.matchAll(/href="(https:\/\/apps\.apple\.com[^"]*)"/g)) {
        const url = new URL(unescape(href));
        const ct = url.searchParams.get("ct");
        expect(ct, relative(WEB, page)).toBeTruthy();
        expect(unescape(href), relative(WEB, page)).toBe(appStoreUrl(ct!));
        tokens.push(ct!);
      }
    }
    expect(tokens.length).toBeGreaterThan(0);
    expect(new Set(tokens).size).toBe(tokens.length);
  });

  it("keeps the bare store address only in the app page's structured data", () => {
    for (const page of pages) {
      const html = readFileSync(page, "utf8").replace(/href="https:\/\/apps\.apple\.com[^"]*"/g, "");
      const bare = html.split("apps.apple.com").length - 1;
      // schema.org installUrl and sameAs name the app itself, not a placement
      expect(bare, relative(WEB, page)).toBe(page.endsWith(join("web", "index.html")) ? 2 : 0);
    }
  });

  it("links the store from components only through appStoreUrl", () => {
    const src = files(join(WEB, "src"), (p) => /\.(ts|tsx)$/.test(p) && !/\.test\.tsx?$/.test(p));
    for (const p of src) {
      if (p.endsWith("appStore.ts")) continue;
      const text = readFileSync(p, "utf8");
      expect(text, relative(WEB, p)).not.toContain("apps.apple.com");
      expect(text, relative(WEB, p)).not.toMatch(/href=\{?\$?\{?APP_STORE_URL/);
    }
  });
});
