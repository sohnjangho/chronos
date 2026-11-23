import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useWindows } from '../../os/windowStore';
import { json, signInAsDemo, stubFetch } from '../../test-helpers';
import Explorer from './Explorer';
import manifest from './index';

const TREE = [
  { id: 1, name: '5층 사무동 신축', domain: 'construction', level: 'L3', version: 2, finish: '2027-11-28', updated_at: '2026-11-20T01:00:00Z' },
  { id: 2, name: '물류센터 증축 공사 — 남측 램프와 하역장 확장을 함께 하는 아주 긴 이름의 일정', domain: 'construction', level: 'L2', version: 1, finish: null, updated_at: '2026-11-19T01:00:00Z' },
  { id: 3, name: '부품 공장 6월 생산', domain: 'production', level: 'L4', version: 1, finish: '2027-06-30', updated_at: '2026-11-18T01:00:00Z' },
];
const VERSIONS = [
  { n: 2, note: 'A2020 기간 10 → 8', by_kind: 'user', by_name: '김하늘', is_plan: false, created_at: '2026-11-20T01:00:00Z' },
  { n: 1, note: '처음 생성 (승인)', by_kind: 'agent', by_name: '이도윤', is_plan: true, created_at: '2026-11-19T01:00:00Z' },
];
const VIEW = { id: 1, name: '5층 사무동 신축', version: 2, finish: '2027-11-28', plan_finish: '2027-11-24', activities: new Array(62).fill({}), relations: new Array(81).fill({}) };

let fetchMock: ReturnType<typeof stubFetch>;
let openSpy: ReturnType<typeof vi.fn>;
let tree = TREE;

function setup(role: 'admin' | 'user' = 'admin', extra: Parameters<typeof stubFetch>[0] = {}) {
  signInAsDemo(role);
  tree = TREE;
  fetchMock = stubFetch({
    '/api/explorer/tree': () => json(200, { schedules: tree }),
    '/api/schedules/1': VIEW,
    '/api/schedules/1/versions': VERSIONS,
    '/api/schedules/3': { ...VIEW, id: 3, name: '부품 공장 6월 생산', version: 1, plan_finish: '2027-06-30' },
    '/api/schedules/3/versions': [VERSIONS[1]],
    'POST /api/schedules/1/versions/1/restore': () => {
      tree = tree.map((t) => (t.id === 1 ? { ...t, version: 3 } : t));
      return json(200, { ...VIEW, version: 3 });
    },
    'DELETE /api/schedules/1': () => {
      tree = tree.filter((t) => t.id !== 1);
      return json(200, { deleted: 1 });
    },
    ...extra,
  });
  openSpy = vi.fn(() => 'w9');
  useWindows.setState({ open: openSpy, wins: [] } as never);
}

const callsTo = (url: string, method = 'GET') => fetchMock.mock.calls.filter(([u, init]) => String(u) === url && (init?.method ?? 'GET') === method);
const table = () => screen.getByRole('table', { name: '일정 목록' });
const panel = () => screen.getByRole('region', { name: '일정 정보' });

async function renderExplorer() {
  render(<Explorer />);
  await within(await screen.findByRole('table', { name: '일정 목록' })).findByText('5층 사무동 신축');
}

async function pick(name: string) {
  await userEvent.click(within(table()).getByText(name));
  await within(panel()).findByRole('heading', { name });
}

beforeEach(() => {
  localStorage.clear();
  useCurrentSchedule.setState({ current: null, userId: null });
});
afterEach(() => vi.unstubAllGlobals());

describe('지시서 시험', () => {
  test('explorer restore asks before applying', async () => {
    setup();
    await renderExplorer();
    await pick('5층 사무동 신축');
    await within(panel()).findByText('처음 생성 (승인)');
    await userEvent.click(screen.getAllByRole('button', { name: '되돌리기' })[0]);
    expect(screen.getByText(/버전 1의 내용으로 새 버전을 만듭니다/)).toBeVisible();
    expect(callsTo('/api/schedules/1/versions/1/restore', 'POST')).toHaveLength(0);
  });
});

