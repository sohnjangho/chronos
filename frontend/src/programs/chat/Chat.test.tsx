import { act, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { StrictMode } from 'react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, describe, expect, test, vi } from 'vitest';
import { useAiChat } from '../../os/aiChat';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import { useSession } from '../../os/session';
import { json, signInAsDemo } from '../../test-helpers';
import Chat from './Chat';
import { useChat } from './chatStore';
import { useEffectiveUi } from './seeing';
import {
  callsTo,
  feed,
  feedPending,
  lastBody,
  openOther,
  openSpy,
  placeWindow,
  renderAt,
  routes,
  send,
  SESSION,
  registerFakePrograms,
  setup,
  SID,
  sse,
} from './testKit';

const toolStart = (n: number, tool: string, call = `c${n}`) => ['tool_start', { run_id: 3, n, call_id: call, tool, program: null, arguments: '{}' }] as [string, unknown];
const toolEnd = (n: number, tool: string, ms: number, call = `c${n}`) =>
  ['tool_end', { run_id: 3, n, call_id: call, tool, ok: true, ms, error: null }] as [string, unknown];

beforeAll(() => registerFakePrograms());
beforeEach(() => {
  localStorage.clear();
  useCurrentSchedule.getState().setCurrent(null);
  setup();
});
afterEach(() => {
  useChat.getState().reset();
  useAiChat.getState().reset();
  useUiContext.getState().reset();
  vi.unstubAllGlobals();
});

describe('지시서 시험 (실제 사건 모양)', () => {
  beforeEach(() => void renderAt(480));

  test('streams text into one assistant message', async () => {
    feed([['text', { text: '안녕' }], ['text', { text: '하세요' }], ['done', {}]]);
    await send('hi');
    expect(screen.getByText('안녕하세요')).toBeVisible();
  });

  test('tool steps collapse into one line', async () => {
    feed([toolStart(1, 'schedule.read'), toolEnd(1, 'schedule.read', 200), ['text', { text: 'x' }], ['done', {}]]);
    await send('q');
    const line = screen.getByRole('button', { name: /도구 1개/ });
    expect(line).toBeVisible();
    expect(line).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(line);
    // 펼치면 단계 이름(한국어)과 서버가 보낸 도구 이름 그대로
    expect(screen.getByText('일정 읽기', { selector: 'li *' })).toBeVisible();
    expect(screen.getByText('schedule.read')).toBeVisible();
  });

  test('generation card shows rounds', async () => {
    const rounds = [
      { n: 1, activity_count: 40, violations: 3 },
      { n: 2, activity_count: 42, violations: 0 },
    ];
    feed([['card', { kind: 'generation', stage: 'check', rounds }], ['done', {}]]);
    await send('q');
    expect(screen.getByText(/1회차 위반 3 → 2회차 0/)).toBeVisible();
  });

  test('open_window event opens the program', async () => {
    feed([['open_window', { program: 'schedule', params: { tab: 'gantt' } }], ['done', {}]]);
    await send('q');
    expect(openSpy).toHaveBeenCalledWith('schedule', { tab: 'gantt' });
  });

  test('llm_not_ready shows a settings button', async () => {
    feed([
      ['error', { code: 'llm_not_ready', message: 'LLM 연결이 필요합니다. 설정에서 연결해 주세요.', action: { open: 'settings', params: { section: 'llm' } } }],
      ['done', {}],
    ]);
    await send('q');
    expect(screen.getByText('LLM 연결이 필요합니다. 설정에서 연결해 주세요.')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '설정 열기' }));
    expect(openSpy).toHaveBeenCalledWith('settings', { section: 'llm' });
  });

  test('ui context is sent with the message', async () => {
    feed([['done', {}]]);
    act(() => openOther('schedule', { program: 'schedule', schedule_id: 1, selected_activity: 'A2020' }));
    await send('이거 당겨 줘');
    expect(lastBody().ui.selected_activity).toBe('A2020');
    expect(lastBody()).toEqual({ text: '이거 당겨 줘', ui: { program: 'schedule', schedule_id: 1, selected_activity: 'A2020' } });
  });

  test('send becomes stop while streaming', async () => {
    feedPending();
    await send('q');
    expect(await screen.findByRole('button', { name: '중단' })).toBeVisible();
    expect(screen.queryByRole('button', { name: '보내기' })).toBeNull();
  });
});

