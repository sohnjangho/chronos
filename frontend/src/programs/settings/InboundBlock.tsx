// 「받는 범위 · 차단」(Task 85) — 설정 → 알림 연결 카드의 아래 칸에 들어가는 한 묶음. NotifyPolicy 의 「받는 범위 · 차단」 자리 글을
// 이것으로 바꿔 단다: <InboundBlock conn={conn} locked={locked} onChanged={onChanged} />.
// 받는 범위(받지 않음 | 주소록에 있는 번호만 | 모두 받기 — 전화와 문자에 같이)는 바꿀 때 확인 창, 사람 연결 번호는 한 칸(지금 번호는 가린
// 꼴만 보이고 칸은 늘 비어 있다), 아래에 차단 목록. 쓰기는 기존 PATCH /api/notify/connections/{id} 하나(inbound_mode · handoff_number).
import { useId, useState } from 'react';
import { api } from '../../shared/api';
import Button from '../../shared/ui/Button';
import BlockedNumbers from './BlockedNumbers';
import type { LlmError } from './model';
import type { NotifyConnection, NotifySaved } from './notifyApi';
import { ErrorLine, toProblem } from './parts';

type InboundMode = NotifyConnection['inbound_mode'];
type InboundPatch = { inbound_mode: InboundMode } | { handoff_number: string | null };

export const BOTH = '걸려 오는 전화와 들어오는 문자에 같이 적용됩니다.';
export const INBOUND_MODES: { id: InboundMode; label: string; hint: string }[] = [
  { id: 'off', label: '받지 않음', hint: '응대하지 않고 기록만 남깁니다.' },
  { id: 'known', label: '주소록에 있는 번호만', hint: '주소록에 있는 사람에게만 응대합니다. 모르는 번호는 기록만 남깁니다.' },
  { id: 'all', label: '모두 받기', hint: '모르는 번호도 받습니다. 모르는 번호는 메모만 남깁니다(일정은 알려 주지 않습니다).' },
];
const modeOf = (id: InboundMode) => INBOUND_MODES.find((m) => m.id === id) ?? INBOUND_MODES[0];

export default function InboundBlock({ conn, locked = false, onChanged }: {
  conn: NotifyConnection;
  /** 카드의 진단·시험이 도는 동안 참 — 모든 칸을 잠근다. */
  locked?: boolean;
  onChanged(): void;
}) {
  const name = useId();
  const [asking, setAsking] = useState<InboundMode | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<{ part: 'range' | 'handoff'; error: LlmError } | null>(null);
  const [number, setNumber] = useState('');
  const off = busy || locked;

  /** 한 번만 보낸다. 성공·실패 모두 목록을 다시 읽는다. */
  async function patch(part: 'range' | 'handoff', body: InboundPatch): Promise<boolean> {
    setBusy(true);
    setProblem(null);
    try {
      await api<NotifySaved>(`/api/notify/connections/${conn.id}`, { method: 'PATCH', body: JSON.stringify(body) });
      return true;
    } catch (e) {
      setProblem({ part, error: toProblem(e) });
      return false;
    } finally {
      setBusy(false);
      setAsking(null);
      onChanged();
    }
  }
  const saveNumber = async () => {
    if (await patch('handoff', { handoff_number: number.trim() })) setNumber('');
  };
  const shown = asking ?? conn.inbound_mode;

  return (
    <section className="st-nt-group" aria-label="받는 범위 · 차단">
      <h4>받는 범위 · 차단</h4>
      <div className="st-nt-seg" role="radiogroup" aria-label="받는 범위">
        {INBOUND_MODES.map((m) => (
          <label key={m.id} className="st-nt-seg-item">
            <input type="radio" name={name} value={m.id} checked={shown === m.id} disabled={off} onChange={() => setAsking(m.id === conn.inbound_mode ? null : m.id)} />
            {m.label}
          </label>
        ))}
      </div>
      <p className="st-muted">{`${modeOf(conn.inbound_mode).hint} ${BOTH} 시험 모드에서는 허용 번호만 받습니다.`}</p>
      {asking && (
        // 화면 안 확인 칸(NotifyPolicy 의 확인 칸과 같은 꼴 — 그 파일을 불러오면 서로 부르게 되어 따로 둔다).
        <div className="st-confirm" role="group" aria-label="받는 범위 바꾸기 확인">
          <p className="st-wrap">{`받는 범위를 「${modeOf(asking).label}」(으)로 바꿉니다. ${BOTH} ${modeOf(asking).hint}`}</p>
          <div className="st-actions">
            <span className="st-gap" />
            <Button onClick={() => setAsking(null)}>취소</Button>
            <Button variant="danger" disabled={off} onClick={() => void patch('range', { inbound_mode: asking })}>
              바꾸기
            </Button>
          </div>
        </div>
      )}
      <ErrorLine error={problem?.part === 'range' ? problem.error : null} />

      <div className="st-nt-addrow">
        <span className="st-nt-perm-label">사람 연결 번호</span>
        <div className="st-nt-add">
          <input
            type="tel"
            className="st-search"
            aria-label="사람 연결 번호"
            aria-invalid={problem?.part === 'handoff' ? true : undefined}
            placeholder="010-0000-0000"
            autoComplete="off"
            maxLength={40}
            value={number}
            disabled={off}
            onChange={(e) => setNumber(e.target.value)}
          />
          <Button disabled={off || number.trim() === ''} onClick={() => void saveNumber()}>
            저장
          </Button>
          <Button disabled={off || conn.handoff_number_masked === null} onClick={() => void patch('handoff', { handoff_number: null })}>
            비우기
          </Button>
        </div>
        <p className="st-muted">
          <span>{conn.handoff_number_masked ? `지금: ${conn.handoff_number_masked}` : '비어 있음'}</span>
          {' — 상대가 사람 담당자를 찾을 때 넘겨 줄 번호입니다.'}
        </p>
        <ErrorLine error={problem?.part === 'handoff' ? problem.error : null} />
      </div>

      <BlockedNumbers locked={locked} />
    </section>
  );
}
