import { STAGES } from '../labels';
import { asList, asNum, asObj, asText, Card, type CardProps } from './Card';

/** "1회차 위반 3 → 2회차 0". 깨진 초안(-1)은 "깨짐". "위반" 은 첫 숫자 앞에 한 번만. */
export function roundsText(rounds: unknown): string {
  let labeled = false;
  return asList(rounds)
    .map(asObj)
    .map((r) => {
      const v = asNum(r.violations);
      if (v === null || v < 0) return `${asNum(r.n) ?? '?'}회차 깨짐`;
      const text = `${r.n}회차 ${labeled ? '' : '위반 '}${v}`;
      labeled = true;
      return text;
    })
    .join(' → ');
}

/** 생성 단계 카드(Task 9): 지금 단계와 회차별 위반. 같은 턴의 다음 단계 카드가 오면 이 카드를 고쳐 그린다. */
export default function GenerationCard({ data }: CardProps) {
  const stage = asText(data.stage);
  const at = STAGES.findIndex(([id]) => id === stage);
  const rounds = asList(data.rounds);
  const last = asObj(rounds[rounds.length - 1]);
  const count = asNum(last.activity_count);
  return (
    <Card title="일정 만들기" extra={count !== null && count > 0 ? `액티비티 ${count}개` : undefined}>
      <ol className="ch-stages">
        {STAGES.map(([id, label], i) => (
          <li key={id} className={i < at ? 'is-done' : undefined} aria-current={i === at ? 'step' : undefined}>
            {label}
          </li>
        ))}
      </ol>
      {rounds.length > 0 && <p className="ch-rounds">{roundsText(rounds)}</p>}
    </Card>
  );
}