test('wide window shows thread list and context panel', () => {
  renderAt(1560);
  expect(screen.getByText('새 대화')).toBeVisible();
  expect(screen.getByRole('tab', { name: '컨텍스트' })).toBeVisible();
});

test('narrow window hides them', () => {
  renderAt(480);
  expect(screen.queryByRole('tab', { name: '컨텍스트' })).toBeNull();
  expect(screen.queryByRole('complementary', { name: '대화 목록' })).toBeNull();
});

test('the layout follows the window: maximizing a small window switches to the large layout', async () => {
  renderAt(480);
  expect(screen.queryByRole('tab', { name: '컨텍스트' })).toBeNull();
  // 확대한 창은 작업 영역(화면 너비) 전체를 쓴다.
  vi.stubGlobal('innerWidth', 1920);
  act(() => useWindows.setState((s) => ({ wins: s.wins.map((x) => ({ ...x, maximized: true })) })));
  expect(await screen.findByRole('tab', { name: '컨텍스트' })).toBeVisible();
});

describe('R1 · params.session', () => {
  test('opens the given session and shows its messages', async () => {
    routes['/api/chat/sessions'] = [{ ...SESSION, id: 7, title: '크레인 2대로 늘리면?', pending_retries: 0 }];
    routes['/api/chat/sessions/7'] = {
      ...SESSION,
      id: 7,
      title: '크레인 2대로 늘리면?',
      running: false,
      pending_retries: [],
      messages: [
        { id: 1, role: 'user', content: { kind: 'text', text: '크레인 2대로 늘리면?' }, created_at: 'x' },
        { id: 2, role: 'assistant', content: { kind: 'text', text: '준공이 **4일** 당겨집니다.' }, created_at: 'x' },
      ],
    };
    renderAt(1560, { session: '7' });
    expect(await screen.findByText('4일')).toBeVisible();
    expect(screen.getByText('4일').tagName).toBe('STRONG');
    feed([['text', { text: '네' }], ['done', {}]], 7);
    await send('고마워');
    expect(callsTo('/api/chat/sessions/7/messages', 'POST')).toHaveLength(1);
    expect(callsTo('/api/chat/sessions', 'POST')).toHaveLength(0);
  });

  test('new params on an open window switch to that session', async () => {
    routes['/api/chat/sessions/8'] = { ...SESSION, id: 8, running: false, pending_retries: [], messages: [{ id: 1, role: 'user', content: { kind: 'text', text: '여덟 번째 대화' }, created_at: 'x' }] };
    const view = renderAt(480);
    view.rerender(<ChatAgain params={{ session: '8' }} />);
    expect(await screen.findByText('여덟 번째 대화')).toBeVisible();
  });

  test('an unreadable session shows the server message inside the window', async () => {
    renderAt(480, { session: '99' });
    expect(await screen.findByText('찾을 수 없습니다.')).toBeVisible();
  });
});

describe('Task 18 R5 · params.compose', () => {
  const composer = () => screen.getByRole('textbox', { name: '에이전트에게 요청' });

  test('pre-fills the composer of the given session and sends nothing by itself', async () => {
    routes['/api/chat/sessions/12'] = { ...SESSION, id: 12, title: '조건 맞추기 — 5층 사무동 신축', running: false, pending_retries: [], messages: [] };
    renderAt(480, { session: '12', compose: '조건에 맞게 일정을 고쳐 주세요.\n- 타워크레인: 1대 → 2대' });
    await waitFor(() => expect(composer()).toHaveValue('조건에 맞게 일정을 고쳐 주세요.\n- 타워크레인: 1대 → 2대'));
    expect(callsTo('/api/chat/sessions/12')).toHaveLength(1);
    expect(callsTo('/api/chat/sessions/12/messages', 'POST')).toHaveLength(0);
    feed([['done', {}]], 12);
    await userEvent.click(screen.getByRole('button', { name: '보내기' }));
    await waitFor(() => expect(callsTo('/api/chat/sessions/12/messages', 'POST')).toHaveLength(1));
    expect(lastBody().text).toBe('조건에 맞게 일정을 고쳐 주세요.\n- 타워크레인: 1대 → 2대');
  });

  test('fix1 m5 · a remount with the same params does not fill the composer again', async () => {
    routes['/api/chat/sessions/12'] = { ...SESSION, id: 12, running: false, pending_retries: [], messages: [] };
    const params = { session: '12', compose: '조건에 맞게 일정을 고쳐 주세요.' };
    const first = renderAt(480, params);
    await waitFor(() => expect(composer()).toHaveValue('조건에 맞게 일정을 고쳐 주세요.'));
    await userEvent.clear(composer());
    first.unmount();
    render(<Chat windowId="w1" params={params} />);
    await waitFor(() => expect(callsTo('/api/chat/sessions/12').length).toBeGreaterThanOrEqual(2));
    expect(composer()).toHaveValue('');
  });

  test('new compose params on an open window replace the text', async () => {
    routes['/api/chat/sessions/12'] = { ...SESSION, id: 12, running: false, pending_retries: [], messages: [] };
    const view = renderAt(480);
    await userEvent.type(composer(), '적던 글');
    view.rerender(<ChatAgain params={{ session: '12', compose: '새 요청' }} />);
    await waitFor(() => expect(composer()).toHaveValue('새 요청'));
  });
});

