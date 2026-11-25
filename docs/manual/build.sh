#!/usr/bin/env bash
# docs/manual/manual.html → ChronOS_설치_사용설명서.pdf (A4). frontend 의 Playwright(Chromium)를 쓴다.
# 준비: (cd frontend && npm ci && npx playwright install chromium)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(git -C "$here" rev-parse --show-toplevel)"
export MANUAL_DIR="$here"
export PW_MODULE="$root/frontend/node_modules/playwright/index.mjs"
node --input-type=module <<'JS'
import { pathToFileURL } from 'node:url';
import { statSync } from 'node:fs';
const { chromium } = await import(pathToFileURL(process.env.PW_MODULE).href);
const dir = process.env.MANUAL_DIR;
const out = `${dir}/ChronOS_설치_사용설명서.pdf`;
const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  await page.goto(pathToFileURL(`${dir}/manual.html`).href, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  await page.pdf({
    path: out, format: 'A4', printBackground: true, preferCSSPageSize: true,
    displayHeaderFooter: true,
    headerTemplate: '<div></div>',
    footerTemplate: '<div style="width:100%;font-size:8px;color:#8a94a3;padding:0 15mm;display:flex;justify-content:space-between;font-family:Apple SD Gothic Neo,sans-serif"><span>ChronOS 설치·초기 설정 사용설명서</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>',
  });
  console.log(`${out} (${Math.round(statSync(out).size / 1024)} KB)`);
} finally {
  await browser.close();
}
JS
