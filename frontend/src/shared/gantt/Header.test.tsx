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