function ChatAgain({ params }: { params: Record<string, string> }) {
  return <Chat windowId="w1" params={params} />;
}

test('「전체 화면으로」 from the Context panel: a turn still running there shows a note and the thread refreshes when it ends', async () => {
  routes[`/api/chat/sessions/${SID}`] = {
    ...SESSION,
    running: true,
    pending_retries: [],
    messages: [{ id: 1, role: 'user', content: { kind: 'text', text: '이 일정 요약해 줘' }, created_at: 'x' }],
  };
  act(() => useAiChat.setState({ sessionId: SID, busy: true }));
  renderAt(1920, { session: String(SID) });
  expect(await screen.findByText('이 일정 요약해 줘')).toBeVisible();
  expect(screen.getByText('이 대화의 앞 요청을 처리하는 중입니다. 끝나면 이 화면에 이어서 보입니다.')).toBeVisible();
  routes[`/api/chat/sessions/${SID}`] = {
    ...SESSION,
    running: false,
    pending_retries: [],
    messages: [
      { id: 1, role: 'user', content: { kind: 'text', text: '이 일정 요약해 줘' }, created_at: 'x' },
      { id: 2, role: 'assistant', content: { kind: 'text', text: '준공은 2027-11-24 입니다.' }, created_at: 'x' },
    ],
  };
  act(() => useAiChat.setState({ busy: false }));
  expect(await screen.findByText('준공은 2027-11-24 입니다.')).toBeVisible();
  expect(screen.queryByText(/앞 요청을 처리하는 중/)).toBeNull();
});

describe('R4 · questionnaire', () => {
  test('a questionnaire event opens the questionnaire program with this session', async () => {
    renderAt(480);
    feed([['questionnaire', { id: 7 }], ['open_window', { program: 'questionnaire', params: { id: '7' } }], ['done', {}]]);
    await send('공정표 만들어 줘');
    expect(openSpy).toHaveBeenCalledWith('questionnaire', { id: '7', session: String(SID) });
    // 도구가 함께 낸 open_window 도 같은 대화를 잃지 않는다
    expect(openSpy).not.toHaveBeenCalledWith('questionnaire', { id: '7' });
    openSpy.mockClear();
    await userEvent.click(screen.getByRole('button', { name: '질문지 열기' }));
    expect(openSpy).toHaveBeenCalledWith('questionnaire', { id: '7', session: String(SID) });
  });

  test('params.resume_questionnaire continues the chat once and renders that stream', async () => {
    feed([['text', { text: '답을 반영해 다시 뽑겠습니다.' }], ['done', {}]]);
    // main.tsx 처럼 StrictMode(효과를 두 번 부름)에서도 한 번만 보낸다.
    placeWindow(480);
    const view = render(
      <StrictMode>
        <ChatAgain params={{ session: String(SID), resume_questionnaire: '7' }} />
      </StrictMode>,
    );
    expect(await screen.findByText('답을 반영해 다시 뽑겠습니다.')).toBeVisible();
    expect(lastBody()).toMatchObject({ questionnaire_id: 7 });
    expect(lastBody().text).toBeUndefined();
    expect(screen.getByText(/질문지 7 제출/)).toBeVisible();
    await waitFor(() => expect(useChat.getState().threads[SID].streaming).toBe(false));
    view.rerender(
      <StrictMode>
        <ChatAgain params={{ session: String(SID), resume_questionnaire: '7' }} />
      </StrictMode>,
    );
    await act(async () => {});
    expect(callsTo(`/api/chat/sessions/${SID}/messages`, 'POST')).toHaveLength(1);
    expect(screen.queryByRole('status')).toBeNull();
  });
});

