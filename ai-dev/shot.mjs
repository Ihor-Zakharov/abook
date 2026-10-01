// Headless screenshots of the review app via Windows Chrome + CDP (node >= 22: global WebSocket).
// usage: node shot.mjs steps.json outdir
import { spawn } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';

const [,, stepsFile, outDir] = process.argv;
const steps = JSON.parse(readFileSync(stepsFile, 'utf8'));
mkdirSync(outDir, { recursive: true });
const PORT = 9333;
const chrome = spawn('/mnt/c/Program Files/Google/Chrome/Application/chrome.exe', [
  '--headless=new', `--remote-debugging-port=${PORT}`, '--user-data-dir=C:\\Users\\Ihor\\AppData\\Local\\Temp\\abook-cdp',
  '--no-first-run', '--no-default-browser-check', '--disable-gpu', '--hide-scrollbars', 'about:blank'], { stdio: 'ignore', cwd: '/mnt/c' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function j(url) { const c = new AbortController(); const t = setTimeout(() => c.abort(), 3000); try { const r = await fetch(url, { signal: c.signal }); return await r.json(); } finally { clearTimeout(t); } }
let targets = null;
for (let i = 0; i < 40 && !targets; i++) { try { targets = await j(`http://127.0.0.1:${PORT}/json/list`); } catch (e) { await sleep(500); } }
if (!targets) { console.error('no CDP'); chrome.kill(); process.exit(1); }
const page = targets.find(t => t.type === 'page');
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0; const pend = new Map();
ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } };
const send = (method, params = {}) => new Promise(res => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Page.enable'); await send('Runtime.enable');
for (const s of steps) {
  if (s.size) await send('Emulation.setDeviceMetricsOverride', { width: s.size[0], height: s.size[1], deviceScaleFactor: 1, mobile: s.size[0] < 700 });
  if (s.nav) { await send('Page.navigate', { url: s.nav }); await sleep(s.wait ?? 1500); }
  if (s.eval) { const r = await send('Runtime.evaluate', { expression: s.eval, awaitPromise: true, returnByValue: true }); if (r.result?.exceptionDetails) console.error('eval error', s.eval.slice(0, 80), JSON.stringify(r.result.exceptionDetails).slice(0, 300)); else if (r.result?.result?.value !== undefined) console.log('=>', JSON.stringify(r.result.result.value).slice(0, 300)); await sleep(s.wait ?? 600); }
  if (s.shot) {
    let clip;
    if (s.full) { const m = await send('Page.getLayoutMetrics'); const cs = m.result.cssContentSize || m.result.contentSize; clip = { x: 0, y: 0, width: s.size ? s.size[0] : cs.width, height: Math.min(cs.height, 6000), scale: 1 }; }
    const r = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: !!s.full, ...(clip ? { clip } : {}) });
    writeFileSync(`${outDir}/${s.shot}`, Buffer.from(r.result.data, 'base64')); console.log('shot', s.shot);
  }
}
ws.close(); chrome.kill(); await sleep(300); process.exit(0);
