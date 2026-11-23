// 현장 모바일 협업 허브: ① 일일 1분 체크인 ② 사진 AI 진도 판독 ③ 만회안 공종 의견 조회 ④ D-3 핸드오프 점검
import { useEffect, useState, type ChangeEvent } from 'react';
import { useSession } from '../../os/session';
import { useActiveDevice } from '../../os/useIsMobile';
import { useWindows } from '../../os/windowStore';
import { ApiError } from '../../shared/api';
import { resizeImage } from '../../shared/files/resizeImage';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import { fieldApi, type FieldActivityOption, type FieldData, type FieldItem, type FieldKind } from './fieldApi';

const TABS: { id: FieldKind; label: string }[] = [
  { id: 'checkin', label: '일일 체크인' },
  { id: 'photo', label: '사진 AI 판독' },
  { id: 'poll', label: '만회안 의견 조회' },
  { id: 'handoff', label: 'D-3 핸드오프 점검' },
];

const SAMPLE_PHOTOS = [
  { key: 'rebar', label: '샘플: 골조 철근·거푸집 검측', file: 'rebar_formwork_check.jpg', note: '철근 배근 1차 완료, 거푸집 조립 양호' },
  { key: 'curtain', label: '샘플: 외장 커튼월 양중 간섭', file: 'curtainwall_crane_delay.jpg', note: '강풍으로 외장 커튼월 양중 지연 우려' },
  { key: 'mold', label: '샘플: 부품 라인 금형 세팅', file: 'press_mold_setup.jpg', note: '프레스 금형 장착 완료, 연속 가동 준비' },
] as const;

/** 현장 관리자가 올린 보고는 승인 수준과 상관없이 승인을 기다린다(서버 agent/proposals) — 올린 뒤 알리는 글. */
const FIELD_WAITS = '승인함에 올렸습니다 — 승인되기 전에는 일정이 바뀌지 않습니다.';

function StatusBadge({ item }: { item: FieldItem }) {
  if (item.approval_id !== null) return <Badge tone="info">{`승인함 #${item.approval_id} 상신`}</Badge>;
  if (item.kind === 'handoff') {
    return item.response_choice === 'ready' ? <Badge tone="success">인계·투입 준비 완료</Badge> : <Badge tone="warning">사전 조치 필요</Badge>;
  }
  if (item.status === 'pending') return <Badge tone="warning">회신 대기</Badge>;
  if (item.response_choice === 'unread') return <Badge tone="warning">판독하지 않음</Badge>;
  if (item.response_choice === 'delayed' || item.response_choice === 'infeasible' || item.response_choice === 'risk') {
    return <Badge tone="danger">지연·불가 우려</Badge>;
  }
  if (item.response_choice === 'conditional') return <Badge tone="warning">조건부 가능</Badge>;
  return <Badge tone="success">회신 완료</Badge>;
}

function SamplePhotoGraphic({ kindKey }: { kindKey: string }) {
  return (
    <svg viewBox="0 0 240 120" className="pg-photo-svg" aria-hidden="true">
      <rect x="0" y="0" width="240" height="120" rx="8" fill="currentColor" opacity="0.08" />
      <path d="M18 96h204M36 96V34h72v62M126 96V48h78v48" stroke="currentColor" strokeWidth="2.5" fill="none" opacity="0.45" />
      <path d="M46 52h52M46 68h52M138 64h54M138 80h54" stroke="currentColor" strokeWidth="2" strokeDasharray={kindKey === 'curtain' ? '4 4' : undefined} opacity="0.7" />
      <circle cx="190" cy="24" r="10" fill="currentColor" opacity="0.28" />
    </svg>
  );
}