describe('R6 · stop and busy', () => {
  test('stop asks the server and keeps the stream until done', async () => {
    renderAt(480);
    const live = feedPending();
    await send('길게 일해 줘');
    await userEvent.click(await screen.findByRole('button', { name: '중단' }));
    expect(callsTo(`/api/chat/sessions/${SID}/stop`, 'POST')).toHaveLength(1);
    expect(screen.getByRole('button', { name: '중단하는 중…' })).toBeDisabled();
    act(() => live.push([['text', { text: '여기까지 했습니다.' }], ['error', { code: 'stopped', message: '중단했습니다.' }], ['done', {}]]));
    expect(await screen.findByText('여기까지 했습니다.')).toBeVisible();
    expect(screen.getByText('중단했습니다.')).toBeVisible();
    act(() => live.close());
    expect(await screen.findByRole('button', { name: '보내기' })).toBeVisible();
  });

  test('a turn that is already running shows the server message inline and keeps the text', async () => {
    renderAt(480);
    routes[`POST /api/chat/sessions/${SID}/messages`] = () =>
      json(409, { code: 'turn_running', message: '앞의 요청을 처리하는 중입니다.', detail: null });
    await userEvent.type(screen.getByRole('textbox', { name: '에이전트에게 요청' }), '하나 더');
    await userEvent.click(screen.getByRole('button', { name: '보내기' }));
    expect(await screen.findByText('앞의 요청을 처리하는 중입니다.')).toBeVisible();
    expect(screen.getByRole('textbox', { name: '에이전트에게 요청' })).toHaveValue('하나 더');
    expect(screen.queryByText('하나 더', { selector: '.ch-me' })).toBeNull();
  });
});

describe('R7 · ui context', () => {
  test('the OS current schedule is the default schedule_id, also for a new session', async () => {
    useCurrentSchedule.getState().setCurrent({ id: 1, name: '5층 사무동 신축' });
    renderAt(480);
    feed([['done', {}]]);
    await send('요약해 줘');
    expect(lastBody().ui).toEqual({ schedule_id: 1 });
    const create = callsTo('/api/chat/sessions', 'POST')[0];
    expect(JSON.parse(String(create[1]!.body))).toEqual({ schedule_id: 1 });
  });

  test('"보는 중" shows the program and activity names, not ids', async () => {
    renderAt(480);
    act(() => openOther('schedule', { program: 'schedule', schedule_id: 1, selected_activity: 'A2020' }));
    expect(await screen.findByText('보는 중: 일정판 · A2020 지상 1~5층 골조')).toBeVisible();
  });

  test('U1 · the publisher\'s schedule wins over the OS current schedule; its window params are not scanned', async () => {
    useCurrentSchedule.getState().setCurrent({ id: 9, name: '다른 현장' });
    renderAt(480);
    act(() => openOther('schedule', { program: 'schedule', schedule_id: 1, selected_activity: null }, { params: { activity: 'A9999' } }));
    feed([['done', {}]]);
    await send('요약해 줘');
    expect(lastBody().ui).toEqual({ program: 'schedule', schedule_id: 1 });
  });

  test('U1 · a front window that published nothing gives only its program; the schedule falls back to the OS one', async () => {
    useCurrentSchedule.getState().setCurrent({ id: 1, name: '5층 사무동 신축' });
    renderAt(480);
    act(() => openOther('settings', undefined, { params: { activity: 'A2020' } }));
    expect(await screen.findByText('보는 중: 설정')).toBeVisible();
    feed([['done', {}]]);
    await send('q');
    expect(lastBody().ui).toEqual({ program: 'settings', schedule_id: 1 });
  });

  test('U1 · a window hidden behind the maximized chat window is not what the user is looking at', async () => {
    renderAt(480);
    act(() => openOther('schedule', { program: 'schedule', schedule_id: 1, selected_activity: 'A2020' }));
    expect(await screen.findByText(/보는 중: 일정판/)).toBeVisible();
    act(() => useWindows.setState((s) => ({ wins: s.wins.map((w) => (w.id === 'w1' ? { ...w, maximized: true } : w)) })));
    await waitFor(() => expect(screen.queryByText(/보는 중:/)).toBeNull());
    feed([['done', {}]]);
    await send('q');
    expect(lastBody().ui).toEqual({});
  });

  test('U1 · closing the publishing window forgets its context', async () => {
    renderAt(480);
    act(() => openOther('schedule', { program: 'schedule', schedule_id: 1, selected_activity: 'A2020' }));
    expect(await screen.findByText(/보는 중: 일정판/)).toBeVisible();
    act(() => useWindows.setState((s) => ({ wins: s.wins.filter((w) => w.id !== 'w2') })));
    await waitFor(() => expect(screen.queryByText(/보는 중:/)).toBeNull());
    expect(useUiContext.getState().byWindow).toEqual({});
  });

  test('U1 · dragging windows does not re-render what reads the ui context', () => {
    placeWindow(480);
    openOther('schedule', { program: 'schedule', schedule_id: 1, selected_activity: 'A2020' });
    let renders = 0;
    const { result } = renderHook(() => {
      renders += 1;
      return useEffectiveUi();
    });
    expect(result.current).toEqual({ program: 'schedule', schedule_id: 1, selected_activity: 'A2020' });
    const before = renders;
    act(() => {
      for (let i = 0; i < 5; i += 1) useWindows.setState((s) => ({ wins: s.wins.map((w) => ({ ...w, x: w.x + 10 })) }));
    });
    expect(renders).toBe(before);
  });
});

