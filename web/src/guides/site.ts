// The /guides pages: every guide in web/content/guides/<lang>/<slug>.md becomes
// a static page under web/public/guides/ (English) or web/public/zh/guides/
// (Chinese), plus a hub per language and the guides' sitemap entries. The
// header, footer and look are the /rules pages'. scripts/build_guides.ts
// writes the files; --check and guides.test.ts compare them with the sources.

import { APP_STORE_URL, SITE_ORIGIN } from "../siteOrigin.ts";
import { esc, resetIds, type Lang } from "./cards.ts";
import { GuideError, parseFrontMatter, plain, render, type FrontMatter, type Heading } from "./markdown.ts";

export interface Source {
  /** Path under web/content/guides/, e.g. "en/how-to-play.md". */
  path: string;
  text: string;
}

export interface Guide {
  meta: FrontMatter;
  html: string;
  headings: Heading[];
}

const IMAGE = `${SITE_ORIGIN}/og/preview.jpg`;
const SITE_NAME = "Sheng Ji 升级";

export const GUIDE_DIRS: Record<Lang, string> = { en: "guides", zh: "zh/guides" };

export function guidePath(lang: Lang, slug?: string): string {
  const base = lang === "en" ? "/guides" : "/zh/guides";
  return slug ? `${base}/${slug}` : base;
}

/** The output file under web/public/ for a page path. */
export function outputFile(path: string): string {
  return `${path.slice(1)}/index.html`;
}

const T = {
  en: {
    htmlLang: "en",
    switchLabel: "中文", switchLang: "zh-Hans",
    play: "Play now",
    home: "Home", hub: "Guides",
    rules: "/rules", rulesText: "The full rules",
    related: "Related guides",
    hubTitle: "Sheng Ji guides: how to play Tractor, step by step",
    hubH1: "Sheng Ji guides",
    hubSub: "How to play Sheng Ji (升级, Tractor), and how to play it well. Each guide covers one part of the game, with real hands.",
    hubDescription: "Guides to Sheng Ji (升级, Tractor): a first hand, declaring trump, burying the kitty, pairs and tractors, scoring and the names of the game.",
    hubRules: "For the rules on one page, see [the rules](/rules).",
    ctaTitle: "Practice this against the bots",
    ctaApp: "Get the iPhone and iPad app",
    ctaWeb: "or play in your browser",
    note: "Automated play is not allowed: AI agents and other automated clients must not join, queue for or play games on this site. Reading these pages is fine. See [llms.txt](/llms.txt) and the [privacy page](/privacy).",
    updated: "Updated",
    sep: " · ",
  },
  zh: {
    htmlLang: "zh-Hans",
    switchLabel: "English", switchLang: "en",
    play: "开始游戏",
    home: "首页", hub: "攻略",
    rules: "/rules/zh", rulesText: "完整规则",
    related: "相关攻略",
    hubTitle: "升级（拖拉机）攻略：从第一局到会打 | Sheng Ji",
    hubH1: "升级攻略",
    hubSub: "升级（拖拉机）怎么打、怎么打好。每篇讲一个环节，用真实的牌例说明。",
    hubDescription: "升级（拖拉机）攻略：第一局怎么打、亮主、埋底、对子拖拉机与甩牌、计分升级，以及升级、拖拉机、八十分、找朋友这些叫法的区别。",
    hubRules: "想看一页纸的完整规则，请看[规则页](/rules/zh)。",
    ctaTitle: "和机器人练一练",
    ctaApp: "下载 iPhone / iPad 版",
    ctaWeb: "或者直接在浏览器里玩",
    note: "本站禁止自动化对局：AI 代理和其他自动化程序不得加入、排队或进行游戏。阅读这些页面不受限制。详见 [llms.txt](/llms.txt) 和[隐私页面](/privacy)。",
    updated: "更新于",
    sep: " · ",
  },
} as const;

/** JSON for a <script> block: no "</" can close the element early. */
export function jsonLd(data: unknown): string {
  return JSON.stringify(data, null, 1)
    .replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026");
}

