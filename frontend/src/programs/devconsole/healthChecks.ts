// 시스템 진단 대응표(시안 A — 2026-11-24 설계): 서버 응답(/api/devconsole/health)은 그대로 두고, 화면 쪽에서만
// 칸 하나하나를 {영역, 쉬운 이름 + 작은 기술 이름, 상태 넷(정상·확인 필요·실패·모름), 한 줄 요약, 할 일, 지금 상태, 영향, 기계 출력}으로 옮긴다.
// 예전 상태 말 9가지(정상·오류·주의·꺼짐·실패·모름·확인 필요·쓸 수 있음·아직 진단 안 함)를 넷으로 모은다. 접속·실행 중 턴은 상태가 아니라 info.
// 이 표가 모르는 칸이 서버에 생기면 「기타」 줄로 보인다(조용히 버리지 않는다). 기계 출력(raw)에는 그 칸 전체가 그대로 남는다.
import type { HealthOut } from './devApi';
import { kakao, notify, voice } from './healthContact';
import { AREAS, type AreaId, bytesText, type Check, type CheckState, fromStatus, n, RANK, TEST_WORD, when } from './healthModel';

export { AREAS, STATES, stateLabel, when } from './healthModel';
export type { AreaId, Check, CheckState, KvGroup } from './healthModel';

/** 서버 칸 → 대응. 서버 응답에 칸이 늘면 healthChecks.test 가 여기에 더하라고 깨진다. */
export const MAPPED: Record<keyof Required<HealthOut>, AreaId> = {
  llm: 'ai',
  search: 'ai',
  evidence_reuse: 'ai',
  vision: 'ai',
  qdrant: 'ai',
  notify: 'contact',
  db: 'data',
  holidays: 'data',
  info_api: 'data',
  presence: 'live',
  active_turns: 'live',
};

const DB_LABELS: Record<string, string> = {
  users: '사용자',
  schedules: '프로젝트 일정',
  chats: '대화 세션',
  workflow_runs: '워크플로우 실행',
  files: '자료함 파일',
  approvals: '승인 대기',
  reports: '보고서',
  skills: '저장 스킬',
};
const INFO_KIND: Record<string, string> = { generic: '범용', kma: '기상청 전용' };

function llm(h: HealthOut, at: Check['checkedAt']): Check {
  const l = h.llm;
  const state = fromStatus(l.status) ?? 'unknown';
  return {
    id: 'llm', source: 'llm', area: 'ai', name: 'AI 모델 연결', tech: 'LLM', state,
    summary: l.default_name
      ? `기본 「${l.default_name}」 · 키 ${l.key_ready ? '준비됨' : '읽지 못함'} · 연결 ${l.connections_count} · 배정 ${l.assignments_count}`
      : l.message,
    todo: state === 'ok' ? null : '설정 → AI 모델 연결에서 기본 연결과 키 확인',
    impact: '대화 · 공정표 · 보고서 등 AI 가 답하는 모든 일이 이 연결을 씁니다.',
    fields: [{ title: '지금 상태', rows: [
      ['서버 말', l.message], ['기본 연결', l.default_name ?? '—'], ['제공자', l.default_provider ?? '—'], ['주소', l.default_base_url ?? '—'],
      ['키', l.key_ready ? '준비됨' : '읽지 못함'], ['등록 연결 / 배정', `${l.connections_count}개 / ${l.assignments_count}개`],
    ] }],
    raw: l, checkedAt: at,
  };
}

