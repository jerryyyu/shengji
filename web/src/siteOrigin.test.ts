// @vitest-environment node
/// <reference types="node" />
// Search engines, link previews and the app see one origin; the host older
// app builds load, shengji.fly.dev, is named only in the files listed here.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SITE_ORIGIN, canonicalUrl, syncCanonical } from "./siteOrigin";

const WEB = new URL("..", import.meta.url).pathname;
const read = (rel: string) => readFileSync(join(WEB, rel), "utf8");

const SEO_FILES = ["index.html", "public/sitemap.xml", "public/robots.txt", "public/llms.txt",
  "public/rules/index.html", "public/rules/zh/index.html"];

// The places that still name shengji.fly.dev: the app's associated domains
// list it beside playshengji.com, so invite links older builds share still
// open the app (InviteLink.swift and its check), and the shell's one-time move
// reads that origin's cookies and localStorage (OriginMove.swift and its check).
const OLD_HOST_FILES = [
  "ios/App/App/App.entitlements",
  "ios/App/App/OriginMove.swift",
  "ios/App/AppChecks/InviteLink/main.swift",
  "ios/App/AppChecks/OriginMove/main.swift",
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

  it("is the origin the app loads, with both hosts' invite links opening it", () => {
    expect(read("capacitor.config.ts")).toContain(`process.env.CAP_SERVER_URL || "${SITE_ORIGIN}"`);
    expect(read("src/components/offlineGame.ts")).toContain(`ONLINE_URL = "${SITE_ORIGIN}/"`);
    expect(read("src/nearbyLogUpload.ts")).toContain(`UPLOAD_URL = "${SITE_ORIGIN}/api/nearby-log"`);
    const domains = [...read("ios/App/App/App.entitlements").matchAll(/<string>applinks:([^<]+)<\/string>/g)]
      .map((m) => m[1]);
    expect(domains).toEqual(["playshengji.com", "shengji.fly.dev"]);
    expect(read("ios/App/App/OriginMove.swift")).toContain('targetHosts: Set<String> = ["playshengji.com"]');
  });

  it("names shengji.fly.dev only in the old-host allow-list", () => {
    const found = walk(WEB)
      .filter((f) => !/\.test\.tsx?$/.test(f) && /shengji\.fly\.dev/i.test(readFileSync(f, "utf8")))
      .map((f) => relative(WEB, f))
      .sort();
    expect(found).toEqual([...OLD_HOST_FILES].sort());
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
