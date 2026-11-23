import { useEffect, useState } from 'react';
import { ApiError } from '../../shared/api';
import Badge, { type Tone } from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import Table, { type Column } from '../../shared/ui/Table';
import { checkedText, type LlmError } from './model';
import { kakaoApi, type KakaoState, type KakaoTemplate, type KakaoTemplateStatus, type NotifyConnection } from './notifyApi';
import { ErrorLine, toProblem } from './parts';

/** 맨 위 띠 — 늘 보인다([PM 11-23] 카카오톡은 연결만 하고 쓰지 않는다). */
export const KAKAO_BAND = '카카오톡은 아직 쓰지 않습니다 — 채널·문안이 승인되면 켤 수 있습니다. 지금은 모두 문자로 나갑니다';
/** 서버가 까닭을 주지 않았을 때 잠긴 [채널·문안 다시 읽기] 옆 글. */
const NO_PATH = '목록을 읽는 길을 확인하지 못했습니다';
const NO_REPLY_IN = '카카오톡으로 온 답은 받을 수 없습니다. 답은 문자로 받습니다';
const CUT = '일부만 읽었습니다 — 읽는 상한에 걸려 뒤쪽 채널·문안은 빠졌을 수 있습니다. 그래서 목록에 없는 문안도 휴면으로 바꾸지 않았습니다.';

/** 「쓰는 곳」 이름(docs/design/kakao-templates-draft.md 의 문안 여섯). 서버에 다른 이름이 있으면 그것도 고르기에 넣는다. */
const USES = ['체크인 요청', '일정 변경 알림', 'D-3 준비 확인', '승인 대기 알림', '회신 전화 예약', '수신 거부 확인'];

const STEPS = [
  '① 카카오톡 비즈니스 채널을 만듭니다 — 사업자 인증이 필요할 수 있습니다.',
  '② 한국AI통신 콘솔에서 채널을 연결합니다(채널 검색용 ID와 채널 관리자 휴대전화로 온 인증번호).',
  '③ 알림톡 문안을 등록하고 카카오 검수를 받습니다 — 승인 전에는 보낼 수 없습니다.',
  '④ 여기서 [채널·문안 다시 읽기]를 누르고, 승인된 문안을 쓰는 곳에 잇습니다.',
];

const STATUS: Record<KakaoTemplateStatus, { tone: Tone; text: string }> = {
  approved: { tone: 'success', text: '승인' },
  reviewing: { tone: 'warning', text: '검수 중' },
  rejected: { tone: 'danger', text: '반려' },
  dormant: { tone: 'neutral', text: '휴면' },
};

const CHANNEL_STATUS: Record<string, { tone: Tone; text: string }> = {
  connected: { tone: 'success', text: '연결됨' },
  unknown: { tone: 'neutral', text: '상태 모름' },
};

/** 상태 읽기 · 다시 읽기(sync) · 쓰는 곳 잇기. 발신번호가 바뀌면 reply_line 이 바뀔 수 있어 다시 읽는다. */
function useKakao(conn: NotifyConnection) {
  const [data, setData] = useState<KakaoState | null>(null);
  const [error, setError] = useState<LlmError | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<LlmError | null>(null);
  const [cut, setCut] = useState(false);
  const [saving, setSaving] = useState<number | null>(null);
  const [rowError, setRowError] = useState<LlmError | null>(null);
  useEffect(() => {
    let live = true;
    kakaoApi
      .get(conn.id)
      .then((d) => live && (setData(d), setError(null)))
      .catch((e) => live && setError(toProblem(e)));
    return () => {
      live = false;
    };
  }, [conn.id, conn.sender_number_masked]);

  async function sync() {
    setSyncing(true);
    setSyncError(null);
    setCut(false);
    try {
      const { truncated, ...state } = await kakaoApi.sync(conn.id);
      setData(state);
      setCut(truncated);
    } catch (e) {
      // 501 = 목록 읽는 길이 아직 확인되지 않음: 오류가 아니라 잠금 — 서버 글을 까닭으로 보인다.
      if (e instanceof ApiError && e.code === 'kakao_listing_unconfirmed') setData((d) => d && { ...d, available: false, reason: e.message });
      else setSyncError(toProblem(e));
    } finally {
      setSyncing(false);
    }
  }

  async function setUse(t: KakaoTemplate, use: string | null) {
    setSaving(t.id);
    setRowError(null);
    try {
      const saved = await kakaoApi.setUse(conn.id, t.id, use);
      setData((d) => d && { ...d, templates: d.templates.map((x) => (x.id === saved.id ? saved : x)) });
    } catch (e) {
      setRowError(toProblem(e));
    } finally {
      setSaving(null);
    }
  }
  return { data, error, syncing, syncError, cut, saving, rowError, sync, setUse };
}