function CheckinCard({
  item,
  busy,
  onSave,
  onSubmitReport,
}: {
  item: FieldItem;
  busy: boolean;
  onSave(choice: string, progress: number | null, rd: number | null, note: string): Promise<void>;
  onSubmitReport(choice: string, progress: number | null, rd: number | null, note: string): Promise<void>;
}) {
  // 회신 전 카드는 값을 비워 둔다 — 고르지 않은 「정상 진행」·진도가 눌린 채 그대로 제출되지 않게(F7).
  const waiting = item.status === 'pending';
  const [choice, setChoice] = useState<string | null>(waiting ? null : (item.response_choice ?? 'on_track'));
  const [progress, setProgress] = useState<number | null>(waiting ? null : (item.reported_progress ?? 50));
  const [rd, setRd] = useState<number | null>(waiting ? null : (item.reported_rd ?? 3));
  const [note, setNote] = useState(item.response_note);

  return (
    <article className="pg-fcard" aria-label={item.title}>
      <div className="pg-fcard-head">
        <div>
          <div className="pg-fcard-trade">{item.trade}</div>
          <h4 className="pg-fcard-title">{item.title}</h4>
        </div>
        <StatusBadge item={item} />
      </div>
      <p className="pg-muted">{item.prompt_text}</p>

      <div className="pg-choice-row" role="group" aria-label="진행 상태 선택">
        {[
          ['on_track', '✓ 정상 진행'],
          ['delayed', '⚠ 지연 우려'],
          ['done', '★ 완료 (100%)'],
        ].map(([val, label]) => (
          <button
            key={val}
            type="button"
            className="pg-choice-btn"
            aria-pressed={choice === val}
            disabled={busy}
            onClick={() => {
              setChoice(val);
              if (val === 'done') {
                setProgress(100);
                setRd(0);
              }
            }}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="pg-chip-row" role="group" aria-label="진도율 빠른 선택">
        {[25, 50, 75, 100].map((pct) => (
          <button
            key={pct}
            type="button"
            className="pg-chip"
            aria-pressed={progress === pct}
            disabled={busy}
            onClick={() => {
              setProgress(pct);
              if (pct === 100) {
                setChoice('done');
                setRd(0);
              }
            }}
          >
            {`${pct}%`}
          </button>
        ))}
      </div>

      <div className={choice === 'delayed' ? 'pg-finputs' : 'pg-finputs is-single'}>
        <label className="pg-flabel">
          <span>진도율 (%)</span>
          <input
            type="number"
            min={0}
            max={100}
            value={progress ?? ''}
            placeholder={item.reported_progress !== null ? `지금 ${item.reported_progress}%` : undefined}
            disabled={busy}
            onChange={(e) => setProgress(e.target.value === '' ? null : Number(e.target.value))}
          />
        </label>
        {choice === 'delayed' && (
          <label className="pg-flabel">
            <span>예상 잔여일 (RD)</span>
            <input
              type="number"
              min={0}
              max={365}
              value={rd ?? ''}
              disabled={busy}
              onChange={(e) => setRd(e.target.value === '' ? null : Number(e.target.value))}
            />
          </label>
        )}
      </div>
      <input
        type="text"
        className="pg-finput-text"
        placeholder={choice === 'delayed' ? '지연 사유를 간단히 적어 주세요 (예: 자재 반입 2일 지연)' : '현장 특이사항 · 메모 한 줄 (선택)'}
        aria-label="현장 메모"
        value={note}
        disabled={busy}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="pg-fcard-foot">
        <Button
          variant="primary"
          className="pg-submit-one"
          disabled={busy || item.approval_id !== null || choice === null}
          onClick={() => choice !== null && void onSubmitReport(choice, progress, rd, note)}
        >
          {item.approval_id !== null ? `보고·상신 완료 (#${item.approval_id})` : '현장 보고 제출 (저장·승인 반영)'}
        </Button>
        <Button disabled={busy || choice === null} onClick={() => choice !== null && void onSave(choice, progress, rd, note)}>
          임시 저장
        </Button>
      </div>
    </article>
  );
}

const PHOTO_MAX_EDGE = 1280;
/** 서버 사진 data URL 한도(backend progress/field.py PHOTO_DATA_URL_MAX 와 같다). */
const PHOTO_MAX_CHARS = 1_500_000;
const PHOTO_TOO_BIG = '사진이 너무 큽니다 — 더 작은 사진으로 다시 올려 주세요';

const readDataUrl = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => (typeof reader.result === 'string' ? resolve(reader.result) : reject(new Error('read')));
    reader.onerror = () => reject(new Error('read'));
    reader.readAsDataURL(file);
  });

function PhotoUploader({
  activities,
  busy,
  onUpload,
}: {
  activities: FieldActivityOption[];
  busy: boolean;
  onUpload(body: { activity_id: string; trade?: string; photo_name: string; photo_data_url?: string; note?: string }): Promise<void>;
}) {
  const [activityId, setActivityId] = useState(activities[0]?.id ?? '');
  const [trade, setTrade] = useState('');
  const [photoName, setPhotoName] = useState('');
  const [dataUrl, setDataUrl] = useState<string | undefined>(undefined);
  const [note, setNote] = useState('');

  const [tooBig, setTooBig] = useState(false);

  // 휴대폰 사진은 수 MB 라 서버 한도를 넘는다 — 긴 변 1280px·JPEG 0.7 로 줄여 보낸다. 줄여도 넘으면 보내지 않는다(I-2).
  const handleFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const { file: small } = await resizeImage(file, PHOTO_MAX_EDGE, { always: true, quality: 0.7 });
    const url = await readDataUrl(small);
    const fits = url.length <= PHOTO_MAX_CHARS;
    setTooBig(!fits);
    setPhotoName(fits ? file.name : '');
    setDataUrl(fits ? url : undefined);
  };

  return (
    <section className="pg-card pg-fbox" aria-label="현장 사진 촬영 및 AI 판독">
      <div className="pg-card-head">
        <h3 className="pg-card-title">현장 사진 AI 진도율 판독 · 증빙 등록</h3>
        <span className="pg-muted">스마트폰·태블릿 카메라로 촬영하거나 파일을 붙이면 그림 읽기 모델이 판독합니다. 샘플 단추는 사진이 없어 판독하지 않습니다.</span>
      </div>
      <div className="pg-fgrid-form">
        <label className="pg-flabel">
          <span>대상 액티비티</span>
          <select value={activityId} disabled={busy} onChange={(e) => setActivityId(e.target.value)}>
            {activities.map((a) => (
              <option key={a.id} value={a.id}>{`${a.id} ${a.name} (${a.progress}%)`}</option>
            ))}
          </select>
        </label>
        <label className="pg-flabel">
          <span>공종 · 촬영자 (선택)</span>
          <input value={trade} disabled={busy} placeholder="예: 골조팀 박반장" onChange={(e) => setTrade(e.target.value)} />
        </label>
        <label className="pg-flabel">
          <span>사진 촬영 / 파일 첨부</span>
          <input type="file" accept="image/*" capture="environment" disabled={busy} onChange={(e) => void handleFile(e)} />
          {tooBig && <span role="alert" className="pg-risk-line">{PHOTO_TOO_BIG}</span>}
        </label>
        <label className="pg-flabel">
          <span>현장 소견 · 판독 참고 메모</span>
          <input value={note} disabled={busy} placeholder="예: 1층 철근 배근 완료, 거푸집 조립 중" onChange={(e) => setNote(e.target.value)} />
        </label>
      </div>
      <div className="pg-fcard-foot">
        {SAMPLE_PHOTOS.map((s) => (
          <Button
            key={s.key}
            disabled={busy || !activityId}
            onClick={() => void onUpload({ activity_id: activityId, trade, photo_name: s.file, note: note || s.note })}
          >
            {s.label}
          </Button>
        ))}
        <span className="sch-gap" />
        <Button
          variant="primary"
          disabled={busy || !activityId || !photoName}
          onClick={() =>
            void onUpload({ activity_id: activityId, trade, photo_name: photoName, photo_data_url: dataUrl, note }).then(() => {
              setPhotoName('');
              setDataUrl(undefined);
              setNote('');
            })
          }
        >
          AI 사진 판독 실행
        </Button>
      </div>
    </section>
  );
}

