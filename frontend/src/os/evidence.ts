import { create } from 'zustand';

/** Context 패널 「근거」 탭의 한 줄. */
export interface EvidenceItem {
  label: string;
  value: string;
  detail?: string;
}

interface EvidenceState {
  /** 창 id → 그 창이 넘긴 근거. */
  byWindow: Record<string, EvidenceItem[]>;
  /** 프로그램이 자기 창의 근거를 넘긴다(null 이면 지움). */
  setEvidence(windowId: string, items: EvidenceItem[] | null): void;
}

export const useEvidence = create<EvidenceState>((set) => ({
  byWindow: {},
  setEvidence: (windowId, items) =>
    set((s) => {
      const byWindow = { ...s.byWindow };
      if (items) byWindow[windowId] = items;
      else delete byWindow[windowId];
      return { byWindow };
    }),
}));
