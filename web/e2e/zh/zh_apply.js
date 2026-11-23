// Mock-only: rewrites the rendered English into the draft zh-Hans strings, live,
// and sets the page's language and a CJK font stack. Not production i18n.
(() => {
  const Z = window.__ZH;
  const exact = new Map(Z.exact.map(([en, zh]) => [en, zh]));
  const pats = Z.patterns.map(([src, rep]) => [new RegExp(src), rep]);
  const SUIT = { spades: "黑桃", hearts: "红桃", diamonds: "方块", clubs: "梅花" };
  const RANK = { Ace: "A", King: "K", Queen: "Q", Jack: "J" };
  const sub = (key) => {
    if (exact.has(key)) return exact.get(key);
    for (const [re, rep] of pats) {
      const m = key.match(re);
      if (!m) continue;
      if (rep === "CARD") return `${SUIT[m[2]]}${RANK[m[1]] ?? m[1]}`;
      return rep.replace(/\$(\d)/g, (_, i) => exact.get(m[+i]) ?? m[+i]);
    }
    return null;
  };
  const done = new WeakMap();
  const text = (n) => {
    const v = n.nodeValue;
    if (done.get(n) === v) return;
    const key = v.trim();
    if (!key) return;
    let zh = null;
    const el = n.parentElement;
    for (const [sel, en, z] of Z.scoped) if (en === key && el?.closest(sel)) { zh = z; break; }
    zh ??= sub(key);
    if (zh === null) return;
    const lead = v.match(/^\s*/)[0], trail = v.match(/\s*$/)[0];
    const out = lead + zh + trail;
    done.set(n, out);
    if (out !== v) n.nodeValue = out;
  };
  // Chinese sets no space between Han characters or next to full-width punctuation,
  // and keeps one between Han and Latin or digits.
  const HAN = /[\u3400-\u9fff]/, FW = /[\u3000-\u303f\uff00-\uffef]/;
  const near = (n, dir) => {
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    w.currentNode = n;
    for (let m; (m = dir < 0 ? w.previousNode() : w.nextNode());) {
      const t = dir < 0 ? m.nodeValue.trimEnd() : m.nodeValue.trimStart();
      if (t) return dir < 0 ? t[t.length - 1] : t[0];
    }
    return "";
  };
  const tight = (a, b) => FW.test(a) || FW.test(b) || (HAN.test(a) && HAN.test(b));
  const spaces = () => {
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const todo = [];
    for (let n; (n = w.nextNode());) if (/\s$|^\s/.test(n.nodeValue)) todo.push(n);
    for (const n of todo) {
      let v = n.nodeValue;
      if (!v.trim()) { if (tight(near(n, -1), near(n, 1))) v = ""; }
      else {
        if (/\s$/.test(v) && tight(v.trimEnd().slice(-1), near(n, 1))) v = v.trimEnd();
        if (/^\s/.test(v) && tight(near(n, -1), v.trimStart()[0])) v = v.trimStart();
      }
      if (v !== n.nodeValue) { n.nodeValue = v; done.set(n, v); }
    }
  };
  let pend = 0;
  const later = () => { if (!pend) pend = setTimeout(() => { pend = 0; spaces(); }, 50); };
  const ATTRS = ["aria-label", "title", "placeholder"];
  const attrs = (e) => {
    for (const a of ATTRS) {
      const v = e.getAttribute(a);
      if (!v || e.dataset["zh" + a.replace("-", "")] === v) continue;
      const zh = sub(`@${a}:${v}`);
      if (zh !== null && zh !== v) { e.dataset["zh" + a.replace("-", "")] = zh; e.setAttribute(a, zh); }
    }
  };
  const walk = (root) => {
    if (root.nodeType === 3) return text(root);
    if (root.nodeType !== 1) return;
    attrs(root);
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    for (let n; (n = w.nextNode());) n.nodeType === 3 ? text(n) : attrs(n);
  };
  const start = () => {
    document.documentElement.lang = "zh-Hans";
    const s = document.createElement("style");
    s.textContent = `:root, html, body { font-family: -apple-system, "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", system-ui, sans-serif !important; }
      .action-bar:has(.btn.gold)::before { content: "亮主" !important; }`;
    document.head.appendChild(s);
    walk(document.body); later();
    new MutationObserver((ms) => {
      later();
      for (const m of ms) {
        if (m.type === "characterData") text(m.target);
        else if (m.type === "attributes") attrs(m.target);
        else for (const n of m.addedNodes) walk(n);
      }
    }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  };
  if (document.body) start(); else document.addEventListener("DOMContentLoaded", start);
})();
