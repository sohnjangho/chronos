import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test } from 'vitest';
import type { ModelInfo, Probe } from './model';
import ProbeResult from './ProbeResult';
import { info } from './testKit';

const MODELS: ModelInfo[] = [
  info('mistral/small', 'Mistral: Small', 'mistralai', 32768),
  info('google/gemini-4-neon', 'Google: Gemini 4 Neon', 'google', 1048576),
  info('liner-mark', 'Liner: Liner Mark', 'liner', 1048576),
  info('openai/gpt-6', 'OpenAI: GPT-6', 'openai', 128000),
  info('liner-gemini-router', 'Liner: Gemini Router', 'liner', 1048576),
  info('anthropic/claude-sonnet-5', 'Anthropic: Claude Sonnet 5', 'anthropic', 1000000),
  info('liner-claude-router', 'Liner: Claude Router', 'liner', 200000),
  info('cohere/command', 'Cohere: Command', 'cohere', null),
  info('openai/batch-only', 'OpenAI: Batch Only', 'openai', 128000, false),
  info('liner-gpt-router', 'Liner: GPT Router', 'liner', 400000),
];
const PROBE: Probe = { ok: true, latency_ms: 398, models: MODELS, error: null };

const count = () => screen.getByRole('status', { name: '찾은 모델 수' });
const group = (name: RegExp) => screen.getByRole('button', { name });
const idsIn = (vendorName: string) =>
  within(screen.getByRole('table', { name: `${vendorName} 모델` }))
    .getAllByRole('row')
    .slice(1)
    .map((r) => r.querySelectorAll('td')[1].textContent);

test('the result is a summary line and collapsed vendor groups, never a wall of text', async () => {
  const { container } = render(<ProbeResult probe={PROBE} />);
  expect(screen.getByText('연결됨 · 398ms · 모델 10개 (대화용 9개) · 업체 6곳')).toBeVisible();
  const headers = screen.getAllByRole('button', { expanded: false }).map((b) => b.textContent);
  expect(headers).toEqual(['업체: 전체', 'Liner 4개', 'Anthropic 1개', 'OpenAI 1개', 'Google 1개', 'Cohere 1개', 'Mistral 1개']);
  expect(screen.queryByRole('table')).toBeNull();
  await userEvent.click(group(/^Liner 4개/));
  const table = screen.getByRole('table', { name: 'Liner 모델' });
  expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['이름', 'ID', '문맥 길이']);
  expect(within(table).getByRole('row', { name: /Liner Mark liner-mark 1.05M/ })).toBeVisible();
  expect(container.textContent).not.toMatch(/liner-mark,|liner-mark\n/);
});

test('search narrows across names, ids and vendor names and opens the matching groups', async () => {
  render(<ProbeResult probe={PROBE} />);
  expect(count()).toHaveTextContent('9개');
  await userEvent.type(screen.getByRole('searchbox', { name: '모델 찾기' }), 'gemini');
  expect(count()).toHaveTextContent('2개');
  expect(idsIn('Liner')).toEqual(['liner-gemini-router']);
  expect(idsIn('Google')).toEqual(['google/gemini-4-neon']);
});

test('vendor filter is a multi-select with counts', async () => {
  render(<ProbeResult probe={PROBE} />);
  await userEvent.click(screen.getByRole('button', { name: '업체: 전체' }));
  await userEvent.click(screen.getByRole('checkbox', { name: 'OpenAI 1' }));
  await userEvent.click(screen.getByRole('checkbox', { name: 'Google 1' }));
  expect(count()).toHaveTextContent('2개');
  expect(screen.getByRole('button', { name: '업체: 2곳' })).toBeVisible();
  expect(idsIn('OpenAI')).toEqual(['openai/gpt-6']);
});

test('context length filter keeps 128K or more, or 1M or more', async () => {
  render(<ProbeResult probe={PROBE} />);
  const ctx = screen.getByRole('combobox', { name: '문맥 길이' });
  expect(Array.from((ctx as HTMLSelectElement).options).map((o) => o.text)).toEqual(['전체', '128K 이상', '1M 이상']);
  await userEvent.selectOptions(ctx, '1M 이상');
  expect(count()).toHaveTextContent('4개');
  await userEvent.selectOptions(ctx, '128K 이상');
  expect(count()).toHaveTextContent('7개');
});

test('chat-only is on by default and can be turned off', async () => {
  render(<ProbeResult probe={PROBE} />);
  const chat = screen.getByRole('checkbox', { name: '대화용만' });
  expect(chat).toBeChecked();
  await userEvent.click(chat);
  expect(count()).toHaveTextContent('10개');
});

test('Liner routers only shows the recommended set first; clearing restores the defaults in one click', async () => {
  render(<ProbeResult probe={PROBE} />);
  const clear = screen.getByRole('button', { name: '필터 지우기' });
  expect(clear).toBeDisabled();
  await userEvent.click(screen.getByRole('checkbox', { name: 'Liner 라우터만' }));
  expect(count()).toHaveTextContent('4개');
  expect(idsIn('Liner')).toEqual(['liner-claude-router', 'liner-gpt-router', 'liner-gemini-router', 'liner-mark']);
  await userEvent.type(screen.getByRole('searchbox', { name: '모델 찾기' }), 'x');
  await userEvent.click(clear);
  expect(count()).toHaveTextContent('9개');
  expect(screen.getByRole('searchbox', { name: '모델 찾기' })).toHaveValue('');
  expect(screen.getByRole('checkbox', { name: 'Liner 라우터만' })).not.toBeChecked();
  expect(screen.getByRole('checkbox', { name: '대화용만' })).toBeChecked();
  expect(clear).toBeDisabled();
});

test('a failed test shows the server message and code', () => {
  render(<ProbeResult probe={{ ok: false, latency_ms: 120, models: [], error: { code: 'bad_key', message: 'API 키가 맞지 않습니다.' } }} />);
  expect(screen.getByText('API 키가 맞지 않습니다.')).toBeVisible();
  expect(screen.getByText('bad_key')).toBeVisible();
  expect(screen.queryByRole('searchbox')).toBeNull();
});

test('an open group shows at most 50 rows with "N개 더 보기", and can be collapsed while searching', async () => {
  const many = Array.from({ length: 120 }, (_, i) => info(`big/model-${i}`, `Big: Model ${i}`, 'big', 8192));
  render(<ProbeResult probe={{ ok: true, latency_ms: 10, models: many, error: null }} />);
  await userEvent.type(screen.getByRole('searchbox', { name: '모델 찾기' }), 'model');
  const rows = () => within(screen.getByRole('table', { name: 'Big 모델' })).getAllByRole('row').length - 1;
  expect(rows()).toBe(50);
  await userEvent.click(screen.getByRole('button', { name: '70개 더 보기' }));
  expect(rows()).toBe(100);
  await userEvent.click(screen.getByRole('button', { name: '20개 더 보기' }));
  expect(rows()).toBe(120);
  expect(screen.queryByRole('button', { name: /더 보기$/ })).toBeNull();
  await userEvent.click(screen.getByRole('button', { name: 'Big 120개' }));
  expect(screen.queryByRole('table', { name: 'Big 모델' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Big 120개' })).toHaveAttribute('aria-expanded', 'false');
});
