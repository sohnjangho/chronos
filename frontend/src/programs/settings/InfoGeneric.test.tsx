// 「정보 API 연결」 범용 연결(빠른 채움·여러 개). 연결·키·응답은 모두 가상.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test } from 'vitest';
import { json } from '../../test-helpers';
import type { InfoConnection, InfoTemplate } from './infoApi';
import { FAKE_SECRET, renderAs, resetAll, sent } from './testKit';

const LIST = '/api/info/connections';
const TEMPLATES = '/api/info/templates';
const HOLIDAY_URL = 'https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService';

const TPL: InfoTemplate[] = [
  {
    id: 'holidays',
    label: '특일 정보(공휴일)',
    base_url: HOLIDAY_URL,
    key_in: 'query',
    key_name: 'serviceKey',
    description: '연·월별 공휴일과 대체공휴일을 돌려줍니다.',
    usage: '경로 /getRestDeInfo · solYear, solMonth 필수 · _type=json',
    test_path: '/getRestDeInfo?solYear=2026&solMonth=12&_type=json',
    docs_url: 'https://www.data.go.kr/data/15012690/openapi.do',
  },
  {
    id: 'air',
    label: '에어코리아 대기오염',
    base_url: 'https://apis.data.go.kr/B552584/ArpltnInforInqireSvc',
    key_in: 'header',
    key_name: 'Authorization',
    description: '측정소별 실시간 대기오염 정보를 돌려줍니다.',
    usage: '경로 /getMsrstnAcctoRltmMesureDnsty',
    test_path: '/getMsrstnAcctoRltmMesureDnsty?stationName=종로구&dataTerm=DAILY&returnType=json',
    docs_url: 'https://www.data.go.kr/data/15073861/openapi.do',
  },
];

function generic(over: Partial<InfoConnection> = {}): InfoConnection {
  return {
    id: 21,
    name: '공휴일',
    preset: 'generic',
    base_url: HOLIDAY_URL,
    secret_last4: '9xQz',
    status: 'ok',
    checked_at: null,
    description: '공휴일·대체공휴일(연·월별)',
    usage: '경로 /getRestDeInfo',
    key_in: 'query',
    key_name: 'serviceKey',
    test_path: '/getRestDeInfo?solYear=2026&solMonth=12&_type=json',
    ...over,
  };
}

const form = () => screen.getByRole('group', { name: '정보 API 연결 추가' });
const card = (name = '공휴일') => screen.getByRole('article', { name });
const fieldOf = (el: HTMLElement) => el.closest('.ui-field') as HTMLElement;

async function openGenericAdd(over = {}) {
  const view = renderAs('admin', { section: 'info' }, { [LIST]: [], [TEMPLATES]: TPL, ...over });
  await userEvent.click(await screen.findByRole('button', { name: '+ 연결 추가' }));
  await userEvent.click(within(form()).getByRole('radio', { name: '범용' }));
  return view;
}

afterEach(resetAll);

test('the kind selector switches between the 기상청 form and the 범용 form', async () => {
  renderAs('admin', { section: 'info' }, { [LIST]: [], [TEMPLATES]: TPL });
  await userEvent.click(await screen.findByRole('button', { name: '+ 연결 추가' }));
  const kinds = within(form()).getByRole('radiogroup', { name: '종류' });
  expect(within(kinds).getAllByRole('radio').map((r) => r.closest('label')?.textContent)).toEqual(['기상청(전용)', '범용']);
  expect(within(kinds).getByRole('radio', { name: '기상청(전용)' })).toBeChecked();
  expect(within(form()).getByLabelText(/^서비스 키/)).toBeVisible();
  expect(within(form()).queryByLabelText('설명')).toBeNull();

  await userEvent.click(within(kinds).getByRole('radio', { name: '범용' }));
  for (const label of ['이름', '주소', '키 넣는 곳', '키 이름', '설명', '쓰는 법', '시험 경로']) {
    expect(within(form()).getByLabelText(label)).toBeVisible();
  }
  expect(within(form()).getByLabelText(/^키 —/)).toHaveAttribute('type', 'password');
  expect(within(form()).queryByLabelText(/^서비스 키/)).toBeNull();
  expect(within(form()).getByLabelText('이름')).toHaveValue('');

  await userEvent.click(within(kinds).getByRole('radio', { name: '기상청(전용)' }));
  expect(within(form()).getByLabelText('이름')).toHaveValue('기상청 날씨');
});

