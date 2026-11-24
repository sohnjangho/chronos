// 관리 포인트 카드의 서버 카드 상태와 다시 읽기(폴링) — PointsChangedCard 가 쓴다(계획 5 Task 6).
import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../../../shared/api';
import type { Json } from '../thread';
import { asNum, asText } from './Card';
import type { Frozen } from './PointRisks';
import { getPoints, type QuoteState } from './pointsApi';

export const POLL_MS = 3000;
/** 이만큼 넘게 다시 읽었으면 멈춘다(서버의 멈춘 찾기 판정 15분과 같음). */
export const POLL_CAP_MS = 15 * 60_000;

const isPending = (q: QuoteState | null | undefined) => q?.status === 'pending';

/** 카드 상태: 서버 카드(폴링이 바꿈)·누른 근거 문장 상태·멈춤. */
export interface Live {
  card: Json;
  quotes: Record<string, QuoteState>;
  frozen: Frozen;
}

/** 서버 카드 + 폴링. 바깥 위험을 찾는 중이거나 누른 근거 문장을 찾는 중이면 GET 으로 다시 읽는다(같은 버전일 때만 바꾼다).
 *  다른 버전·404 → old, POLL_CAP_MS 넘음 → cap 으로 멈춘다. 앞 읽기가 안 끝났으면 그 차례는 건너뛴다. 상한의 시작은 카드마다
 *  ref 에 두어 다시 그려도 바뀌지 않는다(기다림이 끝나면 비우고 — 「다시 불러오기」 뒤 기다릴 것이 없을 때도 — 「다시 불러오기」가
 *  새로 잡는다). 사라진 카드에는 늦게 온 답을 적지 않는다. */
export function useLive(data: Json) {
  const [live, setLive] = useState<Live>({ card: data, quotes: {}, frozen: null });
  const inFlight = useRef(false);
  const capStart = useRef<number | null>(null);
  const mounted = useRef(true);
  const sid = asNum(data.schedule_id);
  const version = asNum(data.version);
  const whatIf = data.what_if === true;
  const looking = asText(live.card.risk_status) === 'looking';
  const waiting = live.frozen === null && (looking || Object.values(live.quotes).some(isPending));

  /** 한 번 읽는다: 다른 버전·404 면 old, 아니면 같은 버전 카드·누른 근거 문장 상태를 바꾼다. */
  const readOnce = async (alive: () => boolean): Promise<void> => {
    if (sid === null || inFlight.current) return;
    inFlight.current = true;
    try {
      const r = await getPoints(sid, whatIf);
      if (!alive()) return;
      if (r.version !== version) return setLive((s) => ({ ...s, frozen: 'old' }));
      setLive((s) => {
        const quotes = { ...s.quotes };
        for (const [k, q] of Object.entries(r.quotes ?? {})) if (q && k in quotes) quotes[k] = q;
        return { ...s, card: r.card && r.card.version === version ? r.card : s.card, quotes, frozen: s.frozen === 'cap' ? null : s.frozen };
      });
    } catch (e) {
      if (alive() && e instanceof ApiError && e.status === 404) setLive((s) => ({ ...s, frozen: 'old' })); // 그 밖은 다음 차례에
    } finally {
      inFlight.current = false;
    }
  };

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!waiting || sid === null) {
      if (live.frozen === null) capStart.current = null; // 기다림이 끝남 — 다음 기다림은 새 상한
      return;
    }
    let alive = true;
    capStart.current ??= Date.now();
    const timer = setInterval(() => {
      if (Date.now() - (capStart.current ?? 0) >= POLL_CAP_MS) return void setLive((s) => ({ ...s, frozen: 'cap' }));
      void readOnce(() => alive);
    }, POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [waiting, live.frozen, sid, version, whatIf]); // frozen: 멈춤이 풀렸는데 기다릴 것이 없으면 상한 시작을 비운다

  return {
    live,
    setQuote: (key: string, q: QuoteState) => setLive((s) => ({ ...s, quotes: { ...s.quotes, [key]: q } })),
    setCard: (next: Json) => next.version === version && setLive((s) => ({ ...s, card: next })),
    /** 너무 오래 멈춘 카드의 「다시 불러오기」: 새 상한으로 한 번 읽고(같은 버전이면 멈춤을 풀어 폴링이 다시 켜짐). */
    reload: () => {
      capStart.current = Date.now();
      void readOnce(() => mounted.current);
    },
  };
}
