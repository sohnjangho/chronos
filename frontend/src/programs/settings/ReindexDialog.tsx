// 임베딩 모델 바꾸기 확인 창(시안 설정 A — 가운데 창). 처음 포커스는 [취소], Esc 도 취소.
import { useRef } from 'react';
import { useModalFocus } from '../../os/modalFocus';
import Button from '../../shared/ui/Button';
import type { ModelInfo } from './model';
import { priceText } from './models';

interface Props {
  /** 지금 배정된 모델 id. */
  from: string;
  /** 새로 고른 모델(목록에 없으면 id 만). */
  to: string;
  toInfo: ModelInfo | undefined;
  busy: boolean;
  onConfirm(): void;
  onCancel(): void;
}

/** 비용 참고: 새 모델의 공개 가격(입력 100만 토큰당). 자료·조각 수를 주는 API 가 없어 총액은 셈하지 않는다. */
function PriceLine({ model }: { model: ModelInfo | undefined }) {
  if (!model?.price) return <dd>가격표에 없는 모델입니다.</dd>;
  return <dd>{`${priceText(model.price)} · Liner 공개 가격표(${model.price.as_of})`}</dd>;
}

export default function ReindexDialog({ from, to, toInfo, busy, onConfirm, onCancel }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const trap = useModalFocus(ref);
  const title = '임베딩 모델을 바꿀까요?';
  return (
    <div className="st-scrim">
      <div
        ref={ref}
        className="st-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onCancel();
          trap(e);
        }}
      >
        <h3>{title}</h3>
        <p>자료를 새 모델로 다시 넣습니다.</p>
        <dl className="st-facts st-facts-wide">
          <dt>지금</dt>
          <dd>{from}</dd>
          <dt>새 모델</dt>
          <dd>{to}</dd>
          <dt>비용 참고</dt>
          <PriceLine model={toInfo} />
        </dl>
        <p className="st-note">
          다 끝날 때까지 찾기는 지금 모델로 합니다. 끝나면 새 모델로 바꾸고 옛 자료는 지웁니다. 그 사이 새로 올린 파일은 두 곳에 모두 넣습니다.
        </p>
        <div className="st-dialog-row">
          <Button autoFocus disabled={busy} onClick={onCancel}>
            취소
          </Button>
          <Button variant="primary" disabled={busy} onClick={onConfirm}>
            다시 넣기 시작
          </Button>
        </div>
      </div>
    </div>
  );
}