function PhotoCard({ item, busy, onApply }: { item: FieldItem; busy: boolean; onApply(): Promise<void> }) {
  const p = item.payload_json || {};
  // 판독하지 않은 사진(사진 없음·모델 호출 실패): 진도 숫자를 보이지 않고 까닭만 보이며 상신할 수 없다(F1).
  const unread = item.response_choice === 'unread';
  const aiProgress = typeof p.ai_progress === 'number' ? p.ai_progress : (item.reported_progress ?? 0);
  const aiReason = typeof p.ai_reason === 'string' ? p.ai_reason : typeof p.ai_stage === 'string' ? p.ai_stage : item.response_note;
  const risks = Array.isArray(p.ai_risks) ? (p.ai_risks as string[]) : [];
  const tag = typeof p.evidence_tag === 'string' ? p.evidence_tag : `#${item.activity_id}`;
  const dataUrl = typeof p.photo_data_url === 'string' ? p.photo_data_url : null;

  return (
    <article className="pg-fcard" aria-label={item.title}>
      <div className="pg-fcard-head">
        <div>
          <div className="pg-fcard-trade">{`${item.trade} · 증빙 ${tag}`}</div>
          <h4 className="pg-fcard-title">{item.title}</h4>
        </div>
        <StatusBadge item={item} />
      </div>
      <div className="pg-photo-frame">
        {dataUrl ? <img src={dataUrl} alt={String(p.photo_name ?? item.title)} className="pg-photo-img" /> : <SamplePhotoGraphic kindKey={String(p.sample_key ?? 'rebar')} />}
      </div>
      {unread ? (
        <div className="pg-ai-result">
          <p className="pg-risk-line">{`판독하지 않음 — ${String(p.unread_reason ?? '')}`}</p>
        </div>
      ) : (
        <div className="pg-ai-result">
          <div className="pg-ai-bar-head">
            <span>AI 추정 진도율</span>
            <b>{`${aiProgress}%`}</b>
          </div>
          <div className="pg-ai-bar" role="progressbar" aria-valuenow={aiProgress} aria-valuemin={0} aria-valuemax={100}>
            <span style={{ width: `${aiProgress}%` }} />
          </div>
          <p className="pg-muted">{`판독 근거: ${aiReason}`}</p>
          {risks.map((r) => (
            <p key={r} className="pg-risk-line">{`⚠ 리스크 감지: ${r}`}</p>
          ))}
        </div>
      )}
      <div className="pg-fcard-foot">
        <span className="pg-muted">{`${String(p.photo_name ?? 'site_photo.jpg')} · ${String(p.captured_at ?? '금일')}`}</span>
        <span className="sch-gap" />
        <Button variant="primary" disabled={busy || item.approval_id !== null || unread} onClick={() => void onApply()}>
          {item.approval_id !== null ? `승인함 #${item.approval_id} 확정됨` : '승인함 상신 · 증빙 확정'}
        </Button>
      </div>
    </article>
  );
}

