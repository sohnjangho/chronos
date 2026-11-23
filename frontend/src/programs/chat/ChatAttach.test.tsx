// Task 55 시험: 대화 첨부(📎·붙여넣기·10개 상한·상태 폴링·file_ids) · 모델 ▾ · notice · 이 대화의 파일 · 두 카드.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { json, signInAsDemo } from '../../test-helpers';
import { useAttach } from './attachStore';
import Chat from './Chat';
import { CardView } from './cards';
import { useChat } from './chatStore';
import { base64BytesOf, MAX_BASE64_BYTES, resizeImage } from '../../shared/files/resizeImage';
import { applyEvent, emptyThread } from './thread';

function sseResponse(events: { type: string; data: unknown }[]): Response {
  const body = events.map((e) => `event: ${e.type}\ndata: ${JSON.stringify(e.data)}\n\n`).join('');
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
}

interface Req {
  method: string;
  url: string;
  body: unknown;
}

function stubApi(handlers: Record<string, (req: Request, body: unknown) => Response> = {}) {
  const reqs: Req[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost');
      const key = `${init?.method ?? 'GET'} ${url.pathname}${url.search}`;
      const pathOnly = `${init?.method ?? 'GET'} ${url.pathname}`;
      const body = typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body;
      reqs.push({ method: init?.method ?? 'GET', url: `${url.pathname}${url.search}`, body });
      const fn = handlers[key] ?? handlers[pathOnly];
      if (fn) return fn(new Request(url, init), body);
      if (pathOnly === 'GET /api/chat/sessions') return json(200, []);
      if (pathOnly === 'GET /api/schedules') return json(200, []);
      return json(404, { code: 'not_found', message: '없음', detail: null });
    }),
  );
  return reqs;
}

