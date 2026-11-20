// 자료 미리 보기: 그림(/raw blob), 쪽 글·표 앞 20행(/preview?page=N).
import { useEffect, useState } from 'react';
import Button from '../../shared/ui/Button';
import { libraryApi, type FileItem, type PreviewData } from './libraryApi';

interface Props {
  file: FileItem;
}

const MAX_SHEET_ROWS = 20;

function formatSheetText(text: string): { lines: string[]; clipped: boolean } {
  const all = text.split(/\r?\n/).filter((line) => line.length > 0);
  if (all.length <= MAX_SHEET_ROWS) return { lines: all, clipped: false };
  return { lines: all.slice(0, MAX_SHEET_ROWS), clipped: true };
}

export default function Preview({ file }: Props) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<PreviewData | null>(null);
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPage(1);
  }, [file.file_id]);

  useEffect(() => {
    const ac = new AbortController();
    let createdUrl: string | null = null;
    setLoading(true);
    setError(null);

    if (file.kind === 'image') {
      setData(null);
      libraryApi
        .rawBlob(file.file_id, ac.signal)
        .then((blob) => {
          createdUrl = URL.createObjectURL(blob);
          setImgUrl(createdUrl);
          setLoading(false);
        })
        .catch((e) => {
          if (ac.signal.aborted) return;
          setImgUrl(null);
          setError(e instanceof Error ? e.message : '그림을 불러올 수 없습니다.');
          setLoading(false);
        });
    } else {
      setImgUrl(null);
      libraryApi
        .preview(file.file_id, page, ac.signal)
        .then((res) => {
          setData(res);
          setLoading(false);
        })
        .catch((e) => {
          if (ac.signal.aborted) return;
          setData(null);
          setError(e instanceof Error ? e.message : '미리 보기를 불러올 수 없습니다.');
          setLoading(false);
        });
    }

    return () => {
      ac.abort();
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [file.file_id, file.kind, page]);

  if (loading) return <div className="lib-preview-box lib-muted">미리 보기를 불러오는 중…</div>;
  if (error) return <div className="lib-preview-box lib-error">{error}</div>;

  if (file.kind === 'image') {
    return (
      <div className="lib-preview-box lib-preview-img-wrap">
        {imgUrl ? (
          <img src={imgUrl} alt={file.name} className="lib-preview-img" />
        ) : (
          <span className="lib-muted">그림을 표시할 수 없습니다.</span>
        )}
      </div>
    );
  }

  const isSheet = file.kind === 'sheet' || file.kind === 'table';
  const text = data?.text ?? '';
  const sheet = isSheet ? formatSheetText(text) : null;
  const pages = data?.pages ?? 1;

  return (
    <div className="lib-preview-box">
      {pages > 1 && (
        <div className="lib-preview-nav">
          <Button disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
            이전 {isSheet ? '시트' : '쪽'}
          </Button>
          <span>
            {page} / {pages}
            {isSheet ? '시트' : '쪽'}
          </span>
          <Button disabled={page >= pages} onClick={() => setPage((p) => Math.min(pages, p + 1))}>
            다음 {isSheet ? '시트' : '쪽'}
          </Button>
        </div>
      )}
      {!text.trim() ? (
        <p className="lib-muted">{file.reason ?? '뽑아낸 글이 없습니다.'}</p>
      ) : sheet ? (
        <div className="lib-preview-sheet">
          <pre className="lib-preview-text">{sheet.lines.join('\n')}</pre>
          {(sheet.clipped || data?.truncated) && (
            <p className="lib-muted">앞 {MAX_SHEET_ROWS}행만 미리 보입니다. 전체 내용은 내려받아 확인하세요.</p>
          )}
        </div>
      ) : (
        <>
          <pre className="lib-preview-text">{text}</pre>
          {data?.truncated && <p className="lib-muted">일부만 미리 보입니다.</p>}
        </>
      )}
    </div>
  );
}
