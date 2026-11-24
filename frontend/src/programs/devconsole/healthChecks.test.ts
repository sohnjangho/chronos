// 시스템 진단 대응표(시안 A): 서버 응답의 칸 하나하나 → {영역, 쉬운 이름, 상태 넷(정상·확인 필요·실패·모름), 한 줄 요약, 할 일, 지금 상태, 영향, 기계 출력}.
import { describe, expect, test } from 'vitest';
import type { HealthOut } from './devApi';
import { AREAS, buildChecks, firstLook, MAPPED, type Check } from './healthChecks';
import { kakaoHealth, notifyHealth, voiceHealth } from './testKit';

/** 지금 서버가 보내는 모든 칸(선택 칸 포함). 서버 응답에 칸이 늘면 이 꼴이 타입 검사에서 깨진다 → MAPPED 에 더한다. */
const FULL: Required<HealthOut> = {
  llm: { status: 'ok', connections_count: 3, assignments_count: 6, default_name: 'Liner 기본', default_provider: 'liner', default_base_url: 'https://api.example.invalid', key_ready: true, message: '기본 연결 및 인증 키 준비됨' },
  qdrant: { status: 'error', collections: [], points_count: 0, latency_ms: 3004, message: 'Qdrant 서버에 연결할 수 없습니다.' },
  search: { status: 'ok', ready: true, calls_7d: 41, failed_7d: 2, message: 'Liner Search/MCP 준비됨' },
  db: { status: 'ok', size_bytes: 18_350_080, counts: { chats: 128, files: 212, approvals: 3, mystery: 9 } },
  active_turns: [{ chat_session_id: 214, title: '한빛 3공구 골조 지연 만회안', stop_requested: false }],
  info_api: {
    status: 'warn', count: 3, message: '연결 3개 · 마지막 연결 시험 실패 1개',
    connections: [
      { id: 1, name: '기상청 단기예보', kind: 'kma', status: 'ok', checked_at: '2026-11-24T04:10:00+00:00' },
      { id: 2, name: '건설기계 대여 시세', kind: 'generic', status: 'failed', checked_at: '2026-11-24T03:55:00+00:00' },
      { id: 3, name: '자재 단가 조회', kind: 'generic', status: 'unknown', checked_at: null },
    ],
  },
  evidence_reuse: { reusable: 184, reused_7d: 23, searches_7d: 41, days: 30 },
  holidays: { status: 'ok', years: [2025, 2026, 2027], counts: { 2025: 19, 2026: 18, 2027: 17 }, message: '공휴일 표 있음' },
  vision: { status: 'ok', model: 'gpt-5.2-mini', connection_name: 'OpenAI 그림', stored: true, key_ready: true, message: '그림 읽기 모델 준비됨' },
  notify: notifyHealth({ needs_check: 2, kakao: kakaoHealth({ ready: true, available: true }), voice: voiceHealth({ status: 'unknown', checked_at: null, last_diagnosis: null }) }),
  presence: { online_users: 3, online_devices: 5 },
};
const FETCHED = new Date('2026-11-24T05:46:00Z');
const byId = (cs: Check[], id: string) => cs.find((c) => c.id === id)!;