export const GUIDE_CSS = `
  :root { color-scheme: dark; }
  html, body { margin: 0; background: #14171e; color: #e8ecf2; }
  body { font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { box-sizing: border-box; max-width: 720px; margin: 0 auto; padding: 24px 16px 48px; }
  header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; }
  h1 { margin: 8px 0 4px; font-size: 30px; line-height: 1.2; color: #f2c14e; }
  h2 { margin: 32px 0 8px; font-size: 20px; color: #f2c14e; }
  h3 { margin: 18px 0 4px; font-size: 16px; }
  p, li { color: #d3d8e0; }
  .sub { margin: 0; color: #9aa3b2; }
  a { color: #f2c14e; }
  .play { box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; min-height: 52px; padding: 0 20px;
          border: 1.5px solid #f2c14e; border-radius: 14px; background: linear-gradient(180deg, #8a6a22, #6b5219);
          color: #fff3cf; font-size: 17px; font-weight: 700; text-decoration: none; }
  .lang { font-size: 14px; }
  .note { margin-top: 40px; padding-top: 16px; border-top: 1px solid #3a4150; font-size: 14px; color: #9aa3b2; }
  .crumbs { margin: 16px 0 0; padding: 0; list-style: none; display: flex; flex-wrap: wrap; gap: 6px; font-size: 14px; color: #9aa3b2; }
  .crumbs li { color: #9aa3b2; }
  .crumbs li + li::before { content: "/"; margin-right: 6px; }
  .red { color: #ff7a8a; }
  code { font: 14px ui-monospace, SFMono-Regular, Menlo, monospace; color: #e8ecf2; }
  .aside { margin: 16px 0; padding: 10px 14px; border-left: 3px solid #f2c14e; background: #1b2029; border-radius: 0 8px 8px 0; }
  .table { overflow-x: auto; margin: 12px 0; }
  table { border-collapse: collapse; min-width: 100%; font-size: 15px; }
  th, td { padding: 7px 10px; border-bottom: 1px solid #3a4150; text-align: left; vertical-align: top; color: #d3d8e0; }
  th { color: #e8ecf2; font-weight: 700; }
  .gv { margin: 18px 0; padding: 0; }
  .gv-svg { display: block; width: 100%; max-width: var(--gv-w); height: auto; border-radius: 12px;
            background: radial-gradient(ellipse at 50% 35%, #2a7049 0%, #1d5638 60%, #164530 100%); }
  .gv figcaption { margin-top: 6px; font-size: 14px; color: #9aa3b2; }
  .gv-anim .gv-p, .gv-anim .gv-win, .gv-anim .gv-back, .gv-anim .gv-stay, .gv-anim .gv-tl,
  .gv-anim .gv-lv, .gv-anim .gv-chg { animation-duration: 9s; animation-iteration-count: infinite;
                                      animation-timing-function: ease-out; animation-fill-mode: both; }
  .gv-trick .gv-p0 { animation-name: gv-p0; } .gv-trick .gv-p1 { animation-name: gv-p1; }
  .gv-trick .gv-p2 { animation-name: gv-p2; } .gv-trick .gv-p3 { animation-name: gv-p3; }
  .gv-trick .gv-win { animation-name: gv-win; }
  @keyframes gv-p0 { 0%, 3% { opacity: 0; transform: translateY(14px); } 8%, 92% { opacity: 1; transform: none; } 100% { opacity: 0; } }
  @keyframes gv-p1 { 0%, 14% { opacity: 0; transform: translateY(14px); } 19%, 92% { opacity: 1; transform: none; } 100% { opacity: 0; } }
  @keyframes gv-p2 { 0%, 25% { opacity: 0; transform: translateY(14px); } 30%, 92% { opacity: 1; transform: none; } 100% { opacity: 0; } }
  @keyframes gv-p3 { 0%, 36% { opacity: 0; transform: translateY(14px); } 41%, 92% { opacity: 1; transform: none; } 100% { opacity: 0; } }
  @keyframes gv-win { 0%, 48% { opacity: 0; } 54%, 92% { opacity: 1; } 100% { opacity: 0; } }
  .gv-throw .gv-back { animation-name: gv-back; } .gv-throw .gv-stay { animation-name: gv-stay; }
  .gv-throw .gv-tl { animation-name: gv-tl; }
  @keyframes gv-back { 0%, 30% { transform: translate(var(--dx), var(--dy)); } 50%, 100% { transform: none; } }
  @keyframes gv-stay { 0%, 30% { transform: translateX(var(--dx)); } 50%, 100% { transform: none; } }
  @keyframes gv-tl { 0%, 28% { opacity: 0; } 34%, 100% { opacity: 1; } }
  .gv-levels .gv-lv { animation-name: gv-lv; } .gv-levels .gv-chg { animation-name: gv-chg; }
  @keyframes gv-lv { 0%, 20% { transform: translateX(var(--dx)); } 55%, 100% { transform: none; } }
  @keyframes gv-chg { 0%, 52% { opacity: 0; } 60%, 100% { opacity: 1; } }
  @media (prefers-reduced-motion: reduce) { .gv-anim * { animation: none !important; } }
  .cta { margin: 36px 0 8px; padding: 18px 16px; border: 1px solid #3a4150; border-radius: 14px; background: #1b2029; }
  .cta h2 { margin-top: 0; }
  .cta p { margin: 8px 0 0; }
  .related { padding-left: 20px; }
  .hub { list-style: none; padding: 0; }
  .hub li { margin: 0 0 18px; }
  .hub a { font-size: 18px; font-weight: 700; }
  .hub p { margin: 2px 0 0; }
`;

