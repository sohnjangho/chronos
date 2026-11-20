import { create } from 'zustand';
import { api, ApiError } from '../shared/api';
import { streamPost } from '../shared/sse';
import type { ContextSource } from './contextStore';
import { useWindows } from './windowStore';

export interface ChatLine {
  who: 'me' | 'agent' | 'error';
  text: string;
}

interface AiChatState {
  /** 이 대화가 묶인 일정. 일정이 바뀌면 대화를 비운다. */
  scheduleId: number | null;
  lines: ChatLine[];
  busy: boolean;
  sessionId: number | null;
  /** 일정에 묶는다. 다른 일정이면 도는 답을 멈추고 대화를 비운다. */
  bindSchedule(scheduleId: number | null): void;
  /** 출처 창의 지금 맥락(보낼 때의 창 params)으로 묻는다. 첫 질문에 대화를 만든다. */
  ask(text: string, source: ContextSource): Promise<void>;
  /** 도는 답을 멈추고 비운다(로그아웃·사용자 바뀜·일정 바뀜). */
  reset(): void;
}

/** 질문에 붙일 화면 맥락: 출처 창의 프로그램, 일정, 보낼 때 그 창에서 고른 액티비티(창 params 를 그때 읽는다). */
function contextUi(source: ContextSource, scheduleId: number | null) {
  const live = useWindows.getState().wins.find((w) => w.id === source.id);
  const activity = (live?.params ?? source.params)?.activity;
  return { program: source.programId, ...(scheduleId !== null && { schedule_id: scheduleId }), ...(activity && { selected_activity: activity }) };
}

// 도는 답은 패널·탭이 닫혀도 이어진다. 멈춤은 reset 만 한다.
let controller: AbortController | null = null;
let generation = 0;

/** Context 패널 「AI」 탭의 대화. 탭을 바꾸거나 패널을 닫아도 남는다. */
export const useAiChat = create<AiChatState>((set, get) => {
  const add = (gen: number, line: ChatLine) => gen === generation && set((s) => ({ lines: [...s.lines, line] }));
  return {
    scheduleId: null,
    lines: [],
    busy: false,
    sessionId: null,
    bindSchedule(scheduleId) {
      if (get().scheduleId === scheduleId) return;
      get().reset();
      set({ scheduleId });
    },
    async ask(text, source) {
      const gen = generation;
      const { scheduleId } = get();
      add(gen, { who: 'me', text });
      set({ busy: true });
      controller = new AbortController();
      const ui = contextUi(source, scheduleId);
      try {
        const id =
          get().sessionId ??
          (await api<{ id: number }>('/api/chat/sessions', { method: 'POST', body: JSON.stringify({ schedule_id: scheduleId }) })).id;
        if (gen !== generation) return;
        set({ sessionId: id });
        await streamPost(
          `/api/chat/sessions/${id}/messages`,
          { text, ui },
          (type, data) => {
            const d = data as { text?: string; message?: string };
            if (type === 'text' && d.text) add(gen, { who: 'agent', text: d.text });
            if (type === 'error') add(gen, { who: 'error', text: d.message ?? '처리 중 문제가 생겼습니다.' });
          },
          controller.signal,
        );
      } catch (err) {
        add(gen, { who: 'error', text: err instanceof ApiError ? err.message : '처리 중 문제가 생겼습니다.' });
      } finally {
        if (gen === generation) set({ busy: false });
      }
    },
    reset() {
      controller?.abort();
      controller = null;
      generation += 1;
      set({ scheduleId: null, lines: [], busy: false, sessionId: null });
    },
  };
});
