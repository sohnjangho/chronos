import { getToken, logout } from '../os/session';

/** 서버 오류 본문 {code, message, detail} 과 HTTP 상태. 연결 실패는 status 0. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: unknown;

  constructor(status: number, code: string, message: string, detail: unknown = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export const networkError = () => new ApiError(0, 'network_error', '서버에 연결할 수 없습니다.');

/** 토큰을 붙인 머리글. 본문이 글(JSON)이면 Content-Type 도 붙인다. */
export function withAuth(init: RequestInit = {}): Headers {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (typeof init.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  return headers;
}

/** 2xx 가 아닌 응답을 ApiError 로. loggedIn 이면 401 에 로그아웃한다. */
export async function failure(res: Response, loggedIn: boolean): Promise<ApiError> {
  if (res.status === 401 && loggedIn) logout();
  const body = (await res.json().catch(() => null)) as { code?: string; message?: string; detail?: unknown } | null;
  return new ApiError(
    res.status,
    body?.code ?? 'http_error',
    body?.message ?? '요청을 처리할 수 없습니다.',
    body?.detail ?? null,
  );
}

async function send<T>(path: string, init: RequestInit, headers: Headers, loggedIn: boolean): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw networkError();
  }
  if (!res.ok) throw await failure(res, loggedIn);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** 로그인한 사용자로 부른다. 토큰을 붙이고, 401 이면 로그아웃한다. */
export function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  return send<T>(path, init, withAuth(init), true);
}

/** 토큰 없이 부른다(로그인·잠금 풀기). 401 이어도 로그아웃하지 않는다. */
export function publicApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (typeof init.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  return send<T>(path, init, headers, false);
}
