// 시험 전용 도우미. 화면 코드는 이 파일을 import하지 않는다.
import { vi } from 'vitest';
import { useSession, type Role } from './os/session';

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

type Route = ((init?: RequestInit) => Response | Promise<Response>) | object;

/** fetch 를 가짜로 바꾼다. 열쇠는 "METHOD /경로" 또는 "/경로"(GET). 값이 객체면 200 JSON. */
export function stubFetch(routes: Record<string, Route>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const route = routes[`${init?.method ?? 'GET'} ${url}`] ?? routes[url];
    if (route === undefined) {
      return json(404, { code: 'not_found', message: '찾을 수 없습니다.', detail: null });
    }
    return typeof route === 'function' ? route(init) : json(200, route);
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

export function signInAs(role: Role = 'admin', name = '손장호') {
  useSession.getState().signIn({ token: 'tok', loginId: 'jhsohn', user: { id: 1, name, role } });
}
