// Traversée du CHECKOUT CREEM (page tierce) — appelé par run.sh entre les
// suites Selenium. La page rejette l'automatisation WebDriver classique
// (options sélectionnables uniquement par pointerdown/clavier trusted, liste
// de pays virtualisée, popover interceptant les clics natifs) : cette recette
// CDP est celle validée de bout en bout jusqu'à ?pro=success&order_id=….
// Usage : node checkout-creem.mjs <checkout_url> <card> <expiry> <cvc> <name>
//   env : CDP_WS (websocket CDP d'une session du grid Selenium)
import puppeteer from "puppeteer-core";

const [URL_CO, CARD, EXPIRY, CVC, HOLDER] = process.argv.slice(2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await puppeteer.connect({
  browserWSEndpoint: process.env.CDP_WS,
  defaultViewport: { width: 1400, height: 1600 },
});
const page = (await browser.pages()).at(-1) || (await browser.newPage());
await page.goto(URL_CO, { waitUntil: "domcontentloaded", timeout: 60000 }).catch(() => {});
await sleep(10000);

// --- étape 1 : nom + pays (clavier trusted) + submit natif ------------------
if (await page.$("#name")) await page.type("#name", HOLDER).catch(() => {});
await page.evaluate(() => {
  [...document.querySelectorAll("button")]
    .find((b) => /pays de facturation|billing country|France/i.test(b.textContent))?.click();
});
await sleep(1500);
const opt = await page.$('[role="option"]');
if (opt) {
  await opt.type("F");                       // saute aux F (liste virtualisée)
  await sleep(700);
  for (let i = 0; i < 15; i++) {
    const cur = await page.evaluate(() => document.activeElement?.textContent?.trim());
    if (cur === "France") break;
    await page.keyboard.press("ArrowDown");
    await sleep(250);
  }
  await page.keyboard.press("Enter");
  await sleep(1000);
}
// submit : scroll centré PUIS clic natif (pointerdown trusted exigé ; sans
// centrage le point de clic tombe sous le bandeau sticky)
await page.evaluate(() => {
  [...document.querySelectorAll("button")]
    .find((b) => b.offsetWidth > 0 && b.type === "submit")
    ?.scrollIntoView({ block: "center" });
});
await sleep(800);
const sb = await page.evaluateHandle(() =>
  [...document.querySelectorAll("button")]
    .find((b) => b.offsetWidth > 0 && b.type === "submit"));
await sb.asElement().click();
console.log("étape 1 soumise");

// --- étape 2 : carte (SDK Yuno) + titulaire + Pay ---------------------------
let card;
for (let i = 0; i < 15 && !card; i++) {
  await sleep(4000);
  card = page.frames().find((f) => f.url().includes("y.uno"));
}
if (!card) { console.error("iframe carte jamais montée"); process.exit(1); }
const typeIn = async (frame, sel, txt) => {
  const h = await frame.$(sel);
  if (h) { await h.type(txt, { delay: 40 }); return true; }
  return false;
};
await typeIn(card, 'input[name="number"]', CARD);
await typeIn(card, 'input[name="expirationDate"]', EXPIRY);   // chiffres seuls
await typeIn(card, 'input[name="cvv"]', CVC);
await sleep(3000);
// titulaire : name="cardHolderName", dans le document principal, ajouté
// dynamiquement après reconnaissance de la carte (pas de placeholder)
let ok = false;
for (let i = 0; i < 8 && !ok; i++) {
  ok = await typeIn(page.mainFrame(), 'input[name="cardHolderName"]', HOLDER);
  if (!ok) await sleep(2000);
}
if (!ok) { console.error("champ titulaire jamais apparu"); process.exit(1); }
await page.evaluate(() => {
  [...document.querySelectorAll("button")]
    .find((b) => b.offsetWidth > 0 && /pay|payer/i.test(b.textContent))
    ?.scrollIntoView({ block: "center" });
});
await sleep(600);
const pb = await page.evaluateHandle(() =>
  [...document.querySelectorAll("button")]
    .find((b) => b.offsetWidth > 0 && /pay|payer/i.test(b.textContent)));
await pb.asElement().click();
console.log("paiement soumis");

for (let i = 0; i < 30; i++) {
  await sleep(4000);
  const u = page.url();
  if (u.includes("pro=success")) {
    console.log("SUCCESS:", u.slice(0, 140));
    await browser.disconnect();
    process.exit(0);
  }
  if (i % 5 === 4) console.log(`[${(i + 1) * 4}s]`, u.slice(0, 90));
}
console.error("jamais redirigé vers ?pro=success — url:", page.url().slice(0, 120));
process.exit(1);
