import { expect, test, type Locator, type Page } from '@playwright/test';

// 화면 끝에서 끝까지(1920×1080): 로그인 → Dock 에서 간트차트 → 막대와 크리티컬 색 → 조건·규칙에서 크레인 2 →
// 미리 보기 문구와 간트 점선 막대 → 되돌리기 → 대화창에서 생성 요청 → 질문지 열림.
// 자료: 씨앗 일정 「5층 사무동 신축」(python -m app.seed demo), LLM: 서버의 CHRONOS_FAKE_LLM=1(가짜 Liner).
// 단계 화면은 E2E_SHOTS_DIR 에 저장한다. 없으면 이 시험의 결과 폴더(임시) — 커밋한 docs/demo/shots/ 는
// E2E_SHOTS_DIR 로 그 폴더를 줄 때만 바뀐다. 실행은 bash scripts/e2e-local.sh.

const LOGIN_ID = process.env.E2E_LOGIN_ID ?? 'demo-admin';
const PASSWORD = process.env.E2E_PASSWORD ?? 'demo-pass-e2e';
const SCHEDULE = '5층 사무동 신축';
const REQUEST = '5층 사무동 공정표 만들어 줘. 착공은 2027년 3월 2일이야.';
// 화면 시계를 고정한다(메뉴바 시각이 매번 같게). 대회 기간의 한 날 — 씨앗 일정(2027) 앞이라 간트에 「오늘」 선이
// 들어오지 않는다(Data Date 선과 겹치지 않게).
const NOW = new Date('2026-11-20T09:00:00+09:00');

async function shot(page: Page, name: string) {
  const dir = process.env.E2E_SHOTS_DIR || test.info().outputPath('shots');
  await page.screenshot({ path: `${dir}/${name}.png` });
}

const win = (page: Page, title: string): Locator => page.locator(`.os-win[aria-label^="${title}"]`);
const dock = (page: Page, name: string): Locator => page.locator(`.os-dock-btn[aria-label="${name}"], .os-dock-btn[aria-label^="${name},"]`);

/** 간트 몸통을 위에서부터 내려 조건에 맞는 것이 몸통 위쪽에 보이게 한다(줄은 보이는 것만 그리고, 옮길 때마다 다시 그린다). */
async function scrollUntil(gantt: Locator, found: Locator) {
  const page = gantt.page();
  const body = gantt.locator('.gt-body');
  const settle = () => page.waitForTimeout(300);
  await body.evaluate((el) => el.scrollTo({ top: 0 }));
  await settle();
  for (let i = 0; i < 30 && (await found.count()) === 0; i++) {
    await body.evaluate((el) => el.scrollBy({ top: 240 }));
    await settle();
  }
  await expect(async () => {
    const y = await found.first().evaluate((el) => {
      const box = el.closest('.gt-body')!;
      return el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
    });
    await body.evaluate((el, top) => el.scrollTo({ top: Math.max(0, top - 120) }), y);
    await settle();
    await expect(found.first()).toBeInViewport({ timeout: 1000 });
  }).toPass({ timeout: 15_000 });
}

async function login(page: Page) {
  await page.clock.setFixedTime(NOW);
  await page.goto('/');
  await page.getByLabel('아이디').fill(LOGIN_ID);
  await page.getByLabel('비밀번호').fill(PASSWORD);
  await shot(page, '01-로그인');
  await page.getByRole('button', { name: '들어가기' }).click();
  await expect(dock(page, '간트차트')).toBeVisible();
  await shot(page, '02-바탕화면');
}

async function pickSchedule(page: Page) {
  await page.getByRole('button', { name: '일정 고르기' }).click();
  await page.getByRole('combobox', { name: '일정 찾기' }).fill('5층');
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', { name: new RegExp(SCHEDULE) }).first()).toBeVisible();
}

async function openGantt(page: Page): Promise<Locator> {
  await dock(page, '간트차트').click();
  const gantt = win(page, '간트차트');
  await expect(gantt.getByText('메뉴바에서 일정을 고르세요.')).toBeVisible();
  await pickSchedule(page);
  await expect(gantt).toHaveAttribute('aria-label', `간트차트 — ${SCHEDULE}`);
  await expect(gantt.locator('[data-bar]').first()).toBeVisible();
  await expect(gantt.getByRole('button', { name: 'CPM' })).toHaveAttribute('aria-pressed', 'true');
  await scrollUntil(gantt, gantt.locator('.gantt-forecast.critical'));
  await shot(page, '03-간트-크리티컬');
  return gantt;
}

async function previewTwoCranes(page: Page, gantt: Locator): Promise<Locator> {
  await dock(page, '조건·규칙').click();
  const conds = win(page, '조건·규칙');
  const crane = conds.getByLabel('타워크레인 수량');
  await expect(crane).toHaveValue('1');
  await crane.fill('2');
  await expect(conds.getByText('1대 → 2대 미리 보기')).toBeVisible();
  await expect(conds.getByText(/준공 .+ → .+ · 위반 0/)).toBeVisible();
  await shot(page, '04-조건-크레인2-미리보기');

  await gantt.locator('.os-win-title').click(); // 간트 창을 앞으로
  await expect(gantt.getByText(/미리 보기 중/).first()).toBeVisible();
  await scrollUntil(gantt, gantt.locator('.gantt-ghost'));
  await shot(page, '05-간트-점선-미리보기');
  return conds;
}

async function revert(page: Page, gantt: Locator, conds: Locator) {
  await dock(page, '조건·규칙').click();
  await conds.getByRole('button', { name: '되돌리기' }).click();
  await expect(conds.getByLabel('타워크레인 수량')).toHaveValue('1');
  await expect(conds.getByText(/준공 .+ → .+ · 위반/)).toHaveCount(0);
  await expect(gantt.locator('.gantt-ghost')).toHaveCount(0);
  await shot(page, '06-되돌리기');
  await conds.getByRole('button', { name: '닫기' }).click();
  await gantt.getByRole('button', { name: '닫기' }).click();
}

async function askAgent(page: Page) {
  await dock(page, '에이전트 대화').click();
  const chat = win(page, '에이전트 대화');
  await chat.getByLabel('에이전트에게 요청').fill(REQUEST);
  await chat.getByRole('button', { name: '보내기' }).click();
  await expect(chat.getByText(REQUEST)).toBeVisible();
  const form = win(page, '질문지');
  await expect(form).toBeVisible();
  await expect(form.getByRole('heading', { name: '건물의 구조 형식은 무엇인가요?' })).toBeVisible();
  await expect(form.getByText('질문 3개 중 0개 답함')).toBeVisible();
  await shot(page, '07-대화-질문지');
}

test('씨앗 일정으로 간트·조건 미리 보기·되돌리기, 대화로 질문지 열기', async ({ page }) => {
  await login(page);
  const gantt = await openGantt(page);
  const conds = await previewTwoCranes(page, gantt);
  await revert(page, gantt, conds);
  await askAgent(page);
});
