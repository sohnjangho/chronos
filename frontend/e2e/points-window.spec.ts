import { expect, test, type APIRequestContext, type Locator, type Page, type Route } from '@playwright/test';

// 「관리 포인트」 창(계획 5 Task 11, 시안 B 3주 보드) 끝에서 끝까지 — 가짜 답으로(FHD 밝게·어둡게 + 1280×800 + 폰 390×844).
// 로그인·일정 목록은 실제 시험 서버(가짜 LLM, 밖 연결 막힘). 관리 포인트 조회·바뀜 기록·당김 효과·근거 문장·연락은 브라우저에서
// 가짜 답(page.route — 서버까지 가지 않음, 꼴은 backend/app/programs/points · points_board 그대로).
// 장면: Dock「관리 포인트」 → 보드(이번 주·다음 주·그다음 주) → 카드 → 자세히(여유 흐름 · 바깥 위험 · [근거 문장 보기] 찾는 중 → 문장 ·
// 당겨도 소용 있나 3일 → 결과·다음 줄) → [담당자에게 확인 연락] 미리 보기 → 바뀜 기록 모두 보기. 폰은 주 하나씩 → 자세히. 넘침 없음.
// 실행: bash scripts/e2e-local.sh e2e/points-window.spec.ts (E2E_SHOTS_DIR=… 면 그 폴더에 p11-*.png). 숫자·회사·기사는 모두 가상.

const LOGIN_ID = process.env.E2E_LOGIN_ID ?? 'demo-admin';
const PASSWORD = process.env.E2E_PASSWORD ?? 'demo-pass-e2e';
const OFFICE = '5층 사무동 신축';
const NOW = new Date('2026-11-24T17:12:00+09:00');
const FULL_NUMBER = /(?:\+82|0)1\d[-. ]?\d{3,4}[-. ]?\d{4}/;

test.use({ actionTimeout: 15_000 });
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: 'ignoreErrors' }));

const P = (activity_id: string, name: string, critical: boolean, tf: number, es: string, ef: string) => ({ activity_id, name, critical, tf, es, ef });
const POINTS = [
  P('A1500', '커튼월 제작 도면 승인', false, 1, '2027-05-27', '2027-06-04'),
  P('A1210', '4층 철근 배근', true, 0, '2027-06-02', '2027-06-07'),
  P('A1220', '4층 거푸집', true, 0, '2027-06-05', '2027-06-10'),
  P('A1510', '커튼월 공장 제작', false, 1, '2027-06-08', '2027-06-18'),
  P('A1230', '4층 콘크리트 타설', true, 0, '2027-06-11', '2027-06-12'),
  P('A1310', '5층 철근 배근', true, 0, '2027-06-15', '2027-06-19'),
  P('A1520', '커튼월 자재 반입', false, 1, '2027-06-21', '2027-06-21'),
  P('A1600', '커튼월·외장 패널 1~3층 — 아주 긴 이름이 줄을 바꾸는지 보는 가상 작업', false, 1, '2027-06-22', '2027-07-09'),
];
const RISKS = [
  { activity_id: 'A1510', kind: 'materials', line: '알루미늄 3개월 +5.0%', as_of: '2026-10', source: 'The World Bank', status: 'ok', why: '커튼월 프레임이 알루미늄 압출재입니다' },
  { activity_id: 'A1510', kind: 'fx', line: '원·달러 1,350원', as_of: '2026-11-24 16:58', source: 'Xignite', status: 'ok', why: '수입 유리·실란트' },
  { activity_id: 'A1510', kind: 'business', line: '(주)가상커튼월, 압출 설비 점검으로 6월 출하 일정 조정', as_of: '2026-11-21', source: '가상경제', status: 'ok' },
  { activity_id: 'A1510', kind: 'weather', line: '공장 안 작업이라 날씨를 보지 않음', as_of: null, source: null, status: 'skipped' },
  { activity_id: 'A1520', kind: 'business', line: '자재 반입 · 바깥 자료 없음', as_of: null, source: null, status: 'none' },
  { activity_id: 'A1600', kind: 'business', line: '(주)가상외장, 수도권 현장 세 곳 동시 착수', as_of: '2026-11-19', source: '가상건설신문', status: 'ok' },
];
const READY = {
  status: 'ready', message: '', error_code: null,
  quotes: [
    { text: '“가상커튼월은 이달 말부터 2주간 압출 라인을 점검해 6월 출하분 일부를 조정한다.”', url: 'https://example.com/a', title: '커튼월 업계, 설비 점검 잇따라 — 가상경제' },
    { text: '“업체 측은 이미 계약된 물량은 먼저 출하하겠다고 밝혔다.”', url: 'https://example.com/b', title: '가상커튼월 출하 일정 안내 — 가상건설신문' },
  ],
};
const PENDING = { status: 'pending', message: '근거 문장 찾는 중', error_code: null, quotes: [] };

