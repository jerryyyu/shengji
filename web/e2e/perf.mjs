/** Start Vite separately, then BASE=http://127.0.0.1:5173/ OUT=/path node e2e/perf.mjs.
 * PERF_MS bounds the game window (1000..25000, default 20000). Mock native bridge,
 * SmartBot, phone viewport; not a physical-phone or release-bot benchmark.
 * The separate injected stall validates callback measurement, not game speed.
 */
import fs from 'node:fs';
import path from 'node:path';
import {launch,open,OUT} from './lib.mjs';
const duration=Number(process.env.PERF_MS ?? 20000);
if (!Number.isInteger(duration) || duration<1000 || duration>25000) throw new Error('PERF_MS must be 1000..25000');
const browser=await launch();
try {
 const page=await open(browser,'phone-land-app',{url:'?offline=1&table=1',native:true,fakeSocket:'window.__shengjiOfflineAutoplay = true;',storage:{'shengji.name':'Perf validation','shengji.coach':'off'}});
 await page.getByRole('button',{name:'Start',exact:true}).waitFor({timeout:15000});
 await page.evaluate(()=>window.__qa.startPerf({maxSamples:2000}));
 await page.getByRole('button',{name:'Start',exact:true}).click();
 await page.waitForSelector('.table-screen');
 await page.waitForTimeout(duration);
 const gameplay=await page.evaluate(()=>({perf:window.__qa.stopPerf(),longTasks:window.__qa.longTasks,table:!!document.querySelector('.table-screen')}));
 await page.evaluate(()=>window.__qa.startPerf({maxSamples:120}));
 await page.waitForTimeout(100);
 await page.evaluate(()=>{window.dispatchEvent(new PointerEvent('pointerdown'));const end=performance.now()+80;while(performance.now()<end){};});
 await page.waitForTimeout(150);
 const injected=await page.evaluate(()=>window.__qa.stopPerf());
 const result={environment:'desktop Chromium, phone viewport, mock native bridge/SmartBot fallback, Vite dev build; NOT physical phone or release bot timing',gameplay,injected,errors:page.qa.errors};
 result.scenario='fresh offline autoplay; random deal, no matched comparison';
 result.valid=gameplay.table && gameplay.perf.frameGaps.length>0 && injected.inputToNextFrame.some(s=>s.latencyMs>=75) && page.qa.errors.length===0;
 fs.writeFileSync(path.join(OUT,'perf.json'),JSON.stringify(result,null,2));
 if (!result.valid) process.exitCode=1;
 console.log(JSON.stringify({frames:gameplay.perf.frameGaps.length,table:gameplay.table,injectedInput:injected.inputToNextFrame,errors:page.qa.errors}));
}finally{await browser.close();}
