// @vitest-environment node
/// <reference types="node" />
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { APP_STORE_URL, SITE_ORIGIN } from "../siteOrigin";
import { DiagramError, renderBlock } from "./cards";
import { inline, render } from "./markdown";
import { GUIDE_CSS, GUIDE_DIRS, buildSite, type Source } from "./site";

const WEB = new URL("../..", import.meta.url).pathname;
const CONTENT = join(WEB, "content", "guides");
const PUBLIC = join(WEB, "public");

function sources(): Source[] {
  const out: Source[] = [];
  for (const lang of ["en", "zh"]) {
    if (!existsSync(join(CONTENT, lang))) continue;
    for (const name of readdirSync(join(CONTENT, lang)).sort()) {
      if (name.endsWith(".md")) out.push({ path: `${lang}/${name}`, text: readFileSync(join(CONTENT, lang, name), "utf8") });
    }
  }
  return out;
}

const built = buildSite(sources(), readFileSync(join(PUBLIC, "sitemap.xml"), "utf8"));
const slugs = sources().filter((s) => s.path.startsWith("en/")).map((s) => s.path.slice(3, -3)).sort();
const pages = [...built].filter(([p]) => p.endsWith(".html"));
const guidePages = pages.filter(([p]) => p.split("/").length === (p.startsWith("zh/") ? 4 : 3));

function ld(html: string): { "@graph": { "@type": string; [k: string]: unknown }[] } {
  const [, block] = /<script type="application\/ld\+json">([\s\S]*?)<\/script>/.exec(html)!;
  return JSON.parse(block);
}

const fixture = (body: string, extra = "") => `---
title: A <b>bold</b> "title"
description: Desc & more
slug: test
order: 1
related: []
updated: 2026-01-01
lang: en
${extra}---
${body}`;

describe("the committed guide pages", () => {
  it("match their sources (npm run guides:check)", () => {
    for (const [p, text] of built) {
      expect(existsSync(join(PUBLIC, p)), p).toBe(true);
      expect(readFileSync(join(PUBLIC, p), "utf8") === text, `${p} is stale: run npm run guides`).toBe(true);
    }
  });

  it("leave no page without a source", () => {
    for (const base of Object.values(GUIDE_DIRS)) {
      for (const name of readdirSync(join(PUBLIC, base))) {
        if (name === "index.html") continue;
        expect(built.has(`${base}/${name}/index.html`), `${base}/${name}`).toBe(true);
      }
    }
  });

  it("cover every guide in both languages, plus a hub each", () => {
    expect(slugs.length).toBeGreaterThanOrEqual(6);
    for (const slug of slugs) {
      expect(built.has(`guides/${slug}/index.html`)).toBe(true);
      expect(built.has(`zh/guides/${slug}/index.html`)).toBe(true);
    }
    expect(built.has("guides/index.html") && built.has("zh/guides/index.html")).toBe(true);
  });
});

