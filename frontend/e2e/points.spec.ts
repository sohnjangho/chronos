import { expect, test, type APIRequestContext, type Locator, type Page, type Route } from '@playwright/test';

// 관리 포인트 카드·당김 효과 카드(계획 5 Task 6) 끝에서 끝까지 — 가짜 답으로(FHD 밝게·어둡게 + 1280×800).
// 로그인·일정 목록·주의할 일정은 실제 시험 서버(가짜 LLM, 밖 연결 막힘). 대화 한 줄(저장된 카드 사건)과 관리 포인트·연락·비교판 읽기는
// 브라우저에서 가짜 답(page.route — 서버까지 가지 않음, 꼴은 backend/app/points/card.py · programs/points · scenarios/compare 그대로).
// 장면: 포인트 카드(건너뛴 자료는 접힘) → [근거 문장 보기] 찾는 중 → 문장·링크 → [담당자에게 확인 연락] 사람 고르기(번호 없음) →
// 미리 보기 → [초안 만들기] → 문자 초안 카드 → 당김 효과 카드 → [관리 포인트로 보기] → 비교판 요약의 새 칸 둘. 넘침 없음.
// 실행: bash scripts/e2e-local.sh e2e/points.spec.ts (E2E_SHOTS_DIR=… 면 그 폴더에 p5-*.png). 숫자·회사·기사는 모두 가상.

const LOGIN_ID = process.env.E2E_LOGIN_ID ?? 'demo-admin';
const PASSWORD = process.env.E2E_PASSWORD ?? 'demo-pass-e2e';
const OFFICE = '5층 사무동 신축';
const CHAT_ID = 99101;
const TITLE = '커튼월 도면 승인 3일 지연';
const NOW = new Date('2026-11-24T17:12:00+09:00');
const DRAFT = '[5층 사무동 신축] 최가상 님, 「커튼월 공장 제작」(06.03~06.18) 여유가 4일에서 1일로 줄었습니다. 참고한 바깥 소식: 알루미늄 3개월 +5.0%; 원·달러 1,350원. 일정대로 진행할 수 있는지 알려 주시겠어요?';
const FULL_NUMBER = /(?:\+82|0)1\d[-. ]?\d{3,4}[-. ]?\d{4}/;
const SIZES = [
  { name: 'fhd', width: 1920, height: 1080 },
  { name: '1280', width: 1280, height: 800 },
] as const;

test.use({ actionTimeout: 15_000 });
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: 'ignoreErrors' }));

const win = (page: Page, title: string): Locator => page.locator(`.os-win[aria-label^="${title}"]`);
const dock = (page: Page, name: string): Locator => page.locator(`.os-dock-btn[aria-label="${name}"], .os-dock-btn[aria-label^="${name},"]`);

const READY = {
  status: 'ready', message: '', error_code: null,
  quotes: [
    { text: '“알루미늄 3개월 평균 가격은 앞 분기보다 5% 올랐다.”', url: 'https://example.com/metal', title: '비철금속 시세 동향 — 가상경제' },
    { text: '“압출 업계는 하반기 원가 부담을 예상했다.”', url: 'https://example.com/extrusion', title: '압출 업계 원가 — 가상건설신문' },
  ],
};
const PENDING = { status: 'pending', message: '근거 문장 찾는 중', error_code: null, quotes: [] };
const FAILED = { status: 'failed', message: '근거 문장을 찾지 못했습니다', error_code: 'timeout', quotes: [] };

const risk = (aid: string, kind: string, line: string, over: Record<string, unknown> = {}) => ({
  activity_id: aid, kind, line, evidence_id: 1, as_of: '2026-10', source: 'The World Bank', status: 'ok', why: '', quote: null,
  actions: kind === 'weather' ? ['quote', 'condition'] : ['quote'], ...over,
});