function view(sid: number, asked: boolean) {
  return {
    schedule_id: sid, version: 8, what_if: false, basis: { tf_days: 3, window_weeks: 3 }, points: POINTS,
    diff: {
      added: [POINTS[3], POINTS[6], POINTS[7]], removed: ['A1400'], tightened: [], became_critical: [],
      before_tf: { A1510: 4, A1520: 4, A1600: 4 },
    },
    risk_status: 'done', risk_message: '', risks: RISKS,
    quotes: { 'A1510/materials': null, 'A1510/fx': null, 'A1510/business': asked ? READY : null, 'A1600/business': null },
    card: { new: [{ activity_id: 'A1510', responsible: ['(주)가상커튼월'] }, { activity_id: 'A1520', responsible: ['(주)가상커튼월'] }], tightened: [] },
  };
}

const entry = (version: number, at: string, note: string, over: Record<string, unknown> = {}) => ({
  version, what_if: false, saved_at: at, note, recorded: true, count: 8, critical: 4, new: [], more: 0, tightened: [], removed: [], ...over,
});
function history(sid: number, float: unknown) {
  return {
    schedule_id: sid, version: 8, basis: { tf_days: 3, window_weeks: 3 },
    window: { data_date: '2027-06-01', weeks: [{ start: '2027-06-01', end: '2027-06-07' }, { start: '2027-06-08', end: '2027-06-14' }, { start: '2027-06-15', end: '2027-06-22' }] },
    versions: [
      entry(8, '2026-11-24T08:05:00Z', '커튼월 제작 도면 승인 +3일', {
        new: [{ activity_id: 'A1510', name: '커튼월 공장 제작', tf: 1, before_tf: 4 }, { activity_id: 'A1520', name: '커튼월 자재 반입', tf: 1, before_tf: 4 },
          { activity_id: 'A1600', name: '커튼월·외장 패널 1~3층', tf: 1, before_tf: 4 }],
        removed: [{ activity_id: 'A1400', name: '경량 벽체 1~3층', reason: 'out_of_window', label: '창 밖으로 밀림', before_tf: 2 }],
      }),
      entry(7, '2026-11-20T02:00:00Z', 'Data Date 05.25 → 06.01', {
        new: [{ activity_id: 'A1310', name: '5층 철근 배근', tf: 0, before_tf: 2, became_critical: true }],
        removed: [{ activity_id: 'A1110', name: '3층 콘크리트 타설', reason: 'finished', label: '끝남', before_tf: 0 },
          { activity_id: 'A1120', name: '3층 양생', reason: 'relief', label: '여유가 늘어남', before_tf: 2, tf: 5 }],
      }),
      entry(6, '2026-11-18T02:00:00Z', '실적 입력 5월 4주', { tightened: [{ activity_id: 'A1500', name: '커튼월 제작 도면 승인', tf: 3, before_tf: 5 }] }),
      entry(5, '2026-11-12T02:00:00Z', '골조 공기 조정'),
      entry(1, '2026-11-01T02:00:00Z', '처음 올림', { recorded: false }),
    ],
    preview: { ...entry(8, '2026-11-24T08:10:00Z', '열린 지연을 넣은 가정'), what_if: true, new: [], removed: [
      { activity_id: 'A1510', name: '커튼월 공장 제작', reason: 'relief', label: '여유가 늘어남', before_tf: 1, tf: 5 },
      { activity_id: 'A1520', name: '커튼월 자재 반입', reason: 'relief', label: '여유가 늘어남', before_tf: 1, tf: 5 }] },
    float,
  };
}
const FLOAT = [
  { version: 5, tf: 6, critical: false, point: false },
  { version: 6, tf: 5, critical: false, point: false },
  { version: 7, tf: 4, critical: false, point: false },
  { version: 8, tf: 1, critical: false, point: true },
];
const ACCEL = {
  kind: 'accel_check', activity_id: 'A1510', name: '커튼월 공장 제작', od_before: 9, od_after: 6, pulled_days: 3, reached_days: 0, ratio: 0, warn: true,
  warn_line: '당긴 3일 중 0일만 준공에 반영됩니다', summary_line: '커튼월 공장 제작 3일 당김 → 준공 0일 당겨짐', finish_before: '2027-11-08', finish_after: '2027-11-08',
  next_chain: [{ activity_id: 'A1320', name: '4층 골조', point: true }, { activity_id: 'A1330', name: '5층 골조', point: true }, { activity_id: 'A1340', name: '옥탑 골조', point: false }],
  same_chain: true,
};
const DRAFT = '[5층 사무동] 최가상 님, 「커튼월 공장 제작」(06.08~06.18) 여유가 4일에서 1일로 줄었습니다. 일정대로 진행할 수 있는지 알려 주시겠어요?';