function PollCard({
  item,
  busy,
  onSubmitPoll,
}: {
  item: FieldItem;
  busy: boolean;
  onSubmitPoll(choice: string, note: string): Promise<void>;
}) {
  const [choice, setChoice] = useState<string | null>(item.status === 'pending' ? null : (item.response_choice ?? 'feasible'));
  const [note, setNote] = useState(item.response_note);
  return (
    <article className="pg-fcard" aria-label={item.title}>
      <div className="pg-fcard-head">
        <div>
          <div className="pg-fcard-trade">{item.trade}</div>
          <h4 className="pg-fcard-title">{item.title}</h4>
        </div>
        <StatusBadge item={item} />
      </div>
      <p className="pg-muted">{item.prompt_text}</p>
      <div className="pg-choice-row" role="group" aria-label="실현 가능성 선택">
        {[
          ['feasible', '수행 가능'],
          ['conditional', '조건부 가능'],
          ['infeasible', '수행 불가'],
        ].map(([val, label]) => (
          <button key={val} type="button" className="pg-choice-btn" aria-pressed={choice === val} disabled={busy} onClick={() => setChoice(val)}>
            {label}
          </button>
        ))}
      </div>
      <input
        type="text"
        className="pg-finput-text"
        placeholder="현장 조건 또는 불가 사유 (예: 야간 소음 민원, 인력 보강 시 가능)"
        aria-label="현장 의견 사유"
        value={note}
        disabled={busy}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="pg-fcard-foot">
        <Button
          variant="primary"
          className="pg-submit-one"
          disabled={busy || choice === null}
          onClick={() => choice !== null && void onSubmitPoll(choice, note)}
        >
          {item.approval_id !== null ? `회신·상신 완료 (#${item.approval_id})` : '의견 회신 완료'}
        </Button>
      </div>
    </article>
  );
}

