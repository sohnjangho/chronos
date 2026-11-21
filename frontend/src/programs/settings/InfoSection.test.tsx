// 「정보 API 연결」(기상청). 연결·키는 모두 가상.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test } from 'vitest';
import { json } from '../../test-helpers';
import type { InfoConnection } from './infoApi';
import { FAKE_SECRET, renderAs, resetAll, sent } from './testKit';

const KMA_URL = 'https://apis.data.go.kr/1360000';
const KEY_HINT = '공공데이터포털 마이페이지의 일반 인증키(인코딩·디코딩 아무거나)';
const LIST = '/api/info/connections';

function kma(over: Partial<InfoConnection> = {}): InfoConnection {
  return { id: 7, name: '기상청 날씨', preset: 'kma', base_url: KMA_URL, secret_last4: 'a91c', status: 'unknown', checked_at: null, ...over };
}

const TESTED = {
  ok: false,
  summary: '단기예보 OK · ASOS 일자료 등록 안 됨',
  services: [
    { service: 'short_forecast', label: '단기예보', ok: true, latency_ms: 312, error: null },
    {
      service: 'asos',
      label: 'ASOS 일자료',
      ok: false,
      latency_ms: 290,
      error: { code: 'not_registered', message: '이 키로는 「ASOS 일자료」 활용 신청이 승인되지 않았습니다.' },
    },
  ],
};

const card = () => screen.getByRole('article', { name: '기상청 날씨' });
const nav = () => screen.getByRole('navigation', { name: '설정 구역' });
const openInfo = (over = {}) => renderAs('admin', { section: 'info' }, { [LIST]: [kma()], ...over });

afterEach(resetAll);

test('the nav has 정보 API 연결 next to LLM 연결 and the card shows the connection', async () => {
  openInfo();
  const names = within(nav()).getAllByRole('button').map((b) => b.textContent);
  expect(names.indexOf('정보 API 연결')).toBe(names.indexOf('LLM 연결') + 1);
  expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('정보 API 연결');
  const c = await screen.findByRole('article', { name: '기상청 날씨' });
  for (const text of ['기상청(공공데이터포털)', '미확인', KMA_URL, '확인한 적 없음']) expect(within(c).getByText(text)).toBeVisible();
  expect(within(c).getByText(/a91c$/)).toBeVisible();
  for (const name of ['연결 테스트', '고치기', '지우기']) expect(within(c).getByRole('button', { name })).toBeVisible();
});

test('an empty list says how to add one', async () => {
  renderAs('admin', { section: 'info' }, { [LIST]: [] });
  expect(await screen.findByText(/아직 연결이 없습니다/)).toBeVisible();
});

test('add sends name, preset and key, then clears the key field', async () => {
  let rows: InfoConnection[] = [];
  const { fetchMock } = renderAs('admin', { section: 'info' }, {
    [LIST]: () => json(200, rows),
    [`POST ${LIST}`]: () => {
      rows = [kma()];
      return json(201, rows[0]);
    },
  });
  await userEvent.click(await screen.findByRole('button', { name: '+ 연결 추가' }));
  const form = screen.getByRole('group', { name: '정보 API 연결 추가' });
  const preset = within(form).getByLabelText('종류');
  expect(within(preset).getAllByRole('option').map((o) => o.textContent)).toEqual(['기상청(공공데이터포털)']);
  const key = within(form).getByLabelText(/^서비스 키/);
  expect(key).toHaveAttribute('type', 'password');
  expect(within(form).getByText(KEY_HINT)).toBeVisible();
  const name = within(form).getByLabelText('이름');
  await userEvent.clear(name);
  await userEvent.type(name, '기상청 날씨');
  await userEvent.type(key, FAKE_SECRET);
  await userEvent.click(within(form).getByRole('button', { name: '저장' }));
  expect(await screen.findByRole('article', { name: '기상청 날씨' })).toBeVisible();
  expect(sent(fetchMock, `POST ${LIST}`)).toEqual([{ name: '기상청 날씨', preset: 'kma', secret: FAKE_SECRET }]);
  expect(screen.queryByRole('group', { name: '정보 API 연결 추가' })).toBeNull();
  expect(document.body.textContent).not.toContain(FAKE_SECRET);
  await userEvent.click(screen.getByRole('button', { name: '+ 연결 추가' }));
  expect(within(screen.getByRole('group', { name: '정보 API 연결 추가' })).getByLabelText(/^서비스 키/)).toHaveValue('');
});

