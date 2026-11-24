import { expect, test } from '@playwright/test';

// 스마트폰 뷰포트(390×844) 전용 MobileShell 끝에서 끝까지 검증.
// 실행: bash scripts/e2e-local.sh e2e/mobile.spec.ts

const LOGIN_ID = process.env.E2E_LOGIN_ID ?? 'demo-admin';
const PASSWORD = process.env.E2E_PASSWORD ?? 'demo-pass-e2e';

test.use({ viewport: { width: 390, height: 844 }, actionTimeout: 15_000 });

test('mobile viewport renders MobileShell with 5 bottom tabs and full-screen programs', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('아이디').fill(LOGIN_ID);
  await page.getByLabel('비밀번호').fill(PASSWORD);
  await page.getByRole('button', { name: '들어가기' }).click();

  await expect(page.getByTestId('mobile-shell')).toBeVisible();
  const nav = page.getByRole('navigation', { name: '모바일 탐색' });
  await expect(nav).toBeVisible();

  // 대화 탭(기본)
  await expect(page.getByLabel('에이전트에게 요청')).toBeVisible();

  // 일정 탭 → 공정률 전환
  await nav.getByRole('button', { name: /일정/ }).click();
  await expect(page.getByRole('tablist', { name: '일정 보기 전환' })).toBeVisible();
  await page.getByRole('tab', { name: '공정률' }).click();

  // 승인 탭
  await nav.getByRole('button', { name: /승인/ }).click();

  // 연락처 탭(Task 105 — 자료함 자리)
  await nav.getByRole('button', { name: /연락처/ }).click();
  await expect(page.locator('.ct-root')).toBeVisible();

  // 전체 탭 → 개발 콘솔(관리자) 표시, 자료함은 여기 안에
  await nav.getByRole('button', { name: /전체/ }).click();
  await expect(page.getByRole('button', { name: '개발 콘솔' })).toBeVisible();
  await page.getByRole('button', { name: '자료함' }).click();
  await expect(page.getByRole('searchbox', { name: '자료 찾기' })).toBeVisible();
});

test('phone keeps the schedule tool ribbon to one row so gantt bars show, and the header and site list fit the screen (F3·F6)', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('아이디').fill(LOGIN_ID);
  await page.getByLabel('비밀번호').fill(PASSWORD);
  await page.getByRole('button', { name: '들어가기' }).click();
  await expect(page.getByTestId('mobile-shell')).toBeVisible();

  // 머리줄: 나가기가 화면 안, 제목이 한 글자로 잘리지 않음(16px 글자 3자 이상)
  const exit = (await page.getByRole('button', { name: '나가기' }).boundingBox())!;
  expect(exit.x + exit.width).toBeLessThanOrEqual(390);
  expect((await page.locator('.mob-title').boundingBox())!.width).toBeGreaterThanOrEqual(48);

  // 일정 고르기 목록이 화면 폭 안에 펼쳐진다
  await page.getByRole('button', { name: '일정 고르기' }).click();
  const pop = (await page.locator('.os-site-pop').boundingBox())!;
  expect(pop.x).toBeGreaterThanOrEqual(0);
  expect(pop.x + pop.width).toBeLessThanOrEqual(390);
  await page.getByRole('option', { name: /5층 사무동/ }).click();

  // 간트: 리본은 한 줄(옆으로 밀기), 첫 막대가 아래 탭바 위에 보인다
  await page.getByRole('navigation', { name: '모바일 탐색' }).getByRole('button', { name: /일정/ }).click();
  await page.getByRole('tab', { name: '간트' }).click();
  const firstBar = page.locator('.gt-rows .gantt-bar').first();
  await expect(firstBar).toBeVisible();
  const ribbon = (await page.getByRole('toolbar', { name: '간트 도구' }).boundingBox())!;
  expect(ribbon.height).toBeLessThan(200);
  const nav = (await page.getByRole('navigation', { name: '모바일 탐색' }).boundingBox())!;
  const first = (await firstBar.boundingBox())!;
  expect(first.y + first.height).toBeLessThanOrEqual(nav.y);
});
