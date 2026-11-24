// 사진 사람 판독(PM 11-24, 시안 B): 왼쪽 = 「사람 판독 대기 / 다시 찍기 요청 / 사람 판독함」으로 묶은 목록 + 찾기,
// 오른쪽 = 고른 사진을 크게 + 진도율·근거 한 줄 → 승인함(현장 보고와 같은 길). 다시 찍기 요청은 사진 줄에 남기고(올린 사람이 본다)
// 문자는 이미 있는 연락 창(ContactButton → BatchSendDialog)으로 보낸다. 관리자(설정으로 사용자까지)에게만 그린다.
import { useState } from 'react';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import ContactButton from '../../shared/outreach/ContactButton';
import { cleanValue } from '../../shared/outreach/contactKit';
import type { FieldActivityOption, FieldItem } from './fieldApi';

export const HUMAN_STATUSES: readonly string[] = ['human_wait', 'retake', 'retaken'];
/** 사람 판독 화면에 드는 사진 줄(대기·요청·다시 올림·사람이 넣은 것). */
export const isHumanItem = (i: FieldItem) => i.kind === 'photo' && (HUMAN_STATUSES.includes(i.status) || i.response_choice === 'human');

type Info = Record<string, unknown>;
const info = (i: FieldItem, key: string): Info => (i.payload_json?.[key] as Info | undefined) ?? {};
export const uploaderOf = (i: FieldItem) => String(info(i, 'uploaded_by').name ?? '') || i.trade;
const when = (i: FieldItem) => String(i.payload_json?.captured_at ?? '');
const why = (i: FieldItem) => String(i.payload_json?.unread_reason ?? '');

const GROUPS: { key: string; label: string; pick(i: FieldItem): boolean }[] = [
  { key: 'wait', label: '사람 판독 대기', pick: (i) => i.status === 'human_wait' },
  { key: 'retake', label: '다시 찍기 요청 — 새 사진을 기다림', pick: (i) => i.status === 'retake' },
  { key: 'done', label: '사람 판독함', pick: (i) => i.response_choice === 'human' },
];

function resultLine(i: FieldItem): string {
  const h = info(i, 'human_read');
  if (i.response_choice === 'human') return `사람 판독 · ${String(h.by ?? '')} — ${String(h.progress ?? i.reported_progress)}%${i.approval_id !== null ? ` · 승인함 #${i.approval_id}` : ''}`;
  if (i.status === 'retake') return `다시 찍기 요청 — ${String(info(i, 'retake').reason ?? '')}`;
  return why(i);
}

interface Props {
  scheduleId: number;
  items: FieldItem[];
  activities: FieldActivityOption[];
  busy: boolean;
  onHumanRead(id: number, progress: number, reason: string): Promise<void>;
  onRetake(id: number, reason: string): Promise<void>;
}