describe('R7 탐색기', () => {
  test('restoring after the question posts the current version as base and reloads', async () => {
    setup();
    await renderExplorer();
    await pick('5층 사무동 신축');
    await within(panel()).findByText('처음 생성 (승인)');
    await userEvent.click(screen.getAllByRole('button', { name: '되돌리기' })[0]);
    await userEvent.click(within(screen.getByRole('alertdialog', { name: '버전 되돌리기' })).getByRole('button', { name: '되돌리기' }));
    await waitFor(() => expect(callsTo('/api/schedules/1/versions/1/restore', 'POST').map(([, i]) => JSON.parse(String(i!.body)))).toEqual([{ base_version: 2 }]));
    expect(await screen.findByText('버전 1의 내용으로 버전 3을 만들었습니다.')).toBeVisible();
    expect(callsTo('/api/explorer/tree').length).toBeGreaterThanOrEqual(2);
  });

  test('W1: a restore tells the open schedule windows to read again', async () => {
    setup();
    await renderExplorer();
    await pick('5층 사무동 신축');
    await within(panel()).findByText('처음 생성 (승인)');
    const before = useCurrentSchedule.getState().reloadToken;
    await userEvent.click(screen.getAllByRole('button', { name: '되돌리기' })[0]);
    await userEvent.click(within(screen.getByRole('alertdialog', { name: '버전 되돌리기' })).getByRole('button', { name: '되돌리기' }));
    expect(await screen.findByText('버전 1의 내용으로 버전 3을 만들었습니다.')).toBeVisible();
    expect(useCurrentSchedule.getState().reloadToken).toBe(before + 1);
  });

  test('a restore conflict shows the server message', async () => {
    setup('admin', {
      'POST /api/schedules/1/versions/1/restore': () => json(409, { code: 'version_conflict', message: '그 사이 일정이 바뀌었습니다. 다시 불러와 주세요.', detail: { current: 3 } }),
    });
    await renderExplorer();
    await pick('5층 사무동 신축');
    await within(panel()).findByText('처음 생성 (승인)');
    await userEvent.click(screen.getAllByRole('button', { name: '되돌리기' })[0]);
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '되돌리기' }));
    expect(await screen.findByText('그 사이 일정이 바뀌었습니다. 다시 불러와 주세요.')).toBeVisible();
  });

  test('the tree groups schedules by domain with counts and search narrows the list', async () => {
    setup();
    await renderExplorer();
    const nav = screen.getByRole('navigation', { name: '일정 분류' });
    expect(within(nav).getByRole('button', { name: '전체 3' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(nav).getByRole('button', { name: '건설 2' })).toBeVisible();
    await userEvent.click(within(nav).getByRole('button', { name: '생산 1' }));
    expect(within(table()).getAllByRole('row')).toHaveLength(2);
    await userEvent.click(within(nav).getByRole('button', { name: '전체 3' }));
    await userEvent.type(screen.getByRole('searchbox', { name: '이름으로 찾기' }), '물류');
    const rows = within(table()).getAllByRole('row');
    expect(rows).toHaveLength(2);
    expect(within(rows[1]).getByText(/물류센터/)).toHaveAttribute('title', TREE[1].name);
  });

  test('the table shows level, version, finish and a broken schedule without a finish', async () => {
    setup();
    await renderExplorer();
    const row = within(table()).getByText('5층 사무동 신축').closest('tr')!;
    expect(row).toHaveTextContent('건설');
    expect(row).toHaveTextContent('L3 관리');
    expect(row).toHaveTextContent('2027.11.28');
    const broken = within(table()).getByText(/물류센터/).closest('tr')!;
    expect(broken).toHaveTextContent('계산 안 됨');
  });

  test('selecting shows the summary and versions with number, Plan, memo and who', async () => {
    setup();
    await renderExplorer();
    await pick('5층 사무동 신축');
    const p = panel();
    expect(await within(p).findByText('62개 · 관계 81개')).toBeVisible();
    expect(within(p).getByText('2027.11.28 (Plan 2027.11.24)')).toBeVisible();
    expect(within(p).getByText('건설 · L3 관리')).toBeVisible();
    const versions = within(p).getByRole('list', { name: '버전' });
    const rows = within(versions).getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('2 지금');
    expect(rows[0]).toHaveTextContent('A2020 기간 10 → 8');
    expect(rows[0]).toHaveTextContent('김하늘 · 직접 수정');
    expect(within(rows[0]).queryByRole('button', { name: '되돌리기' })).toBeNull();
    expect(rows[1]).toHaveTextContent('1 처음 계획'); // is_plan = 처음 계획(PM 11-20: 화면의 「Plan」은 지금 일정을 실적 없이 계산한 것)
    expect(rows[1]).toHaveTextContent('이도윤 · 에이전트');
  });

  test('[스케줄에서 열기] sets the current schedule and opens the 스케줄 program', async () => {
    setup();
    await renderExplorer();
    await pick('5층 사무동 신축');
    await userEvent.click(within(panel()).getByRole('button', { name: '스케줄에서 열기' }));
    expect(useCurrentSchedule.getState().current).toEqual({ id: 1, name: '5층 사무동 신축' });
    expect(openSpy).toHaveBeenCalledWith('schedule-table', { id: '1' });
  });

  test('admin delete asks in the app, names the schedule and clears the current schedule', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm');
    setup();
    useCurrentSchedule.setState({ current: { id: 1, name: '5층 사무동 신축' } });
    await renderExplorer();
    await pick('5층 사무동 신축');
    await userEvent.click(within(panel()).getByRole('button', { name: '일정 지우기' }));
    const dialog = screen.getByRole('alertdialog', { name: '일정 지우기' });
    expect(dialog).toHaveTextContent('「5층 사무동 신축」을 지웁니다.');
    expect(dialog).toHaveTextContent('되돌릴 수 없습니다');
    expect(callsTo('/api/schedules/1', 'DELETE')).toHaveLength(0);
    await userEvent.click(within(dialog).getByRole('button', { name: '지우기' }));
    expect(await screen.findByText('「5층 사무동 신축」을 지웠습니다.')).toBeVisible();
    expect(callsTo('/api/schedules/1', 'DELETE')).toHaveLength(1);
    expect(useCurrentSchedule.getState().current).toBeNull();
    expect(within(table()).queryByText('5층 사무동 신축')).toBeNull();
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  test('cancel closes the delete question without deleting', async () => {
    setup();
    await renderExplorer();
    await pick('5층 사무동 신축');
    await userEvent.click(within(panel()).getByRole('button', { name: '일정 지우기' }));
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '취소' }));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(callsTo('/api/schedules/1', 'DELETE')).toHaveLength(0);
  });

  test('a normal user has no delete button', async () => {
    setup('user');
    await renderExplorer();
    await pick('5층 사무동 신축');
    expect(within(panel()).queryByRole('button', { name: '일정 지우기' })).toBeNull();
  });

  test('there are no empty document or report folders', async () => {
    setup();
    await renderExplorer();
    expect(screen.queryByText(/문서|보고서|복사본/)).toBeNull();
  });

  test('the manifest opens the screen at 1100×720', () => {
    expect(manifest.defaultSize).toEqual({ w: 1100, h: 720 });
  });
});