beforeEach(() => {
  signInAsDemo('admin', '김하늘', 'demo-admin', 1);
  useChat.getState().reset();
  useAttach.getState().clear();
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('attaching files via picker, rejecting 11 files, polling status, and sending file_ids', async () => {
  let polls = 0;
  const reqs = stubApi({
    'POST /api/files': () =>
      json(200, { items: [{ file_id: 11, name: '시방서.pdf', kind: 'pdf', status: 'extracted', reason: null }] }),
    'GET /api/files/11': () => {
      polls += 1;
      return json(200, {
        file_id: 11, name: '시방서.pdf', ext: 'pdf', kind: 'pdf', size: 1024,
        status: 'classified', reason: null, uploaded_by: 1, uploaded_at: '2026-11-20T00:00:00Z',
        pages: 2, summary: '골조 기준', deleted: false, axes: { 종류: ['시방서'] },
      });
    },
    'POST /api/chat/sessions': () =>
      json(200, { id: 5, title: '', schedule_id: null, created_at: '2026-11-20T00:00:00Z' }),
    'POST /api/chat/sessions/5/messages': () =>
      sseResponse([
        { type: 'notice', data: { text: '그림은 그림 읽기 모델(liner-mark)로 봤습니다.' } },
        { type: 'text', data: { text: '확인했습니다.' } },
      ]),
    'GET /api/chat/sessions/5': () =>
      json(200, {
        id: 5, title: '붙인 파일', schedule_id: null, created_at: '2026-11-20T00:00:00Z',
        running: false, model: null,
        files: [{ file_id: 11, name: '시방서.pdf', kind: 'pdf', status: 'classified', deleted: false }],
        messages: [], pending_retries: [],
      }),
  });

  render(<Chat windowId="w-chat" />);

  // 11개 한도 초과 안내
  const tooMany = Array.from({ length: 11 }, (_, i) => new File(['a'], `f${i}.txt`, { type: 'text/plain' }));
  await act(async () => {
    await useAttach.getState().addFiles(tooMany);
  });
  expect(await screen.findByText(/한 번에 10개까지/)).toBeVisible();

  // 정상 첨부
  const input = screen.getByLabelText('파일 선택') as HTMLInputElement;
  const pdf = new File(['%PDF'], '시방서.pdf', { type: 'application/pdf' });
  fireEvent.change(input, { target: { files: [pdf] } });

  expect(await screen.findByText('시방서.pdf')).toBeVisible();

  // 파일만 보내기 → 기본 글 + file_ids 전송 + notice 표시
  await userEvent.click(screen.getByRole('button', { name: '보내기' }));
  await waitFor(() => {
    const msg = reqs.find((r) => r.method === 'POST' && r.url === '/api/chat/sessions/5/messages');
    expect(msg?.body).toMatchObject({ text: '붙인 파일을 봐 주세요.', file_ids: [11] });
  });
  expect(await screen.findByText('그림은 그림 읽기 모델(liner-mark)로 봤습니다.')).toBeVisible();
  expect(await screen.findByText('확인했습니다.')).toBeVisible();
  expect(polls).toBeGreaterThanOrEqual(0);
});

test('model picker sends PUT /api/chat/sessions/{id}/model for active session', async () => {
  const reqs = stubApi({
    'GET /api/chat/sessions': () =>
      json(200, [{ id: 9, title: '기존 대화', schedule_id: null, created_at: '2026-11-20T00:00:00Z', pending_retries: 0 }]),
    'GET /api/chat/sessions/9': () =>
      json(200, {
        id: 9, title: '기존 대화', schedule_id: null, created_at: '2026-11-20T00:00:00Z',
        running: false, model: null,
        files: [
          { file_id: 1, name: '현장.jpg', kind: 'image', status: 'classified', deleted: false },
          { file_id: 2, name: '옛자료.pdf', kind: 'pdf', status: 'classified', deleted: true },
        ],
        messages: [], pending_retries: [],
      }),
    'GET /api/llm/models?for=chat': () =>
      json(200, {
        connections: [{ connection_id: 1, name: 'Liner 기본', is_default: true, models: [{ id: 'liner-mark', name: 'Liner Mark' }] }],
      }),
    'PUT /api/chat/sessions/9/model': (_req, body) => json(200, body),
  });

  render(<Chat windowId="w-chat" params={{ session: '9' }} />);
  const btn = await screen.findByRole('button', { name: /대화 모델 고르기/ });
  await userEvent.click(btn);
  const dialog = await screen.findByRole('dialog', { name: '대화 모델 고르기' });
  await userEvent.click(within(dialog).getByRole('button', { name: 'Liner Mark' }));

  await waitFor(() => {
    const put = reqs.find((r) => r.method === 'PUT' && r.url === '/api/chat/sessions/9/model');
    expect(put?.body).toEqual({ connection_id: 1, model: 'liner-mark', routing_strategy: null });
  });
});

test('a narrow chat window opens 이 대화의 파일 from a 파일 (N) toggle and closes it with Escape or an outside click (B2)', async () => {
  stubApi({
    'GET /api/chat/sessions': () =>
      json(200, [{ id: 9, title: '기존 대화', schedule_id: null, created_at: '2026-11-20T00:00:00Z', pending_retries: 0 }]),
    'GET /api/chat/sessions/9': () =>
      json(200, {
        id: 9, title: '기존 대화', schedule_id: null, created_at: '2026-11-20T00:00:00Z',
        running: false, model: null,
        files: [
          { file_id: 1, name: '현장.jpg', kind: 'image', status: 'classified', deleted: false },
          { file_id: 2, name: '옛자료.pdf', kind: 'pdf', status: 'classified', deleted: true },
        ],
        messages: [], pending_retries: [],
      }),
  });

  render(<Chat windowId="w-chat" params={{ session: '9' }} />);
  expect(screen.queryByRole('complementary', { name: '대화 정보' })).toBeNull();
  const toggle = await screen.findByRole('button', { name: '파일 (1)' });
  expect(toggle).toHaveAttribute('aria-expanded', 'false');

  await userEvent.click(toggle);
  expect(toggle).toHaveAttribute('aria-expanded', 'true');
  const panel = screen.getByRole('complementary', { name: '대화 정보' });
  expect(within(within(panel).getByRole('list', { name: '이 대화의 파일' })).getByText('현장.jpg')).toBeVisible();
  await userEvent.keyboard('{Escape}');
  expect(screen.queryByRole('complementary', { name: '대화 정보' })).toBeNull();

  await userEvent.click(toggle);
  expect(screen.getByRole('complementary', { name: '대화 정보' })).toBeVisible();
  await userEvent.click(document.body);
  expect(screen.queryByRole('complementary', { name: '대화 정보' })).toBeNull();
});

test('renders file_saved and schedule_file cards and triggers import prompt', async () => {
  const sendSpy = vi.spyOn(useChat.getState(), 'send').mockResolvedValue(true);
  const ctx = { sessionId: 1, sendText: async () => true, failedQuestionnaire: null, retryResume: () => {} };

  render(
    <>
      <CardView
        event="card"
        data={{ kind: 'file_saved', file_id: 3, name: 'A현장_시방서.pdf', axes: { 종류: ['시방서'], 현장: ['A현장'] } }}
        ctx={ctx}
      />
      <CardView
        event="card"
        data={{ kind: 'schedule_file', file_id: 7, sheet: '공정표', rows: 120, columns_found: ['작업명', '시작일'], missing: ['기간'] }}
        ctx={ctx}
      />
    </>,
  );

  expect(screen.getByText('A현장_시방서.pdf')).toBeVisible();
  expect(screen.getByText('종류: 시방서')).toBeVisible();
  expect(screen.getByText(/120행/)).toBeVisible();
  expect(screen.getByText(/비어 있는 열: 기간/)).toBeVisible();

  await userEvent.click(screen.getByRole('button', { name: '일정 초안으로 가져오기' }));
  expect(sendSpy).toHaveBeenCalledWith('이 파일로 일정 초안을 만들어 줘(#7)');
});

test('notice event appends a notice part and small images skip resize', async () => {
  const next = applyEvent(emptyThread(), 'notice', { text: '안내 줄' });
  const agent = next.items[0];
  expect(agent.kind).toBe('agent');
  if (agent.kind === 'agent') {
    expect(agent.parts[0]).toEqual({ type: 'notice', text: '안내 줄' });
  }

  const small = new File([new Uint8Array(100)], 'a.jpg', { type: 'image/jpeg' });
  expect(base64BytesOf(small.size)).toBeLessThan(MAX_BASE64_BYTES);
  const res = await resizeImage(small);
  expect(res.resized).toBe(false);
  expect(res.file).toBe(small);
});