function qdrant(h: HealthOut, at: Check['checkedAt']): Check {
  const q = h.qdrant;
  const state = fromStatus(q.status) ?? 'unknown';
  const summary = q.status === 'ok'
    ? `모음 ${q.collections.length}개 · 벡터 ${n(q.points_count)}건${q.latency_ms !== null ? ` · ${q.latency_ms}ms` : ''}`
    : q.status === 'off' ? `꺼 둠 — 자료함 뜻 검색 없이 낱말 검색만 됩니다 · ${q.message}` : `${q.message}${q.latency_ms !== null ? `(${(q.latency_ms / 1000).toFixed(1)}초 기다림)` : ''} — 뜻 검색이 멈추고 낱말 검색만 됩니다`;
  return {
    id: 'qdrant', source: 'qdrant', area: 'ai', name: '벡터 검색 서버', tech: 'Qdrant', state, summary,
    todo: q.status === 'error' ? '벡터 검색 서버가 켜져 있는지 확인' : q.status === 'off' ? '쓰려면 서버 설정 CHRONOS_QDRANT_URL 을 채움' : null,
    impact: '자료함 찾기 · 근거 찾기에서 뜻이 비슷한 글을 찾습니다. 멈추면 낱말이 같은 글만 찾습니다.',
    fields: [{ title: '지금 상태', rows: [
      ['서버 말', q.message], ['연결', q.status === 'ok' ? '됨' : q.status === 'off' ? '꺼 둠' : '안 됨'],
      ['기다린 시간', q.latency_ms !== null ? `${n(q.latency_ms)}ms` : '—'],
      ['모음(컬렉션)', q.collections.length ? q.collections.join(', ') : q.status === 'ok' ? '없음' : '읽지 못함'], ['벡터 점 수', n(q.points_count)],
    ] }],
    raw: q, checkedAt: at,
  };
}

function search(h: HealthOut, at: Check['checkedAt']): Check {
  const s = h.search;
  const state = fromStatus(s.status) ?? 'unknown';
  return {
    id: 'search', source: 'search', area: 'ai', name: '근거 검색', tech: 'Liner · MCP', state,
    summary: s.ready ? `최근 7일 ${n(s.calls_7d)}회 · 실패 ${n(s.failed_7d)}건` : s.message,
    todo: state === 'ok' ? null : '설정 → AI 모델 연결에서 Liner 키 확인',
    impact: '보고서 · 답변에 붙는 외부 근거(웹 · 학술 · 법령)를 찾습니다.',
    fields: [{ title: '지금 상태', rows: [
      ['서버 말', s.message], ['상태', s.ready ? '준비됨' : '미연결'], ['최근 7일 호출', `${n(s.calls_7d)}회`], ['최근 7일 실패', `${n(s.failed_7d)}건`],
    ] }],
    raw: s, checkedAt: at,
  };
}

function db(h: HealthOut, at: Check['checkedAt']): Check {
  const d = h.db;
  const c = d.counts;
  const pick = ([k, label]: [string, string]) => (k in c ? `${label} ${n(c[k])}` : null);
  return {
    id: 'db', source: 'db', area: 'data', name: '저장소', tech: 'SQLite', state: fromStatus(d.status) ?? 'unknown',
    summary: [bytesText(d.size_bytes), ...[['chats', '대화'], ['files', '파일'], ['approvals', '승인 대기']].map((p) => pick(p as [string, string]))].filter(Boolean).join(' · '),
    todo: null,
    impact: '일정 · 대화 · 파일 · 승인 등 모든 자료가 이 파일에 있습니다.',
    fields: [{ title: '지금 상태', rows: [['파일 크기', bytesText(d.size_bytes)], ...Object.entries(c).map(([k, v]) => [DB_LABELS[k] ?? k, n(v)] as [string, string])] }],
    raw: d, checkedAt: at,
  };
}

