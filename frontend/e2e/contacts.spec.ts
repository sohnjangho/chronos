import { expect, test, type APIRequestContext, type Locator, type Page, type Route } from '@playwright/test';

// 계획 4 화면 끝에서 끝까지(Task 107) — PC 1920×1080. 알림 연결 · 연결 진단 → 주소록 CSV 3명 → 허용 번호 밖 문자는 「시험 모드」
// → 체크인 문자 → 답이 그 요청에 이어 → (받는 범위 켬) 자동 답 초안(점선) → [보내기] → 대화의 초안 카드 → [보내기] → 전화 초안 → 걸기
// → 통화 요약·근거 → [결과 확정] → 위임 → [에이전트 발신 · 위임] → 받은 전화 [상대 발신] · 「확인할 보고 1」 → 「모르는 번호」 · 고정 안내
// → 다른 프로젝트는 빈 주소록 → 개발 콘솔: 연락 하네스 격자 [전부 돌리기] · 실행 추적 「연락」 · 진단·사용량. 화면 어디에도 전체 번호가 없다.
//
// 실제 서버(scripts/e2e-local.sh 의 임시 자료, 서버에 CHRONOS_OUTREACH_WORKER=off)가 맡는 것: 로그인·일정·주소록·CSV 가져오기·
// 다른 프로젝트·알림 연결 줄 읽기·권한과 받는 범위 저장·개발 콘솔 격자(칸마다 모래상자 자식 프로세스 — 가짜 통로·음성·LLM).
// 일꾼이 꺼진 서버에는 문자 통로가 없고(보내면 「통로 준비 안 됨」), 제공사·음성 SDK·LLM 을 부를 수 없으므로 **문자·통화·들어온 문자의
// 결과는 브라우저에서 가짜 답**으로 준다(page.route — 서버까지 가지 않는다). 가짜 답의 모양은 서버 끝에서 끝까지
// (backend/tests/e2e/test_outreach_flow.py)가 실제 API 에서 본 것과 같다. 제공사로 나갈 수 있는 길(연결 테스트·진단·음성 모델 목록·
// 음성 진단·카카오 다시 읽기)은 모두 브라우저에서 막는다. 알림 연결 한 줄(가상 키·가상 번호, 시험 모드)은 시험이 임시 DB 에 직접 넣는다.
// 실행: CHRONOS_OUTREACH_WORKER=off bash scripts/e2e-local.sh e2e/contacts.spec.ts

const LOGIN_ID = process.env.E2E_LOGIN_ID ?? 'demo-admin';
const PASSWORD = process.env.E2E_PASSWORD ?? 'demo-pass-e2e';
const OFFICE = '5층 사무동 신축';
const FACTORY = '가상 부품 공장';
const ME = '김공정';
const FULL_NUMBER = /(?:\+82|0)1\d[-. ]?\d{3,4}[-. ]?\d{4}/;
const CSV = '협력사,이름,담당,전화번호,공종\n가람철근,박현장,철근 팀장,010-0000-0199,철근\n가람철근,이반장,철근 반장,010-0000-0198,철근\n'
  + '한빛전기,최전기,전기 과장,010-0000-0197,전기\n';
const T0 = Date.UTC(2026, 10, 27, 1, 0); // 한국 시각 금 10:00

test.use({ actionTimeout: 15_000 });
// 가로챈 읽기가 도는 중에 시험이 끝나면 그 읽기는 버린다.
test.afterEach(async ({ page }) => page.unrouteAll({ behavior: 'ignoreErrors' }));

const win = (page: Page, title: string): Locator => page.locator(`.os-win[aria-label^="${title}"]`);
const dock = (page: Page, name: string): Locator => page.locator(`.os-dock-btn[aria-label="${name}"], .os-dock-btn[aria-label^="${name},"]`);

/** 임시 DB 에 알림 연결 한 줄(시험 모드 · 허용 번호 010-0000-0199)과 음성 설정 — 제공사를 부르지 않고 넣는다. 키·번호는 가상. */
const SEED = `
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.config import Settings
from app.security.crypto import encrypt
from app.store.tables_outreach import NotifyConnection, VoiceSettings
engine = create_engine(f"sqlite:///{Settings().data_dir / 'chronos.db'}")
with Session(engine) as s:
    if s.query(NotifyConnection).count() == 0:
        row = NotifyConnection(name="한국AI통신(가상)", base_url="https://kat.invalid", secret_ciphertext=encrypt("kat-test-key-ZZZZ9999"),
                               secret_last4="9999", account_id="AC00000000003c4d", sender_number="07000000123", is_default=True,
                               status="ok", test_mode=True, allow_numbers_json=["01000000199"])
        s.add(row)
        s.flush()
        s.add(VoiceSettings(connection_id=row.id, provider="google", secret_ciphertext=encrypt("kat-test-key-ZZZZ9999"),
                            secret_last4="9999", model="gemini-3.8-live", agent_number="07000000100",
                            voices_by_language_json={}, status="ok"))
        s.commit()
engine.dispose()
`;

async function seedConnection() {
  // @types/node 없이 타입 검사하므로 이름을 글로 넘긴다(Playwright 는 Node 에서 돈다)
  const cp = (await import('node:child_process' as string)) as { execFileSync: (file: string, args: string[], opts: object) => unknown };
  cp.execFileSync('../backend/.venv/bin/python', ['-c', SEED], { cwd: '../backend', env: process.env, stdio: 'inherit' });
}

// ── 가짜 세상: 문자·통화·들어온 것 ───────────────────────────────────────────

