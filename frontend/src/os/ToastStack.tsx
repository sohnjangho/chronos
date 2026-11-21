// OS 우측 상단 슬라이드 토스트 알림(저장·스킬 등록·창 스냅 등 짧은 피드백).
import { create } from 'zustand';

export type ToastTone = 'info' | 'success' | 'warning';

interface ToastItem {
  id: number;
  text: string;
  tone: ToastTone;
}

let nextId = 1;

export const useToast = create<{
  items: ToastItem[];
  push(text: string, tone?: ToastTone): void;
  dismiss(id: number): void;
}>((set) => ({
  items: [],
  push(text, tone = 'info') {
    const id = nextId++;
    set((s) => ({ items: [...s.items.slice(-3), { id, text, tone }] }));
    setTimeout(() => set((s) => ({ items: s.items.filter((t) => t.id !== id) })), 3200);
  },
  dismiss(id) {
    set((s) => ({ items: s.items.filter((t) => t.id !== id) }));
  },
}));

export const pushToast = (text: string, tone: ToastTone = 'info') => useToast.getState().push(text, tone);

export default function ToastStack() {
  const items = useToast((s) => s.items);
  const dismiss = useToast((s) => s.dismiss);
  if (!items.length) return null;
  return (
    <div className="os-toasts" aria-live="polite">
      {items.map((t) => (
        <button key={t.id} type="button" className={`os-toast is-${t.tone}`} onClick={() => dismiss(t.id)}>
          <span className="os-toast-dot" aria-hidden="true" />
          <span>{t.text}</span>
        </button>
      ))}
    </div>
  );
}