function infoApi(h: HealthOut): Check | null {
  const i = h.info_api;
  if (!i) return null;
  const failed = i.connections.filter((c) => c.status === 'failed');
  const untested = i.connections.filter((c) => c.status !== 'ok' && c.status !== 'failed');
  const times = i.connections.map((c) => c.checked_at).filter((t): t is string => !!t).sort();
  const state: CheckState = i.status === 'off' ? 'ok' : (fromStatus(i.status) ?? 'unknown');
  const parts = [
    ...failed.map((c) => `「${c.name}」 연결 시험 실패`),
    ...untested.map((c) => `「${c.name}」 시험 안 함`),
  ];
  return {
    id: 'info_api', source: 'info_api', area: 'data', name: '정보 API', tech: '기상청 · 시세 · 단가', state,
    summary: i.status === 'off' ? '연결 없음 — 쓰지 않음' : parts.length ? `${i.count}개 중 ${parts.join(' · ')}` : `${i.count}개 모두 정상`,
    todo: state === 'ok' && !untested.length ? null : '설정 → 정보 API 에서 다시 시험',
    impact: '날씨 · 장비 시세 · 자재 단가처럼 에이전트가 외부에서 읽어 오는 값입니다. 실패한 연결은 답에 쓰지 못합니다.',
    fields: [
      { title: '지금 상태', rows: [['서버 말', i.message], ['연결 수', `${i.count}개`]] },
      { title: '연결마다 마지막 시험', rows: i.connections.map((c) => [`${c.name} (${INFO_KIND[c.kind] ?? c.kind})`, `${TEST_WORD[c.status] ?? c.status} · ${c.checked_at ? when(c.checked_at) : '시험 안 함'}`]) },
    ],
    raw: i, checkedAt: { at: times.at(-1) ?? null, server: true },
  };
}

function reuse(h: HealthOut, at: Check['checkedAt']): Check | null {
  const r = h.evidence_reuse;
  if (!r) return null;
  return {
    id: 'evidence_reuse', source: 'evidence_reuse', area: 'ai', name: '근거 다시 쓰기', state: 'ok',
    summary: `지금 다시 쓸 수 있는 근거 ${n(r.reusable)}건 · 7일 동안 ${n(r.reused_7d)}회`,
    todo: null,
    impact: `붙은 곳이 있고 ${r.days}일 안이며 「다시 쓰지 않기」가 아닌 근거만 다시 씁니다 — 그만큼 Liner 를 덜 부릅니다.`,
    fields: [{ title: '지금 상태', rows: [
      ['다시 쓰는 기간', `${r.days}일`], ['지금 다시 쓸 수 있는 근거', `${n(r.reusable)}건`],
      ['최근 7일 다시 씀 / Liner 검색', `${n(r.reused_7d)}회 / ${n(r.searches_7d)}회`],
    ] }],
    raw: r, checkedAt: at,
  };
}

function holidays(h: HealthOut, at: Check['checkedAt']): Check | null {
  const d = h.holidays;
  if (!d) return null;
  const state = fromStatus(d.status) ?? 'unknown';
  const year = new Date().getFullYear();
  const both = d.years.includes(year) && d.years.includes(year + 1);
  return {
    id: 'holidays', source: 'holidays', area: 'data', name: '공휴일 표', state,
    summary: `${d.years.join(' · ')}년 있음${both ? '(올해 · 내년 모두)' : ''}`,
    todo: state === 'ok' ? null : '올해 · 내년 공휴일 표를 채움',
    impact: '공정표의 쉬는 날 계산에 씁니다. 표가 없는 해는 주말만 쉽니다.',
    fields: [{ title: '지금 상태', rows: [['서버 말', d.message], ['있는 해', d.years.join(' · ')], ...d.years.map((y) => [`${y}년`, `${d.counts[String(y)] ?? 0}일`] as [string, string])] }],
    raw: d, checkedAt: at,
  };
}

function vision(h: HealthOut, at: Check['checkedAt']): Check | null {
  const v = h.vision;
  if (!v) return null;
  const state = fromStatus(v.status) ?? 'unknown';
  return {
    id: 'vision', source: 'vision', area: 'ai', name: '그림 읽기', state,
    summary: `${v.model} · 연결 「${v.connection_name ?? '없음'}」`,
    todo: state === 'ok' ? null : '설정 → AI 모델 연결 → 그림 읽기 배정',
    impact: '사진 · 도면 · 스캔 문서를 읽어 자료함과 답변에 씁니다.',
    fields: [{ title: '지금 상태', rows: [
      ['서버 말', v.message], ['모델', v.model], ['연결', v.connection_name ?? '없음'], ['배정', v.stored ? '설정에 저장' : '기본값'], ['키', v.key_ready ? '준비됨' : '읽지 못함'],
    ] }],
    raw: v, checkedAt: at,
  };
}

