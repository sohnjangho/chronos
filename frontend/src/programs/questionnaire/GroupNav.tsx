import type { QGroup, QView } from './qApi';
import { firstOpen } from './model';

interface Props {
  view: QView;
  currentId: string;
  onPick(questionId: string): void;
}

/** 왼쪽: 진행 줄 · 묶음 목차(초록 = 모두 답함, 회색 = 남은 질문 있음) · 지금 묶음의 질문들. */
export default function GroupNav({ view, currentId, onPick }: Props) {
  const { answered, total } = view.progress;
  const rest = total - answered;
  const pct = total > 0 ? Math.round((answered * 100) / total) : 0;
  return (
    <nav className="qn-nav" aria-label="질문 목차">
      <div className="qn-progress">
        <p className="qn-progress-text">{`질문 ${total}개 중 ${answered}개 답함${rest > 0 ? ` · 나머지 ${rest}개는 가정으로` : ''}`}</p>
        <div className="qn-bar" role="progressbar" aria-label="답한 질문" aria-valuemin={0} aria-valuemax={total} aria-valuenow={answered}>
          <i style={{ width: `${pct}%` }} />
        </div>
      </div>
      <ul className="qn-groups">
        {view.groups.map((g) => (
          <GroupEntry key={g.name} group={g} currentId={currentId} onPick={onPick} />
        ))}
      </ul>
      <p className="qn-legend">초록: 모두 답함 · 회색: 남은 질문 있음</p>
    </nav>
  );
}

function GroupEntry({ group: g, currentId, onPick }: { group: QGroup; currentId: string; onPick(id: string): void }) {
  const done = g.answered === g.total;
  const open = g.questions.some((q) => q.id === currentId);
  return (
    <li>
      <button
        type="button"
        className="qn-grp"
        data-state={done ? 'done' : 'open'}
        aria-current={open ? 'true' : undefined}
        aria-label={`${g.name} · ${done ? '모두 답함' : '남은 질문 있음'} · ${g.answered} / ${g.total}`}
        onClick={() => onPick(firstOpen(g.questions)!.id)}
      >
        <span className="qn-dot" aria-hidden="true" />
        <span className="qn-grp-name">{g.name}</span>
        <span className="qn-count" aria-hidden="true">{`${g.answered} / ${g.total}`}</span>
      </button>
      {open && (
        <ul className="qn-items">
          {g.questions.map((q) => (
            <li key={q.id}>
              <button
                type="button"
                className="qn-item"
                data-state={q.answer ? 'done' : 'open'}
                aria-current={q.id === currentId ? 'step' : undefined}
                title={q.question}
                onClick={() => onPick(q.id)}
              >
                <span className="qn-dot" aria-hidden="true" />
                <span className="qn-item-text">
                  {q.question}
                  {q.answer && <b>{` · ${q.answer.label}`}</b>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
