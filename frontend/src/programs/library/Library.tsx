// 자료함 프로그램(시안 A: 왼쪽 축 레일 · 가운데 목록 · 오른쪽 상세 + 끌어서 폭 조절).
import { useCallback, useEffect, useState } from 'react';
import { useSession } from '../../os/session';
import Button from '../../shared/ui/Button';
import FacetBar from './FacetBar';
import FileDetail from './FileDetail';
import FileList from './FileList';
import {
  libraryApi,
  type AxesData,
  type AxisFilters,
  type AxisName,
  type FileItem,
  type FileList as FileListData,
  type MergeSuggestion,
  type ReindexJob,
  type ReindexState,
} from './libraryApi';
import MergeSuggestions from './MergeSuggestions';
import { MAX_DETAIL_WIDTH, MIN_DETAIL_WIDTH, useDetailWidth } from './useDetailWidth';
import './library.css';

const REINDEX_POLL_MS = 3000;

function useLibraryEffects(
  query: string,
  filters: AxisFilters,
  page: number,
  isAdmin: boolean,
  reloadTick: number,
  setSelectedId: React.Dispatch<React.SetStateAction<number | null>>,
) {
  const [listData, setListData] = useState<FileListData | null>(null);
  const [axes, setAxes] = useState<AxesData>({});
  const [suggestions, setSuggestions] = useState<MergeSuggestion[]>([]);
  const [reindex, setReindex] = useState<ReindexState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    setLoading(true);
    setError(null);
    libraryApi
      .list(query, filters, page, ac.signal)
      .then((data) => {
        setListData(data);
        setLoading(false);
        setSelectedId((prev) => (data.items.some((f) => f.file_id === prev) ? prev : (data.items[0]?.file_id ?? null)));
      })
      .catch((e) => {
        if (ac.signal.aborted) return;
        setError(e instanceof Error ? e.message : '자료를 불러올 수 없습니다.');
        setLoading(false);
      });
    return () => ac.abort();
  }, [query, filters, page, reloadTick, setSelectedId]);

  useEffect(() => {
    const ac = new AbortController();
    libraryApi.axes(ac.signal).then(setAxes).catch(() => {});
    if (isAdmin) {
      libraryApi.mergeSuggestions(ac.signal).then((res) => setSuggestions(res.items)).catch(() => setSuggestions([]));
    } else {
      setSuggestions([]);
    }
    return () => ac.abort();
  }, [isAdmin, reloadTick]);

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = () => {
      libraryApi
        .reindex()
        .then((s) => {
          if (!live) return;
          setReindex(s);
          if (s.job?.status === 'running') timer = setTimeout(poll, REINDEX_POLL_MS);
        })
        .catch(() => {});
    };
    poll();
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [reloadTick]);

  return { listData, setListData, axes, setAxes, suggestions, reindex, loading, error };
}

function ReindexBanner({ job }: { job: ReindexJob }) {
  const pct = job.total > 0 ? Math.floor((job.done / job.total) * 100) : 0;
  return (
    <div className="lib-reindex" role="status" aria-label="임베딩 다시 넣기 진행">
      <span>
        새 임베딩 모델로 다시 넣는 중 {pct}% ({job.done.toLocaleString()} / {job.total.toLocaleString()})
      </span>
      <div className="lib-reindex-bar" role="progressbar" aria-valuemin={0} aria-valuemax={job.total} aria-valuenow={job.done}>
        <span style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function SearchHeader({
  query,
  queryInput,
  runningJob,
  onInput,
  onSubmit,
  onClear,
}: {
  query: string;
  queryInput: string;
  runningJob: ReindexJob | null;
  onInput(v: string): void;
  onSubmit(): void;
  onClear(): void;
}) {
  return (
    <header className="lib-head">
      <form
        className="lib-search"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit();
        }}
      >
        <input
          type="search"
          aria-label="자료 찾기"
          placeholder="이름·내용으로 찾기(뜻 + 낱말)"
          value={queryInput}
          onChange={(e) => onInput(e.target.value)}
        />
        <Button type="submit" variant="primary">
          찾기
        </Button>
        {(query || queryInput) && (
          <Button type="button" onClick={onClear}>
            지우기
          </Button>
        )}
      </form>
      {runningJob && <ReindexBanner job={runningJob} />}
    </header>
  );
}