test('the thread list lists sessions by day, searches, and starts a new chat without creating it yet', async () => {
  const today = new Date().toISOString();
  routes['/api/chat/sessions'] = [
    { id: 4, title: '5층 사무동 공정표 만들기', schedule_id: 1, created_at: today, pending_retries: 0 },
    { id: 3, title: '부품 공장 3라인 고장 대응', schedule_id: null, created_at: '2026-01-02T00:00:00Z', pending_retries: 0 },
  ];
  renderAt(1560);
  const list = await screen.findByRole('complementary', { name: '대화 목록' });
  expect(await within(list).findByRole('button', { name: /5층 사무동 공정표 만들기/ })).toBeVisible();
  expect(within(list).getByText('오늘')).toBeVisible();
  expect(within(list).getByText('이전')).toBeVisible();
  await userEvent.type(within(list).getByRole('searchbox', { name: '대화 검색' }), '공장');
  expect(within(list).queryByRole('button', { name: /5층 사무동/ })).toBeNull();
  expect(within(list).getByRole('button', { name: /부품 공장/ })).toBeVisible();
  await userEvent.click(within(list).getByRole('button', { name: '새 대화' }));
  expect(callsTo('/api/chat/sessions', 'POST')).toHaveLength(0);
});

test('a project approved elsewhere re-reads the session list so the chat shows its bound schedule', async () => {
  routes['/api/chat/sessions'] = [{ id: 4, title: '5층 사무동 공정표 만들기', schedule_id: null, created_at: new Date().toISOString(), pending_retries: 0 }];
  await act(() => useChat.getState().loadSessions());
  routes['/api/chat/sessions'] = [{ id: 4, title: '5층 사무동 공정표 만들기', schedule_id: 9, created_at: new Date().toISOString(), pending_retries: 0 }];
  act(() => useCurrentSchedule.getState().bumpReload());
  await waitFor(() => expect(useChat.getState().sessions[0].schedule_id).toBe(9));
});

test('a small window picks a conversation from the top button', async () => {
  routes['/api/chat/sessions'] = [{ id: 4, title: '5층 사무동 공정표 만들기', schedule_id: 1, created_at: new Date().toISOString(), pending_retries: 0 }];
  routes['/api/chat/sessions/4'] = { ...SESSION, id: 4, running: false, pending_retries: [], messages: [{ id: 1, role: 'user', content: { kind: 'text', text: '공정표 만들어 줘' }, created_at: 'x' }] };
  renderAt(480);
  await userEvent.click(screen.getByRole('button', { name: /대화 고르기/ }));
  await userEvent.click(await screen.findByRole('button', { name: /5층 사무동 공정표 만들기/ }));
  expect(await screen.findByText('공정표 만들어 줘')).toBeVisible();
  expect(screen.getByRole('button', { name: /대화 고르기: 5층 사무동 공정표 만들기/ })).toBeVisible();
});