type Row = Record<string, unknown> & { id: number };
const iso = (minutes: number) => new Date(T0 + minutes * 60_000).toISOString();

class World {
  clock = 0;
  sid = 0;
  people: Record<string, number> = {};
  messages: (Row & { contact_id: number })[] = [];
  calls: (Row & { contact_id: number })[] = [];
  transcripts = new Map<number, { role: string; text: string; t: number }[]>();
  reports: Row[] = [];
  unknown: Record<string, unknown>[] = [];
  unknownLines: Row[] = [];
  diagnosis: Record<string, unknown> | null = null;
  private nextId = 1;

  tick(minutes = 2) {
    this.clock += minutes;
    return iso(this.clock);
  }

  message(contactId: number, over: Record<string, unknown>) {
    const row = {
      id: this.nextId++, contact_id: contactId, direction: 'out', channel: 'sms', kind: 'normal', body: '', body_ko: null, has_media: false,
      origin: 'user', origin_name: ME, send_mode: null, approved_by: null, status: 'draft', fail_reason: null, fallback_sms: false,
      template_id: null, reply_to_id: null, activity: null, field_item_id: null, approval_id: null, chat: null, batch: null, events: [],
      scheduled_at: null, sent_at: null, delivered_at: null, created_at: this.tick(), ...over,
    };
    this.messages.push(row);
    return row;
  }

  call(contactId: number, over: Record<string, unknown>) {
    const contact = { id: contactId, name: '박현장', role_title: '철근 팀장', company: '가람철근' };
    const row = {
      id: this.calls.length + 1, contact_id: contactId, direction: 'out', caller_class: null, contact, origin: 'user', origin_name: ME,
      send_mode: null, approved_by: null, status: 'draft', fail_reason: null, purpose: '', questions: [], avoid: [], language: 'ko',
      voice_id: null, duration_s: null, summary_ko: '', result_proposed: '', result_confirmed: null, confirmed_by: null, answers: [],
      events: [], has_recording: false, prev_call_id: null, activity: null, scheduled_at: null, started_at: null, ended_at: null,
      created_at: this.tick(), ...over,
    };
    this.calls.push(row);
    return row;
  }

  find<T extends Row>(rows: T[], id: number): T {
    const row = rows.find((r) => r.id === id);
    if (!row) throw new Error(`가짜 세상에 줄 ${id} 가 없습니다`);
    return row;
  }
}

const GATE_OK = [{ rule: 'channel_choice', verdict: 'allowed', detail: 'sms' }, { rule: 'delivery', verdict: 'allowed', detail: '통로가 받았습니다' }];
const BLOCKED_TEST = '시험 모드라 허용한 번호에만 연락합니다';
const DIAGNOSIS = {
  state: 'done', ran_at: iso(0), by: ME, sent_real: false, sent_unknown: false, sends: [],
  steps: [
    { id: 'P1', label: '인증 + 발신번호 목록', ok: true, skipped: false, detail: '인증됨 · 발신번호 2개(승인 1 · 심사 중 1) · 고른 발신번호는 승인됨', latency_ms: 1, notes: ['[1] GET sender-numbers: HTTP 200 · 1ms'], code: 'ok', maybe_sent: false, pending: false },
    { id: 'P2', label: '시험 문자 1건 보내기', ok: false, skipped: true, detail: '시험 문자를 보내지 않았습니다 — [시험 문자]를 누를 때만 보냅니다.', latency_ms: null, notes: [], code: 'skipped_no_send', maybe_sent: false, pending: false },
    { id: 'P3', label: '보낸 문자 상태 조회', ok: false, skipped: true, detail: '보낸 시험 문자가 없어 확인하지 않았습니다.', latency_ms: null, notes: [], code: 'skipped_no_message', maybe_sent: false, pending: false },
    { id: 'P4', label: '받은 문자 목록', ok: false, skipped: false, detail: '제공사 서버에서 오류가 났습니다.', latency_ms: 0, notes: ['[2] GET messages?status=received: HTTP 500'], code: 'server', maybe_sent: false, pending: false },
  ],
};
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });

