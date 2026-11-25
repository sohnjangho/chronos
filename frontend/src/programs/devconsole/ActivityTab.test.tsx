// 접속 기록 탭: 계정 고르기 · 대화(세션별) · 프로젝트 · 기능 사용(요약 칩 거르기) · 실행 추적 링크.
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, test, vi } from 'vitest';
import ActivityTab from './ActivityTab';
import { devApi, type AccountActivity } from './devApi';

const acc = { user_id: 2, login_id: 'judge', name: '심사위원', role: 'admin', last_at: '2026-11-26T01:12:00Z', logins: 3, failed_logins: 1, chats: 1, features: 2 };
const data: AccountActivity = {
  account: acc,
  chats: [{ id: 7, title: '지연 분석해줘', created_at: '2026-11-26T01:00:00Z', schedule: '수소 과제', messages: [
    { role: 'user', text: '지연 분석해줘', at: '2026-11-26T01:00:00Z', turn_id: 41 },
    { role: 'assistant', text: '크리티컬 경로가 3일 늦습니다.', at: '2026-11-26T01:01:00Z', turn_id: null },
  ] }],
  projects: [{ id: 5, name: '심사 프로젝트', domain: 'rnd', created_at: '2026-11-26T01:05:00Z' }],
  features: [
    { at: '2026-11-26T01:10:00Z', feature: '보고서 만들기·고치기', method: 'POST', route: '/api/reports/templates', schedule: null, device: 'Chrome/macOS', status: 200, note: null },
    { at: '2026-11-26T01:09:00Z', feature: '일정 보기', method: 'GET', route: '/api/schedules/{schedule_id}', schedule: '수소 과제', device: 'Chrome/macOS', status: 200, note: null },
  ],
  summary: [{ feature: '보고서 만들기·고치기', count: 1 }, { feature: '일정 보기', count: 1 }],
};

afterEach(() => vi.restoreAllMocks());

describe('접속 기록 탭', () => {
  test('shows chats by session, projects and filterable features; opens a turn', async () => {
    vi.spyOn(devApi, 'activityAccounts').mockResolvedValue({ accounts: [acc], unknown_failed: [{ at: '2026-11-26T00:00:00Z', login_id: 'guest' }] });
    vi.spyOn(devApi, 'activityAccount').mockResolvedValue(data);
    const open = vi.fn();
    render(<ActivityTab onOpenTurn={open} />);
    expect(await screen.findByText('크리티컬 경로가 3일 늦습니다.')).toBeInTheDocument();
    expect(screen.getByText(/없는 아이디로 로그인 시도 1건/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '실행 추적 →' }));
    expect(open).toHaveBeenCalledWith(41);

    await userEvent.click(screen.getByRole('tab', { name: /프로젝트/ }));
    expect(within(screen.getByRole('table', { name: '만든 프로젝트' })).getByText('심사 프로젝트')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: /기능 사용/ }));
    const table = () => screen.getByRole('table', { name: '기능 사용 기록' });
    expect(within(table()).getAllByRole('row')).toHaveLength(3);
    await userEvent.click(screen.getByRole('button', { name: '일정 보기 1' }));
    expect(within(table()).getAllByRole('row')).toHaveLength(2);
    expect(within(table()).getByText('수소 과제')).toBeInTheDocument();
  });
});
