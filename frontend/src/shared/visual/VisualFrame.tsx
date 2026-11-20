// 보고서용 그림(Task 44). Liner Visualization 이 그린 HTML 은 <iframe sandbox="allow-scripts" srcdoc> 로만 보인다
// (allow-same-origin 없음 — 받은 HTML 이 우리 화면·토큰에 손대지 못한다). srcdoc 머리에 CSP(실측 CDN 두 호스트만,
// connect-src 'none', 그림은 data: 만)와 감시 script 를 넣는다. 서버가 숫자 대조에 실패해 html 이 없거나, 그림 파일(CDN)을
// 못 불러오거나, 그리다 오류가 나거나, 30초 안에 차트가 그려지지 않으면 서버 표로 우리 그림(SVG)을 그리고 까닭을 적는다.
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
  error: '그림을 그리다 오류가 나 기본 그림으로 보입니다.',
};

// 서버 대조의 ALLOWED_PREFIXES 와 같은 목록(backend/app/llm/visual_check.py).
const PREFIXES = [
  'https://cdn.jsdelivr.net/npm/@liner-fe/design-token@',
  'https://cdn.jsdelivr.net/npm/pretendard@',
  'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/',
];

/**
 * CSP 의 허용 출처: 서버가 대조한 외부 주소 가운데 PREFIXES 로 시작하는 것의 패키지 폴더(앞부분 다음 첫 '/' 까지).
 * CSP 는 '/' 로 끝나는 경로만 앞부분으로 맞추므로(예: …/pretendard@1.3.9/) 버전 폴더까지 넣는다.
 */
function sources(external: string[]): string {
  const found = new Set<string>();
  for (const raw of external) {
    const url = raw.startsWith('//') ? `https:${raw}` : raw;
    const prefix = PREFIXES.find((p) => url.startsWith(p));
    const cut = prefix ? url.indexOf('/', prefix.length) : -1;
    if (cut > 0) found.add(url.slice(0, cut + 1));
  }
  return [...found].map((s) => ` ${s}`).join('');
}

function csp(external: string[]): string {
  const from = sources(external);
  return (
    `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'${from}; ` +
    `style-src 'unsafe-inline'${from}; font-src${from}; img-src data:; connect-src 'none'">`
  );
}

// iframe 안의 감시: 그림 파일(script·link)을 못 불러오면 'cdn', 그 밖의 script 오류는 'error', Chart.js 를 불러오면
// 전역 플러그인을 달아 차트를 처음 다 그린 뒤(afterRender) 'ready'. 요소의 load 는 window 까지 오지 않아(DOM 명세) document 에서 잡는다. 처음 알린 것 하나만 보낸다(그린 뒤의 오류는 무시).
const WATCH =
  '<script>(function(){var sent=false;function p(t){if(sent)return;sent=true;try{parent.postMessage({chronosVisual:t},"*")}catch(e){}}' +
  'function hook(){if(window.Chart&&Chart.register&&!window.__chronosHook){window.__chronosHook=1;' +
  'Chart.register({id:"chronosReady",afterRender:function(){p("ready")}})}}' +
  'window.addEventListener("error",function(e){var t=e.target;p(t&&(t.tagName==="SCRIPT"||t.tagName==="LINK")?"cdn":"error")},true);' +
  'document.addEventListener("load",function(e){var t=e.target;if(t&&t.tagName==="SCRIPT")hook()},true);' +
  'window.addEventListener("load",function(){if(typeof Chart==="undefined")p("cdn")})})();</script>';

function withWatch(html: string, external: string[]): string {
  const head = csp(external) + WATCH;
  const m = /<head(\s[^>]*)?>/i.exec(html); // <header> 는 아니다
  if (!m) return head + html;
  const at = m.index + m[0].length;
  return html.slice(0, at) + head + html.slice(at);
}

function caption(d: VisualData, drawn: boolean): string {
  const data = `데이터: 크로노스 계산(버전 v${d.version}${d.data_date ? `, 기준일 ${d.data_date}` : ''})`;
  const line = drawn ? `${data} · 그림: Liner Visualization · 숫자 대조 통과 ${d.passed}/${d.total}` : `${data} · 그림: 크로노스 기본 그림`;
  return d.table_note ? `${line} · ${d.table_note}` : line;
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
      else if (kind === 'error') setState({ ready: false, broken: NOTES.error });
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
          <iframe ref={ref} className="vf-iframe" title={data.title} sandbox="allow-scripts" srcDoc={withWatch(data.html ?? '', data.external)} />
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

/** 화면 위 대화상자(보고서용 그림). Esc·[닫기]로 닫고 Tab 은 안에서만 돈다. */
export function VisualDialog({ onClose, children }: { onClose(): void; children: ReactNode }) {
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

interface ButtonProps {
  scheduleId: number;
  kind: VisualKind;
  /** 창이 보이는 버전. */
  version?: number;
  unit?: 'week' | 'month';
  /** 있으면 단추를 끄고 이 글을 옆에 보인다. */
  disabledReason?: string;
}

/** [보고서용 그림] 단추: 누르면 그 일정의 그림을 만들어 대화상자에 보인다. */
export function VisualButton({ scheduleId, kind, version, unit, disabledReason }: ButtonProps) {
  const [open, setOpen] = useState(false);
  const opts = { ...(version !== undefined && { version }), ...(unit !== undefined && { unit }) };
  return (
    <>
      {disabledReason && <span className="vf-off">{disabledReason}</span>}
      <Button onClick={() => setOpen(true)} disabled={disabledReason !== undefined}>
        보고서용 그림
      </Button>
      {open && (
        <VisualDialog onClose={() => setOpen(false)}>
          <VisualPanel load={() => makeVisual(scheduleId, kind, opts)} />
        </VisualDialog>
      )}
    </>
  );
}