/** 브라우저의 /api 요청을 가로챈다: 위 가짜 세상이 맡는 것만 답하고 나머지는 실제 서버로. */
async function fake(page: Page, w: World) {
  await page.route(/\/api\//, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const method = req.method();
    const body = () => (req.postData() ? JSON.parse(req.postData()!) : {});
    let m: RegExpMatchArray | null;

    // 제공사로 나갈 수 있는 길은 서버까지 보내지 않는다
    if ((m = path.match(/^\/api\/notify\/connections\/\d+\/(diagnose|diagnosis)$/))) {
      if (m[1] === 'diagnose') w.diagnosis = { ...DIAGNOSIS, ran_at: w.tick(0) };
      return json(route, w.diagnosis);
    }
    if (/\/voice\/models$/.test(path))
      return json(route, { models: ['gemini-3.8-live'], default: 'gemini-3.8-live', fallback: false, refused: false, no_live: false, reason: null });
    if (/^\/api\/notify\/connections(\/\d+)?\/(test|voice\/diagnose|kakao\/sync)$/.test(path) || (path === '/api/notify/connections/test'))
      return json(route, { code: 'e2e_blocked', message: '시험에서는 제공사를 부르지 않습니다' }, 503);

    // 문자
    if ((m = path.match(/^\/api\/schedules\/\d+\/outreach\/threads\/(\d+)$/)) && method === 'GET') {
      const real = await (await route.fetch()).json();
      const before = Number(url.searchParams.get('before') ?? Infinity);
      const limit = Number(url.searchParams.get('limit') ?? 50);
      const rows = w.messages.filter((r) => r.contact_id === Number(m![1]) && r.id < before).slice(-limit);
      return json(route, { ...real, messages: rows, has_more: false });
    }
    if (/^\/api\/schedules\/\d+\/outreach\/messages$/.test(path) && method === 'POST') {
      const b = body();
      const row = w.message(b.contact_id, { body: b.body, channel: b.channel });
      if (!b.send) return json(route, { message: row, outcome: null });
      if (b.contact_id === w.people['박현장']) Object.assign(row, { status: 'accepted', send_mode: 'manual', events: GATE_OK, sent_at: w.tick(0) });
      else Object.assign(row, { status: 'blocked_test', fail_reason: BLOCKED_TEST, events: [{ rule: 'test_mode', verdict: 'blocked', detail: BLOCKED_TEST }] });
      const outcome = row.status === 'accepted' ? { code: 'accepted', message: '보냈습니다', scheduled_at: null } : { code: 'blocked_test', message: BLOCKED_TEST, scheduled_at: null };
      return json(route, { message: row, outcome });
    }
    if ((m = path.match(/^\/api\/schedules\/\d+\/outreach\/messages\/(\d+)\/send$/))) {
      const row = w.find(w.messages, Number(m[1]));
      const agent = row.origin === 'agent';
      Object.assign(row, { kind: 'normal', status: 'accepted', send_mode: agent ? 'approved' : 'manual', approved_by: agent ? ME : null,
                           fail_reason: null, sent_at: w.tick(0), events: [...(row.events as unknown[]), ...GATE_OK] });
      return json(route, { message: row, outcome: { code: 'accepted', message: '보냈습니다', scheduled_at: null } });
    }

    // 통화
    if (/^\/api\/schedules\/\d+\/outreach\/calls$/.test(path)) {
      if (method === 'GET') {
        const who = Number(url.searchParams.get('contact_id'));
        return json(route, w.calls.filter((c) => c.contact_id === who).reverse());
      }
      const b = body();
      return json(route, w.call(b.contact_id, { purpose: b.purpose, questions: b.questions, avoid: b.avoid, language: b.language ?? 'ko' }));
    }
    if ((m = path.match(/^\/api\/schedules\/\d+\/outreach\/calls\/(\d+)(?:\/(place|confirm))?$/))) {
      const row = w.find(w.calls, Number(m[1]));
      if (m[2] === 'place') {
        Object.assign(row, { status: 'queued', send_mode: 'manual', events: [{ rule: 'channel_choice', verdict: 'allowed', detail: 'call', at: w.tick(0) }] });
        return json(route, { call: row, outcome: { code: 'queued', message: '전화를 걸 차례에 넣었습니다', scheduled_at: null } });
      }
      if (m[2] === 'confirm') {
        Object.assign(row, { result_confirmed: body().result, confirmed_by: ME });
        return json(route, row);
      }
      if (method === 'PATCH') return json(route, Object.assign(row, body()));
      return json(route, { ...row, transcript: w.transcripts.get(row.id) ?? [], reports: [] });
    }

    // 들어온 것: 보고 · 모르는 번호 · 제안
    if (/^\/api\/(schedules\/\d+\/)?outreach\/reports$/.test(path) && method === 'GET')
      return json(route, url.searchParams.get('unassigned') ? [] : w.reports);
    if (path === '/api/outreach/unknown') return json(route, w.unknown);
    if ((m = path.match(/^\/api\/outreach\/unknown\/(\w+)$/)))
      return json(route, { peer_key: m[1], number_masked: '010-****-0188', blocked: false, known: false, lines: w.unknownLines });

    // 대화: 「박현장 팀장에게 철근 반입 시간 물어봐 줘」 → 문자 초안 카드(모델 대신 정해 둔 턴)
    if (/^\/api\/chat\/sessions\/\d+\/messages$/.test(path) && method === 'POST') {
      const draft = w.message(w.people['박현장'], { origin: 'agent', origin_name: '에이전트', body: '박현장 팀장님, 내일 철근 반입 시간 알려 주실 수 있을까요?',
                                                  chat: { id: 1, title: '박현장 팀장에게 철근 반입 시간 물어봐 줘' } });
      const card = { kind: 'outreach_draft', schedule_id: w.sid, message_id: draft.id, contact: { id: w.people['박현장'], name: '박현장', role_title: '철근 팀장', company: '가람철근' },
                     channel: 'sms', body: draft.body, body_ko: null, needs_approval: true };
      const sse = [['text', { text: '박현장 팀장에게 보낼 문자 초안을 만들었습니다. [보내기]를 눌러 주세요.' }], ['card', card], ['done', {}]]
        .map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('');
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: sse });
    }

    // 개발 콘솔의 연락 추적 · 진단 · 사용량(실제 답에 가짜 세상을 얹는다)
    if (path === '/api/devconsole/outreach') return json(route, { items: consoleItems(w) });
    if ((m = path.match(/^\/api\/devconsole\/outreach\/(message|call)\/(\d+)$/))) return json(route, consoleDetail(w, m[1], Number(m[2])));
    if (path === '/api/devconsole/health') {
      const real = await (await route.fetch()).json();
      return json(route, { ...real, notify: { ...real.notify, last_diagnosis: w.diagnosis && { ran_at: w.diagnosis.ran_at, state: 'done',
        steps: DIAGNOSIS.steps.map((s) => ({ ...s, outcome: s.skipped ? 'skipped' : s.ok ? 'ok' : 'failed' })) } } });
    }
    if (path === '/api/devconsole/usage') {
      const real = await (await route.fetch()).json();
      const sent = w.messages.filter((r) => r.direction === 'out' && ['accepted', 'delivered'].includes(String(r.status))).length;
      return json(route, { ...real, outreach: { ...real.outreach, sms: sent, auto_replies: 1,
        calls: { ...real.outreach.calls, calls_placed: 1, calls_answered: 1, call_seconds: 9 } } });
    }
    return route.fallback();
  });
}

