import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

// 연락처 — 태블릿·스마트폰 화면(Task 105). 폰 390×844: 아래 탭 「연락처」 → 목록 → 대화 한 화면씩(「‹ 이름」 으로 돌아감),
// 입력창은 아래 탭 바로 위에 붙고 넘치지 않음, 통화 카드는 요약이 먼저. 태블릿 1180×820: PC 와 같은 두 칸. 820×1180: 고른 뒤
// 주소록이 접히고 [주소록]으로 펼침. 두 테마 모두 넘침 없음 · 전체 번호 없음.
// 후속: 폰 입력창이 낮아 대화가 360px 이상 보임 · 통화 카드 DOM 차례가 요약 → 목적 · 긴급 보고 토스트가 폰·태블릿 머리 아래에 뜨고
// 아래 탭·입력창을 가리지 않음(긴급 보고 읽기도 가상 줄).
// 자료: 씨앗 일정(python -m app.seed demo) + 이 시험이 API 로 넣는 가상 협력사·사람(번호는 010-0000-01xx 꼴). 대화·통화 목록은
// 알림 연결 없이 만들 수 없어 그 두 읽기만 가상 줄로 바꿔 답한다(주소록·사람·로그인·일정은 실제 서버).
// 실행: bash scripts/e2e-local.sh e2e/contacts-mobile.spec.ts (서버에 CHRONOS_OUTREACH_WORKER=off). 화면은 E2E_SHOTS_DIR 에.

const LOGIN_ID = process.env.E2E_LOGIN_ID ?? 'demo-admin';
const PASSWORD = process.env.E2E_PASSWORD ?? 'demo-pass-e2e';
const OFFICE = '5층 사무동 신축';
const COMPANY = '가상골조';
const FULL_NUMBER = /(?:\+82|0)1\d[-. ]?\d{3,4}[-. ]?\d{4}/;
const IPAD_UA = 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';
const THEMES = ['light', 'dark'] as const;

test.use({ actionTimeout: 15_000 });
// 대화 읽기를 가로채는 중에 시험이 끝나면 그 읽기는 버린다.
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: 'ignoreErrors' }));

async function seedBook(request: APIRequestContext) {
  const login = await request.post('/api/auth/login', { data: { login_id: LOGIN_ID, password: PASSWORD } });
  const headers = { Authorization: `Bearer ${(await login.json()).token}` };
  const list: { id: number; name: string }[] = await (await request.get('/api/schedules', { headers })).json();
  const sid = list.find((s) => s.name === OFFICE)!.id;
  const book: { companies: { name: string }[] } = await (await request.get(`/api/schedules/${sid}/contacts`, { headers })).json();
  if (book.companies.some((c) => c.name === COMPANY)) return;
  const co = await request.post(`/api/schedules/${sid}/contacts/companies`, { headers, data: { name: COMPANY, trade: '골조' } });
  expect(co.ok()).toBe(true);
  const companyId = (await co.json()).id as number;
  for (const [name, role, phone] of [
    ['박가상', '골조 팀장', '010-0000-0101'],
    ['이가상', '골조 반장', '010-0000-0102'],
    ['아주아주긴이름을가진가상의현장담당자', '전기·통신·소방 설비 총괄 현장 대리인 겸 안전 관리 책임자', null],
  ] as const) {
    const p = await request.post(`/api/schedules/${sid}/contacts/people`, { headers, data: { name, role_title: role, company_id: companyId, phone } });
    expect(p.ok(), await p.text()).toBe(true);
  }
}

