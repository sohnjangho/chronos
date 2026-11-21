import { expect, test, type Locator, type Page } from '@playwright/test';

// 계획 3 화면 끝에서 끝까지: 로그인 → 대화 파일 첨부·보내기·모델 ▾ → 자료함(찾기·상세·축 고치기) → 설정(임베딩·정보 API).
// 실행: bash scripts/e2e-local.sh e2e/plan3.spec.ts

const LOGIN_ID = process.env.E2E_LOGIN_ID ?? 'demo-admin';
const PASSWORD = process.env.E2E_PASSWORD ?? 'demo-pass-e2e';
const NOW = new Date('2026-11-20T09:00:00+09:00');

test.use({ actionTimeout: 15_000 });

const win = (page: Page, title: string): Locator => page.locator(`.os-win[aria-label^="${title}"]`);
const dock = (page: Page, name: string): Locator => page.locator(`.os-dock-btn[aria-label="${name}"], .os-dock-btn[aria-label^="${name},"]`);

async function login(page: Page) {
  await page.clock.setFixedTime(NOW);
  await page.goto('/');
  await page.getByLabel('아이디').fill(LOGIN_ID);
  await page.getByLabel('비밀번호').fill(PASSWORD);
  await page.getByRole('button', { name: '들어가기' }).click();
  await expect(dock(page, '자료함')).toBeVisible();
}

test('plan 3: chat attach, model picker, library search & axes edit, settings embedding/info', async ({ page }) => {
  await login(page);

  // 1. 에이전트 대화에서 파일 붙이기 + 보내기 + 모델 ▾ 확인
  await dock(page, '에이전트 대화').click();
  const chatWin = win(page, '에이전트 대화');
  await expect(chatWin).toBeVisible();

  const buf = (globalThis as unknown as { Buffer: { from(s: string, enc: string): unknown } }).Buffer.from(
    '동절기 콘크리트 타설 기준: 4도 이하 한중 양생 적용.\n',
    'utf-8',
  );
  await chatWin.getByLabel('파일 선택').setInputFiles({
    name: '동절기_시방서.txt',
    mimeType: 'text/plain',
    buffer: buf as unknown as never,
  });
  await expect(chatWin.getByText('동절기_시방서.txt')).toBeVisible();
  await expect(chatWin.getByRole('button', { name: '보내기' })).toBeEnabled();
  await chatWin.getByRole('button', { name: '보내기' }).click();
  await expect(chatWin.getByText('붙인 파일을 봐 주세요.')).toBeVisible();

  // 모델 ▾ 열기
  await chatWin.getByRole('button', { name: /대화 모델 고르기/ }).click();
  await expect(chatWin.getByRole('dialog', { name: '대화 모델 고르기' })).toBeVisible();
  await page.keyboard.press('Escape');

  // 2. 자료함 열기 → 찾기 → 미리 보기 → 축 고치기
  await dock(page, '자료함').click();
  const libWin = win(page, '자료함');
  await expect(libWin).toBeVisible();
  await expect(libWin.getByRole('option', { name: /동절기_시방서\.txt/ })).toBeVisible();

  await libWin.getByRole('searchbox', { name: '자료 찾기' }).fill('한중 양생');
  await libWin.getByRole('button', { name: '찾기' }).click();
  await expect(libWin.getByRole('option', { name: /동절기_시방서\.txt/ })).toBeVisible();

  const detail = libWin.getByRole('region', { name: '자료 상세' });
  await expect(detail.getByText(/한중 양생/)).toBeVisible();

  const axisInput = detail.getByLabel('종류 값 추가');
  await axisInput.fill('시방서');
  await axisInput.press('Enter');
  await expect(detail.getByText('시방서')).toBeVisible();

  // 자료함 → [대화에 붙이기] 연동 확인
  await detail.getByRole('button', { name: '대화에 붙이기' }).click();
  await expect(chatWin.getByRole('region', { name: '붙인 파일' }).getByText('동절기_시방서.txt')).toBeVisible();

  // 3. 설정 → 임베딩 줄 & 정보 API 연결 구역 확인
  await dock(page, '설정').click();
  const setWin = win(page, '설정');
  await expect(setWin).toBeVisible();
  await setWin.getByRole('button', { name: '작업별 모델 배정' }).click();
  await expect(setWin.getByRole('group', { name: '임베딩' })).toBeVisible();
  await expect(setWin.getByRole('group', { name: '그림 읽기' })).toBeVisible();
});
