import { render, screen, within } from '@testing-library/react';
import { expect, test } from 'vitest';
import { Markdown } from './markdown';

test('R9 · paragraphs, lists, bold and inline code', () => {
  const { container } = render(
    <Markdown text={'준공은 **2027-11-24** 입니다.\n둘째 줄\n\n- 가정: `양생 7일`\n- 크레인 1대\n\n1. 첫째\n2. 둘째'} />,
  );
  expect(screen.getByText('2027-11-24').tagName).toBe('STRONG');
  expect(screen.getByText('양생 7일').tagName).toBe('CODE');
  expect(container.querySelectorAll('ul > li')).toHaveLength(2);
  expect(container.querySelectorAll('ol > li')).toHaveLength(2);
  expect(container.querySelectorAll('p')).toHaveLength(1);
  expect(container.querySelector('p br')).not.toBeNull();
});

test('R9 · tables and fenced code', () => {
  const { container } = render(<Markdown text={'| 액티비티 | 여유 |\n|---|---:|\n| A2020 골조 | 0일 |\n| A3010 외장 | **3일** |\n\n```\nfinish = 2027-11-24\n```'} />);
  const table = screen.getByRole('table');
  expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['액티비티', '여유']);
  expect(within(table).getAllByRole('row')).toHaveLength(3);
  expect(within(table).getByText('3일').tagName).toBe('STRONG');
  expect(container.querySelector('pre > code')?.textContent).toBe('finish = 2027-11-24');
});

test('R9 · raw HTML is shown as text, never injected', () => {
  const { container } = render(<Markdown text={'<img src=x onerror="alert(1)"> <script>alert(2)</script> **굵게**'} />);
  expect(container.querySelector('img')).toBeNull();
  expect(container.querySelector('script')).toBeNull();
  expect(container.textContent).toContain('<img src=x onerror="alert(1)">');
});

test('unclosed markers stay as plain text', () => {
  const { container } = render(<Markdown text={'별표 하나 * 와 **닫히지 않은 굵게, `열린 코드'} />);
  expect(container.textContent).toBe('별표 하나 * 와 **닫히지 않은 굵게, `열린 코드');
});
