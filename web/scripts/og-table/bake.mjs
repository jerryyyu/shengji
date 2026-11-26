// Bakes the coverage masks the server composes a table's link preview from
// (server/shengji/api/invite_preview.py): the wordmark, the code's glyphs,
// the initials, the bot and person marks, the seat circles and one line per
// seat count. Each mask is a canvas's alpha channel, so the server needs no
// font or image library: it tints and blends them with numpy.
//
//   NODE_PATH=<node_modules with playwright> node web/scripts/og-table/bake.mjs > /tmp/masks.json
//   python3 web/scripts/og-table/pack.py /tmp/masks.json server/shengji/api/invite_atlas.npz
//
// Text is drawn with the system's fonts (PingFang SC for 升级, the system UI
// face for Latin), as the default preview's scene is, so bake on macOS.
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

// The strings and sizes the server's layout expects; the server reads every
// position from the masks' own metrics, so only these names are shared.
const SPEC = {
  codeAlphabet: "ABCDEFGHJKLMNPQRSTUVWXYZ23456789",
  initials: "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
  lines: {
    one: "三缺一 · 1 open seat",
    two: "二缺二 · 2 open seats",
    three: "一缺三 · 3 open seats",
    partner: "等搭档 · partner seat open",
  },
  seat: 200,          // circle diameter
  seatBorder: 7,
  codeSize: 60,
  codeSpacing: 15,    // .25em
  codePadX: 26,
  codePadY: 10,
  codeBorder: 5,
};

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const page = await browser.newPage({ deviceScaleFactor: 1 });
await page.setContent("<!doctype html><meta charset=utf-8><body></body>");
const out = await page.evaluate(async (spec) => {
  const SANS = '"PingFang SC", -apple-system, "Helvetica Neue", Arial, sans-serif';
  const masks = {};
  const alphaOf = (c) => {
    const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    const a = new Array(c.width * c.height);
    for (let i = 0; i < a.length; i++) a[i] = d[i * 4 + 3];
    return a;
  };
  const canvas = (w, h) => {
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    return c;
  };
  // A text mask: its box relative to the pen at the baseline (x0, y0) and
  // its advance, so glyphs set side by side keep the font's spacing.
  const text = (name, s, font, spacing = 0) => {
    const probe = canvas(4, 4).getContext("2d");
    probe.font = font;
    probe.letterSpacing = `${spacing}px`;
    const m = probe.measureText(s);
    const pad = 4;
    const left = Math.ceil(m.actualBoundingBoxLeft) + pad;
    const asc = Math.ceil(m.actualBoundingBoxAscent) + pad;
    const w = left + Math.ceil(m.actualBoundingBoxRight) + pad;
    const h = asc + Math.ceil(m.actualBoundingBoxDescent) + pad;
    const c = canvas(Math.max(w, 1), Math.max(h, 1));
    const g = c.getContext("2d");
    g.font = font;
    g.letterSpacing = `${spacing}px`;
    g.fillStyle = "#fff";
    g.fillText(s, left, asc);
    masks[name] = { w: c.width, h: c.height, x0: -left, y0: -asc, adv: m.width - spacing, a: alphaOf(c) };
  };
  const shape = (name, w, h, draw) => {
    const c = canvas(w, h);
    const g = c.getContext("2d");
    g.fillStyle = "#fff";
    g.strokeStyle = "#fff";
    draw(g);
    masks[name] = { w, h, x0: 0, y0: 0, adv: w, a: alphaOf(c) };
  };

  await document.fonts.ready;
  text("brand_zh", "升级", `800 84px ${SANS}`);
  text("brand_en", "SHENG JI", `500 40px ${SANS}`, 12);
  for (const ch of spec.codeAlphabet) text(`code_${ch}`, ch, `800 ${spec.codeSize}px ${SANS}`);
  for (const ch of spec.initials) text(`init_${ch}`, ch, `800 84px ${SANS}`);
  text("cap_init", "H", `800 84px ${SANS}`);
  text("cap_code", "H", `800 ${spec.codeSize}px ${SANS}`);
  text("plus", "+", `300 110px ${SANS}`);
  for (const [k, s] of Object.entries(spec.lines)) text(`line_${k}`, s, `700 54px ${SANS}`);

  const d = spec.seat, b = spec.seatBorder, r = d / 2;
  shape("disc", d, d, (g) => { g.beginPath(); g.arc(r, r, r, 0, Math.PI * 2); g.fill(); });
  shape("ring", d, d, (g) => {
    g.lineWidth = b; g.beginPath(); g.arc(r, r, r - b / 2, 0, Math.PI * 2); g.stroke();
  });
  shape("dash_ring", d, d, (g) => {
    g.lineWidth = b * 0.8;
    const circ = Math.PI * 2 * (r - b / 2);
    const n = 24;   // dashes round the circle, each with an equal gap
    g.setLineDash([circ / n / 2, circ / n / 2]);
    g.beginPath(); g.arc(r, r, r - b / 2, -Math.PI / 2, Math.PI * 1.5); g.stroke();
  });
  // The bot mark: a head with an antenna, its eyes and mouth cut out.
  shape("bot", 120, 120, (g) => {
    g.lineWidth = 7; g.lineCap = "round";
    g.beginPath(); g.moveTo(60, 14); g.lineTo(60, 34); g.stroke();
    g.beginPath(); g.arc(60, 12, 8, 0, Math.PI * 2); g.fill();
    g.beginPath(); g.roundRect(14, 34, 92, 72, 18); g.fill();
    g.beginPath(); g.roundRect(4, 56, 10, 28, 4); g.roundRect(106, 56, 10, 28, 4); g.fill();
    g.globalCompositeOperation = "destination-out";
    g.beginPath(); g.arc(42, 64, 10, 0, Math.PI * 2); g.arc(78, 64, 10, 0, Math.PI * 2); g.fill();
    g.beginPath(); g.roundRect(40, 86, 40, 8, 4); g.fill();
  });
  // A person without a Latin initial: a head and shoulders.
  shape("person", 110, 110, (g) => {
    g.beginPath(); g.arc(55, 34, 24, 0, Math.PI * 2); g.fill();
    g.beginPath(); g.ellipse(55, 108, 44, 40, 0, Math.PI, Math.PI * 2); g.fill();
  });
  // The code's dashed box, wide enough for the widest four glyphs.
  const widest = Math.max(...[...spec.codeAlphabet].map((ch) => masks[`code_${ch}`].adv));
  const bw = Math.ceil(4 * widest + 3 * spec.codeSpacing + 2 * (spec.codePadX + spec.codeBorder));
  const capCode = -masks.cap_code.y0 - 4;
  const bh = Math.ceil(capCode + 2 * (spec.codePadY + spec.codeBorder) + 16);
  shape("code_box", bw, bh, (g) => {
    g.lineWidth = spec.codeBorder;
    g.setLineDash([14, 9]);
    const h = spec.codeBorder / 2;
    g.beginPath(); g.roundRect(h, h, bw - 2 * h, bh - 2 * h, 22); g.stroke();
  });
  return { spec, masks };
}, SPEC);
await browser.close();
process.stdout.write(JSON.stringify(out));
