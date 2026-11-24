// 개발 콘솔 — 관리 포인트(계획 5 Task 7): 하네스 탭의 설정 카드(기준 다섯 + 분야별 바깥 자료) · 실행 추적의 「관리 포인트」 단계 ·
// 사용량의 Premium Data·MCP·Search Agent 수. 값은 가짜 서버(testKit) 그대로, 일정 이름은 가상이다.
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import DevConsole from './DevConsole';
import { done, mockPointsRuns, mockTurn, mockUsage, pointsPuts, pointsStage, setup } from './testKit';

const show = (params?: Record<string, string>) => render(<DevConsole windowId="w1" params={params} />);
async function card() {
  await screen.findByRole('spinbutton', { name: '크리티컬 직전으로 볼 여유' }); // 설정을 읽은 뒤
  return screen.getByRole('region', { name: '관리 포인트 설정' });
}

beforeEach(() => {
  localStorage.clear();
  setup();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('하네스 탭 — 관리 포인트 설정', () => {
  test('shows the five values with plain labels and a help line each, and the per-domain sources table', async () => {
    show({ tab: 'harness' });
    const c = await card();
    expect(within(c).getByRole('spinbutton', { name: '크리티컬 직전으로 볼 여유' })).toHaveValue(3);
    expect(within(c).getByRole('spinbutton', { name: '앞으로 볼 기간' })).toHaveValue(3);
    expect(within(c).getByRole('spinbutton', { name: '바깥 위험을 찾을 새 포인트 수' })).toHaveValue(5);
    expect(within(c).getByRole('spinbutton', { name: '찾은 바깥 자료를 다시 쓰는 시간' })).toHaveValue(6);
    expect(within(c).getByRole('spinbutton', { name: '당김 효과 경고 비율' })).toHaveValue(0.5);
    expect(c).toHaveTextContent('여유가 이 일수 이하인 작업도 관리 포인트로 봅니다. 0이면 크리티컬만. (0~10)');
    const table = within(c).getByRole('table', { name: '분야별 바깥 자료' });
    expect(within(table).getAllByRole('rowheader').map((h) => h.textContent)).toEqual(['건설', '제조·생산', '그 밖의 분야']);
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['분야', '날씨', '금속·원자재', '환율', '업체 소식']);
    expect(within(table).getByRole('checkbox', { name: '건설 날씨' })).toBeChecked();
    expect(within(table).getByRole('checkbox', { name: '제조·생산 날씨' })).not.toBeChecked();
    expect(within(table).getByRole('checkbox', { name: '그 밖의 분야 업체 소식' })).toBeChecked();
    expect(within(table).getByRole('checkbox', { name: '그 밖의 분야 환율' })).not.toBeChecked();
    expect(within(c).getByRole('button', { name: '관리 포인트 설정 저장' })).toBeDisabled(); // 바꾼 것이 없다
  });

  test('an out-of-range value is named and blocks saving; a valid edit saves the whole set', async () => {
    show({ tab: 'harness' });
    const c = await card();
    const k = within(c).getByRole('spinbutton', { name: '크리티컬 직전으로 볼 여유' });
    await userEvent.clear(k);
    await userEvent.type(k, '11');
    expect(within(c).getByRole('alert')).toHaveTextContent('0~10 사이 정수로 넣어 주세요.');
    expect(within(c).getByRole('button', { name: '관리 포인트 설정 저장' })).toBeDisabled();
    await userEvent.clear(k);
    await userEvent.type(k, '4');
    await userEvent.click(within(c).getByRole('checkbox', { name: '제조·생산 환율' }));
    await userEvent.click(within(c).getByRole('checkbox', { name: '그 밖의 분야 날씨' }));
    await userEvent.click(within(c).getByRole('button', { name: '관리 포인트 설정 저장' }));
    expect(await within(c).findByRole('status')).toHaveTextContent('관리 포인트 설정을 저장했습니다.');
    expect(pointsPuts).toEqual([{
      points_tf_days: 4, points_window_weeks: 3, points_max_new: 5, points_forecast_reuse_hours: 6, accel_warn_ratio: 0.5,
      points_sources: { construction: ['weather', 'materials', 'fx', 'business'], manufacturing: ['materials', 'business'], _other: ['weather', 'business'] },
    }]);
  });

  test('the ratio takes decimals and names its own range', async () => {
    show({ tab: 'harness' });
    const c = await card();
    const ratio = within(c).getByRole('spinbutton', { name: '당김 효과 경고 비율' });
    await userEvent.clear(ratio);
    await userEvent.type(ratio, '1.01');
    expect(within(c).getByRole('alert')).toHaveTextContent('0.1~1 사이로 넣어 주세요.');
    await userEvent.clear(ratio);
    await userEvent.type(ratio, '0.65');
    expect(within(c).queryByRole('alert')).toBeNull();
    expect(within(c).getByRole('button', { name: '관리 포인트 설정 저장' })).toBeEnabled();
  });

  test('opened from the 관리 포인트 window (focus=points) it scrolls the card into view', async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    show({ tab: 'harness', focus: 'points' });
    await card();
    await vi.waitFor(() => expect(scroll).toHaveBeenCalledWith({ block: 'start' }));
  });
});

