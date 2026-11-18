// A second person for a manual or Simulator session: joins the table with the
// given code, taps Start, plays its seat, and says a quick phrase now and then.
//   node e2e/partner.mjs CODE [minutes=15] [chat every s=25]
import { launch, open, sleep, state } from "./lib.mjs";
import { act } from "./drive.mjs";

const [code, minutes = "15", every = "25"] = process.argv.slice(2);
if (!code) { console.error("usage: node e2e/partner.mjs CODE [minutes] [chat-every-s]"); process.exit(2); }
const browser = await launch();
const page = await open(browser, "phone-land", { url: `?code=${code}`, storage: { "shengji.coach": "off", "shengji.name": "Partner Pat" } });
await page.click(".tp-primary", { timeout: 10000 });           // Join
await sleep(800);
await page.click(".tp-primary", { timeout: 10000 }).catch(() => {}); // Start
console.log("partner seated at", code);
const end = Date.now() + Number(minutes) * 60000;
let lastChat = Date.now();
while (Date.now() < end) {
  const s = await state(page).catch(() => null);
  if (s?.phase === "round_end") await page.click("text=Next round", { timeout: 2000 }).catch(() => {});
  const did = await act(page).catch(() => null);
  if (s && Date.now() - lastChat > Number(every) * 1000) {
    lastChat = Date.now();
    try {
      await page.click(".chat-launch", { timeout: 2000 });
      await page.click(".chat-quick-btn", { timeout: 2000 });
      await page.click(".chat-close", { timeout: 2000 });
      console.log("partner said a phrase");
    } catch { /* no chat right now */ }
  }
  if (!did) await sleep(300);
}
await browser.close();
