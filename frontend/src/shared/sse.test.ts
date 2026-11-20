import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useSession } from '../os/session';
import { json, signInAs, stubFetch } from '../test-helpers';
import { streamPost } from './sse';

const enc = new TextEncoder();

/** 주어진 바이트 조각을 차례로 흘리는 200 응답. */
function streamOf(chunks: Uint8Array[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      for (const chunk of chunks) c.enqueue(chunk);
      c.close();
    },
  });
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
}

const textChunks = (...parts: string[]) => parts.map((p) => enc.encode(p));

async function collect(chunks: Uint8Array[]) {
  stubFetch({ 'POST /s': () => streamOf(chunks) });
  const events: [string, unknown][] = [];
  await streamPost('/s', { text: 'hi' }, (type, data) => events.push([type, data]));
  return events;
}

beforeEach(() => signInAs());
afterEach(() => {
  vi.unstubAllGlobals();
  useSession.getState().logout();
});

test('posts JSON with the token and parses events in order', async () => {
  const fetch = stubFetch({
    'POST /s': () => streamOf(textChunks('event: text\ndata: {"text":"안녕"}\n\nevent: done\ndata: {}\n\n')),
  });
  const events: [string, unknown][] = [];
  await streamPost('/s', { text: 'hi' }, (type, data) => events.push([type, data]));
  expect(events).toEqual([
    ['text', { text: '안녕' }],
    ['done', {}],
  ]);
  const init = fetch.mock.calls[0][1]!;
  expect(init.body).toBe('{"text":"hi"}');
  expect(new Headers(init.headers).get('Authorization')).toBe('Bearer tok');
});

test('a multibyte character split across chunks stays intact', async () => {
  const bytes = enc.encode('event: text\ndata: {"text":"한글"}\n\n');
  const cut = bytes.indexOf(0xed) + 1; // '한'(ED 95 9C)의 첫 바이트 뒤에서 자른다
  const events = await collect([bytes.slice(0, cut), bytes.slice(cut)]);
  expect(events).toEqual([['text', { text: '한글' }]]);
});

test('a frame split across chunks is reassembled', async () => {
  const events = await collect(textChunks('event: te', 'xt\ndata: {"te', 'xt":"가"}\n', '\nevent: done\ndata: {}\n\n'));
  expect(events).toEqual([
    ['text', { text: '가' }],
    ['done', {}],
  ]);
});

test('comment lines are ignored', async () => {
  const events = await collect(textChunks(': ping\n\nevent: done\n: ping\ndata: {}\n\n'));
  expect(events).toEqual([['done', {}]]);
});

test('non-JSON data is passed as a string', async () => {
  const events = await collect(textChunks('event: note\ndata: 그냥 글\n\n'));
  expect(events).toEqual([['note', '그냥 글']]);
});

test('non-2xx throws ApiError from the JSON body', async () => {
  stubFetch({ 'POST /s': () => json(409, { code: 'turn_running', message: '앞의 요청을 처리하는 중입니다.', detail: null }) });
  await expect(streamPost('/s', {}, () => {})).rejects.toMatchObject({ status: 409, code: 'turn_running' });
});

test('401 logs out', async () => {
  stubFetch({ 'POST /s': () => json(401, { code: 'unauthorized', message: '다시 로그인해 주세요.', detail: null }) });
  await expect(streamPost('/s', {}, () => {})).rejects.toMatchObject({ status: 401 });
  expect(useSession.getState().session).toBeNull();
});

test('abort resolves quietly and stops events', async () => {
  const ctrl = new AbortController();
  stubFetch({
    'POST /s': () =>
      new Response(
        new ReadableStream<Uint8Array>({
          start(c) {
            c.enqueue(enc.encode('event: text\ndata: {"text":"1"}\n\n'));
            // 닫지 않는다: 서버가 아직 생각 중인 상태
          },
        }),
        { status: 200 },
      ),
  });
  const events: string[] = [];
  const done = streamPost(
    '/s',
    {},
    (type) => {
      events.push(type);
      ctrl.abort();
    },
    ctrl.signal,
  );
  await expect(done).resolves.toBeUndefined();
  expect(events).toEqual(['text']);
});

test('abort before the response resolves quietly', async () => {
  const ctrl = new AbortController();
  ctrl.abort();
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new DOMException('aborted', 'AbortError'))));
  await expect(streamPost('/s', {}, () => {}, ctrl.signal)).resolves.toBeUndefined();
});

test('a dropped connection becomes network_error but an onEvent error is not masked', async () => {
  stubFetch({
    'POST /s': () =>
      new Response(
        new ReadableStream<Uint8Array>({
          start(c) {
            c.error(new TypeError('terminated'));
          },
        }),
        { status: 200 },
      ),
  });
  await expect(streamPost('/s', {}, () => {})).rejects.toMatchObject({ status: 0, code: 'network_error' });
  stubFetch({ 'POST /s': () => streamOf(textChunks('event: text\ndata: {}\n\n')) });
  const bug = new TypeError('caller bug');
  await expect(
    streamPost('/s', {}, () => {
      throw bug;
    }),
  ).rejects.toBe(bug);
});
