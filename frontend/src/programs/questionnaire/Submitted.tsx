import { useId } from 'react';
import Badge from '../../shared/ui/Badge';
import type { QView } from './qApi';
import { flatten } from './model';

interface Row {
  key: string;
  label: string;
  value: string;
}

/** 제출한 질문지: 읽기만. 답한 것과 가정으로 둔 것을 나눠 보인다. */
export default function Submitted({ view, notice }: { view: QView; notice: string | null }) {
  const all = flatten(view);
  const answered = all.filter((q) => q.answer);
  const assumed = all.filter((q) => !q.answer);
  return (
    <div className="qn-done">
      <div className="qn-done-head">
        <Badge tone="success">제출됨</Badge>
        <h2 className="qn-done-title">{view.title}</h2>
      </div>
      {notice && (
        <p className="qn-done-note" role="status">
          {notice}
        </p>
      )}
      <p className="qn-done-count">{`답 ${answered.length}개 · 가정 ${assumed.length}개`}</p>
      <Summary title="답한 것" empty="답한 질문이 없습니다." rows={answered.map((q) => ({ key: q.id, label: q.question, value: q.answer!.label }))} />
      <Summary title="가정으로 둔 것" empty="가정으로 둔 질문이 없습니다." rows={assumed.map((q) => ({ key: q.id, label: q.question, value: q.assumption }))} />
      {view.prefilled.length > 0 && (
        <Summary
          title="대화·자료에서 채운 것"
          empty=""
          rows={view.prefilled.map((p, i) => ({ key: String(i), label: p.label, value: `${p.value} (${p.source})` }))}
        />
      )}
    </div>
  );
}

function Summary({ title, rows, empty }: { title: string; rows: Row[]; empty: string }) {
  const headingId = useId();
  return (
    <section className="qn-card" aria-labelledby={headingId}>
      <h3 id={headingId} className="qn-sub">
        {title}
      </h3>
      {rows.length === 0 ? (
        <p className="qn-muted">{empty}</p>
      ) : (
        <ul className="qn-rows qn-sum">
          {rows.map((r) => (
            <li key={r.key} className="qn-sum-row">
              <span className="qn-row-k">{r.label}</span>
              <b className="qn-row-v">{r.value}</b>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
