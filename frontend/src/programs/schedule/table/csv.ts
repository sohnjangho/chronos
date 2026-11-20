// CSV 내보내기: 보이는 칸 × 모든 액티비티(찾기·거르기·접기와 상관없이 WBS 차례). 엑셀이 한글을 읽게 BOM 을 붙인다.
import type { ScheduleView } from '../scheduleApi';
import type { CellCtx, ColumnDef } from './columns';
import { buildRows, NO_FILTER } from './rows';

const cell = (text: string) => (/[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text);

export function toCsv(view: ScheduleView, columns: ColumnDef[], ctxOf: (aid: string) => Omit<CellCtx, 'a'>): string {
  const lines = [columns.map((c) => cell(c.header)).join(',')];
  for (const r of buildRows(view, NO_FILTER, new Set())) {
    if (r.kind !== 'activity') continue;
    const ctx = { a: r.activity, ...ctxOf(r.key) };
    lines.push(columns.map((c) => cell(c.text(ctx))).join(','));
  }
  return `\uFEFF${lines.join('\r\n')}\r\n`;
}

/** 브라우저 내려받기. */
export function download(fileName: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  a.click();
  URL.revokeObjectURL(url);
}