test('a dropped connection keeps what arrived and says so', async () => {
  renderAt(480);
  routes[`POST /api/chat/sessions/${SID}/messages`] = () => {
    // 첫 조각을 읽은 뒤에 끊긴다(바로 error 하면 읽기 전 조각까지 버려진다).
    let pulls = 0;
    const body = new ReadableStream<Uint8Array>({
      pull(c) {
        pulls += 1;
        if (pulls === 1) c.enqueue(new TextEncoder().encode('event: text\ndata: {"text":"반쯤"}\n\n'));
        else c.error(new Error('끊김'));
      },
    });
    return new Response(body, { status: 200 });
  };
  await userEvent.type(screen.getByRole('textbox', { name: '에이전트에게 요청' }), 'q');
  await userEvent.click(screen.getByRole('button', { name: '보내기' }));
  expect(await screen.findByText('반쯤')).toBeVisible();
  expect(await screen.findByText('서버에 연결할 수 없습니다.')).toBeVisible();
  expect(await screen.findByRole('button', { name: '보내기' })).toBeVisible();
});

describe('fix round 1 · resume, new chat, separation, reset', () => {
  test('m2 · a refused questionnaire resume offers 「다시 이어 가기」 on the notice and on the questionnaire card', async () => {
    routes[`/api/chat/sessions/${SID}`] = {
      ...SESSION,
      running: false,
      pending_retries: [],
      messages: [{ id: 1, role: 'event', content: { type: 'questionnaire', data: { id: 7 } }, created_at: 'x' }],
    };
    let posts = 0;
    routes[`POST /api/chat/sessions/${SID}/messages`] = () => {
      posts += 1;
      return posts === 1
        ? json(409, { code: 'turn_running', message: '앞의 요청을 처리하는 중입니다.', detail: null })
        : sse([['text', { text: '이어서 진행합니다.' }], ['done', {}]]);
    };
    renderAt(480, { session: String(SID), resume_questionnaire: '7' });
    expect(await screen.findByText('앞의 요청을 처리하는 중입니다.')).toBeVisible();
    const retry = screen.getAllByRole('button', { name: '다시 이어 가기' });
    expect(retry).toHaveLength(2);
    expect(within(screen.getByRole('region', { name: '질문지' })).getByRole('button', { name: '다시 이어 가기' })).toBeVisible();
    await userEvent.click(retry[0]);
    expect(await screen.findByText('이어서 진행합니다.')).toBeVisible();
    expect(lastBody()).toMatchObject({ questionnaire_id: 7 });
    expect(screen.queryByRole('button', { name: '다시 이어 가기' })).toBeNull();
  });

  test('m9 · the resumed questionnaire card shows its answer and assumption counts right away', async () => {
    routes['/api/questionnaires/7'] = {
      id: 7,
      title: '공정표 질문',
      status: 'submitted',
      progress: { answered: 1, total: 2 },
      groups: [
        {
          name: '범위',
          questions: [
            { id: 'floors', question: '지상 몇 층인가요?', assumption: '5층으로 가정합니다.', answer: { value: '10', label: '10층' } },
            { id: 'crane', question: '크레인은 몇 대인가요?', assumption: '1대로 가정합니다.', answer: null },
          ],
        },
      ],
    };
    feedPending();
    renderAt(480, { session: String(SID), resume_questionnaire: '7' });
    expect(await screen.findByText('질문지 7 제출 · 답 1개 · 가정 1개')).toBeVisible();
    expect(useChat.getState().threads[SID].streaming).toBe(true);
  });

  test('m3 · a turn cut by reset resolves as not sent', async () => {
    feedPending();
    const sending = useChat.getState().send('q');
    await waitFor(() => expect(callsTo(`/api/chat/sessions/${SID}/messages`, 'POST')).toHaveLength(1));
    act(() => useChat.getState().reset());
    expect(await sending).toBe(false);
  });

  test('m5 · creating a new conversation does not pull the user back from one opened meanwhile', async () => {
    let release = () => {};
    const created: Promise<Response> = new Promise((resolve) => {
      release = () => resolve(json(200, SESSION));
    });
    routes['POST /api/chat/sessions'] = () => created;
    routes['/api/chat/sessions'] = [{ ...SESSION, id: 8, title: '여덟 번째', created_at: new Date().toISOString(), pending_retries: 0 }];
    routes['/api/chat/sessions/8'] = { ...SESSION, id: 8, running: false, pending_retries: [], messages: [{ id: 1, role: 'user', content: { kind: 'text', text: '여덟 번째 대화' }, created_at: 'x' }] };
    feed([['done', {}]]);
    renderAt(1560);
    await userEvent.type(screen.getByRole('textbox', { name: '에이전트에게 요청' }), '새 질문');
    await userEvent.click(screen.getByRole('button', { name: '보내기' }));
    await userEvent.click(await screen.findByRole('button', { name: '여덟 번째' }));
    expect(await screen.findByText('여덟 번째 대화')).toBeVisible();
    act(() => release());
    await waitFor(() => expect(callsTo(`/api/chat/sessions/${SID}/messages`, 'POST')).toHaveLength(1));
    expect(useChat.getState().currentId).toBe(8);
    expect(screen.getByText('여덟 번째 대화')).toBeVisible();
  });

  test('m7 · switching conversations mid-stream keeps their messages apart', async () => {
    routes['/api/chat/sessions'] = [
      { ...SESSION, title: '하나', created_at: new Date().toISOString(), pending_retries: 0 },
      { ...SESSION, id: 8, title: '여덟 번째', created_at: new Date().toISOString(), pending_retries: 0 },
    ];
    routes['/api/chat/sessions/8'] = { ...SESSION, id: 8, running: false, pending_retries: [], messages: [{ id: 1, role: 'user', content: { kind: 'text', text: '여덟 번째 대화' }, created_at: 'x' }] };
    renderAt(1560, { session: String(SID) });
    const live = feedPending();
    await send('첫 대화 질문');
    await userEvent.click(await screen.findByRole('button', { name: '여덟 번째' }));
    expect(await screen.findByText('여덟 번째 대화')).toBeVisible();
    act(() => live.push([['text', { text: '첫 대화의 답' }]]));
    await act(async () => {});
    expect(screen.queryByText('첫 대화의 답')).toBeNull();
    expect(screen.getByRole('button', { name: '보내기' })).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '하나' }));
    expect(await screen.findByText('첫 대화의 답')).toBeVisible();
    expect(screen.queryByText('여덟 번째 대화')).toBeNull();
    expect(screen.getByRole('button', { name: '중단' })).toBeVisible();
  });

  test('m7 · a user switch or logout clears every conversation and stops the stream', async () => {
    routes['/api/chat/sessions'] = [{ ...SESSION, title: '김하늘의 대화', created_at: new Date().toISOString(), pending_retries: 0 }];
    renderAt(1560, { session: String(SID) });
    const live = feedPending();
    await send('비밀 질문');
    routes['/api/chat/sessions'] = [];
    act(() => signInAsDemo('user', '박서준', 'demo-user', 2));
    expect(useChat.getState()).toMatchObject({ sessions: [], threads: {}, currentId: null });
    await waitFor(() => expect(screen.queryByText('비밀 질문')).toBeNull());
    expect(screen.queryByText('김하늘의 대화')).toBeNull();
    // 스트림은 끊겼다(읽기를 취소해 서버로 가는 연결이 닫힌다) — 더 보낼 수 없다.
    await waitFor(() => expect(() => live.push([['text', { text: '늦게 온 답' }]])).toThrow(/closed/));
    expect(screen.queryByText('늦게 온 답')).toBeNull();
    act(() => useSession.getState().logout());
    expect(useChat.getState().threads).toEqual({});
  });
});

