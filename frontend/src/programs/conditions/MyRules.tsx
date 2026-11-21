// ③ 칸 아래: 저장된 내 규칙 목록(Task 35). 범위 배지 · 켜짐 스위치 · [지우기](만든 사람이나 관리자) ·
// 이 일정에 없는 규칙은 [이 일정에 넣기] → 조건 미리 보기({add}) → 기존 미리 보기 띠 → [확정].
// 규칙을 끄거나 지워도 이미 그 조건을 가진 일정은 그대로다(일정은 사본을 가진다).
import { useEffect, useState } from 'react';
import { useSession } from '../../os/session';
import { ApiError } from '../../shared/api';
import { domainLabel } from '../../shared/domainLabels';
import Button from '../../shared/ui/Button';
import { isAdd, rulesApi, type MyRule } from './condApi';
import type { ConditionsModel } from './condStore';

const messageOf = (e: unknown) => (e instanceof ApiError ? e.message : '요청을 처리할 수 없습니다.');

/** "분야 전체 · 건설" / "이 일정". */
export const scopeLabel = (r: Pick<MyRule, 'scope' | 'domain'>) =>
  r.scope === 'schedule' ? '이 일정' : `분야 전체 · ${domainLabel(r.domain)}`;

/** 이 일정의 내 규칙 목록. 저장 버전이 바뀌면(확정 뒤) 다시 읽어 in_schedule 을 맞춘다. */
function useRules(scheduleId: number, version: number) {
  const [rules, setRules] = useState<MyRule[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    rulesApi.list(scheduleId).then(
      (r) => live && (setRules(r), setProblem(null)),
      (e) => live && setProblem(`내 규칙을 읽지 못했습니다: ${messageOf(e)}`),
    );
    return () => void (live = false);
  }, [scheduleId, version]);
  return { rules, setRules, problem, setProblem };
}

interface RowProps {
  rule: MyRule;
  adding: boolean;
  /** 만든 사람이나 관리자: 켜고 끄기·지우기. */
  canDelete: boolean;
  onToggle(enabled: boolean): void;
  onAdd(): void;
  onDelete(): void;
}

function AddCell({ rule, adding, onAdd }: Pick<RowProps, 'rule' | 'adding' | 'onAdd'>) {
  if (rule.in_schedule) return <span className="cd-muted">이 일정에 있음</span>;
  if (adding) return <span className="cd-rule-adding">미리 보기에 넣음</span>;
  return (
    <Button disabled={!rule.enabled} title={rule.enabled ? undefined : '꺼진 규칙은 넣을 수 없습니다'} onClick={onAdd}>
      이 일정에 넣기
    </Button>
  );
}

function RuleRow({ rule, adding, canDelete, onToggle, onAdd, onDelete }: RowProps) {
  const [asking, setAsking] = useState(false);
  const text = rule.condition.text;
  return (
    <li className={`cd-rule${rule.enabled ? '' : ' is-off'}`} aria-label={text}>
      <div className="cd-rule-line">
        <span className={`cd-scope is-${rule.scope}`}>{scopeLabel(rule)}</span>
        <label className="cd-switch">
          <input
            type="checkbox"
            role="switch"
            aria-label={`${text} 켜짐`}
            checked={rule.enabled}
            disabled={!canDelete}
            title={canDelete ? undefined : '만든 사람이나 관리자만 켜고 끌 수 있습니다'}
            onChange={(e) => onToggle(e.target.checked)}
          />
          <span>{rule.enabled ? '켜짐' : '꺼짐'}</span>
        </label>
      </div>
      <p className="cd-rule-text">{text}</p>
      <div className="cd-rule-actions">
        <AddCell rule={rule} adding={adding} onAdd={onAdd} />
        <span className="cd-gap" />
        {canDelete && !asking && <Button onClick={() => setAsking(true)}>지우기</Button>}
        {canDelete && asking && (
          <>
            <Button variant="danger" onClick={onDelete}>
              정말 지우기
            </Button>
            <Button onClick={() => setAsking(false)}>취소</Button>
          </>
        )}
      </div>
      <p className="cd-muted cd-rule-by">{`${rule.created_by} 만듦`}</p>
    </li>
  );
}

export default function MyRules({ scheduleId, version, model }: { scheduleId: number; version: number; model: ConditionsModel }) {
  const { rules, setRules, problem, setProblem } = useRules(scheduleId, version);
  const user = useSession((s) => s.session?.user);
  const run = async (work: () => Promise<void>) => {
    setProblem(null);
    try {
      await work();
    } catch (e) {
      setProblem(messageOf(e));
    }
  };
  const toggle = (r: MyRule, enabled: boolean) =>
    run(async () => {
      const saved = await rulesApi.setEnabled(r.id, enabled);
      setRules((list) => list?.map((x) => (x.id === r.id ? { ...x, enabled: saved.enabled } : x)) ?? null);
    });
  const remove = (r: MyRule) =>
    run(async () => {
      await rulesApi.remove(r.id);
      setRules((list) => list?.filter((x) => x.id !== r.id) ?? null);
    });
  const add = (r: MyRule) => model.add({ ...r.condition, layer: 'mine', source: '내 규칙' });
  return (
    <div className="cd-rules">
      <h4 className="cd-group-head">저장된 내 규칙</h4>
      {problem && (
        <p className="cd-problem" role="alert">
          {problem}
        </p>
      )}
      {rules?.length === 0 && <p className="cd-empty">저장된 내 규칙 없음</p>}
      {rules && rules.length > 0 && (
        <ul className="cd-items" aria-label="내 규칙 목록">
          {rules.map((r) => (
            <RuleRow
              key={r.id}
              rule={r}
              adding={isAdd(model.edits[r.condition.id])}
              canDelete={user?.role === 'admin' || user?.name === r.created_by}
              onToggle={(on) => void toggle(r, on)}
              onAdd={() => add(r)}
              onDelete={() => void remove(r)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
