import { expect, test, type Locator, type Page } from '@playwright/test';

// 개발 콘솔 — 관리 포인트(계획 5 Task 7) FHD 밝게·어둡게: 하네스 탭의 「관리 포인트 설정」 카드(실제 시험 서버 — 임시 DB)와
// 실행 추적 「관리 포인트」 단계(고르기 → 관리 포인트, 목록은 가짜 답 — 꼴은 backend/app/programs/devconsole/points_view 그대로).
// 실행: E2E_SHOTS_DIR=… bash scripts/e2e-local.sh e2e/devconsole-points.spec.ts (그 폴더에 t7-*.png). 일정·숫자는 가상.

const LOGIN_ID = process.env.E2E_LOGIN_ID ?? 'demo-admin';
const PASSWORD = process.env.E2E_PASSWORD ?? 'demo-pass-e2e';
const NOW = new Date('2026-11-24T17:12:00+09:00');

test.use({ actionTimeout: 15_000 });
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: 'ignoreErrors' }));

const search = (branch: string, label: string, calls: number, failed: number, cost_kind: string, per_1k: number | null) =>
  ({ branch, label, calls, failed, cost_kind, per_1k });
const STAGES = [
  {
    schedule_id: 1, schedule_name: '5층 사무동 신축', version: 8, what_if: false, trigger: { kind: 'version', from: 7, to: 8 },
    changed_at: '2026-11-24T08:05:00Z', finished_at: '2026-11-24T08:05:40Z',
    compute: { points: 8, new: 3, tightened: 0, removed: 1 }, risk_status: 'done',
    searches: [
      search('weather', '날씨 (기상청)', 1, 0, '기상청 — Liner 비용 없음', null),
      search('knowledge', '자재·환율 (Premium Data)', 3, 1, 'Search + Premium Data', 2),
      search('business', '업체 소식 (MCP search_business)', 2, 0, 'MCP', 2),
    ],
    skipped: 1, search_agent: { calls: 2, failed: 0, pending: 1, cost_kind: 'Search Agent', per_1k: 20 }, cost: 0.05,
  },
  {
    schedule_id: 1, schedule_name: '5층 사무동 신축', version: 8, what_if: true, trigger: { kind: 'delay', version: 8 },
    changed_at: '2026-11-24T08:10:00Z', finished_at: null, compute: { points: 6, new: 0, tightened: 0, removed: 2 }, risk_status: 'none',
    searches: [
      search('weather', '날씨 (기상청)', 0, 0, '기상청 — Liner 비용 없음', null),
      search('knowledge', '자재·환율 (Premium Data)', 0, 0, 'Search + Premium Data', 2),
      search('business', '업체 소식 (MCP search_business)', 0, 0, 'MCP', 2),
    ],
    skipped: 0, search_agent: { calls: 0, failed: 0, pending: 0, cost_kind: 'Search Agent', per_1k: 20 }, cost: 0,
  },
];

async function login(page: Page) {
  await page.clock.setFixedTime(NOW);
  await page.goto('/');
  await page.getByLabel('아이디').fill(LOGIN_ID);
  await page.getByLabel('비밀번호').fill(PASSWORD);
  await page.getByRole('button', { name: '들어가기' }).click();
  await expect(page.locator('.os-dock-btn').first()).toBeVisible();
}

async function setTheme(page: Page, theme: 'light' | 'dark') {
  const btn = page.getByRole('button', { name: theme === 'dark' ? '어두운 테마' : '밝은 테마' });
  if (await btn.count()) await btn.first().click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
}

