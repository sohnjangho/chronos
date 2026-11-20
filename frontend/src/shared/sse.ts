import { failure, networkError, withAuth } from './api';

type OnEvent = (type: string, data: unknown) => void;

/** 사건 한 덩어리(빈 줄로 끝난 것)를 읽는다. 주석 줄(": ping")은 버린다. */
function dispatch(frame: string, onEvent: OnEvent) {
  let type = 'message';
  const data: string[] = [];
  for (const line of frame.split('\n')) {
    if (line === '' || line.startsWith(':')) continue;
    const colon = line.indexOf(':');
    const field = colon < 0 ? line : line.slice(0, colon);
    const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '');
    if (field === 'event') type = value;
    else if (field === 'data') data.push(value);
  }
  if (data.length === 0) return;
  const text = data.join('\n');
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    parsed = text;
  }
  onEvent(type, parsed);
}

/** 다음 조각. 연결이 끊기면 network_error, 멈췄으면 끝(done)으로 본다. */
async function nextChunk(reader: ReadableStreamDefaultReader<Uint8Array>, signal?: AbortSignal) {
  try {
    return await reader.read();
  } catch {
    if (signal?.aborted) return { done: true as const, value: undefined };
    throw networkError();
  }
}

async function readEvents(body: ReadableStream<Uint8Array>, onEvent: OnEvent, signal?: AbortSignal) {
  const reader = body.getReader();
  const stop = () => void reader.cancel().catch(() => {});
  signal?.addEventListener('abort', stop);
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    for (;;) {
      const { done, value } = await nextChunk(reader, signal);
      if (done || signal?.aborted) return;
      buffer += decoder.decode(value, { stream: true });
      let end: number;
      while ((end = buffer.indexOf('\n\n')) >= 0 && !signal?.aborted) {
        dispatch(buffer.slice(0, end), onEvent);
        buffer = buffer.slice(end + 2);
      }
    }
  } finally {
    signal?.removeEventListener('abort', stop);
  }
}

/**
 * 본문을 JSON 으로 POST 하고 SSE 응답의 사건마다 onEvent(type, data) 를 부른다.
 * data 는 JSON 이면 푼 값, 아니면 글. 2xx 가 아니면 ApiError(401 은 로그아웃).
 * signal 로 멈추면 오류 없이 끝난다.
 */
export async function streamPost(
  path: string,
  body: unknown,
  onEvent: OnEvent,
  signal?: AbortSignal,
): Promise<void> {
  const init: RequestInit = { method: 'POST', body: JSON.stringify(body), signal };
  const headers = withAuth(init);
  headers.set('Accept', 'text/event-stream');
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch {
    if (signal?.aborted) return;
    throw networkError();
  }
  if (!res.ok) throw await failure(res, true);
  if (res.body) await readEvents(res.body, onEvent, signal);
}