function UsePicker({ t, disabled, onPick }: { t: KakaoTemplate; disabled: boolean; onPick(use: string | null): void }) {
  const options = t.use && !USES.includes(t.use) ? [...USES, t.use] : USES;
  return (
    <div className="ui-field">
      <select aria-label="쓰는 곳" value={t.use ?? ''} disabled={disabled} onChange={(e) => onPick(e.target.value || null)}>
        <option value="">잇지 않음</option>
        {options.map((u) => (
          <option key={u} value={u}>
            {u}
          </option>
        ))}
      </select>
    </div>
  );
}

/** 문안은 두 줄까지 보이고, 전문·변수·문자 대신 보낼 글은 접어서. 제공사 id 는 맨 아래 작은 글. */
function Body({ t }: { t: KakaoTemplate }) {
  return (
    <div className="st-kk-cell">
      <div className="st-kk-body">{t.body}</div>
      <details className="st-kk-more">
        <summary>전문 보기</summary>
        <p className="st-kk-whole" aria-label="문안 전문">
          {t.body}
        </p>
        {t.variables.length > 0 && <p className="st-muted">{`변수 ${t.variables.map((v) => `#{${v}}`).join(' ')}`}</p>}
        <p className="st-muted st-wrap">{t.fallback_body ? `문자 대신 보낼 글 — ${t.fallback_body}` : '문자 대신 보낼 글 없음'}</p>
        <p className="st-kk-ids">{`문안 번호 ${t.provider_template_id} · 채널 ${t.channel}`}</p>
      </details>
    </div>
  );
}

function State({ t }: { t: KakaoTemplate }) {
  const s = STATUS[t.status] ?? { tone: 'neutral' as Tone, text: t.status };
  return (
    <div className="st-kk-state">
      <Badge tone={s.tone}>{s.text}</Badge>
      {!t.reply_line && <Badge tone="warning">문자 회신 안내 없음</Badge>}
    </div>
  );
}

function Channels({ data }: { data: KakaoState }) {
  if (data.channels.length === 0) return <p className="st-muted">연결된 채널 없음</p>;
  return (
    <ul className="st-kk-channels" aria-label="연결된 채널">
      {data.channels.map((c) => {
        const s = CHANNEL_STATUS[c.status] ?? { tone: 'neutral' as Tone, text: c.status };
        return (
          <li key={c.id}>
            <span className="st-wrap">{c.name}</span>
            <Badge tone={s.tone}>{s.text}</Badge>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * 설정 → 알림 연결 카드 안 「카카오톡 채널과 문안」 묶음(Task 102, Task 101 계약). 읽기 전용 상태 표 — 보내기·켜기·준비 표시는 없다.
 * locked = 같은 카드의 진단·확인 창 등이 도는 중. onBusy = 다시 읽기가 도는지(카드가 다른 단추를 잠근다).
 */
export default function KakaoBlock({ conn, locked, onBusy }: { conn: NotifyConnection; locked: boolean; onBusy(on: boolean): void }) {
  const k = useKakao(conn);
  const { data } = k;
  useEffect(() => onBusy(k.syncing), [k.syncing, onBusy]);
  const off = locked || k.syncing;
  const columns: Column<KakaoTemplate>[] = [
    { key: 'use', header: '쓰는 곳', width: 168, render: (t) => <UsePicker t={t} disabled={off || k.saving !== null} onPick={(u) => void k.setUse(t, u)} /> },
    { key: 'body', header: '문안', render: (t) => <Body t={t} /> },
    { key: 'status', header: '상태', width: 132, render: (t) => <State t={t} /> },
  ];
  return (
    <section className="st-nt-group st-kk" aria-label="카카오톡 채널과 문안">
      <div className="st-vc-head">
        <h4>카카오톡 채널과 문안</h4>
        {data && <Badge tone={data.ready ? 'info' : 'neutral'}>{data.ready ? '준비됨' : '준비 안 됨'}</Badge>}
        {data && <span className="st-muted">{`마지막으로 읽은 때 — ${data.synced_at ? checkedText(data.synced_at, null) : '아직 읽은 적 없음'}`}</span>}
      </div>
      <p className="st-kk-band">{KAKAO_BAND}</p>
      {data ? <Channels data={data} /> : !k.error && <p className="st-muted">불러오는 중…</p>}
      <ErrorLine error={k.error} />
      <div className="st-kk-sync">
        <Button disabled={!data?.available || off} onClick={() => void k.sync()}>
          {k.syncing ? '읽는 중…' : '채널·문안 다시 읽기'}
        </Button>
        {data && !data.available && <span className="st-muted st-wrap">{data.reason ?? NO_PATH}</span>}
      </div>
      {k.cut && <p className="st-warn">{CUT}</p>}
      <ErrorLine error={k.syncError} />
      {data && data.templates.length > 0 && (
        <div className="st-kk-table">
          <Table columns={columns} rows={data.templates} rowKey={(t) => String(t.id)} label="카카오톡 문안" />
        </div>
      )}
      <ErrorLine error={k.rowError} />
      <b className="st-muted">카카오톡을 켜기까지 준비 차례</b>
      <ol className="st-kk-steps" aria-label="준비 차례">
        {STEPS.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ol>
      <p className="st-muted">{NO_REPLY_IN}</p>
    </section>
  );
}