test('a rejected key shows the server message verbatim and keeps the form', async () => {
  const message = '서비스키에 쓸 수 없는 문자가 있습니다. 공백이나 줄바꿈이 섞이지 않았는지 확인해 주세요.';
  renderAs('admin', { section: 'info' }, {
    [LIST]: [],
    [`POST ${LIST}`]: () => json(422, { code: 'invalid_secret', message, detail: null }),
  });
  await userEvent.click(await screen.findByRole('button', { name: '+ 연결 추가' }));
  const form = screen.getByRole('group', { name: '정보 API 연결 추가' });
  await userEvent.type(within(form).getByLabelText(/^서비스 키/), 'bad key');
  await userEvent.click(within(form).getByRole('button', { name: '저장' }));
  expect(await within(form).findByText(message)).toBeVisible();
  expect(within(form).getByText('invalid_secret')).toBeVisible();
});

test('the test button shows one line per service and the summary', async () => {
  let rows = [kma()];
  openInfo({
    [LIST]: () => json(200, rows),
    'POST /api/info/connections/7/test': () => {
      rows = [kma({ status: 'failed', checked_at: new Date().toISOString() })];
      return json(200, TESTED);
    },
  });
  await userEvent.click(within(await screen.findByRole('article', { name: '기상청 날씨' })).getByRole('button', { name: '연결 테스트' }));
  const result = await within(card()).findByRole('status', { name: '연결 테스트 결과' });
  expect(within(result).getByText('단기예보 OK · ASOS 일자료 등록 안 됨')).toBeVisible();
  const lines = within(result).getAllByRole('listitem');
  expect(lines).toHaveLength(2);
  expect(lines[0]).toHaveTextContent(/OK.*단기예보.*312ms/);
  expect(lines[1]).toHaveTextContent(/실패.*ASOS 일자료.*290ms/);
  expect(within(lines[1]).getByText('이 키로는 「ASOS 일자료」 활용 신청이 승인되지 않았습니다.')).toBeVisible();
  expect(within(lines[1]).getByText('not_registered')).toBeVisible();
  await waitFor(() => expect(within(card()).getByText('연결 실패')).toBeVisible());
});

test('고치기 with a new address and no key shows the 422 message verbatim', async () => {
  const message = '다른 주소로 바꾸면 서비스키를 다시 넣어 주세요.';
  const { fetchMock } = openInfo({
    'PATCH /api/info/connections/7': () => json(422, { code: 'secret_required', message, detail: null }),
  });
  await userEvent.click(within(await screen.findByRole('article', { name: '기상청 날씨' })).getByRole('button', { name: '고치기' }));
  const form = within(card()).getByRole('group', { name: '연결 고치기' });
  const url = within(form).getByLabelText('주소');
  await userEvent.clear(url);
  await userEvent.type(url, 'https://other.example/1360000');
  await userEvent.click(within(form).getByRole('button', { name: '저장' }));
  expect(await within(form).findByText(message)).toBeVisible();
  expect(within(form).getByText('secret_required')).toBeVisible();
  expect(sent(fetchMock, 'PATCH /api/info/connections/7')).toEqual([{ base_url: 'https://other.example/1360000' }]);
});

test('고치기 sends only what changed and clears the key field', async () => {
  const { fetchMock } = openInfo({ 'PATCH /api/info/connections/7': kma({ name: '기상청', secret_last4: '5678' }) });
  await userEvent.click(within(await screen.findByRole('article', { name: '기상청 날씨' })).getByRole('button', { name: '고치기' }));
  const form = within(card()).getByRole('group', { name: '연결 고치기' });
  const name = within(form).getByLabelText('이름');
  await userEvent.clear(name);
  await userEvent.type(name, '기상청');
  await userEvent.type(within(form).getByLabelText(/^서비스 키/), FAKE_SECRET);
  await userEvent.click(within(form).getByRole('button', { name: '저장' }));
  expect(await within(card()).findByText('저장했습니다.')).toBeVisible();
  expect(sent(fetchMock, 'PATCH /api/info/connections/7')).toEqual([{ name: '기상청', secret: FAKE_SECRET }]);
  expect(within(card()).queryByRole('group', { name: '연결 고치기' })).toBeNull();
  expect(document.body.textContent).not.toContain(FAKE_SECRET);
});

test('지우기 asks in the app, then deletes', async () => {
  const { fetchMock } = openInfo({ 'DELETE /api/info/connections/7': () => new Response(null, { status: 204 }) });
  await userEvent.click(within(await screen.findByRole('article', { name: '기상청 날씨' })).getByRole('button', { name: '지우기' }));
  const panel = within(card()).getByRole('group', { name: '연결 지우기 확인' });
  expect(within(panel).getByText(/「기상청 날씨」 연결을 지울까요\?/)).toBeVisible();
  await userEvent.click(within(panel).getByRole('button', { name: '지우기' }));
  await waitFor(() => expect(sent(fetchMock, 'DELETE /api/info/connections/7')).toHaveLength(1));
});

test('the section is admin-only', () => {
  const { fetchMock } = renderAs('user', { section: 'info' }, { [LIST]: [kma()] });
  expect(within(nav()).queryByRole('button', { name: '정보 API 연결' })).toBeNull();
  expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('내 정보');
  expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith('/api/info'))).toBe(false);
});