function HandoffCard({
  item,
  busy,
  onSave,
}: {
  item: FieldItem;
  busy: boolean;
  onSave(body: { pred_handover_ok: boolean; material: boolean; equipment: boolean; workforce: boolean; response_note: string }): Promise<void>;
}) {
  const p = item.payload_json || {};
  const initList = (p.checklist as Record<string, boolean> | undefined) ?? { material: true, equipment: false, workforce: true };
  const [predOk, setPredOk] = useState(Boolean(p.pred_handover_ok ?? true));
  const [material, setMaterial] = useState(Boolean(initList.material));
  const [equipment, setEquipment] = useState(Boolean(initList.equipment));
  const [workforce, setWorkforce] = useState(Boolean(initList.workforce));
  const [note, setNote] = useState(item.response_note);
  const open = useWindows((s) => s.open);

  const allReady = predOk && material && equipment && workforce;

  return (
    <article className="pg-fcard" aria-label={item.title}>
      <div className="pg-fcard-head">
        <div>
          <div className="pg-fcard-trade">{`${item.trade} · 착수 D-${String(p.days_left ?? 3)}`}</div>
          <h4 className="pg-fcard-title">{item.title}</h4>
        </div>
        <StatusBadge item={item} />
      </div>
      <p className="pg-muted">{item.prompt_text}</p>
      <div className="pg-handoff-grid">
        <label className="pg-fcheck">
          <input type="checkbox" checked={predOk} disabled={busy} onChange={(e) => setPredOk(e.target.checked)} />
          <span>선행 작업면 정시 인계 가능</span>
        </label>
        <label className="pg-fcheck">
          <input type="checkbox" checked={material} disabled={busy} onChange={(e) => setMaterial(e.target.checked)} />
          <span>자재 반입 완료</span>
        </label>
        <label className="pg-fcheck">
          <input type="checkbox" checked={equipment} disabled={busy} onChange={(e) => setEquipment(e.target.checked)} />
          <span>장비·양중 확보</span>
        </label>
        <label className="pg-fcheck">
          <input type="checkbox" checked={workforce} disabled={busy} onChange={(e) => setWorkforce(e.target.checked)} />
          <span>투입 인력 배치</span>
        </label>
      </div>
      <input
        type="text"
        className="pg-finput-text"
        placeholder="인계·투입 특이사항"
        aria-label="핸드오프 메모"
        value={note}
        disabled={busy}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="pg-fcard-foot">
        <Button disabled={busy} onClick={() => void onSave({ pred_handover_ok: predOk, material, equipment, workforce, response_note: note })}>
          점검 저장
        </Button>
        {!allReady && (
          <Button
            variant="primary"
            onClick={() =>
              void open('chat', {
                ask: `${item.activity_id} ${item.activity_name} 착수 3일 전 핸드오프 미준비(${note || '장비/자재 대기'})에 대한 선제 대안과 병행 일정을 검토해 줘.`,
              })
            }
          >
            에이전트에게 선제 대안 요청
          </Button>
        )}
      </div>
    </article>
  );
}

