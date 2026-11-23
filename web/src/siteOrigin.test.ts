// @vitest-environment node
/// <reference types="node" />
// Search engines and link previews see one origin; the app's own host stays
// on shengji.fly.dev only in the files listed here.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SITE_ORIGIN, canonicalUrl, syncCanonical } from "./siteOrigin";

const WEB = new URL("..", import.meta.url).pathname;
const read = (rel: string) => readFileSync(join(WEB, rel), "utf8");

const SEO_FILES = ["index.html", "public/sitemap.xml", "public/robots.txt", "public/llms.txt",
  "public/rules/index.html", "public/rules/zh/index.html"];

// The places that must keep shengji.fly.dev until the app ships on SITE_ORIGIN:
// the app loads that host (its cookies and socket are same-origin with it), its
// associated domain is applinks:shengji.fly.dev, and the offline page and the
// device-test log upload reach that host from the app. The two info pages name
// it in their copy.
const APP_HOST_FILES = [
  "capacitor.config.ts",
  "ios/App/App/App.entitlements",
  "ios/App/AppChecks/InviteLink/main.swift",
  "src/components/offlineGame.ts",
  "src/nearbyLogUpload.ts",
  "src/support/PrivacyPage.tsx",
  "src/support/TermsPage.tsx",
];

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (["node_modules", "dist", "Pods", "build", "DerivedData", "public"].includes(name)) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(ts|tsx|html|swift|entitlements|plist|json)$/.test(name)) out.push(p);
  }
  return out;
}

describe("the canonical origin", () => {
  it("is playshengji.com", () => {
    expect(SITE_ORIGIN).toBe("https://playshengji.com");
  });

  it("names index.html's canonical link, og:url and JSON-LD url", () => {
    const html = read("index.html");
    expect(html).toContain(`<link rel="canonical" href="${SITE_ORIGIN}/" />`);
    expect(html).toContain(`<meta property="og:url" content="${SITE_ORIGIN}/" />`);
    const [, block] = /<script type="application\/ld\+json">([\s\S]*?)<\/script>/.exec(html)!;
    const data = JSON.parse(block);
    expect(data.url).toBe(`${SITE_ORIGIN}/`);
    expect(data.image.startsWith(`${SITE_ORIGIN}/`)).toBe(true);
    expect(html).toContain('<meta name="apple-itunes-app"');
  });

  it("leaves no shengji.fly.dev in the SEO files", () => {
    for (const f of SEO_FILES) expect(read(f), f).not.toMatch(/shengji\.fly\.dev/i);
  });

  it("keeps shengji.fly.dev only in the app-host allow-list", () => {
    const found = walk(WEB)
      .filter((f) => !/\.test\.tsx?$/.test(f) && /shengji\.fly\.dev/i.test(readFileSync(f, "utf8")))
      .map((f) => relative(WEB, f))
      .sort();
    expect(found).toEqual([...APP_HOST_FILES].sort());
  });
});

describe("canonicalUrl and syncCanonical", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it("drops a trailing slash except the root's", () => {
    expect(canonicalUrl("/")).toBe(`${SITE_ORIGIN}/`);
    expect(canonicalUrl("")).toBe(`${SITE_ORIGIN}/`);
    expect(canonicalUrl("/privacy/")).toBe(`${SITE_ORIGIN}/privacy`);
  });

  it("points the canonical link and og:url at an in-place navigation", () => {
    const attrs: Record<string, [string, string]> = {};
    vi.stubGlobal("document", {
      querySelector: (sel: string) => ({ setAttribute: (k: string, v: string) => { attrs[sel] = [k, v]; } }),
    });
    syncCanonical("/terms");
    expect(attrs['link[rel="canonical"]']).toEqual(["href", `${SITE_ORIGIN}/terms`]);
    expect(attrs['meta[property="og:url"]']).toEqual(["content", `${SITE_ORIGIN}/terms`]);
  });
});
