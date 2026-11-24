import { expect, test, type Page } from '@playwright/test';

// 다시 열면 그대로(계정별 · 화면 형태별): 무언가를 열고 새로 고쳐도 그대로 열려 있다.
// 실행: CHRONOS_OUTREACH_WORKER=off bash scripts/e2e-local.sh e2e/restore.spec.ts

const LOGIN_ID = process.env.E2E_LOGIN_ID ?? 'demo-admin';
const PASSWORD = process.env.E2E_PASSWORD ?? 'demo-pass-e2e';

async function login(page: Page) {
  await page.goto('/');
  await page.getByLabel('아이디').fill(LOGIN_ID);
  await page.getByLabel('비밀번호').fill(PASSWORD);
  await page.getByRole('button', { name: '들어가기' }).click();
}

/** 그 프로그램이 든 모양을 서버에 쓸 때(바뀐 뒤 1초)까지 기다린다. 누르기 전에 건다. */
const saved = (page: Page, mode: string, program: string) =>
  page.waitForResponse(
    (r) => r.url().endsWith(`/api/me/ui-state/${mode}`) && r.request().method() === 'PUT' && r.ok() && (r.request().postData() ?? '').includes(`"${program}"`),
  );

test.describe('desktop 1920×1080', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('an open window stays open after a reload', async ({ page }) => {
    await login(page);
    const save = saved(page, 'desktop', 'gantt');
    await page.locator('.os-dock-btn[aria-label="간트차트"], .os-dock-btn[aria-label^="간트차트,"]').click();
    const gantt = page.locator('.os-win[aria-label^="간트차트"]');
    await expect(gantt).toBeVisible();
    await save; // 여는 움직임이 끝난 뒤 자리를 잰다
    const before = (await gantt.boundingBox())!;
    await page.reload();
    await expect(gantt).toBeVisible();
    const after = (await gantt.boundingBox())!;
    expect(Math.round(after.x)).toBe(Math.round(before.x));
    expect(Math.round(after.width)).toBe(Math.round(before.width));
  });
});

test.describe('tablet 1180×820', () => {
  test.use({ viewport: { width: 1180, height: 820 } });

  test('the open program stays open after a reload', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('chronos.deviceMode', JSON.stringify('tablet')));
    await login(page);
    await expect(page.getByTestId('tablet-shell')).toBeVisible();
    const rail = page.getByRole('navigation', { name: '태블릿 탐색' });
    const save = saved(page, 'tablet', 'contacts');
    await rail.getByRole('button', { name: /연락처/ }).click();
    await expect(rail.getByRole('button', { name: /연락처/ })).toHaveAttribute('aria-current', 'page');
    await save;
    await page.reload();
    await expect(page.getByTestId('tablet-shell')).toBeVisible();
    await expect(rail.getByRole('button', { name: /연락처/ })).toHaveAttribute('aria-current', 'page');
  });
});

test.describe('phone 390×844', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('the bottom tab stays after a reload (and it first continues from the tablet)', async ({ page }) => {
    await login(page);
    await expect(page.getByTestId('mobile-shell')).toBeVisible();
    const nav = page.getByRole('navigation', { name: '모바일 탐색' });
    // 같은 계정이 바로 앞 시험(태블릿)에서 연락처를 열었다 — 더 새것이라 스마트폰도 연락처로 이어 연다.
    await expect(nav.getByRole('button', { name: /연락처/ })).toHaveAttribute('aria-current', 'page');
    await expect(page.locator('.ct-root')).toBeVisible();
    const save = saved(page, 'phone', 'approvals');
    await nav.getByRole('button', { name: /승인/ }).click();
    await expect(nav.getByRole('button', { name: /승인/ })).toHaveAttribute('aria-current', 'page');
    await save;
    await page.reload();
    await expect(page.getByTestId('mobile-shell')).toBeVisible();
    await expect(nav.getByRole('button', { name: /승인/ })).toHaveAttribute('aria-current', 'page');
  });
});
