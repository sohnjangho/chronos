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

/** 머리글. withToken 이면 지금 토큰을 붙이고 그 토큰도 돌려준다(401 때 비교용). 본문이 글이면 JSON. */
export function requestHeaders(init: RequestInit, withToken: boolean): { headers: Headers; token: string | null } {
  const headers = new Headers(init.headers);
  const token = withToken ? getToken() : null;
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (typeof init.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  return { headers, token };
}

/**
 * 2xx 가 아닌 응답을 ApiError 로. 401 이고 보낸 토큰이 아직 지금 세션의 토큰이면 로그아웃한다
 * (그 사이 다시 로그인했으면 새 세션은 두고). 로그아웃 까닭으로 서버의 code 를 남긴다(로그인 화면 안내).
 */
export async function failure(res: Response, sentToken: string | null): Promise<ApiError> {
  const body = (await res.json().catch(() => null)) as { code?: string; message?: string; detail?: unknown } | null;
  if (res.status === 401 && sentToken !== null && getToken() === sentToken) logout(body?.code);
  return new ApiError(
    res.status,
    body?.code ?? 'http_error',
    body?.message ?? '요청을 처리할 수 없습니다.',
    body?.detail ?? null,
  );
}

/** 2xx 본문: 비었으면 undefined, JSON 이 아니면 bad_response. */
async function readBody<T>(res: Response): Promise<T> {
  const text = await res.text();
  if (text === '') return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(res.status, 'bad_response', '서버 응답을 읽을 수 없습니다.');
  }
}

async function send<T>(path: string, init: RequestInit, withToken: boolean): Promise<T> {
  const { headers, token } = requestHeaders(init, withToken);
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch (e) {
    if (init.signal?.aborted) throw e;
    throw networkError();
  }
  if (!res.ok) throw await failure(res, token);
  return readBody<T>(res);
}

/** 로그인한 사용자로 부른다. 토큰을 붙이고, 그 토큰이 401 이면 로그아웃한다. 멈춤은 그 오류 그대로 던진다. */
export function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  return send<T>(path, init, true);
}

/** 토큰 없이 부른다(로그인·잠금 풀기). 401 이어도 로그아웃하지 않는다. */
export function publicApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  return send<T>(path, init, false);
}
