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

test('a mark that would run past the right edge is written leftwards from its line', () => {
  // 폭 560: 기한 540 은 글(어림 72px)이 넘친다 → 선 왼쪽(text-anchor end). Data Date 40 은 그대로 오른쪽.
  const { container } = render(
    <Header
      scale={makeScale('2027-03-01', '2027-03-28', 560, 0)}
      marks={[
        { key: 'deadline', x: 540, label: '기한 03.28', tone: 'deadline' },
        { key: 'data', x: 40, label: 'Data Date 03.03', tone: 'data' },
      ]}
    />,
  );
  const due = container.querySelector('[data-mark="deadline"]')!;
  expect(due).toHaveAttribute('text-anchor', 'end');
  expect(due).toHaveAttribute('x', '537');
  const data = container.querySelector('[data-mark="data"]')!;
  expect(data).toHaveAttribute('x', '43');
  expect(data.getAttribute('text-anchor') ?? 'start').toBe('start');
});

// 재확인 ④: 휴대폰(390px) 간트 머리에서 「Data Date 04.17」과 「준공 기한 12.24」가 겹쳐 「Data D준공 기한12.24」로 보였다.
// 겹치면 덜 중요한 것부터 날짜만 남기고(전체 이름은 title), 둘 다 읽히게 — 이름표 자리는 서로 겹치지 않는다.
const textW = (t: string) => [...t].reduce((n, ch) => n + (/[가-힣]/.test(ch) ? 11 : 7), 8);
function boxes(c: HTMLElement) {
  return [...c.querySelectorAll<SVGTextElement>('.gantt-mark')].map((el) => {
    const x = Number(el.getAttribute('x'));
    const w = textW(el.lastChild!.textContent!);
    return el.getAttribute('text-anchor') === 'end' ? [x + 3 - w, x + 3] : [x - 3, x - 3 + w];
  });
}
const apart = (bs: number[][]) => bs.every((a, i) => bs.every((b, j) => i === j || a[1] <= b[0] || b[1] <= a[0]));

test('phone width: Data Date and the deadline label never overlap and both stay readable', () => {
  // 휴대폰 간트 차트 폭(약 165px), Data Date 30 · 준공 기한 162(오른쪽 끝) — 재확인 RC-7 의 자리
  const { container } = render(
    <Header
      scale={makeScale('2027-03-01', '2027-12-31', 165, 0)}
      marks={[
        { key: 'data', x: 30, label: 'Data Date 04.17', tone: 'data' },
        { key: 'deadline', x: 162, label: '준공 기한 12.24', tone: 'deadline', title: '준공 2027-12-24까지 — 준공 기한 2027.12.24' },
      ]}
    />,
  );
  const data = container.querySelector('[data-mark="data"]')!;
  const due = container.querySelector('[data-mark="deadline"]')!;
  expect(data.lastChild!.textContent).toMatch(/04\.17$/);
  expect(due.lastChild!.textContent).toMatch(/12\.24$/);
  expect(apart(boxes(container))).toBe(true);
  expect(due.querySelector('title')).toHaveTextContent('준공 기한 2027.12.24');
});

test('when there is room for one full label, the Data Date keeps its name and the deadline shows the date', () => {
  const { container } = render(
    <Header
      scale={makeScale('2027-03-01', '2027-12-31', 220, 0)}
      marks={[
        { key: 'data', x: 30, label: 'Data Date 04.17', tone: 'data' },
        { key: 'deadline', x: 215, label: '준공 기한 12.24', tone: 'deadline' },
      ]}
    />,
  );
  expect(container.querySelector('[data-mark="data"]')).toHaveTextContent('Data Date 04.17');
  const due = container.querySelector('[data-mark="deadline"]')!;
  expect(due.lastChild!.textContent).toBe('12.24');
  expect(due.querySelector('title')).toHaveTextContent('준공 기한 12.24'); // 줄인 이름표는 전체 이름을 title 로
  expect(apart(boxes(container))).toBe(true);
});

test('labels far apart keep their full names', () => {
  const { container } = render(
    <Header
      scale={makeScale('2027-03-01', '2027-12-31', 1200, 0)}
      marks={[
        { key: 'data', x: 160, label: 'Data Date 04.17', tone: 'data' },
        { key: 'deadline', x: 1180, label: '준공 기한 12.24', tone: 'deadline' },
      ]}
    />,
  );
  expect([...container.querySelectorAll('.gantt-mark')].map((e) => e.textContent)).toEqual(['Data Date 04.17', '준공 기한 12.24']);
});
