// 설정 시험 전용 도우미. 화면 코드는 이 파일을 import하지 않는다.
import { render } from '@testing-library/react';
import { vi, type Mock } from 'vitest';
import type { Role } from '../../os/session';
import { useSession } from '../../os/session';
import { useWindows } from '../../os/windowStore';
import { signInAs, stubFetch } from '../../test-helpers';
import type { Connection, ModelInfo } from './model';
import Settings from './Settings';

/** 누가 봐도 가짜인 키. */
export const FAKE_SECRET = 'abcd1234efgh5678';
export const LINER_URL = 'https://platform.liner.com/api/v1';
/** 가짜 모델 한 개. 업체 이름은 이름의 "업체: " 앞, 없으면 업체 이름을 대문자로 시작. */
export function info(id: string, name: string, vendor: string, context_length: number | null, chat = true): ModelInfo {
  const vendor_name = name.includes(':') ? name.split(':')[0] : vendor[0].toUpperCase() + vendor.slice(1);
  return { id, name, vendor, vendor_name, context_length, chat, price: null };
}

/** 연결 1 의 모델 목록(Liner 모양). Liner 대화용 셋 + 다른 업체 넷 + 대화용 아닌 것 하나. */
export const MODELS: ModelInfo[] = [
  info('liner-mark', 'Liner: Liner Mark', 'liner', 1048576),
  info('liner-claude-router', 'Liner: Claude Router', 'liner', 200000),
  info('liner-gpt-router', 'Liner: GPT Router', 'liner', 400000),
  info('anthropic/claude-sonnet-5', 'Anthropic: Claude Sonnet 5', 'anthropic', 1000000),
  info('openai/gpt-6', 'OpenAI: GPT-6', 'openai', 128000),
  info('google/gemini-4-neon', 'Google: Gemini 4 Neon', 'google', 1048576),
  info('openai/batch-only', 'OpenAI: Batch Only', 'openai', 128000, false),
];
export const LINER_CHAT_IDS = ['liner-mark', 'liner-claude-router', 'liner-gpt-router'];

export function connection(over: Partial<Connection> = {}): Connection {
  return {
    id: 1,
    name: 'Liner 기본',
    provider: 'liner',
    base_url: LINER_URL,
    secret_last4: '4f2a',
    is_default: true,
    status: 'ok',
    model_count: 3,
    checked_at: null,
    latency_ms: 412,
    ...over,
  };
}

export const ASSIGNMENTS = {
  items: [
    { purpose: 'light', connection_id: 1, model: 'liner-claude-router', routing_strategy: 'cost' },
    { purpose: 'normal', connection_id: 1, model: 'liner-claude-router', routing_strategy: 'balanced' },
    { purpose: 'hard', connection_id: 1, model: 'liner-claude-router', routing_strategy: 'quality' },
    { purpose: 'longdoc', connection_id: 1, model: 'liner-mark', routing_strategy: null },
  ],
};

type Routes = Parameters<typeof stubFetch>[0];

/** 설정 화면이 처음 읽는 길. over 로 바꾸거나 더한다. */
export function routes(over: Routes = {}): Routes {
  return {
    '/api/llm/connections': [],
    '/api/llm/assignments': ASSIGNMENTS,
    '/api/llm/connections/1/models': { models: MODELS },
    '/api/settings/approval': { mode: 'important' },
    '/api/auth/users': [{ id: 1, name: '손장호', role: 'admin', login_id: 'jhsohn' }],
    ...over,
  };
}

export function renderAs(role: Role = 'admin', params?: Record<string, string>, over: Routes = {}) {
  signInAs(role);
  const fetchMock = stubFetch(routes(over));
  const view = render(<Settings windowId="w1" params={params} />);
  return { fetchMock, ...view };
}

/** "METHOD /경로" 로 보낸 요청들의 본문(JSON 을 푼 것). */
export function sent(fetchMock: Mock, key: string): unknown[] {
  return fetchMock.mock.calls
    .filter(([url, init]) => `${(init as RequestInit | undefined)?.method ?? 'GET'} ${String(url)}` === key)
    .map(([, init]) => {
      const body = (init as RequestInit | undefined)?.body;
      return typeof body === 'string' ? JSON.parse(body) : undefined;
    });
}

export function resetAll() {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  useWindows.getState().reset();
  useSession.getState().logout();
}
