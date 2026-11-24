// 다른 화면에서 연락 시작하기(Task 104) — 스케줄·간트·현장 허브·승인함이 쓰는 단추. 누르면 공용 BatchSendDialog(Task 103)를 연다:
// 받는 사람 고르기·내용 확인·보내기·결과는 모두 그 창이 한다(이 단추는 보내지 않는다). 현장 관리자에게는 그리지 않고(서버도 403),
// 알림 연결이 없으면 흐리게 「알림 연결이 없습니다」. 여는 쪽의 까닭(예: 고른 작업 행이 없음)이 있으면 그 까닭으로 흐리게.
// 창은 이 단추가 든 창 본문(.os-win-body — position: relative)에 붙여 그 창만 덮고, 창 본문이 없으면(모바일) 화면 전체를 덮는다.
import { useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Button from '../ui/Button';
import BatchSendDialog, { type BatchPreset } from './BatchSendDialog';
import { useCanContact, useNotifyReady } from './contactKit';

export const NO_CONNECTION = '알림 연결이 없습니다';
const COVER = { position: 'fixed', inset: 0, zIndex: 1000 } as const;

export interface ContactButtonProps {
  scheduleId: number;
  /** 연결할 작업(preset.activityId 보다 앞선다). */
  activityId?: string;
  preset: BatchPreset;
  /** 단추 글(기본 「연락」). */
  label?: string;
  /** 창 제목(기본 단추 글). */
  title?: string;
  /** 여는 쪽이 지금 열 수 없다고 하면 그 까닭(흐리게 + title). */
  blocked?: string | null;
  variant?: 'default' | 'primary';
  className?: string;
}

export default function ContactButton({ scheduleId, activityId, preset, label = '연락', title, blocked, variant, className }: ContactButtonProps) {
  const can = useCanContact();
  const ready = useNotifyReady(can);
  const [open, setOpen] = useState(false);
  const [host, setHost] = useState<HTMLElement | null>(null);
  const ref = useRef<HTMLButtonElement | null>(null); // 창을 닫으면 초점을 돌려줄 단추
  if (!can) return null;
  const why = ready === false ? NO_CONNECTION : (blocked ?? null);
  const full: BatchPreset = activityId ? { ...preset, activityId } : preset;
  const close = () => {
    setOpen(false);
    ref.current?.focus();
  };
  const dialog = open && (
    <BatchSendDialog scheduleId={scheduleId} title={title ?? label} preset={full} onClose={close} />
  );
  return (
    <>
      <Button
        variant={variant}
        className={className}
        disabled={ready !== true || !!why}
        title={why ?? undefined}
        onClick={(e) => {
          ref.current = e.currentTarget;
          setHost(e.currentTarget.closest<HTMLElement>('.os-win-body'));
          setOpen(true);
        }}
      >
        {label}
      </Button>
      {dialog && createPortal(host ? dialog : <div style={COVER}>{dialog}</div>, host ?? document.body)}
    </>
  );
}