/** 대화(30줄)와 통화(요약 있는 것 · 받지 않음) 읽기를 가상 줄로. 사람 칸(contact)은 실제 서버의 답 그대로. */
async function fakeThreadAndCalls(page: Page) {
  await page.route(/\/api\/schedules\/\d+\/outreach\/threads\/\d+(\?.*)?$/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    const messages = Array.from({ length: 30 }, (_, i) => ({
      id: 9000 + i, direction: i % 3 === 0 ? 'in' : 'out', channel: 'sms', kind: 'normal',
      body: i % 3 === 0 ? `가상 회신 ${i + 1} — 내일 오전 반입 가능합니다.` : `가상 문자 ${i + 1} — A1210 철근 반입 시간을 알려 주세요. 길게 이어지는 글이 줄을 바꾸는지 봅니다.`,
      body_ko: null, has_media: false, origin: i % 3 === 0 ? 'peer' : 'user', origin_name: i % 3 === 0 ? '박가상' : '김공정',
      send_mode: i % 3 === 0 ? null : 'manual', approved_by: null, status: i % 3 === 0 ? 'received' : 'delivered', fail_reason: null,
      fallback_sms: false, template_id: null, reply_to_id: null, activity: null, field_item_id: null, approval_id: null, chat: null,
      batch: null, events: [], scheduled_at: null, sent_at: null, delivered_at: null,
      created_at: new Date(Date.UTC(2026, 10, 20 + Math.floor(i / 10), 1 + (i % 10))).toISOString(),
    }));
    await route.fulfill({ json: { ...body, contact: { ...body.contact, unread: 0 }, messages, has_more: false } });
  });
  const call = (over: Record<string, unknown>) => ({
    id: 1, direction: 'out', caller_class: 'outbound', contact: { id: 1, name: '박가상', role_title: '골조 팀장', company: COMPANY },
    origin: 'agent', origin_name: '에이전트', send_mode: 'approved', approved_by: '김공정', status: 'completed', fail_reason: null,
    purpose: 'A1210 만회안 B(주말 작업 2일) 가능 여부 확인', questions: ['이번 주말 인원 투입 가능한지'], avoid: ['계약·금액'],
    language: 'ko', voice_id: null, duration_s: 130, summary_ko: '토요일 6명 가능, 일요일은 불가. 가장 빠른 대안은 월요일 연장 작업.',
    result_proposed: '조건부 가능', result_confirmed: null, confirmed_by: null,
    answers: [{ question: '이번 주말 인원 투입 가능한지', answer: '토요일만 가능', quote: '토요일은 6명 됩니다', quote_found: true }],
    events: [], has_recording: false, prev_call_id: null, activity: null, scheduled_at: null,
    started_at: '2026-11-23T05:15:00Z', ended_at: '2026-11-23T05:17:10Z', created_at: '2026-11-23T05:14:00Z', ...over,
  });
  await page.route(/\/api\/schedules\/\d+\/outreach\/calls\?contact_id=\d+$/, (route) =>
    route.fulfill({
      json: [
        call({ id: 2, status: 'no_answer', duration_s: null, summary_ko: '', result_proposed: '', answers: [], created_at: '2026-11-22T05:14:00Z', started_at: '2026-11-22T05:15:00Z' }),
        call({}),
      ],
    }),
  );
}

async function login(page: Page) {
  await page.goto('/');
  await page.getByLabel('아이디').fill(LOGIN_ID);
  await page.getByLabel('비밀번호').fill(PASSWORD);
  await page.getByRole('button', { name: '들어가기' }).click();
}

async function setTheme(page: Page, theme: 'light' | 'dark') {
  const want = theme === 'dark' ? '어두운 테마' : '밝은 테마'; // 단추 이름은 「누르면 될 테마」
  const btn = page.getByRole('button', { name: want });
  if (await btn.count()) await btn.first().click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
}

async function pickOffice(page: Page) {
  await page.getByRole('button', { name: /일정 고르기|5층 사무동/ }).first().click();
  await page.getByRole('option', { name: /5층 사무동/ }).click();
}

