// 에이전트 답의 기본 Markdown(문단·목록·굵게·코드·표). 글을 React 요소로만 만든다 — HTML 을 넣지 않으므로
// 답 속의 <img>·<script> 같은 글은 글자 그대로 보인다.
import type { ReactNode } from 'react';

interface ListItem {
  /** 표시 줄과 바로 이어지는 줄(한 문단). */
  head: string[];
  /** 들여 쓴 하위 목록·빈 줄 뒤 문단 — 다시 Markdown 으로 읽는다. */
  body: string[];
}

type Block =
  | { t: 'p'; lines: string[] }
  | { t: 'h'; text: string }
  | { t: 'ul' | 'ol'; items: ListItem[]; start: number }
  | { t: 'code'; text: string }
  | { t: 'table'; head: string[]; rows: string[][] };

const BULLET = /^\s*[-*]\s+/;
// 번호는 1~3자리만: "2027. 11. 24. 준공" 같은 날짜 글은 목록이 아니다.
const NUMBER = /^\s*(\d{1,3})[.)]\s+/;
const HEADING = /^#{1,6}\s+/;
const FENCE = /^\s*```/;
const RULE = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

const blank = (l: string) => l.trim() === '';
const indent = (l: string) => l.length - l.trimStart().length;
const isTable = (lines: string[], i: number) => lines[i].includes('|') && i + 1 < lines.length && RULE.test(lines[i + 1]);
const cells = (line: string) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
const startsBlock = (lines: string[], i: number) =>
  BULLET.test(lines[i]) || NUMBER.test(lines[i]) || HEADING.test(lines[i]) || FENCE.test(lines[i]) || isTable(lines, i);

/** 공통 들여쓰기를 뗀다(목록 항목 안의 내용을 다시 읽으려고). */
function dedent(lines: string[]): string[] {
  const depth = Math.min(...lines.filter((l) => !blank(l)).map(indent));
  return lines.map((l) => l.slice(Math.min(depth, indent(l))));
}

/**
 * 목록 하나. 같은 깊이의 표시 줄마다 항목이 생기고, 더 들여 쓴 줄(하위 목록·이어지는 글)과 빈 줄 사이의 다음 항목은
 * 같은 목록에 남는다. 들여 쓰지 않은 이어지는 줄은 그 항목의 글로 붙는다.
 */
function readList(lines: string[], i: number, t: 'ul' | 'ol'): [Block, number] {
  const marker = t === 'ul' ? BULLET : NUMBER;
  const base = indent(lines[i]);
  const isItem = (l: string) => marker.test(l) && indent(l) - base < 2;
  const items: ListItem[] = [];
  let j = i;
  while (j < lines.length) {
    const line = lines[j];
    if (blank(line)) {
      let k = j;
      while (k < lines.length && blank(lines[k])) k += 1;
      if (k >= lines.length || !(isItem(lines[k]) || indent(lines[k]) - base >= 2)) break;
      if (!isItem(lines[k])) items[items.length - 1].body.push('');
      j = k;
      continue;
    }
    const item = items[items.length - 1];
    if (isItem(line)) items.push({ head: [line.replace(marker, '')], body: [] });
    else if (indent(line) - base >= 2) {
      // 들여 쓴 줄: 하위 목록 같은 덩어리가 시작됐으면 body, 아니면 그 항목의 글에 잇는다.
      if (item.body.length > 0 || startsBlock(lines, j)) item.body.push(line);
      else item.head.push(line.trim());
    } else if (startsBlock(lines, j)) break;
    else item.head.push(line.trim());
    j += 1;
  }
  const start = t === 'ol' ? Number(NUMBER.exec(lines[i])?.[1] ?? 1) : 1;
  return [{ t, items, start }, j];
}

/** 한 덩어리를 읽고 다음 줄 번호를 돌려준다. */
function readBlock(lines: string[], i: number): [Block, number] {
  const line = lines[i];
  if (FENCE.test(line)) {
    let j = i + 1;
    while (j < lines.length && !FENCE.test(lines[j])) j += 1;
    return [{ t: 'code', text: lines.slice(i + 1, j).join('\n') }, j + 1];
  }
  if (isTable(lines, i)) {
    let end = i + 2;
    while (end < lines.length && lines[end].includes('|') && !blank(lines[end])) end += 1;
    return [{ t: 'table', head: cells(line), rows: lines.slice(i + 2, end).map(cells) }, end];
  }
  if (BULLET.test(line)) return readList(lines, i, 'ul');
  if (NUMBER.test(line)) return readList(lines, i, 'ol');
  if (HEADING.test(line)) return [{ t: 'h', text: line.replace(HEADING, '') }, i + 1];
  let j = i + 1;
  while (j < lines.length && !blank(lines[j]) && !startsBlock(lines, j)) j += 1;
  return [{ t: 'p', lines: lines.slice(i, j) }, j];
}

function parse(lines: string[]): Block[] {
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    if (blank(lines[i])) {
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

/** 줄들을 <br> 로 이은 글. */
const joinLines = (ls: string[]) => ls.flatMap((l, i) => (i === 0 ? inline(l) : [<br key={`b${i}`} />, ...inline(l)]));

function renderList(b: Extract<Block, { t: 'ul' | 'ol' }>, key: number): ReactNode {
  const List = b.t;
  return (
    <List key={key} {...(b.t === 'ol' && b.start !== 1 && { start: b.start })}>
      {b.items.map((it, i) => (
        <li key={i}>
          {joinLines(it.head)}
          {it.body.some((l) => !blank(l)) && parse(dedent(it.body)).map(renderBlock)}
        </li>
      ))}
    </List>
  );
}

function renderBlock(b: Block, key: number): ReactNode {
  switch (b.t) {
    case 'p':
      return <p key={key}>{joinLines(b.lines)}</p>;
    case 'h':
      return <p key={key} className="ch-md-h"><strong>{b.text}</strong></p>;
    case 'ul':
    case 'ol':
      return renderList(b, key);
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
  return <div className="ch-md">{parse(text.replace(/\r\n?/g, '\n').split('\n')).map(renderBlock)}</div>;
}