describe('Task 25 · params.ask', () => {
  const real = { send: useChat.getState().send, newChat: useChat.getState().newChat, openSession: useChat.getState().openSession };
  const sendSpy = vi.fn();
  const newChatSpy = vi.fn();
  const openSessionSpy = vi.fn();
  beforeEach(() => {
    sendSpy.mockReset().mockResolvedValue(true);
    newChatSpy.mockReset();
    openSessionSpy.mockReset().mockResolvedValue(undefined);
    useChat.setState({ send: sendSpy, newChat: newChatSpy, openSession: openSessionSpy });
    placeWindow(480);
  });
  afterEach(() => useChat.setState(real));

  test('ask param sends once in a new chat', async () => {
    const params = { ask: '만회 계획을 만들어 줘' };
    const view = render(<StrictMode><ChatAgain params={params} /></StrictMode>);
    await waitFor(() => expect(sendSpy).toHaveBeenCalledTimes(1));
    expect(sendSpy).toHaveBeenCalledWith('만회 계획을 만들어 줘');
    expect(newChatSpy).toHaveBeenCalled();
    view.rerender(<StrictMode><ChatAgain params={params} /></StrictMode>);
    await act(async () => {});
    expect(sendSpy).toHaveBeenCalledTimes(1);
  });

  test('ask with session opens that session first', async () => {
    render(<ChatAgain params={{ session: '4', ask: '지연 영향을 알려 줘' }} />);
    await waitFor(() => expect(openSessionSpy).toHaveBeenCalledWith(4));
    await waitFor(() => expect(sendSpy).toHaveBeenCalledWith('지연 영향을 알려 줘'));
    expect(newChatSpy).not.toHaveBeenCalled();
    expect(openSessionSpy.mock.invocationCallOrder[0]).toBeLessThan(sendSpy.mock.invocationCallOrder[0]);
  });

  test('ask with session under StrictMode opens the session and sends once', async () => {
    render(<StrictMode><ChatAgain params={{ session: '4', ask: '지연 영향을 알려 줘' }} /></StrictMode>);
    await waitFor(() => expect(sendSpy).toHaveBeenCalledTimes(1));
    expect(openSessionSpy).toHaveBeenCalledTimes(1);
  });

  test('rejected ask leaves a notice', async () => {
    sendSpy.mockResolvedValue(false);
    render(<ChatAgain params={{ ask: 'x' }} />);
    expect(await screen.findByText('앞의 요청이 끝난 뒤 다시 보내 주세요.')).toBeVisible();
  });
});

