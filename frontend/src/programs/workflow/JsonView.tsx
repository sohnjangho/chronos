// 받은 것·돌려준 것(JSON 글)을 읽히게: 요약 줄 + 접는 나무. 긴 목록은 50개씩, 긴 글은 앞 300자만 먼저 보인다.
// 관리자가 아니면 서버가 앞 2,000자에서 잘라 보내므로 읽지 못할 수 있다 — 그때는 그렇게 알리고 원문을 접어 둔다.
import { useMemo, useState, type ReactNode } from 'react';
import { useSession } from '../../os/session';
import { CUT_AT } from './wfApi';

const PAGE = 50;
const TEXT_CUT = 300;
const OPEN_MAX = 20;

type Parsed = { ok: true; value: unknown } | { ok: false };

function parse(text: string): Parsed {
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch {
    return { ok: false };
  }
}

const isBox = (v: unknown): v is Record<string, unknown> | unknown[] => typeof v === 'object' && v !== null;
const entriesOf = (v: Record<string, unknown> | unknown[]): [string, unknown][] =>
  Array.isArray(v) ? v.map((x, i) => [`항목 ${i + 1}`, x]) : Object.entries(v);
const sizeLabel = (v: Record<string, unknown> | unknown[]) => (Array.isArray(v) ? `목록 ${v.length}개` : `칸 ${Object.keys(v).length}개`);

function LongText({ text }: { text: string }) {
  const [all, setAll] = useState(false);
  if (text.length <= TEXT_CUT || all) return <>{`"${text}"`}</>;
  return (
    <>
      {`"${text.slice(0, TEXT_CUT)}…"`}{' '}
      <button type="button" className="wf-more" onClick={() => setAll(true)}>
        전체 보기 ({text.length.toLocaleString()}자)
      </button>
    </>
  );
}

function Leaf({ name, value }: { name: string; value: unknown }) {
  const kind = value === null ? 'null' : typeof value;
  return (
    <li className="wf-leaf">
      <span className="wf-key">{name}</span>
      <span className={`wf-val is-${kind}`}>{typeof value === 'string' ? <LongText text={value} /> : String(value)}</span>
    </li>
  );
}

function Entries({ entries, depth }: { entries: [string, unknown][]; depth: number }) {
  const [shown, setShown] = useState(PAGE);
  return (
    <ul className="wf-tree">
      {entries.slice(0, shown).map(([k, v]) => (isBox(v) ? <Box key={k} name={k} value={v} depth={depth} /> : <Leaf key={k} name={k} value={v} />))}
      {entries.length > shown && (
        <li>
          <button type="button" className="wf-more" onClick={() => setShown(entries.length)}>
            나머지 {entries.length - shown}개 더 보기
          </button>
        </li>
      )}
    </ul>
  );
}

/** 접는 묶음. 펼쳤을 때만 아이들을 그린다(큰 목록이 접혀 있으면 그리지 않음). */
function Box({ name, value, depth }: { name: string; value: Record<string, unknown> | unknown[]; depth: number }) {
  const entries = entriesOf(value);
  const [open, setOpen] = useState(depth === 0 && entries.length <= OPEN_MAX);
  return (
    <li>
      <details open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary>
          <span className="wf-key">{name}</span>
          <span className="wf-type">{sizeLabel(value)}</span>
        </summary>
        {open && entries.length > 0 && <Entries entries={entries} depth={depth + 1} />}
      </details>
    </li>
  );
}

function Raw({ text, children }: { text: string; children: ReactNode }) {
  return (
    <>
      <p className="wf-io-note">{children}</p>
      <details className="wf-raw">
        <summary>원문 보기 ({text.length.toLocaleString()}자)</summary>
        <pre>{text}</pre>
      </details>
    </>
  );
}

export default function JsonView({ label, text, empty }: { label: string; text: string | null; empty: string }) {
  const admin = useSession((s) => s.session?.user.role === 'admin');
  const parsed = useMemo(() => (text === null ? null : parse(text)), [text]);
  return (
    <div className="wf-io" role="group" aria-label={label}>
      <h4 className="wf-io-h">{label}</h4>
      {text === null && <p className="wf-io-note">{empty}</p>}
      {text !== null && parsed?.ok === false && (
        <Raw text={text}>{!admin && text.length >= CUT_AT ? '앞 2,000자만 받았습니다(관리자는 전체를 봅니다).' : 'JSON 으로 읽을 수 없는 글입니다.'}</Raw>
      )}
      {parsed?.ok && isBox(parsed.value) && (
        <>
          <p className="wf-io-note">{sizeLabel(parsed.value)}</p>
          {entriesOf(parsed.value).length > 0 && <Entries entries={entriesOf(parsed.value)} depth={0} />}
        </>
      )}
      {parsed?.ok && !isBox(parsed.value) && (
        <ul className="wf-tree">
          <Leaf name="값" value={parsed.value} />
        </ul>
      )}
    </div>
  );
}