function head(opts: {
  lang: Lang; title: string; description: string; url: string; enUrl: string; zhUrl: string;
  ogTitle: string; ogType: string; ld: unknown;
}): string {
  return `<!doctype html>
<html lang="${T[opts.lang].htmlLang}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="theme-color" content="#14171e" />
<meta name="color-scheme" content="dark" />
<title>${esc(opts.title)}</title>
<meta name="description" content="${esc(opts.description)}" />
<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
<link rel="canonical" href="${opts.url}" />
<link rel="alternate" hreflang="en" href="${opts.enUrl}" />
<link rel="alternate" hreflang="zh-Hans" href="${opts.zhUrl}" />
<link rel="alternate" hreflang="x-default" href="${opts.enUrl}" />
<meta property="og:type" content="${opts.ogType}" />
<meta property="og:site_name" content="${esc(SITE_NAME)}" />
<meta property="og:url" content="${opts.url}" />
<meta property="og:title" content="${esc(opts.ogTitle)}" />
<meta property="og:description" content="${esc(opts.description)}" />
<meta property="og:image" content="${IMAGE}" />
<meta property="og:locale" content="${opts.lang === "en" ? "en_US" : "zh_CN"}" />
<meta name="twitter:card" content="summary_large_image" />
<script type="application/ld+json">
${jsonLd(opts.ld)}
</script>
<style>${GUIDE_CSS}</style>
</head>`;
}

function chrome(lang: Lang, otherPath: string): string {
  const t = T[lang];
  return `<header>
  <a class="lang" href="${otherPath}" hreflang="${t.switchLang}" lang="${t.switchLang}">${t.switchLabel}</a>
  <a class="play" href="/">${t.play}</a>
</header>`;
}

function crumbs(lang: Lang, here?: string): string {
  const t = T[lang];
  const items = [`<li><a href="/">${t.home}</a></li>`,
    here ? `<li><a href="${guidePath(lang)}">${t.hub}</a></li>` : `<li>${t.hub}</li>`];
  if (here) items.push(`<li>${esc(here)}</li>`);
  return `<nav aria-label="${lang === "en" ? "Breadcrumb" : "导航"}"><ol class="crumbs">${items.join("")}</ol></nav>`;
}

function footer(lang: Lang): string {
  return `<p class="note">${inlineNote(T[lang].note)}</p>`;
}

function inlineNote(text: string): string {
  return esc(text).replace(/\[([^\]]+)\]\((\/[^)]+)\)/g, '<a href="$2">$1</a>');
}

function breadcrumbLd(lang: Lang, url: string, title?: string): unknown {
  const t = T[lang];
  const items: { "@type": string; position: number; name: string; item: string }[] = [
    { "@type": "ListItem", position: 1, name: t.home, item: `${SITE_ORIGIN}/` },
    { "@type": "ListItem", position: 2, name: t.hub, item: SITE_ORIGIN + guidePath(lang) },
  ];
  if (title) items.push({ "@type": "ListItem", position: 3, name: title, item: url });
  return { "@type": "BreadcrumbList", "@id": `${url}#breadcrumb`, itemListElement: items };
}

function cta(lang: Lang): string {
  const t = T[lang];
  return `<aside class="cta" data-cta="app">
<h2>${t.ctaTitle}</h2>
<p><a class="play" href="${APP_STORE_URL}">${t.ctaApp}</a></p>
<p><a href="/">${t.ctaWeb}</a></p>
</aside>`;
}

