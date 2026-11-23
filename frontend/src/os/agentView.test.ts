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

// F4(재확인): 현장 관리자는 새 일정을 만들 수 없다(서버 도구가 거절) — 생성 도구가 시작돼도 「새 프로젝트 생성 중」으로 바꾸지 않는다.
describe('new project mode by role', () => {
  const askGenerate = { run_id: 7, n: 1, call_id: 'c1', tool: 'ask.questionnaire', program: 'questionnaire', arguments: '{"purpose":"generate"}' };

  async function startAs(role: 'field' | 'user') {
    const { useSession } = await import('./session');
    const { useCurrentSchedule } = await import('./currentSchedule');
    useSession.getState().signIn({ token: 't', loginId: 'x', user: { id: 1, name: '박현장', role } });
    useCurrentSchedule.setState({ current: null, creatingNewProject: false });
    useAgentView.getState().reset();
    useAgentView.getState().onToolStart(askGenerate);
    return { creating: useCurrentSchedule.getState().creatingNewProject, ribbon: useAgentView.getState().ribbon.creatingNewProject };
  }

  it('the field role never enters new project mode', async () => {
    expect(await startAs('field')).toEqual({ creating: false, ribbon: false });
  });

  it('other roles still do', async () => {
    expect(await startAs('user')).toEqual({ creating: true, ribbon: true });
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

// 재확인 2(#49): 가져오기가 승인함에 낸 초안을 기다리는 실행은 생성 흐름처럼 「승인 대기 중」이다.
describe('import waiting for approval', () => {
  it('a waiting run whose last step is schedule.import waits for approval', () => {
    useAgentView.getState().reset();
    useAgentView.getState().onWorkflowEvent({ run_id: 49, status: 'waiting', steps: [{ n: 1, tool: 'schedule.import', program: null, status: 'done' }] });
    expect(useAgentView.getState().ribbon.waitReason).toBe('approval');
  });

  // 재확인 3(#51): 가져오기가 빈 칸 질문을 열고 기다리면 서버가 wait_reason answer 를 싣는다 — 「답변 대기 중」.
  it('the server wait reason wins over the guess from the last step', () => {
    useAgentView.getState().reset();
    useAgentView.getState().onWorkflowEvent({ run_id: 51, status: 'waiting', wait_reason: 'answer', steps: [{ n: 1, tool: 'schedule.import', program: null, status: 'done' }] });
    expect(useAgentView.getState().ribbon.waitReason).toBe('answer');
  });
});