function presence(h: HealthOut, at: Check['checkedAt']): Check | null {
  const p = h.presence;
  if (!p) return null;
  return {
    id: 'presence', source: 'presence', area: 'live', name: '접속 중', state: 'info',
    summary: `사람 ${p.online_users}명 · 기기 ${p.online_devices}대`, todo: null,
    impact: '2분 안에 접속 신호를 보낸 사람 · 기기 수입니다. 누구인지는 설정 → 계정에서 봅니다.',
    fields: [{ title: '지금 상태', rows: [['접속 중인 사람', `${p.online_users}명`], ['접속 중인 기기', `${p.online_devices}대`]] }],
    raw: p, checkedAt: at,
  };
}

function turns(h: HealthOut, at: Check['checkedAt']): Check {
  const t = h.active_turns;
  return {
    id: 'active_turns', source: 'active_turns', area: 'live', name: '실행 중인 에이전트 턴', state: 'info',
    summary: t.length ? t.map((x) => `#${x.chat_session_id} ${x.title}${x.stop_requested ? '(중단 신호 보냄)' : ''}`).join(' · ') : '지금 실행 중인 턴이 없습니다',
    todo: null,
    impact: '응답이 길게 멈춘 턴이 있으면 여기에서 안전하게 중단 신호를 보낼 수 있습니다.',
    fields: [], raw: t, checkedAt: at,
  };
}

/** 대응표에 없는 칸(새 서버) → 「기타」. status 가 있으면 넷으로, 없으면 info. */
function other(key: string, value: unknown, at: Check['checkedAt']): Check {
  const box = typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null;
  const state = fromStatus(box?.status) ?? 'info';
  const message = typeof box?.message === 'string' ? box.message : null;
  return {
    id: key, source: key, area: 'other', name: key, state,
    summary: message ?? '화면에 아직 이름이 없는 진단 칸입니다 — 기계 출력을 보세요',
    todo: state === 'fail' || state === 'check' ? '기계 출력을 보고 담당자에게 알림' : null,
    impact: '이 화면이 아직 모르는 칸입니다. 서버가 보낸 그대로 기계 출력에 있습니다.',
    fields: [], raw: value, checkedAt: at,
  };
}

/** 서버 응답 → 점검 줄들(영역 차례). fetchedAt = 진단을 부른 때(서버가 시각을 주지 않는 칸의 마지막 확인). */
export function buildChecks(h: HealthOut, fetchedAt: Date): Check[] {
  const at = { at: fetchedAt.toISOString(), server: false };
  const list: (Check | null)[] = [
    llm(h, at), search(h, at), reuse(h, at), vision(h, at), qdrant(h, at),
    h.notify ? notify(h.notify) : null,
    h.notify?.kakao ? kakao(h.notify.kakao) : null,
    h.notify?.voice ? voice(h.notify.voice) : null,
    db(h, at), holidays(h, at), infoApi(h),
    presence(h, at), turns(h, at),
  ];
  for (const [key, value] of Object.entries(h)) {
    if (!(key in MAPPED) && value !== null && value !== undefined) list.push(other(key, value, at));
  }
  const order = (c: Check) => AREAS.findIndex((a) => a.id === c.area);
  return list.filter((c): c is Check => c !== null).sort((a, b) => order(a) - order(b));
}

/** 「먼저 볼 것」: 실패 → 확인 필요 → 모름(같은 상태는 영역 차례). */
export function firstLook(checks: Check[]): Check[] {
  const rank = (c: Check) => (c.state === 'info' || c.state === 'ok' ? 9 : RANK[c.state]);
  return checks.filter((c) => rank(c) < 3).sort((a, b) => rank(a) - rank(b));
}
