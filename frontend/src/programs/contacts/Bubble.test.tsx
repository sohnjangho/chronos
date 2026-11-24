// 말풍선의 번역 줄(Task 100): 한국어가 아닌 글 밑에 한국어 뜻. 받은 글의 번역은 AI 가 옮긴 것이라 그렇게 밝힌다.
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';
import Bubble, { type BubbleProps } from './Bubble';
import { agentDraft, received } from './threadKit';

afterEach(cleanup);

const noop = () => undefined;
const show = (m: BubbleProps['m']) =>
  render(<Bubble m={m} all={[m]} scheduleId={1} busy={null} note={null} blocked={null} onSend={noop} onDiscard={noop} onSave={async () => true} onCancel={noop} onResend={noop} />);

test('a received text in another language shows the AI translation line under it', () => {
  show(received({ id: 5, body: 'Can you come on Saturday?', body_ko: '토요일에 오실 수 있나요?' }));
  const line = screen.getByText('토요일에 오실 수 있나요?').closest('p');
  expect(line).toHaveClass('th-ko');
  expect(line).toHaveAttribute('lang', 'ko');
  expect(line?.textContent).toContain('AI 번역');
  expect(screen.getByText('Can you come on Saturday?')).toBeVisible();
});

test('a draft in another language shows its Korean meaning as 번역 (written with the draft)', () => {
  show(agentDraft({ id: 6, body: 'Xin chào, ngày mai được không?', body_ko: '안녕하세요, 내일 되나요?' }));
  const line = screen.getByText('안녕하세요, 내일 되나요?').closest('p');
  expect(line?.textContent).toContain('번역');
  expect(line?.textContent).not.toContain('AI 번역');
});

test('a Korean text has no translation line', () => {
  show(received({ id: 7, body: '내일 가능합니다', body_ko: null }));
  expect(document.querySelector('.th-ko')).toBeNull();
});