test('a quick-fill template fills every field except the key, and the name only when empty', async () => {
  await openGenericAdd();
  const pick = await within(form()).findByLabelText('빠른 채움');
  await userEvent.type(within(form()).getByLabelText(/^키 —/), FAKE_SECRET);
  await userEvent.selectOptions(pick, '특일 정보(공휴일)');
  const f = within(form());
  expect(f.getByLabelText('이름')).toHaveValue('특일 정보(공휴일)');
  expect(f.getByLabelText('주소')).toHaveValue(HOLIDAY_URL);
  expect(f.getByLabelText('키 넣는 곳')).toHaveValue('query');
  expect(f.getByLabelText('키 이름')).toHaveValue('serviceKey');
  expect(f.getByLabelText('설명')).toHaveValue(TPL[0].description);
  expect(f.getByLabelText('쓰는 법')).toHaveValue(TPL[0].usage);
  expect(f.getByLabelText('시험 경로')).toHaveValue(TPL[0].test_path);
  expect(f.getByLabelText(/^키 —/)).toHaveValue(FAKE_SECRET);
  const docs = f.getByRole('link', { name: '공식 문서' });
  expect(docs).toHaveAttribute('href', TPL[0].docs_url);
  expect(docs).toHaveAttribute('target', '_blank');
  expect(docs).toHaveAttribute('rel', 'noopener noreferrer');

  const name = f.getByLabelText('이름');
  await userEvent.clear(name);
  await userEvent.type(name, '대기 정보');
  await userEvent.selectOptions(pick, '에어코리아 대기오염');
  expect(name).toHaveValue('대기 정보');
  expect(f.getByLabelText('키 넣는 곳')).toHaveValue('header');
  expect(f.getByLabelText('키 이름')).toHaveValue('Authorization');
  expect(f.getByRole('link', { name: '공식 문서' })).toHaveAttribute('href', TPL[1].docs_url);
});

test('saving without the required fields shows Korean messages and sends nothing', async () => {
  const { fetchMock } = await openGenericAdd();
  await userEvent.click(within(form()).getByRole('button', { name: '저장' }));
  const f = within(form());
  expect(within(fieldOf(f.getByLabelText('이름'))).getByText('이름을 넣어 주세요.')).toBeVisible();
  expect(within(fieldOf(f.getByLabelText('주소'))).getByText('주소를 넣어 주세요.')).toBeVisible();
  expect(within(fieldOf(f.getByLabelText(/^키 —/))).getByText('키를 넣어 주세요.')).toBeVisible();
  expect(within(fieldOf(f.getByLabelText('설명'))).getByText('설명을 넣어 주세요.')).toBeVisible();
  expect(sent(fetchMock, `POST ${LIST}`)).toEqual([]);
});

test('create sends exactly the contract body, then clears the key field', async () => {
  let rows: InfoConnection[] = [];
  const { fetchMock } = await openGenericAdd({
    [LIST]: () => json(200, rows),
    [`POST ${LIST}`]: () => {
      rows = [generic({ name: '특일 정보(공휴일)' })];
      return json(201, rows[0]);
    },
  });
  await userEvent.selectOptions(await within(form()).findByLabelText('빠른 채움'), '특일 정보(공휴일)');
  await userEvent.type(within(form()).getByLabelText(/^키 —/), FAKE_SECRET);
  await userEvent.click(within(form()).getByRole('button', { name: '저장' }));
  expect(await screen.findByRole('article', { name: '특일 정보(공휴일)' })).toBeVisible();
  expect(sent(fetchMock, `POST ${LIST}`)).toEqual([
    {
      name: '특일 정보(공휴일)',
      preset: 'generic',
      base_url: HOLIDAY_URL,
      secret: FAKE_SECRET,
      description: TPL[0].description,
      usage: TPL[0].usage,
      key_in: 'query',
      key_name: 'serviceKey',
      test_path: TPL[0].test_path,
    },
  ]);
  expect(document.body.textContent).not.toContain(FAKE_SECRET);
  await userEvent.click(screen.getByRole('button', { name: '+ 연결 추가' }));
  await userEvent.click(within(form()).getByRole('radio', { name: '범용' }));
  expect(within(form()).getByLabelText(/^키 —/)).toHaveValue('');
});

test('a 422 from the server shows its Korean message and keeps the form', async () => {
  const message = '내부 주소(localhost·사설 IP)는 쓸 수 없습니다.';
  await openGenericAdd({ [`POST ${LIST}`]: () => json(422, { code: 'invalid_base_url', message, detail: null }) });
  await userEvent.selectOptions(await within(form()).findByLabelText('빠른 채움'), '특일 정보(공휴일)');
  await userEvent.type(within(form()).getByLabelText(/^키 —/), FAKE_SECRET);
  await userEvent.click(within(form()).getByRole('button', { name: '저장' }));
  expect(await within(form()).findByText(message)).toBeVisible();
  expect(within(form()).getByText('invalid_base_url')).toBeVisible();
});

