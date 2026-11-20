// CPM 도구줄: 층(Plan·Actual·CPM) · 보기(전체·크리티컬 경로만·선택 항목) · 찾기 · 자동 배치 · 맞춤 · WBS · 범례 · PNG 내보내기 · 개수.
// 꺼진 단추는 title 로 까닭을 말한다. 좁으면 줄을 바꾼다.
import { useState } from 'react';
import Popover from '../../shared/schedule/Popover';
import Button from '../../shared/ui/Button';
import type { Layers } from './cards';
import type { ViewMode } from './layout';

const LAYERS: { key: keyof Layers; label: string }[] = [
  { key: 'plan', label: 'Plan' },
  { key: 'actual', label: 'Actual' },
  { key: 'cpm', label: 'CPM' },
];

const MODES: { key: ViewMode; label: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'critical', label: '크리티컬 경로만' },
  { key: 'selected', label: '선택 항목' },
];

const LEGEND: [string, string][] = [
  ['is-cpm', '크리티컬(CPM 층) — 빨간 테두리 카드와 빨간 관계선: 지금 계산에서 여유(TF)가 0 이하. 관계선은 두 끝이 모두 크리티컬일 때'],
  ['is-selected', '고른 카드 — 파란 테두리. 다른 창(스케줄·간트차트)에서 고르면 이 그림도 그 카드로 갑니다'],
  ['is-line', '관계선 — FS 앞 카드 오른쪽 → 뒤 카드 왼쪽, SS 왼쪽 → 왼쪽, FF 오른쪽 → 오른쪽, SF 왼쪽 → 오른쪽. 글은 종류와 간격(SS+15 = 15일 뒤)'],
  ['is-ms', '마일스톤은 ID 앞에 ◇ · 카드 줄: ES/EF 이른 시작·종료, LS/LF 늦은 시작·종료, OD/RD 원래·남은 기간, TF 여유, 진도'],
  ['is-plan', 'Plan(Plan 층) — 지금 일정을 실적 없이 계산한 날짜. Plan 대비: +n일 늦음, −n일 앞섬(근무일)'],
  ['is-actual', 'Actual(Actual 층) — 상태(완료·진행 중·미착수)와 카드 아래 초록 진도 막대'],
  ['is-drag', '카드를 끌면 이 창에서만 자리가 바뀝니다(일정은 그대로). [자동 배치]로 되돌립니다'],
];

function Legend() {
  return (
    <ul className="sch-pop-body cpm-legend">
      {LEGEND.map(([cls, text]) => (
        <li key={cls}>
          <span className={`cpm-swatch ${cls}`} aria-hidden="true" />
          {text}
        </li>
      ))}
    </ul>
  );
}

/** 찾기 칸: 이름·ID. Enter 나 [찾기]. */
function Find({ onFind }: { onFind(text: string): void }) {
  const [text, setText] = useState('');
  return (
    <form
      role="search"
      className="cpm-find"
      onSubmit={(e) => {
        e.preventDefault();
        onFind(text);
      }}
    >
      <input aria-label="코드·이름 검색" placeholder="코드·이름 검색" value={text} onChange={(e) => setText(e.target.value)} />
      <Button type="submit">찾기</Button>
    </form>
  );
}

export interface CpmToolbarProps {
  layers: Layers;
  onLayer(key: keyof Layers): void;
  mode: ViewMode;
  onMode(mode: ViewMode): void;
  hasSelection: boolean;
  onFind(text: string): void;
  onAutoLayout(): void;
  onFit(): void;
  wbsGroups: { code: string; name: string }[];
  wbs: string | null;
  onWbs(code: string | null): void;
  onPng(): void;
  counts: string;
}

const Sep = () => <span className="sch-sep" aria-hidden="true" />;

export default function CpmToolbar(p: CpmToolbarProps) {
  return (
    <div role="toolbar" aria-label="CPM 도구" className="sch-toolbar cpm-toolbar">
      {LAYERS.map((l) => (
        <button key={l.key} type="button" className="cpm-chip-btn" aria-pressed={p.layers[l.key]} onClick={() => p.onLayer(l.key)}>
          <span className={`cpm-swatch is-${l.key}`} aria-hidden="true" />
          {l.label}
        </button>
      ))}
      <Sep />
      {MODES.map((m) => {
        const off = m.key === 'selected' && !p.hasSelection && p.mode !== 'selected';
        return (
          <button
            key={m.key} type="button" className="cpm-chip-btn" aria-pressed={p.mode === m.key} disabled={off}
            title={off ? '카드를 먼저 고르세요' : undefined} onClick={() => p.onMode(m.key)}
          >
            {m.label}
          </button>
        );
      })}
      <Sep />
      <Find onFind={p.onFind} />
      <Button title="끌어 옮긴 자리를 버리고 다시 배치합니다" onClick={p.onAutoLayout}>자동 배치</Button>
      <Button onClick={p.onFit}>맞춤</Button>
      <span className="sch-gap" />
      <select className="cpm-wbs" aria-label="WBS" value={p.wbs ?? ''} onChange={(e) => p.onWbs(e.target.value || null)}>
        <option value="">전체 WBS</option>
        {p.wbsGroups.map((w) => (
          <option key={w.code} value={w.code}>{`${w.code} ${w.name}`}</option>
        ))}
      </select>
      <Popover button="범례" label="범례" align="right">
        {() => <Legend />}
      </Popover>
      <Button onClick={p.onPng}>PNG 내보내기</Button>
      <span className="cpm-counts">{p.counts}</span>
    </div>
  );
}
