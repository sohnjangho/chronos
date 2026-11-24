import { devices, expect, test, type Page } from '@playwright/test';

// 기기 화면 깨짐(a4cap findings 1~5): iPad Pro 11 가로 · iPhone 15 Pro 에서 글이 접히거나 칸이 자리보다 넓어지지 않는지.
// 씨앗 자료에 없는 것(답 속 표 · 긴 파일 이름 사진 카드)은 실제 화면 안에 같은 class 로 끼워 넣고 잰다.
// 실행: bash scripts/e2e-local.sh e2e/devices.spec.ts

const LOGIN_ID = process.env.E2E_LOGIN_ID ?? 'demo-admin';
const PASSWORD = process.env.E2E_PASSWORD ?? 'demo-pass-e2e';

/** 기기 흉내(화면·배율·터치·UA)만 쓴다. 브라우저는 설정대로 크로미움(describe 안에서 바꿀 수 없음). */
function device(name: string) {
  const rest: Partial<(typeof devices)[string]> = { ...devices[name] };
  delete rest.defaultBrowserType;
  return rest;
}

/** 대화 고르기 단추에 긴 대화 제목을 넣는다(촬영 자료의 「창호 제작이 업체 공장 사정으로 3일…」처럼). */
async function longPicker(page: Page, root: string) {
  await page.locator(`${root} .ch-picker .ch-ellipsis`).evaluate((e) => { e.textContent = '창호 제작이 업체 공장 사정으로 3일 늦어졌어. 커튼월 쪽 영향도 같이 봐 줘'; });
}

async function login(page: Page) {
  await page.goto('/');
  await page.getByLabel('아이디').fill(LOGIN_ID);
  await page.getByLabel('비밀번호').fill(PASSWORD);
  await page.getByRole('button', { name: '들어가기' }).click();
  await page.getByRole('button', { name: '일정 고르기' }).click();
  await page.getByRole('option', { name: /5층 사무동/ }).click();
}

/** 좁은 대화 칸 안에 넓은 표가 든 답을 끼워 넣고, 그 표의 상자를 돌려준다. */
async function wideTableIn(page: Page, root: string) {
  return page.evaluate((sel) => {
    const host = document.querySelector(`${sel} .ch-thread`) ?? document.querySelector(`${sel} .ch-main`);
    if (!host) throw new Error(`no chat in ${sel}`);
    const md = document.createElement('div');
    md.className = 'ch-md';
    md.innerHTML = `<table><thead><tr>${['안', '준공', '이득', '바꾸는 것', '부담', '위반'].map((h) => `<th>${h}</th>`).join('')}</tr></thead>`
      + `<tbody><tr>${['B · 압축·자원 추가 (scenario 3, 추천)', '2027-11-01', '6일', '골조 3개조 → 4개조, 천장 마감 15일 → 12일', '장비·인건비', '없음'].map((c) => `<td>${c}</td>`).join('')}</tr></tbody></table>`;
    host.appendChild(md);
    const t = md.querySelector('table')!;
    const tds = [...t.querySelectorAll('td')].map((d) => d.getBoundingClientRect());
    return { client: t.clientWidth, scroll: t.scrollWidth, host: md.clientWidth, minTd: Math.min(...tds.map((r) => r.width)), maxTdH: Math.max(...tds.map((r) => r.height)) };
  }, root);
}

test.describe('iPad Pro 11 가로', () => {
  test.use(device('iPad Pro 11 landscape'));

  test('chat header pills stay on one line (finding 1)', async ({ page }) => {
    await login(page);
    await expect(page.getByTestId('tablet-shell')).toBeVisible();
    await page.getByRole('button', { name: '대화', exact: true }).first().click();
    const pills = page.locator('.ch-head .ch-pill:not(.ch-model-btn)');
    await expect(pills).toHaveCount(2);
    // 대화 제목이 길면(예: 「창호 제작이 업체 공장 사정으로 3일 늦어졌어.」) 알약 자리가 줄어든다
    await page.locator('.ch-head .ch-title').evaluate((e) => { e.textContent = '창호 제작이 업체 공장 사정으로 3일 늦어졌어. 커튼월 쪽 영향도 같이 봐 줘'; });
    for (const h of await pills.evaluateAll((es) => es.map((e) => e.getBoundingClientRect().height))) expect(h).toBeLessThanOrEqual(30);
  });

  test('side AI panel keeps the model name readable and lets answer tables scroll sideways (finding 2)', async ({ page }) => {
    await login(page);
    await page.getByRole('button', { name: '현장 점검', exact: true }).first().click();
    const side = '.tab-root .ch-root.is-narrow';
    await expect(page.locator(side)).toBeVisible();
    await longPicker(page, side);
    const label = (await page.locator(`${side} .ch-model-btn .ch-ellipsis`).boundingBox())!;
    expect(label.width).toBeGreaterThanOrEqual(40);
    const t = await wideTableIn(page, side);
    expect(t.client).toBeLessThanOrEqual(t.host);
    expect(t.scroll).toBeGreaterThan(t.client); // 옆으로 민다
    expect(t.minTd).toBeGreaterThanOrEqual(80); // 칸마다 몇 글자씩 접히지 않는다
  });
});

