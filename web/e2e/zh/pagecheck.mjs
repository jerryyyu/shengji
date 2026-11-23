import { chromium } from "playwright-core";
const b = await chromium.launch({ executablePath: process.env.CP });
for (const [w, h, s, n] of [[1280, 2000, "dark", "desk"], [390, 2400, "light", "phone"]]) {
  const p = await b.newPage({ viewport: { width: w, height: h }, colorScheme: s });
  await p.goto("file:///Users/jerryyu/.claude/jobs/d0498cda/tmp/zh_mocks/index.html");
  await p.waitForTimeout(800);
  console.log(n, await p.evaluate(() => [document.documentElement.scrollWidth, innerWidth]));
  await p.screenshot({ path: `/tmp/zh_page_${n}.png` });
  if (n === "desk") { await p.evaluate(() => document.querySelector("#terms").scrollIntoView()); await p.screenshot({ path: "/tmp/zh_page_terms.png" }); }
}
await b.close();
