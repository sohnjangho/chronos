import { useState } from 'react';
import Button from '../../shared/ui/Button';
import type { Account, AccountPresence, DeviceKind, DevicePresence, LlmError } from './model';
import { ErrorLine, toProblem } from './parts';
import { settingsApi } from './settingsApi';
import './presence.css';

const KIND_LABELS: Record<DeviceKind, string> = { desktop: '데스크톱', tablet: '태블릿', phone: '휴대폰' };
const SEARCH_FROM = 7; // 계정이 6개를 넘으면 찾기 칸
const CONFIRM = '이 기기에서 로그아웃할까요? 그 기기는 다음 동작 때 로그인 화면으로 갑니다';
const OWN_WARNING = '지금 쓰고 있는 이 기기입니다. 로그아웃하면 이 화면도 바로 로그인 화면으로 갑니다.';

const two = (n: number) => String(n).padStart(2, '0');

/** 마지막 접속 시각: 「오늘 14:12」·「어제 08:05」·「11월 2일 07:30」(올해가 아니면 연도도). 이 브라우저의 시간대. */
export function lastSeenText(iso: string, now = new Date()): string {
  const t = new Date(iso);
  const time = `${two(t.getHours())}:${two(t.getMinutes())}`;
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diff = Math.round((day(now) - day(t)) / 86_400_000);
  if (diff === 0) return `오늘 ${time}`;
  if (diff === 1) return `어제 ${time}`;
  const date = `${t.getMonth() + 1}월 ${t.getDate()}일`;
  return t.getFullYear() === now.getFullYear() ? `${date} ${time}` : `${t.getFullYear()}년 ${date} ${time}`;
}

/** 계정 표의 「접속」 칸. 목록을 아직 못 읽었으면 —. */
export function PresenceCell({ presence, loaded }: { presence: AccountPresence | undefined; loaded: boolean }) {
  if (!loaded) return <span className="st-muted">—</span>;
  if (!presence) return <span className="st-muted">접속 기록 없음</span>;
  return <PresenceText online={presence.online} lastSeen={presence.last_seen_at} />;
}

function PresenceText({ online, lastSeen }: { online: boolean; lastSeen: string }) {
  if (online) {
    return (
      <span className="st-presence">
        <i className="st-dot st-dot-on" aria-hidden="true" />
        <span>접속 중</span>
      </span>
    );
  }
  const text = `마지막 접속 ${lastSeenText(lastSeen)}`;
  return (
    <span className="st-presence st-muted" title={text}>
      <i className="st-dot" aria-hidden="true" />
      <span>{text}</span>
    </span>
  );
}

function DeviceLine({ device, onChanged }: { device: DevicePresence; onChanged(): void }) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<LlmError | null>(null);
  async function logout() {
    setBusy(true);
    setError(null);
    try {
      await settingsApi.logoutDevice(device.id, device.current);
      setAsking(false);
      onChanged();
    } catch (e) {
      setError(toProblem(e));
    } finally {
      setBusy(false);
    }
  }
  const label = `${KIND_LABELS[device.kind] ?? device.kind} · ${device.browser} · ${device.os}`;
  return (
    <li className="st-device">
      <div className="st-device-row">
        <span className="st-device-name" title={label}>
          {label}
        </span>
        {device.current && <span className="st-device-tag">지금 이 기기</span>}
        {device.revoked ? (
          <span className="st-muted">로그아웃됨</span>
        ) : (
          <PresenceText online={device.online} lastSeen={device.last_seen_at} />
        )}
        <span className="st-gap" />
        {!device.revoked && !asking && (
          <Button className="st-danger-text" onClick={() => setAsking(true)}>
            이 기기 로그아웃
          </Button>
        )}
      </div>
      {asking && (
        <div className="st-confirm st-device-confirm">
          <p>{CONFIRM}</p>
          {device.current && <p className="st-device-own">{OWN_WARNING}</p>}
          <div className="st-actions">
            <span className="st-gap" />
            <Button disabled={busy} onClick={() => setAsking(false)}>
              취소
            </Button>
            <Button variant="danger" disabled={busy} onClick={() => void logout()}>
              로그아웃
            </Button>
          </div>
        </div>
      )}
      <ErrorLine error={error} />
    </li>
  );
}

function AccountGroup({ account, presence, onChanged }: { account: Account; presence: AccountPresence; onChanged(): void }) {
  const [open, setOpen] = useState(false);
  const title = `${account.name} (${account.login_id})`;
  return (
    <div role="group" aria-label={title} className="st-device-group">
      <button type="button" className="st-device-head" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="st-device-caret" aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>
        <b className="st-device-title" title={title}>
          {title}
        </b>
        <span className="st-muted">{`기기 ${presence.devices.length}대`}</span>
        <span className="st-gap" />
        <PresenceText online={presence.online} lastSeen={presence.last_seen_at} />
      </button>
      {open && (
        <ul className="st-device-list">
          {presence.devices.map((d) => (
            <DeviceLine key={d.id} device={d} onChanged={onChanged} />
          ))}
        </ul>
      )}
    </div>
  );
}

/** 「접속 기기」: 계정별로 묶은 기기 목록(펼쳐 보기)과 기기 로그아웃. 30일 넘게 신호가 없는 기기는 서버가 빼고 준다. */
export default function AccountDevices({
  accounts,
  presence,
  error,
  onChanged,
}: {
  accounts: Account[];
  presence: AccountPresence[] | null;
  error: LlmError | null;
  onChanged(): void;
}) {
  const [query, setQuery] = useState('');
  const byUser = new Map((presence ?? []).map((p) => [p.user_id, p]));
  const withDevices = accounts.filter((a) => byUser.has(a.id));
  const q = query.trim().toLowerCase();
  const shown = q ? withDevices.filter((a) => `${a.name} ${a.login_id}`.toLowerCase().includes(q)) : withDevices;
  return (
    <section className="st-card" aria-label="접속 기기">
      <div className="st-card-head">
        <b>접속 기기</b>
        <span className="st-muted">2분 안에 신호가 온 기기는 접속 중입니다. 잃어버린 기기는 여기서 로그아웃하세요.</span>
      </div>
      <ErrorLine error={error} />
      {accounts.length >= SEARCH_FROM && (
        <input
          type="search"
          className="st-search"
          aria-label="계정 찾기"
          placeholder="이름 또는 아이디로 찾기"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      )}
      {presence && withDevices.length === 0 && <p className="st-note">아직 접속한 기기가 없습니다.</p>}
      {withDevices.length > 0 && shown.length === 0 && <p className="st-note">찾는 계정이 없습니다.</p>}
      <div className="st-device-groups">
        {shown.map((a) => (
          <AccountGroup key={a.id} account={a} presence={byUser.get(a.id)!} onChanged={onChanged} />
        ))}
      </div>
    </section>
  );
}