describe("each page's metadata", () => {
  it("names itself canonical on SITE_ORIGIN with en and zh-Hans alternates", () => {
    for (const [p, html] of pages) {
      const path = "/" + p.replace(/\/index\.html$/, "");
      const en = path.replace(/^\/zh/, "");
      expect(html, p).toContain(`<link rel="canonical" href="${SITE_ORIGIN}${path}" />`);
      expect(html, p).toContain(`<link rel="alternate" hreflang="en" href="${SITE_ORIGIN}${en}" />`);
      expect(html, p).toContain(`<link rel="alternate" hreflang="zh-Hans" href="${SITE_ORIGIN}/zh${en}" />`);
      expect(html, p).toContain(`<meta property="og:url" content="${SITE_ORIGIN}${path}" />`);
      expect(html, p).toMatch(/<title>[^<]{10,}<\/title>/);
      expect(html, p).toMatch(/<meta name="description" content="[^"]{30,}" \/>/);
      expect(html, p).toContain(`<html lang="${p.startsWith("zh/") ? "zh-Hans" : "en"}">`);
    }
  });

  it("carries JSON-LD that parses: an Article and a BreadcrumbList, a HowTo where declared", () => {
    for (const [p, html] of guidePages) {
      const types = ld(html)["@graph"].map((n) => n["@type"]);
      expect(types.slice(0, 2), p).toEqual(["Article", "BreadcrumbList"]);
      const src = readFileSync(join(CONTENT, p.startsWith("zh/") ? "zh" : "en", `${p.split("/").at(-2)}.md`), "utf8");
      expect(types.includes("HowTo"), p).toBe(/^schema: HowTo$/m.test(src));
      const crumbs = ld(html)["@graph"][1].itemListElement as { item: string }[];
      expect(crumbs.map((c) => c.item.startsWith(SITE_ORIGIN))).toEqual([true, true, true]);
    }
    for (const hub of ["guides/index.html", "zh/guides/index.html"]) {
      expect(ld(built.get(hub)!)["@graph"].map((n) => n["@type"])).toEqual(["CollectionPage", "BreadcrumbList"]);
    }
  });

  it("puts one app call to action on each guide, none on the hubs", () => {
    for (const [p, html] of guidePages) {
      expect(html.split('data-cta="app"').length - 1, p).toBe(1);
      expect(html.split(APP_STORE_URL).length - 1, p).toBe(1);
      const block = /<aside class="cta"[\s\S]*?<\/aside>/.exec(html)![0];
      expect(block, p).toContain('<a href="/">');
    }
    expect(built.get("guides/index.html")).not.toContain(APP_STORE_URL);
  });

  it("links the rules, the other language and related guides that exist", () => {
    for (const [p, html] of guidePages) {
      const zh = p.startsWith("zh/");
      expect(html, p).toContain(`href="${zh ? "/rules/zh" : "/rules"}"`);
      for (const [, href] of html.matchAll(/href="(\/(?:zh\/)?guides\/[^"#]+)"/g)) {
        expect(built.has(`${href.slice(1)}/index.html`), `${p} links ${href}`).toBe(true);
      }
    }
  });

  it("loads no script or stylesheet from anywhere", () => {
    for (const [p, html] of pages) {
      expect(html, p).not.toMatch(/<script(?![^>]*application\/ld\+json)/);
      expect(html, p).not.toMatch(/<link[^>]+stylesheet/);
    }
  });
});

describe("the guide visuals", () => {
  it("give every guide at least two diagrams and one animation, each with a text alternative", () => {
    for (const [p, html] of guidePages) {
      const figures = html.match(/<figure class="gv"/g) ?? [];
      expect(figures.length, p).toBeGreaterThanOrEqual(2);
      expect(html, p).toMatch(/class="gv-svg gv-anim/);
      for (const [, svg] of html.matchAll(/(<svg class="gv-svg[\s\S]*?<\/svg>)/g)) {
        expect(svg, p).toMatch(/role="img" aria-labelledby="(gv\d+)"[\s\S]*<title id="\1">[^<]{10,}<\/title>/);
      }
    }
  });

  it("stop moving under reduced motion", () => {
    expect(GUIDE_CSS).toContain("@media (prefers-reduced-motion: reduce) { .gv-anim * { animation: none !important; } }");
    for (const [p, html] of guidePages) expect(html, p).toContain(GUIDE_CSS);
  });

  it("draw Play now and the app link in the app's one gold, at its 52px action size", () => {
    const play = /\.play \{([^}]*)\}/.exec(GUIDE_CSS)![1].replace(/\s+/g, " ");
    const face = "linear-gradient(180deg, #8a6a22, #6b5219)";
    expect(play).toContain(`background: ${face};`);
    expect(play).toContain("border: 1.5px solid #f2c14e;");
    expect(play).toContain("color: #fff3cf;");
    expect(play).toContain("min-height: 52px;");
    expect(play).toContain("border-radius: 14px;");
    expect(play).toContain("font-size: 17px; font-weight: 700;");
    // the app's shared gold rule draws the same face and label
    const app = readFileSync(join(WEB, "src", "index.css"), "utf8");
    expect(app).toContain(`background: ${face};`);
    expect(app).toContain("color: #fff3cf;");
    const lum = (hex: string) => {
      const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
        .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
      return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    };
    const ratio = (a: string, b: string) => (lum(a) + 0.05) / (lum(b) + 0.05);
    // the label holds AA on the face's lighter end
    expect(ratio("#fff3cf", "#8a6a22")).toBeGreaterThanOrEqual(4.5);
  });

  it("refuse an unknown card code or diagram kind", () => {
    expect(() => renderBlock("cards: SK S1", "en", inline)).toThrow(DiagramError);
    expect(() => renderBlock("kind: movie\ncards: SK", "en", inline)).toThrow(DiagramError);
    expect(() => renderBlock("kind: trick\nnames: A | B\nplays: SK | SA\nwinner: 3", "en", inline)).toThrow(DiagramError);
  });

  it("describe cards in words", () => {
    const html = renderBlock("cards: SK H10 | BJ", "en", inline);
    expect(html).toContain("King of spades, 10 of hearts; big joker");
    expect(renderBlock("cards: SK", "zh", inline)).toContain("黑桃K");
  });
});

describe("the Markdown converter", () => {
  it("escapes raw HTML in text, titles and captions", () => {
    const [, html] = [...buildSite([{ path: "en/test.md", text: fixture("<script>alert(1)</script> & <b>x</b>\n\n```cards\ncards: SK\ncaption: <img src=x>\n```\n") },
      { path: "zh/test.md", text: fixture("x", "").replace("lang: en", "lang: zh") }], "<urlset>\n</urlset>")]
      .find(([p]) => p === "guides/test/index.html")!;
    expect(html).not.toContain("<script>alert");
    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt; &amp; &lt;b&gt;x&lt;/b&gt;");
    expect(html).toContain("<title>A &lt;b&gt;bold&lt;/b&gt; &quot;title&quot; | Sheng Ji guides</title>");
    expect(html).toContain("&lt;img src=x&gt;");
    expect(html).not.toContain("<img");
  });

  it("keeps </script> out of JSON-LD", () => {
    const [, html] = [...buildSite([{ path: "en/test.md", text: fixture("x").replace("Desc & more", "</script><script>alert(1)</script>") },
      { path: "zh/test.md", text: fixture("x").replace("lang: en", "lang: zh") }], "<urlset>\n</urlset>")]
      .find(([p]) => p === "guides/test/index.html")!;
    const block = /<script type="application\/ld\+json">([\s\S]*?)<\/script>/.exec(html)![1];
    expect(block).not.toContain("</");
    expect(JSON.parse(block)["@graph"][0].description).toBe("</script><script>alert(1)</script>");
  });

  it("allows only site paths and https links", () => {
    expect(inline("[a](/rules) [b](https://example.com) [c](javascript:alert) [d](//evil.com)"))
      .toBe('<a href="/rules">a</a> <a href="https://example.com">b</a> c d');
  });

  it("formats emphasis, code, tables and red suits", () => {
    expect(inline("**bold** *it* `x<y` ♥K ♠K")).toBe(
      '<strong>bold</strong> <em>it</em> <code>x&lt;y</code> <span class="red">♥K</span> ♠K');
    const { html } = render("| a | b |\n| --- | ---: |\n| 1 | 2 |\n", "en");
    expect(html).toContain('<th>a</th><th style="text-align:right">b</th>');
    expect(html).toContain('<td>1</td><td style="text-align:right">2</td>');
  });

  it("refuses an h1 in the body and an unknown fence", () => {
    expect(() => render("# Title\n", "en")).toThrow();
    expect(() => render("```js\nx\n```\n", "en")).toThrow();
  });
});

describe("the sitemap", () => {
  it("lists every guide and hub in both languages, with alternates", () => {
    const map = built.get("sitemap.xml")!;
    for (const slug of ["", ...slugs.map((s) => `/${s}`)]) {
      for (const base of ["/guides", "/zh/guides"]) {
        expect(map).toContain(`<loc>${SITE_ORIGIN}${base}${slug}</loc>`);
      }
    }
    expect(map.match(/<!-- guides: generated/g)?.length).toBe(1);
    expect(map).toContain(`<loc>${SITE_ORIGIN}/rules</loc>`);
  });
});
