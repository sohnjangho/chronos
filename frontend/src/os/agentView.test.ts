import { describe, expect, it } from 'vitest';
import { resolveToolTarget, useAgentView } from './agentView';

const labelOf = (tool: string, program: string | null) => {
  useAgentView.getState().onToolStart({ run_id: 1, n: 1, call_id: 'c1', tool, program, arguments: '{}' });
  return useAgentView.getState().ribbon.steps.find((s) => s.tool === tool)?.label;
};

describe('새 에이전트 도구의 화면 이름(A6)', () => {
  it('files.set_axes 는 「자료 분류 수정」이고 자료함 창을 가리킨다', () => {
    expect(labelOf('files.set_axes', null)).toBe('자료 분류 수정');
    expect(resolveToolTarget('files.set_axes', null).programId).toBe('library');
  });

  it('field.list 는 「현장 데이터 조회」다', () => {
    expect(labelOf('field.list', 'progress')).toBe('현장 데이터 조회');
  });

  it('info.list 는 「정보 API 목록」, info.call 은 「정보 API 조회」다', () => {
    expect(labelOf('info.list', null)).toBe('정보 API 목록');
    expect(labelOf('info.call', null)).toBe('정보 API 조회');
  });
});

// 리뷰 W2: 에이전트가 지연을 기록하면(버전은 그대로) 간트·공정률의 기록된 지연 띠가 다시 센다.
describe('onToolEnd delay signal', () => {
  it('a successful delay tool bumps the delays token, other tools and failures do not', async () => {
    const { useCurrentSchedule } = await import('./currentSchedule');
    const token = () => useCurrentSchedule.getState().delaysToken;
    const before = token();
    useAgentView.getState().onToolEnd({ tool: 'delay.record', ok: true, n: 1 });
    expect(token()).toBe(before + 1);
    useAgentView.getState().onToolEnd({ tool: 'delay.record', ok: false, n: 2 });
    useAgentView.getState().onToolEnd({ tool: 'schedule.read', ok: true, n: 3 });
    expect(token()).toBe(before + 1);
  });
});
