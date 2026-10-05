// Capture the user guide's screenshots from a running demo server with headless Edge (DevTools protocol).
// Usage: node make_screenshots.mjs <out-dir>   (server: python demo/server.py --simulate). Called by build.py.
import { spawn } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";

const EDGE = process.env.EDGE || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const BASE = "http://127.0.0.1:8765";
const OUT = process.argv[2];
const PORT = 9333;
mkdirSync(OUT, { recursive: true });

const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${tmpdir()}/sigil-guide-edge`, "--window-size=1440,900", "about:blank"],
  { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let targets;
for (let i = 0; i < 50; i++) {
  try { targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(); if (targets.some((t) => t.type === "page")) break; } catch {}
  await sleep(200);
}
const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0; const pending = new Map(); const waiters = [];
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  if (m.method) for (const w of [...waiters]) if (w.method === m.method) { waiters.splice(waiters.indexOf(w), 1); w.resolve(m); }
});
const send = (method, params = {}) => new Promise((resolve) => { const i = ++id; pending.set(i, resolve); ws.send(JSON.stringify({ id: i, method, params })); });
const once = (method) => new Promise((resolve) => waiters.push({ method, resolve }));
const js = async (expression) => {
  const r = await send("Runtime.evaluate", { expression: `(async () => { ${expression} })()`, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(`${expression}\n${JSON.stringify(r.result.exceptionDetails).slice(0, 400)}`);
  return r.result?.result?.value;
};

await send("Page.enable");
await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

async function go(path) {
  const loaded = once("Page.loadEventFired");
  await send("Page.navigate", { url: BASE + path });
  await loaded;
  await sleep(2600);   // data fetch + entry animations
}
async function shot(name, { full = false } = {}) {
  await sleep(300);
  const params = { format: "png" };
  if (full) {
    const h = await js("return document.documentElement.scrollHeight");
    params.clip = { x: 0, y: 0, width: 1440, height: Math.min(h, 4000), scale: 1 };
    params.captureBeyondViewport = true;
  }
  const r = await send("Page.captureScreenshot", params);
  writeFileSync(`${OUT}/${name}.png`, Buffer.from(r.result.data, "base64"));
  console.log("saved", name);
}
const scrollTo = (sel, block = "start", dy = 0) =>
  js(`document.querySelector(${JSON.stringify(sel)}).scrollIntoView({behavior: "instant", block: "${block}"}); window.scrollBy({top: ${dy}, behavior: "instant"}); await new Promise(r => setTimeout(r, 900));`);
const click = (sel, text) =>
  js(`const el = [...document.querySelectorAll(${JSON.stringify(sel)})].find(e => e.textContent.includes(${JSON.stringify(text)})); if (!el) throw new Error("no " + ${JSON.stringify(text)}); el.click(); await new Promise(r => setTimeout(r, 1400));`);

// Home
await go("/"); await shot("home-hero");
await scrollTo("#how", "start", -20); await shot("home-how");
await scrollTo("#robust", "start", -20); await shot("home-robust");
await scrollTo("#team", "start", -20); await shot("home-team");

// The starting state: nothing has run yet (no stored view), then every saved result shown for the tour
await go("/app");
await js(`["sigil.shown", "sigil.shownModels", "sigil.clearedAt", "sigil.model"].forEach((k) => localStorage.removeItem(k));`);
await go("/app"); await shot("overview-empty");
await js(`localStorage.setItem("sigil.shown", JSON.stringify(["train","attacks","forgery","committed_seed","zk","zk_hashed","protocol_v2"]));`);
const MODELS = ["watermarked_v2","watermarked_v1","prune65","prune90","int8","finetune","permute","overwrite","clean","null_0","null_1","null_2","null_3"];
await js(`localStorage.setItem("sigil.shownModels", JSON.stringify(${JSON.stringify(MODELS)})); localStorage.setItem("sigil.model", "watermarked_v2");`);
const useModel = (id) => js(`localStorage.setItem("sigil.model", "${id}");`);
/** Scroll so the first `sel` whose text contains `text` is at the top. */
const scrollToText = (sel, text, dy = 0) =>
  js(`const el = [...document.querySelectorAll(${JSON.stringify(sel)})].find((e) => e.textContent.includes(${JSON.stringify(text)})); el.scrollIntoView({behavior: "instant", block: "start"}); window.scrollBy({top: ${dy}, behavior: "instant"}); await new Promise(r => setTimeout(r, 900));`);

// The model bar with a tested stolen copy
await useModel("prune90"); await go("/app"); await scrollTo(".modelbar", "start", -24); await shot("modelbar");
await js(`document.querySelector(".modelbar .dd-btn").click(); await new Promise(r => setTimeout(r, 500));`); await shot("modelbar-menu");
await useModel("watermarked_v2");

// Overview
await go("/app"); await shot("overview");
await scrollTo(".page .cols", "start", -24); await shot("overview-models");

// Embed
await go("/app/embed"); await scrollTo(".page h1", "start", -150); await shot("embed-v2");
await click(".segbar button", "v1"); await scrollTo(".page h1", "start", -150); await shot("embed-v1");

// Verify
await useModel("prune65"); await go("/app/verify"); await scrollTo(".modelbar", "start", -16); await shot("verify-model-proven");
await useModel("permute"); await go("/app/verify"); await scrollTo(".modelbar", "start", -16); await shot("verify-model-permuted");
await useModel("watermarked_v2");
await go("/app/verify"); await scrollToText(".page h2", "The recorded claim", -24); await shot("verify-ok");
await click(".segbar button", "On-chain"); await scrollToText(".page h2", "The recorded claim", -24); await shot("verify-onchain");
await click(".segbar button", "Off-chain");
// a misuse button re-runs the verifier (replayed in simulate mode): verdict above, every check in the console
await click(".page button", "tampered proof bytes"); await sleep(2600); await scrollToText(".page h2", "The recorded claim", -24); await shot("verify-rejected");
await click(".console button", "Hide console");
await scrollTo(".page .stp.fail", "center", 80); await shot("verify-checks-failed");

// Robustness
await go("/app/robustness"); await scrollToText(".page h2", "Attack the owner", -40); await shot("robustness-copies");
await js(`document.querySelectorAll(".page .statgrid")[1].scrollIntoView({behavior: "instant", block: "start"}); window.scrollBy({top: -60, behavior: "instant"}); await new Promise(r => setTimeout(r, 900));`);
await shot("robustness");
await scrollTo(".vbars", "center"); await sleep(1200); await shot("robustness-sweep");

// Research demos
for (const k of ["A", "B", "C", "D", "E", "F"]) { await go(`/app/demo/${k}`); await scrollTo(".page h1, .page h2", "start", -150); await shot(`demo-${k}`); }
await js(`window.scrollTo({top: document.documentElement.scrollHeight, behavior: "instant"}); await new Promise(r => setTimeout(r, 900));`); await shot("demo-F-dispute");

// Runs in the console (simulate mode replays recorded logs)
await go("/app/demo/F");
await click(".page button", "Run demo F");
await sleep(3000); await shot("console-finished");
await go("/app/demo/B");
await js(`[...document.querySelectorAll(".side button")].find(b => b.textContent.includes("Run all")).click(); await new Promise(r => setTimeout(r, 1100));`);
await shot("console-running");

ws.close();
edge.kill();
process.exit(0);