export default function FieldHub({ scheduleId }: { scheduleId: number }) {
  const role = useSession((s) => s.session?.user.role ?? 'user');
  const device = useActiveDevice();
  const isSimpleField = role === 'field' || device === 'phone';
  const waits = role === 'field' ? FIELD_WAITS : undefined; // 현장 관리자에게만 — 다른 역할은 바로 반영될 수 있다
  const [data, setData] = useState<FieldData | null>(null);
  const [tab, setTab] = useState<FieldKind>('checkin');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pollOpen, setPollOpen] = useState(false);
  const [pollAct, setPollAct] = useState('');
  // 의견 조회 작성 칸은 비워 두고 예시는 자리표시로만 — 기본 문구가 그대로 발송되지 않게(F7).
  const [pollTitle, setPollTitle] = useState('');
  const [pollPrompt, setPollPrompt] = useState('');

  useEffect(() => {
    let live = true;
    fieldApi
      .list(scheduleId)
      .then((d) => {
        if (!live) return;
        setData(d);
        setPollAct((cur) => cur || d.activities[0]?.id || '');
        setError(null);
      })
      .catch((e) => live && setError(e instanceof ApiError ? e.message : '현장 협업 데이터를 읽을 수 없습니다.'));
    return () => {
      live = false;
    };
  }, [scheduleId]);

  /** done: 성공하면 보일 한 줄(예: 저장했습니다.). */
  async function run(task: () => Promise<FieldData>, done?: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await task();
      setData(next);
      if (done ?? next.notice) setNotice(done ?? next.notice ?? null); // 서버 알림(일괄 발송에서 건너뛴 것 등)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '요청을 처리하지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  if (error && !data) return <p className="pg-empty" role="alert">{error}</p>;
  if (!data) return <p className="pg-empty">현장 모바일 협업 현황을 불러오는 중…</p>;

  const s = data.summary;
  const shown = data.items.filter((i) => i.kind === tab);

  return (
    <div className="pg-field-wrap" role="region" aria-label="현장 모바일 협업 허브">
      {isSimpleField ? (
        <div className="pg-field-simple-bar" role="status" aria-label="오늘 현장 보고 요약">
          <span>{`체크인 ${s.checkin_responded}/${s.checkin_total}`}</span>
          <span>{`사진 판독 ${s.photo_total}건`}</span>
          <span>{`핸드오프 ${s.handoff_ready}/${s.handoff_total}`}</span>
        </div>
      ) : (
        <div className="pg-field-kpis">
          <div className="pg-fkpi">
            <span className="pg-muted">일일 체크인 응답률</span>
            <b>{`${s.checkin_responded} / ${s.checkin_total}`}</b>
          </div>
          <div className="pg-fkpi">
            <span className="pg-muted">AI 사진 판독 증빙</span>
            <b>{`${s.photo_total}건`}</b>
          </div>
          <div className="pg-fkpi">
            <span className="pg-muted">만회안 공종 의견</span>
            <b>{`가능 ${s.poll_feasible} · 조건부 ${s.poll_conditional} · 불가 ${s.poll_infeasible}`}</b>
          </div>
          <div className="pg-fkpi">
            <span className="pg-muted">D-3 핸드오프 준비</span>
            <b>{`${s.handoff_ready} / ${s.handoff_total} 준비 완료`}</b>
          </div>
        </div>
      )}

      <div className="pg-field-subbar">
        <div role="tablist" aria-label="현장 협업 기능" className="pg-seg">
          {TABS.map((t) => (
            <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </div>
        <span className="sch-gap" />
        {!isSimpleField && tab === 'checkin' && (
          <Button variant="primary" disabled={busy} onClick={() => void run(() => fieldApi.dispatchCheckins(scheduleId))}>
            관리자 에이전트: 오늘의 체크인 일괄 발송
          </Button>
        )}
        {!isSimpleField && tab === 'poll' && (
          <Button variant="primary" disabled={busy} onClick={() => setPollOpen((o) => !o)}>
            {pollOpen ? '작성 닫기' : '+ 공종 담당자 의견 조회 발송'}
          </Button>
        )}
      </div>

      {error && <p className="pg-risk-line" role="alert">{error}</p>}
      {notice && <p className="pg-muted" role="status">{notice}</p>}

      {tab === 'photo' && (
        <PhotoUploader activities={data.activities} busy={busy} onUpload={(body) => run(() => fieldApi.uploadPhoto(scheduleId, body))} />
      )}

      {tab === 'poll' && pollOpen && (
        <section className="pg-card pg-fbox" aria-label="새 만회안 의견 조회 발송">
          <div className="pg-fgrid-form">
            <label className="pg-flabel">
              <span>대상 액티비티</span>
              <select value={pollAct} onChange={(e) => setPollAct(e.target.value)}>
                {data.activities.map((a) => (
                  <option key={a.id} value={a.id}>{`${a.id} ${a.name}`}</option>
                ))}
              </select>
            </label>
            <label className="pg-flabel">
              <span>검토 중인 만회안 제목</span>
              <input value={pollTitle} placeholder="예: 공종 주말·병행 단축 2일안" onChange={(e) => setPollTitle(e.target.value)} />
            </label>
          </div>
          <label className="pg-flabel">
            <span>담당자에게 보낼 질문</span>
            <input
              value={pollPrompt}
              placeholder="예: 일정 만회를 위해 선행 공종 완료 즉시 야간/주말 병행 투입이 가능한지 의견을 주세요."
              onChange={(e) => setPollPrompt(e.target.value)}
            />
          </label>
          <div className="pg-fcard-foot">
            <Button
              variant="primary"
              disabled={busy || !pollAct || !pollTitle.trim() || !pollPrompt.trim()}
              onClick={() =>
                void run(() =>
                  fieldApi.createPoll(scheduleId, {
                    activity_id: pollAct,
                    scenario_title: pollTitle,
                    target_delta_days: -2,
                    prompt_text: pollPrompt,
                  }),
                ).then(() => setPollOpen(false))
              }
            >
              공종 담당자에게 의견 조회 발송
            </Button>
          </div>
        </section>
      )}

      <div className="pg-field-grid">
        {shown.length === 0 && <p className="pg-muted">등록된 항목이 없습니다.</p>}
        {shown.map((item) => {
          if (item.kind === 'checkin') {
            return (
              <CheckinCard
                key={item.id}
                item={item}
                busy={busy}
                onSave={(choice, prog, rd, note) =>
                  run(
                    () =>
                      fieldApi.respond(scheduleId, item.id, {
                        response_choice: choice,
                        reported_progress: prog ?? undefined,
                        reported_rd: rd ?? undefined,
                        response_note: note,
                      }),
                    '저장했습니다.',
                  )
                }
                onSubmitReport={(choice, prog, rd, note) =>
                  run(async () => {
                    const saved = await fieldApi.respond(scheduleId, item.id, {
                      response_choice: choice,
                      reported_progress: prog ?? undefined,
                      reported_rd: rd ?? undefined,
                      response_note: note,
                    });
                    if (saved.items.find((x) => x.id === item.id)?.approval_id !== null) return saved;
                    return fieldApi.apply(scheduleId, item.id);
                  }, waits)
                }
              />
            );
          }
          if (item.kind === 'photo') {
            return <PhotoCard key={item.id} item={item} busy={busy} onApply={() => run(() => fieldApi.apply(scheduleId, item.id), waits)} />;
          }
          if (item.kind === 'poll') {
            return (
              <PollCard
                key={item.id}
                item={item}
                busy={busy}
                onSubmitPoll={(choice, note) =>
                  run(async () => {
                    const saved = await fieldApi.respond(scheduleId, item.id, { response_choice: choice, response_note: note });
                    const updated = saved.items.find((x) => x.id === item.id);
                    if (!note.trim() || !updated || updated.approval_id !== null) return saved;
                    return fieldApi.apply(scheduleId, item.id);
                  }, waits)
                }
              />
            );
          }
          return (
            <HandoffCard key={item.id} item={item} busy={busy} onSave={(body) => run(() => fieldApi.updateHandoff(scheduleId, item.id, body), '저장했습니다.')} />
          );
        })}
      </div>
    </div>
  );
}