function pointsCard(sid: number, quote: unknown) {
  return {
    kind: 'points_changed', schedule_id: sid, version: 8, what_if: false, basis: { tf_days: 3, window_weeks: 3 }, domain: 'construction',
    trigger: { kind: 'version', from: 7, to: 8 },
    new: [
      {
        activity_id: 'A1500', name: '커튼월 공장 제작', critical: false, tf: 1, es: '2027-06-03', ef: '2027-06-18', became_critical: false, before_tf: 4, responsible: ['(주)가상커튼월'],
        risks: [
          risk('A1500', 'materials', '알루미늄 3개월 +5.0%', { why: '커튼월 프레임이 알루미늄 압출재입니다', quote }),
          risk('A1500', 'fx', '원·달러 1,350원', { source: 'Xignite', as_of: '2026-11-24 16:58', why: '수입 유리·실란트' }),
          risk('A1500', 'business', '(주)가상커튼월, 압출 설비 점검으로 6월 출하 일정 조정', { source: '가상경제', as_of: '2026-11-21' }),
        ],
        actions: ['contact', 'recovery'],
      },
      {
        activity_id: 'A1600', name: '커튼월·외장 패널 1~3층 — 아주 긴 이름이 줄을 바꾸는지 보는 가상 작업 이름', critical: true, tf: 0, es: '2027-06-21', ef: '2027-07-09', became_critical: true, responsible: ['(주)가상외장'],
        risks: [
          risk('A1600', 'business', '(주)가상외장, 수도권 현장 세 곳 동시 착수', { source: '가상건설신문', as_of: '2026-11-19', quote: FAILED }),
          risk('A1600', 'materials', '외장 패널 · 바깥 자료 없음', { status: 'none', source: null, as_of: null, evidence_id: null, actions: [], why: '외장 패널 단가 자료를 받지 못함' }),
        ],
        actions: ['contact', 'recovery'],
      },
    ],
    more: 0, tightened: [],
    removed: [
      { activity_id: 'A1400', name: '경량 벽체 1~3층', reason: 'relief', label: '여유가 늘어남', before_tf: 3, tf: 6 },
      { activity_id: 'A1450', name: '설비 배관 4층', reason: 'out_of_window', label: '창 밖으로 밀림', before_tf: 2 },
    ],
    skipped: [{ activity_id: 'A1600', name: '커튼월·외장 패널 1~3층', kind: 'weather', line: '프로젝트 주소가 없어 날씨를 보지 않음' }],
    skipped_count: 1, risk_status: 'done', risk_message: '',
  };
}

function accelCard(sid: number) {
  return {
    kind: 'accel_check', schedule_id: sid, activity_id: 'A1320', name: '5층 골조', od_before: 12, od_after: 7, pulled_days: 5, reached_days: 1,
    ratio: 0.2, warn: true, warn_line: '당긴 5일 중 1일만 준공에 반영됩니다', summary_line: '5층 골조 5일 당김 → 준공 1일 당겨짐',
    finish_before: '2027-10-29', finish_after: '2027-10-28',
    next_chain: [
      { activity_id: 'A1490', name: '커튼월 제작 도면 승인', point: true },
      { activity_id: 'A1500', name: '커튼월 공장 제작', point: true },
      { activity_id: 'A1550', name: '커튼월 자재 반입', point: false },
      { activity_id: 'A1600', name: '커튼월·외장 패널 1~3층', point: true },
    ],
    same_chain: false,
  };
}

const ev = (type: string, data: unknown, id: number) => ({ id, role: 'event', content: { type, data } });

async function officeId(request: APIRequestContext): Promise<number> {
  const login = await request.post('/api/auth/login', { data: { login_id: LOGIN_ID, password: PASSWORD } });
  const headers = { Authorization: `Bearer ${(await login.json()).token}` };
  const list: { id: number; name: string }[] = await (await request.get('/api/schedules', { headers })).json();
  return list.find((s) => s.name === OFFICE)!.id;
}

