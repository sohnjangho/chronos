// 보고서용 그림(Task 44). Liner Visualization 이 그린 HTML 은 <iframe sandbox="allow-scripts" srcdoc> 로만 보인다
// (allow-same-origin 없음 — 받은 HTML 이 우리 화면·토큰에 손대지 못한다). 서버가 숫자 대조에 실패해 html 이 없거나,
// 그림 파일(CDN)을 못 불러오거나, 30초 안에 다 그리지 못하면 서버 표로 우리 그림(SVG)을 그리고 까닭을 적는다.
// 화면은 값을 계산하지 않는다 — 표(columns·rows)는 서버 계산값 그대로다.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useModalFocus } from '../../os/modalFocus';
import { ApiError } from '../api';
import Button from '../ui/Button';
import FallbackChart from './FallbackChart';
import { makeVisual, type VisualData, type VisualKind } from './visualApi';
import './visual.css';

export const WAIT_MS = 30_000;
const NOTES = {
  cdn: '그림 파일(CDN)을 불러오지 못해 기본 그림으로 보입니다.',
  slow: '그림이 30초 안에 그려지지 않아 기본 그림으로 보입니다.',
};

// iframe 안에서 그림 파일(script·link)을 못 불러오면 'cdn', 다 불러오면 'ready' 를 부모에게 알린다.
const WATCH =
  "<script>(function(){function p(t){try{parent.postMessage({chronosVisual:t},'*')}catch(e){}}" +
  "window.addEventListener('error',function(e){var t=e.target;if(t&&(t.tagName==='SCRIPT'||t.tagName==='LINK'))p('cdn')},true);" +
  "window.addEventListener('load',function(){p(typeof Chart==='undefined'?'cdn':'ready')})})();</script>";

function withWatch(html: string): string {
  const m = /<head[^>]*>/i.exec(html);
  if (!m) return WATCH + html;
  const at = m.index + m[0].length;
  return html.slice(0, at) + WATCH + html.slice(at);
}

function caption(d: VisualData, drawn: boolean): string {
  const data = `데이터: 크로노스 계산(버전 v${d.version}${d.data_date ? `, 기준일 ${d.data_date}` : ''})`;
  return drawn ? `${data} · 그림: Liner Visualization · 숫자 대조 통과 ${d.passed}/${d.total}` : `${data} · 그림: 크로노스 기본 그림`;
}

function DataTable({ d }: { d: VisualData }) {
  return (
    <details className="vf-fold">
      <summary>표 보기</summary>
      <div className="vf-table-wrap">
        <table className="vf-table" aria-label="그림의 표">
          <thead>
            <tr>
              {d.columns.map((c) => (
                <th key={c} scope="col">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {d.rows.map((r, i) => (
              <tr key={i}>
                {r.map((v, j) => (
                  <td key={j}>{v === null ? '' : String(v)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/** 그림 한 장: Liner HTML(sandbox) 또는 우리 그림 + 캡션 + 접힌 표. */
export default function VisualFrame({ data, height = 520 }: { data: VisualData; height?: number }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [state, setState] = useState<{ ready: boolean; broken: string | null }>({ ready: false, broken: null });
  const drawn = data.html !== null && state.broken === null;
  useEffect(() => {
    if (!drawn || state.ready) return;
    const onMessage = (e: MessageEvent) => {
      const kind = (e.data as { chronosVisual?: unknown } | null)?.chronosVisual;
      if (!ref.current || e.source !== ref.current.contentWindow) return;
      if (kind === 'ready') setState({ ready: true, broken: null });
      else if (kind === 'cdn') setState({ ready: false, broken: NOTES.cdn });
    };
    const timer = setTimeout(() => setState({ ready: false, broken: NOTES.slow }), WAIT_MS);
    window.addEventListener('message', onMessage);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('message', onMessage);
    };
  }, [drawn, state.ready]);
  const note = state.broken ?? (data.fallback ? data.note : '');
  return (
    <figure className="vf-root">
      {drawn ? (
        <div className="vf-stage" style={{ height }}>
          <iframe ref={ref} className="vf-iframe" title={data.title} sandbox="allow-scripts" srcDoc={withWatch(data.html ?? '')} />
          {!state.ready && <div className="vf-wait">그림 만드는 중…</div>}
        </div>
      ) : (
        <FallbackChart data={data} />
      )}
      {note && (
        <p className="vf-note" role="note">
          {note}
        </p>
      )}
      <figcaption className="vf-caption">{caption(data, drawn)}</figcaption>
      <DataTable d={data} />
    </figure>
  );
}

/** 서버 그림 모양인가(표가 목록이고 줄도 목록). 아니면 그리지 않고 오류로 보인다. */
const isVisual = (d: unknown): d is VisualData =>
  typeof d === 'object' && d !== null && Array.isArray((d as VisualData).columns) && Array.isArray((d as VisualData).rows) &&
  (d as VisualData).rows.every(Array.isArray);

type Load = { status: 'loading' } | { status: 'slow' } | { status: 'done'; data: VisualData } | { status: 'error'; message: string };

/** load() 로 그림을 받아 보인다. 받는 동안 「그림 만드는 중…」, 30초가 넘으면 다시 불러오기(서버는 끝난 그림을 바로 준다). */
export function VisualPanel({ load, height }: { load: () => Promise<VisualData>; height?: number }) {
  const [state, setState] = useState<Load>({ status: 'loading' });
  const [n, setN] = useState(0);
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  });
  useEffect(() => {
    let live = true;
    setState({ status: 'loading' });
    const timer = setTimeout(() => live && setState((s) => (s.status === 'loading' ? { status: 'slow' } : s)), WAIT_MS);
    loadRef.current().then(
      (data) => live && setState(isVisual(data) ? { status: 'done', data } : { status: 'error', message: '그림 응답을 읽을 수 없습니다.' }),
      (e: unknown) => live && setState({ status: 'error', message: e instanceof ApiError ? e.message : '그림을 만들 수 없습니다.' }),
    );
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [n]);
  const retry = <Button onClick={() => setN((x) => x + 1)}>다시 불러오기</Button>;
  if (state.status === 'done') return <VisualFrame key={state.data.id} data={state.data} height={height} />;
  if (state.status === 'loading') return <div className="vf-wait is-static">그림 만드는 중…</div>;
  return (
    <div className="vf-wait is-static">
      <p role="alert">{state.status === 'slow' ? '30초 안에 그림이 오지 않았습니다. 서버는 계속 만들고 있습니다.' : state.message}</p>
      {retry}
    </div>
  );
}

function Dialog({ onClose, children }: { onClose(): void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const trap = useModalFocus(ref);
  useEffect(() => ref.current?.focus(), []);
  return createPortal(
    <div className="vf-scrim">
      <div
        ref={ref}
        className="vf-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="보고서용 그림"
        tabIndex={-1}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.stopPropagation();
            onClose();
          }
          trap(e);
        }}
      >
        <div className="vf-dialog-h">
          <h3>보고서용 그림</h3>
          <Button onClick={onClose}>닫기</Button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

/** [보고서용 그림] 단추: 누르면 그 일정의 그림을 만들어 대화상자에 보인다. */
export function VisualButton({ scheduleId, kind, version, disabled }: { scheduleId: number; kind: VisualKind; version?: number; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)} disabled={disabled}>
        보고서용 그림
      </Button>
      {open && (
        <Dialog onClose={() => setOpen(false)}>
          <VisualPanel load={() => makeVisual(scheduleId, kind, version)} />
        </Dialog>
      )}
    </>
  );
}
