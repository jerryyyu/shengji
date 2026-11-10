// Real-browser check (manual; CI has no browser): in a portrait game drawn turned, the round-end dialog, which
// showModal() lifts into the top layer, takes the same quarter turn as the table and Next round is hit where drawn.
//   node scripts/rotated-dialog-check.mjs [--css src/index.css] [--out DIR] [--chrome PATH]   exit 0 pass, 1 fail
import { chromium } from 'playwright-core';
import { readFileSync } from 'node:fs';
const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fallback; };
const css = arg('--css', new URL('../src/index.css', import.meta.url).pathname);
const out = arg('--out', null);
const browser = await chromium.launch({ executablePath: arg('--chrome', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome') });
const res = {};
for (const [w, h] of [[390, 844], [375, 667]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, hasTouch: true, isMobile: true, deviceScaleFactor: 2 });
  await page.setContent('<html class="phone-landscape"><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body><div class="app rotated"><div class="table-screen"></div><dialog class="modal-backdrop"><div class="modal"><h2 class="modal-title">Round over</h2><p>Defenders 85 points</p><button class="btn primary" id="next">Next round</button></div></dialog></div></body></html>');
  await page.addStyleTag({ content: readFileSync(css, 'utf8') });
  await page.locator('dialog').evaluate(d => d.showModal());
  await page.waitForTimeout(400);
  const r = await page.evaluate(() => {
    const app = document.querySelector('.app'), dlg = document.querySelector('dialog'), btn = document.getElementById('next');
    const b = btn.getBoundingClientRect(), d = dlg.getBoundingClientRect();
    const hit = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);
    return { appT: getComputedStyle(app).transform, dlgT: getComputedStyle(dlg).transform, dlgBox: [d.x, d.y, d.width, d.height].map(Math.round),
             btnBox: [b.x, b.y, b.width, b.height].map(Math.round), hitsNext: hit === btn, modal: dlg.matches(':modal') };
  });
  await page.tap('#next').catch(e => { r.tapError = String(e).slice(0, 120); });
  res[`${w}x${h}`] = r;
  if (out) await page.screenshot({ path: `${out}/rotated_dialog_${w}x${h}.png` });
  await page.close();
}
console.log(JSON.stringify(res, null, 1));
const ok = Object.values(res).every(r => r.modal && r.dlgT === r.appT && r.hitsNext && !r.tapError && r.btnBox[3] > r.btnBox[2]);
await browser.close();
process.exit(ok ? 0 : 1);
