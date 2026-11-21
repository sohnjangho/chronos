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

  // 자료함 탭
  await nav.getByRole('button', { name: /자료함/ }).click();
  await expect(page.getByRole('searchbox', { name: '자료 찾기' })).toBeVisible();

  // 전체 탭 → 개발 콘솔(관리자) 표시
  await nav.getByRole('button', { name: /전체/ }).click();
  await expect(page.getByRole('button', { name: '개발 콘솔' })).toBeVisible();
});
