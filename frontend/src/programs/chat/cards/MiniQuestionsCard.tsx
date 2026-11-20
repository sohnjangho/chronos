import { useState } from 'react';
import Badge from '../../../shared/ui/Badge';
import Button from '../../../shared/ui/Button';
import { asList, asObj, asText, Card, type CardProps } from './Card';

interface Question {
  id: string;
  question: string;
  why: string;
  options: { value: string; label: string; recommended: boolean }[];
  allowFree: boolean;
  assumption: string;
}

const read = (q: unknown): Question => {
  const o = asObj(q);
  const options = asList(o.options)
    .map(asObj)
    .map((x) => ({ value: asText(x.value), label: asText(x.label) || asText(x.value), recommended: x.recommended === true }));
  return { id: asText(o.id), question: asText(o.question), why: asText(o.why), options, allowFree: o.allow_free !== false, assumption: asText(o.assumption) };
};

/** 대화에 보낼 답 글. 답하지 않은 질문은 적어 둔 가정으로(에이전트가 assumed 로 넘긴다). */
export function answerText(questions: Question[], answers: Record<string, string>): string {
  const lines = questions.map((q) => {
    const a = answers[q.id]?.trim();
    return `- ${q.question}: ${a ? a : `답하지 않음 (가정: ${q.assumption})`}`;
  });
  return ['카드 질문에 답합니다.', ...lines].join('\n');
}

function QuestionRow({ q, value, onChange }: { q: Question; value: string; onChange(v: string): void }) {
  const picked = q.options.find((o) => o.label === value);
  return (
    <div className="ch-q">
      <p className="ch-q-text ch-wrap">{q.question}</p>
      {q.why && <p className="ch-muted ch-wrap">{q.why}</p>}
      {q.options.length > 0 && (
        <div className="ch-options">
          {q.options.map((o) => (
            <button key={o.value} type="button" className="ch-pill" aria-pressed={picked === o} onClick={() => onChange(picked === o ? '' : o.label)}>
              <span className="ch-wrap">{o.label}</span>
              {o.recommended && <Badge tone="info">권장</Badge>}
            </button>
          ))}
        </div>
      )}
      {q.allowFree && (
        <input
          className="ch-free"
          aria-label={`${q.question} 직접 입력`}
          placeholder="직접 입력"
          value={picked ? '' : value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {q.assumption && <p className="ch-muted ch-wrap">답하지 않으면: {q.assumption}</p>}
    </div>
  );
}

/** 질문 두 개 이하(ask.questionnaire 의 카드 모드). 고르거나 적은 답을 한 번에 대화로 보낸다. */
export default function MiniQuestionsCard({ data, ctx }: CardProps) {
  const questions = asList(data.questions).map(read);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [state, setState] = useState<'idle' | 'sending' | 'sent'>('idle');
  async function submit() {
    setState('sending');
    setState((await ctx.sendText(answerText(questions, answers))) ? 'sent' : 'idle');
  }
  return (
    <Card title={asText(data.title) || '확인할 것'}>
      {questions.map((q) => (
        <QuestionRow key={q.id} q={q} value={answers[q.id] ?? ''} onChange={(v) => setAnswers((a) => ({ ...a, [q.id]: v }))} />
      ))}
      <div className="ch-actions">
        <Button variant="primary" disabled={state !== 'idle' || questions.length === 0} onClick={() => void submit()}>
          {state === 'sent' ? '보냈습니다' : '답 보내기'}
        </Button>
      </div>
    </Card>
  );
}