describe('실행 추적 — 관리 포인트 단계', () => {
  test('a turn that changed the points shows 계산 → 겨냥 검색 by branch → Search Agent with the cost kind of each call', async () => {
    mockTurn({ ...done(), points: [pointsStage()] });
    show({ tab: 'trace' });
    const stage = await screen.findByRole('region', { name: '관리 포인트 — 5층 사무동 신축 · 버전 2 → 3' });
    expect(stage).toHaveTextContent('찾기 끝');
    expect(stage).toHaveTextContent('포인트 7곳 · 새로 들어옴 2 · 여유 줄어듦 1 · 빠짐 1');
    expect(stage).toHaveTextContent('겨냥 검색 4회');
    expect(stage).toHaveTextContent('날씨 (기상청) 1회기상청 — Liner 비용 없음 · 비용 없음');
    expect(stage).toHaveTextContent('자재·환율 (Premium Data) 2회 (실패 1)Search + Premium Data · $2/1K');
    expect(stage).toHaveTextContent('업체 소식 (MCP search_business) 1회MCP · $2/1K');
    expect(stage).toHaveTextContent('건너뛴 자료 1개');
    expect(stage).toHaveTextContent('Search Agent 2회');
    expect(stage).toHaveTextContent('찾는 중 1');
    expect(stage).toHaveTextContent('Search Agent · $20/1K');
    expect(stage).toHaveTextContent('어림 비용 $0.0460');
  });

  test('a turn without a points change has no stage', async () => {
    mockTurn(done());
    show({ tab: 'trace' });
    await screen.findByRole('list', { name: '실행 추적' });
    expect(screen.queryByRole('region', { name: /^관리 포인트 —/ })).toBeNull();
  });

  test('version changes outside a turn are picked from 관리 포인트 in the picker', async () => {
    mockPointsRuns([pointsStage({ what_if: true, version: 4, trigger: { kind: 'delay', version: 4 }, risk_status: 'looking' })]);
    show({ tab: 'trace' });
    await screen.findByRole('list', { name: '실행 추적' });
    await userEvent.click(screen.getByRole('button', { name: /^요청:/ }));
    const dialog = screen.getByRole('dialog', { name: '요청 고르기' });
    await userEvent.click(within(dialog).getByRole('radio', { name: '관리 포인트' }));
    const pick = await within(dialog).findByRole('button', { name: /5층 사무동 신축 · 가정 · 버전 4 · 지연 기록/ });
    expect(pick).toHaveTextContent('포인트 7 · 새로 2 · 겨냥 검색 4 · Search Agent 2');
    await userEvent.click(pick);
    const stage = await screen.findByRole('region', { name: '관리 포인트 — 5층 사무동 신축 · 가정 · 버전 4 · 지연 기록' });
    expect(stage).toHaveTextContent('바깥 위험 찾는 중');
    expect(screen.queryByRole('list', { name: '실행 추적' })).toBeNull();
    expect(screen.getByRole('button', { name: /^관리 포인트: 5층 사무동 신축/ })).toBeVisible();
  });
});

describe('사용량 — 관리 포인트 호출', () => {
  test('Premium Data, MCP and Search Agent calls are counted with an estimate from the count', async () => {
    mockUsage({
      counters: {
        info_api: { calls: 0, failed: 0 }, weather: { calls: 0, failed: 0 }, searches: { calls: 0, failed: 0 }, reuses: { calls: 0 },
        vision: { calls: 0, input_tokens: 0, output_tokens: 0, cost: null, failed: 0 },
        embedding: { calls: 0, input_tokens: 0, output_tokens: 0, cost: null, failed: 0 },
        knowledge: { calls: 3, failed: 1 }, mcp: { calls: 2, failed: 0 }, search_agent: { calls: 5, failed: 1 },
      },
    });
    show({ tab: 'usage' });
    const group = await screen.findByRole('rowgroup', { name: '관리 포인트 (Liner)' });
    expect(within(group).getByRole('row', { name: /자재·환율 \(Search \+ Premium Data\)/ })).toHaveTextContent('31—어림 $0.0060$2/1K');
    expect(within(group).getByRole('row', { name: /업체 소식/ })).toHaveTextContent('20—어림 $0.0040$2/1K');
    expect(within(group).getByRole('row', { name: /근거 문장 \(Search Agent\)/ })).toHaveTextContent('51—어림 $0.1000$20/1K');
  });
});