async function officeId(request: APIRequestContext): Promise<number> {
  const login = await request.post('/api/auth/login', { data: { login_id: LOGIN_ID, password: PASSWORD } });
  const headers = { Authorization: `Bearer ${(await login.json()).token}` };
  const list: { id: number; name: string }[] = await (await request.get('/api/schedules', { headers })).json();
  return list.find((s) => s.name === OFFICE)!.id;
}

/** 가짜 답. 근거 문장은 처음 누르면 찾는 중, 다음 조회부터 찾음. 보낸 POST 본문을 모은다. */
async function fake(page: Page, sid: number) {
  let asked = false;
  const posts: { url: string; body: unknown }[] = [];
  const base = `/api/schedules/${sid}/points`;
  await page.route(new RegExp(`${base}$`), (route) => route.fulfill({ json: view(sid, asked) }));
  await page.route(new RegExp(`${base}/history(\\?.*)?$`), (route) =>
    route.fulfill({ json: history(sid, new URL(route.request().url()).searchParams.get('activity') ? FLOAT : null) }));
  await page.route(new RegExp(`${base}/[^/]+/accel$`), (route) => {
    posts.push({ url: route.request().url(), body: route.request().postDataJSON() });
    return route.fulfill({ json: ACCEL });
  });
  await page.route(new RegExp(`${base}/A1510/quotes/business$`), (route) => {
    posts.push({ url: route.request().url(), body: route.request().postDataJSON() });
    asked = true;
    return route.fulfill({ json: PENDING });
  });
  await page.route(new RegExp(`${base}/A1510/contact$`), (route: Route) => {
    if (route.request().method() === 'GET')
      return route.fulfill({
        json: {
          activity_id: 'A1510', name: '커튼월 공장 제작',
          people: [
            { contact_id: 31, name: '최가상', role_title: '생산 관리', company: '(주)가상커튼월', trade: '커튼월', do_not_contact: false, channels: ['sms', 'call'] },
            { contact_id: 33, name: '오가상', role_title: '공장장', company: '(주)가상커튼월', trade: '커튼월', do_not_contact: true, channels: [] },
          ],
        },
      });
    const body = route.request().postDataJSON() as Record<string, unknown>;
    posts.push({ url: route.request().url(), body });
    return route.fulfill({ json: { preview: true, channel: 'sms', body: DRAFT } });
  });
  return { posts };
}

async function login(page: Page) {
  await page.clock.setFixedTime(NOW);
  await page.goto('/');
  await page.getByLabel('아이디').fill(LOGIN_ID);
  await page.getByLabel('비밀번호').fill(PASSWORD);
  await page.getByRole('button', { name: '들어가기' }).click();
  await expect(page.locator('.os-dock-btn, [data-testid="mobile-shell"]').first()).toBeVisible();
}

