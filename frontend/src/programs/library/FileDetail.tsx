// 자료함 오른쪽 상세(미리 보기 · 축 고치기 · 대화에 붙이기 · 내려받기 · 지우기/완전히 지우기).
import { useEffect, useState } from 'react';
import type { User } from '../../os/session';
import { useWindows } from '../../os/windowStore';
import Button from '../../shared/ui/Button';
import { AXES, formatBytes, formatDate, libraryApi, type AxisName, type FileItem } from './libraryApi';
import Preview from './Preview';

interface Props {
  file: FileItem | null;
  user: User;
  onUpdated(file: FileItem): void;
  onDeleted(fileId: number): void;
}

function ConfirmDelete({
  name,
  mode,
  busy,
  onCancel,
  onConfirm,
}: {
  name: string;
  mode: 'delete' | 'purge';
  busy: boolean;
  onCancel(): void;
  onConfirm(): void;
}) {
  return (
    <div className="lib-confirm" role="alertdialog" aria-label="삭제 확인">
      <p>
        {mode === 'purge'
          ? `「${name}」의 원본과 검색 색인을 완전히 지웁니다. 되돌릴 수 없습니다.`
          : `「${name}」을(를) 자료함에서 지울까요?`}
      </p>
      <div className="lib-confirm-btns">
        <Button disabled={busy} onClick={onCancel}>
          취소
        </Button>
        <Button variant="danger" disabled={busy} onClick={onConfirm}>
          {mode === 'purge' ? '완전히 지우기 확인' : '지우기 확인'}
        </Button>
      </div>
    </div>
  );
}

function AxesEditor({
  file,
  onUpdated,
  onError,
}: {
  file: FileItem;
  onUpdated(file: FileItem): void;
  onError(msg: string | null): void;
}) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [savingAxis, setSavingAxis] = useState<string | null>(null);

  useEffect(() => {
    setDraft({});
  }, [file.file_id]);

  async function saveAxis(axis: AxisName, nextValues: string[]) {
    setSavingAxis(axis);
    onError(null);
    try {
      onUpdated(await libraryApi.patchAxes(file.file_id, { [axis]: nextValues }));
    } catch (e) {
      onError(e instanceof Error ? e.message : '분류를 저장하지 못했습니다.');
    } finally {
      setSavingAxis(null);
    }
  }

  async function addAxisValue(axis: AxisName) {
    const val = (draft[axis] ?? '').trim();
    if (!val) return;
    const prev = file.axes[axis] ?? [];
    if (!prev.includes(val)) await saveAxis(axis, [...prev, val]);
    setDraft((d) => ({ ...d, [axis]: '' }));
  }

  return (
    <div className="lib-axes-editor" aria-label="분류 값 고치기">
      <h4>분류 값</h4>
      {AXES.map((axis) => {
        const vals = file.axes[axis] ?? [];
        const saving = savingAxis === axis;
        return (
          <div key={axis} className="lib-axis-edit-row">
            <span className="lib-axis-edit-label">{axis}</span>
            <div className="lib-axis-edit-chips">
              {vals.map((val) => (
                <span key={val} className="lib-chip lib-chip-edit">
                  {val}
                  <button
                    type="button"
                    className="lib-chip-x"
                    aria-label={`${axis} ${val} 지우기`}
                    disabled={saving}
                    onClick={() => saveAxis(axis, vals.filter((v) => v !== val))}
                  >
                    ×
                  </button>
                </span>
              ))}
              <form
                className="lib-axis-add"
                onSubmit={(e) => {
                  e.preventDefault();
                  addAxisValue(axis);
                }}
              >
                <input
                  type="text"
                  aria-label={`${axis} 값 추가`}
                  placeholder={`${axis} 추가`}
                  value={draft[axis] ?? ''}
                  disabled={saving}
                  onChange={(e) => setDraft((d) => ({ ...d, [axis]: e.target.value }))}
                />
                <button type="submit" className="lib-add-btn" disabled={saving || !(draft[axis] ?? '').trim()}>
                  추가
                </button>
              </form>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function FileDetail({ file, user, onUpdated, onDeleted }: Props) {
  const [confirmMode, setConfirmMode] = useState<'delete' | 'purge' | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setConfirmMode(null);
    setError(null);
  }, [file?.file_id]);

  if (!file) {
    return (
      <section className="lib-detail lib-detail-empty" aria-label="자료 상세">
        <p className="lib-muted">왼쪽 목록에서 자료를 고르면 미리 보기와 분류를 확인할 수 있습니다.</p>
      </section>
    );
  }

  const currentFile = file;
  const canDelete = user.role === 'admin' || user.id === currentFile.uploaded_by;
  const canPurge = user.role === 'admin';

  async function handleDownload() {
    setError(null);
    try {
      const blob = await libraryApi.rawBlob(currentFile.file_id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = currentFile.name;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : '파일을 내려받지 못했습니다.');
    }
  }

  async function handleConfirmDelete() {
    if (!confirmMode) return;
    setBusy(true);
    setError(null);
    try {
      await libraryApi.remove(currentFile.file_id, confirmMode === 'purge');
      setConfirmMode(null);
      onDeleted(currentFile.file_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : '자료를 지우지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="lib-detail" aria-label="자료 상세">
      <div className="lib-detail-head">
        <h3 title={currentFile.name}>{currentFile.name}</h3>
        <div className="lib-detail-meta">
          <span>{formatBytes(currentFile.size)}</span>
          {currentFile.pages ? <span>{currentFile.pages}쪽</span> : null}
          <span>{formatDate(currentFile.uploaded_at)}</span>
        </div>
      </div>

      {currentFile.summary && <p className="lib-detail-summary">{currentFile.summary}</p>}
      {currentFile.reason && <p className="lib-row-warn">{currentFile.reason}</p>}
      {error && (
        <p className="lib-error" role="alert">
          {error}
        </p>
      )}

      <div className="lib-detail-actions">
        <Button
          variant="primary"
          onClick={() => useWindows.getState().open('chat', { attach: String(currentFile.file_id) })}
        >
          대화에 붙이기
        </Button>
        <Button onClick={handleDownload}>내려받기</Button>
        {canDelete && (
          <Button variant="danger" onClick={() => setConfirmMode('delete')}>
            지우기
          </Button>
        )}
        {canPurge && (
          <Button variant="danger" onClick={() => setConfirmMode('purge')}>
            완전히 지우기
          </Button>
        )}
      </div>

      {confirmMode && (
        <ConfirmDelete
          name={currentFile.name}
          mode={confirmMode}
          busy={busy}
          onCancel={() => setConfirmMode(null)}
          onConfirm={handleConfirmDelete}
        />
      )}

      <Preview file={currentFile} />
      <AxesEditor file={currentFile} onUpdated={onUpdated} onError={setError} />
    </section>
  );
}
