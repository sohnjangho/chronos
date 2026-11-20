import { expect, test } from 'vitest';
import type { ModelInfo } from './model';
import { contextText, DEFAULT_FILTER, filterModels, groupByVendor, modelLabel, shortName, vendorFacets } from './models';

const m = (id: string, name: string, vendor: string, vendor_name: string, context_length: number | null, chat = true): ModelInfo => ({
  id,
  name,
  vendor,
  vendor_name,
  context_length,
  chat,
});

const MODELS = [
  m('mistral/small', 'Mistral: Small', 'mistralai', 'Mistral', 32768),
  m('google/gemini-4-neon', 'Google: Gemini 4 Neon', 'google', 'Google', 1048576),
  m('liner-mark', 'Liner: Liner Mark', 'liner', 'Liner', 1048576),
  m('openai/gpt-6', 'OpenAI: GPT-6', 'openai', 'OpenAI', 128000),
  m('liner-gemini-router', 'Liner: Gemini Router', 'liner', 'Liner', 1048576),
  m('anthropic/claude-sonnet-5', 'Anthropic: Claude Sonnet 5', 'anthropic', 'Anthropic', 1000000),
  m('liner-claude-router', 'Liner: Claude Router', 'liner', 'Liner', 200000),
  m('cohere/command', 'Cohere: Command 한국어', 'cohere', 'Cohere', null),
  m('openai/batch-only', 'OpenAI: Batch Only', 'openai', 'OpenAI', 128000, false),
  m('liner-gpt-router', 'Liner: GPT Router', 'liner', 'Liner', 400000),
];
const ids = (list: ModelInfo[]) => list.map((x) => x.id);

test('shortName drops the "Vendor: " prefix and contextText reads like 1.05M / 200K', () => {
  expect(shortName(MODELS[1])).toBe('Gemini 4 Neon');
  expect(shortName(m('x', 'Plain name', 'liner', 'Liner', null))).toBe('Plain name');
  expect([1048576, 1000000, 2000000, 200000, 128000, 32768, 512, null].map(contextText)).toEqual([
    '1.05M',
    '1M',
    '2M',
    '200K',
    '128K',
    '33K',
    '512',
    '',
  ]);
  expect(modelLabel(MODELS[1])).toBe('Gemini 4 Neon · 1.05M');
  expect(modelLabel(MODELS[7])).toBe('Command 한국어');
});

test('vendors are ordered Liner, anthropic, openai, google, then by vendor name', () => {
  expect(groupByVendor(MODELS).map((g) => [g.vendor, g.models.length])).toEqual([
    ['liner', 4],
    ['anthropic', 1],
    ['openai', 2],
    ['google', 1],
    ['cohere', 1],
    ['mistralai', 1],
  ]);
});

test('the default filter keeps chat models only', () => {
  expect(DEFAULT_FILTER).toEqual({ query: '', vendors: [], minContext: 0, chatOnly: true, linerRouters: false });
  expect(ids(filterModels(MODELS, DEFAULT_FILTER))).not.toContain('openai/batch-only');
  expect(filterModels(MODELS, { ...DEFAULT_FILTER, chatOnly: false })).toHaveLength(10);
});

test('search matches name, id and vendor name, case-insensitively, Korean as typed', () => {
  const find = (query: string) => ids(filterModels(MODELS, { ...DEFAULT_FILTER, query }));
  expect(find('GEMINI')).toEqual(['google/gemini-4-neon', 'liner-gemini-router']);
  expect(find('claude-sonnet')).toEqual(['anthropic/claude-sonnet-5']);
  expect(find('mistral')).toEqual(['mistral/small']);
  expect(find('한국어')).toEqual(['cohere/command']);
});

test('vendor filter takes several vendors', () => {
  expect(ids(filterModels(MODELS, { ...DEFAULT_FILTER, vendors: ['openai', 'google'] }))).toEqual([
    'google/gemini-4-neon',
    'openai/gpt-6',
  ]);
});

test('context filter keeps 128K or more, or 1M or more', () => {
  expect(ids(filterModels(MODELS, { ...DEFAULT_FILTER, minContext: 1_000_000 }))).toEqual([
    'google/gemini-4-neon',
    'liner-mark',
    'liner-gemini-router',
    'anthropic/claude-sonnet-5',
  ]);
  expect(filterModels(MODELS, { ...DEFAULT_FILTER, minContext: 128_000 })).toHaveLength(7);
});

test('Liner routers only shows the three routers and liner-mark, recommended order first', () => {
  expect(ids(filterModels(MODELS, { ...DEFAULT_FILTER, linerRouters: true }))).toEqual([
    'liner-claude-router',
    'liner-gpt-router',
    'liner-gemini-router',
    'liner-mark',
  ]);
});

test('vendor facets count what the other filters leave, in vendor order', () => {
  const facets = vendorFacets(MODELS, { ...DEFAULT_FILTER, vendors: ['openai'], minContext: 128_000 });
  expect(facets.map((f) => [f.vendor_name, f.count])).toEqual([
    ['Liner', 4],
    ['Anthropic', 1],
    ['OpenAI', 1],
    ['Google', 1],
  ]);
});
