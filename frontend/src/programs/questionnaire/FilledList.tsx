import { useId } from 'react';
import Button from '../../shared/ui/Button';
import type { Prefilled, QQuestion } from './qApi';

interface Props {
  /** 에이전트가 대화·자료에서 미리 채운 것(읽기만). */
  prefilled: Prefilled[];
  /** 지금 묶음에서 답한 질문. */
  answered: QQuestion[];
  onEdit(questionId: string): void;
}

/** "이미 채운 것": 미리 채운 것(출처, 고치려면 대화로) · 이 묶음에서 답한 것([고치기]). */
export default function FilledList({ prefilled, answered, onEdit }: Props) {
  const headingId = useId();
  return (
    <section className="qn-card qn-filled" aria-labelledby={headingId}>
      <h3 id={headingId} className="qn-sub">
        이미 채운 것
      </h3>
      {prefilled.length > 0 && (
        <div className="qn-fgroup">
          <p className="qn-fhead">
            <span>대화·자료에서 채운 것</span>
            <span className="qn-muted">고치려면 대화로 말해 주세요</span>
          </p>
          <ul className="qn-rows">
            {prefilled.map((p, i) => (
              <li key={i} className="qn-row">
                <span className="qn-row-k">{p.label}</span>
                <b className="qn-row-v">{p.value}</b>
                <span className="qn-src">{p.source}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="qn-fgroup">
        <p className="qn-fhead">
          <span>이 묶음에서 답한 것</span>
        </p>
        {answered.length === 0 ? (
          <p className="qn-muted">이 묶음에서 아직 답한 질문이 없습니다.</p>
        ) : (
          <ul className="qn-rows">
            {answered.map((q) => (
              <li key={q.id} className="qn-row">
                <span className="qn-row-k">{q.question}</span>
                <b className="qn-row-v">{q.answer?.label}</b>
                <span className="qn-src">질문지</span>
                <Button onClick={() => onEdit(q.id)}>고치기</Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