async function shot(page: Page, name: string) {
  const dir = process.env.E2E_SHOTS_DIR || test.info().outputPath('shots');
  await page.mouse.move(5, 540);
  await page.evaluate(() => { // 칸에 글을 넣을 때 바깥 틀(넘침 숨김)이 밀린 것을 되돌린다 — 창 안 스크롤은 그대로
    for (const el of [document.documentElement, document.body, ...document.querySelectorAll<HTMLElement>('body *')]) {
      if (el.scrollTop && !el.closest('.dc-body')) el.scrollTop = 0;
    }
  });
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${dir}/t7-${name}.png` });
}

/** 넘침 없음: 문서가 옆으로 밀리지 않고, 새 칸(.dc-pt-*)이 잘린 채 넘치지 않는다. */
async function fits(page: Page) {
  const r = await page.evaluate(() => {
    const clipped = [...document.querySelectorAll<HTMLElement>('[class*="dc-pt-"], [class*="dc-pt-"] *')]
      .filter((e) => e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX !== 'visible')
      .map((e) => `${e.tagName}.${e.className} ${e.scrollWidth}>${e.clientWidth}`);
    return { doc: document.documentElement.scrollWidth, vw: window.innerWidth, clipped: clipped.slice(0, 5) };
  });
  expect(r.doc).toBeLessThanOrEqual(r.vw);
  expect(r.clipped).toEqual([]);
}

const win = (page: Page): Locator => page.locator('.os-win[aria-label^="개발 콘솔"]');

for (const theme of ['light', 'dark'] as const) {
  test(`dev console 관리 포인트 · fhd · ${theme}`, async ({ page }) => {
    await page.route(/\/api\/devconsole\/points-runs(\?.*)?$/, (route) => route.fulfill({ json: STAGES }));
    await login(page);
    await setTheme(page, theme);
    const w = win(page);
    await w.waitFor({ state: 'visible', timeout: 3000 }).catch(() => undefined); // 앞 시험에서 연 창은 다시 열린다
    if (!(await w.isVisible())) await page.locator('.os-dock-btn[aria-label="개발 콘솔"], .os-dock-btn[aria-label^="개발 콘솔,"]').click();
    await expect(w).toBeVisible();
    if ((await w.locator('.os-lt-max').getAttribute('title')) === '최대화') await w.locator('.os-lt-max').click();

    // 1. 하네스 탭 — 관리 포인트 설정(실제 서버 값)
    await w.getByRole('tab', { name: '하네스·차단 시험' }).click();
    const card = w.getByRole('region', { name: '관리 포인트 설정' });
    await expect(card.getByRole('spinbutton', { name: '크리티컬 직전으로 볼 여유' })).toHaveValue('3');
    await expect(card.getByRole('table', { name: '분야별 바깥 자료' }).getByRole('rowheader')).toHaveText(['건설', '제조·생산', '그 밖의 분야']);
    await w.locator('.dc-cat-wrap').evaluate((el) => { // 카드가 그 칸 맨 위에 오게(창 바깥은 움직이지 않는다)
      const c = el.querySelector('#dc-points-config') as HTMLElement;
      el.scrollTop += c.getBoundingClientRect().top - el.getBoundingClientRect().top - 12;
    });
    await fits(page);
    await shot(page, `settings-fhd-${theme}`);
    if (theme === 'light') { // 범위 밖 → 까닭 · 저장 막힘, 바른 값은 서버에 저장(임시 DB)
      const k = card.getByRole('spinbutton', { name: '크리티컬 직전으로 볼 여유' });
      await k.fill('11');
      await expect(card.getByRole('alert')).toHaveText('0~10 사이 정수로 넣어 주세요.');
      await expect(card.getByRole('button', { name: '관리 포인트 설정 저장' })).toBeDisabled();
      await shot(page, 'settings-invalid-fhd-light');
      await k.fill('3');
      await card.getByRole('checkbox', { name: '그 밖의 분야 환율' }).check();
      await card.getByRole('button', { name: '관리 포인트 설정 저장' }).click();
      await expect(card.getByRole('status')).toContainText('관리 포인트 설정을 저장했습니다.');
      await card.getByRole('checkbox', { name: '그 밖의 분야 환율' }).uncheck(); // 다음 시험을 위해 되돌린다
      await card.getByRole('button', { name: '관리 포인트 설정 저장' }).click();
      await expect(card.getByRole('status')).toContainText('관리 포인트 설정을 저장했습니다.');
    }

    // 2. 실행 추적 — 고르기 「관리 포인트」 → 단계
    await w.getByRole('tab', { name: '실행 추적' }).click();
    await w.locator('.dc-pick-btn').click();
    const dialog = w.getByRole('dialog', { name: '요청 고르기' });
    await dialog.getByRole('radio', { name: '관리 포인트' }).click();
    await expect(dialog.getByRole('button', { name: /5층 사무동 신축 · 버전 7 → 8/ })).toBeVisible();
    await shot(page, `trace-picker-fhd-${theme}`);
    await dialog.getByRole('button', { name: /5층 사무동 신축 · 버전 7 → 8/ }).click();
    const stage = w.getByRole('region', { name: '관리 포인트 — 5층 사무동 신축 · 버전 7 → 8' });
    await expect(stage).toContainText('겨냥 검색 6회');
    await expect(stage).toContainText('Search + Premium Data · $2/1K');
    await expect(stage).toContainText('Search Agent · $20/1K');
    await expect(stage).toContainText('어림 비용 $0.0500');
    await fits(page);
    await shot(page, `trace-stage-fhd-${theme}`);
  });
}