test.describe('iPhone 15 Pro', () => {
  test.use(device('iPhone 15 Pro'));

  test('chat model button shows the model name (finding 5)', async ({ page }) => {
    await login(page);
    await expect(page.getByTestId('mobile-shell')).toBeVisible();
    await page.getByRole('navigation', { name: '모바일 탐색' }).getByRole('button', { name: /대화/ }).click();
    await longPicker(page, '.mob-root');
    const label = (await page.locator('.ch-bar .ch-model-btn .ch-ellipsis').boundingBox())!;
    expect(label.width).toBeGreaterThanOrEqual(40);
    const bar = (await page.locator('.ch-bar').boundingBox())!;
    const last = (await page.locator('.ch-bar > *').last().boundingBox())!;
    expect(last.x + last.width).toBeLessThanOrEqual(bar.x + bar.width);
  });

  test('schedule ribbon is one short row that scrolls and the empty relation panel folds so the table gets the space (finding 3)', async ({ page }) => {
    await login(page);
    await page.getByRole('navigation', { name: '모바일 탐색' }).getByRole('button', { name: /일정/ }).click();
    await page.getByRole('tab', { name: '스케줄' }).click();
    const bar = page.getByRole('toolbar', { name: '스케줄표 도구' });
    await expect(bar).toBeVisible();
    const b = (await bar.boundingBox())!;
    expect(b.height).toBeLessThanOrEqual(80);
    expect(await bar.evaluate((e) => getComputedStyle(e).overflowX)).toBe('auto');
    const rel = (await page.getByRole('region', { name: '관계' }).boundingBox())!;
    expect(rel.height).toBeLessThanOrEqual(48);
    const grid = (await page.locator('.sch-grid-wrap').boundingBox())!;
    expect(grid.height).toBeGreaterThanOrEqual(200);
  });

  test('field photo card fits its slot and the human-read switch stays on one line (finding 4)', async ({ page }) => {
    await login(page);
    await page.getByRole('navigation', { name: '모바일 탐색' }).getByRole('button', { name: /일정/ }).click();
    await page.getByRole('tab', { name: '현장 점검' }).click();
    await page.getByRole('tab', { name: /^사진 AI 판독/ }).click();
    const sw = page.locator('.pg-hr-switch button');
    await expect(sw).toHaveCount(2);
    for (const h of await sw.evaluateAll((es) => es.map((e) => e.getBoundingClientRect().height))) expect(h).toBeLessThanOrEqual(48);
    const card = await page.evaluate(() => {
      const host = document.querySelector('.pg-field-grid') ?? document.querySelector('.pg-scroll');
      if (!host) throw new Error('no field host');
      const a = document.createElement('article');
      a.className = 'pg-fcard';
      a.innerHTML = '<div class="pg-fcard-foot"><span class="pg-muted">P01_CVNWR_Rebar_getting_placed_479534119.jpg · 2027-06-30 09:12</span>'
        + '<span class="sch-gap"></span><button type="button" class="ui-btn ui-btn-primary">승인함 상신 · 증빙 확정</button></div>';
      host.appendChild(a);
      return { slot: host.clientWidth, card: a.getBoundingClientRect().width, scroll: a.scrollWidth, client: a.clientWidth };
    });
    expect(card.card).toBeLessThanOrEqual(card.slot);
    expect(card.scroll).toBeLessThanOrEqual(card.client + 2);
  });
});
