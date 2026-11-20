// 원문(글·JSON 글·객체)을 읽히게(화면 검수 3): 접힌 채 요약 줄만 보이고, 펼치면 들여 쓴 접는 나무.
// 안쪽 글도 JSON 이면(도구 입력·출력, 도구 호출 인자) 풀어서 나무로 잇는다. 긴 목록은 50개씩, 긴 글은 앞 300자만 먼저.
import { useMemo, useState } from 'react';
import { count } from './format';

const PAGE = 50;
const TEXT_CUT = 300;
const OPEN_DEPTH = 2;
const OPEN_MAX = 20;

type Box = Record<string, unknown> | unknown[];
const isBox = (v: unknown): v is Box => typeof v === 'object' && v !== null;

function parseDeep(v: unknown, depth = 0): unknown {
  if (depth > 8) return v;
  if (typeof v === 'string') {
    const t = v.trim();
    if (!(t.startsWith('{') || t.startsWith('['))) return v;
    try {
      return parseDeep(JSON.parse(t), depth + 1);
    } catch {
      return v;
    }
  }
  if (Array.isArray(v)) return v.map((x) => parseDeep(x, depth + 1));
  if (isBox(v)) return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, parseDeep(x, depth + 1)]));
  return v;
}

/** 목록 항목 이름: 메시지는 "1. user", 단계는 "1. schedule.read", 도구 호출은 "1. delay.impact". */
function itemName(x: unknown, i: number): string {
  if (!isBox(x) || Array.isArray(x)) return `${i + 1}`;
  const tag = x.role ?? x.tool ?? x.name;
  const n = typeof x.n === 'number' ? x.n : i + 1;
  return typeof tag === 'string' ? `${n}. ${tag}` : `${n}`;
}
const entriesOf = (v: Box): [string, unknown][] => (Array.isArray(v) ? v.map((x, i) => [itemName(x, i), x]) : Object.entries(v));
const sizeLabel = (v: Box) => (Array.isArray(v) ? `목록 ${v.length}개` : `칸 ${Object.keys(v).length}개`);

function LongText({ text, quote = true }: { text: string; quote?: boolean }) {
  const [all, setAll] = useState(false);
  const q = quote ? '"' : '';
  if (text.length <= TEXT_CUT || all) return <>{`${q}${text}${q}`}</>;
  return (
    <>
      {`${q}${text.slice(0, TEXT_CUT)}…${q}`}{' '}
      <button type="button" className="dc-link" onClick={() => setAll(true)}>
        전체 보기 ({count(text.length)}자)
      </button>
    </>
  );
}

function Leaf({ name, value }: { name: string; value: unknown }) {
  const kind = value === null ? 'null' : typeof value;
  return (
    <li className="dc-leaf">
      <span className="dc-key">{name}</span>
      <span className={`dc-val is-${kind}`}>{typeof value === 'string' ? <LongText text={value} /> : String(value)}</span>
    </li>
  );
}

function Entries({ entries, depth }: { entries: [string, unknown][]; depth: number }) {
  const [shown, setShown] = useState(PAGE);
  return (
    <ul className="dc-tree">
      {entries.slice(0, shown).map(([k, v], i) => (isBox(v) ? <Branch key={`${i}${k}`} name={k} value={v} depth={depth} /> : <Leaf key={`${i}${k}`} name={k} value={v} />))}
      {entries.length > shown && (
        <li>
          <button type="button" className="dc-link" onClick={() => setShown(entries.length)}>
            나머지 {entries.length - shown}개 더 보기
          </button>
        </li>
      )}
    </ul>
  );
}

/** 접는 묶음. 펼쳤을 때만 아이들을 그린다. 얕고 작은 묶음은 처음부터 펼친다. */
function Branch({ name, value, depth }: { name: string; value: Box; depth: number }) {
  const entries = entriesOf(value);
  const [open, setOpen] = useState(depth <= OPEN_DEPTH && entries.length <= OPEN_MAX);
  return (
    <li>
      <details open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary>
          <span className="dc-key">{name}</span>
          <span className="dc-type">{sizeLabel(value)}</span>
        </summary>
        {open && entries.length > 0 && <Entries entries={entries} depth={depth + 1} />}
      </details>
    </li>
  );
}

const isEmpty = (v: unknown) => v === null || v === undefined || v === '' || (Array.isArray(v) && v.length === 0);
const rawLength = (v: unknown) => (typeof v === 'string' ? v.length : JSON.stringify(v).length);

/** JSON 처럼 시작하지만 풀리지 않는 글 — 서버가 60,000자에서 자르고 「(뒤는 생략)」을 붙인 원문. */
const isCutJson = (raw: unknown, value: unknown) => typeof raw === 'string' && typeof value === 'string' && /^\s*[[{]/.test(raw);

function summary(raw: unknown, value: unknown): string {
  const size = `${count(rawLength(raw))}자`;
  if (isCutJson(raw, value)) return `길어서 잘린 원문 — 나무로 풀 수 없음 · ${size}`;
  if (!isBox(value)) return `글 ${size}`;
  return `${sizeLabel(value)} · ${size}`;
}

/** label 묶음: 접힌 채 요약 줄과 [펼치기]. 비었으면 empty 글만. */
export default function RawBlock({ label, value, empty = '없음' }: { label: string; value: unknown; empty?: string }) {
  const [open, setOpen] = useState(false);
  const parsed = useMemo(() => parseDeep(value), [value]);
  if (isEmpty(value)) {
    return (
      <section className="dc-raw">
        <div className="dc-raw-head">
          <h4>{label}</h4>
          <span className="dc-raw-sum">{empty}</span>
        </div>
      </section>
    );
  }
  return (
    <section className="dc-raw">
      <div className="dc-raw-head">
        <h4>{label}</h4>
        <span className="dc-raw-sum">{summary(value, parsed)}</span>
        <button type="button" className="dc-btn" aria-expanded={open} aria-label={`${label} ${open ? '접기' : '펼치기'}`} onClick={() => setOpen(!open)}>
          {open ? '접기' : '펼치기'}
        </button>
      </div>
      {open && (
        <div className="dc-raw-body" role="group" aria-label={`${label} 내용`}>
          {isBox(parsed) ? (
            entriesOf(parsed).length > 0 ? <Entries entries={entriesOf(parsed)} depth={0} /> : <p className="dc-muted">{sizeLabel(parsed)}</p>
          ) : (
            <p className="dc-text">
              <LongText text={String(parsed)} quote={false} />
            </p>
          )}
        </div>
      )}
    </section>
  );
}