describe('tablet 3-pane layout', () => {
  test('tablet-main opens in wide 3-pane mode with collapsible panels, while tablet-side and PC < 1100 stay narrow', async () => {
    routes['/api/chat/sessions'] = [{ ...SESSION, title: '태블릿 대화', created_at: new Date().toISOString(), pending_retries: 0 }];
    routes[`/api/chat/sessions/${SID}`] = { ...SESSION, running: false, pending_retries: [], messages: [] };

    const tabletMain = render(<Chat windowId="tablet-main" params={{}} />);
    expect(await tabletMain.container.querySelector('.ch-root.is-wide')).not.toBeNull();
    expect(tabletMain.container.querySelector('.ch-side')).not.toBeNull();
    expect(tabletMain.container.querySelector('.ch-ctx')).not.toBeNull();

    const threadsToggle = screen.getByRole('button', { name: '대화 목록' });
    const contextToggle = screen.getByRole('button', { name: '컨텍스트' });
    expect(threadsToggle).toHaveAttribute('aria-pressed', 'true');
    expect(contextToggle).toHaveAttribute('aria-pressed', 'true');

    await userEvent.click(threadsToggle);
    expect(tabletMain.container.querySelector('.ch-side')).toBeNull();
    expect(threadsToggle).toHaveAttribute('aria-pressed', 'false');

    await userEvent.click(contextToggle);
    expect(tabletMain.container.querySelector('.ch-ctx')).toBeNull();
    expect(contextToggle).toHaveAttribute('aria-pressed', 'false');

    await userEvent.click(threadsToggle);
    await userEvent.click(contextToggle);
    expect(tabletMain.container.querySelector('.ch-side')).not.toBeNull();
    expect(tabletMain.container.querySelector('.ch-ctx')).not.toBeNull();
    tabletMain.unmount();

    const tabletSide = render(<Chat windowId="tablet-side" params={{}} />);
    expect(tabletSide.container.querySelector('.ch-root.is-narrow')).not.toBeNull();
    expect(tabletSide.container.querySelector('.ch-side')).toBeNull();
    expect(tabletSide.container.querySelector('.ch-ctx')).toBeNull();
    expect(screen.queryByRole('button', { name: '대화 목록' })).toBeNull();
    expect(screen.queryByRole('button', { name: '컨텍스트' })).toBeNull();
    tabletSide.unmount();

    placeWindow(1560);
    const pcWide = render(<Chat windowId="w1" params={{}} />);
    expect(pcWide.container.querySelector('.ch-root.is-wide')).not.toBeNull();
    expect(screen.queryByRole('button', { name: '대화 목록' })).toBeNull();
    expect(screen.queryByRole('button', { name: '컨텍스트' })).toBeNull();
  });
});
