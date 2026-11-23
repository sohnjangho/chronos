// CSV 가져오기 — 넣기 전에 확인(Task 77, 시안 ⑤). 파일을 고르면 미리 보기(dry_run=1)만 부르고, 행을 빼면(X) 그 행 번호를 skip 에 넣어
// 다시 묻는다. [n명 넣기]를 눌러야 같은 파일·같은 skip 으로 넣는다(dry_run=0) — 서버가 다시 판정하므로 결과는 서버의 셈을 보인다.
// 파일과 행은 이 컴포넌트의 상태에만 있다(저장·URL·콘솔 없음). 닫히거나 프로젝트가 바뀌면(창이 다시 그려짐) 사라진다.
import { useEffect, useRef, useState } from 'react';
import Button from '../../shared/ui/Button';
import { importCsv, KIND_LABEL, type ImportOut, type ImportRow } from './contactsApi';
import XferDialog from './XferDialog';

const MAX_BYTES = 1024 * 1024;
const ENCODING = '엑셀에서 저장한 CSV 는 한글이 깨질 수 있습니다 — 깨지면 UTF-8 로 저장해 주세요';
const isBad = (r: ImportRow) => r.result === 'bad_phone' || r.result === 'bad_row';
const adds = (o: ImportOut) => o.summary.new + o.summary.no_phone;
const message = (e: unknown) => (e instanceof Error ? e.message : '요청을 처리할 수 없습니다.');

function summaryText(o: ImportOut, done: boolean): string {
  const s = o.summary;
  const head = done ? `${adds(o)}명 넣었습니다` : `${o.rows.length}행 중 ${adds(o)}행 넣음`;
  return `${head} · ${s.exists}행 건너뜀 · ${s.bad}행 오류${s.skipped ? ` · ${s.skipped}행 뺌` : ''}`;
}

function Verdict({ r, done }: { r: ImportRow; done: boolean }) {
  if (r.skipped) return <span className="ct-tag">뺌</span>;
  const [label, tone] = {
    new: [done ? '넣음' : '새로 넣음', 'is-ok'],
    no_phone: [done ? '넣음 · 번호 없음(보내기 불가)' : '번호 없음 · 넣되 보내기 불가', 'is-warn'],
    exists: ['이미 있음 · 건너뜀', ''],
    bad_phone: ['번호 형식 오류', 'is-bad'],
    bad_row: [r.column ? `「${r.column}」 칸 오류` : '행 오류', 'is-bad'],
  }[r.result];
  return (
    <>
      <span className="ct-xfer-tags">
        <span className={`ct-tag ${tone}`}>{label}</span>
        {r.do_not_contact && <span className="ct-tag is-bad">수신 거부</span>}
      </span>
      {r.reason && <span className="ct-xfer-reason">{r.reason}</span>}
    </>
  );
}

const Cell = ({ text }: { text: string | null }) =>
  text ? (
    <span className="ct-ellipsis ct-xfer-cell" title={text}>
      {text}
    </span>
  ) : (
    <span className="ct-muted">—</span>
  );