export default function Library() {
  const user = useSession((s) => s.session?.user);
  const userId = user?.id ?? 0;
  const isAdmin = user?.role === 'admin';

  const [queryInput, setQueryInput] = useState('');
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState<AxisFilters>({});
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [mergeBusy, setMergeBusy] = useState<string | null>(null);
  const [mergeError, setMergeError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  const { width, startResize, stepResize } = useDetailWidth(userId);
  const refreshAll = useCallback(() => setReloadTick((t) => t + 1), []);
  const { listData, setListData, axes, setAxes, suggestions, reindex, loading, error } = useLibraryEffects(
    query,
    filters,
    page,
    isAdmin,
    reloadTick,
    setSelectedId,
  );

  function toggleFilter(axis: AxisName, value: string) {
    setPage(1);
    setFilters((prev) => {
      const cur = prev[axis] ?? [];
      return { ...prev, [axis]: cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value] };
    });
  }

  async function handleMerge(item: MergeSuggestion) {
    setMergeBusy(`${item.axis}:${item.from.join(',')}:${item.to}`);
    setMergeError(null);
    try {
      await libraryApi.merge(item.axis, item.from, item.to);
      refreshAll();
    } catch (e) {
      setMergeError(e instanceof Error ? e.message : '값을 합치지 못했습니다.');
    } finally {
      setMergeBusy(null);
    }
  }

  function handleUpdated(updated: FileItem) {
    setListData((prev) => (prev ? { ...prev, items: prev.items.map((f) => (f.file_id === updated.file_id ? updated : f)) } : prev));
    libraryApi.axes().then(setAxes).catch(() => {});
  }

  function handleDeleted(fileId: number) {
    setListData((prev) => {
      if (!prev) return prev;
      const items = prev.items.filter((f) => f.file_id !== fileId);
      setSelectedId(items[0]?.file_id ?? null);
      return { ...prev, items, total: Math.max(0, prev.total - 1) };
    });
    refreshAll();
  }

  const selectedFile = listData?.items.find((f) => f.file_id === selectedId) ?? null;
  const runningJob = reindex?.job?.status === 'running' ? reindex.job : null;

  return (
    <div className="lib-root">
      <SearchHeader
        query={query}
        queryInput={queryInput}
        runningJob={runningJob}
        onInput={setQueryInput}
        onSubmit={() => { setPage(1); setQuery(queryInput.trim()); }}
        onClear={() => { setQueryInput(''); setQuery(''); setPage(1); }}
      />
      {error && <p className="lib-error lib-top-error" role="alert">{error}</p>}

      <div className="lib-body">
        <FacetBar axes={axes} filters={filters} onToggle={toggleFilter} onClear={() => { setPage(1); setFilters({}); }} />
        <main className="lib-center">
          {isAdmin && <MergeSuggestions items={suggestions} busyKey={mergeBusy} error={mergeError} onMerge={handleMerge} />}
          <FileList data={listData} loading={loading} selectedId={selectedId} query={query} onSelect={(f) => setSelectedId(f.file_id)} onPage={setPage} />
        </main>
        <div
          className="lib-splitter"
          role="separator"
          aria-orientation="vertical"
          aria-label="미리 보기 폭 조절"
          aria-valuemin={MIN_DETAIL_WIDTH}
          aria-valuemax={MAX_DETAIL_WIDTH}
          aria-valuenow={width}
          tabIndex={0}
          onPointerDown={startResize}
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft') stepResize(24);
            if (e.key === 'ArrowRight') stepResize(-24);
          }}
        />
        <div className="lib-detail-pane" style={{ width }}>
          {user && <FileDetail file={selectedFile} user={user} onUpdated={handleUpdated} onDeleted={handleDeleted} />}
        </div>
      </div>
    </div>
  );
}
