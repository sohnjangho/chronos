// 카드 틀과 여러 카드가 함께 쓰는 조각. 카드 data 는 서버가 보낸 그대로라 칸이 빠져 있어도 그릴 수 있어야 한다.
import type { ReactNode } from 'react';
import { useWindows } from '../../../os/windowStore';
import Button from '../../../shared/ui/Button';
import { dotDate, reasonLabel } from '../labels';
import type { Json } from '../thread';

/** 카드가 대화에서 쓸 수 있는 것. */
export interface CardCtx {
  sessionId: number | null;
  /** 대화에 글을 보낸다(미니 질문의 답). 서버가 받으면 true. */
  sendText(text: string): Promise<boolean>;
}

export interface CardProps {
  data: Json;
  ctx: CardCtx;
}

export const asList = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
export const asObj = (v: unknown): Json => (typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Json) : {});
export const asNum = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
export const asText = (v: unknown): string => (typeof v === 'string' ? v : v === null || v === undefined ? '' : String(v));

/** 제목 줄이 있는 카드(region, 이름 = 제목). */
export function Card({ title, extra, tone, children }: { title: string; extra?: ReactNode; tone?: 'warn' | 'bad'; children: ReactNode }) {
  return (
    <section className={`ch-card${tone ? ` is-${tone}` : ''}`} aria-label={title}>
      <h4 className="ch-card-h">
        <span className="ch-wrap">{title}</span>
        {extra && <span className="ch-card-extra">{extra}</span>}
      </h4>
      <div className="ch-card-b">{children}</div>
    </section>
  );
}

/** 질문지 창을 이 대화와 함께 연다(제출 뒤 이 대화로 이어 가도록 — Task 15). */
export function OpenQuestionnaire({ id, ctx }: { id: unknown; ctx: CardCtx }) {
  if (id === undefined || id === null) return null;
  const params = { id: String(id), ...(ctx.sessionId !== null && { session: String(ctx.sessionId) }) };
  return <Button onClick={() => useWindows.getState().open('questionnaire', params)}>질문지 열기</Button>;
}

const signed = (n: number) => (n > 0 ? `+${n}` : String(n));

function finishLine(f: Json): string | null {
  const after = dotDate(f.after);
  if (!after) return null;
  if (f.before === null || f.before === undefined) return after;
  const delta = asNum(f.delta_days);
  const change = delta === null ? '' : delta === 0 ? ' (변동 없음)' : ` (${signed(delta)}일)`;
  return `${dotDate(f.before)} → ${after}${change}`;
}

function criticalLine(c: Json): string | null {
  const after = asNum(c.after_count);
  if (after === null) return null;
  const before = asNum(c.before_count);
  return `${before === null ? '' : `${before} → `}${after}개${c.path_changed === true ? ' · 경로 바뀜' : ''}`;
}

function floatLine(f: Json): string | null {
  const after = asNum(f.after);
  if (after === null) return null;
  const before = asNum(f.before);
  return `${before === null ? '' : `${before} → `}${after}일(근무일)`;
}

/** 점검 결과. 자동 점검 안 된 조건은 통과에 넣지 않고 따로 센다. */
export function checkLine(check: Json): string | null {
  if (Object.keys(check).length === 0) return null;
  const parts = [`통과 ${asNum(check.passed) ?? 0}`, `위반 ${asList(check.violations).length}`, `자동 점검 안 됨 ${asNum(check.uncheckable) ?? 0}`];
  const invalid = asNum(check.invalid) ?? 0;
  return parts.join(' · ') + (invalid ? ` · 형식 틀림 ${invalid}` : '');
}

/** 승인 요청·자동 적용 카드의 요약 숫자(Task 11 summary_json). */
export function SummaryLines({ summary }: { summary: unknown }) {
  const s = asObj(summary);
  const check = asObj(s.check);
  const rows: [string, string | null][] = [
    ['준공', finishLine(asObj(s.finish))],
    ['크리티컬', criticalLine(asObj(s.critical))],
    ['기한까지 여유', floatLine(asObj(s.finish_float))],
    ['바뀐 액티비티', asNum(s.changed_count) === null ? null : `${s.changed_count}개`],
    ['조건 점검', checkLine(check)],
  ];
  const violations = asList(check.violations).map((v) => asText(asObj(v).message)).filter(Boolean);
  const changed = asList(s.conditions_changed).map(asObj);
  return (
    <>
      <dl className="ch-kv">
        {rows
          .filter((r): r is [string, string] => r[1] !== null)
          .map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd className="ch-wrap">{v}</dd>
            </div>
          ))}
        {changed.length > 0 && (
          <div>
            <dt>바뀐 조건</dt>
            <dd>
              <ul className="ch-plain">
                {changed.map((c, i) => (
                  <li key={i} className="ch-wrap">{`${asText(c.name) || asText(c.id)} ${asText(c.before) || '없음'} → ${asText(c.after) || '없음'}`}</li>
                ))}
              </ul>
            </dd>
          </div>
        )}
      </dl>
      {violations.length > 0 && (
        <ul className="ch-plain ch-violations">
          {violations.map((m, i) => (
            <li key={i} className="ch-wrap">{m}</li>
          ))}
        </ul>
      )}
    </>
  );
}

export const reasonTone = (r: string) => (r === 'condition_violated' ? 'danger' : 'warning');
export { reasonLabel };
