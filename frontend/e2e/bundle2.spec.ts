import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';

// 묶음 2 화면 끝에서 끝까지(1920×1080): 로그인 → 스케줄(사무동)에서 지상 골조 고르기 → 대화에서 지연 말하기 → 대화 카드·
// 지연 기록 창 → 공정률 S-커브(승인 전) → [만회 계획 요청] → 만회안 카드 → 비교판(같은 차트·요약 표) → [이 안을 반영] →
// 승인함 승인 → CPM 요약 줄(만회 계획 달성률) → 개발 콘솔 구조 → 생산 일정 간트(자원 묶음·「프레스 작업 금지」 띠).
// 자료: 씨앗 두 일정(python -m app.seed demo), LLM: 서버의 CHRONOS_FAKE_LLM=1(app.llm.fake 의 묶음 2 대본).
// 서버 시험 backend/tests/e2e/test_bundle2_flow.py 와 같은 대본이다. [보고서용 그림]은 누르지 않는다(가짜 시각화 없음).
// 단계 화면은 E2E_SHOTS_DIR 에 b2-<번호>-<이름>.png 로(없으면 이 시험의 결과 폴더). 실행은 bash scripts/e2e-local.sh.

const LOGIN_ID = process.env.E2E_LOGIN_ID ?? 'demo-admin';
const PASSWORD = process.env.E2E_PASSWORD ?? 'demo-pass-e2e';
const OFFICE = '5층 사무동 신축';
const FACTORY = '가상 부품 공장 — 브래킷 BR-200 2만 개';
const FRAME = 'A1210'; // 1층 철근 배근 — 지상 골조의 첫 작업
const DELAY_TEXT = '지상 골조가 비 때문에 3일 늦어졌어';
const NOW = new Date('2026-11-20T09:00:00+09:00'); // demo.spec 과 같은 고정 시계

test.use({ actionTimeout: 15_000 }); // 가려진 단추를 누르려다 시험 시간을 다 쓰지 않게