export default function HumanRead({ scheduleId, items, activities, busy, onHumanRead, onRetake }: Props) {
  const [query, setQuery] = useState('');
  const [picked, setPicked] = useState<number | null>(null);
  const q = query.trim().toLowerCase();
  const shown = items.filter(
    (i) => !q || [i.activity_id, i.activity_name, i.trade, uploaderOf(i)].some((t) => t.toLowerCase().includes(q)),
  );
  const groups = GROUPS.map((g) => {
    const rows = shown.filter(g.pick);
    return { ...g, rows: g.key === 'wait' ? [...rows].sort((a, b) => a.id - b.id) : rows }; // 대기는 오래된 것부터
  });
  const flat = groups.flatMap((g) => g.rows);
  const current = flat.find((i) => i.id === picked) ?? flat[0] ?? null;

  return (
    <div className="pg-hr" role="region" aria-label="사진 사람 판독">
      <div className="pg-hr-list">
        <div className="pg-hr-bar">
          <input
            className="pg-finput-text pg-hr-search"
            type="search"
            aria-label="사람 판독 찾기"
            placeholder="작업·공종·올린 사람으로 찾기"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="pg-hr-scroll">
          {flat.length === 0 && <p className="pg-muted pg-hr-empty">{q ? '찾는 사진이 없습니다.' : '사람 판독을 기다리는 사진이 없습니다.'}</p>}
          {groups.map(
            (g) =>
              g.rows.length > 0 && (
                <section key={g.key} aria-label={`${g.label} ${g.rows.length}`}>
                  <h4 className="pg-hr-group">{`${g.label} ${g.rows.length}`}</h4>
                  <ul className="pg-hr-ul">
                    {g.rows.map((i) => (
                      <li key={i.id}>
                        <button
                          type="button"
                          className="pg-hr-row"
                          aria-current={current?.id === i.id ? 'true' : undefined}
                          onClick={() => setPicked(i.id)}
                        >
                          <Thumb item={i} />
                          <span className="pg-hr-cell">
                            <b className="pg-hr-clip" title={`${i.activity_id} ${i.activity_name}`}>{`${i.activity_id} ${i.activity_name}`}</b>
                            <small className="pg-hr-clip">{`${uploaderOf(i)} · ${when(i)}`}</small>
                          </span>
                          <span className="pg-hr-cell pg-hr-why">
                            <small className="pg-hr-clip" title={resultLine(i)}>{resultLine(i)}</small>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              ),
          )}
        </div>
      </div>
      <aside className="pg-hr-side" aria-label="사람 판독 자세히">
        {current ? (
          <Detail
            key={current.id}
            item={current}
            scheduleId={scheduleId}
            recorded={activities.find((a) => a.id === current.activity_id)?.progress ?? null}
            busy={busy}
            onHumanRead={onHumanRead}
            onRetake={onRetake}
          />
        ) : (
          <p className="pg-muted">왼쪽에서 사진을 고르세요.</p>
        )}
      </aside>
    </div>
  );
}

function Thumb({ item }: { item: FieldItem }) {
  const url = typeof item.payload_json?.photo_data_url === 'string' ? item.payload_json.photo_data_url : null;
  return url ? <img className="pg-hr-thumb" src={url} alt="" /> : <span className="pg-hr-thumb" aria-hidden="true" />;
}

function Detail({
  item,
  scheduleId,
  recorded,
  busy,
  onHumanRead,
  onRetake,
}: {
  item: FieldItem;
  scheduleId: number;
  recorded: number | null;
  busy: boolean;
  onHumanRead(id: number, progress: number, reason: string): Promise<void>;
  onRetake(id: number, reason: string): Promise<void>;
}) {
  const open = item.status === 'human_wait' || item.status === 'retake';
  const url = typeof item.payload_json?.photo_data_url === 'string' ? item.payload_json.photo_data_url : null;
  const human = info(item, 'human_read');
  const asked = info(item, 'retake');
  const act = `${item.activity_id} ${item.activity_name}`;
  return (
    <div className="pg-hr-detail">
      <div className="pg-hr-head">
        <h3 className="pg-hr-title">{act}</h3>
        {item.status === 'human_wait' && <Badge tone="warning">사람 판독 대기</Badge>}
        {item.status === 'retake' && <Badge tone="warning">다시 찍기 요청</Badge>}
        {item.response_choice === 'human' && <Badge tone="info">사람 판독</Badge>}
      </div>
      {url ? <img className="pg-hr-photo" src={url} alt={`${act} 사진`} /> : <div className="pg-hr-photo pg-hr-nophoto">사진 없음</div>}
      <dl className="pg-hr-kv">
        <dt>올린 사람</dt>
        <dd>{`${uploaderOf(item)} · ${when(item)}`}</dd>
        <dt>AI 판독</dt>
        <dd>{`판독하지 않음 — ${why(item)}`}</dd>
        <dt>기록된 진도</dt>
        <dd>
          {recorded === null ? '—' : <b>{`${recorded}%`}</b>} <span className="pg-muted">(비교용 — AI 에는 보내지 않음)</span>
        </dd>
        {item.status === 'retake' && (
          <>
            <dt>다시 찍기</dt>
            <dd>{`${String(asked.by ?? '')} 요청 — ${String(asked.reason ?? '')}`}</dd>
          </>
        )}
        {item.response_choice === 'human' && (
          <>
            <dt>사람 판독</dt>
            <dd>{`사람 판독 · ${String(human.by ?? '')} — ${String(human.progress ?? item.reported_progress)}% · ${String(human.reason ?? '')}`}</dd>
            <dt>승인함</dt>
            <dd>{item.approval_id !== null ? `#${item.approval_id} 에 올림` : '—'}</dd>
          </>
        )}
      </dl>
      {open && <ReadForm item={item} act={act} scheduleId={scheduleId} busy={busy} onHumanRead={onHumanRead} onRetake={onRetake} />}
    </div>
  );
}

/** 사람 판독 입력(진도율·근거 한 줄)과 다시 찍기 요청. 요청을 남긴 사진은 연락 창으로 문자도 보낼 수 있다. */
function ReadForm({
  item,
  act,
  scheduleId,
  busy,
  onHumanRead,
  onRetake,
}: {
  item: FieldItem;
  act: string;
  scheduleId: number;
  busy: boolean;
  onHumanRead(id: number, progress: number, reason: string): Promise<void>;
  onRetake(id: number, reason: string): Promise<void>;
}) {
  const [pct, setPct] = useState('');
  const [reason, setReason] = useState('');
  const [asking, setAsking] = useState(false);
  const [retakeWhy, setRetakeWhy] = useState('');
  const n = Number(pct);
  const valid = pct.trim() !== '' && Number.isInteger(n) && n >= 0 && n <= 100 && reason.trim() !== '';
  const asked = info(item, 'retake');
  return (
      <>
        <h4 className="pg-hr-sec">사람 판독</h4>
        <div className="pg-hr-form">
          <label className="pg-flabel">
            <span>진도율 (%)</span>
            <input inputMode="numeric" placeholder="0~100" value={pct} disabled={busy} onChange={(e) => setPct(e.target.value.replace(/[^0-9]/g, '').slice(0, 3))} />
          </label>
          <label className="pg-flabel">
            <span>근거 한 줄</span>
            <input maxLength={200} placeholder="이 진도로 본 까닭 한 줄" value={reason} disabled={busy} onChange={(e) => setReason(e.target.value)} />
          </label>
        </div>
        <p className="pg-muted pg-hr-hint">
          {`올리면 승인함에 「[현장 반영] ${act} (${valid ? n : 'n'}%)」 건으로 갑니다. 승인되기 전에는 일정이 바뀌지 않고, 기록에는 「사람 판독 · 이름」이 남습니다.`}
        </p>
        {asking && (
          <div className="pg-hr-form pg-hr-retake">
            <label className="pg-flabel">
              <span>다시 찍을 까닭 (올린 사람에게 보입니다)</span>
              <input maxLength={200} placeholder="예: 보가 걸린 자리와 설치된 보가 함께 보이게 낮에 다시 찍어 주세요" value={retakeWhy} disabled={busy} onChange={(e) => setRetakeWhy(e.target.value)} />
            </label>
            <Button disabled={busy || !retakeWhy.trim()} onClick={() => void onRetake(item.id, retakeWhy.trim()).then(() => setAsking(false))}>
              요청 남기기
            </Button>
          </div>
        )}
        <div className="pg-hr-actions">
          {!asking && (
            <Button disabled={busy} onClick={() => setAsking(true)}>
              다시 찍어 달라고 요청
            </Button>
          )}
          {item.status === 'retake' && (
            <ContactButton
              scheduleId={scheduleId}
              activityId={item.activity_id}
              label="문자·카카오톡으로도 알리기"
              title={`다시 찍기 알리기 — ${act}`}
              preset={{ fieldItemId: item.id, trade: item.trade, body: `사진을 다시 찍어 주세요 — ${cleanValue(act)}: ${cleanValue(asked.reason, 160)}` }}
            />
          )}
          <span className="sch-gap" />
          <Button variant="primary" disabled={busy || !valid} onClick={() => void onHumanRead(item.id, n, reason.trim())}>
            사람 판독으로 승인함에 올리기
          </Button>
        </div>
      </>
  );
}