async function setTheme(page: Page, theme: 'light' | 'dark') {
  const btn = page.getByRole('button', { name: theme === 'dark' ? '어두운 테마' : '밝은 테마' });
  if (await btn.count()) await btn.first().click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
}

async function pickOffice(page: Page) {
  await page.getByRole('button', { name: /일정 고르기|5층 사무동/ }).first().click();
  await page.getByRole('option', { name: /5층 사무동/ }).click();
}

async function shot(page: Page, name: string) {
  const dir = process.env.E2E_SHOTS_DIR || test.info().outputPath('shots');
  await page.mouse.move(5, 540);
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${dir}/p11-${name}.png` });
}

/** 넘침 없음: 문서가 옆으로 밀리지 않고, 창 안 어떤 칸도 잘린 채 넘치지 않는다(…로 자르는 칸은 빼고). 전체 번호도 없다. */
async function fits(page: Page) {
  const r = await page.evaluate(() => {
    const vw = window.innerWidth;
    const all = [...document.querySelectorAll<HTMLElement>('.pt-root, .pt-root *')];
    const clipped = all
      .filter((e) => e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX !== 'visible')
      .filter((e) => getComputedStyle(e).textOverflow !== 'ellipsis')
      .map((e) => `${e.tagName}.${e.className} ${e.scrollWidth}>${e.clientWidth}`);
    return { doc: document.documentElement.scrollWidth, vw, clipped: clipped.slice(0, 5), roots: document.querySelectorAll('.pt-root').length };
  });
  expect(r.roots).toBe(1);
  expect(r.doc).toBeLessThanOrEqual(r.vw);
  expect(r.clipped).toEqual([]);
  expect(await page.locator('body').innerText()).not.toMatch(FULL_NUMBER);
}

const win = (page: Page): Locator => page.locator('.os-win[aria-label^="관리 포인트"]');

const SIZES = [
  { name: 'fhd', width: 1920, height: 1080, themes: ['light', 'dark'] as const },
  { name: '1280', width: 1280, height: 800, themes: ['light'] as const },
];

for (const size of SIZES) {
  for (const theme of size.themes) {
    test(`points window · ${size.name} · ${theme}`, async ({ page, request }) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      const sid = await officeId(request);
      const { posts } = await fake(page, sid);
      await login(page);
      await setTheme(page, theme);
      await pickOffice(page);
      const tag = `${size.name}-${theme}`;

      const w = win(page);
      await page.waitForTimeout(500); // 앞 시험에서 연 창은 다시 열린다(서버에 둔 창 배치)
      if (!(await w.isVisible())) await page.locator('.os-dock-btn[aria-label="관리 포인트"], .os-dock-btn[aria-label^="관리 포인트,"]').click();
      await expect(w).toBeVisible();
      if ((await w.locator('.os-lt-max').getAttribute('title')) === '최대화') await w.locator('.os-lt-max').click();
      await expect(w).toHaveAttribute('aria-label', new RegExp(`관리 포인트 — ${OFFICE}`));

      // 1. 보드: 이번 주 · 다음 주 · 그다음 주, 시작일 순 카드
      const col = (name: string) => w.getByRole('region', { name, exact: true });
      await expect(col('이번 주')).toContainText('06.01 ~ 06.07 · 3곳');
      await expect(col('이번 주').getByRole('button')).toHaveCount(3);
      await expect(col('다음 주').getByRole('button')).toHaveCount(2);
      await expect(col('그다음 주').getByRole('button')).toHaveCount(3);
      await expect(col('다음 주').getByRole('button').first()).toContainText('바뀜 4 → 1');
      await expect(w.getByRole('group', { name: '바뀜 기록' })).toContainText('커튼월 제작 도면 승인 +3일 · 들어옴 3 · 빠짐 1');
      await fits(page);
      await shot(page, `board-${tag}`);

      // 2. 자세히: 여유 흐름 → 바깥 위험(건너뛴 자료 접힘) → 근거 문장(찾는 중 → 문장) → 당김 효과
      await col('다음 주').getByRole('button', { name: /커튼월 공장 제작/ }).click();
      const d = w.getByRole('region', { name: '커튼월 공장 제작 자세히' });
      await expect(d.getByRole('list', { name: '여유 흐름' }).getByRole('listitem')).toHaveCount(4);
      await expect(d.getByRole('button', { name: '건너뛴 자료 1개 ▸' })).toBeVisible();
      await expect(d.getByText('공장 안 작업이라 날씨를 보지 않음')).toBeHidden();
      expect(posts).toEqual([]);
      await d.getByRole('button', { name: '근거 문장 보기' }).nth(2).click();
      await expect(d.getByText('근거 문장 찾는 중', { exact: false })).toBeVisible();
      await expect(d.getByText(READY.quotes[0].text)).toBeVisible({ timeout: 10_000 }); // 다음 조회(3초)에서 찾음
      await d.getByRole('textbox', { name: '당길 날 수' }).fill('3');
      await d.getByRole('button', { name: '계산' }).click();
      await expect(d.getByRole('status').last()).toContainText('당긴 3일 중 0일만 준공에 반영됩니다');
      await expect(d.getByRole('status').last()).toContainText('당긴 뒤에도 같은 줄이 일정을 정합니다');
      await expect(d.getByRole('button', { name: '준비 상태 확인 요청' })).toHaveCount(0);
      await fits(page);
      await shot(page, `detail-${tag}`);

      // 3. 담당자에게 확인 연락: 사람(번호 없음) → 미리 보기(보내지 않음)
      await d.getByRole('button', { name: '담당자에게 확인 연락' }).click();
      await d.getByRole('radio', { name: /최가상/ }).click();
      await expect(d.getByText(DRAFT)).toBeVisible();
      await d.getByText(DRAFT).scrollIntoViewIfNeeded();
      await fits(page);
      if (size.name === 'fhd') await shot(page, `contact-${tag}`);
      expect(posts.map((p) => [new URL(p.url).pathname.replace(`/api/schedules/${sid}/points/`, ''), p.body])).toEqual([
        ['A1510/quotes/business', { what_if: false, retry: false }],
        ['A1510/accel', { days: 3 }],
        ['A1510/contact', { contact_id: 31, channel: 'sms', preview: true }],
      ]);

      // 4. 바뀜 기록 모두 보기(버전마다 묶음, 가정은 점선)
      await w.getByRole('button', { name: '모두 보기' }).click();
      await expect(w.getByRole('region', { name: '버전 7' })).toContainText('빠짐 · 3층 콘크리트 타설 — 끝남');
      await expect(w.getByRole('region', { name: '미리 보기' })).toContainText('여유가 늘어남');
      await fits(page);
      if (size.name === 'fhd') await shot(page, `history-${tag}`);
    });
  }
}

test.describe('phone 390×844', () => {
  test.use({ viewport: { width: 390, height: 844 } });
  for (const theme of ['light', 'dark'] as const) {
    test(`points window on a phone: one week at a time, tap for the detail (${theme})`, async ({ page, request }) => {
      const sid = await officeId(request);
      await fake(page, sid);
      await login(page);
      await expect(page.getByTestId('mobile-shell')).toBeVisible();
      await setTheme(page, theme);
      await pickOffice(page);
      await page.getByRole('navigation', { name: '모바일 탐색' }).getByRole('button', { name: /전체/ }).click();
      await page.getByRole('button', { name: '관리 포인트' }).click();

      const week = (name: string) => page.getByRole('region', { name: `${name} 포인트` });
      await expect(week('이번 주').getByRole('button')).toHaveCount(3);
      await fits(page);
      await shot(page, `phone-${theme}-1-board`);

      await page.getByRole('button', { name: '다음 주', exact: true }).click();
      await expect(week('다음 주').getByRole('button')).toHaveCount(2);
      await week('다음 주').getByRole('button', { name: /커튼월 공장 제작/ }).click();
      const d = page.getByRole('region', { name: '커튼월 공장 제작 자세히' });
      await expect(d.getByRole('list', { name: '여유 흐름' }).getByRole('listitem')).toHaveCount(4);
      await fits(page);
      await shot(page, `phone-${theme}-2-detail`);
      await d.getByRole('button', { name: '‹ 보드' }).click();
      await expect(week('다음 주')).toBeVisible();
    });
  }
});
