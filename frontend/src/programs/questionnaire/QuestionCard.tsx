import { useEffect, useId, useRef, useState, type RefObject } from 'react';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import type { QQuestion } from './qApi';
import type { FocusRequest } from './model';

interface Props {
  question: QQuestion;
  /** 지금 고른 값: 보내는 중인 값이 있으면 그것, 없으면 서버 답. 선택지 눌림·[가정대로 두기]가 이것을 따른다. */
  chosen: string | null;
  /** n 이 바뀔 때마다 초점을 옮긴다 — heading: 질문 제목, input: 직접 입력 칸(없으면 고른 선택지·첫 선택지). */
  focusRequest?: FocusRequest;
  /** null 이면 답을 지운다(가정대로). 성공하면 true. */
  onAnswer(value: string | null): Promise<boolean>;
}

/** 오른쪽: 질문 하나 — 왜 묻나요 · 선택지(추천·힌트) · 직접 입력 · 답하지 않으면 쓰는 가정. */
export default function QuestionCard({ question: q, chosen, focusRequest, onAnswer }: Props) {
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const free = useRef<HTMLInputElement>(null);
  const opts = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!focusRequest) return;
    if (focusRequest.target === 'heading') return heading.current?.focus();
    const picked = opts.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"]') ?? opts.current?.querySelector('button');
    (free.current ?? picked)?.focus();
  }, [focusRequest]);
  return (
    <section className="qn-card" aria-labelledby={headingId}>
      <h2 id={headingId} className="qn-q" tabIndex={-1} ref={heading}>
        {q.question}
      </h2>
      {q.why && (
        <p className="qn-why">
          <span className="qn-why-k">왜 묻나요</span>
          <span>{q.why}</span>
        </p>
      )}
      {q.options.length > 0 && (
        <div className="qn-opts" role="group" aria-label="선택지" ref={opts}>
          {q.options.map((o) => {
            const on = chosen === o.value;
            return (
              <button key={o.value} type="button" className="qn-opt" aria-pressed={on} onClick={() => void (on || onAnswer(o.value))}>
                <span className="qn-radio" aria-hidden="true" />
                <span className="qn-opt-body">
                  <span>{o.label}</span>
                  {o.hint && <span className="qn-opt-hint">{o.hint}</span>}
                </span>
                {o.recommended && <Badge tone="info">추천</Badge>}
              </button>
            );
          })}
        </div>
      )}
      {q.allow_free && <FreeInput question={q} inputRef={free} onAnswer={onAnswer} />}
      <div className="qn-assume">
        <span className="qn-assume-text">{`답하지 않으면: ${q.assumption}`}</span>
        <Button disabled={chosen === null} onClick={() => void onAnswer(null)}>
          가정대로 두기
        </Button>
      </div>
    </section>
  );
}

/** 선택지에 없는 답(직접 적은 글). 선택지를 골랐으면 빈 칸. */
const freeText = (q: QQuestion) => (q.answer && !q.options.some((o) => o.value === q.answer!.value) ? q.answer.value : '');

/** Enter(한글 조합 중이 아닐 때)나 칸을 나갈 때만 보낸다. 같은 글은 다시 보내지 않는다. */
function FreeInput({ question: q, inputRef, onAnswer }: { question: QQuestion; inputRef: RefObject<HTMLInputElement | null>; onAnswer: Props['onAnswer'] }) {
  const [text, setText] = useState(() => freeText(q));
  const sent = useRef<string | null>(q.answer?.value ?? null);
  const stored = q.answer?.value ?? null;
  // 서버가 돌려준 답이 바뀔 때만 칸을 맞춘다. 보낸 뒤에 더 적은 글(저장 안 된 초안)은 덮지 않는다.
  useEffect(() => {
    const before = sent.current;
    setText((t) => (t.trim() === '' || t.trim() === (before ?? '') ? freeText(q) : t));
    sent.current = stored;
  }, [stored]); // eslint 의 hooks 규칙은 쓰지 않는다 — q 는 일부러 뺐다
  const commit = async () => {
    const value = text.trim();
    if (!value || value === sent.current) return;
    const before = sent.current;
    sent.current = value;
    if (!(await onAnswer(value))) sent.current = before;
  };
  return (
    <div className="qn-free">
      <input
        ref={inputRef}
        className="qn-input"
        aria-label="직접 입력"
        maxLength={500}
        value={text}
        placeholder={q.options.length > 0 ? '직접 입력 — 선택지에 없으면 여기에 적어 주세요' : '답을 적어 주세요'}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key !== 'Enter' || e.nativeEvent.isComposing) return;
          e.preventDefault();
          void commit();
        }}
        onBlur={() => void commit()}
      />
      <p className="qn-hint">Enter 를 누르거나 칸을 나가면 저장합니다.</p>
    </div>
  );
}
