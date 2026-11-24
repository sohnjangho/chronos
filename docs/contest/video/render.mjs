// HTML 조각을 1920×1080 PNG 로 그린다. 사용: node render.mjs jobs.json
// jobs.json = [{ "html": "<!doctype html>…", "out": "/abs/path.png", "transparent": true }]
// file:// 그림을 읽을 수 있게 HTML 을 out 옆 .html 로 써 두고 연다.
import { readFileSync, writeFileSync } from 'node:fs';
import { chromium } from '../../../frontend/node_modules/playwright/index.mjs';

const jobs = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
for (const j of jobs) {
  const h = j.out.replace(/\.png$/, '.html');
  writeFileSync(h, j.html);
  await p.goto('file://' + h, { waitUntil: 'load' });
  await p.waitForTimeout(60);
  await p.screenshot({ path: j.out, omitBackground: !!j.transparent });
}
await b.close();
console.log(`rendered ${jobs.length}`);