async function shot(page: Page, name: string) {
  const dir = process.env.E2E_SHOTS_DIR || test.info().outputPath('shots');
  await page.mouse.move(1880, 520); // Dock 확대·이름표가 화면에 남지 않게 빈 바탕으로
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${dir}/b2-${name}.png` });
}

const win = (page: Page, title: string): Locator => page.locator(`.os-win[aria-label^="${title}"]`);
const dock = (page: Page, name: string): Locator => page.locator(`.os-dock-btn[aria-label="${name}"], .os-dock-btn[aria-label^="${name},"]`);

/** 메뉴바 윈도우 ▸ 모두 닫기(다음 장면을 깨끗한 바탕화면에서). */
async function closeAll(page: Page) {
  await page.getByRole('banner').getByRole('button', { name: '윈도우', exact: true }).click();
  await page.getByRole('menuitem', { name: /^모두 닫기/ }).click();
  await expect(page.locator('.os-win')).toHaveCount(0);
}

async function login(page: Page) {
  await page.clock.setFixedTime(NOW);
  await page.goto('/');
  await page.getByLabel('아이디').fill(LOGIN_ID);
  await page.getByLabel('비밀번호').fill(PASSWORD);
  await page.getByRole('button', { name: '들어가기' }).click();
  await expect(dock(page, '스케줄')).toBeVisible();
}

async function pickSchedule(page: Page, query: string, name: string) {
  await page.locator('.os-site-btn').click(); // 메뉴바 일정 고르기(이름은 지금 일정)
  await page.getByRole('combobox', { name: '일정 찾기' }).fill(query);
  await expect(page.getByRole('option', { name: new RegExp(query) })).toHaveCount(1); // 목록이 읽힌 뒤 Enter
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', { name: `${name} · L3` })).toBeVisible(); // 메뉴바의 지금 일정
}

async function pickFrame(page: Page) {
  await pickSchedule(page, '5층', OFFICE);
  await dock(page, '스케줄').click();
  const table = win(page, '스케줄');
  await expect(table).toHaveAttribute('aria-label', `스케줄 — ${OFFICE}`);
  const row = table.locator(`tr.sch-row[data-key="${FRAME}"]`);
  await row.click();
  await expect(row).toHaveAttribute('aria-current', 'true');
  await shot(page, '01-스케줄-골조-고름');
}

async function sayDelay(page: Page): Promise<Locator> {
  await dock(page, '에이전트 대화').click();
  const chat = win(page, '에이전트 대화');
  await expect(chat.getByText(`스케줄 · ${FRAME}`).first()).toBeVisible(); // 보낼 화면 맥락: 고른 액티비티
  await chat.getByLabel('에이전트에게 요청').fill(DELAY_TEXT);
  await chat.getByRole('button', { name: '보내기' }).click();
  const card = chat.getByRole('region', { name: '지연 영향' });
  await expect(card).toBeVisible();
  await expect(card.getByText(`${FRAME} 1층 철근 배근 · 3일 지연`)).toBeVisible();
  const delays = win(page, '지연 기록');
  await expect(delays).toHaveAttribute('aria-label', `지연 기록 — ${OFFICE}`);
  await expect(delays.getByText('1층 철근 배근').first()).toBeVisible();
  await chat.locator('.os-win-title').click(); // 대화 창을 앞으로(카드가 보이게)
  await shot(page, '02-대화-지연영향');
  await delays.locator('.os-win-title').click();
  await shot(page, '03-지연기록');
  return chat;
}

/** 지연을 기록한 직후(승인 전) 공정률: S-커브와 「지연 영향 반영」 선. 본 뒤 그 창만 닫는다. */
async function progressAfterDelay(page: Page) {
  await dock(page, '공정률').click();
  const progress = win(page, '공정률');
  await expect(progress).toHaveAttribute('aria-label', `공정률 — ${OFFICE}`);
  await expect(progress.getByRole('region', { name: 'S-커브' })).toBeVisible();
  await shot(page, '04-공정률-지연뒤');
  await progress.getByRole('button', { name: '닫기', exact: true }).click();
  await expect(progress).toHaveCount(0);
}

async function askRecovery(page: Page, chat: Locator): Promise<Locator> {
  await chat.locator('.os-win-title').click();
  await chat.getByRole('region', { name: '지연 영향' }).getByRole('button', { name: '만회 계획 요청' }).click();
  const options = chat.getByRole('region', { name: '만회안' });
  await expect(options).toBeVisible({ timeout: 30_000 });
  await expect(options.locator('.ch-option').first()).toBeVisible();
  await expect(options.locator('.ch-option.is-pick')).toHaveCount(1); // 추천 하나
  const compare = win(page, '비교판');
  await expect(compare).toBeVisible();
  await chat.locator('.os-win-title').click();
  await shot(page, '05-대화-만회안');
  return compare;
}

async function submitRecovery(page: Page, compare: Locator) {
  await compare.locator('.os-win-title').click();
  await expect(compare.getByRole('region', { name: '같은 차트' })).toBeVisible();
  await expect(compare.getByRole('table', { name: '여러 안 요약' })).toBeVisible();
  await expect(compare.getByRole('button', { name: '같은 차트' })).toHaveAttribute('aria-pressed', 'true');
  await shot(page, '06-비교판');
  await compare.getByRole('button', { name: '이 안을 반영 (승인함으로)' }).click();
  const dialog = page.getByRole('dialog', { name: '이 안을 반영' });
  await dialog.getByRole('button', { name: '보내기' }).click();
  const approvals = win(page, '승인함');
  await expect(approvals).toBeVisible();
  await expect(approvals).toHaveClass(/is-active/); // 보내면 승인함이 비교판 앞에 열린다
  const approve = approvals.getByRole('button', { name: '승인하고 반영' });
  await expect(approve).toBeVisible();
  await shot(page, '07-승인함');
  await approve.click();
  await expect(approve).toHaveCount(0);
}

/** 승인 뒤 CPM 요약 줄: 만회 계획 달성률. */
async function cpmAfterApproval(page: Page) {
  await closeAll(page);
  await dock(page, 'CPM').click();
  const cpm = win(page, 'CPM');
  await expect(cpm).toHaveAttribute('aria-label', `CPM — ${OFFICE}`);
  await expect(cpm.getByText('만회 계획 달성률')).toBeVisible();
  await shot(page, '08-CPM-요약');
  await closeAll(page);
}

async function devConsole(page: Page) {
  await dock(page, '개발 콘솔').click();
  const dev = win(page, '개발 콘솔');
  await dev.locator('.dc-pick-btn').click();
  await dev.getByRole('dialog', { name: '요청 고르기' }).getByRole('button', { name: /지상 골조/ }).click();
  await expect(dev.locator('.dc-pick-btn')).toContainText('지상 골조');
  const structure = dev.getByRole('group', { name: '에이전트 구조' });
  await expect(structure).toBeVisible();
  await expect(structure.getByRole('button', { name: /^도구 실행, / })).toBeVisible();
  await shot(page, '09-개발콘솔-구조');
  await closeAll(page);
}

async function factoryGantt(page: Page) {
  await pickSchedule(page, '부품', FACTORY);
  await dock(page, '간트차트').click();
  const gantt = win(page, '간트차트');
  await expect(gantt).toHaveAttribute('aria-label', `간트차트 — ${FACTORY}`);
  await expect(gantt.locator('[data-bar]').first()).toBeVisible();
  await expect(gantt.getByText('프레스 작업 금지').first()).toBeAttached();
  await expect(gantt.getByRole('button', { name: '프레스 라인' })).toBeAttached(); // 자원 묶음 줄
  await shot(page, '10-생산간트-자원묶음');
}

/** 같은 서버에서 demo.spec 이 이어 돌 수 있게 사무동 일정을 씨앗의 버전 2(실적 입력)로 되돌린다. 바뀌지 않았으면(버전 2) 그대로. */
async function restoreOffice(request: APIRequestContext) {
  const login = await request.post('/api/auth/login', { data: { login_id: LOGIN_ID, password: PASSWORD } });
  const headers = { Authorization: `Bearer ${(await login.json()).token}` };
  const list: { id: number; name: string; version: number }[] = await (await request.get('/api/schedules', { headers })).json();
  const office = list.find((s) => s.name === OFFICE)!;
  if (office.version <= 2) return;
  const restored = await request.post(`/api/schedules/${office.id}/versions/2/restore`, { headers, data: { base_version: office.version } });
  expect(restored.ok()).toBe(true);
}

test('지연 → 영향 → 만회안 → 승인, CPM·공정률·개발 콘솔, 생산 간트', async ({ page, request }) => {
  try {
    await login(page);
    await pickFrame(page);
    const chat = await sayDelay(page);
    await progressAfterDelay(page);
    const compare = await askRecovery(page, chat);
    await submitRecovery(page, compare);
    await cpmAfterApproval(page);
    await devConsole(page);
    await factoryGantt(page);
  } finally {
    await restoreOffice(request); // 중간에 실패해도 다음 시험(demo.spec)이 씨앗 그대로에서 돈다
  }
});