describe('대응표', () => {
  test('every field of the health response maps to at least one check (a new field must be added to MAPPED)', () => {
    const checks = buildChecks(FULL, FETCHED);
    const sources = new Set(checks.map((c) => c.source));
    for (const key of Object.keys(FULL)) expect(sources, key).toContain(key);
    expect(Object.keys(MAPPED).sort()).toEqual(Object.keys(FULL).sort());
    // notify 안의 카카오톡 · AI 전화도 저마다 한 줄
    expect(sources).toContain('notify.kakao');
    expect(sources).toContain('notify.voice');
  });

  test('every check has a known area, a plain name, one of the four states (or info for live rows) and its raw output', () => {
    for (const c of buildChecks(FULL, FETCHED)) {
      expect(AREAS.map((a) => a.id)).toContain(c.area);
      expect(c.name.length).toBeGreaterThan(0);
      expect(['ok', 'check', 'fail', 'unknown', 'info']).toContain(c.state);
      expect(c.summary.length).toBeGreaterThan(0);
      expect(c.raw).toBeDefined();
    }
  });

  test('nine old status words collapse to four: error/failed → 실패, warn/off/needs-check → 확인 필요, unknown → 모름', () => {
    const cs = buildChecks(FULL, FETCHED);
    expect(byId(cs, 'qdrant').state).toBe('fail');
    expect(byId(cs, 'info_api').state).toBe('check');
    expect(byId(cs, 'notify').state).toBe('check'); // 연결은 정상이지만 보냈는지 모르는 문자 2건
    expect(byId(cs, 'voice').state).toBe('unknown');
    expect(byId(cs, 'llm').state).toBe('ok');
    expect(byId(cs, 'evidence_reuse').state).toBe('ok'); // 예전 「30일」 배지는 상태가 아니다
    const off = buildChecks({ ...FULL, qdrant: { ...FULL.qdrant, status: 'off' } }, FETCHED);
    expect(byId(off, 'qdrant').state).toBe('check');
  });

  test('fields: nothing the old cards showed is lost (unknown db counts keep their key, base url is shown)', () => {
    const cs = buildChecks(FULL, FETCHED);
    const flat = (c: Check) => c.fields.flatMap((g) => g.rows.map(([k, v]) => `${k}=${v}`));
    expect(flat(byId(cs, 'llm'))).toContain('주소=https://api.example.invalid');
    expect(flat(byId(cs, 'db'))).toContain('mystery=9');
    expect(flat(byId(cs, 'db'))).toContain('대화 세션=128');
    expect(byId(cs, 'notify').steps?.diag.steps.map((s) => s.id)).toEqual(['P1', 'P2', 'P3', 'P4']);
    expect(byId(cs, 'notify').fields.find((g) => g.title === '조회 일꾼')).toBeDefined();
    expect(byId(cs, 'voice').fields.find((g) => g.title === '통화 일꾼')).toBeDefined();
  });

  test('last checked: the server time where the server keeps one, otherwise the time the diagnosis was fetched', () => {
    const cs = buildChecks(FULL, FETCHED);
    expect(byId(cs, 'llm').checkedAt).toEqual({ at: FETCHED.toISOString(), server: false });
    expect(byId(cs, 'notify').checkedAt).toEqual({ at: FULL.notify!.checked_at, server: true });
    expect(byId(cs, 'info_api').checkedAt).toEqual({ at: '2026-11-24T04:10:00+00:00', server: true });
    expect(byId(cs, 'voice').checkedAt).toEqual({ at: null, server: true }); // 아직 진단 안 함 → 「—」
  });

  test('an older server without the optional fields only gets the old rows', () => {
    const { llm, qdrant, search, db, active_turns } = FULL;
    const ids = buildChecks({ llm, qdrant, search, db, active_turns }, FETCHED).map((c) => c.id);
    expect(ids.sort()).toEqual(['active_turns', 'db', 'llm', 'qdrant', 'search']);
  });

  test('a field the screen does not know yet lands in 기타 with its raw output (never silently dropped)', () => {
    const odd = { ...FULL, backup: { status: 'error', message: '백업 실패' } } as unknown as HealthOut;
    const c = byId(buildChecks(odd, FETCHED), 'backup');
    expect(c.area).toBe('other');
    expect(c.state).toBe('fail');
    expect(c.raw).toEqual({ status: 'error', message: '백업 실패' });
  });

  test('no notify connection is 확인 필요 (texts and calls do not go out); a kakao without channel is 정상 · 쓰지 않음', () => {
    const cs = buildChecks({ ...FULL, notify: { ...notifyHealth(), connected: false } }, FETCHED);
    expect(byId(cs, 'notify').state).toBe('check');
    expect(byId(cs, 'notify').summary).toContain('알림 연결이 없습니다');
    const k = buildChecks({ ...FULL, notify: notifyHealth({ kakao: kakaoHealth({ channel: null }) }) }, FETCHED);
    expect(byId(k, 'kakao').state).toBe('ok');
    expect(byId(k, 'kakao').summary).toContain('쓰지 않음');
  });
});

describe('먼저 볼 것', () => {
  test('실패 → 확인 필요 → 모름, info and ok rows left out', () => {
    const rows = firstLook(buildChecks(FULL, FETCHED));
    expect(rows.map((c) => c.state)).toEqual(['fail', 'check', 'check', 'unknown']);
    expect(rows.map((c) => c.id)).toEqual(['qdrant', 'notify', 'info_api', 'voice']); // 같은 상태는 영역 차례(AI·검색 → 문자·카카오톡·전화 → 자료)
    for (const r of rows) expect(r.todo).toBeTruthy();
  });
});