function consoleItems(w: World) {
  const book = (id: number) => (id === w.people['이반장'] ? '이반장' : '박현장');
  const messages = w.messages.map((r) => ({ kind: 'message', id: r.id, at: r.created_at, direction: r.direction, channel: 'sms', origin: r.origin,
    origin_name: r.origin_name, send_mode: r.send_mode, caller_class: r.direction === 'in' ? 'contact' : null, status: r.status,
    contact_name: book(r.contact_id), company_name: '가람철근', number_masked: book(r.contact_id) === '이반장' ? '010-****-0198' : '010-****-0199',
    schedule_name: OFFICE, events: (r.events as unknown[]).length, needs_check: false }));
  const calls = w.calls.map((c) => ({ kind: 'call', id: c.id, at: c.created_at, direction: c.direction, channel: 'call', origin: c.origin,
    origin_name: c.origin_name, send_mode: c.send_mode, caller_class: c.caller_class, status: c.status, contact_name: '박현장',
    company_name: '가람철근', number_masked: '010-****-0199', schedule_name: OFFICE, events: (c.events as unknown[]).length, needs_check: false }));
  return [...messages, ...calls].sort((a, b) => String(b.at).localeCompare(String(a.at)));
}

const GROUP_OF: Record<string, [string, string]> = {
  test_mode: ['gate_decision', '나가는 문 판정'], channel_choice: ['gate_decision', '나가는 문 판정'], delivery: ['channel_result', '통로 결과'],
  admission: ['admission', '들어오는 문'], recheck_before_dial: ['call', '통화'],
};

function consoleDetail(w: World, kind: string, id: number) {
  const head = consoleItems(w).find((i) => i.kind === kind && i.id === id)!;
  const row = kind === 'message' ? w.find(w.messages, id) : w.find(w.calls, id);
  const timeline = (row.events as { rule: string; verdict: string; detail: string }[]).map((e, n) => {
    const [group, groupLabel] = GROUP_OF[e.rule] ?? (e.rule.startsWith('tool:') ? ['tool', '도구'] : ['unknown', '알 수 없는 사건']);
    return { seq: n + 1, kind: 'harness', label: e.rule === 'test_mode' ? '시험 모드·허용 번호' : e.rule, started_at: row.created_at, ms: null, model: null,
      input_tokens: 0, output_tokens: 0, cost: null, ok: e.verdict !== 'blocked', error: e.verdict === 'blocked' ? '막음' : null, input_text: '', output_text: '',
      parallel_group: null, signals: [], harness: { group, group_label: groupLabel, rule: e.rule, verdict: e.verdict,
        verdict_label: e.verdict === 'blocked' ? '막음' : '지나감', attempt: 1, order: null, code: null, needs_check: false, unknown: false } };
  });
  return { head: { ...head, approved_by: row.approved_by ?? null, fail_reason: row.fail_reason ?? null, reply_to_id: row.reply_to_id ?? null,
    duration_s: row.duration_s ?? null, transcript_lines: kind === 'call' ? (w.transcripts.get(id)?.length ?? 0) : null },
    timeline, groups: [], attempts: 1, needs_check: 0, omitted: 0, flow: [], branches_lit: [] };
}

// ── 화면 도우미 ────────────────────────────────────────────────────────

async function login(page: Page) {
  await page.goto('/', { waitUntil: 'networkidle' });
  await expect(async () => {
    await page.getByLabel('아이디').fill(LOGIN_ID);
    await page.getByLabel('비밀번호').fill(PASSWORD);
    await page.getByRole('button', { name: '들어가기' }).click();
    await expect(dock(page, '연락처')).toBeVisible({ timeout: 5_000 });
  }).toPass({ timeout: 30_000 });
}

async function pickProject(page: Page, name: string) {
  await page.getByRole('button', { name: /일정 고르기|5층 사무동|가상 부품 공장/ }).first().click();
  await page.getByRole('option', { name: new RegExp(name) }).click();
}

