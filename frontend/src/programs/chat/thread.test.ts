import { expect, test } from 'vitest';
import { applyEvent, emptyThread, fromDetail, type Thread } from './thread';

const run = (events: [string, unknown][], start: Thread = emptyThread()) => events.reduce((t, [type, data]) => applyEvent(t, type, data), start);

test('text, tools and cards of one turn stay in one agent block in arrival order', () => {
  const t = run([
    ['text', { text: '조건을 뽑겠습니다.' }],
    ['tool_start', { run_id: 1, n: 1, call_id: 'c1', tool: 'generate.extract_conditions', program: null, arguments: '{}' }],
    ['tool_end', { run_id: 1, n: 1, call_id: 'c1', tool: 'generate.extract_conditions', ok: true, ms: 1500, error: null }],
    ['card', { kind: 'answers_filled', questionnaire_id: 1, count: 1 }],
    ['text', { text: '다 했습니다.' }],
  ]);
  expect(t.items).toHaveLength(1);
  const [agent] = t.items;
  expect(agent.kind).toBe('agent');
  if (agent.kind !== 'agent') return;
  expect(agent.steps).toEqual([{ callId: 'c1', tool: 'generate.extract_conditions', status: 'done', ms: 1500, error: null }]);
  expect(agent.parts.map((p) => p.type)).toEqual(['text', 'card', 'text']);
});

test('a user message starts a new block; workflow and usage go to the thread, not the items', () => {
  let t = run([['text', { text: '하나' }]]);
  t = { ...t, items: [...t.items, { kind: 'user', key: 'u', text: '둘' }] };
  t = run(
    [
      ['text', { text: '둘째 답' }],
      ['workflow', { run_id: 2, status: 'done', steps: [] }],
      ['usage', { input_tokens: 5, output_tokens: 1, cost: null, calls: 1 }],
      ['usage', { input_tokens: 5, output_tokens: 1, cost: 0.5, calls: 1 }],
      ['ping', {}],
      ['done', {}],
    ],
    t,
  );
  expect(t.items.map((i) => i.kind)).toEqual(['agent', 'user', 'agent']);
  expect(t.workflow).toEqual({ run_id: 2, status: 'done', steps: [] });
  expect(t.usage).toEqual({ input_tokens: 10, output_tokens: 2, cost: 0.5, calls: 2 });
});

test('broken payloads never throw', () => {
  const t = run([
    ['text', null],
    ['text', { text: 3 }],
    ['tool_end', { call_id: 'nope' }],
    ['card', null],
    ['card', 'x'],
    ['approval', {}],
    ['usage', { input_tokens: 'a' }],
    ['workflow', { steps: 'x' }],
    ['error', {}],
  ]);
  expect(t.items.length).toBeLessThanOrEqual(1);
  expect(t.usage.calls).toBe(0);
});

test('a reopened session ends unfinished steps as stopped, unless a turn is still running', () => {
  const messages = [
    { id: 1, role: 'user', content: { kind: 'text', text: 'q' }, created_at: 'x' },
    { id: 2, role: 'assistant', content: { kind: 'tool_calls', text: '', tool_calls: [{ id: 'a', name: 'schedule.read', arguments: {} }, { id: 'b', name: 'calc.cpm', arguments: {} }] }, created_at: 'x' },
    { id: 3, role: 'tool', content: { kind: 'tool_result', tool_call_id: 'a', name: 'schedule.read', ok: false, content: '{"error":"x"}' }, created_at: 'x' },
  ];
  const stopped = fromDetail({ messages, running: false, pending_retries: [] });
  const agent = stopped.items[1];
  expect(agent.kind === 'agent' && agent.steps.map((s) => s.status)).toEqual(['failed', 'stopped']);
  const running = fromDetail({ messages, running: true, pending_retries: [] });
  const live = running.items[1];
  expect(live.kind === 'agent' && live.steps.map((s) => s.status)).toEqual(['failed', 'running']);
});
