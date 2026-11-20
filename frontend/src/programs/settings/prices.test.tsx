import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test } from 'vitest';
import type { ModelInfo, Price, Probe } from './model';
import { priceAsOf, priceShort, priceText } from './models';
import ProbeResult from './ProbeResult';
import { connection, info, renderAs, resetAll } from './testKit';

afterEach(resetAll);

const AS_OF = '2026-11-20';
const SONNET: Price = { kind: 'model', as_of: AS_OF, input: 2, output: 10, cached_input: 0.1 };
const ROUTER: Price = { kind: 'range', as_of: AS_OF, input_min: 0.1, input_max: 10, output_min: 0.5, output_max: 50 };
const priced = (m: ModelInfo, price: Price | null): ModelInfo => ({ ...m, price });

test('price text: a model shows input / output, a router shows a range, none shows nothing', () => {
  expect(priceText(SONNET)).toBe('입력 $2 / 출력 $10 (1M 토큰)');
  expect(priceText(ROUTER)).toBe('입력 $0.1~$10 / 출력 $0.5~$50 (1M 토큰)');
  expect(priceShort(SONNET)).toBe('$2 / $10');
  expect(priceShort({ ...SONNET, input: 0.075, output: 3.75 })).toBe('$0.075 / $3.75');
  expect(priceText(null)).toBe('');
  expect(priceAsOf([info('a', 'A', 'liner', null), priced(info('b', 'B', 'liner', null), SONNET)])).toBe(AS_OF);
  expect(priceAsOf([info('a', 'A', 'liner', null)])).toBeNull();
});

test('the assignment row shows the price of the chosen model and the basis note under the table', async () => {
  const models = [
    priced(info('liner-mark', 'Liner: Liner Mark', 'liner', 1048576), { ...SONNET, input: 1, output: 5 }),
    priced(info('liner-claude-router', 'Liner: Claude Router', 'liner', 200000), ROUTER),
    info('liner-gpt-router', 'Liner: GPT Router', 'liner', 400000),
  ];
  renderAs('admin', { section: 'assign' }, { '/api/llm/connections': [connection()], '/api/llm/connections/1/models': { models } });
  const light = await screen.findByRole('group', { name: '가벼운 일' });
  expect(await within(light).findByText('입력 $0.1~$10 / 출력 $0.5~$50 (1M 토큰)')).toBeVisible();
  expect(within(screen.getByRole('group', { name: '긴 문서 읽기' })).getByText('입력 $1 / 출력 $5 (1M 토큰)')).toBeVisible();
  expect(screen.getByText('가격 기준: Liner 공개 가격표(2026-11-20)')).toBeVisible();
  // 가격이 없는 모델을 고르면 가격 줄이 사라진다.
  await userEvent.selectOptions(within(light).getByRole('combobox', { name: '가벼운 일 모델' }), 'liner-gpt-router');
  expect(within(light).queryByText(/입력 \$/)).toBeNull();
});

test('find results carry the price', async () => {
  const models = [priced(info('liner-claude-router', 'Liner: Claude Router', 'liner', 200000), ROUTER)];
  renderAs('admin', { section: 'assign' }, { '/api/llm/connections': [connection()], '/api/llm/connections/1/models': { models } });
  const light = await screen.findByRole('group', { name: '가벼운 일' });
  await within(light).findByRole('combobox', { name: '가벼운 일 업체' });
  await userEvent.click(within(light).getByRole('button', { name: '가벼운 일 모델 찾기' }));
  const found = within(within(light).getByRole('group', { name: '가벼운 일 모델 찾기' }));
  expect(found.getByRole('button', { name: /Claude Router/ })).toHaveTextContent('입력 $0.1~$10 / 출력 $0.5~$50 (1M 토큰)');
});

test('the probe result table has a price column and the basis note; a missing price is a dash', async () => {
  const probe: Probe = {
    ok: true,
    latency_ms: 10,
    error: null,
    models: [priced(info('liner-mark', 'Liner: Liner Mark', 'liner', 1048576), SONNET), info('liner-x', 'Liner: X', 'liner', null)],
  };
  render(<ProbeResult probe={probe} />);
  await userEvent.click(screen.getByRole('button', { name: /^Liner 2개/ }));
  const table = screen.getByRole('table', { name: 'Liner 모델' });
  expect(within(table).getByRole('row', { name: /Liner Mark/ })).toHaveTextContent('$2 / $10');
  expect(within(table).getByRole('row', { name: /^X liner-x/ })).toHaveTextContent('-');
  expect(screen.getByText('가격 기준: Liner 공개 가격표(2026-11-20)')).toBeVisible();
});
