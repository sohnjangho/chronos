// 개발 콘솔 — 하루 LLM 비용 상한(11-25): 하네스 탭의 설정 카드(저장·비우기·환경 변수로 정해짐) · 사용량 탭의 「오늘 $a / 상한 $b」.
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import DevConsole from './DevConsole';
import { llmCapPuts, mockLlmCap, mockUsage, setup } from './testKit';

const show = (params?: Record<string, string>) => render(<DevConsole windowId="w1" params={params} />);
async function card() {
  const c = await screen.findByRole('region', { name: '하루 LLM 비용 상한' });
  await within(c).findByText(/^오늘 \$/); // 상한을 읽은 뒤
  return c;
}

beforeEach(() => {
  localStorage.clear();
  setup();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('하네스 탭 — 하루 LLM 비용 상한', () => {
  test('off by default, saves a cap and clears it back to none', async () => {
    mockLlmCap({ spent_today_usd: 1.5 });
    show({ tab: 'harness' });
    const c = await card();
    const input = within(c).getByRole('spinbutton', { name: '하루 LLM 비용 상한(USD)' });
    expect(input).toHaveValue(null);
    expect(c).toHaveTextContent('오늘 $1.50 / 상한 없음');
    await userEvent.type(input, '10');
    await userEvent.click(within(c).getByRole('button', { name: '상한 저장' }));
    expect(await within(c).findByRole('status')).toHaveTextContent('상한을 저장했습니다.');
    expect(c).toHaveTextContent('오늘 $1.50 / 상한 $10.00');
    await userEvent.clear(input);
    await userEvent.click(within(c).getByRole('button', { name: '상한 저장' }));
    await within(c).findByText('오늘 $1.50 / 상한 없음');
    expect(llmCapPuts).toEqual([{ cap_usd: 10 }, { cap_usd: null }]);
  });

  test('refuses zero or negative before sending', async () => {
    show({ tab: 'harness' });
    const c = await card();
    await userEvent.type(within(c).getByRole('spinbutton', { name: '하루 LLM 비용 상한(USD)' }), '0');
    expect(within(c).getByRole('button', { name: '상한 저장' })).toBeDisabled();
    expect(within(c).getByRole('alert')).toHaveTextContent('0보다 큰 금액');
    expect(llmCapPuts).toEqual([]);
  });

  test('a cap fixed by the environment is shown read-only', async () => {
    mockLlmCap({ cap_usd: 5, fixed_by_env: true });
    show({ tab: 'harness' });
    const c = await card();
    expect(within(c).getByRole('spinbutton', { name: '하루 LLM 비용 상한(USD)' })).toBeDisabled();
    expect(within(c).getByRole('spinbutton', { name: '하루 LLM 비용 상한(USD)' })).toHaveValue(5);
    expect(c).toHaveTextContent('환경 변수 CHRONOS_LLM_DAILY_USD 로 정해져 있어');
    expect(within(c).queryByRole('button', { name: '상한 저장' })).toBeNull();
  });
});

describe('사용량 탭 — 오늘 쓴 돈', () => {
  test('shows today and the cap, or no cap', async () => {
    mockUsage({ llm_cap: { cap_usd: 10, fixed_by_env: false, spent_today_usd: 2.345 } });
    const { unmount } = show({ tab: 'usage' });
    expect(await screen.findByText('오늘 $2.35 / 상한 $10.00')).toBeVisible();
    unmount();
    mockUsage({ llm_cap: { cap_usd: null, fixed_by_env: false, spent_today_usd: 0 } });
    show({ tab: 'usage' });
    expect(await screen.findByText('오늘 $0.00 / 상한 없음')).toBeVisible();
  });
});