/** 가짜 답들. 근거 문장은 처음 누르면 찾는 중, 다음 GET 부터 찾음. 연락 POST 본문을 모은다. */
async function fake(page: Page, sid: number) {
  let asked = false;
  const contactBodies: Record<string, unknown>[] = [];
  const session = { id: CHAT_ID, title: TITLE, schedule_id: sid, created_at: '2026-11-24T08:10:00Z' };
  await page.route(/\/api\/chat\/sessions(\?.*)?$/, (route: Route) =>
    route.request().method() === 'GET' ? route.fulfill({ json: [session] }) : route.fallback());
  await page.route(new RegExp(`/api/chat/sessions/${CHAT_ID}$`), (route) =>
    route.fulfill({
      json: {
        ...session, running: false, model: null, files: [], pending_retries: [],
        messages: [
          { id: 1, role: 'user', content: { kind: 'text', text: '커튼월 제작 도면 승인이 3일 늦어졌어' } },
          ev('card', { kind: 'delay_impact', schedule_id: sid, event_id: 5, activity_id: 'A1490', name: '커튼월 제작 도면 승인', days: 3, status: 'open', impact: { finish_delta: 0, absorbed: 3, critical_added: [], critical_removed: [], new_clashes: [] } }, 2),
          ev('card', pointsCard(sid, null), 3),
          { id: 4, role: 'assistant', content: { kind: 'text', text: '지연을 기록했습니다. 준공은 그대로이지만 관리 포인트 두 곳이 바뀌어, 그 기간의 자재 시세·환율·업체 소식을 찾아 붙였습니다.' } },
          { id: 5, role: 'user', content: { kind: 'text', text: '5층 골조를 5일 당기면 준공이 당겨져?' } },
          ev('card', accelCard(sid), 6),
          { id: 7, role: 'assistant', content: { kind: 'text', text: '준공은 1일만 당겨집니다. 그다음은 커튼월 도면 승인부터 이어지는 줄이 준공을 정합니다.' } },
        ],
      },
    }));
  await page.route(new RegExp(`/api/schedules/${sid}/points\\?what_if=(true|false)$`), (route) => {
    if (route.request().url().endsWith('what_if=true')) return route.fulfill({ status: 404, json: { code: 'no_what_if', message: '가정 관리 포인트가 없습니다.', detail: null } });
    const quote = asked ? READY : null;
    return route.fulfill({
      json: {
        schedule_id: sid, version: 8, what_if: false, basis: { tf_days: 3, window_weeks: 3 }, points: [], risk_status: 'done', risks: [],
        quotes: { 'A1500/materials': quote, 'A1600/business': FAILED }, card: pointsCard(sid, quote),
      },
    });
  });
  await page.route(new RegExp(`/api/schedules/${sid}/points/A1500/quotes/materials$`), (route) => {
    asked = true;
    return route.fulfill({ json: PENDING });
  });
  await page.route(new RegExp(`/api/schedules/${sid}/points/A1500/contact(\\?.*)?$`), (route) => {
    if (route.request().method() === 'GET')
      return route.fulfill({
        json: {
          activity_id: 'A1500', name: '커튼월 공장 제작',
          people: [
            { contact_id: 31, name: '최가상', role_title: '생산 관리', company: '(주)가상커튼월', trade: '커튼월', do_not_contact: false, channels: ['sms', 'call'] },
            { contact_id: 32, name: '한가상', role_title: '영업', company: '(주)가상커튼월', trade: '커튼월', do_not_contact: false, channels: ['sms'] },
            { contact_id: 33, name: '오가상', role_title: '공장장', company: '(주)가상커튼월', trade: '커튼월', do_not_contact: true, channels: [] },
          ],
        },
      });
    const body = route.request().postDataJSON() as Record<string, unknown>;
    contactBodies.push(body);
    const text = DRAFT;
    if (body.preview) return route.fulfill({ json: { preview: true, channel: 'sms', body: text } });
    return route.fulfill({
      json: { preview: false, card: { kind: 'outreach_draft', schedule_id: sid, message_id: 9901, contact: { id: 31, name: '최가상', role_title: '생산 관리', company: '(주)가상커튼월' }, channel: 'sms', body: text, body_ko: null, needs_approval: true } },
    });
  });
  // 초안 카드가 그 줄의 지금 모습을 읽는다 — 초안 그대로
  await page.route(new RegExp(`/api/schedules/${sid}/outreach/threads/31(\\?.*)?$`), (route) =>
    route.fulfill({ json: { contact: { id: 31, name: '최가상' }, messages: [{ id: 9901, status: 'draft', channel: 'sms', body: DRAFT, body_ko: null }], has_more: false } }));
  // 비교판(지연 카드 [비교판에서 보기] → 복사본 4): 요약 표에 당김 효과 칸
  await page.route(new RegExp(`/api/schedules/${sid}/delays/scenario$`), (route) => route.fulfill({ json: { scenario_id: 4 } }));
  const side = (over: Record<string, unknown>) => ({
    version: 8, finish: '2027-10-29', plan_delta: 0, deadline: '2027-10-31', deadline_float: 2, critical_count: 12, violations: 0, uncheckable: 0,
    peak: null, changes: [], stale: false, status: null, accel: null, accel_reason: null, ...over,
  });
  const sides = [
    side({ ref: 'current', label: '현재 일정 (버전 8)' }),
    side({ ref: 'plan', label: 'Plan (버전 1)' }),
    side({
      ref: 's:4', label: '만회안 · 5층 골조 5일 당기기', finish: '2027-10-28', plan_delta: -1, deadline_float: 3, status: 'open', changes: ['5층 골조 기간 12일 → 7일'],
      accel: { pulled_days: 5, finish_gain: 1, warn: true, next_chain: accelCard(sid).next_chain },
    }),
    side({ ref: 's:5', label: '만약에 · 골조 당김 + 자원 늘림', finish: '2027-10-27', plan_delta: -2, status: 'open', accel_reason: '여러 가지를 함께 바꿔 당김 효과를 따로 셀 수 없습니다' }),
  ];
  await page.route(new RegExp(`/api/schedules/${sid}/compare/summary$`), (route) => route.fulfill({ json: { sides } }));
  await page.route(new RegExp(`/api/schedules/${sid}/compare\\?`), (route) =>
    route.fulfill({ json: { base: sides[0], other: sides[2], rows: [], changed_count: 0 } }));
  return { contactBodies };
}