export function guidePage(guide: Guide, byKey: Map<string, Guide>): string {
  const { meta } = guide;
  const lang = meta.lang;
  const t = T[lang];
  const other: Lang = lang === "en" ? "zh" : "en";
  const url = SITE_ORIGIN + guidePath(lang, meta.slug);
  const enUrl = SITE_ORIGIN + guidePath("en", meta.slug);
  const zhUrl = SITE_ORIGIN + guidePath("zh", meta.slug);
  const title = plain(meta.title);
  const description = plain(meta.description);
  const graph: unknown[] = [
    {
      "@type": "Article",
      "@id": `${url}#article`,
      headline: title,
      description,
      inLanguage: t.htmlLang,
      url,
      mainEntityOfPage: url,
      image: IMAGE,
      dateModified: meta.updated,
      datePublished: meta.updated,
      author: { "@type": "Organization", name: SITE_NAME, url: `${SITE_ORIGIN}/` },
      publisher: { "@type": "Organization", name: SITE_NAME, url: `${SITE_ORIGIN}/` },
      about: { "@type": "Game", name: "Sheng Ji", alternateName: ["升级", "Tractor", "拖拉机", "八十分"] },
      isPartOf: { "@type": "WebSite", name: SITE_NAME, url: `${SITE_ORIGIN}/` },
    },
    breadcrumbLd(lang, url, title),
  ];
  if (meta.schema === "HowTo") {
    const steps = guide.headings.filter((h) => h.level === 2 && h.firstParagraph);
    graph.push({
      "@type": "HowTo",
      "@id": `${url}#howto`,
      name: title,
      description,
      inLanguage: t.htmlLang,
      step: steps.map((h, i) => ({
        "@type": "HowToStep", position: i + 1, name: plain(h.text), text: plain(h.firstParagraph), url: `${url}#${h.id}`,
      })),
    });
  }
  const related = meta.related.map((slug) => {
    const g = byKey.get(`${lang}/${slug}`);
    if (!g) throw new GuideError(`${lang}/${meta.slug}: related guide ${slug} does not exist`);
    return `<li><a href="${guidePath(lang, slug)}">${esc(plain(g.meta.title))}</a></li>`;
  });
  return `${head({
    lang, title: `${title}${lang === "en" ? " | Sheng Ji guides" : " | 升级攻略"}`, description, url, enUrl, zhUrl,
    ogTitle: title, ogType: "article", ld: { "@context": "https://schema.org", "@graph": graph },
  })}
<body>
<main>
${chrome(lang, guidePath(other, meta.slug))}
${crumbs(lang, title)}
<article>
<h1>${esc(title)}</h1>
<p class="sub">${esc(description)}</p>
${guide.html}
</article>
${cta(lang)}
<h2>${t.related}</h2>
<ul class="related">
${related.join("\n")}
<li><a href="${t.rules}">${t.rulesText}</a></li>
</ul>
<p class="sub">${t.updated} ${meta.updated}</p>
${footer(lang)}
</main>
</body>
</html>
`;
}

export function hubPage(lang: Lang, guides: Guide[]): string {
  const t = T[lang];
  const other: Lang = lang === "en" ? "zh" : "en";
  const url = SITE_ORIGIN + guidePath(lang);
  const graph = [
    {
      "@type": "CollectionPage",
      "@id": `${url}#page`,
      name: t.hubH1,
      description: t.hubDescription,
      inLanguage: t.htmlLang,
      url,
      isPartOf: { "@type": "WebSite", name: SITE_NAME, url: `${SITE_ORIGIN}/` },
      mainEntity: {
        "@type": "ItemList",
        itemListElement: guides.map((g, i) => ({
          "@type": "ListItem", position: i + 1, name: plain(g.meta.title), url: SITE_ORIGIN + guidePath(lang, g.meta.slug),
        })),
      },
    },
    breadcrumbLd(lang, url),
  ];
  const items = guides.map((g) => `<li><a href="${guidePath(lang, g.meta.slug)}">${esc(plain(g.meta.title))}</a>
<p>${esc(plain(g.meta.description))}</p></li>`);
  return `${head({
    lang, title: t.hubTitle, description: t.hubDescription, url,
    enUrl: SITE_ORIGIN + guidePath("en"), zhUrl: SITE_ORIGIN + guidePath("zh"),
    ogTitle: t.hubH1, ogType: "website", ld: { "@context": "https://schema.org", "@graph": graph },
  })}
<body>
<main>
${chrome(lang, guidePath(other))}
${crumbs(lang)}
<h1>${t.hubH1}</h1>
<p class="sub">${esc(t.hubSub)}</p>
<ul class="hub">
${items.join("\n")}
</ul>
<p>${inlineNote(t.hubRules)}</p>
${footer(lang)}
</main>
</body>
</html>
`;
}

