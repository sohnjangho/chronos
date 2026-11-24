import { useEffect, useState } from 'react';
import { api } from '../shared/api';

export const ATTENTION_POLL_MS = 60_000;

export interface AttentionItem {
  id: number;
  name: string;
  domain: string;
  finish: string | null;
  plan_finish: string | null;
  finish_delta: number | null;
  late_count: number;
  negative_float_count: number;
  violations: number;
  open_delays: number;
  level: 'danger' | 'warning' | 'ok';
  /** 지금 버전의 관리 포인트 수(계획 5). 계산이 안 되는 일정은 null. */
  points_count?: number | null;
  /** 마지막 바뀜의 새 포인트 + 여유가 준 포인트 수(열린 지연이 있으면 그 가정 기준). 등급에는 넣지 않는다. */
  points_changed?: number;
  /** 사진 사람 판독 대기 수(PM 11-24). 사람 판독을 할 수 있는 사람에게만 0 보다 크다. 등급에는 넣지 않는다. */
  human_read_wait?: number;
}

/** 한 줄 까닭. 예: "준공 +4일 · 지연 사건 1건 · 관리 포인트 4곳" */
export function reasonText(i: AttentionItem): string {
  if (i.finish === null) return '일정을 계산할 수 없음';
  const parts: string[] = [];
  if (i.finish_delta !== null && i.finish_delta > 0) parts.push(`준공 +${i.finish_delta}일`);
  if (i.violations > 0) parts.push(`조건 위반 ${i.violations}건`);
  if (i.negative_float_count > 0) parts.push(`여유 부족 ${i.negative_float_count}건`);
  if (i.late_count > 0) parts.push(`늦은 작업 ${i.late_count}개`);
  if (i.open_delays > 0) parts.push(`지연 사건 ${i.open_delays}건`);
  if (i.points_count) parts.push(`관리 포인트 ${i.points_count}곳`);
  return parts.join(' · ');
}

/**
 * 주의할 일정 목록(ok 포함, 서버 차례 그대로). 처음에 읽고 60초마다 다시 읽는다. 창이 안 보이는 동안은 읽지 않고,
 * 다시 보이면 바로 읽는다. 읽기에 실패하면 마지막 값을 둔다(처음부터 실패면 'error').
 */
export function useAttention(): AttentionItem[] | 'error' | null {
  const [state, setState] = useState<AttentionItem[] | 'error' | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => {
      if (document.visibilityState === 'hidden') return;
      api<{ items: AttentionItem[] }>('/api/attention')
        .then((r) => alive && setState(r.items))
        .catch(() => alive && setState((s) => s ?? 'error'));
    };
    load();
    const timer = setInterval(load, ATTENTION_POLL_MS);
    document.addEventListener('visibilitychange', load);
    return () => {
      alive = false;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', load);
    };
  }, []);
  return state;
}