function PreviewTable({ rows, done, busy, onToggle }: { rows: ImportRow[]; done: boolean; busy: boolean; onToggle: (n: number) => void }) {
  return (
    <table className="ct-xfer-tbl" aria-label="미리 보기">
      <thead>
        <tr>
          {['행', '협력사', '이름', '담당', '전화번호', '결과', ...(done ? [] : ['빼기'])].map((h) => (
            <th key={h} scope="col" className={h === '행' || h === '빼기' ? 'ct-xfer-narrow' : undefined}>
              {h === '빼기' ? <span className="ct-sr">빼기</span> : h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.n} aria-label={`${r.n}행`} className={r.skipped ? 'is-skipped' : isBad(r) && !r.skipped ? 'is-bad' : undefined}>
            <td className="ct-num ct-muted" data-label="행">{r.n}</td>
            <td data-label="협력사"><Cell text={r.company} /></td>
            <td data-label="이름"><Cell text={r.name} /></td>
            <td data-label="담당"><Cell text={r.role_title} /></td>
            <td data-label="전화번호">
              <span className="ct-xfer-tags">
                <span className="ct-num">{r.phone_shown}</span>
                {r.phone_kind && r.phone_kind !== 'mobile' && <span className="ct-tag">{KIND_LABEL[r.phone_kind]}</span>}
              </span>
            </td>
            <td data-label="결과"><Verdict r={r} done={done} /></td>
            {!done && (
              <td className="ct-xfer-x">
                {r.skipped ? (
                  <button type="button" className="ct-link" aria-label={`${r.n}행 되돌리기`} disabled={busy} onClick={() => onToggle(r.n)}>
                    되돌리기
                  </button>
                ) : (
                  <button type="button" className="ct-xfer-del" aria-label={`${r.n}행 빼기`} title="이 행은 넣지 않기" disabled={busy} onClick={() => onToggle(r.n)}>
                    ✕
                  </button>
                )}
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function useImport(scheduleId: number, onDone: () => void) {
  const [file, setFile] = useState<File | null>(null);
  const [skip, setSkip] = useState<number[]>([]);
  const [preview, setPreview] = useState<ImportOut | null>(null);
  const [result, setResult] = useState<ImportOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'preview' | 'commit' | null>(null);
  const seq = useRef(0);
  useEffect(() => () => void (seq.current += 1), []); // 닫힌 뒤 온 답은 버린다

  async function run<T>(kind: 'preview' | 'commit', call: () => Promise<T>, ok: (v: T) => void) {
    const my = ++seq.current;
    setBusy(kind);
    setError(null);
    try {
      const v = await call();
      if (my === seq.current) ok(v);
    } catch (e) {
      if (my === seq.current) setError(message(e));
    } finally {
      if (my === seq.current) setBusy(null);
    }
  }
  const ask = (f: File, s: number[]) => run('preview', () => importCsv(scheduleId, f, s, true), (out) => {
    setPreview(out);
    setSkip(s);
  });
  return {
    file, preview, result, error, busy,
    choose(f: File) {
      seq.current += 1;
      setFile(null);
      setPreview(null);
      setSkip([]);
      setBusy(null);
      if (!/\.csv$/i.test(f.name)) return setError('CSV 파일(.csv)만 고를 수 있습니다.');
      if (f.size > MAX_BYTES) return setError('CSV 파일은 1MB 까지 올릴 수 있습니다.');
      setFile(f);
      void ask(f, []);
    },
    toggle(n: number) {
      if (file) void ask(file, skip.includes(n) ? skip.filter((x) => x !== n) : [...skip, n].sort((a, b) => a - b));
    },
    commit() {
      if (file) void run('commit', () => importCsv(scheduleId, file, skip, false), (out) => {
        setResult(out);
        onDone();
      });
    },
  };
}

export default function CsvImport({ scheduleId, onClose, onDone }: { scheduleId: number; onClose: () => void; onDone: () => void }) {
  const im = useImport(scheduleId, onDone);
  const [errorsOnly, setErrorsOnly] = useState(false);
  const shown = im.result ?? im.preview;
  const rows = shown && errorsOnly && !im.result ? shown.rows.filter((r) => isBad(r) && !r.skipped) : (shown?.rows ?? []);
  const n = im.preview ? adds(im.preview) : 0;
  const foot = (
    <>
      <span className="ct-xfer-sum" aria-live="polite">
        {im.busy === 'preview' ? '미리 보는 중…' : im.busy === 'commit' ? '넣는 중…' : shown ? summaryText(shown, im.result !== null) : ''}
      </span>
      {im.result ? (
        <Button variant="primary" onClick={onClose}>닫기</Button>
      ) : (
        <>
          <Button onClick={onClose} disabled={im.busy === 'commit'}>취소</Button>
          {im.preview && (
            <Button variant="primary" onClick={im.commit} disabled={n === 0 || im.busy !== null}>{`${n}명 넣기`}</Button>
          )}
        </>
      )}
    </>
  );
  return (
    <XferDialog title="CSV 가져오기" wide busy={im.busy === 'commit'} onClose={onClose} foot={foot}>
      <div className="ct-xfer-top">
        <div className="ct-xfer-pickrow">
          <label className={`ui-btn ct-xfer-pick${im.result ? ' is-off' : ''}`}>
            <input
              type="file"
              className="ct-sr"
              accept=".csv,text/csv"
              aria-label="CSV 파일 고르기"
              disabled={im.result !== null || im.busy === 'commit'}
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = '';
                if (f) im.choose(f);
              }}
            />
            {im.file ? '다른 파일 고르기' : 'CSV 파일 고르기'}
          </label>
          {im.file && <span className="ct-ellipsis ct-xfer-file" title={im.file.name}>{im.file.name}</span>}
        </div>
        <p className="ct-hint is-warn">{ENCODING}</p>
        <p className="ct-hint ct-xfer-cols">첫 줄은 열 이름 — 협력사·이름(꼭 있어야 함) · 공종·담당·전화번호·성별·언어·메모. 한 번에 500행·1MB 까지.</p>
        {im.error && <p className="ct-error" role="alert">{im.error}</p>}
        {im.result && adds(im.result) !== n && <p className="ct-hint is-warn">미리 본 뒤 주소록이 바뀌어 결과가 미리 보기와 다릅니다.</p>}
        {im.preview && !im.result && (
          <label className="ct-check ct-xfer-filter">
            <input type="checkbox" checked={errorsOnly} disabled={im.preview.summary.bad === 0} onChange={(e) => setErrorsOnly(e.target.checked)} />
            {`오류만 보기 (${im.preview.summary.bad}행)`}
          </label>
        )}
      </div>
      <div className="ct-xfer-scroll">
        {shown ? (
          <PreviewTable rows={rows} done={im.result !== null} busy={im.busy !== null} onToggle={im.toggle} />
        ) : (
          <p className="ct-muted ct-pad">
            {!im.file
              ? '파일을 고르면 넣기 전에 행마다 무엇이 들어가는지 먼저 보여 드립니다. 넣기 전에는 아무것도 저장하지 않습니다.'
              : im.error
                ? '파일을 고친 뒤 다시 골라 주세요.'
                : '미리 보는 중…'}
          </p>
        )}
      </div>
    </XferDialog>
  );
}