test('a failed templates endpoint leaves a muted line and the form still saves', async () => {
  const { fetchMock } = await openGenericAdd({
    [TEMPLATES]: () => json(500, { code: 'internal', message: '서버 오류', detail: null }),
    [`POST ${LIST}`]: () => json(201, generic()),
  });
  const line = await within(form()).findByText('빠른 채움 목록을 불러오지 못했습니다');
  expect(line).toHaveClass('st-muted');
  expect(within(form()).queryByRole('alert')).toBeNull();
  expect(within(form()).queryByLabelText('빠른 채움')).toBeNull();
  const f = within(form());
  await userEvent.type(f.getByLabelText('이름'), '공휴일');
  await userEvent.type(f.getByLabelText('주소'), HOLIDAY_URL);
  await userEvent.type(f.getByLabelText(/^키 —/), FAKE_SECRET);
  await userEvent.type(f.getByLabelText('설명'), '공휴일 목록');
  await userEvent.click(f.getByRole('button', { name: '저장' }));
  await waitFor(() => expect(sent(fetchMock, `POST ${LIST}`)).toHaveLength(1));
});

test('an empty templates list shows the same muted line', async () => {
  await openGenericAdd({ [TEMPLATES]: [] });
  expect(await within(form()).findByText('빠른 채움 목록을 불러오지 못했습니다')).toBeVisible();
});

test('a 범용 card shows the kind, host and path, description, key end and actions', async () => {
  renderAs('admin', { section: 'info' }, { [LIST]: [generic()] });
  const c = await screen.findByRole('article', { name: '공휴일' });
  expect(within(c).getByText('범용')).toBeVisible();
  expect(within(c).getByText('apis.data.go.kr/B090041/openapi/service/SpcdeInfoService')).toHaveAttribute('title', HOLIDAY_URL);
  expect(within(c).getByText('공휴일·대체공휴일(연·월별)')).toBeVisible();
  expect(within(c).getByText('키 …9xQz')).toBeVisible();
  for (const text of ['연결됨', '확인한 적 없음']) expect(within(c).getByText(text)).toBeVisible();
  for (const name of ['연결 테스트', '고치기', '지우기']) expect(within(c).getByRole('button', { name })).toBeVisible();
});

test('고치기 on a 범용 card sends only what changed', async () => {
  const { fetchMock } = renderAs('admin', { section: 'info' }, {
    [LIST]: [generic()],
    'PATCH /api/info/connections/21': generic({ key_in: 'header' }),
  });
  await userEvent.click(within(await screen.findByRole('article', { name: '공휴일' })).getByRole('button', { name: '고치기' }));
  const f = within(within(card()).getByRole('group', { name: '연결 고치기' }));
  expect(f.getByLabelText('설명')).toHaveValue('공휴일·대체공휴일(연·월별)');
  expect(f.getByLabelText('쓰는 법')).toHaveValue('경로 /getRestDeInfo');
  expect(f.getByLabelText('시험 경로')).toHaveValue(generic().test_path);
  expect(f.getByLabelText(/^키 —/)).toHaveValue('');
  await userEvent.selectOptions(f.getByLabelText('키 넣는 곳'), '헤더');
  const keyName = f.getByLabelText('키 이름');
  await userEvent.clear(keyName);
  await userEvent.type(keyName, 'Authorization');
  await userEvent.type(f.getByLabelText('설명'), ' 목록');
  await userEvent.click(f.getByRole('button', { name: '저장' }));
  expect(await within(card()).findByText('저장했습니다.')).toBeVisible();
  expect(sent(fetchMock, 'PATCH /api/info/connections/21')).toEqual([
    { description: '공휴일·대체공휴일(연·월별) 목록', key_in: 'header', key_name: 'Authorization' },
  ]);
});

test('고치기 with a new address and no key shows the server 422 message', async () => {
  const message = '다른 주소로 바꾸면 서비스키를 다시 넣어 주세요.';
  const { fetchMock } = renderAs('admin', { section: 'info' }, {
    [LIST]: [generic()],
    'PATCH /api/info/connections/21': () => json(422, { code: 'secret_required', message, detail: null }),
  });
  await userEvent.click(within(await screen.findByRole('article', { name: '공휴일' })).getByRole('button', { name: '고치기' }));
  const group = within(card()).getByRole('group', { name: '연결 고치기' });
  const url = within(group).getByLabelText('주소');
  await userEvent.clear(url);
  await userEvent.type(url, 'https://apis.data.go.kr/B090041/other');
  await userEvent.click(within(group).getByRole('button', { name: '저장' }));
  expect(await within(group).findByText(message)).toBeVisible();
  expect(sent(fetchMock, 'PATCH /api/info/connections/21')).toEqual([{ base_url: 'https://apis.data.go.kr/B090041/other' }]);
});

