// 에이전트 답의 기본 Markdown(문단·목록·굵게·코드·표). 글을 React 요소로만 만든다 — HTML 을 넣지 않으므로
// 답 속의 <img>·<script> 같은 글은 글자 그대로 보인다.
import type { ReactNode } from 'react';

type Block =
  | { t: 'p'; lines: string[] }
  | { t: 'h'; text: string }
  | { t: 'ul' | 'ol'; items: string[] }
  | { t: 'code'; text: string }
  | { t: 'table'; head: string[]; rows: string[][] };

const BULLET = /^\s*[-*]\s+/;
const NUMBER = /^\s*\d+[.)]\s+/;
const HEADING = /^#{1,6}\s+/;
const FENCE = /^\s*```/;
const RULE = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

const isTable = (lines: string[], i: number) => lines[i].includes('|') && i + 1 < lines.length && RULE.test(lines[i + 1]);
const cells = (line: string) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
const startsBlock = (lines: string[], i: number) =>
  BULLET.test(lines[i]) || NUMBER.test(lines[i]) || HEADING.test(lines[i]) || FENCE.test(lines[i]) || isTable(lines, i);

/** 한 덩어리를 읽고 다음 줄 번호를 돌려준다. */
function readBlock(lines: string[], i: number): [Block, number] {
  const line = lines[i];
  const take = (test: (l: string) => boolean) => {
    let j = i;
    while (j < lines.length && test(lines[j])) j += 1;
    return j;
  };
  if (FENCE.test(line)) {
    let j = i + 1;
    while (j < lines.length && !FENCE.test(lines[j])) j += 1;
    return [{ t: 'code', text: lines.slice(i + 1, j).join('\n') }, j + 1];
  }
  if (isTable(lines, i)) {
    const end = take((l) => l.includes('|') && l.trim() !== '');
    return [{ t: 'table', head: cells(line), rows: lines.slice(i + 2, Math.max(end, i + 2)).map(cells) }, Math.max(end, i + 2)];
  }
  for (const [t, re] of [['ul', BULLET], ['ol', NUMBER]] as const) {
    if (re.test(line)) {
      const end = take((l) => re.test(l));
      return [{ t, items: lines.slice(i, end).map((l) => l.replace(re, '')) }, end];
    }
  }
  if (HEADING.test(line)) return [{ t: 'h', text: line.replace(HEADING, '') }, i + 1];
  let j = i + 1;
  while (j < lines.length && lines[j].trim() !== '' && !startsBlock(lines, j)) j += 1;
  return [{ t: 'p', lines: lines.slice(i, j) }, j];
}

function parse(text: string): Block[] {
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    if (lines[i].trim() === '') {
      i += 1;
      continue;
    }
    const [block, next] = readBlock(lines, i);
    blocks.push(block);
    i = next;
  }
  return blocks;
}

const INLINE = /\*\*([^*]+?)\*\*|`([^`]+)`/;

/** **굵게** 와 `코드` 만. 닫히지 않은 표시는 글자 그대로. */
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let rest = text;
  let m: RegExpExecArray | null;
  while ((m = INLINE.exec(rest)) !== null) {
    if (m.index > 0) out.push(rest.slice(0, m.index));
    out.push(m[1] !== undefined ? <strong key={out.length}>{m[1]}</strong> : <code key={out.length}>{m[2]}</code>);
    rest = rest.slice(m.index + m[0].length);
  }
  if (rest) out.push(rest);
  return out;
}

function renderBlock(b: Block, key: number): ReactNode {
  switch (b.t) {
    case 'p':
      return <p key={key}>{b.lines.flatMap((l, i) => (i === 0 ? inline(l) : [<br key={`b${i}`} />, ...inline(l)]))}</p>;
    case 'h':
      return <p key={key} className="ch-md-h"><strong>{b.text}</strong></p>;
    case 'ul':
    case 'ol': {
      const List = b.t;
      return <List key={key}>{b.items.map((it, i) => <li key={i}>{inline(it)}</li>)}</List>;
    }
    case 'code':
      return <pre key={key}><code>{b.text}</code></pre>;
    case 'table':
      return (
        <table key={key}>
          <thead><tr>{b.head.map((h, i) => <th key={i}>{inline(h)}</th>)}</tr></thead>
          <tbody>{b.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{inline(c)}</td>)}</tr>)}</tbody>
        </table>
      );
  }
}

export function Markdown({ text }: { text: string }) {
  return <div className="ch-md">{parse(text).map(renderBlock)}</div>;
}
