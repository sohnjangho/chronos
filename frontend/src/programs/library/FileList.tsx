// 자료함 가운데 파일 목록(50개씩 쪽 나눔, 이름·축 값·요약/상태·올린 날).
import Button from '../../shared/ui/Button';
import { AXES, formatBytes, formatDate, isClassified, type FileItem, type FileList as FileListData } from './libraryApi';

interface Props {
  data: FileListData | null;
  loading: boolean;
  selectedId: number | null;
  query: string;
  onSelect(item: FileItem): void;
  onPage(page: number): void;
}

const KIND_LABEL: Record<string, string> = {
  pdf: 'PDF',
  image: '사진',
  sheet: '표',
  table: '표',
  doc: '문서',
  text: '글',
};

function statusLabel(f: FileItem): string | null {
  if (f.status === 'failed') return f.reason ? `실패 — ${f.reason}` : '실패';
  if (!isClassified(f)) return f.reason ?? '분류 전';
  return null;
}

export default function FileList({ data, loading, selectedId, query, onSelect, onPage }: Props) {
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const page = data?.page ?? 1;
  const pageSize = data?.page_size ?? 50;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  if (loading && !data) {
    return <div className="lib-empty">자료를 불러오는 중…</div>;
  }

  if (items.length === 0) {
    return (
      <div className="lib-empty">
        {query.trim() ? `「${query.trim()}」에 맞는 자료가 없습니다.` : '표시할 자료가 없습니다.'}
      </div>
    );
  }

  return (
    <div className="lib-list-wrap">
      <div className="lib-list-meta">
        <span>전체 {total.toLocaleString()}건</span>
        {loading && <span className="lib-muted">갱신 중…</span>}
      </div>
      <div className="lib-list-scroll">
        <ul className="lib-list" role="listbox" aria-label="자료 목록">
          {items.map((f) => {
            const active = f.file_id === selectedId;
            const warn = statusLabel(f);
            const chips = AXES.flatMap((axis) => (f.axes[axis] ?? []).map((val) => ({ axis, val })));
            return (
              <li
                key={f.file_id}
                role="option"
                aria-selected={active}
                className={`lib-row ${active ? 'is-selected' : ''}`}
                onClick={() => onSelect(f)}
              >
                <div className="lib-row-top">
                  <span className={`lib-kind lib-kind-${f.kind}`}>{KIND_LABEL[f.kind] ?? f.ext.toUpperCase()}</span>
                  <span className="lib-row-name" title={f.name}>
                    {f.name}
                  </span>
                  <span className="lib-row-size">{formatBytes(f.size)}</span>
                  <span className="lib-row-date">{formatDate(f.uploaded_at)}</span>
                </div>
                {f.summary && <p className="lib-row-summary">{f.summary}</p>}
                {warn && <p className="lib-row-warn">{warn}</p>}
                {chips.length > 0 && (
                  <div className="lib-row-chips">
                    {chips.map(({ axis, val }) => (
                      <span key={`${axis}:${val}`} className="lib-chip" title={axis}>
                        {val}
                      </span>
                    ))}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </div>
      {totalPages > 1 && (
        <nav className="lib-pager" aria-label="목록 쪽 이동">
          <Button disabled={page <= 1} onClick={() => onPage(page - 1)}>
            이전
          </Button>
          <span className="lib-pager-info">
            {page} / {totalPages}쪽
          </span>
          <Button disabled={page >= totalPages} onClick={() => onPage(page + 1)}>
            다음
          </Button>
        </nav>
      )}
    </div>
  );
}