test('the test result shows the summary, HTTP status, latency and the sample in a monospace box', async () => {
  const sample = '{"response":{"header":{"resultCode":"00","resultMsg":"NORMAL SERVICE."},"body":{"items":{"item":[{"dateName":"기독탄신일","locdate":20261225}]}}}}';
  renderAs('admin', { section: 'info' }, {
    [LIST]: [generic()],
    'POST /api/info/connections/21/test': {
      ok: true,
      summary: '공휴일 OK',
      services: [{ service: 'generic', label: '공휴일', ok: true, latency_ms: 245, error: null }],
      http_status: 200,
      sample,
    },
  });
  await userEvent.click(within(await screen.findByRole('article', { name: '공휴일' })).getByRole('button', { name: '연결 테스트' }));
  const result = await within(card()).findByRole('status', { name: '연결 테스트 결과' });
  expect(within(result).getByText('공휴일 OK')).toBeVisible();
  expect(within(result).getByText('HTTP 200')).toBeVisible();
  expect(within(result).getByText('245ms')).toBeVisible();
  const box = within(result).getByText(sample);
  expect(box.tagName).toBe('PRE');
  expect(box).toHaveClass('st-info-sample');
});

test('a failed generic test shows the service error', async () => {
  renderAs('admin', { section: 'info' }, {
    [LIST]: [generic()],
    'POST /api/info/connections/21/test': {
      ok: false,
      summary: '공휴일 실패',
      services: [{ service: 'generic', label: '공휴일', ok: false, latency_ms: 80, error: { code: 'not_registered', message: '이 키로는 활용 신청이 승인되지 않았습니다.' } }],
      http_status: 200,
      sample: null,
    },
  });
  await userEvent.click(within(await screen.findByRole('article', { name: '공휴일' })).getByRole('button', { name: '연결 테스트' }));
  const result = await within(card()).findByRole('status', { name: '연결 테스트 결과' });
  expect(within(result).getByText('이 키로는 활용 신청이 승인되지 않았습니다.')).toBeVisible();
  expect(result.querySelector('.st-info-sample')).toBeNull();
});

test('test_path_required opens the edit form with the message next to the test-path field', async () => {
  renderAs('admin', { section: 'info' }, {
    [LIST]: [generic({ test_path: '' })],
    'POST /api/info/connections/21/test': () => json(422, { code: 'test_path_required', message: '시험 경로를 넣어 주세요.', detail: null }),
  });
  await userEvent.click(within(await screen.findByRole('article', { name: '공휴일' })).getByRole('button', { name: '연결 테스트' }));
  const group = await within(card()).findByRole('group', { name: '연결 고치기' });
  const path = within(group).getByLabelText('시험 경로');
  expect(within(fieldOf(path)).getByText('시험 경로를 넣어 주세요.')).toBeVisible();
});

const many = (n: number) =>
  Array.from({ length: n }, (_, i) =>
    generic({ id: 100 + i, name: `연결 ${i + 1}`, description: i === 4 ? '측정소별 대기오염' : `설명 ${i + 1}` }),
  );

test('six connections show no filter', async () => {
  renderAs('admin', { section: 'info' }, { [LIST]: many(6) });
  expect(await screen.findByRole('article', { name: '연결 6' })).toBeVisible();
  expect(screen.queryByRole('searchbox', { name: '이름·설명 찾기' })).toBeNull();
});

test('seven connections show a filter that matches name or description', async () => {
  renderAs('admin', { section: 'info' }, { [LIST]: many(7) });
  const filter = await screen.findByRole('searchbox', { name: '이름·설명 찾기' });
  await userEvent.type(filter, '대기오염');
  expect(screen.getAllByRole('article').map((a) => a.getAttribute('aria-label'))).toEqual(['연결 5']);
  await userEvent.clear(filter);
  await userEvent.type(filter, '연결 7');
  expect(screen.getAllByRole('article').map((a) => a.getAttribute('aria-label'))).toEqual(['연결 7']);
  await userEvent.clear(filter);
  await userEvent.type(filter, '없는 말');
  expect(screen.queryAllByRole('article')).toHaveLength(0);
  expect(screen.getByText('찾는 연결이 없습니다.')).toBeVisible();
});
