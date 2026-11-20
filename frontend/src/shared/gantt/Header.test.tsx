import { render } from '@testing-library/react';
import { expect, test } from 'vitest';
import Header from './Header';
import { makeScale } from './scale';

const monthTexts = (c: HTMLElement) => [...c.querySelectorAll('.gantt-month')].map((t) => t.textContent);

test('a month too narrow for its name is left blank and passes its year to the next month', () => {
  // 2월은 6일(약 21px)만 보인다 → 이름 없이, 3월이 연도를 단다.
  const { container } = render(<Header scale={makeScale('2027-02-23', '2027-05-31', 350, 0)} />);
  expect(monthTexts(container)).toEqual(['', '2027년 3월', '4월', '5월']);
});

// Task 17 리뷰 I2: 좁은 창에서 연도를 계속 넘기다 모든 달이 빈칸이 되던 것.
test('narrow months shorten to YY.M or M월 instead of all going blank', () => {
  // 하루 1.15px → 달마다 32~36px: 'YY.M'(36px)이 안 들어가도 첫 달과 1월은 연도를 단다 — 다음 달까지 걸쳐 쓰고 다음 달은 비운다(fix 2 e).
  const thin = render(<Header scale={makeScale('2027-02-01', '2028-01-31', 365 * 1.15, 0)} />);
  expect(monthTexts(thin.container)).toEqual(['27.2', '', '4월', '5월', '6월', '7월', '8월', '9월', '10월', '11월', '12월', '28.1']);
  thin.unmount();
  // 하루 1.3px → 달마다 36~40px: 연도 달은 'YY.M'.
  const slim = render(<Header scale={makeScale('2027-02-01', '2028-01-31', 365 * 1.3, 0)} />);
  const labels = monthTexts(slim.container);
  expect(labels[0]).toBe('27.2');
  expect(labels[1]).toBe('3월');
  expect(labels.at(-1)).toBe('28.1');
  expect(labels.every(Boolean)).toBe(true);
});

test('however narrow, the first month and every January show the year', () => {
  const labels = monthTexts(render(<Header scale={makeScale('2027-02-01', '2029-01-31', 730, 0)} />).container); // 하루 1px
  expect(labels[0]).toBe('27.2');
  expect(labels[11]).toBe('28.1');
  expect(labels[23]).toBe('29.1');
  expect(labels[1]).toBe(''); // 걸쳐 쓴 연도 자리
});

test('wide months keep the 첫 달·1월 연도 rule', () => {
  const { container } = render(<Header scale={makeScale('2027-12-01', '2028-02-29', 900, 0)} />);
  expect(monthTexts(container)).toEqual(['2027년 12월', '2028년 1월', '2월']);
});

test('week labels thin out when weeks are narrow; marks are written in the bottom row', () => {
  const wide = render(<Header scale={makeScale('2027-03-01', '2027-03-28', 560, 0)} marks={[{ key: 'data', x: 40, label: 'Data Date 03.03', tone: 'data' }]} />);
  expect([...wide.container.querySelectorAll('.gantt-week')].map((t) => t.textContent)).toEqual(['3/1', '3/8', '3/15', '3/22']);
  expect(wide.container.querySelector('[data-mark="data"]')).toHaveTextContent('Data Date 03.03');
  wide.unmount();
  const narrow = render(<Header scale={makeScale('2027-03-01', '2027-05-30', 182, 0)} />); // 2px/일 → 주 14px
  expect([...narrow.container.querySelectorAll('.gantt-week')].map((t) => t.textContent)).toEqual(['3/1', '3/22', '4/12', '5/3', '5/24']);
});