async function login(page: Page) {
  await page.clock.setFixedTime(NOW);
  await page.goto('/');
  await page.getByLabel('아이디').fill(LOGIN_ID);
  await page.getByLabel('비밀번호').fill(PASSWORD);
  await page.getByRole('button', { name: '들어가기' }).click();
  await expect(dock(page, '에이전트 대화')).toBeVisible();
}

async function setTheme(page: Page, theme: 'light' | 'dark') {
  const want = theme === 'dark' ? '어두운 테마' : '밝은 테마';
  const btn = page.getByRole('button', { name: want });
  if (await btn.count()) await btn.first().click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
}

async function shot(page: Page, name: string) {
  const dir = process.env.E2E_SHOTS_DIR || test.info().outputPath('shots');
  await page.mouse.move(5, 540);
  // 카드로 내려 볼 때 바탕(문서) 자체가 밀리지 않게 — 대화 칸 안의 스크롤만 남긴다
  await page.evaluate(() => {
    window.scrollTo(0, 0);
    for (const e of document.querySelectorAll<HTMLElement>('html, body, #root, .os-desktop, .os-win, .os-win-body')) e.scrollTop = 0;
  });
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${dir}/p5-${name}.png` });
}

/** 넘침 없음: 문서가 옆으로 밀리지 않고, 카드 안 어떤 칸도 잘린 채 넘치지 않는다(…로 자르는 칸은 빼고). 전체 번호도 없다. */
async function fits(page: Page, scope: string) {
  const r = await page.evaluate((sel) => {
    const vw = window.innerWidth;
    const all = [...document.querySelectorAll<HTMLElement>(`${sel}, ${sel} *`)];
    const clipped = all
      .filter((e) => e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX !== 'visible')
      .filter((e) => getComputedStyle(e).textOverflow !== 'ellipsis' && !e.closest('.ch-ellipsis') && !e.matches('.ch-scroll, .cmp-sum, .cmp-root, .ch-ctx-scroll'))
      .map((e) => `${e.tagName}.${e.className} ${e.scrollWidth}>${e.clientWidth}`);
    return { doc: document.documentElement.scrollWidth, vw, clipped: clipped.slice(0, 5) };
  }, scope);
  expect(r.doc).toBeLessThanOrEqual(r.vw);
  expect(r.clipped).toEqual([]);
  expect(await page.locator('body').innerText()).not.toMatch(FULL_NUMBER);
}

async function openThread(page: Page): Promise<Locator> {
  const chat = win(page, '에이전트 대화');
  await page.waitForTimeout(500); // 앞 시험에서 연 창은 다시 열린다(서버에 둔 창 배치)
  if (!(await chat.isVisible())) await dock(page, '에이전트 대화').click();
  await expect(chat).toBeVisible();
  const max = chat.locator('.os-lt-max');
  if ((await max.getAttribute('title')) === '최대화') await max.click(); // 대화 목록이 옆에 보이도록 창을 키운다
  const item = chat.getByRole('button', { name: TITLE, exact: true });
  if (!(await item.isVisible())) await chat.getByRole('button', { name: /^대화 고르기/ }).click(); // 좁은 화면: 위쪽 고르기
  await item.click();
  await expect(chat.getByRole('region', { name: '관리 포인트' })).toBeVisible();
  return chat;
}

for (const size of SIZES) {
  for (const theme of ['light', 'dark'] as const) {
    if (size.name === '1280' && theme === 'dark') continue; // 1280×800 은 밝게 한 장만
    test(`points cards · ${size.name} · ${theme}`, async ({ page, request }) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      const sid = await officeId(request);
      const { contactBodies } = await fake(page, sid);
      await login(page);
      await setTheme(page, theme);
      const chat = await openThread(page);
      const tag = `${size.name}-${theme}`;

      // 1. 포인트 카드: 여유 4일 → 1일, 크리티컬, 위험 줄 출처, 건너뛴 자료는 접힘, 빠진 포인트 까닭
      const card = chat.getByRole('region', { name: '관리 포인트' });
      const a = card.getByRole('group', { name: '커튼월 공장 제작' });
      await expect(a.getByText('알루미늄 3개월 +5.0%')).toBeVisible();
      await expect(a.getByText('The World Bank · 2026-10')).toBeVisible();
      await expect(card.getByText('건너뛴 자료 1개')).toBeVisible();
      await expect(card.getByText(/프로젝트 주소가 없어/)).toBeHidden();
      await expect(card.getByText('설비 배관 4층 — 창 밖으로 밀림')).toBeVisible();
      await expect(a.getByText('2027.06.03 ~ 2027.06.18 · 담당 (주)가상커튼월')).toBeVisible();
      await expect(card.getByText('2027.06.21 ~ 2027.07.09 · 실외 작업 · 담당 (주)가상외장')).toBeVisible(); // 건설 · 날씨를 찾은 포인트만
      await expect(card.getByRole('button', { name: '조건으로 넣어 보기' })).toHaveCount(0); // 본문에 날씨 줄 없음
      await card.scrollIntoViewIfNeeded();
      await fits(page, '.ch-root');
      await shot(page, `01-card-${tag}`);

      // 2. [근거 문장 보기]: 찾는 중 → (폴링) 문장·링크. 실패 줄은 「다시 찾기」
      await a.getByRole('button', { name: '근거 문장 보기' }).first().click();
      await expect(a.getByText(/근거 문장 찾는 중/)).toBeVisible();
      await expect(a.getByText('“알루미늄 3개월 평균 가격은 앞 분기보다 5% 올랐다.”')).toBeVisible({ timeout: 10_000 });
      await expect(a.getByRole('link', { name: /비철금속 시세 동향/ })).toHaveAttribute('target', '_blank');
      const b = card.getByRole('group', { name: /커튼월·외장 패널 1~3층/ });
      await b.getByRole('button', { name: '근거 문장 보기' }).click();
      await expect(b.getByText('근거 문장을 찾지 못했습니다.')).toBeVisible();
      await expect(b.getByRole('button', { name: '다시 찾기' })).toBeVisible();
      await a.scrollIntoViewIfNeeded();
      await fits(page, '.ch-root');
      await shot(page, `02-quotes-${tag}`);

      // 3. [담당자에게 확인 연락] → 사람 고르기(번호 없음) → 미리 보기 → [초안 만들기] → 문자 초안 카드
      await a.getByRole('button', { name: '담당자에게 확인 연락' }).click();
      const picker = a.getByRole('group', { name: '담당자에게 확인 연락' });
      await expect(picker.getByText(/연락처 3명 · 번호는 보이지 않습니다/)).toBeVisible();
      await expect(picker.getByRole('radio', { name: /오가상/ })).toBeDisabled();
      await picker.getByRole('radio', { name: /최가상/ }).click();
      await expect(picker.getByText(/여유가 4일에서 1일로 줄었습니다/)).toBeVisible();
      await picker.scrollIntoViewIfNeeded();
      await fits(page, '.ch-root');
      await shot(page, `03-contact-${tag}`);
      await picker.getByRole('button', { name: '초안 만들기' }).click();
      const draft = a.getByRole('region', { name: '문자 초안' });
      await expect(draft).toBeVisible();
      await expect(draft.getByRole('button', { name: '보내기' })).toBeVisible(); // 보내기는 사람이 — 자동 발송 없음
      expect(contactBodies.map((x) => x.preview)).toEqual([true, false]);
      await draft.scrollIntoViewIfNeeded();
      await shot(page, `04-draft-${tag}`);

      // 4. 당김 효과 카드 → [관리 포인트로 보기] 는 대화에 포인트 카드를
      const accel = chat.getByRole('region', { name: '당김 효과' });
      await accel.scrollIntoViewIfNeeded();
      await expect(accel.getByText('준공 반영 5일 중 1일')).toBeVisible();
      await expect(accel.getByText('당긴 5일 중 1일만 준공에 반영됩니다')).toBeVisible();
      await fits(page, '.ch-root');
      await shot(page, `05-accel-${tag}`);
      await accel.getByRole('button', { name: '관리 포인트로 보기' }).click();
      await expect(chat.getByRole('region', { name: '관리 포인트' })).toHaveCount(2);
      await chat.getByRole('region', { name: '관리 포인트' }).nth(1).scrollIntoViewIfNeeded();
      await fits(page, '.ch-root');
      await shot(page, `06-accel-points-${tag}`);

      // 5. 비교판 요약 표: 「준공 반영」 5일 중 1일 · 「다음 결정 줄」 · 셀 수 없는 까닭
      await chat.getByRole('region', { name: '지연 영향' }).getByRole('button', { name: '비교판에서 보기' }).click();
      const compare = win(page, '비교판');
      await expect(compare).toBeVisible();
      const table = compare.getByRole('table', { name: '여러 안 요약' });
      await expect(table.getByRole('columnheader', { name: '준공 반영' })).toBeVisible();
      await expect(table.getByText('5일 중 1일')).toBeVisible();
      await expect(table.getByText('커튼월 제작 도면 승인 → 커튼월 공장 제작 → 커튼월 자재 반입 → 커튼월·외장 패널 1~3층')).toBeAttached();
      await expect(table.getByText('여러 가지를 함께 바꿔 당김 효과를 따로 셀 수 없습니다')).toBeAttached();
      await table.getByRole('columnheader', { name: '다음 결정 줄' }).scrollIntoViewIfNeeded();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width);
      await shot(page, `07-compare-${tag}`);
    });
  }
}