async function shot(page: Page, name: string) {
  const dir = process.env.E2E_SHOTS_DIR || test.info().outputPath('shots');
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${dir}/${name}.png` });
}

async function noFullNumber(page: Page) {
  expect(await page.locator('body').innerText()).not.toMatch(FULL_NUMBER);
}

const bookOf = (w: Locator) => w.getByRole('navigation', { name: '주소록' });
const personIn = (w: Locator, name: string) => bookOf(w).getByRole('button', { name: new RegExp(`^${name}`) }).first();

/** 다른 사람을 눌렀다가 돌아와 대화를 다시 읽게 한다(새로 온 문자를 보려고). */
async function reopen(w: Locator, name: string) {
  await personIn(w, name === '최전기' ? '이반장' : '최전기').click();
  await personIn(w, name).click();
}

interface Flow {
  page: Page;
  world: World;
  request: APIRequestContext;
  auth: { Authorization: string };
}

/** 1~2. 알림 연결 · 연결 진단 → CSV 로 3명 */
async function diagnoseAndImport(f: Flow) {
  const { page, world } = f;
  const settings = win(page, '설정');
  const contacts = win(page, '연락처');
  // 1. 설정 → 알림 연결: 시험 모드 · 허용 번호 · [연결 진단] → OK/FAIL 줄
  await dock(page, '설정').click();
  await settings.getByRole('button', { name: '알림 연결' }).click();
  const card = settings.getByRole('article', { name: /한국AI통신/ });
  await expect(card).toBeVisible();
  await card.getByRole('button', { name: '연결 진단' }).click();
  const diag = settings.getByRole('region', { name: '연결 진단 결과' });
  await expect(diag).toContainText('인증됨 · 발신번호 2개');
  await expect(diag).toContainText('제공사 서버에서 오류가 났습니다.');
  await shot(page, 'c01-settings-diagnosis');
  await noFullNumber(page);

  // 2. 연락처 → CSV 가져오기로 3명
  await dock(page, '연락처').click();
  await expect(contacts.getByRole('status', { name: '알림 연결 상태' })).toContainText('시험 모드 · 허용 번호 1개');
  await bookOf(contacts).getByRole('button', { name: 'CSV 가져오기' }).click();
  const csvDialog = page.getByRole('dialog', { name: 'CSV 가져오기' });
  const buffer = (globalThis as unknown as { Buffer: { from(s: string, enc: string): unknown } }).Buffer.from(CSV, 'utf-8');
  await csvDialog.getByLabel('CSV 파일 고르기').setInputFiles({ name: '협력사.csv', mimeType: 'text/csv', buffer: buffer as never });
  await expect(csvDialog.getByRole('table', { name: '미리 보기' }).getByRole('row')).toHaveCount(4);
  await expect(csvDialog).toContainText('010-****-0199');
  await shot(page, 'c02-csv-preview');
  await csvDialog.getByRole('button', { name: '3명 넣기' }).click();
  await expect(csvDialog.getByText('3명 넣었습니다')).toBeVisible();
  await csvDialog.getByRole('button', { name: '닫기' }).click();
  const book: { companies: { people: { id: number; name: string }[] }[] } =
    await (await f.request.get(`/api/schedules/${world.sid}/contacts`, { headers: f.auth })).json();
  for (const p of book.companies.flatMap((c) => c.people)) world.people[p.name] = p.id;
  expect(Object.keys(world.people).sort()).toEqual(['박현장', '이반장', '최전기']);

}

/** 3~5. 시험 모드 · 체크인과 답 · 자동 답 초안 */
async function texts(f: Flow) {
  const { page, world } = f;
  const settings = win(page, '설정');
  const contacts = win(page, '연락처');
  const log = contacts.getByRole('log', { name: '문자 · 카카오톡 대화' });
  const input = contacts.getByRole('region', { name: '메시지 입력' });
  // 3. 허용 번호가 아닌 사람에게 문자 → 시험 모드로 보내지 않음
  await personIn(contacts, '이반장').click();
  await input.getByRole('textbox', { name: '보낼 글' }).fill('내일 철근 반입 가능하신가요?');
  await input.getByRole('button', { name: '보내기' }).click();
  await expect(contacts).toContainText(BLOCKED_TEST);
  await expect(log.getByRole('article').filter({ hasText: '내일 철근 반입 가능하신가요?' })).toContainText('시험 모드로 보내지 않음');
  await shot(page, 'c03-blocked-test');

  // 4. 허용 번호 사람에게 체크인 문자 → 도착 → 답이 그 요청에 이어 대화에
  await personIn(contacts, '박현장').click();
  await input.getByRole('textbox', { name: '보낼 글' }).fill('내일 오전 철근 반입 예정대로인가요?');
  await input.getByRole('button', { name: '보내기' }).click();
  await expect(log).toContainText('내일 오전 철근 반입 예정대로인가요?');
  const checkin = world.messages.at(-1)!;
  Object.assign(checkin, { status: 'delivered', delivered_at: world.tick(), events: [...(checkin.events as unknown[]),
    { rule: 'delivery_update', verdict: 'allowed', detail: 'delivered' }] });
  world.message(world.people['박현장'], { direction: 'in', origin: 'peer', origin_name: '', body: '네 예정대로 9시에 들어갑니다', status: 'received',
    reply_to_id: checkin.id, sent_at: world.tick(0), events: [{ rule: 'admission', verdict: 'blocked', detail: 'inbound_off' }] });
  await reopen(contacts, '박현장');
  await expect(log).toContainText('네 예정대로 9시에 들어갑니다');
  await expect(log).toContainText('[상대 발신]');
  await expect(log).toContainText('보낸 글에 대한 답');
  await shot(page, 'c04-reply-linked');

  // 5. 받는 범위 켬(설정 — 실제 서버에 저장) → 자동 답 초안이 점선 말풍선으로 → [보내기]
  await dock(page, '설정').click();
  await settings.getByRole('radiogroup', { name: '받는 범위' }).getByRole('radio', { name: '주소록에 있는 번호만' }).check();
  const rangeConfirm = settings.getByRole('group', { name: '받는 범위 바꾸기 확인' });
  await expect(rangeConfirm).toContainText('주소록');
  await shot(page, 'c05-receive-scope-confirm');
  await rangeConfirm.getByRole('button', { name: '바꾸기' }).click();
  await expect.poll(async () => (await (await f.request.get('/api/notify/connections', { headers: f.auth })).json())[0].inbound_mode).toBe('known');
  const question = world.message(world.people['박현장'], { direction: 'in', origin: 'peer', origin_name: '', body: '하차 장소는 어디로 하면 될까요?',
    status: 'received', reply_to_id: checkin.id, events: [{ rule: 'admission', verdict: 'allowed', detail: 'known_caller' }] });
  world.message(world.people['박현장'], { kind: 'auto_reply', origin: 'agent', origin_name: 'AI 비서', body: '네, 9시 반입으로 알겠습니다. 감사합니다.',
    status: 'draft', fail_reason: '사람의 승인이 필요합니다', reply_to_id: question.id,
    events: [{ rule: 'permission', verdict: 'blocked', detail: '사람의 승인이 필요합니다' }] });
  await dock(page, '연락처').click();
  await reopen(contacts, '박현장');
  const autoDraft = log.getByRole('article').filter({ hasText: '네, 9시 반입으로 알겠습니다' });
  await expect(autoDraft).toBeVisible();
  await expect(autoDraft).toContainText('들어온 문자에 대한 답 초안');
  expect(await autoDraft.evaluate((e) => getComputedStyle(e).borderStyle)).toBe('dashed'); // 점선 말풍선
  await shot(page, 'c06-auto-reply-draft');
  await autoDraft.getByRole('button', { name: '보내기' }).click();
  await expect(log.getByRole('article', { name: /\[에이전트 발신\] · 김공정 승인/ }).filter({ hasText: '9시 반입으로 알겠습니다' })).toBeVisible();

}

/** 6~7. 대화의 초안 카드 · 전화 초안과 통화 */
async function chatAndCall(f: Flow) {
  const { page, world } = f;
  const contacts = win(page, '연락처');
  const callLog = contacts.getByRole('log', { name: '통화 기록' });
  // 6. 대화: 「박현장 팀장에게 철근 반입 시간 물어봐 줘」 → 초안 카드 → [보내기] → [에이전트 발신] · 김공정 승인
  await dock(page, '에이전트 대화').click();
  const chat = win(page, '에이전트 대화');
  await chat.getByRole('textbox').first().fill('박현장 팀장에게 철근 반입 시간 물어봐 줘');
  await chat.getByRole('button', { name: '보내기' }).click();
  const draftCard = chat.getByRole('region', { name: '문자 초안' });
  await expect(draftCard).toContainText('박현장 팀장님, 내일 철근 반입 시간 알려 주실 수 있을까요?');
  await expect(draftCard).toContainText('승인 받기');
  await shot(page, 'c07-chat-draft-card');
  await draftCard.getByRole('button', { name: '보내기' }).click();
  await expect(draftCard).toContainText('[에이전트 발신] · 김공정 승인');
  await shot(page, 'c08-chat-draft-sent');

  // 7. 전화 초안 → 걸기 창 → (가짜) 통화 → 받아쓰기·요약·근거 → [결과 확정]
  await dock(page, '연락처').click();
  await contacts.getByRole('tab', { name: /통화/ }).click();
  await contacts.getByRole('button', { name: '전화 걸기' }).click();
  const callDialog = page.getByRole('dialog', { name: '전화 걸기' });
  await callDialog.getByRole('textbox', { name: '통화 목적' }).fill('내일 철근 반입 시간 확인');
  await callDialog.getByRole('textbox', { name: '물어볼 것' }).fill('내일 철근 반입 시각');
  await callDialog.getByRole('textbox', { name: '말하지 않을 것' }).fill('계약·금액');
  await callDialog.getByRole('button', { name: '저장' }).click();
  await expect(callDialog).toContainText('① 내일 철근 반입 시각');
  await shot(page, 'c09-call-dialog');
  await callDialog.getByRole('button', { name: '전화 걸기' }).click();
  await expect(callDialog.getByRole('status')).toHaveText('전화를 걸 차례에 넣었습니다');
  const placed = world.calls[0];
  expect(placed.status).toBe('queued');
  // (가짜) 통화가 끝났다 — 서버 끝에서 끝까지의 SimulatedVoice 통화와 같은 결과
  Object.assign(placed, { status: 'completed', duration_s: 5, started_at: world.tick(), ended_at: world.tick(0),
    summary_ko: '박현장 팀장이 내일 오전 9시에 철근이 들어온다고 답했습니다.', result_proposed: '내일 09:00 반입',
    answers: [{ question: '내일 철근 반입 시각', answer: '오전 9시', quote: '철근은 내일 오전 9시에 들어옵니다', quote_found: true }],
    events: [...(placed.events as unknown[]), { rule: 'recheck_before_dial', verdict: 'allowed', detail: 'ok', at: world.tick(0) },
      { rule: 'tool:record_answer', verdict: 'allowed', detail: '답을 적음', at: world.tick(0) }] });
  world.transcripts.set(placed.id, [
    { role: 'agent', text: '안녕하세요, 5층 사무동 신축 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다. 박현장님 맞으신가요?', t: 0 },
    { role: 'peer', text: '네 박현장입니다', t: 1 }, { role: 'peer', text: '철근은 내일 오전 9시에 들어옵니다', t: 3 },
    { role: 'agent', text: '네 오전 9시로 전하겠습니다', t: 5 }]);
  await callDialog.getByRole('button', { name: '닫기' }).click();
  await contacts.getByRole('tab', { name: '문자 · 카카오톡' }).click();
  await contacts.getByRole('tab', { name: /통화/ }).click();
  const callCard = callLog.getByRole('article').filter({ hasText: '내일 오전 9시에 철근이 들어온다고' });
  await expect(callCard).toBeVisible();
  await expect(callCard.getByRole('list', { name: '질문별 답' })).toContainText('근거 「철근은 내일 오전 9시에 들어옵니다」');
  await expect(callCard).toContainText('결과: 내일 09:00 반입 (에이전트 제안 · 확정 전)');
  await callCard.getByRole('button', { name: '받아쓰기 보기' }).click();
  await expect(contacts).toContainText('이 통화는 기록됩니다');
  await callCard.getByRole('button', { name: '결과 확정' }).click();
  await callCard.getByRole('textbox', { name: '확정할 결과' }).fill('내일 09:00 반입 확정');
  await callCard.getByRole('button', { name: '확정' }).click();
  await expect(callLog.getByRole('article').first()).toContainText('김공정 확정');
  await shot(page, 'c10-call-summary-confirmed');

}

/** 8~11. 위임 · 받은 전화 · 모르는 번호 · 다른 프로젝트 */
async function delegateAndInbound(f: Flow) {
  const { page, world } = f;
  const settings = win(page, '설정');
  const contacts = win(page, '연락처');
  const log = contacts.getByRole('log', { name: '문자 · 카카오톡 대화' });
  const callLog = contacts.getByRole('log', { name: '통화 기록' });
  // 8. 위임으로 바꾼 뒤(설정 — 실제 서버에 저장) 에이전트가 직접 → [에이전트 발신 · 위임]
  await dock(page, '설정').click();
  await settings.getByRole('radiogroup', { name: '문자 발송 권한' }).getByRole('radio', { name: '위임' }).click();
  const delegate = settings.getByRole('group', { name: '위임 확인' });
  await expect(delegate).toContainText('사람 확인 없이');
  await shot(page, 'c11-delegate-confirm');
  await delegate.getByRole('button', { name: '위임으로 바꾸기' }).click();
  await expect.poll(async () => (await (await f.request.get('/api/notify/connections', { headers: f.auth })).json())[0].agent_sms).toBe('delegate');
  world.message(world.people['박현장'], { origin: 'agent', origin_name: '에이전트', body: '내일 하차는 2번 게이트로 부탁드립니다.', status: 'accepted',
    send_mode: 'delegated', sent_at: world.tick(0), events: GATE_OK, chat: { id: 1, title: '박현장 팀장에게 철근 반입 시간 물어봐 줘' } });
  await dock(page, '연락처').click();
  await contacts.getByRole('tab', { name: '문자 · 카카오톡' }).click();
  await reopen(contacts, '박현장');
  await expect(log.getByRole('article', { name: /\[에이전트 발신 · 위임\]/ })).toContainText('2번 게이트');
  await shot(page, 'c12-delegated');

  // 9. 받는 통화(가짜 Ring) → [상대 발신] · 보고
  const ring = world.call(world.people['박현장'], { direction: 'in', caller_class: 'contact', origin: 'peer', origin_name: '', status: 'completed',
    duration_s: 4, started_at: world.tick(), ended_at: world.tick(0), summary_ko: '박현장 팀장이 철근 반입이 내일 오후 2시로 늦어진다고 알렸습니다.',
    result_proposed: '철근 반입 지연 보고', events: [{ rule: 'admission', verdict: 'allowed', detail: 'known_caller', at: world.tick(0) },
      { rule: 'tool:report_from_contact', verdict: 'allowed', detail: '보고 남김', at: world.tick(0) }] });
  world.transcripts.set(ring.id, [{ role: 'agent', text: '안녕하세요, ChronOS AI 비서입니다. 이 통화는 기록됩니다.', t: 0 },
    { role: 'peer', text: '철근 반입이 내일 오후 2시로 늦어집니다', t: 2 }]);
  world.reports.push({ id: 1, schedule_id: world.sid, medium: 'call', kind: 'delay', text: '철근 반입 내일 오후 2시로 지연',
    quote: '철근 반입이 내일 오후 2시로 늦어집니다', quote_found: true, status: 'open', contact_id: world.people['박현장'], contact_name: '박현장',
    peer_masked: null, peer_key: null, message_id: null, call_id: ring.id, draft_id: null, created_at: world.tick(0), reviewed_by: null, reviewed_at: null });
  await contacts.getByRole('tab', { name: /통화/ }).click();
  await expect(callLog.getByRole('article', { name: /\[상대 발신\] 받은 전화/ })).toContainText('오후 2시로 늦어진다고');
  await shot(page, 'c13-inbound-call');

  // 10. 모르는 번호의 문자 → 「모르는 번호」 묶음 · 고정 안내(일정 내용 없음)
  world.unknown.push({ peer_key: 'b4f20fbac1ff', number_masked: '010-****-0188', last_at: world.tick(), messages: 2, calls: 0,
    last_line: '담당자가 확인 후 연락드리겠습니다.', last_kind: 'message', last_direction: 'out', blocked: false, known: false, shared: false });
  world.unknownLines.push(
    { kind: 'message', id: 90, direction: 'in', at: world.tick(0), text: '거기 현장 사무실 맞나요?', status: 'received', message_kind: 'normal',
      events: [{ rule: 'admission', verdict: 'allowed', detail: 'unknown_accepted' }], caller_class: 'unknown', fail_reason: null, duration_s: null },
    { kind: 'message', id: 91, direction: 'out', at: world.tick(), text: '담당자가 확인 후 연락드리겠습니다.', status: 'accepted', message_kind: 'notice',
      events: GATE_OK, caller_class: null, fail_reason: null, duration_s: null });

  // 11. 다른 프로젝트로 바꾸면 주소록이 비어 있음(실제 서버) — 돌아오면 「확인할 보고 1」·「모르는 번호」가 보인다
  await pickProject(page, FACTORY);
  await expect(win(page, '연락처')).toHaveAttribute('aria-label', /가상 부품 공장/);
  await expect(bookOf(contacts)).toContainText('아직 주소록이 비어 있습니다');
  await shot(page, 'c14-other-project-empty');
  await pickProject(page, OFFICE);
  await expect(contacts.getByRole('button', { name: /확인할 보고/ })).toHaveText('확인할 보고 1');
  await contacts.getByRole('button', { name: /확인할 보고/ }).click();
  await expect(contacts.getByRole('region', { name: '확인할 보고' })).toContainText('철근 반입 내일 오후 2시로 지연');
  await shot(page, 'c15-report');
  const unknownGroup = contacts.getByRole('group', { name: '모르는 번호 · 대표번호 1' });
  await unknownGroup.getByRole('button', { name: /010-\*\*\*\*-0188/ }).click();
  const peer = contacts.getByRole('region', { name: '모르는 번호 010-****-0188' });
  await expect(peer.getByRole('list', { name: '주고받은 줄' })).toContainText('거기 현장 사무실 맞나요?');
  await expect(peer.getByRole('list', { name: '주고받은 줄' })).toContainText('담당자가 확인 후 연락드리겠습니다.');
  await shot(page, 'c16-unknown-number');
  await noFullNumber(page);

}

/** 12. 개발 콘솔 */
async function devConsole(f: Flow) {
  const { page } = f;
  // 12. 개발 콘솔: 연락 하네스 격자 [전부 돌리기](실제 서버 — 칸마다 모래상자 자식 프로세스) · 실행 추적 「연락」 · 진단 · 사용량
  await dock(page, '개발 콘솔').click();
  const dev = win(page, '개발 콘솔');
  await dev.getByRole('tab', { name: '하네스·차단 시험' }).click();
  await dev.getByRole('group', { name: '하네스 묶음 필터' }).getByRole('button', { name: '연락 하네스 96' }).click();
  const grid = dev.getByRole('region', { name: '연락 하네스' });
  await grid.getByRole('button', { name: '전부 돌리기' }).click();
  const progress = grid.getByRole('status', { name: '격자 진행' });
  await expect(progress).toContainText('아직 안 돌림 0', { timeout: 180_000 });
  await expect(progress).toHaveText('통과 93 · 실패 3 · 아직 안 돌림 0'); // 실패 셋은 「하네스 갈라짐」 표시 칸(S-13 둘 · S-20 받기)
  await shot(page, 'c17-devconsole-grid');

  await dev.getByRole('tab', { name: '실행 추적' }).click();
  await dev.getByRole('button', { name: '요청 고르기' }).click();
  await dev.getByRole('radiogroup', { name: '기록 종류' }).getByRole('radio', { name: '연락' }).click();
  const picker = dev.getByRole('dialog', { name: '요청 고르기' });
  await expect(picker.getByRole('button', { name: /이반장 · 가람철근 시험 모드로 보내지 않음/ })).toBeVisible();
  await shot(page, 'c18-devconsole-outreach-list');
  await picker.getByRole('button', { name: /이반장 · 가람철근 시험 모드로 보내지 않음/ }).click();
  const trace = dev.getByRole('tabpanel', { name: '실행 추적' });
  await expect(trace.getByRole('group', { name: '이 연락' })).toContainText('시험 모드로 보내지 않음');
  await expect(trace.getByRole('list', { name: '실행 추적' })).toContainText('나가는 문 판정');
  await expect(trace.getByRole('list', { name: '실행 추적' })).toContainText('막음');
  await shot(page, 'c19-devconsole-trace-gate');
  await noFullNumber(page);

  await dev.getByRole('tab', { name: '시스템 진단' }).click();
  const notifyHealth = dev.getByRole('article', { name: '알림 연결' });
  await expect(notifyHealth.getByRole('list', { name: '마지막 연결 진단' })).toContainText(/P1\s*인증 \+ 발신번호 목록\s*정상/);
  await expect(notifyHealth.getByRole('list', { name: '마지막 연결 진단' })).toContainText(/P4\s*받은 문자 목록\s*실패/);
  await expect(notifyHealth).toContainText('주소록에 있는 번호만');
  await expect(notifyHealth).toContainText('문자 위임');
  await shot(page, 'c20-devconsole-health');
  await noFullNumber(page);

  await dev.getByRole('tab', { name: '사용량·비용' }).click();
  await expect(dev.getByRole('table', { name: '연락 사용량' }).getByRole('row', { name: /문자 \(단문·장문\) 4/ })).toBeVisible();
  await shot(page, 'c21-devconsole-usage');
  await noFullNumber(page);
}

test('plan 4: contacts · texts · AI calls end to end (fake provider, fake voice)', async ({ page, request }) => {
  test.setTimeout(300_000);
  const world = new World();
  await seedConnection();
  const token = (await (await request.post('/api/auth/login', { data: { login_id: LOGIN_ID, password: PASSWORD } })).json()).token;
  const auth = { Authorization: `Bearer ${token}` };
  expect((await request.patch('/api/auth/me', { headers: auth, data: { name: ME } })).ok()).toBe(true);
  const schedules: { id: number; name: string }[] = await (await request.get('/api/schedules', { headers: auth })).json();
  world.sid = schedules.find((s) => s.name === OFFICE)!.id;
  await fake(page, world);
  await login(page);
  await pickProject(page, OFFICE);
  const flow: Flow = { page, world, request, auth };
  await diagnoseAndImport(flow);
  await texts(flow);
  await chatAndCall(flow);
  await delegateAndInbound(flow);
  await devConsole(flow);
});
