import { useState } from 'react';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import type { Change, Cond, CondView } from './condApi';
import type { EditPatch } from './condStore';
import { condLabel, fieldLabel, paramKey, parseValue, STATE_LABEL, STATE_TONE, unitOf, valueText } from './labels';

interface ItemProps {
  /** 보이는 상태(미리 보기 중이면 미리 보기의 것). */
  cond: Cond;
  /** 저장된 조건(입력 칸의 처음 값). */
  saved: Cond;
  change: Change | undefined;
  resources: CondView['resources'];
  onEdit(id: string, patch: EditPatch): void;
}

/** 값 칸 하나. 적는 글은 이 칸이 들고, 맞는 값일 때만 바꿈으로 올린다(틀리면 빨간 테·바꿈 뺌). */
function ValueField({ label, initial, valueKey, unit, onValue }: { label: string; initial: unknown; valueKey: string; unit: string; onValue(v: number | string | null): void }) {
  const [raw, setRaw] = useState(String(initial ?? ''));
  const bad = parseValue(valueKey, raw) === null;
  if (valueKey === 'days_per_week') {
    return (
      <select
        className="cd-select"
        aria-label={label}
        value={raw}
        onChange={(e) => {
          setRaw(e.target.value);
          onValue(Number(e.target.value));
        }}
      >
        {[5, 6, 7].map((n) => (
          <option key={n} value={String(n)}>{`주 ${n}일`}</option>
        ))}
      </select>
    );
  }
  return (
    <span className="cd-field">
      <input
        className={`cd-input ${valueKey === 'date' ? 'is-date' : ''}`}
        aria-label={label}
        aria-invalid={bad}
        inputMode={valueKey === 'date' ? undefined : 'numeric'}
        placeholder={valueKey === 'date' ? 'YYYY-MM-DD' : undefined}
        value={raw}
        onChange={(e) => {
          setRaw(e.target.value);
          onValue(parseValue(valueKey, e.target.value));
        }}
      />
      {unit && <span className="cd-unit">{unit}</span>}
    </span>
  );
}

/** 바꾼 값 줄: 「1대 → 2대 미리 보기」. */
function changeNote(saved: Cond, change: Change | undefined, key: string | null, unit: string): string | null {
  if (!change) return null;
  if (change.enabled !== undefined && change.enabled !== saved.enabled) return change.enabled ? '켜서 미리 보기' : '꺼서 미리 보기';
  if (!key || change.params?.[key] === undefined) return null;
  return `${valueText(key, saved.params[key], unit)} → ${valueText(key, change.params[key], unit)} 미리 보기`;
}

function UsedBy({ cond }: { cond: Cond }) {
  if (!cond.used_by || cond.used_by.length === 0) return null;
  const what = cond.kind === 'resource_cap' ? '쓰는 액티비티' : '걸리는 액티비티';
  return (
    <details className="cd-used">
      <summary>{`${what} ${cond.used_by.length}개`}</summary>
      <p>{cond.used_by.join(', ')}</p>
    </details>
  );
}

/** 조건 하나: 이름(+값 칸) · 상태 배지 · 켜기/끄기 / 출처 · 바꾼 값 / 까닭 / 걸리는 액티비티(접음). */
export default function ConditionItem({ cond, saved, change, resources, onEdit }: ItemProps) {
  const label = condLabel(saved, resources);
  const key = saved.editable === true ? paramKey(saved.kind) : null;
  const unit = unitOf(saved, resources);
  const enabled = change?.enabled ?? saved.enabled;
  const canToggle = saved.editable !== false && saved.overridden_by === null;
  const note = changeNote(saved, change, key, unit);
  const classes = ['cd-item', `is-${cond.state}`, change && 'is-edited'].filter(Boolean).join(' ');
  return (
    <li className={classes} aria-label={label}>
      <div className="cd-line">
        <span className={saved.kind === 'resource_cap' ? 'cd-name is-strong' : 'cd-name'}>{label}</span>
        {key && (
          <ValueField
            label={fieldLabel(saved, label)}
            initial={saved.params[key]}
            valueKey={key}
            unit={key === 'date' ? '' : unit}
            onValue={(v) => onEdit(saved.id, { params: v === null ? null : { [key]: v } })}
          />
        )}
        <Badge tone={STATE_TONE[cond.state]}>{STATE_LABEL[cond.state]}</Badge>
        {canToggle && (
          <Button className="cd-toggle" onClick={() => onEdit(saved.id, { enabled: !enabled })}>
            {enabled ? '끄기' : '켜기'}
          </Button>
        )}
      </div>
      <div className="cd-meta">
        <span>{saved.source}</span>
        {note && <span className="cd-note">{note}</span>}
      </div>
      {cond.message && <p className={`cd-msg is-${cond.state}`}>{cond.message}</p>}
      <UsedBy cond={cond} />
    </li>
  );
}