describe('Fix round 1', () => {
  test('m2: domains read in Korean, unknown ones raw, and cut cells show the whole text on hover', async () => {
    const rows = [
      { ...TREE[0], id: 1, domain: 'construction' },
      { ...TREE[0], id: 6, name: '라인 증설', domain: 'production' },
      { ...TREE[0], id: 7, name: '신소재', domain: 'research' },
      { ...TREE[0], id: 8, name: '가전 출시', domain: 'commercialization', level: 'L1' },
      { ...TREE[0], id: 9, name: '선박 블록', domain: 'shipbuilding' },
    ];
    setup('admin', { '/api/explorer/tree': () => json(200, { schedules: rows }) });
    await renderExplorer();
    const nav = screen.getByRole('navigation', { name: '일정 분류' });
    for (const name of ['건설 1', '생산 1', '연구개발 1', '사업화 1', 'shipbuilding 1']) expect(within(nav).getByRole('button', { name })).toBeVisible();
    expect(within(nav).getByText('shipbuilding')).toHaveAttribute('title', 'shipbuilding');
    const row = within(table()).getByText('가전 출시').closest('tr')!;
    expect(within(row).getByText('사업화')).toHaveAttribute('title', '사업화');
    expect(within(row).getByText('L1 마스터')).toHaveAttribute('title', 'L1 마스터');
  });

  test('m6: a version list that cannot be read says so and can be read again', async () => {
    let fail = true;
    setup('admin', {
      '/api/schedules/1/versions': () => (fail ? json(500, { code: 'internal_error', message: '서버에서 문제가 생겼습니다.', detail: null }) : json(200, VERSIONS)),
    });
    await renderExplorer();
    await pick('5층 사무동 신축');
    const alert = await within(panel()).findByRole('alert');
    expect(alert).toHaveTextContent('버전을 읽지 못했습니다: 서버에서 문제가 생겼습니다.');
    fail = false;
    await userEvent.click(within(alert).getByRole('button', { name: '다시 읽기' }));
    expect(await within(panel()).findByText('처음 생성 (승인)')).toBeVisible();
    expect(within(panel()).queryByRole('alert')).toBeNull();
  });

  test('m8: an author named like its kind is shown once', async () => {
    setup('admin', { '/api/schedules/3/versions': [{ ...VERSIONS[1], by_name: '에이전트' }] });
    await renderExplorer();
    await pick('부품 공장 6월 생산');
    const row = within(await within(panel()).findByRole('list', { name: '버전' })).getAllByRole('listitem')[0];
    expect(row).toHaveTextContent('에이전트 · ');
    expect(row).not.toHaveTextContent('에이전트 · 에이전트');
  });
});