async function shot(page: Page, name: string) {
  const dir = process.env.E2E_SHOTS_DIR || test.info().outputPath('shots');
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${dir}/${name}.png` });
}

/** 넘침 없음: 문서가 옆으로 밀리지 않고, 연락처 안의 어떤 칸도 잘린 채 넘치지 않으며(…로 자르는 칸은 빼고) 화면 밖으로 나가지 않는다.
 *  전체 번호도 보이지 않는다. */
async function fits(page: Page) {
  const r = await page.evaluate(() => {
    const vw = window.innerWidth;
    const all = [...document.querySelectorAll<HTMLElement>('.ct-root, .ct-root *')];
    const clipped = all
      .filter((e) => e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX !== 'visible')
      .filter((e) => !e.classList.contains('ct-ellipsis') && !e.classList.contains('ct-sr') && !e.closest('.ct-ellipsis'))
      .filter((e) => getComputedStyle(e).textOverflow !== 'ellipsis' && !e.closest('.cmp-pick-btn'))
      .map((e) => `${e.tagName}.${e.className} ${e.scrollWidth}>${e.clientWidth}`);
    const outside = all
      .filter((e) => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0 && (b.right > vw + 1 || b.left < -1); })
      .filter((e) => !e.closest('.ct-ellipsis'))
      .map((e) => `${e.tagName}.${e.className}`);
    return { doc: document.documentElement.scrollWidth, vw, clipped, outside: outside.slice(0, 5) };
  });
  expect(r.doc).toBeLessThanOrEqual(r.vw);
  expect(r.clipped).toEqual([]);
  expect(r.outside).toEqual([]);
  expect(await page.locator('body').innerText()).not.toMatch(FULL_NUMBER);
}

/** 긴급 보고 읽기를 가상 줄 하나로(처음 한 번만 — 다음 물음부터는 빈 목록). */
async function fakeUrgent(page: Page) {
  let first = true;
  await page.route(/\/api\/outreach\/alerts(\?.*)?$/, (route) => {
    const items = first
      ? [{ id: 77, schedule_id: null, schedule_name: OFFICE, medium: 'call', contact_name: '박가상', created_at: new Date().toISOString() }]
      : [];
    first = false;
    return route.fulfill({ json: { now: new Date().toISOString(), items } });
  });
}
const URGENT = '긴급 보고 — 5층 사무동 신축 · 박가상 · 전화로 받은 보고';

const book = (page: Page) => page.getByRole('navigation', { name: '주소록' });
const person = (page: Page, name: string) => book(page).getByRole('button', { name: new RegExp(name) }).first();

test.describe('phone 390×844', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  for (const theme of THEMES) {
    test(`연락처 tab: list → conversation one screen at a time, composer on the bottom, summary first (${theme})`, async ({ page, request }) => {
      await seedBook(request);
      await fakeThreadAndCalls(page);
      await login(page);
      await expect(page.getByTestId('mobile-shell')).toBeVisible();
      await setTheme(page, theme);
      await pickOffice(page);
      const nav = page.getByRole('navigation', { name: '모바일 탐색' });
      await expect(nav.locator('.mob-tab-label')).toHaveText(['대화', '일정·현장', '승인', '연락처', '전체']);
      await nav.getByRole('button', { name: /연락처/ }).click();

      // 1. 목록만
      await expect(person(page, '박가상')).toBeVisible();
      await expect(page.getByRole('region', { name: '연락처 자세히' })).toBeHidden();
      await fits(page);
      await shot(page, `phone-${theme}-1-book`);

      // 2. 대화만 — 위 「‹ 이름」, 탭 둘, 입력창은 아래 탭 바로 위
      await person(page, '박가상').click();
      await expect(book(page)).toBeHidden();
      const back = page.getByRole('button', { name: '박가상 — 주소록으로 돌아가기' });
      await expect(back).toHaveText('‹ 박가상');
      const tabs = page.getByRole('tablist', { name: '대화 종류' });
      await expect(tabs.getByRole('tab')).toHaveText(['문자 · 카카오톡', '통화 2']);
      const log = page.getByRole('log').first();
      await expect(log.getByText('가상 문자 29', { exact: false })).toBeVisible();
      const composer = page.locator('[data-slot="composer"]');
      const navBox = (await nav.boundingBox())!;
      const box = async () => (await composer.boundingBox())!;
      const at = await box();
      expect(at.x).toBeGreaterThanOrEqual(0);
      expect(at.x + at.width).toBeLessThanOrEqual(390);
      expect(at.y + at.height).toBeLessThanOrEqual(navBox.y + 1);
      expect(navBox.y - (at.y + at.height)).toBeLessThan(4); // 붙어 있다
      expect(await log.evaluate((e) => e.scrollHeight > e.clientHeight)).toBe(true); // 긴 대화는 대화 칸 안에서만 밀린다
      expect((await log.boundingBox())!.height).toBeGreaterThanOrEqual(360); // 입력창이 낮아 대화가 360px 이상 보인다
      await log.evaluate((e) => e.scrollTo(0, 0));
      expect((await box()).y).toBeCloseTo(at.y, 0);
      await fits(page);
      await shot(page, `phone-${theme}-2-thread`);

      // 3. 통화 — 카드는 요약이 먼저(누가·상태 줄 바로 아래)
      await tabs.getByRole('tab', { name: '통화 2' }).click();
      const card = page.getByRole('log', { name: '통화 기록' }).getByRole('article').filter({ hasText: '토요일 6명 가능' });
      await expect(card).toBeVisible();
      const summary = (await card.locator('.cl-text', { hasText: '요약' }).boundingBox())!;
      const purpose = (await card.locator('.cl-text', { hasText: '목적' }).boundingBox())!;
      const head = (await card.locator('.th-meta').first().boundingBox())!;
      expect(head.y).toBeLessThan(summary.y);
      expect(summary.y).toBeLessThan(purpose.y);
      await expect(card.locator('.cl-text b')).toHaveText(['요약', '목적']); // DOM 차례도 같다(읽는 차례)
      await card.scrollIntoViewIfNeeded();
      await fits(page);
      await shot(page, `phone-${theme}-3-calls`);

      // 4. 돌아가기
      await back.click();
      await expect(person(page, '박가상')).toBeVisible();
      await expect(page.getByRole('region', { name: /대화$/ })).toBeHidden();
    });

    test(`urgent report toast on the phone sits under the header, clear of the composer and the tab bar (${theme})`, async ({ page, request }) => {
      await seedBook(request);
      await fakeThreadAndCalls(page);
      await page.clock.install();
      await login(page);
      await expect(page.getByTestId('mobile-shell')).toBeVisible();
      await setTheme(page, theme);
      await pickOffice(page);
      const nav = page.getByRole('navigation', { name: '모바일 탐색' });
      await nav.getByRole('button', { name: /연락처/ }).click();
      await person(page, '박가상').click();
      await expect(page.locator('[data-slot="composer"]')).toBeVisible();
      await fakeUrgent(page);
      await page.clock.runFor(21_000); // 다음 물음(20초)
      const toast = page.getByRole('button', { name: URGENT });
      await expect(toast).toBeVisible();
      await expect.poll(async () => (await toast.evaluate((e) => getComputedStyle(e).transform))).toMatch(/^(none|matrix\(1, 0, 0, 1, 0, 0\))$/); // 들어오는 움직임 끝
      const t = (await toast.boundingBox())!;
      const head = (await page.locator('.mob-head').boundingBox())!;
      const cmp = (await page.locator('[data-slot="composer"]').boundingBox())!;
      expect(t.y).toBeGreaterThanOrEqual(head.y + head.height);
      expect(t.y + t.height).toBeLessThanOrEqual(cmp.y);
      expect(t.x).toBeGreaterThanOrEqual(0);
      expect(t.x + t.width).toBeLessThanOrEqual(390);
      expect(await page.locator('body').innerText()).not.toMatch(FULL_NUMBER);
      await shot(page, `phone-${theme}-4-urgent-toast`);
      await toast.click(); // 누르면 닫힌다
      await expect(toast).toBeHidden();
    });
  }
});

test.describe('tablet', () => {
  test.use({ userAgent: IPAD_UA, hasTouch: true });

  for (const theme of THEMES) {
    test(`landscape 1180×820: two panes like the PC, urgent toast under the header (${theme})`, async ({ page, request }) => {
      await page.setViewportSize({ width: 1180, height: 820 });
      await seedBook(request);
      await fakeThreadAndCalls(page);
      await page.clock.install();
      await login(page);
      await expect(page.getByTestId('tablet-shell')).toBeVisible();
      await setTheme(page, theme);
      await pickOffice(page);
      await page.getByRole('navigation', { name: '태블릿 탐색' }).getByRole('button', { name: '연락처' }).click();
      await person(page, '박가상').click();
      await expect(book(page)).toBeVisible();
      await expect(page.getByRole('region', { name: '박가상 대화' })).toBeVisible();
      await expect(page.getByRole('button', { name: /주소록으로 돌아가기/ })).toHaveCount(0);
      await fits(page);
      await shot(page, `tablet-${theme}-1-two-panes`);
      await page.getByRole('tab', { name: '통화 2' }).click();
      await fits(page);
      await shot(page, `tablet-${theme}-2-calls`);

      // 긴급 보고 토스트(후속): 머리 아래 오른쪽
      await fakeUrgent(page);
      await page.clock.runFor(21_000);
      const toast = page.getByRole('button', { name: URGENT });
      await expect(toast).toBeVisible();
      await expect.poll(async () => (await toast.evaluate((e) => getComputedStyle(e).transform))).toMatch(/^(none|matrix\(1, 0, 0, 1, 0, 0\))$/);
      const t = (await toast.boundingBox())!;
      expect(t.y).toBeGreaterThanOrEqual((await page.locator('.tab-head').boundingBox())!.height);
      expect(t.x + t.width).toBeLessThanOrEqual(1180);
      await shot(page, `tablet-${theme}-3-urgent-toast`);
    });

    test(`portrait 820×1180: the book folds after picking and [주소록] unfolds it (${theme})`, async ({ page, request }) => {
      await page.setViewportSize({ width: 820, height: 1180 });
      await seedBook(request);
      await fakeThreadAndCalls(page);
      await login(page);
      await expect(page.getByTestId('tablet-shell')).toBeVisible();
      await setTheme(page, theme);
      await pickOffice(page);
      await page.getByRole('navigation', { name: '태블릿 탐색' }).getByRole('button', { name: '연락처' }).click();
      await expect(person(page, '박가상')).toBeVisible();
      await fits(page);
      await shot(page, `tablet-portrait-${theme}-1-book`);
      await person(page, '박가상').click();
      await expect(book(page)).toBeHidden();
      const pane = page.getByRole('region', { name: '박가상 대화' });
      await expect(pane).toBeVisible();
      await fits(page);
      await shot(page, `tablet-portrait-${theme}-2-folded`);
      const toggle = page.getByRole('button', { name: '주소록', exact: true });
      await expect(toggle).toHaveAttribute('aria-expanded', 'false');
      await toggle.click();
      await expect(book(page)).toBeVisible();
      await expect(pane).toBeVisible();
      await fits(page);
      await shot(page, `tablet-portrait-${theme}-3-unfolded`);
      await person(page, '이가상').click();
      await expect(book(page)).toBeHidden();
      await expect(page.getByRole('region', { name: '이가상 대화' })).toBeVisible();
    });
  }
});
