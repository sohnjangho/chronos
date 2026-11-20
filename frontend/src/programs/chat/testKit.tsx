// 대화창 시험 전용 도우미. 화면 코드는 이 파일을 import하지 않는다. 사람·현장은 모두 가상이다.
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { lazy } from 'react';
import { vi } from 'vitest';
import { register } from '../../os/registry';
import { useWindows } from '../../os/windowStore';
import { json, signInAsDemo, stubFetch } from '../../test-helpers';
import Chat from './Chat';
import { useChat } from './chatStore';

export const SID = 1;
export const SESSION = { id: SID, title: '', schedule_id: null, created_at: '2026-11-20T01:00:00Z' };
export const SCHEDULES = [
  { id: 1, name: '5층 사무동 신축', domain: 'construction', level: 'L3', version: 3, finish: '2027-11-24', updated_at: '2026-11-19T09:00:00Z' },
];
export const VIEW = {
  id: 1,
  name: '5층 사무동 신축',
  domain: 'construction',
  level: 'L3',
  version: 3,
  finish: '2027-11-24',
  activities: [{ id: 'A2020', name: '지상 1~5층 골조' }],
};

type Routes = Parameters<typeof stubFetch>[0];
export type Ev = [string, unknown];

const encode = (events: Ev[]) =>
  events.map(([type, data]) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`).join('');

/** 사건을 모두 보내고 닫히는 SSE 응답. */
export function sse(events: Ev[]): Response {
  return new Response(
    new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(new TextEncoder().encode(encode(events)));
        c.close();
      },
    }),
    { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
  );
}

/** 시험이 사건을 하나씩 밀어 넣는 SSE 응답. close() 를 부를 때까지 열려 있다. */
export function liveSse() {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const response = new Response(new ReadableStream<Uint8Array>({ start: (c) => void (ctrl = c) }), { status: 200 });
  return {
    response,
    push: (events: Ev[]) => ctrl.enqueue(new TextEncoder().encode(encode(events))),
    close: () => ctrl.close(),
  };
}

/** 이름을 보일 다른 프로그램(프로그램끼리 import하지 않으므로 등록부에 같은 이름으로 둔다). */
export function registerFakePrograms() {
  const names: [string, string][] = [['schedule', '일정판'], ['questionnaire', '질문지'], ['approvals', '승인함'], ['settings', '설정'], ['workflow', '워크플로우']];
  for (const [id, name] of names) {
    register({ id, name, icon: null, kind: 'system', defaultSize: { w: 800, h: 600 }, component: lazy(() => import('../../os/Placeholder')) });
  }
}

export let routes: Routes = {};
export let fetchMock: ReturnType<typeof stubFetch>;
export let openSpy: ReturnType<typeof vi.fn>;
let pending = false;

/** 로그인(가상 사람) + 가짜 API + windowStore.open 엿보기. */
export function setup(over: Routes = {}) {
  signInAsDemo('admin');
  pending = false;
  routes = {
    '/api/chat/sessions': [],
    'POST /api/chat/sessions': () => json(200, SESSION),
    [`/api/chat/sessions/${SID}`]: { ...SESSION, running: false, messages: [], pending_retries: [] },
    [`POST /api/chat/sessions/${SID}/stop`]: { stopping: true },
    '/api/schedules': SCHEDULES,
    '/api/schedules/1': VIEW,
    '/api/workflows/runs': [],
    ...over,
  };
  fetchMock = stubFetch(routes);
  openSpy = vi.fn(() => 'w9');
  useWindows.setState({ open: openSpy } as never);
}

/** 다음 메시지 POST 가 이 사건들을 흘려보내고 끝난다. */
export function feed(events: Ev[], sid = SID) {
  pending = false;
  routes[`POST /api/chat/sessions/${sid}/messages`] = () => sse(events);
}

/** 다음 메시지 POST 가 끝나지 않는다. */
export function feedPending(sid = SID) {
  pending = true;
  const live = liveSse();
  routes[`POST /api/chat/sessions/${sid}/messages`] = () => live.response;
  return live;
}

/** 창 하나(대화)를 이 너비로 두고 대화 화면을 그린다. */
export function renderAt(width: number, params?: Record<string, string>) {
  placeWindow(width, params);
  return render(<Chat windowId="w1" params={params} />);
}

/** 대화 창(w1)을 이 너비로 둔다(그리지는 않음). */
export function placeWindow(width: number, params?: Record<string, string>) {
  useWindows.setState({
    wins: [{ id: 'w1', programId: 'chat', title: '에이전트 대화', x: 0, y: 48, w: width, h: 760, z: 1, minimized: false, maximized: false, params }],
  });
}

const messageCalls = () => fetchMock.mock.calls.filter(([url, init]) => /\/messages$/.test(String(url)) && init?.method === 'POST');

/** 입력창에 적고 [보내기]. 끝나는 흐름이면 스트림이 끝날 때까지 기다린다. */
export async function send(text: string) {
  const before = messageCalls().length;
  await userEvent.type(screen.getByRole('textbox', { name: '에이전트에게 요청' }), text);
  await userEvent.click(screen.getByRole('button', { name: '보내기' }));
  await waitFor(() => expectMore(before));
  if (!pending) await waitFor(() => expectIdle());
}

function expectMore(before: number) {
  if (messageCalls().length <= before) throw new Error('메시지를 아직 보내지 않았습니다');
}

function expectIdle() {
  const { threads } = useChat.getState();
  if (Object.values(threads).some((t) => t.streaming)) throw new Error('아직 스트림이 도는 중입니다');
}

/** 마지막 메시지 POST 의 본문. */
export function lastBody() {
  const calls = messageCalls();
  return JSON.parse(String(calls[calls.length - 1][1]!.body));
}

/** 모든 요청 중 이 경로·메서드로 간 것. */
export const callsTo = (url: string, method = 'GET') =>
  fetchMock.mock.calls.filter(([u, init]) => String(u) === url && (init?.method ?? 'GET') === method);
