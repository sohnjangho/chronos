import { useEffect } from 'react';
import { create } from 'zustand';
import { api } from '../shared/api';

export const APPROVALS_POLL_MS = 30_000;

/** 승인 대기 수(메뉴바·Dock 배지, 승인 대기 위젯). ticks 는 다시 읽을 때마다 하나씩 는다(위젯이 목록을 다시 읽는 신호). */
export const useApprovals = create<{ pending: number; ticks: number }>(() => ({ pending: 0, ticks: 0 }));

/** 다시 읽는다. 실패하면 조용히 마지막 값을 둔다. 승인함 화면이 결정 뒤에 불러도 된다. */
export async function refreshApprovals(): Promise<void> {
  try {
    const { pending } = await api<{ pending: number }>('/api/approvals/count');
    useApprovals.setState((s) => ({ pending, ticks: s.ticks + 1 }));
  } catch {
    // 배지는 조용히 실패한다(마지막 값 유지).
    useApprovals.setState((s) => ({ ticks: s.ticks + 1 }));
  }
}

/** 30초마다, 그리고 브라우저 탭이 다시 앞에 오면 다시 읽는다. */
export function useApprovalPolling(): void {
  useEffect(() => {
    void refreshApprovals();
    const timer = setInterval(() => void refreshApprovals(), APPROVALS_POLL_MS);
    const onFocus = () => void refreshApprovals();
    window.addEventListener('focus', onFocus);
    return () => {
      clearInterval(timer);
      window.removeEventListener('focus', onFocus);
    };
  }, []);
}