export function parseGuides(sources: Source[]): Guide[] {
  const guides: Guide[] = [];
  for (const src of sources) {
    const m = /^(en|zh)\/([a-z0-9-]+)\.md$/.exec(src.path);
    if (!m) throw new GuideError(`${src.path}: guides live at <en|zh>/<slug>.md`);
    const { meta, body } = parseFrontMatter(src.text, src.path);
    if (meta.lang !== m[1] || meta.slug !== m[2]) throw new GuideError(`${src.path}: lang and slug must match the path`);
    resetIds();
    const { html, headings } = render(body, meta.lang);
    guides.push({ meta, html, headings });
  }
  const order = (a: Guide, b: Guide) => a.meta.order - b.meta.order || a.meta.slug.localeCompare(b.meta.slug);
  guides.sort(order);
  const en = new Set(guides.filter((g) => g.meta.lang === "en").map((g) => g.meta.slug));
  const zh = new Set(guides.filter((g) => g.meta.lang === "zh").map((g) => g.meta.slug));
  for (const slug of new Set([...en, ...zh])) {
    if (!en.has(slug) || !zh.has(slug)) throw new GuideError(`guide ${slug} needs both an en and a zh source`);
  }
  return guides;
}

const SITEMAP_START = "  <!-- guides: generated by scripts/build_guides.ts -->";
const SITEMAP_END = "  <!-- /guides -->";

function sitemapEntries(guides: Guide[]): string {
  const slugs = [...new Set(guides.map((g) => g.meta.slug))];
  const updated = new Map(guides.map((g) => [`${g.meta.lang}/${g.meta.slug}`, g.meta.updated]));
  const entry = (lang: Lang, slug?: string) => {
    const alt = (["en", "zh"] as Lang[]).map((l) =>
      `    <xhtml:link rel="alternate" hreflang="${T[l].htmlLang}" href="${SITE_ORIGIN}${guidePath(l, slug)}" />`).join("\n");
    const lastmod = slug ? `\n    <lastmod>${updated.get(`${lang}/${slug}`)}</lastmod>` : "";
    return `  <url>\n    <loc>${SITE_ORIGIN}${guidePath(lang, slug)}</loc>${lastmod}\n${alt}\n  </url>`;
  };
  const out: string[] = [];
  for (const lang of ["en", "zh"] as Lang[]) {
    out.push(entry(lang));
    for (const slug of slugs) out.push(entry(lang, slug));
  }
  return out.join("\n");
}

/** The sitemap with its guides section replaced (or added before </urlset>). */
export function withGuidesInSitemap(sitemap: string, guides: Guide[]): string {
  const block = `${SITEMAP_START}\n${sitemapEntries(guides)}\n${SITEMAP_END}`;
  const start = sitemap.indexOf(SITEMAP_START);
  const end = sitemap.indexOf(SITEMAP_END);
  if (start >= 0 && end > start) return sitemap.slice(0, start) + block + sitemap.slice(end + SITEMAP_END.length);
  const close = sitemap.lastIndexOf("</urlset>");
  if (close < 0) throw new GuideError("sitemap.xml has no </urlset>");
  return `${sitemap.slice(0, close)}${block}\n${sitemap.slice(close)}`;
}

/** Every generated file under web/public/, keyed by its path there. */
export function buildSite(sources: Source[], sitemap: string): Map<string, string> {
  const guides = parseGuides(sources);
  const byKey = new Map(guides.map((g) => [`${g.meta.lang}/${g.meta.slug}`, g]));
  const out = new Map<string, string>();
  for (const lang of ["en", "zh"] as Lang[]) {
    const mine = guides.filter((g) => g.meta.lang === lang);
    out.set(outputFile(guidePath(lang)), hubPage(lang, mine));
    for (const g of mine) out.set(outputFile(guidePath(lang, g.meta.slug)), guidePage(g, byKey));
  }
  out.set("sitemap.xml", withGuidesInSitemap(sitemap, guides));
  return out;
}
