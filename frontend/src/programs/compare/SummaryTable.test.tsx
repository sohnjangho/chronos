// 비교판 요약 표의 당김 효과 칸 둘(계획 5 Task 6): 「준공 반영」 n일 중 m일 · 「다음 결정 줄」. 값은 서버 SideOut.accel 그대로.
import { render, screen, within } from '@testing-library/react';
import { expect, test } from 'vitest';
import type { SideOut } from './compareApi';
import SummaryTable from './SummaryTable';
import { CURRENT, RECOVERY } from './testKit';

const chain = [
  { activity_id: 'A1500', name: '커튼월 공장 제작', point: true },
  { activity_id: 'A1550', name: '커튼월 자재 반입', point: false },
];
const row = (label: string) => screen.getByText(label).closest('tr')!;
const cells = (label: string) => within(row(label) as HTMLElement).getAllByRole('cell');

function draw(sides: SideOut[]) {
  render(<SummaryTable sides={sides} base="current" other={null} refreshing={false} onPick={() => {}} />);
}

test('two new columns: 「준공 반영」 as 「n일 중 m일」 (warning tone when warned) and 「다음 결정 줄」', () => {
  draw([CURRENT, { ...RECOVERY, accel: { pulled_days: 5, finish_gain: 1, warn: true, next_chain: chain }, accel_reason: null }]);
  expect(screen.getByRole('columnheader', { name: '준공 반영' })).toBeVisible();
  expect(screen.getByRole('columnheader', { name: '다음 결정 줄' })).toBeVisible();
  const reach = screen.getByText('5일 중 1일');
  expect(reach).toHaveClass('is-warn');
  const next = screen.getByText('커튼월 공장 제작 → 커튼월 자재 반입');
  expect(next).toHaveClass('cmp-chain-text'); // 두 줄까지 줄 바꿈(… 아님)
  expect(next.closest('td')).toHaveAttribute('title', '커튼월 공장 제작 → 커튼월 자재 반입');
});

test('ratio > 1 (resources mixed in) shows the numbers as they are without the warning tone', () => {
  draw([CURRENT, { ...RECOVERY, accel: { pulled_days: 0, finish_gain: 2, warn: false, next_chain: [] }, accel_reason: null }]);
  expect(screen.getByText('0일 중 2일')).not.toHaveClass('is-warn');
});

test('accel_reason is shown when the copy mixes pulls with other edits; no accel and no reason = 「—」', () => {
  const mixed = '여러 가지를 함께 바꿔 당김 효과를 따로 셀 수 없습니다';
  draw([CURRENT, { ...RECOVERY, accel: null, accel_reason: mixed }]);
  expect(screen.getByText(mixed)).toBeVisible();
  const own = cells('현재 일정 (버전 3)');
  expect(own.at(-3)!.textContent).toBe('—');
  expect(own.at(-2)!.textContent).toBe('—');
});
